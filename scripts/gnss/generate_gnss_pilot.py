#!/usr/bin/env python3
"""Generate provisional synthetic observations, private annotations and teacher batches.

These are workflow fixtures, not validated RF simulations or confirmed intent labels.
"""
import argparse
import hashlib
import json
import random
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "docs/reference/GNSS干扰意图大模型推理-思路.docx"
BANDS = {"L1": ("GPS", 1575.42), "B1I": ("BDS", 1561.098), "L2": ("GPS", 1227.6)}
PROFILES = {
    "personal_privacy_evasion": ("个人隐私逃避与防追踪", ["L1", "B1I"], "chirp", "not_detected", "mobile", "road_corridor"),
    "counter_uas_defensive": ("重要目标防护与低空防御", ["L1", "B1I"], "noise", "not_detected", "stationary", "event_venue"),
    "tactical_denial": ("战术性区域拒止", ["L1", "B1I", "L2"], "noise", "not_detected", "stationary", "open_area"),
    "malicious_hijacking": ("恶意诱导与导航劫持", ["L1", "B1I"], "gnss_like", "detected", "stationary", "waterway"),
    "unintentional_testing": ("非恶意测试外泄或设备异常", ["L1"], "tone", "unknown", "stationary", "research_park"),
}
CASES = ["STANDARD"] * 7 + ["MISSING_CONTEXT"] * 2 + ["CONFLICTING_EVIDENCE"]
PROMPT = """你是 GNSS 监测事件分析员。以下输入是虚构测试观测，未包含真实意图标签。
请只依据可见字段给出简短、可核查的分析依据，不要补写未提供的坐标、报备或历史记录。
received_power_dbm 是监测接收机端的功率，不能当作发射功率或直接换算覆盖半径。
not_detected 表示本次未检出，不代表确定不存在；unknown/null 表示不可用。
POI 和波形只能支持假设，不能据此确认行为主体或动机。证据不足时允许 inconclusive。
候选类别：personal_privacy_evasion、counter_uas_defensive、tactical_denial、malicious_hijacking、unintentional_testing。
每个事件返回一个独立的 ```json 代码块，使用以下结构：
{"event_id":"与输入一致","decision":"上述类别或inconclusive","certainty":"low或medium或high",
"rationale_summary":"简短说明支持依据与限制",
"alternatives":[{"intent":"候选类别","reason":"为何仍可能或支持较弱"}],
"evidence":[{"field":"输入内的字段路径，例如physical_features.signals[0].received_power_dbm","value":"复制该字段原有JSON值及类型","unit":"适用单位或null","interpretation":"这条观测支持什么、不能说明什么"}],
"missing_information":["仍需的观测或调查资料"]}
evidence.value 必须逐字段原样复制，禁止互换数值或单位。certainty 是未校准的证据充分程度描述，不是统计概率。
"""


def make_observation(intent, case, rng):
    _, bands, waveform, spoof_status, motion, poi = PROFILES[intent]
    speed = round(rng.uniform(35, 85), 1) if motion == "mobile" else 0.0
    obj = {
        "event_meta": {"event_id": "", "detection_timestamp": f"2026-11-{rng.randint(1, 15):02d}T{rng.randrange(24):02d}:00:00Z"},
        "physical_features": {
            "affected_systems": sorted({BANDS[b][0] for b in bands}),
            "signals": [{
                "band": b, "center_frequency_mhz": BANDS[b][1],
                "observed_bandwidth_mhz": 0.01 if waveform == "tone" else round(rng.uniform(0.5, 2.0), 2),
                "signal_classification": waveform,
                "received_power_dbm": round(rng.uniform(-105, -85), 1),
                "power_reference": "monitor_receiver_input",
            } for b in bands],
            "duration_seconds": rng.randint(60, 1800),
            "emission_pattern": rng.choice(["continuous", "intermittent"]),
        },
        "spoofing_features": {
            "detection_status": spoof_status,
            "position_offset_meters": round(rng.uniform(50, 500), 1) if spoof_status == "detected" else None,
            "position_offset_pattern": "gradual_drift" if spoof_status == "detected" else None,
            "clock_bias_seconds": None,
        },
        "spatial_context": {
            "coordinate_frame": "fictional_local_ENU_m",
            "jammer_location": {"east_m": rng.randint(-500, 500), "north_m": rng.randint(-500, 500)},
            "motion_state": motion, "speed_kmh": speed,
            "trajectory_trend": "along_road" if motion == "mobile" else "fixed_position",
            "gis_poi_match": [poi],
        },
        "temporal_context": {"recurrence_pattern": "unknown"},
        "historical_reference": None,
    }
    notes = ["意图是生成剧本设定，未经调查确认；观测只支持候选解释。"]
    if case == "MISSING_CONTEXT":
        obj["spatial_context"] = {
            "coordinate_frame": None, "jammer_location": None, "motion_state": "unknown",
            "speed_kmh": None, "trajectory_trend": None, "gis_poi_match": [],
        }
        notes.append("定位及其派生空间信息同时移除，允许无法区分候选意图。")
    elif case == "CONFLICTING_EVIDENCE":
        # Change the contextual cue, not the physical observation, to challenge POI shortcuts.
        obj["spatial_context"]["gis_poi_match"] = {
            "personal_privacy_evasion": ["event_venue", "road_corridor"],
            "counter_uas_defensive": ["research_park"],
            "tactical_denial": ["road_corridor"],
            "malicious_hijacking": ["research_park"],
            "unintentional_testing": ["event_venue"],
        }[intent]
        notes.append("POI 与典型场景先验不一致；不得由某个强特征强行确认动机。")
    return obj, notes


