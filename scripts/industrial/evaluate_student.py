#!/usr/bin/env python3
"""学生推断与评估的唯一入口：--mode run / predict / score。

run 生成报告并评分，predict 只推断，score 只使用已有预测评分（无需 GPU）。
全类别与 HDF/PWF/OSF 三类指标统一写入一个 metrics.json，含推断配置与文件哈希。
"""
import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.industrial.common import (
    ROOT, DATA, WorkflowPaths, LABELS, STUDENT_INSTRUCTION,
    NUM_RE, numbers, derived_measurements, read_jsonl, write_json,
)
ADAPTER = ROOT / 'outputs/industrial/qwen2.5-3b-industrial-v2-lora'


def extract_label(report):
    match = re.search(r"(?:^|\n)\s*(?:#{1,6}\s*)?结论\s*[：:]\s*([^\n。；;]+)", report)
    if not match:
        return ""
    line = match.group(1).strip().strip("* ")
    # 与训练数据质检保持一致：中文类别名可规范化为完整名称。
    # 仅接受结论开头的类别，避免将“不是某类”或分析段的提及误当作预测。
    hits = [label for label in LABELS.values()
            if line.startswith(label) or line.startswith(label.split(" (", 1)[0])]
    return hits[0] if len(hits) == 1 else ""

def build_messages(payload):
    """与 SFT 训练一致，instruction 与 input 同在 user 消息中。"""
    return [{'role': 'user', 'content': STUDENT_INSTRUCTION + '\n' + payload}]


def predict(args, layout):
    if not args.base_only and not (args.adapter / "adapter_config.json").exists():
        raise SystemExit(f"尚无正式训练适配器：{args.adapter}")
    inputs = layout.input("05_evaluation", f"{args.split}_inputs.jsonl")
    output = args.predictions
    if output.exists():
        raise SystemExit(f"预测文件已存在，请另选 --predictions，避免覆盖：{output}")
    from llamafactory.chat import ChatModel

    model_config = {
        "model_name_or_path": args.base_model,
        "template": "qwen",
        "finetuning_type": "lora",
        "quantization_bit": 4,
        "quantization_method": "bnb",
    }
    if not args.base_only:
        model_config["adapter_name_or_path"] = str(args.adapter)
    model = ChatModel(model_config)
    output.parent.mkdir(parents=True, exist_ok=True)
    write_json(args.summary_json, {'status': 'generating', 'inference': {
        'base_model': args.base_model, 'adapter': None if args.base_only else str(args.adapter),
        'prompt_layout': 'alpaca', 'split': args.split,
        'max_new_tokens': args.max_new_tokens, 'do_sample': False,
        'uses_ground_truth': False, 'adds_rule_features': False,
    }})
    with inputs.open(encoding="utf-8") as source, output.open("w", encoding="utf-8") as target:
        for line in source:
            if not line.strip():
                continue
            row = json.loads(line)
            payload = json.dumps(row["input"], ensure_ascii=False, separators=(",", ":"))
            messages = build_messages(payload)
            response = model.chat(messages, system=None,
                                  max_new_tokens=args.max_new_tokens, do_sample=False)[0]
            report = response.response_text.strip()
            target.write(json.dumps({"event_id": row["event_id"],
                                     "predicted_label": extract_label(report),
                                     "report": report}, ensure_ascii=False) + "\n")
            target.flush()
            print(row["event_id"], "标签已提取" if extract_label(report) else "标签未识别")
    print(f"预测已保存：{output}")

def keyed(rows, path):
    result = {}
    for row in rows:
        event_id = row["event_id"]
        if event_id in result:
            raise ValueError(f"{path} 中事件 ID 重复：{event_id}")
        result[event_id] = row
    return result

