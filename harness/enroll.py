"""Enroll explicitly listed repository Task files as central single owners."""
import argparse
import hashlib
import json
import os
from pathlib import Path

from harness.migrate import rewrite_links, contained


def enroll(root, plan, record):
    root = root.resolve()
    entries = plan["files"]
    if len({e["target"] for e in entries}) != len(entries):
        raise ValueError("Duplicate enrollment target")
    for entry in entries:
        source = Path(entry["source"])
        target = contained(root, entry["target"])
        if source.is_symlink() or source.suffix != ".md" or "tasks" not in source.parts:
            raise ValueError(f"Expected a regular repository Task: {source}")
        if hashlib.sha256(source.read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError(f"Stale source: {source}")
        if target.exists():
            raise ValueError(f"Target already exists: {target}")
    record.mkdir(parents=True, exist_ok=False)
    (record / "manifest.json").write_text(json.dumps(plan, indent=2) + "\n")
    for entry in entries:
        source = Path(entry["source"])
        raw = source.read_bytes()
        before = record / "before" / entry["target"]
        before.parent.mkdir(parents=True, exist_ok=True)
        before.write_bytes(raw)
        assert hashlib.sha256(before.read_bytes()).hexdigest() == entry["sha256"]
    receipts = []
    for entry in entries:
        source = Path(entry["source"]).resolve()
        target = contained(root, entry["target"])
        raw = source.read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            raise ValueError(f"Concurrent source change: {source}")
        text = rewrite_links(raw.decode(), os.path.relpath(source, root), entry["target"], {}, root)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as output:
            output.write(text.encode())
        temp = source.with_name(source.name + ".central-link")
        temp.symlink_to(os.path.relpath(target, source.parent))
        if hashlib.sha256(source.read_bytes()).hexdigest() != entry["sha256"]:
            temp.unlink()
            raise ValueError(f"Concurrent source change before switch: {source}")
        os.replace(temp, source)
        assert source.resolve() == target.resolve()
        receipts.append({**entry, "output_sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
        (record / "receipts.json").write_text(json.dumps(receipts, indent=2) + "\n")
    return len(receipts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("plan", type=Path)
    parser.add_argument("record", type=Path)
    args = parser.parse_args()
    print(enroll(args.root, json.loads(args.plan.read_text()), args.record))


if __name__ == "__main__":
    main()
