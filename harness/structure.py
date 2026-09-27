"""Authoring contracts read from templates; adoption is an explicit corpus gate."""
import json
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


def prose(body):
    """Hide fenced examples while retaining inline text used in real headings."""
    return re.sub(r'(?ms)^(`{3,}|~{3,})[^\n]*\n.*?^\1[ \t]*$', '', body)


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
    if meta.get('type') != expected['type']:
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
    if not re.search(r'^# \S', clean, re.M):
        error('structure-title', 'A document H1 is required')
    if not re.sub(r'^#+ .*$', '', clean, flags=re.M).strip():
        error('structure-body', 'Document body cannot contain only headings or comments')
    # Code is real content within a section, but a heading inside code is not a section.
    outside_headings = {m[1] for m in re.finditer(r'^## (.+)$', clean, re.M)}
    body_without_comments = re.sub(r'<!--.*?-->', '', document.body, flags=re.S)
    for heading in headings:
        match = re.search(r'^## '+re.escape(heading)+r'[ \t]*\n(.*?)(?=^## |\Z)',
                          body_without_comments, re.M | re.S)
        if heading not in outside_headings or not match or not re.sub(r'^#+ .*$', '', match[1], flags=re.M).strip():
            error('structure-section', f'Missing populated section: {heading}')
    marker = r'\{\{(?:title|date(?::[^}]+)?|time(?::[^}]+)?)\}\}|<(?:project-id|stable-task-name)>'
    if re.search(marker, clean) or re.search(marker, json.dumps(meta, default=str)):
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
