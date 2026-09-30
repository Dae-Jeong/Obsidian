"""Code-work observations; Task owners remain in the central document corpus."""
import hashlib
import json
from contextlib import closing, ExitStack
from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import uuid

from harness.context import git_environment

WORK_AGENTS = ('codex', 'claude', 'kiro')


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


def observation_manifest(workspace, selected=None):
    """Git scope plus explicit file targets, including ignored code artifacts.

    Unknown shell windows retain Git's exclusion boundary; do not scan ignored
    trees (credentials, dependencies, caches) to guess what a command changed.
    """
    current = manifest(workspace)
    if selected is not None:
        root = repository(workspace)
        for name in selected:
            current[name] = file_hash(root, name)
    return current


def differences(before, after):
    return {name: {'before': before.get(name), 'after': after.get(name)}
            for name in sorted(before.keys() | after.keys())
            if before.get(name) != after.get(name)}


def database(root):
    from harness.hooks import database as hook_database
    db = hook_database(root)
    db.row_factory = sqlite3.Row
    db.execute('CREATE TABLE IF NOT EXISTS work_sessions (id TEXT PRIMARY KEY, workspace TEXT NOT NULL, project TEXT NOT NULL, task TEXT, task_path TEXT, task_hash TEXT, handoff_hash TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS work_calls (id INTEGER PRIMARY KEY, session TEXT NOT NULL, tool TEXT NOT NULL, before_state TEXT NOT NULL, targets TEXT, task_hash TEXT, handoff_hash TEXT, state TEXT NOT NULL, changes TEXT, ambiguous INTEGER NOT NULL DEFAULT 0, reconciliation TEXT, reconciled_state TEXT, UNIQUE(session,tool))')
    db.commit()
    # Additive, idempotent migration: add only missing nullable columns; never recreate.
    for column in SESSION_COLUMNS:
        if column not in {r['name'] for r in db.execute('PRAGMA table_info(work_sessions)')}:
            try:
                db.execute(f'ALTER TABLE work_sessions ADD COLUMN {column} TEXT')
                db.commit()
            except sqlite3.OperationalError as exc:
                # A concurrent process may have added the same column first.
                if 'duplicate column' not in str(exc):
                    raise
    return db


SESSION_COLUMNS = ('terminal', 'terminal_source')
TERMINAL_ENV = 'ORCA_TERMINAL_HANDLE'
TERMINAL_LIMIT = 256


def valid_terminal(value):
    return (isinstance(value, str) and 0 < len(value) <= TERMINAL_LIMIT
            and value.isprintable() and not any(char.isspace() for char in value))


def terminal_identity(explicit=None, strict=True):
    """Return (terminal, source) from an explicit opaque ID or this process's Orca handle.

    The value identifies the terminal of the calling process only; no process
    scanning or CLI-internal inspection is performed. None means unknown.
    """
    if explicit is not None:
        if not valid_terminal(explicit):
            raise ValueError(f'--terminal must be 1-{TERMINAL_LIMIT} printable characters without whitespace')
        return explicit, 'explicit'
    handle = os.environ.get(TERMINAL_ENV)
    if handle is None:
        return None, None
    value = 'orca:' + handle
    if not valid_terminal(handle) or len(value) > TERMINAL_LIMIT:
        if strict:
            raise ValueError(f'{TERMINAL_ENV} is not a valid terminal handle; pass --terminal explicitly')
        return None, None
    return value, 'env'


def identity(key):
    if (not isinstance(key, str) or key.count(':') != 1
            or key.split(':', 1)[0] not in WORK_AGENTS
            or not key.split(':', 1)[1] or any(char.isspace() for char in key)):
        raise ValueError('Work session must identify ' + ', '.join(f'{agent}:SESSION' for agent in WORK_AGENTS))


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


def ensure_session(root, db, key, workspace, terminal=None):
    from harness.context import context
    identity(key)
    workspace = repository(workspace)
    row = db.execute('SELECT * FROM work_sessions WHERE id=?', (key,)).fetchone()
    if row:
        if row['workspace'] != str(workspace):
            raise ValueError('A work session cannot silently change worktrees')
        return row
    owner = context(root, workspace)
    # A newly observed session (bind, CLI begin or hook) records its own Orca
    # handle when present; invalid env values are ignored so hooks never fail.
    terminal, source = terminal if terminal else terminal_identity(strict=False)
    db.execute('INSERT INTO work_sessions(id,workspace,project,terminal,terminal_source) VALUES (?,?,?,?,?)',
               (key, str(workspace), owner['project_id'], terminal, source))
    return db.execute('SELECT * FROM work_sessions WHERE id=?', (key,)).fetchone()


