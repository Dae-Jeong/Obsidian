"""Authoring contracts read from templates; adoption is an explicit corpus gate."""
import json
from collections import Counter
import re
from datetime import date, datetime
from pathlib import Path

import yaml

from harness.documents import parse, paths

TEMPLATES = Path(__file__).parent / 'templates'
NOTE_TEMPLATES = {'concept': 'note', 'procedure': 'note-procedure',
                  'reference': 'note-reference', 'policy': 'note-policy'}


def role(path):
    parts = Path(path).parts
    if path in {'AGENTS.md', 'README.md', 'wiki/index.md', 'wiki/profile.md'} or (parts and parts[0] == 'docs' and Path(path).suffix == '.md'):
        return 'document'
    if parts[:2] == ('wiki', 'log'):
        return 'log'
    if parts[:2] not in {('wiki', 'notes'), ('wiki', 'projects')}:
        return None
    if Path(path).name == 'index.md':
        return 'project' if parts[:2] == ('wiki', 'projects') and len(parts) == 4 else 'index'
    if parts[:2] == ('wiki', 'projects') and len(parts) >= 5:
        if parts[3] == 'tasks':
            return 'task'
        if parts[3] == 'reviews':
            return 'review'
    return 'note'


def contract(kind, subject_type=None):
    if kind == 'document':
        return {}, []
    if kind == 'index':
        return {'type': 'index', 'title': '{{title}}'}, []
    name = kind
    if kind == 'note':
        if subject_type not in NOTE_TEMPLATES:
            raise ValueError('Note subject_type must be concept, procedure, reference or policy')
        name = NOTE_TEMPLATES[subject_type]
    template = parse(name, (TEMPLATES / f'{name}.md').read_bytes())
    required = []
    for match in re.finditer(r'^## ([^\n]+)\n(.*?)(?=^## |\Z)', template.body, re.M | re.S):
        if '<!-- Required' in match[2]:
            required.append(match[1])
    return template.metadata, required


def heading_rows(body):
    """ATX headings with line offsets; fenced examples/comments are not structure."""
    lines = re.sub(r'<!--.*?-->', lambda m: '\n' * m[0].count('\n'), body, flags=re.S).splitlines()
    fence = None
    result = []
    for number, line in enumerate(lines):
        marker = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$', line)
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not marker[2].strip():
                fence = None
            continue
        if marker:
            fence = marker[1]
            continue
        match = re.match(r'^ {0,3}(#{1,6})\s+(.+?)\s*$', line)
        if match:
            result.append((number, len(match[1]), re.sub(r'\s+#+$', '', match[2])))
    return result


def prose(body):
    """Hide fenced examples while retaining line offsets."""
    fence = None
    lines = []
    for line in body.splitlines():
        marker = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$', line)
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not marker[2].strip():
                fence = None
            lines.append('')
        elif marker:
            fence = marker[1]
            lines.append('')
        else:
            lines.append(line)
    return '\n'.join(lines)


def template_order(kind, subject_type=None):
    if kind in {'index', 'document'}:
        return []
    name = NOTE_TEMPLATES[subject_type] if kind == 'note' else kind
    template = parse(name, (TEMPLATES / f'{name}.md').read_bytes())
    return [title for _, level, title in heading_rows(template.body) if level == 2]


def actual_date(value):
    if isinstance(value, datetime) or not isinstance(value, (date, str)):
        return False
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', str(value)):
        return False
    try:
        date.fromisoformat(str(value))
    except ValueError:
        return False
    return True


