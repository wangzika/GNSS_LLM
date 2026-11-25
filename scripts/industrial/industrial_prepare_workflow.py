#!/usr/bin/env python3
"""将已有的 AI4I 先导样本划分为训练、验证、测试集。

本脚本读取 step1_meta_records.json，不读取旧版 step1_input_prompts.txt。
训练集生成无答案的教师提示词；验证集和测试集分别保存输入与标签。
"""
import argparse
import json
import random
from collections import Counter, defaultdict
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.industrial.workflow_paths import WorkflowPaths

# 默认从项目 data 目录读取完整元数据，结果写到独立的 industrial_v1 目录。
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_META = ROOT / "data/industrial_source/step1_meta_records.json"
DEFAULT_OUT = ROOT / "data/industrial_v1"


def write_json(path, value):
    """将单个对象写成易读的 JSON 文件。"""
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path, rows):
    """将多条记录逐行写入 JSONL，便于后续逐条读取。"""
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")


def model_input(rec):
    """去掉真实标签、案例类型和来源，只保留模型应看到的监测输入。"""
    return {key: value for key, value in rec.items()
            if key not in {"ground_truth_intent", "case_type", "data_source"}}


def allocate(groups, target):
    """给各故障类别分配目标集名额，并尽量兼顾原始类别比例。"""
    sizes = {label: len(items) for label, items in groups.items()}
    if target < len(groups):
        raise ValueError("目标集太小，无法包含每种故障类型")
    # 每类先分配 1 条，保证目标集包含所有已有故障类别。
    quotas = {label: 1 for label in groups}
    while sum(quotas.values()) < target:
        # 每类至少留下 2 条，供另外两个数据划分使用。
        eligible = [label for label in groups if quotas[label] < sizes[label] - 2]
        if not eligible:
            raise ValueError("样本量不足，无法保留训练、验证、测试三个划分")
        # 优先补给当前名额比按原比例计算的期望名额少得最多的类别。
        label = max(eligible, key=lambda x: (sizes[x] * target / sum(sizes.values()) - quotas[x], x))
        quotas[label] += 1
    return quotas


def split(records, seed):
    """按故障标签分层打乱，返回互不重叠的训练/验证/测试记录。"""
    groups = defaultdict(list)
    for rec in records:
        groups[rec["ground_truth_intent"]].append(rec)
    if any(len(items) < 3 for items in groups.values()):
        raise ValueError("每种故障至少需要 3 条样本才能分别进入训练、验证、测试")
    # 此处的 seed 控制划分；它独立于 step1_prepare_inputs.py 的采样种子。
    rng = random.Random(seed)
    for items in groups.values():
        rng.shuffle(items)
    total = len(records)
    # 先预留约 20% 测试集，再从剩余样本预留约 10% 总量作验证集。
    test_quota = allocate(groups, round(total * 0.2))
    remaining = {label: items[test_quota[label]:] for label, items in groups.items()}
    val_quota = allocate(remaining, round(total * 0.1))
    result = {"train": [], "validation": [], "test": []}
    for label, items in groups.items():
        ntest, nval = test_quota[label], val_quota[label]
        result["test"].extend(items[:ntest])
        result["validation"].extend(items[ntest:ntest + nval])
        result["train"].extend(items[ntest + nval:])
    # 随机划分后按事件 ID 排序，使输出文件便于查找和比较。
    for items in result.values():
        items.sort(key=lambda rec: rec["event_meta"]["event_id"])
    return result


def write_prompts(path, records, batch_size):
    """仅对训练集生成分批的无答案教师提示词。"""
    with path.open("w", encoding="utf-8") as stream:
        for start in range(0, len(records), batch_size):
            stream.write(f"===== 教师第 {start // batch_size + 1} 批 =====\n")
            stream.write(
                "请根据监测特征独立判断工业设备故障类别。每条样本输出一个独立的 "
                "```markdown 代码块，包含事件 ID、<think>中的简短排除依据、"
                "### 监测事件意图推理报告、### 关键支撑证据链。"
                "证据链须原样引用所有 physical_features 数值。"
                "空间上下文缺失时说明局限、置信度不高于65%及补充排查建议；"
                "待机区与物理读数矛盾时说明“物理强证据覆盖环境弱证据”。"
                "请勿假定车间区域和运行模式是真实测量或故障成因。\n\n"
            )
            for rec in records[start:start + batch_size]:
                # 提示词只写 model_input，教师看不到 ground_truth_intent。
                payload = json.dumps(model_input(rec), ensure_ascii=False, separators=(",", ":"))
                stream.write(f"--- {rec['event_meta']['event_id']} ---\n{payload}\n\n")


def main():
    """读取完整样本，检查事件 ID，划分并写出各阶段所需文件。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--meta", type=Path, default=DEFAULT_META)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--batch-size", type=int, default=5)
    args = parser.parse_args()
    if args.batch_size <= 0:
        parser.error("--batch-size 必须为正数")
    # 元数据含真实标签，仅用于划分和事后核对，不应直接交给教师模型。
    records = json.loads(args.meta.read_text(encoding="utf-8"))
    ids = [rec["event_meta"]["event_id"] for rec in records]
    if len(ids) != len(set(ids)):
        raise ValueError("输入含重复事件 ID")
    parts = split(records, args.seed)
    layout = WorkflowPaths(args.out_dir)
    layout.initialize()
    if layout.structured:
        write_json(layout.file("events_meta.json"), records)
    # 训练集内部元数据保留标签，供下一步质检教师报告。
    write_json(layout.file("train_meta.json"), parts["train"])
    for part in ("validation", "test"):
        # 留出集的纯输入与参考标签分开存，推断时只读取 *_inputs.jsonl。
        write_jsonl(layout.file(f"{part}_inputs.jsonl"),
                    [{"event_id": rec["event_meta"]["event_id"], "input": model_input(rec)}
                     for rec in parts[part]])
        write_jsonl(layout.file(f"{part}_labels.jsonl"),
                    [{"event_id": rec["event_meta"]["event_id"],
                      "ground_truth_intent": rec["ground_truth_intent"]}
                     for rec in parts[part]])
    write_prompts(layout.file("teacher_prompts_blind.txt"), parts["train"], args.batch_size)
    # 清单记录划分参数、各集数量及数据限制，便于复核来源。
    write_json(layout.file("manifest.json"), {
        "source_meta": str(args.meta), "seed": args.seed,
        "counts": {name: len(items) for name, items in parts.items()},
        "label_counts": {name: dict(Counter(rec["ground_truth_intent"] for rec in items))
                         for name, items in parts.items()},
        "warning": "运行模式和车间区域是随机模拟字段；本划分仅供流程开发，不能证明泛化能力。",
    })
    print("已准备工业故障流程：" + ", ".join(f"{k}={len(v)}" for k, v in parts.items()))


if __name__ == "__main__":
    main()
