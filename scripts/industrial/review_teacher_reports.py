#!/usr/bin/env python3
"""自动报告审阅：程序核对、模型提取断言、保守过滤及 SFT 导出。

只读取教师原始回答，不重新生成诊断报告。默认使用已保存的验算结果；
缺少记录时请求教师提取原句，再由 Python 计算比较真假，可断点续跑。
"""
import argparse
import hashlib
import json
import math
import operator
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


POLICY_VERSION = 'automatic-v1'
OPERATORS = {'>': operator.gt, '<': operator.lt, '>=': operator.ge,
             '<=': operator.le, '=': operator.eq}


def verify_extraction(rec, response, extraction):
    """原句必须存在、结构可核查；不能验证的提取自动隔离，不默认为通过。"""
    issues, unresolved = [], []
    if extraction.get('extraction_error'):
        return [], ['文字提取失败，暂不纳入训练；下次联网审阅自动重试']
    comparisons = extraction.get('comparisons', extraction.get('extracted_comparisons', []))
    claims = extraction.get('rule_claims', extraction.get('extracted_rule_claims', []))
    if not isinstance(comparisons, list) or not isinstance(claims, list):
        return [], ['文字提取结构错误']
    if not comparisons or not claims:
        unresolved.append('未提取到完整的比较句或规则说法')
    for item in comparisons:
        if not isinstance(item, dict):
            unresolved.append('比较提取项不是对象'); continue
        quote, op = item.get('quote'), item.get('op')
        left, right = item.get('left'), item.get('right')
        if (not isinstance(quote, str) or not quote or quote not in response
                or op not in OPERATORS
                or any(isinstance(v, bool) or not isinstance(v, (int, float))
                       or not math.isfinite(v) for v in (left, right))):
            unresolved.append('比较提取缺少有效原句、数字或运算符'); continue
        nums = [float(x) for x in re.findall(r'(?<![A-Za-z_])(?<![\d.])-?\d+(?:\.\d+)?', quote)]
        if left not in nums or right not in nums:
            unresolved.append('提取数字不在原句中：' + quote); continue
        # 比较方向从原句解析，不沿用提取器猜测的运算符。
        phrases = {'不超过': '<=', '未超过': '<=', '不大于': '<=', '不高于': '<=',
                   '不低于': '>=', '未低于': '>=', '不小于': '>=',
                   '大于等于': '>=', '小于等于': '<=',
                   '大于': '>', '高于': '>', '超过': '>', '小于': '<', '低于': '<', '等于': '='}
        pattern = '|'.join(map(re.escape, sorted(phrases, key=len, reverse=True)))
        directions = {phrases[m.group()] for m in re.finditer(pattern, quote)}
        if not directions:
            directions = set(re.findall(r'>=|<=|>|<|=', quote))
        ordered = any(a < b for a, value in enumerate(nums) if value == left
                      for b, other in enumerate(nums) if other == right)
        if len(directions) != 1 or not ordered:
            unresolved.append('原句比较关系或数字顺序无法可靠解析：' + quote); continue
        actual_op = next(iter(directions))
        denied = bool(re.search(r'(?:条件|要求)\s*(?:未满足|不满足|未成立|不成立)[。\s]*$', quote))
        if OPERATORS[actual_op](left, right) == denied:
            issues.append('原句比较不成立：' + quote)
    checks = derived_measurements(rec)['rule_checks']
    for item in claims:
        if not isinstance(item, dict):
            unresolved.append('规则提取项不是对象'); continue
        quote, rule, state = item.get('quote'), item.get('rule'), item.get('triggered')
        if not isinstance(quote, str) or not quote or quote not in response or rule not in ('HDF','PWF','OSF') or not isinstance(state, bool):
            unresolved.append('规则提取没有有效引文或触发状态'); continue
        if state != checks[rule + '_triggered']:
            unresolved.append('规则说法提取与程序重算不一致，无法确定是报告还是提取器错误：' + quote)
    return issues, unresolved


