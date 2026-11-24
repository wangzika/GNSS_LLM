#!/usr/bin/env python3
"""Prepare GNSS teacher batches from already labelled, physically checked JSONL."""
import argparse
import json
import random
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "gnss"
RATIOS = {"STANDARD": 7, "MISSING_CONTEXT": 2, "CONFLICTING_EVIDENCE": 1}
EVENT_RE = re.compile(r"^EVT-\d{8}-\d{4}$")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="人工标注并核查物理约束的 GNSS JSONL")
    parser.add_argument("--count", type=int, default=2500)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--batch-size", type=int, default=5)
    args = parser.parse_args()
    if args.count <= 0 or args.count % 10 or args.batch_size <= 0:
        parser.error("--count 必须为 10 的正整数，--batch-size 必须为正数")
    rows = []
    with args.input.open(encoding="utf-8") as stream:
        for line_no, line in enumerate(stream, 1):
            if not line.strip():
                continue
            rec = json.loads(line)
            for key in ("ground_truth_intent", "event_meta", "case_type"):
                if key not in rec:
                    raise ValueError(f"第 {line_no} 行缺少 {key}")
            eid = rec["event_meta"].get("event_id", "")
            if not EVENT_RE.fullmatch(eid):
                raise ValueError(f"第 {line_no} 行事件 ID 不符合 EVT-YYYYMMDD-NNNN: {eid}")
            if rec["case_type"] not in RATIOS:
                raise ValueError(f"第 {line_no} 行样本类型无效")
            if rec["case_type"] == "MISSING_CONTEXT":
                context = rec.get("spatial_context")
                nested_location = context.get("jammer_location", "present") if isinstance(context, dict) else "present"
                location = rec.get("jammer_location", nested_location)
                if location is not None:
                    raise ValueError(f"第 {line_no} 行缺失上下文样本应设 jammer_location=null")
            rows.append(rec)
    ids = [r["event_meta"]["event_id"] for r in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("输入含重复事件 ID")
    rng = random.Random(args.seed)
    selected = []
    for case_type, ratio in RATIOS.items():
        pool = [r for r in rows if r["case_type"] == case_type]
        needed = args.count * ratio // 10
        if len(pool) < needed:
            raise ValueError(f"{case_type} 仅有 {len(pool)} 条，至少需要 {needed} 条")
        selected.extend(rng.sample(pool, needed))
    rng.shuffle(selected)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "step1_meta_records.json").write_text(
        json.dumps(selected, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    prompts = OUT / "step1_input_prompts.txt"
    with prompts.open("w", encoding="utf-8") as stream:
        for offset in range(0, len(selected), args.batch_size):
            stream.write(f"===== 第 {offset // args.batch_size + 1} 批 =====\n")
            stream.write(
                "你是 GNSS 干扰事件分析员。每条记录输出单独的 ```markdown 代码块，"
                "包含事件 ID、<think>...</think> 中的简短排除依据、"
                "### 监测事件意图推理报告 和 ### 关键支撑证据链。"
                "证据链须原样引用输入中的所有测量数字和频段字符串。"
                "jammer_location 缺失时用“置信度：60%”这类格式给出不高于65%的置信度并说明补充观测；"
                "冲突样本说明“物理强证据覆盖环境弱证据”。"
                "真实结论仅供核对，不得作为输入特征。\n\n"
            )
            for rec in selected[offset:offset + args.batch_size]:
                clean = {k: v for k, v in rec.items() if k not in
                         ("ground_truth_intent", "case_type", "data_source")}
                stream.write(f"--- 样本 {rec['event_meta']['event_id']} [{rec['case_type']}] ---\n")
                stream.write(f"【监测特征 JSON】：{json.dumps(clean, ensure_ascii=False, separators=(',', ':'))}\n")
                stream.write(f"【真实意图结论】：{rec['ground_truth_intent']}\n\n")
    print(f"已选 {len(selected)} 条 GNSS 记录，类型分布 {dict(Counter(r['case_type'] for r in selected))}；提示词 {prompts}")


if __name__ == "__main__":
    main()
