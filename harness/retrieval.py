"""Small, optional discovery declarations; Markdown remains their sole owner."""
from harness.documents import sections


def metadata(doc):
    if 'retrieval' not in doc.metadata:
        return {}
    value = doc.metadata['retrieval']
    fields = {'description', 'use_when', 'role', 'aliases', 'sections'}
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError('retrieval requires description, use_when, role, aliases and sections only')
    for name in ('description', 'use_when'):
        if not isinstance(value[name], str) or not value[name].strip() or len(value[name]) > 240:
            raise ValueError(f'retrieval.{name} must be 1–240 characters')
    if value['role'] not in ('guidance', 'policy', 'evidence', 'navigation'):
        raise ValueError('retrieval.role must be guidance, policy, evidence or navigation')
    for name, maximum in (('aliases', 8), ('sections', 4)):
        items = value[name]
        if not isinstance(items, list) or not 1 <= len(items) <= maximum or any(
                not isinstance(item, str) or not item.strip() or len(item) > 120 for item in items):
            raise ValueError(f'retrieval.{name} requires 1–{maximum} strings of 1–120 characters')
        if len(set(items)) != len(items):
            raise ValueError(f'retrieval.{name} must not contain duplicates')
    headings = [heading for heading, _ in sections(doc.body)]
    if any(headings.count(heading) != 1 for heading in value['sections']):
        raise ValueError('retrieval.sections must identify unique existing sections')
    return value


def card(doc):
    result = {'title': str(doc.metadata.get('title', doc.path.rsplit('/', 1)[-1])),
              'retrieval': metadata(doc)}
    for name in ('type', 'checked', 'verification'):
        if name in doc.metadata:
            result[name] = str(doc.metadata[name])
    return result


def read(root, path, selected=None, *, offset=0, limit=6000, expected_hash=None):
    """Read selected current-owner sections and their local applicability boundaries."""
    import re
    from harness.documents import parse, paths
    from harness import domains
    from harness.readiness import ensure_readable

    root = root.resolve()
    publication = ensure_readable(root)
    target = root / path
    owners = set(paths(root)) | set(domains.paths(root))
    if target.is_symlink() or target not in owners or target.suffix != '.md':
        raise ValueError('Read requires a canonical current Markdown owner')
    target.resolve().relative_to(root)
    name = target.relative_to(root).as_posix()
    doc = parse(name, target.read_bytes())
    if '/tasks/' in name or doc.metadata.get('type') == 'task':
        raise ValueError('Read the full Task with context --task or directly from its owner')
    if expected_hash and expected_hash != doc.sha256:
        raise ValueError('Owner changed; retrieve its current card before continuing')
    if not isinstance(offset, int) or offset < 0 or not 100 <= limit <= 12000:
        raise ValueError('offset must be nonnegative and limit 100–12000 characters')
    lines = doc.body.splitlines(keepends=True)
    headings = []
    fenced = False
    for number, line in enumerate(lines):
        if line.startswith(('```', '~~~')):
            fenced = not fenced
        match = re.match(r'^(#{1,6})\s+(.+?)\s*$', line) if not fenced else None
        if match:
            headings.append((number, len(match[1]), match[2]))
    names = [item[2] for item in headings]
    chosen = list(selected) if selected else list(metadata(doc).get('sections', []))
    if not chosen:
        raise ValueError('Choose sections explicitly for an owner without retrieval metadata')
    for boundary in ('Applicability', 'Constraints', 'Evidence', 'Authority', 'Prerequisites', 'Verification'):
        if boundary in names and boundary not in chosen:
            chosen.append(boundary)
    included = set()
    for heading in chosen:
        if names.count(heading) != 1:
            raise ValueError(f'Choose a unique existing section: {heading}')
        start, level, _ = headings[names.index(heading)]
        end = next((line for line, depth, _ in headings if line > start and depth <= level), len(lines))
        included.update(range(start, end))
    content = ''.join(lines[i] for i in sorted(included))
    if offset > len(content):
        raise ValueError('offset exceeds selected content')
    end = min(offset + limit, len(content))
    if target.read_bytes() != doc.text.encode('utf-8'):
        raise ValueError('Owner changed during read; retry')
    ensure_readable(root, publication)
    return {**card(doc), 'path': name, 'sha256': doc.sha256, 'sections': chosen,
            'content': content[offset:end], 'offset': offset, 'total_characters': len(content),
            'next_offset': end if end < len(content) else None, 'truncated': end < len(content),
            'verification': 'retrieval-only', 'declared_verification': str(doc.metadata.get('verification', 'unspecified'))}
