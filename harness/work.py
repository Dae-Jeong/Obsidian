"""Code-work observations; Task owners remain in the central document corpus."""
import hashlib
import json
from contextlib import closing
from datetime import datetime, timezone
import os
from pathlib import Path
import stat
import subprocess
import uuid

from harness.context import git_environment


def git(workspace, *args):
    result = subprocess.run(['git', '-C', str(workspace), *args],
                            capture_output=True, check=False, env=git_environment())
    if result.returncode:
        raise ValueError('Code observation requires an accessible Git worktree')
    return result.stdout


def repository(workspace):
    workspace = Path(workspace).resolve()
    if not workspace.is_dir():
        raise ValueError('Code observation requires an existing Git worktree')
    path = git(workspace, 'rev-parse', '--show-toplevel').rstrip(b'\n')
    return Path(os.fsdecode(path)).resolve()


def signature(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def file_hash(root, name):
    relative = Path(name)
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('Git returned a path outside the observed worktree')
    path = root / relative
    for ancestor in relative.parents:
        if ancestor != Path('.') and (root / ancestor).is_symlink():
            return 'ancestor-symlink'
    try:
        before = path.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(before.st_mode):
        value = 'symlink:' + hashlib.sha256(os.fsencode(os.readlink(path))).hexdigest()
    elif stat.S_ISREG(before.st_mode):
        digest = hashlib.sha256()
        digest.update(str(before.st_mode & 0o111).encode() + b'\0')
        # Do not dereference a symlink substituted for the observed leaf.
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, 'rb') as stream:
            if signature(os.fstat(stream.fileno())) != signature(before):
                raise ValueError('File changed during code observation; retry after reconciliation')
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        value = 'file:' + digest.hexdigest()
    elif stat.S_ISDIR(before.st_mode):
        # Git submodules are independent workspaces, not recursively owned code.
        return 'directory'
    else:
        raise ValueError('Unsupported file type in observed Git worktree')
    if signature(path.lstat()) != signature(before):
        raise ValueError('File changed during code observation; retry after reconciliation')
    return value


def manifest(workspace):
    root = repository(workspace)
    listed = git(root, 'ls-files', '-z', '--cached', '--others', '--exclude-standard')
    names = sorted({os.fsdecode(name) for name in listed.split(b'\0') if name})
    return {name: file_hash(root, name) for name in names}


def differences(before, after):
    return {name: {'before': before.get(name), 'after': after.get(name)}
            for name in sorted(before.keys() | after.keys())
            if before.get(name) != after.get(name)}


def database(root):
    from harness.hooks import database as hook_database
    db = hook_database(root)
    import sqlite3
    db.row_factory = sqlite3.Row
    db.execute('CREATE TABLE IF NOT EXISTS work_sessions (id TEXT PRIMARY KEY, workspace TEXT NOT NULL, project TEXT NOT NULL, task TEXT, task_path TEXT, task_hash TEXT, handoff_hash TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS work_calls (id INTEGER PRIMARY KEY, session TEXT NOT NULL, tool TEXT NOT NULL, before_state TEXT NOT NULL, targets TEXT, task_hash TEXT, handoff_hash TEXT, state TEXT NOT NULL, changes TEXT, ambiguous INTEGER NOT NULL DEFAULT 0, reconciliation TEXT, UNIQUE(session,tool))')
    db.commit()
    return db


def identity(key):
    if not isinstance(key, str) or ':' not in key or key.split(':', 1)[0] not in ('codex', 'claude') or not key.split(':', 1)[1]:
        raise ValueError('Work session must identify codex:SESSION or claude:SESSION')


def task_hash(root, row):
    return hashlib.sha256((root / row['task_path']).read_bytes()).hexdigest() if row['task_path'] else None


def handoff_hash(root, path):
    if not path:
        return None
    from harness.documents import parse, sections
    from harness.check import TASK_SECTIONS
    doc = parse(path, (root / path).read_bytes())
    headings = {heading.casefold().strip(): body.strip() for heading, body in sections(doc.body)}
    values = {}
    for field in ('result', 'next_action'):
        values[field] = doc.metadata.get(field) or '\n'.join(headings.get(name.casefold(), '') for name in TASK_SECTIONS[field]).strip()
        if not values[field]:
            raise ValueError('Task requires current result and next action for handoff')
    return hashlib.sha256(json.dumps(values, sort_keys=True, default=str).encode()).hexdigest()