def automatic_decision(rec, response, extraction):
    """所有事件共用同一套规则；没有事件 ID 白名单或外部覆盖裁定。"""
    if any(name in rec['ground_truth_intent'] for name in ('Tool Wear Failure', 'Random Failure')):
        return {'status': 'uncertain', 'issues': ['随机故障无法从当前观测确认，不纳入确定标签训练']}
    blocks = BLOCK_RE.findall(response)
    if len(blocks) != 1:
        return {'status': 'reject', 'issues': ['代码块数量异常']}
    reason = validate(blocks[0], rec)
    issues = ([reason] if reason else []) + numeric_issues(rec, blocks[0]) + content_flags(rec, response)
    if issues:
        return {'status': 'reject', 'issues': list(dict.fromkeys(issues))}
    errors, unresolved = verify_extraction(rec, response, extraction)
    if errors:
        return {'status': 'reject', 'issues': errors}
    if unresolved:
        return {'status': 'needs_review', 'issues': list(dict.fromkeys(unresolved))}
    return {'status': 'accept', 'issues': []}


def inspect(rec, response, args):
    preliminary = automatic_decision(rec, response, {})
    if preliminary['status'] in ('reject', 'uncertain'):
        return preliminary
    try:
        extraction = judge(rec, response, args)
    except Exception as exc:
        return {'status': 'needs_review', 'issues': ['文字提取失败，暂不纳入训练：' + str(exc)],
                'extraction_error': True}
    return {**automatic_decision(rec, response, extraction),
            'extracted_comparisons': extraction['comparisons'],
            'extracted_rule_claims': extraction['rule_claims']}


def content_flags(rec,text):
    flags=[]
    # 直接从原文匹配局部数值比较，补充模型提取可能漏掉的“未低于”等否定比较。
    comparison=re.compile(r'(-?\d+(?:\.\d+)?)\s*(?:min·Nm|rpm|分钟|K|W|min)?[，,\s]*(接近但未低于|未低于|不低于|未超过|不超过|远大于|远小于|远高于|远低于|大于|小于|高于|低于|超过)[^。；\n\d]{0,25}(-?\d+(?:\.\d+)?)')
    def negated_tail(tail):
        return re.match(r'\s*(?:rpm|分钟|K|W|min)?\s*的?\s*(?:条件|要求)\s*(?:未满足|不满足|未成立|不成立)', tail)
    for match in comparison.finditer(text):
        a=float(match.group(1));b=float(match.group(3));op=match.group(2)
        if op in ('接近但未低于','未低于','不低于'):ok=a>=b
        elif op in ('未超过','不超过'):ok=a<=b
        elif op in ('大于','高于','超过','远大于','远高于'):ok=a>b
        else:ok=a<b
        denied = bool(negated_tail(text[match.end():]))
        if ok == denied:flags.append('原文直接数值比较不成立:'+match.group())
    # 现有测量不能排除独立随机故障；对这类无依据的排除句采取保守剔除。
    for sentence in re.split('[。；\n]',text):
        if any(x in sentence for x in ['RNF','Random Failure','随机系统故障','随机性故障']):
            cleaned=re.sub('不能排除|无法排除|不应排除|不排除','',sentence)
            if '排除' in cleaned:flags.append('不能从当前观测排除随机故障:'+sentence)
    wear=rec['physical_features']['tool_wear_min']
    # 比较链共享同一左值，例如“功率3301.8，小于9000但小于3500的条件未满足”。
    chain = re.compile(r'(?:但|且|并且|也)\s*(小于|低于|大于|高于|超过)\s*(-?\d+(?:\.\d+)?)')
    for match in comparison.finditer(text):
        a, b = float(match.group(1)), float(match.group(3))
        following = text[match.end():].split('。', 1)[0].split('；', 1)[0].split('\n', 1)[0]
        following = re.sub(r'^\s*(?:rpm|分钟|K|W|min)\s*', '', following)
        more = chain.match(following)
        if more:
            rhs = float(more.group(2)); less = more.group(1) in ('小于','低于')
            actual = a < rhs if less else a > rhs
            denied = bool(negated_tail(following[more.end():]))
            if actual == denied:
                flags.append('连续数值比较不成立：' + match.group() + following[:more.end()+12])
    checks = derived_measurements(rec)['rule_checks']
    for match in re.finditer(r'\b(HDF_triggered|PWF_triggered|OSF_triggered|TWF_risk_window_only)\s*(?:为|是|[:=])\s*(true|false)\b', text, re.I):
        if (match.group(2).lower() == 'true') != {k.lower(): v for k, v in checks.items()}[match.group(1).lower()]:
            flags.append('报告规则布尔值与程序重算不一致：' + match.group())
    for sentence in re.split('[。；\n]', text):
        if not any(term in sentence for term in ('磨损','TWF','tool_wear')):
            continue
        # “不在/未处于”与肯定的“在/处于”分别匹配，避免把否定句当肯定句。
        within = re.search(r'(?:处于|处在|位于|在)\s*(?:200\s*(?:至|到|～|~|-|—)\s*240\s*(?:分钟|min)?\s*的?\s*)?风险窗口内', sentence)
        if within:
            prefix = sentence[max(0, within.start()-3):within.start()]
            negated = prefix.endswith(('不','未','没有','并非','非'))
            expected = 200 <= wear <= 240
            if (not negated) != expected:
                flags.append('风险窗口文字与实际磨损时间不一致：' + sentence)
        if checks['TWF_risk_window_only']:
            # 风险窗口内只能说无法确认，不能据此排除随机 TWF；不强行猜测其实际发生。
            cleaned = re.sub(r'不能排除|无法排除|不应排除|不排除', '', sentence)
            if re.search(r'排除\s*(?:了)?\s*(?:TWF|工具(?:严重)?磨损故障|Tool Wear Failure)', cleaned):
                flags.append('风险窗口内缺乏排除 TWF 的确定证据：' + sentence)
    return flags


