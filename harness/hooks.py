"""One Codex/Claude hook adapter. No prompts, shell evaluation or network calls."""
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import sqlite3
import sys
import uuid

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.check import check
from harness.checkpoint import baseline_path, digest
from harness.documents import fingerprint
from harness.layout import excluded
from harness.readiness import ensure_readable

ROOT = Path(__file__).resolve().parents[1]
EVENTS = ('SessionStart', 'PreToolUse', 'PostToolUse', 'PostToolUseFailure', 'Stop')


def role(root, path):
    try:
        name = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return 'outside'
    if excluded(name) or name.startswith('orchestration/'):
        return 'outside'
    if name.startswith(('wiki/log/', 'wiki/sources/')):
        if name.startswith('wiki/sources/'):
            from harness.domains import paths as domain_paths
            if any(path.resolve() == owner.resolve() for owner in domain_paths(root)):
                return 'current'
        return 'evidence'
    if name in {'README.md', 'AGENTS.md', 'wiki/index.md', 'wiki/profile.md'} or name.startswith(('wiki/notes/', 'wiki/projects/', 'docs/')):
        return 'current'
    return 'outside'


def targets(payload, resolve=True):
    tool = payload.get('tool_name', '')
    data = payload.get('tool_input', {})
    if not isinstance(data, dict):
        raise ValueError('tool_input must be an object')
    cwd = Path(payload.get('cwd', '.')).resolve()
    def target(name):
        path = cwd / name
        return path.resolve() if resolve else Path(os.path.abspath(path))
    if tool in ('Edit', 'Write', 'MultiEdit'):
        name = data.get('file_path')
        if not isinstance(name, str) or not name:
            raise ValueError('Edit/Write requires file_path')
        return [target(name)]
    if tool == 'apply_patch':
        command = data.get('command', data.get('patch', data.get('input', '')))
        if not isinstance(command, str):
            raise ValueError('apply_patch requires a patch string')
        names = re.findall(r'^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+)$', command, re.M)
        if not names:
            raise ValueError('Cannot determine apply_patch targets')
        return list(dict.fromkeys(target(name) for name in names))
    return []


def registered(root, cwd):
    registry = root / '.local/harness/projects.json'
    if not registry.exists():
        return False
    from harness.context import git_common
    entries = json.loads(registry.read_text())['projects']
    cwd = Path(cwd).resolve()
    if any(cwd == Path(p['root']).resolve() or Path(p['root']).resolve() in cwd.parents for p in entries):
        return True
    common = git_common(cwd) if cwd.is_dir() else None
    return bool(common and any(p.get('git_common_dir') == common for p in entries))


def preserved(root, path):
    name = path.relative_to(root).as_posix()
    expected = digest(path)
    for manifest in (root / 'wiki/log').glob('*/manifest.json'):
        try:
            for item in json.loads(manifest.read_text())['files']:
                if item.get('path', item.get('source')) != name or item.get('sha256') != expected:
                    continue
                before = manifest.parent / 'before' / name
                before.resolve().relative_to((manifest.parent / 'before').resolve())
                if digest(before) == expected:
                    return True
        except (OSError, ValueError, TypeError, KeyError):
            continue
    return False


def database(root):
    path = root / '.local/harness/hook-state.sqlite'
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=2)
    db.execute('CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, revision TEXT NOT NULL, dirty INTEGER NOT NULL DEFAULT 0, retries INTEGER NOT NULL DEFAULT 0, failure TEXT, verdict TEXT, evidence TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS pending (path TEXT PRIMARY KEY, session TEXT NOT NULL, before_hash TEXT)')
    db.commit()
    return db


def issue(code, message):
    return {'code': code, 'message': message}


