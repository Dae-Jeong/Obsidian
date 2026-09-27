"""Markdown metadata and explicit corpus scopes shared by CLI operations."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re

import yaml
from harness.layout import excluded


class UniqueLoader(yaml.SafeLoader):
    pass


def mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str):
            raise ValueError("Metadata keys must be strings")
        if key in result:
            raise ValueError(f"Duplicate metadata key: {key}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)


@dataclass
class Document:
    path: str
    text: str
    metadata: dict
    body: str
    sha256: str


def parse(path, raw):
    text = raw.decode("utf-8")
    match = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)", text, re.S)
    metadata = yaml.load(match[1], Loader=UniqueLoader) if match else {}
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict):
        raise ValueError("Frontmatter must be a mapping")
    if text.startswith("---\n") and not match:
        raise ValueError("Unclosed frontmatter")
    return Document(str(path), text, metadata, text[match.end():] if match else text,
                    hashlib.sha256(raw).hexdigest())


def paths(root, scope="current"):
    folders = {"current": ("wiki/notes", "wiki/projects", "docs"), "sources": ("wiki/sources",), "history": ("wiki/log",)}[scope]
    if scope == "current":
        for name in ("wiki/profile.md", "README.md", "AGENTS.md", "wiki/index.md"):
            p = root / name
            if p.is_file():
                yield p
    for folder in folders:
        for p in sorted((root / folder).rglob("*.md")):
            rel = p.relative_to(root)
            if excluded(rel.as_posix()) or p.is_symlink() or any(part.startswith(".") for part in rel.parts):
                continue
            yield p


def protected_roots(root):
    """Explicit extra preservation scope, never an automatic currentness claim."""
    registry = root / '.local/harness/projects.json'
    if not registry.exists():
        return []
    data = json.loads(registry.read_text())
    if not isinstance(data, dict):
        raise ValueError('Project registry must be an object')
    names = data.get('protected_roots', [])
    if not isinstance(names, list):
        raise ValueError('protected_roots must be a list')
    result = []
    for name in names:
        if not isinstance(name, str) or not name or Path(name).is_absolute() or '..' in Path(name).parts:
            raise ValueError('Protected roots must be local relative paths')
        # This extension is specifically for domain owners stored in sources.
        if not name.startswith('wiki/sources/') or Path(name).as_posix() != name:
            raise ValueError('Additional protected roots must identify a domain under wiki/sources')
        path = root / name
        if path.is_symlink():
            raise ValueError('Protected domain root must not be a symlink')
        path.resolve().relative_to(root.resolve())
        if not path.exists():
            raise ValueError(f'Protected domain is missing: {name}')
        result.append(name)
    return sorted(set(result))


def protected_paths(root):
    """Full bytes of current owners/companions plus explicitly registered domains."""
    result = set(paths(root))
    for folder in ('wiki/notes', 'wiki/projects', 'docs', *protected_roots(root)):
        base = root / folder
        candidates = [base] if base.is_file() else base.rglob('*')
        for p in candidates:
            rel = p.relative_to(root)
            if not p.is_file() or p.is_symlink() or any(part.startswith('.') for part in rel.parts):
                continue
            # A directory bridge must never silently extend the managed scope.
            if any(parent.is_symlink() for parent in p.parents if parent != root and root in parent.parents):
                continue
            p.resolve().relative_to(root.resolve())
            result.add(p)
    yield from sorted(result)


def fingerprint(root, scope="current"):
    h = hashlib.sha256()
    registry = root / '.local/harness/projects.json'
    if scope == 'current' and registry.exists():
        h.update(registry.read_bytes())
    for p in (protected_paths(root) if scope == "current" else sorted(paths(root, scope))):
        h.update(p.relative_to(root).as_posix().encode())
        h.update(b"\0")
        h.update(hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()


def sections(body):
    current = "Introduction"
    lines = []
    fenced = False
    for line in body.splitlines():
        if line.startswith(("```", "~~~")):
            fenced = not fenced
        if not fenced and re.match(r"^#{1,6}\s+", line):
            if lines:
                yield current, "\n".join(lines)
            current = re.sub(r"^#+\s+", "", line)
            lines = []
        else:
            lines.append(line)
    if lines:
        yield current, "\n".join(lines)
