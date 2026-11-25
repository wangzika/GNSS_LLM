#!/usr/bin/env python3
"""统一报告审阅：程序核对、模型提取断言、保守过滤、争议裁定及 SFT 导出。

只读取教师原始回答，不重新生成诊断报告。默认使用已保存的验算结果；
缺少记录时请求教师提取原句，再由 Python 计算比较真假，可断点续跑。
"""
import argparse
import hashlib
import json
import re
import sys
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.industrial.common import (
    DATA, WorkflowPaths, model_input, derived_measurements, BLOCK_RE, validate,
    normalize_conclusion, STUDENT_INSTRUCTION, read_jsonl, write_json, write_jsonl,
)
from scripts.industrial.generate_teacher_reports import read_existing, read_records


JUDGE = """你是报告文字提取员，任务是忠实摘录，不是评价报告。
从report中提取所有关于当前事件的数字大小比较，quote必须逐字复制原文的连续片段，保留左右顺序。
不要摘录通用规则、风险窗口范围；只摘录当前测量值与阈值的比较。
例：原文‘温差9.5 K大于8.6 K’，填 left=9.5,op=">",right=8.6。
例：原文‘转速1372 rpm大于1380 rpm’，填 left=1372,op=">",right=1380。不要纠正原文错误。
也提取当前事件是否触发HDF/PWF/OSF的明确说法，排除该类表示triggered=false。
只输出JSON：{"comparisons":[{"quote":"逐字原文","left":9.5,"op":">","right":8.6}],"rule_claims":[{"quote":"逐字原文","rule":"HDF","triggered":false}]}。
不能提取的项目留空数组。不要输出任何修改建议或评价。"""


def judge(rec, report, args):
    payload={'model':args.model,'temperature':0,'max_tokens':1000,'response_format':{'type':'json_object'},'messages':[
        {'role':'system','content':JUDGE},
        {'role':'user','content':json.dumps({'input':model_input(rec),'computed':derived_measurements(rec),'report':report},ensure_ascii=False)}]}
    req=urllib.request.Request(args.url,data=json.dumps(payload,ensure_ascii=False).encode(),headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=180) as response:
        obj=json.load(response)
    if obj['choices'][0].get('finish_reason')!='stop':raise ValueError('审阅回复被截断')
    result=json.loads(obj['choices'][0]['message']['content'])
    if not isinstance(result.get('comparisons'),list) or not isinstance(result.get('rule_claims'),list):
        raise ValueError('提取JSON格式错误')
    return result


def numeric_issues(rec, block):
    """按键值对检查原始测量；派生量若列出，也须与重新计算值一致。"""
    issues=[]
    evidence=block.split('### 关键支撑证据链',1)[-1]
    expected={**rec['physical_features'],**{k:v for k,v in derived_measurements(rec).items() if k!='rule_checks'}}
    for key,value in expected.items():
        matches=re.findall(r'(?m)^\s*-\s*'+re.escape(key)+r'\s*[:=]\s*(-?\d+(?:\.\d+)?)',evidence)
        if not matches and key in rec['physical_features']: issues.append('缺少键值对:'+key)
        if any(abs(float(x)-value)>.11 for x in matches):issues.append('键值不一致:'+key)
    checks=derived_measurements(rec)['rule_checks']
    label=rec['ground_truth_intent']
    mapping={'Power Failure':'PWF_triggered','Heat Dissipation Failure':'HDF_triggered','Overstrain Failure':'OSF_triggered'}
    for name,key in mapping.items():
        if name in label and not checks[key]:issues.append('真实标签与可重算规则不一致:'+key)
    return issues


