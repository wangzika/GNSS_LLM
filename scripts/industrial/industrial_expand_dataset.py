#!/usr/bin/env python3
"""使用全部单故障 AI4I 事件扩充独立版本，保留 v1 的既有划分归属。"""
import argparse
import csv
import hashlib
import json
import random
import sys
from collections import Counter
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.industrial.workflow_paths import WorkflowPaths
from scripts.industrial.step1_prepare_inputs import make_record, LABELS
from scripts.industrial.industrial_prepare_workflow import model_input, write_json, write_jsonl, write_prompts
ROOT = Path(__file__).resolve().parents[2]


def signature(rec):
    return (rec['event_meta']['equipment_grade'], *rec['physical_features'].values())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir', type=Path, default=ROOT/'data/industrial_v2')
    parser.add_argument('--seed', type=int, default=42)
    args = parser.parse_args()
    out = args.out_dir
    if out.exists():
        raise SystemExit('输出目录已存在；使用新的目录避免覆盖实验')
    old = ROOT/'data/industrial_v1'
    assignments = {signature(x): 'train' for x in json.loads((old/'train_meta.json').read_text())}
    for part in ('validation', 'test'):
        for line in (old/f'{part}_inputs.jsonl').read_text().splitlines():
            key = signature(json.loads(line)['input'])
            if key in assignments:
                raise ValueError('v1 同一物理输入跨集合重复')
            assignments[key] = part
    csv_path = ROOT/'data/industrial_source/raw_ai4i2020.csv'
    records = []; origins = {}; fixed = {}; seen = set()
    for row in csv.DictReader(csv_path.open(encoding='utf-8-sig')):
        active = [k for k in LABELS if row[k] == '1']
        if row['Machine failure'] != '1' or len(active) != 1:
            continue
        udi = int(row['UDI'])
        rng = random.Random(args.seed * 100000 + udi)
        rec = make_record(row, active[0], f'EVT-20261124-{len(records)+1:04d}', rng, 'uci_ai4i2020')
        key = signature(rec)
        if key in seen:
            raise ValueError('重复物理输入需按组划分，不能独立抽样')
        seen.add(key)
        rec['case_type'] = 'STANDARD'
        eid = rec['event_meta']['event_id']
        origins[eid] = {'source_udi': udi, 'product_id': row['Product ID']}
        if key in assignments:
            fixed[eid] = assignments[key]
        records.append(rec)
    if len(fixed) != len(assignments):
        raise ValueError('不能完整映射旧划分')
    groups = {}
    for rec in records:
        groups.setdefault(rec['ground_truth_intent'], []).append(rec)
    parts = {part: [] for part in ('train', 'validation', 'test')}
    rng = random.Random(args.seed)
    for label, group in sorted(groups.items()):
        rng.shuffle(group)
        target = {'validation': round(len(group)*.1), 'test': round(len(group)*.2)}
        target['train'] = len(group)-sum(target.values())
        remaining = []
        for rec in group:
            eid = rec['event_meta']['event_id']
            if eid in fixed:
                parts[fixed[eid]].append(rec)
            else:
                remaining.append(rec)
        for part in ('test','validation','train'):
            current = sum(x['ground_truth_intent']==label for x in parts[part])
            need = target[part] - current
            if need < 0: raise ValueError('目标比例无法容纳旧划分')
            parts[part].extend(remaining[:need]); del remaining[:need]
        assert not remaining
    layout = WorkflowPaths(out)
    layout.initialize(source_csv=csv_path, legacy_dir=old)
    for part, items in parts.items():
        items.sort(key=lambda r:r['event_meta']['event_id'])
        # 模拟上下文只在分集后设置，不能改变原始测量或影响物理诊断。
        shuffled = list(items); random.Random(args.seed + len(items)).shuffle(shuffled)
        for index, rec in enumerate(shuffled):
            if index < round(len(items)*.2):
                rec['case_type']='MISSING_CONTEXT'
                rec['spatial_context']={'operating_mode':None,'workshop_zone':None}
            elif index < round(len(items)*.3):
                rec['case_type']='CONFLICTING_EVIDENCE'
                rec['spatial_context']['workshop_zone']='Idle_Standby_Bay'
        write_json(layout.file(f'{part}_meta.json'), items)
        if part != 'train':
            write_jsonl(layout.file(f'{part}_inputs.jsonl'),[{'event_id':r['event_meta']['event_id'],'input':model_input(r)} for r in items])
            write_jsonl(layout.file(f'{part}_labels.jsonl'),[{'event_id':r['event_meta']['event_id'],'ground_truth_intent':r['ground_truth_intent']} for r in items])
    write_json(layout.file('events_meta.json'), sorted(records, key=lambda r:r['event_meta']['event_id']))
    write_prompts(layout.file('teacher_prompts_blind.txt'),parts['train'],5)
    write_jsonl(layout.file('source_provenance.jsonl'),[{'event_id':r['event_meta']['event_id'],'split':part,**origins[r['event_meta']['event_id']]} for part,items in parts.items() for r in items])
    write_json(layout.file('manifest.json'),{'seed':args.seed,'raw_sha256':hashlib.sha256(csv_path.read_bytes()).hexdigest(),'counts':{k:len(v) for k,v in parts.items()},'label_counts':{k:dict(Counter(x['ground_truth_intent'] for x in v)) for k,v in parts.items()},'v1_assignments_preserved':len(fixed),'duplicate_physical_inputs':0,'limitations':['只包含单一故障事件，不含正常样本和多故障样本','TWF 随机发生，风险窗口不能确定真实故障','仅按独立行划分，不是按时间或生产批次留出，不能声称时间泛化','运行模式和车间区域是随机背景']})
    print(json.dumps({'out':str(out),'counts':{k:len(v) for k,v in parts.items()}},ensure_ascii=False))

if __name__=='__main__': main()