def bind(root, key, workspace, task, terminal=None):
    from harness.context import context
    owner = context(root, Path(workspace), task)['tasks'][0]
    if owner['status'] in ('done', 'cancelled'):
        raise ValueError('Task must be active work before binding code changes')
    value, source = terminal_identity(terminal)
    with closing(database(root)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        row = ensure_session(root, db, key, workspace, (value, source) if value else None)
        if row['task'] and row['task'] != owner['id']:
            if db.execute("SELECT 1 FROM work_calls WHERE session=? AND state!='recorded'", (key,)).fetchone():
                raise ValueError('Cannot rebind unfinished observations to another Task')
        if row['task'] != owner['id']:
            db.execute('UPDATE work_sessions SET task=?,task_path=?,task_hash=?,handoff_hash=? WHERE id=?',
                       (owner['id'], owner['path'], owner['sha256'], handoff_hash(root, owner['path']), key))
        # Without a new value, keep any recorded terminal instead of erasing it.
        if value and (row['terminal'], row['terminal_source']) != (value, source):
            db.execute('UPDATE work_sessions SET terminal=?,terminal_source=? WHERE id=?', (value, source, key))
    return status(root, key)


def begin(root, key, tool, workspace, selected=None, on_begin=None):
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
        before = observation_manifest(workspace, selected)
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
        if on_begin is not None:
            on_begin(db)
    return {'pending': tool}


def finish(root, key, tool, reconciliation=None):
    with closing(database(root)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        call = db.execute("SELECT * FROM work_calls WHERE session=? AND tool=? AND state='pending'", (key, tool)).fetchone()
        if not call:
            raise ValueError('No matching pending code observation')
        session = db.execute('SELECT * FROM work_sessions WHERE id=?', (key,)).fetchone()
        selected = json.loads(call['targets']) if call['targets'] is not None else None
        changes = differences(json.loads(call['before_state']), observation_manifest(Path(session['workspace']), selected))
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
    with closing(database(root)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        call = db.execute('SELECT * FROM work_calls WHERE session=? AND tool=?', (key, tool)).fetchone()
        if not call or call['state'] == 'recorded':
            raise ValueError('Reconciliation requires an unfinished observation')
        if call['state'] == 'changed':
            session = db.execute('SELECT * FROM work_sessions WHERE id=?', (key,)).fetchone()
            current = observation_manifest(Path(session['workspace']), json.loads(call['changes']))
            inspected = {p: current.get(p) for p in json.loads(call['changes'])}
            db.execute('UPDATE work_calls SET reconciled_state=?,reconciliation=?,ambiguous=1,task_hash=?,handoff_hash=? WHERE id=?',
                       (json.dumps(inspected), reason, task_hash(root, session),
                        handoff_hash(root, session['task_path']), call['id']))
            db.commit()
            from harness.hooks import reconcile_pair
            reconcile_pair(root, key, tool)
            return status(root, key)
    result = finish(root, key, tool, reconciliation=reason)
    from harness.hooks import reconcile_pair
    reconcile_pair(root, key, tool)
    return result


def evidence_hash(root, evidence):
    """Read a stable regular Log file without following swapped path components."""
    try:
        relative = (root / evidence).relative_to(root)
        if relative.parts[:2] != ('wiki', 'log') or '..' in relative.parts:
            raise ValueError('Execution evidence must exist inside wiki/log')
        with ExitStack() as stack:
            parent = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            stack.callback(os.close, parent)
            opened = []
            for part in relative.parts[:-1]:
                fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                stack.callback(os.close, fd)
                opened.append((parent, part, os.fstat(fd)))
                parent = fd
            fd = os.open(relative.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            with os.fdopen(fd, 'rb') as stream:
                before = os.fstat(stream.fileno())
                if not stat.S_ISREG(before.st_mode):
                    raise ValueError('Execution evidence must be a regular file')
                digest = hashlib.sha256()
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(chunk)
                if signature(os.fstat(stream.fileno())) != signature(before):
                    raise ValueError('Execution evidence changed during reading')
            if signature(os.stat(relative.name, dir_fd=parent, follow_symlinks=False)) != signature(before):
                raise ValueError('Execution evidence was replaced during reading')
            for ancestor, part, info in opened:
                current = os.stat(part, dir_fd=ancestor, follow_symlinks=False)
                if (current.st_dev, current.st_ino, current.st_mode) != (info.st_dev, info.st_ino, info.st_mode):
                    raise ValueError('Execution evidence directory was replaced during reading')
            return digest.hexdigest()
    except OSError as exc:
        raise ValueError('Execution evidence must remain an accessible regular file inside Log') from exc


def write_receipt(root, payload):
    name = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-work-' + uuid.uuid4().hex[:8]
    try:
        with ExitStack() as stack:
            parent = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            stack.callback(os.close, parent)
            opened = []
            for part in ('wiki', 'log'):
                fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                stack.callback(os.close, fd)
                opened.append((parent, part, os.fstat(fd)))
                parent = fd
            os.mkdir(name, mode=0o700, dir_fd=parent)
            folder = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            stack.callback(os.close, folder)
            fd = os.open('record.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=folder)
            with os.fdopen(fd, 'w') as stream:
                stream.write(json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
            for ancestor, part, info in opened:
                current = os.stat(part, dir_fd=ancestor, follow_symlinks=False)
                if (current.st_dev, current.st_ino, current.st_mode) != (info.st_dev, info.st_ino, info.st_mode):
                    raise ValueError('Log directory changed during receipt creation')
    except OSError as exc:
        raise ValueError('Receipt requires a stable Log directory without symlinks') from exc
    return root / 'wiki/log' / name / 'record.json'


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
    source = root / evidence
    source_hash = evidence_hash(root, evidence)
    with closing(database(root)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        session = db.execute('SELECT * FROM work_sessions WHERE id=?', (key,)).fetchone()
        calls = db.execute("SELECT * FROM work_calls WHERE session=? AND state!='recorded' ORDER BY id", (key,)).fetchall()
        if any(c['state'] == 'pending' for c in calls):
            raise ValueError('Cannot record while calls are pending; finish the running tool, then run work record as a separate central CLI call. Reconcile only after confirming an interrupted writer has stopped.')
        if not calls:
            return {'recorded': 0, 'evidence': None,
                    'reason': 'no_unrecorded_observations',
                    'scope': 'Git tracked/unignored files and explicit code targets; unknown shell changes to ignored files are not observed',
                    'verification': 'observation-state-only; not proof that no files changed'}
        if not session or not session['task']:
            raise ValueError('Bind a central Task before recording work')
        from harness.context import context
        owner = context(root, Path(session['workspace']), session['task'])['tasks'][0]
        if owner['path'] != session['task_path']:
            raise ValueError('Bound Task owner changed; reconcile its identity before recording')
        current_task = task_hash(root, session)
        if current_task == session['task_hash'] or any(current_task == c['task_hash'] for c in calls):
            raise ValueError('Update the Task with current result and handoff after the code change')
        current_handoff = handoff_hash(root, session['task_path'])
        if current_handoff == session['handoff_hash'] or any(current_handoff == c['handoff_hash'] for c in calls):
            raise ValueError('Task handoff content must change; metadata-only edits do not record work')
        if any(c['ambiguous'] for c in calls) and not (isinstance(reconciliation, str) and reconciliation.strip()):
            raise ValueError('Writer overlap requires explicit reconciliation findings')
        expected = {}
        for call in calls:
            expected.update(json.loads(call['reconciled_state']) if call['reconciled_state'] is not None
                            else {p: value['after'] for p, value in json.loads(call['changes']).items()})
        actual = observation_manifest(Path(session['workspace']), expected)
        if any(actual.get(p) != value for p, value in expected.items()):
            raise ValueError('Observed files drifted; reconcile actual work before recording')
        payload = {'session': key, 'workspace': session['workspace'], 'project': session['project'],
                   'task': session['task'], 'task_path': session['task_path'], 'task_hash': current_task,
                   'source_evidence': str(source.relative_to(root)),
                   'source_evidence_hash': source_hash,
                   'reconciliation': reconciliation, 'verification': 'observations-and-record-linkage-only',
                   'observations': [{'tool': c['tool'], 'changes': json.loads(c['changes']),
                                     'attribution': 'explicit-target' if c['targets'] is not None else 'observed-window',
                                     'ambiguous': bool(c['ambiguous']), 'reconciliation': c['reconciliation'],
                                     'reconciled_state': json.loads(c['reconciled_state']) if c['reconciled_state'] is not None else None} for c in calls]}
        target = write_receipt(root, payload)
        if task_hash(root, session) != current_task:
            raise ValueError('Task drifted while recording; reconcile current handoff')
        latest = observation_manifest(Path(session['workspace']), expected)
        if any(latest.get(p) != value for p, value in expected.items()):
            raise ValueError('Observed files drifted during recording; reconcile actual work')
        if evidence_hash(root, evidence) != source_hash:
            raise ValueError('Execution evidence changed during recording')
        db.execute("UPDATE work_calls SET state='recorded' WHERE session=? AND state='changed'", (key,))
        db.execute('UPDATE work_sessions SET task_hash=?,handoff_hash=? WHERE id=?', (current_task, current_handoff, key))
    return {'recorded': len(calls), 'evidence': str(target.relative_to(root))}
