#!/usr/bin/env python3
"""从 AI4I 数据准备故障实验样本；无需第三方 Python 包。

输出的元数据保留真实标签；随后由 industrial_prepare_workflow.py 划分并生成无答案提示词。
"""
import argparse
import csv
import json
import random
import urllib.request
from pathlib import Path

# 所有路径以项目根目录为基准，避免从不同工作目录运行时写错位置。
ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data/industrial_source"
CSV_PATH = DATA / "raw_ai4i2020.csv"
UCI_URL = "https://archive.ics.uci.edu/ml/machine-learning-databases/00601/ai4i2020.csv"
# AI4I 原始 CSV 中的故障列名及本项目使用的中文标签。
LABELS = {
    "TWF": "工具严重磨损故障 (Tool Wear Failure)",
    "HDF": "散热系统失效故障 (Heat Dissipation Failure)",
    "PWF": "驱动电力异常故障 (Power Failure)",
    "OSF": "机械负载过载故障 (Overstrain Failure)",
    "RNF": "偶发性随机系统故障 (Random Failure)",
}
# 仅在生成规则合成样本时使用；这些范围不是 UCI 原始测量值或故障判定阈值。
# 每行顺序：故障代码、空气温度[K]、过程温度[K]、转速[rpm]、扭矩[N·m]、刀具磨损[min]。
# 每个二元组是随机取值的最小值和最大值；此处未给 RNF（随机故障）设置合成场景。
SCENARIOS = [
    ("HDF", (302.0, 304.5), (309.5, 312.0), (1250, 1380), (40.0, 55.0), (20, 150)),  # 散热失效
    ("OSF", (297.0, 300.0), (307.0, 310.0), (1150, 1350), (58.0, 72.0), (190, 240)),  # 机械过载
    ("PWF", (298.0, 301.0), (308.0, 310.5), (2500, 2880), (8.0, 16.0), (10, 180)),   # 驱动电力异常
    ("TWF", (297.5, 300.5), (307.5, 310.0), (1400, 1750), (30.0, 48.0), (210, 250)),  # 刀具磨损
]


def read_uci():
    """读取 UCI CSV，只保留发生故障且恰好只有一种故障标签的行。"""
    # 本地没有原始 CSV 时才尝试下载；已有文件不会被覆盖。
    if not CSV_PATH.exists():
        urllib.request.urlretrieve(UCI_URL, CSV_PATH)
    with CSV_PATH.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        # 在筛选前验证列名，避免数据集版本不符导致误读。
        required = {"Type", "Air temperature [K]", "Process temperature [K]",
                    "Rotational speed [rpm]", "Torque [Nm]", "Tool wear [min]",
                    "Machine failure", *LABELS}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("AI4I CSV 缺少必要列")
        rows = []
        for row in reader:
            # 非故障行不用于这个故障类型先导实验。
            if row["Machine failure"] != "1":
                continue
            active = [key for key in LABELS if row[key] == "1"]
            # 多故障行无法作为唯一类别标签，故只保留恰好命中一列的行。
            if len(active) == 1:
                rows.append((row, active[0]))
    return rows


def make_record(row, label_key, event_id, rng, source):
    """把一行 UCI 数据或一个合成场景转换为统一的事件记录。"""
    if row is None:
        # 合成分支：按 SCENARIOS 范围随机生成五项测量值和产品类别。
        _, air, process, rpm, torque, wear = next(s for s in SCENARIOS if s[0] == label_key)
        features = {
            "air_temp_k": round(rng.uniform(*air), 1),
            "process_temp_k": round(rng.uniform(*process), 1),
            "rotational_speed_rpm": rng.randint(*rpm),
            "torque_nm": round(rng.uniform(*torque), 1),
            "tool_wear_min": rng.randint(*wear),
        }
        grade = rng.choice("LMH")
    else:
        # 真实数据分支：直接读取 CSV 测量值；Type 为产品质量类别 L/M/H。
        features = {
            "air_temp_k": float(row["Air temperature [K]"].strip()),
            "process_temp_k": float(row["Process temperature [K]"].strip()),
            "rotational_speed_rpm": int(row["Rotational speed [rpm]"].strip()),
            "torque_nm": float(row["Torque [Nm]"].strip()),
            "tool_wear_min": int(row["Tool wear [min]"].strip()),
        }
        grade = row["Type"]
    return {
        "ground_truth_intent": LABELS[label_key],
        "data_source": source,
        "event_meta": {"event_id": event_id, "equipment_grade": grade},
        "physical_features": features,
        # AI4I 不提供运行模式和车间区域；这两个字段始终是随机模拟上下文。
        "spatial_context": {
            "operating_mode": rng.choice(["Continuous_Load", "Peak_Shift", "Standard_Cycle"]),
            "workshop_zone": rng.choice(["Line_A_Stamping", "Line_B_CNC", "Line_C_Assembly"]),
        },
    }


def main():
    """解析参数，选择真实/合成来源，构造案例并写出元数据。"""
    parser = argparse.ArgumentParser()
    # auto：优先 UCI，失败后回退合成；uci：失败即报错；synthetic：只用规则合成。
    parser.add_argument("--source", choices=("auto", "uci", "synthetic"), default="auto")
    parser.add_argument("--count", type=int, default=50)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    # 10 的倍数使后面的 70%/20%/10% 案例数量都为整数。
    if args.count <= 0 or args.count % 10:
        parser.error("--count 必须为 10 的正整数")
    DATA.mkdir(parents=True, exist_ok=True)
    # 固定种子便于复现抽样、合成特征及模拟上下文。
    rng = random.Random(args.seed)
    source = "uci_ai4i2020"
    rows = None
    if args.source != "synthetic":
        try:
            rows = read_uci()
            if len(rows) < args.count:
                raise ValueError(f"单一故障样本不足：{len(rows)} < {args.count}")
        except Exception as exc:
            # 用户明确指定 uci 时保留错误；auto 模式才允许回退。
            if args.source == "uci":
                raise
            print(f"UCI 获取失败，使用显式标记的合成数据：{exc}")
    if rows is None:
        # 用四种预设场景循环生成；来源字段会明确标记为合成。
        source = "synthetic_rule_based"
        rows = [(None, SCENARIOS[i % len(SCENARIOS)][0]) for i in range(args.count)]
        rng.shuffle(rows)
    else:
        # 从合格的 UCI 行中无放回随机抽取所需条数。
        rows = rng.sample(rows, args.count)
    records = []
    for idx, (row, label) in enumerate(rows):
        rec = make_record(row, label, f"EVT-20261116-{idx + 1:04d}", rng, source)
        # 70% 常规、20% 缺失上下文、10% 冲突证据；修改的是模拟上下文。
        if idx < args.count * 7 // 10:
            rec["case_type"] = "STANDARD"
        elif idx < args.count * 9 // 10:
            rec["case_type"] = "MISSING_CONTEXT"
            rec["spatial_context"] = {"operating_mode": None, "workshop_zone": None}
        else:
            rec["case_type"] = "CONFLICTING_EVIDENCE"
            rec["spatial_context"]["workshop_zone"] = "Idle_Standby_Bay"
        records.append(rec)
    # 保存内部带标签元数据，教师请求不会直接发送此文件。
    (DATA / "step1_meta_records.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已生成 {len(records)} 条：35/10/5 比例随 --count 缩放；来源 {source}；目录 {DATA}")


if __name__ == "__main__":
    main()
