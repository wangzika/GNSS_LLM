#!/usr/bin/env python3
"""Run the trained local adapter on reserved inputs without reading their labels."""
import argparse
import json
import re
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.industrial.step1_prepare_inputs import LABELS
from scripts.common.step2_validate_and_pack import SYSTEM_PROMPTS

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data/industrial_v1"
ADAPTER = ROOT / "outputs/industrial/qwen2.5-3b-industrial-v1-lora"


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


def build_messages(payload, layout):
    """alpaca 与训练转换器一致：instruction + 换行 + input 均位于 user 中。"""
    instruction = SYSTEM_PROMPTS["industrial"]
    if layout == "legacy":
        return [{"role": "user", "content": payload}], instruction
    return [{"role": "user", "content": instruction + "\n" + payload}], None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("validation", "test"), default="validation")
    parser.add_argument("--data-dir", type=Path, default=DATA)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--adapter", type=Path, default=ADAPTER)
    parser.add_argument("--base-only", action="store_true", help="只运行基础模型，供与微调结果比较")
    parser.add_argument("--prompt-layout", choices=("alpaca", "legacy"), default="alpaca",
                        help="默认与实际训练消息位置一致；legacy 复现早期 system/user 布局")
    parser.add_argument("--base-model", default="Qwen/Qwen2.5-3B-Instruct")
    parser.add_argument("--max-new-tokens", type=int, default=512)
    args = parser.parse_args()
    if not args.base_only and not (args.adapter / "adapter_config.json").exists():
        raise SystemExit(f"尚无正式训练适配器：{args.adapter}")
    inputs = args.data_dir / f"{args.split}_inputs.jsonl"
    output = args.out or args.data_dir / f"{args.split}_predictions.jsonl"
    if output.exists():
        raise SystemExit(f"预测文件已存在，请另选 --out，避免覆盖：{output}")
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
    output.with_name(output.name + ".meta.json").write_text(json.dumps({
        "base_model": args.base_model, "adapter": None if args.base_only else str(args.adapter),
        "prompt_layout": args.prompt_layout, "split": args.split,
        "max_new_tokens": args.max_new_tokens, "do_sample": False,
        "uses_ground_truth": False, "adds_rule_features": False,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with inputs.open(encoding="utf-8") as source, output.open("w", encoding="utf-8") as target:
        for line in source:
            if not line.strip():
                continue
            row = json.loads(line)
            payload = json.dumps(row["input"], ensure_ascii=False, separators=(",", ":"))
            messages, system = build_messages(payload, args.prompt_layout)
            response = model.chat(messages, system=system,
                                  max_new_tokens=args.max_new_tokens, do_sample=False)[0]
            report = response.response_text.strip()
            target.write(json.dumps({"event_id": row["event_id"],
                                     "predicted_label": extract_label(report),
                                     "report": report}, ensure_ascii=False) + "\n")
            target.flush()
            print(row["event_id"], "标签已提取" if extract_label(report) else "标签未识别")
    print(f"预测已保存：{output}")


if __name__ == "__main__":
    main()