def validate(document):
    kind = role(document.path)
    if kind is None:
        return []
    errors = []

    def error(code, message):
        errors.append({'path': document.path, 'code': code, 'message': message})

    meta = document.metadata
    try:
        expected, headings = contract(kind, meta.get('subject_type'))
    except (ValueError, TypeError):
        error('structure-subtype', 'Select a Note purpose: concept, procedure, reference or policy')
        return errors
    for field, sample in expected.items():
        if field not in meta:
            error('structure-field', f'Missing {field} for {kind}')
            continue
        value = meta[field]
        if field in {'checked', 'recorded'}:
            if field == 'checked' and value is None and kind != 'task':
                continue
            if not actual_date(value):
                error('structure-date', f'{field} requires an actual ISO date')
        elif isinstance(sample, list):
            if not isinstance(value, list) or any(not isinstance(x, str) or not x.strip() for x in value):
                error('structure-type', f'{field} requires a list of nonempty strings')
        elif not isinstance(value, str) or not value.strip():
            error('structure-type', f'{field} requires nonempty text')
    if 'type' in expected and meta.get('type') != expected['type']:
        error('structure-location', f'{kind} location requires type: {expected["type"]}')
    if kind in {'note', 'review'}:
        verification = meta.get('verification')
        if not isinstance(verification, str) or verification not in {'unverified', 'partial', 'verified'}:
            error('structure-verification', 'verification requires unverified, partial or verified')
        elif verification != 'unverified' and not actual_date(meta.get('checked')):
            error('structure-date', 'A partial or verified review requires its actual checked date')
    if kind == 'task':
        if meta.get('kind') != 'task':
            error('structure-type', 'Task requires kind: task')
        status = meta.get('status')
        if not isinstance(status, str) or status not in {'ready', 'active', 'blocked', 'review', 'done', 'cancelled'}:
            error('structure-status', 'Unknown Task status')
        if status == 'blocked' and not all(isinstance(meta.get(k), str) and meta[k].strip()
                                           for k in ('blocker', 'unblock_condition')):
            error('structure-blocker', 'Blocked Task requires blocker and unblock_condition text')
        if status == 'done' and not meta.get('evidence'):
            error('structure-evidence', 'Done Task requires evidence')
    if kind in {'task', 'project'} and meta.get('project_id') != Path(document.path).parts[2]:
        error('structure-project', 'project_id must match the owning folder')
    text = prose(document.body)
    clean = re.sub(r'<!--.*?-->', '', text, flags=re.S)
    rows = heading_rows(document.body)
    h2 = [title for _, level, title in rows if level == 2]
    if sum(level == 1 for _, level, _ in rows) != 1:
        error('structure-title', 'Exactly one document H1 is required')
    duplicates = [title for title, count in Counter(h2).items() if count > 1]
    if duplicates:
        error('structure-duplicate-heading', 'Duplicate H2: ' + ', '.join(duplicates))
    order = template_order(kind, meta.get('subject_type'))
    if [title for title in h2 if title in order] != [title for title in order if title in h2]:
        error('structure-order', 'Present template sections must retain template order')
    if not re.sub(r'^#+ .*$', '', clean, flags=re.M).strip():
        error('structure-body', 'Document body cannot contain only headings or comments')
    # Locate real section boundaries, then count code as section content.
    lines = document.body.splitlines()
    for heading in headings:
        positions = [(n, level, title) for n, level, title in rows if level == 2 and title == heading]
        populated = False
        for number, _, _ in positions:
            end = next((n for n, level, _ in rows if n > number and level <= 2), len(lines))
            section = re.sub(r'<!--.*?-->', '', '\n'.join(lines[number+1:end]), flags=re.S)
            if re.sub(r'^\s*#+ .*$', '', section, flags=re.M).strip():
                populated = True
        if not populated:
            error('structure-section', f'Missing populated section: {heading}')
    marker = r'\{\{(?:title|date(?::[^}]+)?|time(?::[^}]+)?)\}\}|<(?:project-id|stable-task-name)>'
    if kind != 'document' and (re.search(marker, clean) or re.search(marker, json.dumps(meta, default=str))):
        error('structure-placeholder', 'Fill template variables and identifiers')
    guidance = {s for p in TEMPLATES.glob('*.md') for s in re.findall(r'<!--.*?-->', p.read_text(), re.S)}
    if any(s in text for s in guidance):
        error('structure-guidance', 'Replace template authoring comments with actual content')
    return errors


def check_file(root, path):
    name = path.relative_to(root).as_posix()
    if role(name) is None:
        return [{'path': name, 'code': 'structure-scope', 'message': 'No role template applies to this path'}]
    try:
        return validate(parse(name, path.read_bytes()))
    except (ValueError, TypeError, UnicodeError, yaml.YAMLError) as exc:
        return [{'path': name, 'code': 'structure-metadata', 'message': str(exc)}]


def check_structure(root):
    return [issue for p in paths(root) if role(p.relative_to(root).as_posix())
            for issue in check_file(root, p)]


def enabled(root):
    registry = root / '.local/harness/projects.json'
    if not registry.exists():
        return False
    data = json.loads(registry.read_text())
    if not isinstance(data, dict):
        raise ValueError('Project registry must be an object')
    version = data.get('document_contract')
    if version is None:
        return False
    if type(version) is not int or version != 1:
        raise ValueError('Unsupported document_contract version')
    return True
