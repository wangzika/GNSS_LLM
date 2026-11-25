#!/usr/bin/env python3
"""统一一致性检查：链接、样本泄漏、预处理重现、审阅重现、已有指标重算。

只使用本地数据与临时目录，不加载模型、不训练、不调用教师，不额外保存测试产物。
"""
import argparse
import contextlib
import hashlib
import io
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.industrial.common import DATA, ROOT, STAGES, WorkflowPaths, read_jsonl
from scripts.industrial.preprocess_data import preprocess, signature
from scripts.industrial.generate_teacher_reports import read_existing
from scripts.industrial.review_teacher_reports import finalize
from scripts.industrial.evaluate_student import score


def check(root):
    data = WorkflowPaths(root)
    for stage in STAGES:
        for side in ('input', 'output'):
            if not (root / stage / side).is_dir():
                raise ValueError(f'缺少目录：{stage}/{side}')
    for link in root.rglob('*'):
        if link.is_symlink() and (not link.exists() or link.readlink().is_absolute()):
            raise ValueError(f'失效或非相对链接：{link}')
    meta = json.loads(data.file('train_meta.json').read_text())
    inputs = {'train': meta}
    for split in ('validation', 'test'):
        rows = read_jsonl(data.file(f'{split}_inputs.jsonl'))
        labels = read_jsonl(data.file(f'{split}_labels.jsonl'))
        if len({r['event_id'] for r in rows}) != len(rows) or {r['event_id'] for r in rows} != {r['event_id'] for r in labels}:
            raise ValueError(f'{split} ID/标签不完整或重复')
        if any('ground_truth_intent' in r['input'] for r in rows):
            raise ValueError('留出输入泄漏真实标签')
        inputs[split] = [r['input'] for r in rows]
    seen = set()
    for split, rows in inputs.items():
        for row in rows:
            key = signature(row)
            if key in seen:
                raise ValueError('同一物理输入重复或跨集合')
            seen.add(key)
    clean = read_jsonl(data.file('train_sft.jsonl'))
    train_inputs = {signature(r) for r in meta}
    clean_signatures = set()
    for row in clean:
        payload = json.loads(row['input'])
        if set(payload) & {'ground_truth_intent', 'case_type', 'data_source'}:
            raise ValueError('训练输入含内部答案字段')
        key = signature(payload)
        if key not in train_inputs or key in clean_signatures:
            raise ValueError('训练报告样本重复或来自留出集')
        clean_signatures.add(key)
    raw = read_existing(data.file('teacher_responses.jsonl'), 'Qwen/Qwen2.5-32B-Instruct')
    if set(raw) != {r['event_meta']['event_id'] for r in meta}:
        raise ValueError('教师回答未精确覆盖训练集')
    audits = {r['event_id']: r for r in read_jsonl(data.file('report_audit.jsonl'))}
    for eid, response in raw.items():
        if audits[eid]['response_sha256'] != hashlib.sha256(response.encode()).hexdigest():
            raise ValueError('审阅哈希与教师原文不一致')
    with tempfile.TemporaryDirectory(prefix='industrial_check_') as temp:
        generated = preprocess(data.input('01_preprocess', 'raw_ai4i2020.csv'),
                               Path(temp) / 'reproduced',
                               json.loads(data.file('manifest.json').read_text())['seed'],
                               data.input('01_preprocess', 'split_assignments.json'))
        for name in ('train_meta.json', 'validation_inputs.jsonl', 'validation_labels.jsonl',
                     'test_inputs.jsonl', 'test_labels.jsonl', 'source_provenance.jsonl'):
            if generated.file(name).read_bytes() != data.file(name).read_bytes():
                raise ValueError(f'预处理重现不一致：{name}')
        # 新划分重现时改为读取固定表，方法名称会变，数据、种子和类别统计须相同。
        for key in ('seed', 'raw_sha256', 'counts', 'label_counts', 'duplicate_physical_inputs'):
            original = json.loads(data.file('manifest.json').read_text())
            reproduced = json.loads(generated.file('manifest.json').read_text())
            if original[key] != reproduced[key]:
                raise ValueError(f'预处理清单重现不一致：{key}')
        finalize(generated, meta, audits, raw)
        for name in ('train_sft.jsonl', 'final_review_decisions.jsonl', 'review_summary.json'):
            if generated.file(name).read_bytes() != data.file(name).read_bytes():
                raise ValueError(f'审阅重现不一致：{name}')
    metrics_path = data.file('validation_metrics.json')
    if metrics_path.exists():
        saved = json.loads(metrics_path.read_text())
        with contextlib.redirect_stdout(io.StringIO()):
            for key, deterministic in [('all_classes', False), ('deterministic_classes', True)]:
                computed = score(data, data.file('validation_predictions.jsonl'), 'validation', deterministic)
                if computed != saved[key]:
                    raise ValueError(f'验证指标重算不一致：{key}')
    registry = json.loads((ROOT / 'data/dataset_info.json').read_text())
    if root.resolve() == DATA.resolve():
        if (ROOT / 'data' / registry['industrial_sft']['file_name']).resolve() != data.file('train_sft.jsonl').resolve():
            raise ValueError('训练注册路径不一致')
    summary = json.loads(data.file('review_summary.json').read_text())
    decisions = read_jsonl(data.file('final_review_decisions.jsonl'))
    if sum(row['status'] == 'accept' for row in decisions) != len(clean):
        raise ValueError('正式训练数据混入了未通过的报告')
    print('一致性检查通过：链接有效，无跨集合重复或输入标签泄漏；预处理、审阅和指标可重现。')
    print(f"事件 {dict((key, len(rows)) for key, rows in inputs.items())}；SFT {len(clean)} 条；裁定 {summary['status_counts']}")
    training = data.file('train_results.json')
    if training.exists():
        source = json.loads(training.read_text()).get('training_data')
        if source and source['sha256'] != hashlib.sha256(data.file('train_sft.jsonl').read_bytes()).hexdigest():
            print(f"既有模型使用历史 {source['samples']} 条训练数据；当前自动筛选结果尚未用于重训。")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=DATA)
    check(parser.parse_args().data_dir)
