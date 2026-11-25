#!/usr/bin/env python3
"""数据预处理：读取 AI4I、筛选单故障、构造字段、划分集合并分离输入与标签。

默认使用当前固定划分表，可完整重现 214/31/61 及模拟上下文。
不下载数据、不生成教师报告；输出目录必须不存在，避免覆盖已完成实验。
"""
import argparse
import csv
import hashlib
import json
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.industrial.common import (
    DATA, SOURCE_CSV, SPLIT_ASSIGNMENTS, LABELS, WorkflowPaths,
    model_input, write_json, write_jsonl,
)


def make_record(row, label, index, seed):
    """原始测量保持不变；只有运行模式与车间区域是可复现的随机背景。"""
    rng = random.Random(seed * 100000 + int(row['UDI']))
    return {
        'ground_truth_intent': LABELS[label],
        'data_source': 'uci_ai4i2020',
        # 固定编号延续已有报告引用，不以本次运行日期更改事件 ID。
        'event_meta': {'event_id': f'EVT-20261124-{index:04d}', 'equipment_grade': row['Type']},
        'physical_features': {
            'air_temp_k': float(row['Air temperature [K]'].strip()),
            'process_temp_k': float(row['Process temperature [K]'].strip()),
            'rotational_speed_rpm': int(row['Rotational speed [rpm]'].strip()),
            'torque_nm': float(row['Torque [Nm]'].strip()),
            'tool_wear_min': int(row['Tool wear [min]'].strip()),
        },
        'spatial_context': {
            'operating_mode': rng.choice(['Continuous_Load', 'Peak_Shift', 'Standard_Cycle']),
            'workshop_zone': rng.choice(['Line_A_Stamping', 'Line_B_CNC', 'Line_C_Assembly']),
        },
        'case_type': 'STANDARD',
    }


def signature(record):
    return (record['event_meta']['equipment_grade'], *record['physical_features'].values())