def inspect(rec, response, args):
    blocks=BLOCK_RE.findall(response)
    issues=[]
    if len(blocks)!=1:return {'status':'reject','issues':['代码块数量异常']}
    block=blocks[0]
    reason=validate(block,rec)
    if reason:issues.append(reason)
    issues.extend(numeric_issues(rec,block))
    if issues:return {'status':'reject','issues':issues}
    # 不为随机故障采纳确定标签，即使文字提到风险且与原标注一致。
    if any(x in rec['ground_truth_intent'] for x in ('Tool Wear Failure','Random Failure')):
        return {'status':'uncertain','issues':['仅有风险窗口，不能由观测确认随机故障；不纳入确定标签训练']}
    result=judge(rec,response,args)
    operators={'>':lambda a,b:a>b, '<':lambda a,b:a<b, '>=':lambda a,b:a>=b, '<=':lambda a,b:a<=b, '=':lambda a,b:a==b}
    comparisons=[]; flags=[]
    for item in result['comparisons']:
        quote=item.get('quote','')
        # 模型必须提供确实存在于原文的引文与其中出现的两个数字，不能凭空指控。
        if not quote or quote not in response: continue
        left=item.get('left'); right=item.get('right'); op=item.get('op')
        if not isinstance(left,(int,float)) or not isinstance(right,(int,float)) or op not in operators:continue
        nums=[float(x) for x in re.findall(r'(?<![A-Za-z_])(?<![\d.])-?\d+(?:\.\d+)?',quote)]
        if left not in nums or right not in nums:continue
        ok=operators[op](left,right)
        comparisons.append({**item,'recomputed_true':ok})
        if not ok:flags.append('比较矛盾:'+quote)
    checks=derived_measurements(rec)['rule_checks']
    claims=[]
    for item in result['rule_claims']:
        quote=item.get('quote',''); rule=item.get('rule'); state=item.get('triggered')
        if quote and quote in response and rule in ('HDF','PWF','OSF') and isinstance(state,bool):
            ok=state==checks[rule+'_triggered']
            claims.append({**item,'recomputed_consistent':ok})
            if not ok:flags.append('规则触发说法矛盾:'+quote)
    # 提取器仍可能误读语气；保留结构化引文供人工/代理复核，不以模型口头评价作结论。
    return {'status':'accept' if not flags else 'reject','issues':flags,
            'extracted_comparisons':comparisons,'extracted_rule_claims':claims,
            'review_limit':'提取模型可能漏掉未列出的矛盾，需查看审阅摘要'}


def content_flags(rec,text):
    flags=[]
    # 直接从原文匹配局部数值比较，补充模型提取可能漏掉的“未低于”等否定比较。
    comparison=re.compile(r'(-?\d+(?:\.\d+)?)\s*(?:min·Nm|rpm|分钟|K|W|min)?[，,\s]*(接近但未低于|未低于|不低于|未超过|不超过|远大于|远小于|远高于|远低于|大于|小于|高于|低于|超过)[^。；\n\d]{0,25}(-?\d+(?:\.\d+)?)')
    for match in comparison.finditer(text):
        a=float(match.group(1));b=float(match.group(3));op=match.group(2)
        if op in ('接近但未低于','未低于','不低于'):ok=a>=b
        elif op in ('未超过','不超过'):ok=a<=b
        elif op in ('大于','高于','超过','远大于','远高于'):ok=a>b
        else:ok=a<b
        if not ok:flags.append('原文直接数值比较不成立:'+match.group())
    # 现有测量不能排除独立随机故障；对这类无依据的排除句采取保守剔除。
    for sentence in re.split('[。；\n]',text):
        if any(x in sentence for x in ['RNF','Random Failure','随机系统故障','随机性故障']):
            cleaned=re.sub('不能排除|无法排除|不应排除|不排除','',sentence)
            if '排除' in cleaned:flags.append('不能从当前观测排除随机故障:'+sentence)
    wear=rec['physical_features']['tool_wear_min']
    if not 200<=wear<=240:
        for sentence in re.split('[。；\n]',text):
            if any(x in sentence for x in ['磨损','tool_wear']):
                if re.search('(?<!不)处于风险窗口内|处于200[至到～~—-]+240分钟的风险窗口内',sentence.replace(' ','')):
                    flags.append('磨损风险窗口表述与实际磨损时间不一致:'+sentence)
    return flags


