"""Shared publication gate for validation and current-context readers."""
import hashlib
import json


def publication_state(root):
    errors, revision = [], []
    for journal in sorted((root / 'wiki/log').glob('*/publication.json')):
        name = journal.relative_to(root).as_posix()
        try:
            raw = journal.read_bytes()
            revision.append((name, hashlib.sha256(raw).hexdigest()))
            data = json.loads(raw)
            if not isinstance(data, dict) or data.get('status') not in {'prepared', 'applied'}:
                raise ValueError('Invalid publication journal')
            if data['status'] != 'applied':
                errors.append({'path': name, 'code': 'interrupted-update',
                               'message': 'Finish the prepared migration before reading current documents'})
        except (ValueError, TypeError, OSError) as exc:
            errors.append({'path': name, 'code': 'migration-journal',
                           'message': f'Invalid publication journal: {exc}'})
    return errors, revision


def ensure_readable(root, expected=None):
    errors, revision = publication_state(root)
    if errors:
        raise ValueError('Current publication is not readable: ' + json.dumps(errors))
    if expected is not None and revision != expected:
        raise ValueError('Publication changed during read; retry after migration finishes')
    return revision
