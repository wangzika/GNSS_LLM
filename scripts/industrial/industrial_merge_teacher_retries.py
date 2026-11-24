#!/usr/bin/env python3
"""把单独重试且通过质检的教师回复合并回主文件，并保留合并前版本。"""
import argparse
import json
import shutil
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.industrial.industrial_generate_teacher import read_records, write_raw
from scripts.common.step2_validate_and_pack import BLOCK_RE, validate


def read_rows(path):
    """读取 JSONL 并拒绝重复事件，防止合并时覆盖不明来源的回复。"""
    rows = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        event_id = row["event_id"]
        if event_id in rows:
            raise ValueError(f"{path} 第 {number} 行重复事件：{event_id}")
        rows[event_id] = row
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--meta", type=Path, required=True)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--retry", type=Path, required=True)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--backup", type=Path, required=True)
    args = parser.parse_args()

    records = read_records(args.meta)
    meta = {rec["event_meta"]["event_id"]: rec for rec in records}
    base = read_rows(args.base)
    retry = read_rows(args.retry)
    if set(base) != set(meta):
        raise ValueError("主回复文件未覆盖当前全部训练事件")
    if set(retry) - set(meta):
        raise ValueError("重试文件含元数据之外的事件")
    if args.backup.exists():
        raise FileExistsError(f"备份已存在：{args.backup}")

    accepted = {}
    for event_id, row in retry.items():
        if row.get("model") != base[event_id].get("model"):
            print(f"[保留原版] {event_id}: 模型名不一致")
            continue
        blocks = BLOCK_RE.findall(row.get("response", ""))
        reason = validate(blocks[0], meta[event_id]) if len(blocks) == 1 else "代码块数量异常"
        if reason:
            print(f"[保留原版] {event_id}: {reason}")
            continue
        accepted[event_id] = row
        print(f"[采用重试] {event_id}")
    if not accepted:
        raise SystemExit("没有可合并的合格重试报告")

    # 只替换验证合格的事件；原版回复完整保存在单独备份中。
    shutil.copy2(args.base, args.backup)
    merged = {**base, **accepted}
    ordered = [merged[rec["event_meta"]["event_id"]] for rec in records]
    temporary = args.base.with_name(args.base.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        for row in ordered:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    temporary.replace(args.base)
    write_raw(args.raw, records, {event_id: row["response"] for event_id, row in merged.items()})
    print(f"已合并 {len(accepted)}/{len(retry)} 条；原版备份：{args.backup}")


if __name__ == "__main__":
    main()
