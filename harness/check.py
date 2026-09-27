"""Deterministic contract checks; semantic and product verification are separate."""
from pathlib import Path
from datetime import date
import re
from urllib.parse import unquote

import yaml

from harness.documents import parse, paths, sections
from harness.anchors import fragment_issue
from harness.checkpoint import issues as preservation_issues
from harness.layout import issues as layout_issues
from harness.structure import enabled as structure_enabled, validate as validate_structure


STATUSES = {"ready", "active", "blocked", "review", "done", "cancelled"}
TASK_FIELDS = ("id", "project_id", "status", "checked")
TASK_SECTIONS = {
    "purpose": ("Goal", "Purpose", "목표", "목적"),
    "scope": ("Scope", "범위", "권한 범위"),
    "acceptance": ("Acceptance Criteria", "완료 기준", "예상 결과"),
    "result": ("Current Result", "Current State", "현재 결과", "현재 상태"),
    "next_action": ("Next Action", "다음 행동", "남은 작업"),
}


def local_links(body):
    # Ignore examples in fenced code, while retaining links in ordinary prose.
    prose = re.sub(r"(?ms)^(```|~~~).*?^\1[^\n]*$", "", body)
    prose = re.sub(r"`[^`\n]+`", "", prose)
    for match in re.finditer(r"\]\((<[^>]+>|[^\s)]+)(?:\s+\"[^\"]*\")?\)", prose):
        yield match[1].strip("<>"), False
    for match in re.finditer(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]", prose):
        yield match[1].rstrip("\\"), True


def link_target(root, document, value, wiki=False):
    if value.startswith(("#", "http:", "https:", "mailto:", "app:", "obsidian:")):
        return None
    value = unquote(value.split("#", 1)[0].split("?", 1)[0])
    if not value:
        return None
    p = Path(value)
    if p.is_absolute():
        return p
    target = (root / value) if wiki else (document.parent / value)
    if wiki and not target.suffix:
        target = target.with_suffix(".md")
    return target


def check(root, strict_tasks=True, *, initialize=False):
    issues = preservation_issues(root, initialize=initialize) + layout_issues(root)
    enforce_structure = structure_enabled(root)
    docs = []
    ids = {}
    tasks = {}
    def error(path, code, message):
        issues.append({"path": str(path), "code": code, "message": message})
    for path in paths(root):
        rel = path.relative_to(root).as_posix()
        try:
            doc = parse(rel, path.read_bytes())
        except (ValueError, UnicodeError, yaml.YAMLError) as exc:
            error(rel, "metadata", str(exc))
            continue
        docs.append(doc)
        if enforce_structure:
            issues.extend(validate_structure(doc))
        for heading, _ in sections(doc.body):
            if re.search(r'(?:이전 본문|이전 입구|보존 원문|보존 본문|보존 요약|변경 이력|작업 로그|progress log|changelog|previous version)', heading, re.I):
                error(rel, 'history-in-current', 'Move prior content/process into Log; keep current conclusions here')
        identity = doc.metadata.get("id")
        if identity:
            if not isinstance(identity, str):
                error(rel, "id", "ID must be a string")
            elif identity in ids:
                error(rel, "duplicate-id", f"Also owned by {ids[identity]}")
            else:
                ids[identity] = rel
        for value, wiki in local_links(doc.body):
            target = link_target(root, path, value, wiki)
            if target is not None and not target.exists():
                error(rel, "missing-link", value)
            try:
                fragment = fragment_issue(root, path, value, wiki, link_target)
                if fragment: issues.append(fragment)
            except (ValueError, UnicodeError, OSError, yaml.YAMLError) as exc:
                error(rel, "anchor-target", f"{value}: {exc}")
        is_task = "/tasks/" in rel and Path(rel).name not in {"README.md", "index.md"}
        if (doc.metadata.get("kind") == "task" or is_task) and strict_tasks:
            meta = doc.metadata
            for field in TASK_FIELDS:
                if not meta.get(field):
                    error(rel, "task-field", f"Missing {field}")
            headings = {name.casefold().strip() for name, body in sections(doc.body) if body.strip()}
            for field, names in TASK_SECTIONS.items():
                if not meta.get(field) and not any(name.casefold() in headings for name in names):
                    error(rel, "task-section", f"Missing {field}: metadata or a dedicated section required")
            if meta.get("status") not in STATUSES:
                error(rel, "task-status", str(meta.get("status")))
            try:
                date.fromisoformat(str(meta.get("checked")))
            except ValueError:
                error(rel, "task-date", "checked must be an ISO date")
            if rel.startswith("wiki/projects/") and meta.get("project_id") != Path(rel).parts[2]:
                error(rel, "task-project", "project_id must match the owning project directory")
            if meta.get("status") == "blocked" and not (meta.get("blocker") and meta.get("unblock_condition")):
                error(rel, "task-blocker", "Blocked tasks need blocker and unblock_condition")
            if meta.get("status") == "done" and not meta.get("evidence"):
                error(rel, "task-evidence", "Done tasks require evidence references")
            evidence = meta.get("evidence", [])
            if not isinstance(evidence, list):
                error(rel, "task-evidence", "evidence must be a list of source paths or URLs")
            else:
                for reference in evidence:
                    if not isinstance(reference, str) or not reference.strip():
                        error(rel, "task-evidence", "Evidence reference must be a nonempty string")
                        continue
                    target = link_target(root, path, reference)
                    if target is not None and not target.is_file():
                        error(rel, "task-evidence", f"Evidence file does not exist: {reference}")
            if isinstance(identity, str):
                tasks[identity] = doc
    visiting, visited = set(), set()
    def visit(identity):
        if identity in visiting:
            error(tasks[identity].path, "dependency-cycle", identity)
            return
        if identity in visited:
            return
        visiting.add(identity)
        doc = tasks[identity]
        dependencies = doc.metadata.get("depends_on", [])
        if not isinstance(dependencies, list):
            error(doc.path, "dependency", "depends_on must be a list")
            dependencies = []
        for dependency in dependencies:
            if not isinstance(dependency, str) or dependency not in tasks:
                error(doc.path, "dependency", f"Unknown task: {dependency}")
            else:
                visit(dependency)
        visiting.remove(identity)
        visited.add(identity)
    for identity in tasks:
        visit(identity)
    return {"ok": not issues, "documents": len(docs), "tasks": len(tasks), "issues": issues,
            "verification": "document-contract-only"}