def output(event, verdict, code, message):
    text = f'[wiki-harness:{code}] {message}'
    if event == 'PreToolUse' and verdict == 'deny':
        return {'hookSpecificOutput': {'hookEventName': event, 'permissionDecision': 'deny',
                                       'permissionDecisionReason': text}}
    if event == 'Stop' and verdict == 'repair':
        return {'decision': 'block', 'reason': text}
    if verdict == 'pass' and not message:
        return {}
    if event in ('SessionStart', 'PostToolUse', 'PreToolUse'):
        return {'hookSpecificOutput': {'hookEventName': event, 'additionalContext': text}}
    return {'systemMessage': text}


def result_log(root, key, result, revision):
    from datetime import datetime, timezone
    record = root / 'wiki/log' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-hook-' + uuid.uuid4().hex[:8])
    record.mkdir(parents=True)
    data = {'checked': datetime.now(timezone.utc).isoformat(), 'session': key, 'revision': revision,
            'verification': 'document-contract-only', **result}
    (record / 'result.json').write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    return str(record.relative_to(root))


def pending_issues(root):
    path = root / '.local/harness/hook-state.sqlite'
    if not path.exists():
        return []
    with closing(sqlite3.connect(f'{path.as_uri()}?mode=ro', uri=True, timeout=2)) as db:
        rows = db.execute('SELECT path FROM pending').fetchall()
    return [dict(path=name, code='hook-pending', message='Unfinished hooked edit; reconcile its session before checkpoint') for (name,) in rows]


