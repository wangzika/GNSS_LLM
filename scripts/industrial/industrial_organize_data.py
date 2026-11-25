#!/usr/bin/env python3
"""把已有扁平工业数据迁移到六阶段 input/output；逐文件核对 SHA-256。"""
import argparse
import hashlib
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.industrial.workflow_paths import ROOT, STAGES, WorkflowPaths


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def migrate(root):
    root = Path(root)
    if not (root / "train_meta.json").exists():
        raise ValueError("仅迁移尚未整理的扁平目录；已整理的数据无需重复迁移")
    layout = WorkflowPaths(root, structured=True)
    # 先完整检查未知文件、目标冲突和 JSON，任何问题均在移动前中止。
    moves = []
    archive = root / "archive"
    archive_hashes = {}
    for source in sorted(root.iterdir()):
        if source == archive and source.is_dir():
            if layout.archive.exists():
                raise FileExistsError(layout.archive)
            archive_hashes = {str(p.relative_to(source)): digest(p)
                              for p in source.rglob("*") if p.is_file()}
            continue
        if not source.is_file():
            raise ValueError(f"发现额外目录或特殊文件，需先确定归属：{source}")
        target = layout.file(source.name)
        if target.exists() or target.is_symlink():
            raise FileExistsError(target)
        moves.append((source, target, digest(source)))
    records = []
    for split in ("train", "validation", "test"):
        records.extend(json.loads((root / f"{split}_meta.json").read_text()))
    if len({r["event_meta"]["event_id"] for r in records}) != len(records):
        raise ValueError("事件 ID 重复，不能建立准备阶段快照")
    for source, target, sha in moves:
        target.parent.mkdir(parents=True, exist_ok=True)
        source.rename(target)
        if digest(target) != sha:
            raise RuntimeError(f"移动后内容校验失败：{target}")
    if archive.exists():
        archive.rename(layout.archive)
        if any(digest(layout.archive / name) != sha for name, sha in archive_hashes.items()):
            raise RuntimeError("旧归档移动后校验失败")
    layout.initialize(source_csv=ROOT / "data/industrial_source/raw_ai4i2020.csv",
                      legacy_dir=ROOT / "data/industrial_v1")
    # 原元数据仅重排为按 ID 排序的完整快照，不重新抽样或修改输入。
    layout.file("events_meta.json").write_text(json.dumps(
        sorted(records, key=lambda r: r["event_meta"]["event_id"]),
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = {"layout_version": 1, "migrated_on": date.today().isoformat(), "stages": STAGES,
                "archive_files_verified": len(archive_hashes),
                "files": [{"old": src.name, "new": str(dst.relative_to(root)), "sha256": sha}
                          for src, dst, sha in moves]}
    (root / "layout.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                                      encoding="utf-8")
    print(f"已迁移 {len(moves)} 个文件，全部 SHA-256 一致；完整事件快照 {len(records)} 条")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data/industrial_v2")
    migrate(parser.parse_args().data_dir)
