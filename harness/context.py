"""Resolve registered repositories/worktrees and return central Task owners."""
import json
import os
from pathlib import Path
import subprocess
import sqlite3
from contextlib import closing

from harness.documents import parse
from harness.readiness import ensure_readable


def git_environment():
    """Do not let a caller's repository-local Git settings redirect another repo."""
    result = subprocess.run(['git', 'rev-parse', '--local-env-vars'],
                            capture_output=True, text=True, check=True)
    local = set(result.stdout.splitlines())
    return {key: value for key, value in os.environ.items() if key not in local}


def git_common(workspace):
    result = subprocess.run(["git", "-C", str(workspace), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                            capture_output=True, text=True, check=False, env=git_environment())
    return str(Path(result.stdout.strip()).resolve()) if result.returncode == 0 else None


def context(root, workspace, task=None):
    root = root.resolve()
    publication = ensure_readable(root)
    workspace = workspace.resolve()
    if not workspace.is_dir():
        raise ValueError('Workspace directory does not exist')
    registry = json.loads((root / ".local/harness/projects.json").read_text())
    common = git_common(workspace)
    matches = []
    for entry in registry["projects"]:
        registered = Path(entry["root"]).resolve()
        if workspace == registered or registered in workspace.parents or (common and common == entry.get("git_common_dir")):
            matches.append(entry)
    if len(matches) != 1:
        raise ValueError("Workspace must resolve to exactly one registered project")
    project = matches[0]
    folder = (root / project["documents"]).resolve()
    folder.relative_to(root.resolve())
    if not folder.is_dir() or not (folder / 'index.md').is_file():
        raise ValueError('Registered document owner requires an existing directory and index.md')
    tasks = []
    for path in sorted((folder / "tasks").glob("*.md")):
        if path.name in ("README.md", "index.md"):
            continue
        doc = parse(path.relative_to(root).as_posix(), path.read_bytes())
        identity = doc.metadata.get("id", path.stem)
        if task and task not in (identity, path.stem):
            continue
        entry = {"id": identity, "path": doc.path, "status": doc.metadata.get("status", "unverified"),
                 "title": doc.metadata.get("title", path.stem), "sha256": doc.sha256}
        if task:
            entry["content"] = doc.text
        tasks.append(entry)
    if task and len(tasks) != 1:
        raise ValueError("Task must resolve to exactly one document within the project")
    unfinished = []
    state = root / '.local/harness/hook-state.sqlite'
    if state.exists() and common:
        actual = subprocess.run(['git', '-C', str(workspace), 'rev-parse', '--show-toplevel'],
                                capture_output=True, text=True, check=True, env=git_environment())
        worktree = str(Path(actual.stdout.strip()).resolve())
        # Read-only: context is also called inside a work-state write transaction.
        with closing(sqlite3.connect(f'{state.as_uri()}?mode=ro', uri=True)) as db:
            db.row_factory = sqlite3.Row
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if {'work_sessions', 'work_calls'} <= tables:
                unfinished = [dict(r) for r in db.execute(
                    "SELECT s.id AS session,s.task,s.task_path,c.tool,c.state,c.ambiguous FROM work_sessions s JOIN work_calls c ON c.session=s.id WHERE s.workspace=? AND c.state!='recorded' ORDER BY c.id",
                    (worktree,))]
                if 'hook_calls' in tables:
                    unfinished += [dict(r) for r in db.execute(
                        "SELECT s.id AS session,s.task,s.task_path,h.tool,'hook-pending' AS state FROM work_sessions s JOIN hook_calls h ON h.session=s.id LEFT JOIN work_calls c ON c.session=h.session AND c.tool=h.tool WHERE s.workspace=? AND (c.id IS NULL OR c.state!='pending')",
                        (worktree,))]
        for call in unfinished:
            call['issues'] = ['work-pending' if call['state'] in ('pending', 'hook-pending') else 'work-unrecorded']
            if not call['task']:
                call['issues'].append('work-task-missing')
    ensure_readable(root, publication)
    return {"project_id": project["id"], "index": str(folder.relative_to(root.resolve()) / "index.md"),
            "policy": "wiki/notes/agents/work-management-policy.md", "workspace": str(workspace),
            "git_common_dir": common, "tasks": tasks, "unfinished_work": unfinished,
            "instruction": "Read the chosen full Task, reconcile workspace and active writers, then continue authorized work. "
                           "Do not infer product completion from metadata or start every listed task."}
