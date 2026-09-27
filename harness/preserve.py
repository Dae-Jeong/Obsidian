#!/usr/bin/env python3
"""Local document preservation and explicitly scoped Markdown retrieval."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
LOG = Path("wiki/log")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def local(root, value):
    path = (root / value).resolve()
    path.relative_to(root.resolve())
    return path


def historical(path):
    return any(p.lower() in {"log", "logs", "log.md", "_log.md", "changelog.md"}
               for p in path.parts)


def snapshot(root, files, reason):
    root = root.resolve()
    # Resolve and validate the entire request before creating a record.
    paths = [local(root, f) for f in files]
    if not reason.strip() or not paths:
        raise ValueError("A change reason and at least one file are required")
    for path in paths:
        if not path.is_file() or historical(path.relative_to(root)):
            raise ValueError(f"Expected an existing current file: {path}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = root / LOG / (stamp + "-" + uuid.uuid4().hex[:8])
    target.mkdir(parents=True)
    records = []
    for path in paths:
        relative = path.relative_to(root)
        before = digest(path)
        copy = target / "before" / relative
        copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, copy)
        if digest(copy) != before or digest(path) != before:
            raise ValueError(f"Source changed during snapshot: {path}; do not edit")
        records.append({"path": relative.as_posix(), "sha256": before})
    manifest = {"created": stamp, "reason": reason, "files": records}
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    (target / "README.md").write_text(
        "# Change record\n\n" + reason + "\n\n"
        "Before-state bytes and hashes are recorded in manifest.json. Relative links "
        "in snapshots are interpreted from their original document paths. "
        "A snapshot records preparation, not successful completion.\n")
    return target


def verify(root, record):
    root = root.resolve()
    target = local(root, record)
    target.relative_to((root / LOG).resolve())
    manifest = json.loads((target / "manifest.json").read_text())
    for entry in manifest["files"]:
        copy = local(target / "before", entry["path"])
        if digest(copy) != entry["sha256"]:
            raise ValueError(f"Snapshot integrity failure: {entry['path']}")
    return len(manifest["files"])
