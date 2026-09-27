"""Read-only inventory for a reviewed document migration, never an auto-rewriter."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from harness.layout import walk, excluded
import re


HISTORY_PARTS = {"log", "logs", "log.md", "_log.md", "changelog.md"}
LEGACY_HEADING = re.compile(
    r"^#{1,6}\s+.*(?:작업 로그|변경 이력|진행 이력|변경 전|History|Changelog|Progress Log)",
    re.IGNORECASE | re.MULTILINE,
)


def category(path):
    parts = {part.casefold() for part in path.parts}
    if excluded(path.as_posix()):
        return "excluded"
    if parts & HISTORY_PARTS or "legacy-indexes" in parts:
        return "history"
    if path.parts[:3] == ("wiki", "sources", "basic-memory"):
        return "memory-review"
    if path.parts[:2] == ("wiki", "sources") or path.parts[0] == "sources":
        return "source"
    return "current"


def inventory(root):
    root = root.resolve()
    files = []
    for path, kind in walk(root):
        relative = path.relative_to(root)
        entry = {"path": relative.as_posix(), "category": category(relative)}
        if kind in {"directory", "runtime-boundary"}:
            entry.update(kind=kind, empty=not any(path.iterdir()) if kind == "directory" else None)
        elif path.is_symlink():
            entry.update(kind="symlink", target=str(path.readlink()))
        else:
            raw = path.read_bytes()
            entry.update(kind="file", size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
            if path.suffix.casefold() == ".md":
                body = raw.decode("utf-8", errors="replace")
                entry["history_heading_candidates"] = LEGACY_HEADING.findall(body)
                entry["title"] = next((line[2:].strip() for line in body.splitlines()
                                       if line.startswith("# ")), "")
                frontmatter = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)", body, re.S)
                entry["metadata"] = {}
                if frontmatter:
                    for key in ("id", "type", "status", "canonical", "sot"):
                        match = re.search(r"^" + key + r":\s*(.+)$", frontmatter[1], re.M)
                        if match:
                            entry["metadata"][key] = match[1].strip()
        files.append(entry)
    return {"verification": "inventory-only-not-content-verification",
            "counts": dict(Counter(f["category"] for f in files)), "files": files}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = inventory(args.root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"output": str(args.output), "counts": result["counts"]}))


if __name__ == "__main__":
    main()
