#!/usr/bin/env python3
"""生成新版教师报告，做数值/规则核验和独立请求复核，保留逐事件审阅记录。

自动语义复核由同一教师服务的新请求执行，不能视为独立专家评审。
TWF/RNF 的发生不能从输入确定，因此不进入确定故障标签的 clean 文件。
"""
import argparse
import hashlib
import json
import re
import shutil
import sys
import time
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.industrial import industrial_generate_teacher as teacher
from scripts.industrial.industrial_prepare_workflow import model_input
from scripts.common.step2_validate_and_pack import BLOCK_RE, validate, normalize_conclusion, SYSTEM_PROMPTS

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
        {'role':'user','content':json.dumps({'input':model_input(rec),'computed':teacher.derived_measurements(rec),'report':report},ensure_ascii=False)}]}
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
    expected={**rec['physical_features'],**{k:v for k,v in teacher.derived_measurements(rec).items() if k!='rule_checks'}}
    for key,value in expected.items():
        matches=re.findall(r'(?m)^\s*-\s*'+re.escape(key)+r'\s*[:=]\s*(-?\d+(?:\.\d+)?)',evidence)
        if not matches and key in rec['physical_features']: issues.append('缺少键值对:'+key)
        if any(abs(float(x)-value)>.11 for x in matches):issues.append('键值不一致:'+key)
    checks=teacher.derived_measurements(rec)['rule_checks']
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
    checks=teacher.derived_measurements(rec)['rule_checks']
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


def one(rec,args):
    attempts=[]
    for index in range(args.attempts):
        response=None
        try:
            response=(args.existing[rec['event_meta']['event_id']]
                      if index==0 and rec['event_meta']['event_id'] in args.existing
                      else teacher.request_report(args.url,args.model,rec,180,1100,2))
            audit=inspect(rec,response,args)
            attempts.append({'response':response,**audit})
            if audit['status'] in ('accept','uncertain'):break
        except Exception as exc:
            attempts.append({'status':'error','issues':[type(exc).__name__+':'+str(exc)],**({'response':response} if response else {})})
    # 不选取失败尝试中某个“看起来像正确”的文本；只取最后一次记录。
    last=attempts[-1]
    return {'event_id':rec['event_meta']['event_id'],'model':args.model,'attempts':attempts,**last}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',type=Path,required=True)
    parser.add_argument('--workers',type=int,default=4)
    parser.add_argument('--attempts',type=int,default=2)
    parser.add_argument('--audit-name',default='report_audit.jsonl')
    parser.add_argument('--seed-audit',type=Path,help='只读复用旧审阅日志里的原始回答，不沿用旧判定')
    parser.add_argument('--audit-only',action='store_true',help='复核已有 teacher_responses.jsonl，不重新生成')
    parser.add_argument('--url',default='http://127.0.0.1:8000/v1/chat/completions')
    parser.add_argument('--model',default='Qwen/Qwen2.5-32B-Instruct')
    args=parser.parse_args()
    if args.workers<1 or args.attempts<1:parser.error('workers/attempts 必须为正数')
    data=args.data_dir; meta=teacher.read_records(data/'train_meta.json')
    audits=data/args.audit_name
    saved={}
    if audits.exists():
        for line in audits.read_text().splitlines():
            if line.strip():
                row=json.loads(line); saved[row['event_id']]=row
    existing={}
    args.existing=teacher.read_existing(data/'teacher_responses.jsonl',args.model) if (data/'teacher_responses.jsonl').exists() else {}
    if args.seed_audit and args.seed_audit.exists():
        for line in args.seed_audit.read_text().splitlines():
            row=json.loads(line)
            if 'response' in row: args.existing.setdefault(row['event_id'],row['response'])
    if args.audit_only:
        existing=teacher.read_existing(data/'teacher_responses.jsonl',args.model)
    def run(rec):
        if not args.audit_only:return one(rec,args)
        eid=rec['event_meta']['event_id']; response=existing[eid]
        try: audit=inspect(rec,response,args)
        except Exception as exc:audit={'status':'error','issues':[str(exc)]}
        return {'event_id':eid,'model':args.model,'response':response,**audit}
    pending=[r for r in meta if r['event_meta']['event_id'] not in saved]
    with audits.open('a',encoding='utf-8') as stream, ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures={pool.submit(run,r):r for r in pending}
        for future in as_completed(futures):
            row=future.result(); saved[row['event_id']]=row
            stream.write(json.dumps(row,ensure_ascii=False)+'\n'); stream.flush()
            print(len(saved),'/',len(meta),row['event_id'],row['status'],row['issues'],flush=True)
    backup=data/'archive'/('before_review_'+str(time.time_ns()))
    for name in ['teacher_responses.jsonl','teacher_raw.txt','train_sft_review.jsonl','train_sft_clean.jsonl','audit_summary.json']:
        previous=data/name
        if previous.exists():
            backup.mkdir(parents=True,exist_ok=True)
            with previous.open('rb') as src,(backup/name).open('xb') as dst:shutil.copyfileobj(src,dst)
    responses={eid:row['response'] for eid,row in saved.items() if 'response' in row}
    # audit-only 不改原始回答；新批次保留每个事件最终回答，所有尝试留在审阅日志。
    if not args.audit_only:
        with (data/'teacher_responses.jsonl').open('w',encoding='utf-8') as stream:
            for rec in meta:
                eid=rec['event_meta']['event_id']
                if eid in responses:stream.write(json.dumps({'event_id':eid,'model':args.model,'response':responses[eid]},ensure_ascii=False)+'\n')
        teacher.write_raw(data/'teacher_raw.txt',meta,responses)
    # clean 是审阅通过的子集；完整覆盖率记录在清单中，不能宣称全部报告通过。
    accepted=[]
    for rec in meta:
        row=saved[rec['event_meta']['event_id']]
        if row['status']=='accept':
            accepted.append({'instruction':SYSTEM_PROMPTS['industrial'],'input':json.dumps(model_input(rec),ensure_ascii=False,separators=(',',':')),'output':normalize_conclusion(BLOCK_RE.findall(row['response'])[0],rec).strip()})
    for name in ['train_sft_review.jsonl','train_sft_clean.jsonl']:
        with (data/name).open('w',encoding='utf-8') as stream:
            for row in accepted:stream.write(json.dumps(row,ensure_ascii=False)+'\n')
    summary={'total_train':len(meta),'status_counts':dict(Counter(x['status'] for x in saved.values())),'clean_count':len(accepted),'method':'结构、标签、逐字段数值、可重算规则检查 + 文本比较/规则说法提取后程序验算','review_model':args.model,'limitations':['同模型复核存在相关错误，不是独立专家评审','排除观测不能确认的 TWF/RNF，不将风险强行确认为故障','正常样本和多故障样本未纳入','clean 仅是通过当前审阅的子集，仍需独立留出集验证'],'meta_sha256':hashlib.sha256((data/'train_meta.json').read_bytes()).hexdigest()}
    (data/'audit_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(summary,ensure_ascii=False),flush=True)

if __name__=='__main__': main()
