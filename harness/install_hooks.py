"""Idempotently add the single shared adapter to existing Codex/Claude settings."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shlex
import sys
import uuid

MARKER = 'Central Wiki document contract'


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def merged(data, command, agent):
    # Round-trip to avoid mutating the supplied config during preview/tests.
    data = json.loads(json.dumps(data))
    hooks = data.setdefault('hooks', {})
    if not isinstance(hooks, dict):
        raise ValueError('hooks must be an object')
    events = ['SessionStart', 'PreToolUse', 'PostToolUse', 'Stop']
    if agent == 'claude':
        events.append('PostToolUseFailure')
    for event in events:
        groups = hooks.setdefault(event, [])
        if not isinstance(groups, list):
            raise ValueError('Hook event must contain a list')
        kept = []
        for group in groups:
            group = dict(group)
            handlers = [h for h in group.get('hooks', []) if h.get('statusMessage') != MARKER]
            if handlers:
                group['hooks'] = handlers
                kept.append(group)
        group = {'hooks': [{'type': 'command', 'command': command, 'timeout': 15, 'statusMessage': MARKER}]}
        if event in ('PreToolUse', 'PostToolUse', 'PostToolUseFailure'):
            group['matcher'] = '.*' if agent == 'codex' else '*'
        kept.append(group)
        hooks[event] = kept
    return data


def install(root, home, python):
    root, home, python = root.resolve(), home.resolve(), python.absolute()
    if not python.is_file() or not (root / 'harness/hooks.py').is_file():
        raise ValueError('Installed Python and central adapter must exist')
    plans = []
    for agent, suffix in [('codex', '.codex/hooks.json'), ('claude', '.claude/settings.json')]:
        target = home / suffix
        before = target.read_bytes() if target.exists() else None
        data = json.loads(before) if before is not None else {}
        if agent == 'claude' and data.get('disableAllHooks'):
            raise ValueError('Claude disables all hooks; do not silently change that setting')
        command = shlex.join([str(python), str(root / 'harness/hooks.py'), '--agent', agent])
        after = (json.dumps(merged(data, command, agent), ensure_ascii=False, indent=2) + '\n').encode()
        plans.append((agent, target, before, after))
    if all(before == after for _, _, before, after in plans):
        return {'changed': False, 'verification': 'configuration-only-not-runtime-trust'}
    record = root / 'wiki/log' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-hook-install-' + uuid.uuid4().hex[:8])
    record.mkdir(parents=True)
    manifest = {'files': []}
    for agent, target, before, after in plans:
        if before is None:
            continue
        name = f'machine/{agent}.json'
        saved = record / 'before' / name
        saved.parent.mkdir(parents=True, exist_ok=True)
        saved.write_bytes(before)
        if digest(saved.read_bytes()) != digest(before):
            raise ValueError('Config preservation failed')
        manifest['files'].append({'path': name, 'source_path': str(target), 'sha256': digest(before)})
    (record / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    # Check both sources before changing either; preserve each before-state above.
    for _, target, before, _ in plans:
        if (target.read_bytes() if target.exists() else None) != before:
            raise ValueError('Configuration changed during preparation; retry')
    result = []
    for agent, target, before, after in plans:
        if (target.read_bytes() if target.exists() else None) != before:
            raise ValueError('Configuration changed during installation; inspect preserved record')
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + '.wiki-' + uuid.uuid4().hex)
        try:
            temporary.write_bytes(after)
            temporary.chmod(target.stat().st_mode & 0o777 if target.exists() else 0o600)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        result.append({'agent': agent, 'path': str(target), 'sha256': digest(target.read_bytes())})
    (record / 'installed.json').write_text(json.dumps(result, indent=2) + '\n')
    return {'changed': True, 'record': str(record.relative_to(root)), 'configs': result,
            'verification': 'configuration-only-not-runtime-trust'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, default=Path.home())
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    print(json.dumps(install(args.root, args.home, Path(sys.executable)), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
