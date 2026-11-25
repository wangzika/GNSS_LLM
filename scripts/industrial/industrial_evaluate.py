#!/usr/bin/env python3
"""Score real model predictions against the reserved industrial pilot split."""
import argparse
import json
import re
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.common.step2_validate_and_pack import NUM_RE, numbers
from scripts.industrial.step1_prepare_inputs import LABELS
from scripts.industrial.workflow_paths import WorkflowPaths
from scripts.industrial.industrial_generate_teacher import derived_measurements

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA = ROOT / "data/industrial_v2"


def read_jsonl(path):
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def keyed(rows, path):
    result = {}
    for row in rows:
        event_id = row["event_id"]
        if event_id in result:
            raise ValueError(f"{path} 中事件 ID 重复：{event_id}")
        result[event_id] = row
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--split", choices=("validation", "test"), default="test")
    parser.add_argument("--predictions", type=Path, required=True,
                        help="JSONL: event_id, predicted_label, report")
    parser.add_argument("--deterministic-only", action="store_true",
                        help="仅统计真实标签为 HDF/PWF/OSF 的三类子集；仍要求提供完整留出集预测")
    parser.add_argument("--summary-json", type=Path, help="另存统计结果，便于比较基础模型和微调模型")
    args = parser.parse_args()
    layout = WorkflowPaths(args.data_dir)
    inputs_path = layout.input("06_evaluation", f"{args.split}_inputs.jsonl")
    labels_path = layout.input("06_evaluation", f"{args.split}_labels.jsonl")
    inputs = keyed(read_jsonl(inputs_path), inputs_path)
    labels = keyed(read_jsonl(labels_path), labels_path)
    predictions = keyed(read_jsonl(args.predictions), args.predictions)
    if set(inputs) != set(labels) or set(predictions) != set(labels):
        missing = sorted(set(labels) - set(predictions))
        extra = sorted(set(predictions) - set(labels))
        raise ValueError(f"事件集合不一致；缺失预测：{missing}；多余预测：{extra}")
    if not any(isinstance(row.get("report"), str) and row["report"].strip() for row in predictions.values()):
        raise ValueError("所有报告均为空，不能评估空白预测模板")
    all_count = len(labels)
    if args.deterministic_only:
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
    print(f"{args.split}: {total} 条；故障类别准确率 {correct}/{total} = {correct / total:.1%}")
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
    args.summary_json = args.summary_json or layout.file(
        f"{args.split}_metrics" + ("_three_classes" if args.deterministic_only else "") + ".json")
    if args.summary_json:
        args.summary_json.parent.mkdir(parents=True, exist_ok=True)
        args.summary_json.write_text(json.dumps({
            "split": args.split, "deterministic_only": args.deterministic_only,
            "full_split_count": all_count, "evaluated_count": total,
            "correct": correct, "accuracy": correct / total, "macro_f1": macro_f1,
            "invalid_label_count": invalid_labels,
            "report_complete_count": complete_reports, "numeric_coverage_count": numeric_coverage,
            "derived_report_count": derived_report_count,
            "derived_error_report_count": derived_error_report_count,
            "derived_error_details": derived_error_details,
            "per_class": per_class,
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("注意：这是小样本流程检查，不是泛化能力证明。")


if __name__ == "__main__":
    main()