def score(layout, predictions_path, split, deterministic=False):
    inputs_path = layout.input("05_evaluation", f"{split}_inputs.jsonl")
    labels_path = layout.input("05_evaluation", f"{split}_labels.jsonl")
    inputs = keyed(read_jsonl(inputs_path), inputs_path)
    labels = keyed(read_jsonl(labels_path), labels_path)
    predictions = keyed(read_jsonl(predictions_path), predictions_path)
    if set(inputs) != set(labels) or set(predictions) != set(labels):
        missing = sorted(set(labels) - set(predictions))
        extra = sorted(set(predictions) - set(labels))
        raise ValueError(f"事件集合不一致；缺失预测：{missing}；多余预测：{extra}")
    if not any(isinstance(row.get("report"), str) and row["report"].strip() for row in predictions.values()):
        raise ValueError("所有报告均为空，不能评估空白预测模板")
    all_count = len(labels)
    if deterministic:
        selected = {LABELS[k] for k in ("HDF", "PWF", "OSF")}
        labels = {eid: row for eid, row in labels.items() if row["ground_truth_intent"] in selected}
    if not labels:
        raise ValueError("所选评估子集为空")
    classes = sorted({row["ground_truth_intent"] for row in labels.values()})
    # 空标签、未识别标签按失败计入准确率，不因输出格式不合格而中止整批评估。
    invalid_labels = sum(predictions[eid].get("predicted_label") not in LABELS.values() for eid in labels)
    correct = 0
    complete_reports = 0
    numeric_coverage = 0
    derived_report_count = 0
    derived_error_report_count = 0
    derived_error_details = []
    for eid, gold in labels.items():
        pred = predictions[eid]
        correct += pred.get("predicted_label") == gold["ground_truth_intent"]
        report = pred.get("report", "")
        complete_reports += ("### 监测事件意图推理报告" in report
                             and "### 关键支撑证据链" in report)
        evidence = report.split("### 关键支撑证据链", 1)[-1] if "### 关键支撑证据链" in report else ""
        expected = numbers(inputs[eid]["input"].get("physical_features", {}))
        numeric_coverage += expected.issubset(set(NUM_RE.findall(evidence)))
        # 原始数字被抄出并不代表计算正确；另核对报告明确列出的 AI4I 派生量。
        observation = inputs[eid]["input"]
        features = observation.get("physical_features", {})
        required = {"air_temp_k", "process_temp_k", "rotational_speed_rpm", "torque_nm", "tool_wear_min"}
        if required.issubset(features) and observation.get("event_meta", {}).get("equipment_grade") in ("L", "M", "H"):
            computed = derived_measurements(observation)
            found, errors = False, []
            for key in ("temperature_gap_k", "shaft_power_w", "wear_torque_min_nm", "overstrain_limit_min_nm"):
                values = re.findall(r"(?m)^\s*-\s*" + key + r"\s*[:=]\s*(-?\d+(?:\.\d+)?)", evidence)
                found = found or bool(values)
                for value in values:
                    if abs(float(value) - computed[key]) > 0.11:
                        errors.append({"field": key, "reported": float(value), "recomputed": computed[key]})
            derived_report_count += found
            derived_error_report_count += bool(errors)
            if errors:
                derived_error_details.append({"event_id": eid, "errors": errors})
    total = len(labels)
    print(f"{split}: {total} 条；故障类别准确率 {correct}/{total} = {correct / total:.1%}")
    print(f"报告标题完整 {complete_reports}/{total}；证据链数值引用完整 {numeric_coverage}/{total}")
    print(f"评估范围 {total}/{all_count}；未识别/空标签 {invalid_labels} 条（计为错误）")
    print(f"列出可核对派生量 {derived_report_count}/{total}；其中存在数值错误 {derived_error_report_count} 条")
    per_class = {}
    for label in classes:
        ids = [eid for eid, row in labels.items() if row["ground_truth_intent"] == label]
        hit = sum(predictions[eid].get("predicted_label") == label for eid in ids)
        predicted_count = sum(predictions[eid].get("predicted_label") == label for eid in labels)
        precision = hit / predicted_count if predicted_count else 0.0
        recall = hit / len(ids)
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class[label] = {"support": len(ids), "correct": hit, "precision": precision, "recall": recall, "f1": f1}
        print(f"{label}: {hit}/{len(ids)}；F1={f1:.3f}")
    macro_f1 = sum(row["f1"] for row in per_class.values()) / len(per_class)
    print(f"Macro-F1={macro_f1:.3f}")
    return {
            "split": split, "deterministic_only": deterministic,
            "full_split_count": all_count, "evaluated_count": total,
            "correct": correct, "accuracy": correct / total, "macro_f1": macro_f1,
            "invalid_label_count": invalid_labels,
            "report_complete_count": complete_reports, "numeric_coverage_count": numeric_coverage,
            "derived_report_count": derived_report_count,
            "derived_error_report_count": derived_error_report_count,
            "derived_error_details": derived_error_details,
            "per_class": per_class,
        }

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('run', 'predict', 'score'), default='score')
    parser.add_argument('--data-dir', type=Path, default=DATA)
    parser.add_argument('--split', choices=('validation', 'test'), default='validation')
    parser.add_argument('--predictions', type=Path, help='预测文件；run/predict 为输出，score 为输入')
    parser.add_argument('--summary-json', type=Path, help='合并保存推断配置、全类别与三类指标')
    parser.add_argument('--adapter', type=Path, default=ADAPTER)
    parser.add_argument('--base-only', action='store_true', help='只运行基础模型，供与微调比较')
    parser.add_argument('--base-model', default='Qwen/Qwen2.5-3B-Instruct')
    parser.add_argument('--max-new-tokens', type=int, default=512)
    args = parser.parse_args()
    if args.max_new_tokens < 1:
        parser.error('--max-new-tokens 必须为正数')
    layout = WorkflowPaths(args.data_dir)
    args.predictions = args.predictions or layout.file(f'{args.split}_predictions.jsonl')
    metrics_name = args.predictions.stem.replace('predictions', 'metrics')
    if metrics_name == args.predictions.stem:
        metrics_name += '_metrics'
    args.summary_json = args.summary_json or layout.output_dir('05_evaluation') / (metrics_name + '.json')
    if args.predictions.resolve() == args.summary_json.resolve():
        parser.error('预测与指标不能使用同一文件')
    if args.mode in ('run', 'predict'):
        predict(args, layout)
    if args.mode in ('run', 'score'):
        sha = hashlib.sha256(args.predictions.read_bytes()).hexdigest()
        previous = json.loads(args.summary_json.read_text()) if args.summary_json.exists() else {}
        inference = previous.get('inference') if previous.get('predictions_sha256', sha) == sha else None
        print('全部故障类别：')
        all_classes = score(layout, args.predictions, args.split)
        print('可观测三类子集：')
        deterministic = score(layout, args.predictions, args.split, deterministic=True)
        labels = read_jsonl(layout.input('05_evaluation', f'{args.split}_labels.jsonl'))
        counts = Counter(r['ground_truth_intent'] for r in labels)
        predictions = read_jsonl(args.predictions)
        write_json(args.summary_json, {
            'split': args.split, 'status': 'evaluated', 'predictions_sha256': sha,
            'inference': inference, 'all_classes': all_classes,
            'deterministic_classes': deterministic,
            'majority_baseline': {'label': counts.most_common(1)[0][0],
                                  'accuracy': max(counts.values()) / len(labels)},
            'predicted_label_counts': dict(Counter(r.get('predicted_label', '') for r in predictions)),
        })
        print(f'合并指标：{args.summary_json}')
        print('注意：当前为小样本流程实验，不是泛化能力证明。')


if __name__ == '__main__':
    main()