def ensure_session(root, db, key, workspace):
    from harness.context import context
    identity(key)
    workspace = repository(workspace)
    row = db.execute('SELECT * FROM work_sessions WHERE id=?', (key,)).fetchone()
    if row:
        if row['workspace'] != str(workspace):
            raise ValueError('A work session cannot silently change worktrees')
        return row
    owner = context(root, workspace)
    db.execute('INSERT INTO work_sessions(id,workspace,project) VALUES (?,?,?)',
               (key, str(workspace), owner['project_id']))
    return db.execute('SELECT * FROM work_sessions WHERE id=?', (key,)).fetchone()


def bind(root, key, workspace, task):
    from harness.context import context
    owner = context(root, Path(workspace), task)['tasks'][0]
    if owner['status'] in ('done', 'cancelled'):
        raise ValueError('Task must be active work before binding code changes')
    with closing(database(root)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        row = ensure_session(root, db, key, workspace)
        if row['task'] and row['task'] != owner['id']:
            if db.execute("SELECT 1 FROM work_calls WHERE session=? AND state!='recorded'", (key,)).fetchone():
                raise ValueError('Cannot rebind unfinished observations to another Task')
        if row['task'] != owner['id']:
            db.execute('UPDATE work_sessions SET task=?,task_path=?,task_hash=?,handoff_hash=? WHERE id=?',
                       (owner['id'], owner['path'], owner['sha256'], handoff_hash(root, owner['path']), key))
    return status(root, key)


def begin(root, key, tool, workspace, selected=None):
    if not isinstance(tool, str) or not tool:
        raise ValueError('Paired code observation requires tool_use_id')
    if selected is not None:
        selected = list(selected)
        if any(not isinstance(p, str) or Path(p).is_absolute() or '..' in Path(p).parts for p in selected):
            raise ValueError('Observed targets must stay relative to the worktree')
    with closing(database(root)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        session = ensure_session(root, db, key, workspace)
        if db.execute('SELECT 1 FROM work_calls WHERE session=? AND tool=?', (key, tool)).fetchone():
            raise ValueError('Duplicate tool observation; reconcile the existing call')
        before = manifest(workspace)
        ambiguous = selected is None
        peers = db.execute("SELECT c.* FROM work_calls c JOIN work_sessions s ON s.id=c.session WHERE s.workspace=? AND c.state='pending'", (session['workspace'],)).fetchall()
        for peer in peers:
            targets = json.loads(peer['targets']) if peer['targets'] is not None else None
            overlap = selected != [] and targets != [] and (selected is None or targets is None or bool(set(selected) & set(targets)))
            if overlap:
                ambiguous = True
                db.execute('UPDATE work_calls SET ambiguous=1 WHERE id=?', (peer['id'],))
        db.execute("INSERT INTO work_calls(session,tool,before_state,targets,task_hash,state,ambiguous,handoff_hash) VALUES (?,?,?,?,?,'pending',?,?)",
                   (key, tool, json.dumps(before), json.dumps(selected) if selected is not None else None,
                    task_hash(root, session), int(ambiguous), handoff_hash(root, session['task_path'])))
    return {'pending': tool}


def finish(root, key, tool, reconciliation=None):
    with closing(database(root)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        call = db.execute("SELECT * FROM work_calls WHERE session=? AND tool=? AND state='pending'", (key, tool)).fetchone()
        if not call:
            raise ValueError('No matching pending code observation')
        session = db.execute('SELECT * FROM work_sessions WHERE id=?', (key,)).fetchone()
        changes = differences(json.loads(call['before_state']), manifest(Path(session['workspace'])))
        if call['targets'] is not None:
            selected = set(json.loads(call['targets']))
            changes = {p: change for p, change in changes.items() if p in selected}
        if changes:
            db.execute("UPDATE work_calls SET state='changed',changes=?,reconciliation=?,ambiguous=?,task_hash=?,handoff_hash=? WHERE id=?",
                       (json.dumps(changes), reconciliation, int(bool(call['ambiguous'] or reconciliation)),
                        task_hash(root, session), handoff_hash(root, session['task_path']), call['id']))
        else:
            db.execute('DELETE FROM work_calls WHERE id=?', (call['id'],))
    return status(root, key)


def reconcile(root, key, tool, reason):
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError('Reconciliation requires actual writer and workspace findings')
    return finish(root, key, tool, reconciliation=reason)


def status(root, key=None, workspace=None):
    with closing(database(root)) as db:
        clauses, values = [], []
        if key:
            clauses.append('id=?')
            values.append(key)
        if workspace:
            clauses.append('workspace=?')
            values.append(str(repository(workspace)))
        query = 'SELECT * FROM work_sessions' + (' WHERE ' + ' AND '.join(clauses) if clauses else '')
        sessions = []
        all_issues = set()
        for row in db.execute(query, values).fetchall():
            calls = db.execute("SELECT tool,state,ambiguous,reconciliation FROM work_calls WHERE session=? AND state!='recorded' ORDER BY id", (row['id'],)).fetchall()
            issues = set()
            if calls and not row['task']:
                issues.add('work-task-missing')
            if any(c['state'] == 'pending' for c in calls):
                issues.add('work-pending')
            if any(c['state'] == 'changed' for c in calls):
                issues.add('work-unrecorded')
            if any(c['ambiguous'] for c in calls):
                issues.add('work-ambiguous')
            all_issues.update(issues)
            sessions.append({**dict(row), 'calls': [dict(c) for c in calls], 'issues': sorted(issues)})
    return {'sessions': sessions, 'issues': sorted(all_issues)}


def record(root, key, evidence, reconciliation=None):
    root = root.resolve()
    source = (root / evidence).resolve()
    try:
        source.relative_to(root / 'wiki/log')
    except ValueError:
        raise ValueError('Execution evidence must exist inside wiki/log') from None
    if not source.is_file():
        raise ValueError('Execution evidence must exist before work recording')
    with closing(database(root)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        session = db.execute('SELECT * FROM work_sessions WHERE id=?', (key,)).fetchone()
        calls = db.execute("SELECT * FROM work_calls WHERE session=? AND state!='recorded' ORDER BY id", (key,)).fetchall()
        if any(c['state'] == 'pending' for c in calls):
            raise ValueError('Reconcile pending calls before recording work')
        if not calls:
            return {'recorded': 0, 'evidence': None}
        if not session or not session['task']:
            raise ValueError('Bind a central Task before recording work')
        from harness.context import context
        owner = context(root, Path(session['workspace']), session['task'])['tasks'][0]
        if owner['path'] != session['task_path']:
            raise ValueError('Bound Task owner changed; reconcile its identity before recording')
        current_task = task_hash(root, session)
        if current_task == session['task_hash'] or current_task == calls[-1]['task_hash']:
            raise ValueError('Update the Task with current result and handoff after the code change')
        current_handoff = handoff_hash(root, session['task_path'])
        if current_handoff == session['handoff_hash'] or current_handoff == calls[-1]['handoff_hash']:
            raise ValueError('Task handoff content must change; metadata-only edits do not record work')
        if any(c['ambiguous'] for c in calls) and not (isinstance(reconciliation, str) and reconciliation.strip()):
            raise ValueError('Writer overlap requires explicit reconciliation findings')
        actual = manifest(Path(session['workspace']))
        expected = {}
        for call in calls:
            expected.update({p: value['after'] for p, value in json.loads(call['changes']).items()})
        if any(actual.get(p) != value for p, value in expected.items()):
            raise ValueError('Observed files drifted; reconcile actual work before recording')
        receipt = root / 'wiki/log' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-work-' + uuid.uuid4().hex[:8])
        receipt.mkdir()
        payload = {'session': key, 'workspace': session['workspace'], 'project': session['project'],
                   'task': session['task'], 'task_path': session['task_path'], 'task_hash': current_task,
                   'source_evidence': str(source.relative_to(root)),
                   'source_evidence_hash': hashlib.sha256(source.read_bytes()).hexdigest(),
                   'reconciliation': reconciliation, 'verification': 'observations-and-record-linkage-only',
                   'observations': [{'tool': c['tool'], 'changes': json.loads(c['changes']),
                                     'attribution': 'explicit-target' if c['targets'] is not None else 'observed-window',
                                     'ambiguous': bool(c['ambiguous']), 'reconciliation': c['reconciliation']} for c in calls]}
        target = receipt / 'record.json'
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
        if task_hash(root, session) != current_task:
            raise ValueError('Task drifted while recording; reconcile current handoff')
        latest = manifest(Path(session['workspace']))
        if any(latest.get(p) != value for p, value in expected.items()):
            raise ValueError('Observed files drifted during recording; reconcile actual work')
        db.execute("UPDATE work_calls SET state='recorded' WHERE session=? AND state='changed'", (key,))
        db.execute('UPDATE work_sessions SET task_hash=?,handoff_hash=? WHERE id=?', (current_task, current_handoff, key))
    return {'recorded': len(calls), 'evidence': str(target.relative_to(root))}