def preprocess(csv_path, out_dir, seed=42, assignments_path=SPLIT_ASSIGNMENTS):
    """生成一份完整的新实验数据；固定划分与全新分层划分共用一个入口。"""
    if out_dir.exists():
        raise ValueError('输出目录已存在，请指定新的 --out-dir，避免覆盖已有实验')
    raw_hash = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    fixed = {}
    if assignments_path is not None:
        frozen = json.loads(assignments_path.read_text(encoding='utf-8'))
        if frozen['source_sha256'] != raw_hash or frozen['seed'] != seed:
            raise ValueError('CSV 或 seed 与固定划分不匹配；确需新实验时使用 --new-split')
        fixed = frozen['assignments']
    records, origins, fixed_by_id, seen, source_ids = [], {}, {}, set(), set()
    with csv_path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        required = {'UDI', 'Product ID', 'Type', 'Air temperature [K]', 'Process temperature [K]',
                    'Rotational speed [rpm]', 'Torque [Nm]', 'Tool wear [min]', 'Machine failure', *LABELS}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError('CSV 缺少 AI4I 必要字段')
        for row in reader:
            active = [key for key in LABELS if row[key] == '1']
            if row['Machine failure'] != '1' or len(active) != 1:
                continue
            rec = make_record(row, active[0], len(records) + 1, seed)
            key = signature(rec)
            if key in seen or row['UDI'] in source_ids:
                raise ValueError('物理输入或源 UDI 重复，需先按组去重或划分')
            seen.add(key); source_ids.add(row['UDI'])
            eid = rec['event_meta']['event_id']
            origins[eid] = {'source_udi': int(row['UDI']), 'product_id': row['Product ID']}
            if row['UDI'] in fixed:
                fixed_by_id[eid] = fixed[row['UDI']]
            records.append(rec)
    if not records or (fixed and set(fixed) != source_ids):
        raise ValueError('没有可用事件，或固定划分未精确覆盖当前单故障事件')
    groups = {}
    for rec in records:
        groups.setdefault(rec['ground_truth_intent'], []).append(rec)
    parts = {name: [] for name in ('train', 'validation', 'test')}
    rng = random.Random(seed)
    for label, group in sorted(groups.items()):
        rng.shuffle(group)
        targets = {'validation': round(len(group) * .1), 'test': round(len(group) * .2)}
        targets['train'] = len(group) - sum(targets.values())
        remaining = []
        for rec in group:
            eid = rec['event_meta']['event_id']
            if eid in fixed_by_id:
                part = fixed_by_id[eid]
                if part not in parts:
                    raise ValueError(f'非法集合名：{part}')
                parts[part].append(rec)
            else:
                remaining.append(rec)
        for part in ('test', 'validation', 'train'):
            need = targets[part] - sum(r['ground_truth_intent'] == label for r in parts[part])
            if need < 0:
                raise ValueError('固定划分与类别目标比例冲突')
            parts[part].extend(remaining[:need]); del remaining[:need]
        if remaining:
            raise ValueError('划分未覆盖全部事件')
    layout = WorkflowPaths(out_dir)
    layout.initialize(source_csv=csv_path, assignments=assignments_path)
    for part, items in parts.items():
        items.sort(key=lambda r: r['event_meta']['event_id'])
        shuffled = list(items)
        random.Random(seed + len(items)).shuffle(shuffled)
        for index, rec in enumerate(shuffled):
            if index < round(len(items) * .2):
                rec['case_type'] = 'MISSING_CONTEXT'
                rec['spatial_context'] = {'operating_mode': None, 'workshop_zone': None}
            elif index < round(len(items) * .3):
                rec['case_type'] = 'CONFLICTING_EVIDENCE'
                rec['spatial_context']['workshop_zone'] = 'Idle_Standby_Bay'
        if part == 'train':
            write_json(layout.file('train_meta.json'), items)
        else:
            write_jsonl(layout.file(f'{part}_inputs.jsonl'), [
                {'event_id': r['event_meta']['event_id'], 'input': model_input(r)} for r in items])
            write_jsonl(layout.file(f'{part}_labels.jsonl'), [
                {'event_id': r['event_meta']['event_id'], 'ground_truth_intent': r['ground_truth_intent']}
                for r in items])
    provenance = [{'event_id': r['event_meta']['event_id'], 'split': part,
                   **origins[r['event_meta']['event_id']]} for part, items in parts.items() for r in items]
    write_jsonl(layout.file('source_provenance.jsonl'), provenance)
    write_json(layout.file('manifest.json'), {
        'seed': seed, 'raw_sha256': raw_hash,
        'counts': {part: len(items) for part, items in parts.items()},
        'label_counts': {part: dict(Counter(r['ground_truth_intent'] for r in items))
                         for part, items in parts.items()},
        'split_method': 'frozen_source_udi' if fixed else 'stratified_random',
        'fixed_assignments': len(fixed), 'duplicate_physical_inputs': 0,
        'limitations': ['只包含单故障，不含正常和多故障样本', 'TWF 随机发生，风险窗口不能确认故障',
                        '按事件行划分，不能声称时间或生产批次泛化', '运行模式和车间区域是随机背景'],
    })
    if assignments_path is None:
        write_json(layout.input('01_preprocess', 'split_assignments.json'), {
            'source_sha256': raw_hash, 'seed': seed,
            'assignments': {str(r['source_udi']): r['split'] for r in provenance},
        })
    return layout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--csv', type=Path, default=SOURCE_CSV)
    parser.add_argument('--out-dir', type=Path, default=DATA)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--assignments', type=Path, default=SPLIT_ASSIGNMENTS)
    parser.add_argument('--new-split', action='store_true', help='创建新的随机分层划分，不沿用当前固定集合')
    args = parser.parse_args()
    try:
        layout = preprocess(args.csv, args.out_dir, args.seed, None if args.new_split else args.assignments)
    except ValueError as exc:
        parser.error(str(exc))
    print('数据预处理完成：', layout.output_dir('01_preprocess'))


if __name__ == '__main__':
    main()