def validate_observation(obj):
    signals = obj["physical_features"]["signals"]
    assert signals and len({x["band"] for x in signals}) == len(signals)
    for signal in signals:
        assert signal["center_frequency_mhz"] == BANDS[signal["band"]][1]
        assert signal["observed_bandwidth_mhz"] > 0
        assert signal["power_reference"] == "monitor_receiver_input"
    assert obj["physical_features"]["affected_systems"] == sorted({BANDS[s["band"]][0] for s in signals})
    spatial = obj["spatial_context"]
    if spatial["jammer_location"] is None:
        assert spatial["speed_kmh"] is None and spatial["motion_state"] == "unknown"
        assert spatial["trajectory_trend"] is None and spatial["gis_poi_match"] == []
    elif spatial["motion_state"] == "stationary":
        assert spatial["speed_kmh"] == 0 and spatial["trajectory_trend"] == "fixed_position"
    else:
        assert spatial["speed_kmh"] > 0
    spoof = obj["spoofing_features"]
    if spoof["detection_status"] != "detected":
        assert spoof["position_offset_meters"] is None and spoof["position_offset_pattern"] is None
    assert set(obj) == {"event_meta", "physical_features", "spoofing_features", "spatial_context", "temporal_context", "historical_reference"}


def generate(seed, count):
    rng = random.Random(seed)
    records = []
    for intent in PROFILES:
        for i in range(count // 5):
            case = CASES[i % 10]
            obs, notes = make_observation(intent, case, rng)
            records.append({"input": obs, "annotation": {
                "scenario_intent": intent, "intent_label": PROFILES[intent][0],
                "case_type": case, "label_status": "synthetic_scenario_not_confirmed",
                "source": "document_based_provisional_generator_v1",
                "source_is_synthetic": True, "expert_reviewed": False,
                "acceptable_decision_policy": "Allow inconclusive and evidence-supported alternatives; do not force scenario_intent.",
                "review_notes": notes,
            }})
    rng.shuffle(records)
    for idx, record in enumerate(records, 1):
        record["input"]["event_meta"]["event_id"] = f"JAM-SYN-20261117-{idx:04d}"
        validate_observation(record["input"])
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=50)
    parser.add_argument("--seed", type=int, default=20261117)
    parser.add_argument("--out-dir", type=Path, default=ROOT / "data" / "gnss_pilot_v1")
    args = parser.parse_args()
    if args.count <= 0 or args.count % 50:
        parser.error("count 必须是 50 的正整数倍，确保每类均满足 7:2:1")
    records = generate(args.seed, args.count)
    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)
    def write_jsonl(name, values):
        (out / name).write_text(''.join(json.dumps(v, ensure_ascii=False) + '\n' for v in values), encoding="utf-8")
    write_jsonl("samples_with_annotations.jsonl", records)
    write_jsonl("inputs_only.jsonl", [r["input"] for r in records])
    preview = [next(r for r in records if r["annotation"]["scenario_intent"] == intent and r["annotation"]["case_type"] == "STANDARD") for intent in PROFILES]
    (out / "preview_5_cases.json").write_text(json.dumps(preview, ensure_ascii=False, indent=2) + '\n', encoding="utf-8")
    with (out / "teacher_prompts.txt").open("w", encoding="utf-8") as stream:
        for start in range(0, len(records), 5):
            stream.write(f"===== 批次 {start // 5 + 1} =====\n{PROMPT}\n")
            for r in records[start:start + 5]:
                stream.write(json.dumps(r["input"], ensure_ascii=False) + '\n\n')
    manifest = {
        "schema_version": "gnss_pilot_v1_provisional", "seed": args.seed, "count": len(records),
        "intent_counts": dict(Counter(r["annotation"]["scenario_intent"] for r in records)),
        "case_counts": dict(Counter(r["annotation"]["case_type"] for r in records)),
        "source_document": SOURCE.name,
        "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest() if SOURCE.exists() else None,
        "limitations": ["虚构本地坐标及POI，未查询地图", "功率是合成接收端观测，不是发射配置或传播仿真", "脚本检查只保证定义内的一致性，不代表物理或意图真实性", "尚无专家审核、教师报告或独立评估集", "不可把随机分割的同模板样本用于泛化能力结论"],
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding="utf-8")
    print(json.dumps({"out_dir": str(out), **{k: manifest[k] for k in ("count", "intent_counts", "case_counts")}}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