def handle_documents(root, agent, payload, scoped=False, own_change=False):
    root = root.resolve()
    event = payload.get('hook_event_name')
    if event not in EVENTS:
        return {}
    raw_session = payload.get('session_id')
    if not isinstance(raw_session, str) or not raw_session:
        raise ValueError('Hook requires session_id')
    key = agent + ':' + raw_session
    selected = targets(payload) if event in ('PreToolUse', 'PostToolUse', 'PostToolUseFailure') else []
    current = [p for p in selected if role(root, p) == 'current']
    evidence = [p for p in selected if role(root, p) == 'evidence']
    # Explicit targets outside the managed corpus must not inherit vault gates.
    if selected and not current and not evidence:
        return {}
    relevant = bool(current or evidence) or registered(root, payload.get('cwd', '.'))
    state_path = root / '.local/harness/hook-state.sqlite'
    if not relevant and not state_path.exists():
        return {}
    with closing(database(root)) as db:
        row = db.execute('SELECT revision,dirty,retries,failure FROM sessions WHERE id=?', (key,)).fetchone()
        if not relevant and row is None:
            return {}
        revision = fingerprint(root)
        if row is None:
            db.execute('INSERT INTO sessions(id,revision) VALUES (?,?)', (key, revision))
            db.commit()
            row = (revision, 0, 0, None)
        if event == 'SessionStart':
            return output(event, 'info', 'context', f'Read {root}/wiki/notes/agents/work-management-policy.md. Use harness context for the full Task. Snapshot existing documents before edits; check and checkpoint before finishing. Pending edits: {len(pending_issues(root))}.')
        if event == 'PreToolUse':
            if any(p.exists() for p in evidence):
                return output(event, 'deny', 'evidence-immutable', 'Existing source/log files require their domain-specific preservation workflow. Do not overwrite original evidence.')
            if not current:
                return {}
            ensure_readable(root)
            # Validate required baseline without making pre-existing content errors
            # prevent a correctly preserved repair edit.
            from harness.checkpoint import issues
            invalid = [i for i in issues(root) if i['code'] in ('checkpoint-missing', 'checkpoint-invalid')]
            if invalid:
                return output(event, 'deny', invalid[0]['code'], invalid[0]['message'])
            for p in current:
                if p.exists() and (not p.is_file() or not preserved(root, p)):
                    return output(event, 'deny', 'before-state', f'Run harness snapshot and verify the exact current bytes before editing {p.relative_to(root)}.')
                if not p.exists() and (p.suffix == '.md'):
                    if p.name not in {'README.md', 'AGENTS.md', '_map.md'} and (not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*\.md', p.name) or re.match(r'\d{4}-\d{2}-\d{2}', p.name) or re.search(r'(?:^|-)(?:latest|final)(?:-|\.md$)', p.name)):
                        return output(event, 'deny', 'filename', 'New current documents require stable lowercase kebab-case names.')
            db.execute('BEGIN IMMEDIATE')
            for p in current:
                name = p.relative_to(root).as_posix()
                prior = db.execute('SELECT session FROM pending WHERE path=?', (name,)).fetchone()
                if prior:
                    db.rollback()
                    return output(event, 'deny', 'writer-conflict', f'{name} has an unfinished edit. Reconcile its pending session; do not take over by age.')
            for p in current:
                db.execute('INSERT INTO pending VALUES (?,?,?)', (p.relative_to(root).as_posix(), key, digest(p) if p.exists() else None))
            db.commit()
            return {}
        if event in ('PostToolUse', 'PostToolUseFailure'):
            if current:
                for p in current:
                    db.execute('DELETE FROM pending WHERE path=? AND session=?', (p.relative_to(root).as_posix(), key))
            changed = own_change if scoped else revision != row[0] or bool(current)
            if changed:
                db.execute('UPDATE sessions SET dirty=1 WHERE id=?', (key,))
            db.commit()
            if not changed:
                return {}
            result = check(root)
            if not result['ok']:
                return output(event, 'repair', 'document-check', 'Edit has already run. Repair and rerun harness check: ' + json.dumps(result['issues'][:3], ensure_ascii=False))
            return {}
        if event == 'Stop':
            if not row[1] and (scoped or revision == row[0]) and not db.execute('SELECT 1 FROM pending WHERE session=?', (key,)).fetchone():
                return {}
            result = check(root)
            pending = pending_issues(root)
            result['issues'].extend(pending)
            try:
                checkpoint_revision = json.loads(baseline_path(root).read_text())['revision']
            except (OSError, ValueError, KeyError, TypeError):
                checkpoint_revision = None
            if result['ok'] and not pending and checkpoint_revision != revision:
                result['issues'].append(issue('checkpoint-stale', 'After updating Task and evidence, run harness checkpoint; the hook never advances it automatically.'))
            result['ok'] = not result['issues']
            log = result_log(root, key, result, revision)
            if result['ok']:
                db.execute('UPDATE sessions SET revision=?,dirty=0,retries=0,failure=NULL,verdict=?,evidence=? WHERE id=?', (revision, 'pass', log, key))
                db.commit()
                return {}
            failure = hashlib.sha256((revision + json.dumps(result['issues'], sort_keys=True)).encode()).hexdigest()
            repeat = row[3] == failure or row[2] >= 3 or (payload.get('stop_hook_active') and row[2] == 0)
            db.execute('UPDATE sessions SET dirty=1,retries=retries+1,failure=?,verdict=?,evidence=? WHERE id=?', (failure, 'unverified' if repeat else 'repair', log, key))
            db.commit()
            message = f'Validation incomplete; evidence: {log}. ' + json.dumps(result['issues'][:3], ensure_ascii=False)
            if repeat:
                return output(event, 'unverified', 'handoff-required', message + ' Stop retrying this unchanged failure; report remaining work, not completion.')
            return output(event, 'repair', 'validation-required', message)
    return {}


def control_command(root, cwd, command):
    """Recognize only central CLI batches; never evaluate shell input.

    Newlines and && may join pure controls. Every segment must qualify;
    mixed code/control scripts still receive an ordinary work observation.
    """
    if not isinstance(command, str) or any(c in command for c in '\r$`;|<>()*?[]{}~'):
        return False
    segments = [line.strip() for line in command.strip().split('\n') if line.strip()]
    segments = [part.strip() for line in segments for part in line.split('&&')]
    if not segments or any(not part for part in segments):
        return False
    try:
        commands = [shlex.split(part) for part in segments]
    except ValueError:
        return False
    if commands[0][:1] == ['cd']:
        if len(commands[0]) != 2 or Path(commands[0][1]).resolve() != root.resolve():
            return False
        # Only the established cd ROOT && prefix changes the CLI location.
        if '&&' not in command.split('\n', 1)[0]:
            return False
        commands = commands[1:]
    elif Path(cwd).resolve() != root.resolve():
        return False
    if not commands:
        return False
    interpreters = {'python', 'python3', str(root / '.venv/bin/python')}
    for words in commands:
        if any('&' in word for word in words):
            return False
        if words[:2] == ['uv', 'run']:
            words = words[2:]
        if len(words) < 4 or words[0] not in interpreters or words[1:3] != ['-m', 'harness']:
            return False
        if words[3] == '--root':
            if len(words) < 6 or Path(words[4]).resolve() != root.resolve():
                return False
            words = words[:3] + words[5:]
        if words[3] == 'work':
            if len(words) <= 4 or words[4] not in {'bind', 'record', 'status', 'reconcile'}:
                return False
        elif words[3] not in {'context', 'search', 'index', 'snapshot', 'verify', 'check', 'checkpoint', 'structure', 'catalog', 'read'}:
            return False
    return True


def paired_database(root):
    db = database(root)
    db.execute('CREATE TABLE IF NOT EXISTS hook_calls (session TEXT NOT NULL, tool TEXT NOT NULL, paths TEXT NOT NULL, before_docs TEXT, revision TEXT NOT NULL, observes_work INTEGER NOT NULL, PRIMARY KEY(session,tool))')
    db.commit()
    return db


def pair_changed(root, call):
    before = json.loads(call[1]) if call[1] is not None else None
    return (fingerprint(root) != call[2] if before is None else
            any((digest(Path(p)) if Path(p).is_file() else None) != value for p, value in before.items()))


def reconcile_pair(root, key, tool):
    """Explicit writer reconciliation retains document verification obligations."""
    with closing(paired_database(root)) as db, db:
        call = db.execute('SELECT paths,before_docs,revision FROM hook_calls WHERE session=? AND tool=?', (key, tool)).fetchone()
        if not call:
            return
        if pair_changed(root, call):
            db.execute('UPDATE sessions SET dirty=1 WHERE id=?', (key,))
        for name in json.loads(call[0]):
            path = Path(name)
            if path.is_relative_to(root):
                db.execute('DELETE FROM pending WHERE path=? AND session=?', (str(path.relative_to(root)), key))
        db.execute('DELETE FROM hook_calls WHERE session=? AND tool=?', (key, tool))


def handle(root, agent, payload):
    root = root.resolve()
    config = root / '.local/harness/projects.json'
    enabled = json.loads(config.read_text()).get('work_contract', 0) if config.exists() else 0
    if enabled not in (0, 1):
        raise ValueError('Unsupported work_contract')
    if not enabled:
        # A configuration toggle is not evidence that previous work was recorded.
        state = root / '.local/harness/hook-state.sqlite'
        if state.exists():
            key = agent + ':' + str(payload.get('session_id', ''))
            with closing(database(root)) as db:
                tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                enabled = bool(('work_calls' in tables and db.execute("SELECT 1 FROM work_calls WHERE session=? AND state!='recorded'", (key,)).fetchone()) or
                               ('hook_calls' in tables and db.execute('SELECT 1 FROM hook_calls WHERE session=?', (key,)).fetchone()))
        if not enabled:
            return handle_documents(root, agent, payload)
    from harness import work
    event = payload.get('hook_event_name')
    raw_session = payload.get('session_id')
    if not isinstance(raw_session, str) or not raw_session:
        raise ValueError('Hook requires session_id')
    key = agent + ':' + raw_session
    cwd = Path(payload.get('cwd', '.')).resolve()
    tool = payload.get('tool_use_id')
    name = payload.get('tool_name')
    if event == 'SessionStart':
        response = handle_documents(root, agent, payload, scoped=True)
        if registered(root, cwd):
            from harness.context import context
            owner = context(root, cwd)
            return output(event, 'info', 'context',
                          f'Agent: {agent}. Session ID: {raw_session}. CLI identity: --agent {agent} --session {raw_session}. Workspace: {cwd}. Read {root}/wiki/notes/agents/work-management-policy.md and the full central Task. '
                          'Bind this session to its Task before code changes; update the Task and record actual evidence before finishing. '
                          'Unfinished work in this worktree: ' + json.dumps(owner['unfinished_work'], ensure_ascii=False) +
                          f' Knowledge discovery root: {root}. Before substantive writing, design or troubleshooting advice, '
                          'including read-only proposals, select relevant guidance from these routes and read its applicability '
                          'and evidence before answering. Simple factual lookups need no invented Task. '
                          'Use search --brief for topic candidates and read PATH for selected sections from this root. '
                          'Routes (links resolve against links_relative_to under the discovery root): ' +
                          json.dumps(owner['navigation'], ensure_ascii=False))
        return response
    if event == 'PreToolUse':
        if name not in {'Bash', 'Edit', 'Write', 'MultiEdit', 'apply_patch'}:
            return handle_documents(root, agent, payload, scoped=True)
        command = payload.get('tool_input', {}).get('command', '')
        if name == 'Bash' and control_command(root, cwd, command):
            return handle_documents(root, agent, payload, scoped=True)
        selected = targets(payload)
        observes_work = registered(root, cwd)
        if not observes_work and not any(role(root, p) in {'current', 'evidence'} for p in selected):
            return {}
        if not isinstance(tool, str) or not tool:
            return output(event, 'deny', 'tool-id-missing', 'Paired work observation requires tool_use_id.')
        with closing(paired_database(root)) as db:
            if db.execute('SELECT 1 FROM hook_calls WHERE session=? AND tool=?', (key, tool)).fetchone():
                return output(event, 'deny', 'tool-id-duplicate', 'Reconcile the unfinished call before retrying its ID.')
        response = handle_documents(root, agent, payload, scoped=True)
        if response.get('hookSpecificOutput', {}).get('permissionDecision') == 'deny':
            return response
        before_docs = {str(p): digest(p) if p.is_file() else None for p in selected if role(root, p) == 'current'}
        def save_pair(db):
            db.execute('INSERT INTO hook_calls VALUES (?,?,?,?,?,?)',
                       (key, tool, json.dumps([str(p) for p in selected]),
                        json.dumps(before_docs) if selected else None, fingerprint(root), int(observes_work)))
        try:
            if observes_work:
                workspace = work.repository(cwd)
                lexical = targets(payload, resolve=False)
                relative = [str(p.relative_to(workspace)) for p in lexical
                            if p.is_relative_to(workspace) and role(root, p) == 'outside'] if lexical else None
                work.begin(root, key, tool, workspace, relative, on_begin=save_pair)
            else:
                with closing(paired_database(root)) as db, db:
                    save_pair(db)
        except Exception:
            # This Pre failed before a tool could run. Release only its document targets.
            with closing(database(root)) as db, db:
                for p in selected:
                    if p.is_relative_to(root):
                        db.execute('DELETE FROM pending WHERE path=? AND session=?', (str(p.relative_to(root)), key))
            raise
        return response
    if event in ('PostToolUse', 'PostToolUseFailure'):
        with closing(paired_database(root)) as db:
            call = db.execute('SELECT paths,before_docs,revision,observes_work FROM hook_calls WHERE session=? AND tool=?', (key, tool)).fetchone()
        if not call:
            # Read tools and pure CLI controls never create observations.
            return {}
        paths = json.loads(call[0])
        changed = pair_changed(root, call)
        if call[3]:
            with closing(work.database(root)) as db:
                pending = db.execute("SELECT 1 FROM work_calls WHERE session=? AND tool=? AND state='pending'", (key, tool)).fetchone()
            if pending:
                work.finish(root, key, tool)
        paired = dict(payload, tool_name='apply_patch' if paths else 'Bash',
                      tool_input={'command': '\n'.join('*** Update File: ' + p for p in paths) if paths else ''})
        response = handle_documents(root, agent, paired, scoped=True, own_change=changed)
        with closing(paired_database(root)) as db, db:
            db.execute('DELETE FROM hook_calls WHERE session=? AND tool=?', (key, tool))
        return response
    if event == 'Stop':
        state = work.status(root, key)
        with closing(paired_database(root)) as db:
            pending = db.execute('SELECT tool FROM hook_calls WHERE session=?', (key,)).fetchall()
        issues = list(state['issues'])
        if pending and 'work-pending' not in issues:
            issues.append('work-pending')
        if issues:
            result = {'ok': False, 'issues': [{'code': c} for c in issues], 'work': state}
            log = result_log(root, key, result, fingerprint(root))
            return output(event, 'unverified' if payload.get('stop_hook_active') else 'repair',
                          'work-record-required', f'Reconcile actual writer/workspace, update the full Task and record evidence. Evidence: {log}. ' + json.dumps(issues))
        return handle_documents(root, agent, payload, scoped=True)
    return handle_documents(root, agent, payload, scoped=True)


def recover(root, agent, session, unchanged_only=False):
    """Explicit reconciliation, never based on age; does not fabricate before-state."""
    result = check(root)
    if not result['ok'] and not unchanged_only:
        raise ValueError('Repair document check failures before releasing pending edits')
    key = agent + ':' + session
    with closing(database(root)) as db:
        db.execute('BEGIN IMMEDIATE')
        pending = db.execute('SELECT path,before_hash FROM pending WHERE session=?', (key,)).fetchall()
        if unchanged_only:
            for name, before_hash in pending:
                path = root / name
                if path.resolve() != path.absolute() or not path.is_relative_to(root):
                    raise ValueError('Pending path changed or is unsafe')
                current_hash = digest(path) if path.is_file() else None
                if current_hash != before_hash or (path.exists() and not path.is_file()):
                    raise ValueError('Pending file changed; unchanged-only recovery refused')
        log = result_log(root, key, {**result, 'document_check_ok': result['ok'],
                                    'operation': 'unchanged-reconciliation' if unchanged_only else 'explicit-reconciliation',
                                    'pending': pending}, fingerprint(root))
        db.execute('DELETE FROM pending WHERE session=?', (key,))
        db.execute('UPDATE sessions SET dirty=1,retries=0,failure=NULL WHERE id=?', (key,))
        db.commit()
    return {'reconciled': len(pending), 'evidence': log, 'document_check_ok': result['ok']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--agent', choices=('codex', 'claude'), required=True)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--recover-session')
    parser.add_argument('--unchanged-only', action='store_true')
    args = parser.parse_args()
    if args.unchanged_only and not args.recover_session:
        parser.error('--unchanged-only requires --recover-session')
    payload = {}
    try:
        if args.recover_session:
            print(json.dumps(recover(args.root.resolve(), args.agent, args.recover_session, args.unchanged_only)))
            return 0
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise ValueError('Hook input must be a JSON object')
        print(json.dumps(handle(args.root, args.agent, payload), ensure_ascii=False))
        return 0
    except Exception as exc:
        # Hook errors are not automatically blocking in either runtime. Emit a
        # supported PreToolUse denial; never send tool inputs or secrets back.
        event = payload.get('hook_event_name') if isinstance(payload, dict) else None
        message = f'Central document hook unavailable ({type(exc).__name__}). Diagnose the adapter; do not claim successful verification.'
        if event == 'PreToolUse':
            print(json.dumps(output(event, 'deny', 'hook-unavailable', message)))
            return 0
        if event == 'Stop' and not payload.get('stop_hook_active'):
            print(json.dumps(output(event, 'repair', 'hook-unavailable', message)))
            return 0
        print(json.dumps({'systemMessage': '[wiki-harness:unverified] ' + message}))
        return 0


if __name__ == '__main__':
    sys.exit(main())
