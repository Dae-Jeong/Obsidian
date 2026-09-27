"""Explicit-manifest migration with full before-state and resumable file moves."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from urllib.parse import unquote


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def contained(root, name):
    p = root / name
    if Path(name).is_absolute() or ".." in Path(name).parts or p.is_symlink():
        raise ValueError(f"Unsafe manifest path: {name}")
    p.resolve().relative_to(root.resolve())
    return p


def relocate(value, mapping):
    if value in mapping:
        return mapping[value]
    for before, after in sorted(mapping.items(), key=lambda item: -len(item[0])):
        if value.startswith(before.rstrip("/") + "/"):
            return after.rstrip("/") + value[len(before.rstrip("/")):]
    return value


def rewrite_links(text, old, new, mapping, root):
    def markdown(match):
        value = match[1].strip("<>")
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", value) or value.startswith("#"):
            return match[0]
        base, separator, anchor = value.partition("#")
        decoded = unquote(base)
        absolute = Path(decoded) if decoded.startswith("/") else Path(os.path.normpath(root / Path(old).parent / decoded))
        try:
            relative = absolute.relative_to(root).as_posix()
        except ValueError:
            # A moved page's external relative link must still reach the same file.
            if not decoded.startswith("/"):
                target = os.path.relpath(absolute, root / Path(new).parent)
                return "](" + target + (separator + anchor if separator else "") + ")"
            return match[0]
        target = root / relocate(relative, mapping)
        value = str(target) if decoded.startswith("/") else os.path.relpath(target, root / Path(new).parent)
        if " " in value:
            value = "<" + value + (separator + anchor if separator else "") + ">"
        else:
            value += separator + anchor if separator else ""
        return "](" + value + ")"
    text = re.sub(r"\]\((<[^>]+>|[^\s)]+)\)", markdown, text)
    def wikilink(match):
        target, sep, label = match[1].partition("|")
        escaped_separator = target.endswith("\\") and bool(sep)
        target = target.rstrip("\\") if escaped_separator else target
        base, anchor_sep, anchor = target.partition("#")
        key = base if base.endswith(".md") else base + ".md"
        moved = mapping.get(key, mapping.get(base, base))
        if not base.endswith(".md") and moved.endswith(".md"):
            moved = moved[:-3]
        return "[[" + moved + (anchor_sep + anchor if anchor_sep else "") + (("\\" if escaped_separator else "") + sep + label if sep else "") + "]]"
    text = re.sub(r"\[\[([^\]]+)\]\]", wikilink, text)
    # Exact vault-root path references in backticks and metadata.
    for before, after in sorted(mapping.items(), key=lambda item: -len(item[0])):
        if before != after:
            text = text.replace(str(root / before), str(root / after))
            text = re.sub(r"(?<![\w/.-])" + re.escape(before) + r"(?![\w.-])", lambda m: after, text)
    return text


def apply(root, plan_path, record):
    root = root.resolve()
    plan = json.loads(plan_path.read_text())
    entries = plan["files"]
    destinations = [e["target"] for e in entries]
    if len(set(destinations)) != len(destinations):
        raise ValueError("Duplicate destinations")
    mapping = {e["source"]: e["target"] for e in entries}
    mapping.update(plan.get("directories", {}))
    mapping.update(plan.get("redirects", {}))
    # Validate every source and destination before writing any destination.
    for entry in entries:
        source = contained(root, entry["source"])
        target = contained(root, entry["target"])
        if sha(source.read_bytes()) != entry["sha256"]:
            raise ValueError(f"Stale migration source: {source}")
        if target != source and target.exists():
            raise ValueError(f"Destination exists: {target}")
    record.mkdir(parents=True, exist_ok=False)
    shutil.copy2(plan_path, record / "manifest.json")
    staged = []
    for entry in entries:
        source = contained(root, entry["source"])
        raw = source.read_bytes()
        before = record / "before" / entry["source"]
        before.parent.mkdir(parents=True, exist_ok=True)
        before.write_bytes(raw)
        if sha(before.read_bytes()) != entry["sha256"]:
            raise ValueError("Snapshot verification failed")
        output = raw
        if entry.get("rewrite") and source.suffix.lower() == ".md":
            output = rewrite_links(raw.decode("utf-8"), entry["source"], entry["target"], mapping, root).encode("utf-8")
        candidate = record / "candidates" / entry["target"]
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_bytes(output)
        staged.append({**entry, "output_sha256": sha(output)})
    (record / "publication.json").write_text(json.dumps({"status": "prepared", "files": staged}, indent=2) + "\n")
    finish(root, record)
    return len(entries)


def finish(root, record):
    journal = json.loads((record / "publication.json").read_text())
    for entry in journal["files"]:
        source = contained(root, entry["source"])
        target = contained(root, entry["target"])
        candidate = record / "candidates" / entry["target"]
        if sha(candidate.read_bytes()) != entry["output_sha256"]:
            raise ValueError("Candidate integrity failure")
        if target.exists() and sha(target.read_bytes()) == entry["output_sha256"]:
            continue
        if not source.exists() or sha(source.read_bytes()) != entry["sha256"]:
            raise ValueError(f"Concurrent source change: {source}")
        if target != source and target.exists():
            raise ValueError(f"Concurrent destination change: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_name(target.name + ".migration-tmp")
        temp.write_bytes(candidate.read_bytes())
        os.replace(temp, target)
    # All destinations are present before any original path is removed.
    for entry in journal["files"]:
        source = contained(root, entry["source"])
        target = contained(root, entry["target"])
        if sha(target.read_bytes()) != entry["output_sha256"]:
            raise ValueError("Destination changed before cleanup")
        if source != target and source.exists():
            if sha(source.read_bytes()) != entry["sha256"]:
                raise ValueError(f"Concurrent source change during cleanup: {source}")
            source.unlink()
    journal["status"] = "applied"
    (record / "publication.json").write_text(json.dumps(journal, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("plan", type=Path)
    parser.add_argument("record", type=Path)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.resume:
        finish(args.root.resolve(), args.record)
    else:
        print(apply(args.root, args.plan, args.record))


if __name__ == "__main__":
    main()