def finalize(data, meta, audits, responses):
    """在同一次审阅中应用全部最终规则，仅输出一份正式训练文件。"""
    if set(audits) != {r['event_meta']['event_id'] for r in meta}:
        raise ValueError('审阅日志尚未精确覆盖全部训练事件')
    path = data.file('review_overrides.jsonl')
    overrides = {r['event_id']: r for r in read_jsonl(path)} if path.exists() else {}
    if set(overrides) - set(audits):
        raise ValueError('追加裁定含当前训练事件之外的 ID')
    rows, decisions = [], []
    for rec in meta:
        eid = rec['event_meta']['event_id']
        audit, response = audits[eid], responses[eid]
        expected = hashlib.sha256(response.encode()).hexdigest()
        if audit.get('response_sha256') != expected:
            raise ValueError(f'报告与审阅记录不匹配：{eid}')
        state, issues = audit['status'], list(audit.get('issues', []))
        if state == 'accept':
            flags = content_flags(rec, response)
            if flags:
                state = 'reject'; issues.extend(flags)
        if any(name in rec['ground_truth_intent'] for name in ['Tool Wear Failure', 'Random Failure']):
            state = 'uncertain'
            issues = ['随机故障无法从当前观测确认，不纳入确定标签训练'] + issues
        if eid in overrides:
            state, issues = overrides[eid]['status'], overrides[eid]['issues']
        if state not in ('accept', 'reject', 'uncertain', 'error'):
            raise ValueError(f'非法裁定状态：{state}')
        decisions.append({'event_id': eid, 'status': state, 'issues': issues,
                          'response_sha256': expected})
        if state == 'accept':
            rows.append({'instruction': STUDENT_INSTRUCTION,
                         'input': json.dumps(model_input(rec), ensure_ascii=False, separators=(',', ':')),
                         'output': normalize_conclusion(BLOCK_RE.findall(response)[0], rec).strip()})
    stats = {'total_train': len(meta), 'clean_count': len(rows),
             'status_counts': dict(Counter(r['status'] for r in decisions)),
             'review_method': '程序逐字段/规则核对、模型抽取文字断言后验算、保守内容过滤，代理复核争议',
             'limitations': ['文本提取可能漏检；不是外部专家认证', 'TWF样本不纳入确定故障训练',
                             '留出集未交给教师生成训练报告', '不包含正常类与多故障类，不能宣称通用故障检测能力']}
    write_jsonl(data.file('train_sft.jsonl'), rows)
    write_jsonl(data.file('final_review_decisions.jsonl'), decisions)
    write_json(data.file('review_summary.json'), stats)
    return stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=DATA)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--offline', action='store_true', help='仅使用已有审阅记录；缺记录即失败，不请求模型')
    parser.add_argument('--url', default='http://127.0.0.1:8000/v1/chat/completions')
    parser.add_argument('--model', default='Qwen/Qwen2.5-32B-Instruct')
    args = parser.parse_args()
    if args.workers < 1:
        parser.error('--workers 必须为正数')
    data = WorkflowPaths(args.data_dir)
    data.initialize()
    meta = read_records(data.input('03_review', 'train_meta.json'))
    responses = read_existing(data.input('03_review', 'teacher_responses.jsonl'), args.model)
    ids = {r['event_meta']['event_id'] for r in meta}
    if set(responses) != ids:
        raise ValueError('教师回答尚未精确覆盖训练事件，请先完成教师生成')
    audit_path = data.file('report_audit.jsonl')
    saved = {}
    if audit_path.exists():
        for row in read_jsonl(audit_path):
            if row['event_id'] in saved:
                raise ValueError('审阅日志存在重复事件')
            saved[row['event_id']] = row
    if set(saved) - ids:
        raise ValueError('审阅日志包含当前训练集之外的事件')
    for eid, row in saved.items():
        if row.get('response_sha256') != hashlib.sha256(responses[eid].encode()).hexdigest():
            raise ValueError(f'已保存审阅与报告不匹配：{eid}，请使用新的实验目录')
    pending = [r for r in meta if r['event_meta']['event_id'] not in saved]
    if args.offline and pending:
        raise ValueError(f'离线审阅缺少 {len(pending)} 条记录')
    def review(rec):
        eid = rec['event_meta']['event_id']; response = responses[eid]
        audit = inspect(rec, response, args)
        return {'event_id': eid, 'model': args.model,
                'response_sha256': hashlib.sha256(response.encode()).hexdigest(), **audit}
    with audit_path.open('a', encoding='utf-8') as stream, ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(review, rec) for rec in pending]
        for future in as_completed(futures):
            row = future.result(); saved[row['event_id']] = row
            stream.write(json.dumps(row, ensure_ascii=False) + '\n'); stream.flush()
            print(row['event_id'], row['status'], flush=True)
    print(json.dumps(finalize(data, meta, saved, responses), ensure_ascii=False))


if __name__ == '__main__':
    main()
