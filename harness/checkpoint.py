"""Detect lost before-state against the last validated local corpus checkpoint."""
import hashlib
import fcntl
import json
import os
from pathlib import Path
import re

from harness.documents import protected_paths, protected_roots, fingerprint
from harness.readiness import publication_state


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def baseline_path(root):
    return root / '.local/harness/checkpoint.json'


def state(root):
    return {p.relative_to(root).as_posix(): digest(p) for p in protected_paths(root)}


def issues(root, initialize=False):
    errors, _ = publication_state(root)
    baseline = baseline_path(root)
    if not baseline.exists():
        if not initialize:
            errors.append({'path': str(baseline.relative_to(root)), 'code': 'checkpoint-missing',
                           'message': 'Required preservation checkpoint is missing; restore it. Use --initialize only for a reviewed first setup'})
        return errors
    try:
        data = json.loads(baseline.read_text())
        if not isinstance(data, dict) or not isinstance(data.get('files'), dict):
            raise ValueError('files must be a mapping')
        if not isinstance(data.get('revision'), str) or not re.fullmatch(r'[0-9a-f]{64}', data['revision']):
            raise ValueError('revision must be a SHA-256 digest')
        previous = data['files']
        registered = protected_roots(root)
        if any(name not in registered for name in data.get('protected_roots', [])):
            raise ValueError('A protected domain was unregistered; restore its registration before checking')
        for name, sha in previous.items():
            if (not isinstance(name, str) or not name or Path(name).is_absolute()
                    or '..' in Path(name).parts or Path(name).as_posix() != name
                    or not isinstance(sha, str) or not re.fullmatch(r'[0-9a-f]{64}', sha)):
                raise ValueError('files must contain relative paths and SHA-256 digests')
    except (ValueError, TypeError, OSError) as exc:
        errors.append({'path': str(baseline.relative_to(root)), 'code': 'checkpoint-invalid',
                       'message': f'Invalid preservation checkpoint: {exc}'})
        return errors
    current = state(root)
    changed = {p: h for p, h in previous.items() if current.get(p) != h}
    preserved = set()
    relocated = set()
    for manifest in (root / 'wiki/log').glob('*/manifest.json'):
        try:
            entries = json.loads(manifest.read_text())['files']
            for entry in entries:
                name = entry.get('path', entry.get('source'))
                target = entry.get('target')
                if (target in current and name in previous
                        and Path(target).name == Path(name).name
                        and entry.get('sha256') == previous[name]):
                    before = manifest.parent / 'before' / name
                    before.resolve().relative_to((manifest.parent / 'before').resolve())
                    if digest(before) == previous[name]:
                        relocated.add(target)
                if name not in changed or entry.get('sha256') != changed[name]:
                    continue
                before = manifest.parent / 'before' / name
                before.resolve().relative_to((manifest.parent / 'before').resolve())
                if digest(before) == changed[name]:
                    preserved.add(name)
        except (ValueError, KeyError, OSError, TypeError):
            continue
    for name in changed.keys() - preserved:
        errors.append({'path': name, 'code': 'before-state',
                       'message': 'Changed/deleted owner has no hash-verified full before-state matching the checkpoint'})
    for name in current.keys() - previous.keys():
        if name in relocated:
            continue
        if name.startswith('wiki/sources/'):
            continue  # Domain-specific naming and frozen artifacts keep their original names.
        leaf = Path(name).name
        invalid = not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*\.[a-z0-9]+', leaf)
        invalid = invalid or bool(re.match(r'\d{4}-\d{2}-\d{2}', leaf)) or bool(re.search(r'(?:^|-)(?:latest|final)(?:-|\.md$)', leaf))
        if leaf not in {'README.md', 'AGENTS.md', '_map.md'} and invalid:
            errors.append({'path': name, 'code': 'filename', 'message': 'New current documents require lowercase kebab-case names'})
    return errors


def checkpoint(root, initialize=False):
    target = baseline_path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Keep the lock file: unlinking it lets another process lock a new inode.
    with (target.parent / 'checkpoint.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError('Another checkpoint is already running; retry after it finishes') from exc
        return _checkpoint(root, initialize)


def _checkpoint(root, initialize):
    from harness.check import check
    from harness.hooks import pending_issues
    from harness.preserve import snapshot, verify
    target = baseline_path(root)
    if initialize == target.exists():
        raise ValueError('Use --initialize only once for a corpus without a checkpoint')
    before = fingerprint(root)
    result = check(root, initialize=initialize)
    result['issues'].extend(pending_issues(root))
    result['ok'] = not result['issues']
    if not result['ok']:
        raise ValueError('Document check failed; checkpoint not advanced: ' + json.dumps(result['issues'], ensure_ascii=False))
    files = state(root)
    if target.exists():
        previous = json.loads(target.read_text())['files']
        changed = [name for name, sha in files.items() if previous.get(name) != sha]
        if changed:
            record = snapshot(root, changed, 'Preserve new checkpoint baseline bytes for continuing writers')
            verify(root, record)
            captured = {entry['path']: entry['sha256']
                        for entry in json.loads((record / 'manifest.json').read_text())['files']}
            if captured != {name: files[name] for name in changed}:
                raise ValueError('Corpus changed during checkpoint preservation; retry from current sources')
    if before != fingerprint(root):
        raise ValueError('Corpus changed during validation; retry from current sources')
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix('.tmp')
    temp.write_text(json.dumps({'files': files, 'revision': before, 'protected_roots': protected_roots(root)}, indent=2) + '\n')
    os.replace(temp, target)
    return {'ok': True, 'documents': len(files), 'revision': before,
            'verification': 'document-contract-and-before-state-only'}