def finalize(data, meta, audits, responses):
    """从原文与缓存提取内容重新验算，不信任缓存的 accept/reject 结论。"""
    if set(audits) != {r['event_meta']['event_id'] for r in meta}:
        raise ValueError('审阅日志尚未精确覆盖全部训练事件')
    rows, decisions, checked_audits = [], [], []
    for rec in meta:
        eid = rec['event_meta']['event_id']
        audit, response = audits[eid], responses[eid]
        expected = hashlib.sha256(response.encode()).hexdigest()
        if audit.get('response_sha256') != expected:
            raise ValueError(f'报告与审阅记录不匹配：{eid}')
        result = automatic_decision(rec, response, audit)
        state, issues = result['status'], result['issues']
        checked_audits.append({**audit, **result, 'policy_version': POLICY_VERSION})
        decisions.append({'event_id': eid, 'status': state, 'issues': issues,
                          'response_sha256': expected, 'policy_version': POLICY_VERSION})
        if state == 'accept':
            rows.append({'instruction': STUDENT_INSTRUCTION,
                         'input': json.dumps(model_input(rec), ensure_ascii=False, separators=(',', ':')),
                         'output': normalize_conclusion(BLOCK_RE.findall(response)[0], rec).strip()})
    stats = {'total_train': len(meta), 'clean_count': len(rows),
             'status_counts': dict(Counter(r['status'] for r in decisions)),
             'accepted_label_counts': dict(Counter(
                 rec['ground_truth_intent'] for rec, decision in zip(meta, decisions)
                 if decision['status'] == 'accept')),
             'policy_version': POLICY_VERSION,
             'review_method': '通用程序检查、模型提取原句后验算，无法可靠验证的内容自动隔离；无外部裁定覆盖',
             'limitations': ['文本提取和规则仍可能漏检；自动通过不等于专家认证',
                             'needs_review/uncertain/reject 均不进入训练，无需人工操作即可完成批处理', 'TWF样本不纳入确定故障训练',
                             '留出集未交给教师生成训练报告', '不包含正常类与多故障类，不能宣称通用故障检测能力']}
    write_jsonl(data.file('train_sft.jsonl'), rows)
    write_jsonl(data.file('report_audit.jsonl'), checked_audits)
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
    pending = [r for r in meta if r['event_meta']['event_id'] not in saved
               or (not args.offline and saved[r['event_meta']['event_id']].get('extraction_error'))]
    if args.offline and pending:
        raise ValueError(f'离线审阅缺少 {len(pending)} 条记录')
    def review(rec):
        eid = rec['event_meta']['event_id']; response = responses[eid]
        audit = inspect(rec, response, args)
        return {'event_id': eid, 'model': args.model,
                'response_sha256': hashlib.sha256(response.encode()).hexdigest(), **audit}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(review, rec) for rec in pending]
        for future in as_completed(futures):
            row = future.result(); saved[row['event_id']] = row
            temporary = audit_path.with_suffix('.jsonl.tmp')
            write_jsonl(temporary, [saved[eid] for eid in sorted(saved)])
            temporary.replace(audit_path)
            print(row['event_id'], row['status'], flush=True)
    print(json.dumps(finalize(data, meta, saved, responses), ensure_ascii=False))


if __name__ == '__main__':
    main()
