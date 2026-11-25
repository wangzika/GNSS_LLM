#!/usr/bin/env python3
"""结合代理逐条裁定和保守内容检查，导出审阅后的 SFT 子集及可读审阅索引。"""
import argparse
import hashlib
import json
import re
import shutil
import sys
import time
from collections import Counter
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from scripts.common.step2_validate_and_pack import BLOCK_RE, SYSTEM_PROMPTS, normalize_conclusion
from scripts.industrial.industrial_prepare_workflow import model_input
from scripts.industrial.workflow_paths import WorkflowPaths


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


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',type=Path,required=True)
    parser.add_argument('--audit-name',default='report_audit_recomputed.jsonl')
    args=parser.parse_args(); data=WorkflowPaths(args.data_dir)
    data.initialize()
    meta=json.loads((data.input('04_review', 'train_meta.json')).read_text())
    audits={r['event_id']:r for r in [json.loads(x) for x in (data.audit(args.audit_name)).read_text().splitlines() if x.strip()]}
    if len(audits)!=len(meta):raise ValueError('审阅尚未覆盖所有训练事件')
    overrides={}
    p=data.file('agent_review_decisions.jsonl')
    if p.exists(): overrides={r['event_id']:r for r in [json.loads(x) for x in p.read_text().splitlines() if x.strip()]}
    backup=data.archive/('before_final_review_'+str(time.time_ns()));backup.mkdir(parents=True)
    for name in ['train_sft_clean.jsonl','train_sft_review.jsonl','audit_summary.json']:
        src=data.file(name)
        if src.exists():
            with src.open('rb') as stream,(backup/name).open('xb') as dst:shutil.copyfileobj(stream,dst)
    rows=[]; decisions=[]; summary=[]
    for rec in meta:
        eid=rec['event_meta']['event_id'];audit=audits[eid];response=audit.get('response','')
        state=audit['status'];issues=list(audit.get('issues',[]))
        if state=='accept':
            flags=content_flags(rec,response)
            if flags:state='reject';issues.extend(flags)
        if any(x in rec['ground_truth_intent'] for x in ['Tool Wear Failure','Random Failure']):
            state='uncertain';issues=['随机故障无法从当前观测确认，不纳入确定标签训练']+issues
        if eid in overrides:
            state=overrides[eid]['status'];issues=overrides[eid]['issues']
        decisions.append({'event_id':eid,'status':state,'issues':issues,'response_sha256':hashlib.sha256(response.encode()).hexdigest()})
        if state=='accept':
            rows.append({'instruction':SYSTEM_PROMPTS['industrial'],'input':json.dumps(model_input(rec),ensure_ascii=False,separators=(',',':')),'output':normalize_conclusion(BLOCK_RE.findall(response)[0],rec).strip()})
        summary.append(f"| {eid} | {state} | {'；'.join(issues).replace('|','／') or '当前检查未发现问题'} |")
    for name in ['train_sft_clean.jsonl','train_sft_review.jsonl']:
        (data.file(name)).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))
    (data.file('final_review_decisions.jsonl')).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in decisions))
    stats={'total_train':len(meta),'clean_count':len(rows),'status_counts':dict(Counter(x['status'] for x in decisions)),'review_method':'程序逐字段/规则核对、模型抽取文字断言后验算、保守内容过滤，代理复核争议','limitations':['文本提取可能漏检；不是外部专家认证','TWF样本不纳入确定故障训练','留出集未交给教师生成训练报告','不包含正常类与多故障类，不能宣称通用故障检测能力']}
    (data.file('audit_summary.json')).write_text(json.dumps(stats,ensure_ascii=False,indent=2)+'\n')
    (data.file('REVIEW.md')).write_text('# 教师报告审阅结果\n\n'+json.dumps(stats,ensure_ascii=False,indent=2)+'\n\n| 事件 | 判定 | 依据 |\n| --- | --- | --- |\n'+'\n'.join(summary)+'\n')
    print(json.dumps(stats,ensure_ascii=False))

if __name__=='__main__':main()
