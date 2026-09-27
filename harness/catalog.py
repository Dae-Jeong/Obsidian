"""Derived document register. Declared dates never certify factual freshness."""
from collections import Counter
from datetime import date, datetime, timezone
import hashlib
import html
import json
import os
from pathlib import Path
import re
from urllib.parse import quote

import yaml

from harness.documents import parse
from harness.layout import walk, excluded

DOMAIN = 'wiki/sources/Dae-Jeong/wiki/'
TEXT_TYPES = {'.md', '.markdown', '.yaml', '.yml', '.json', '.html', '.txt', '.csv'}
MANAGED = {'current', 'current-companion', 'domain-owner-candidate'}
DATE_FIELDS = {
    'updated': 'content', 'last_updated': 'content', 'modified': 'content',
    'updated_at': 'content', 'revised_at': 'content', 'modified_at': 'content',
    'checked': 'review', 'last_verified': 'review', 'verified_at': 'review',
    'reviewed_at': 'review',
    'source_checked': 'source-review', 'surveyed': 'source-review',
    'fetched_at': 'capture', 'timestamp': 'unspecified', 'date': 'unspecified',
    'captured_at': 'capture', 'retrieved_at': 'capture',
    'stale_after': 'review-due',
}
LABELS = {'current': '현재 문서', 'current-companion': '현재 부속 자료',
          'domain-owner-candidate': '도메인 정본 후보', 'domain-archive': '도메인 보존 자료',
          'source': '원본·첨부', 'history': 'Log', 'excluded': '관리 제외'}
FLAGS = {'content-date-unknown': '내용 수정일 미기록', 'review-date-unknown': '검토일 미기록',
         'review-due': '명시된 재검토일 도래', 'future-date': '미래 날짜 확인',
         'invalid-date': '날짜 형식 확인', 'metadata-parse-error': 'metadata 해석 실패',
         'renamed-metadata-key': '경로로 변한 metadata 키',
         'structured-data-in-markdown': 'Markdown 내부 구조화 데이터',
         'embedded-file-missing': '구조화 데이터의 파일 연결 누락',
         'role-inferred': '역할 확인 필요', 'domain-boundary-review': '활성·보존 경계 확인',
         'hidden-file': '숨김 자료', 'broken-link': '끊어진 symlink',
         'no-content-certification': '목록화·내용 최신성 미검증'}


class CatalogLoader(yaml.SafeLoader):
    """Domain YAML may legitimately use numeric keys below its metadata."""


def unique_mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ValueError('Duplicate YAML key')
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


CatalogLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def iso_day(value):
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    match = re.match(r'^\s*(\d{4}-\d{2}-\d{2})(?:T|\s|$)', str(value))
    if not match:
        return None
    try:
        return date.fromisoformat(match[1]).isoformat()
    except ValueError:
        return None


def dates(metadata, body):
    records = []
    for key, category in DATE_FIELDS.items():
        if metadata.get(key) is not None:
            records.append({'kind': category, 'date': iso_day(metadata[key]), 'field': key,
                            'raw': str(metadata[key])[:120], 'origin': 'metadata'})
    for key, kind in [('generated', 'generation'), ('verified', 'review')]:
        values = metadata.get(key, [])
        if isinstance(values, dict):
            values = [values]
        if isinstance(values, list):
            for v in values:
                if isinstance(v, dict) and v.get('at'):
                    records.append({'kind': kind, 'date': iso_day(v['at']), 'field': key + '.at',
                                    'raw': str(v['at'])[:120], 'origin': 'metadata'})
    # Only explicit date labels outside code blocks. Incidental dates in claims,
    # URLs, filenames and prose are not document review timestamps.
    fenced = False
    labels = r'(Checked|Verified|검토|확인|확인일|검증일|검토일|검토 기준|탐색 확인|출처 확인|조회일|수집일|수정일|갱신일|Updated)'
    for number, line in enumerate(body.splitlines(), 1):
        if line.lstrip().startswith(('```', '~~~')):
            fenced = not fenced
        if fenced:
            continue
        clean = re.sub(r'^[\s>\-*]+', '', line).replace('**', '')
        m = re.match(labels + r'\s*(?:[:：—–-]\s*|\(\s*)(\d{4}-\d{2}-\d{2})(?=\D|$)', clean, re.I)
        if m:
            label = m[1].lower()
            kind = 'content' if label in {'수정일', '갱신일', 'updated'} else ('capture' if label in {'조회일', '수집일'} else 'review')
            records.append({'kind': kind, 'date': iso_day(m[2]), 'field': m[1],
                            'raw': m[2], 'origin': 'body', 'body_line': number})
    return records


def scope_for(name, metadata):
    if excluded(name):
        return 'excluded'
    if name.startswith('wiki/log/'):
        return 'history'
    if name.startswith(DOMAIN):
        parts = set(Path(name[len(DOMAIN):]).parts)
        state = str(metadata.get('artifact_state', metadata.get('status', '')))
        if parts & {'revisions', 'submissions', 'snapshots', 'original-documents'} or state in {'frozen', 'historical-snapshot'}:
            return 'domain-archive'
        return 'domain-owner-candidate'
    if name.startswith('wiki/sources/'):
        return 'source'
    return 'current' if Path(name).suffix.lower() == '.md' else 'current-companion'


def describe(path, root, today):
    name = path.relative_to(root).as_posix()
    stat = path.stat()
    raw = path.read_bytes()
    text = raw.decode('utf-8', errors='replace') if path.suffix.lower() in TEXT_TYPES else ''
    metadata = {}; body = text; flags = []; structured = None
    try:
        if path.suffix.lower() in {'.md', '.markdown'}:
            doc = parse(name, raw); metadata = doc.metadata; body = doc.body
            if body.lstrip().startswith('{'):
                try:
                    structured = json.loads(body)
                    flags.append('structured-data-in-markdown')
                except ValueError:
                    pass
        elif path.suffix.lower() in {'.json', '.yaml', '.yml'}:
            structured = json.loads(text) if path.suffix.lower() == '.json' else yaml.load(text, Loader=CatalogLoader)
            metadata = structured if isinstance(structured, dict) else {}
    except (ValueError, UnicodeError, TypeError, yaml.YAMLError):
        flags.append('metadata-parse-error')
    scope = scope_for(name, metadata)
    title = metadata.get('title')
    if not isinstance(title, str):
        heading = re.search(r'^#\s+(.+)$', body, re.M)
        web_title = re.search(r'<title[^>]*>(.*?)</title>', text, re.S | re.I)
        title = heading[1] if heading else (html.unescape(web_title[1]) if web_title else path.stem)
    role = metadata.get('kind') or metadata.get('type')
    if not isinstance(role, str):
        role = 'task' if '/tasks/' in name and path.name not in {'README.md','index.md'} and path.suffix == '.md' else ('index' if path.name in {'README.md','index.md','_map.md'} else 'unclassified')
        if role == 'unclassified' and scope in MANAGED:
            flags.append('role-inferred')
        role_origin = 'path-inferred'
    else:
        role_origin = 'metadata'
    observations = dates(metadata, body)
    def latest(kinds):
        return max((d['date'] for d in observations if d['kind'] in kinds and d['date'] and d['date'] <= today), default=None)
    content_date = latest({'content'})
    review_date = latest({'review', 'source-review'})
    if scope in MANAGED:
        if not content_date: flags.append('content-date-unknown')
        if not review_date: flags.append('review-date-unknown')
        if scope == 'domain-owner-candidate': flags.append('domain-boundary-review')
    if any(d['date'] is None for d in observations): flags.append('invalid-date')
    if any(d['date'] and d['date'] > today and d['kind'] != 'review-due' for d in observations): flags.append('future-date')
    if any(d['kind'] == 'review-due' and d['date'] and d['date'] <= today for d in observations): flags.append('review-due')
    if any(str(k).startswith('wiki/') for k in metadata): flags.append('renamed-metadata-key')
    if any(p.startswith('.') for p in Path(name).parts): flags.append('hidden-file')
    missing_files = []
    if isinstance(structured, dict) and isinstance(structured.get('nodes'), list):
        for node in structured['nodes']:
            if isinstance(node, dict) and isinstance(node.get('file'), str):
                target = root / node['file']
                if not target.exists(): missing_files.append(node['file'])
        if missing_files: flags.append('embedded-file-missing')
    verification = metadata.get('verification', metadata.get('current_verification', ''))
    return {'path': name, 'title': str(title)[:300], 'scope': scope, 'role': role,
            'role_origin': role_origin, 'area': '/'.join(Path(name).parts[:3]),
            'status': str(metadata.get('status', '')), 'content_updated_declared': content_date,
            'review_recorded': review_date, 'source_review_declared': latest({'source-review'}),
            'captured_declared': latest({'capture'}), 'generation_declared': latest({'generation'}),
            'unspecified_date': latest({'unspecified'}), 'date_evidence': observations,
            'file_mtime_utc': datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            'verification_declared': str(verification)[:400], 'flags': sorted(set(flags)),
            'missing_embedded_files': missing_files, 'bytes': len(raw),
            'sha256': hashlib.sha256(raw).hexdigest(),
            'freshness_certification': 'not-performed'}


def catalog(root):
    rows = []; links = []; now = datetime.now(timezone.utc)
    roots = [root / 'wiki', root / 'Operations', root / 'docs']
    candidates = [root / n for n in ['README.md', 'AGENTS.md'] if (root / n).is_file()]
    for base in roots:
        if not base.exists(): continue
        for p, kind in walk(base):
            if kind == 'file': candidates.append(p)
            elif kind == 'symlink':
                links.append({'path': p.relative_to(root).as_posix(), 'target': os.readlink(p),
                              'exists': p.exists(), 'traversed': False})
    for path in sorted(candidates):
        rows.append(describe(path, root, now.date().isoformat()))
    managed = [r for r in rows if r['scope'] in MANAGED]
    summary = {'all_files': len(rows), 'managed_candidates': len(managed),
               'scopes': dict(Counter(r['scope'] for r in rows)),
               'managed_flags': dict(Counter(f for r in managed for f in r['flags'])),
               'review_recorded': sum(bool(r['review_recorded']) for r in managed),
               'content_date_recorded': sum(bool(r['content_updated_declared']) for r in managed),
               'symlinks_not_traversed': len(links)}
    return {'generated_at': now.isoformat(), 'coverage': 'metadata-and-explicit-date-labels-not-semantic-review',
            'summary': summary, 'documents': rows, 'symlinks': links}


def export(root, output):
    root = root.resolve()
    output = (root / output).resolve()
    output.relative_to((root / 'wiki/log').resolve())
    if output.exists(): raise ValueError('Use a new Log directory; existing evidence is not overwritten')
    data = catalog(root)
    output.mkdir(parents=True)
    (output / 'catalog.json').write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    page = (Path(__file__).parent / 'catalog.html').read_text()
    relative_root = os.path.relpath(root, output)
    display = []
    for row in data['documents']:
        if row['scope'] not in MANAGED: continue
        display.append({**row, 'url': relative_root + '/' + quote(row['path'], safe='/')})
    payload = json.dumps({'generated_at': data['generated_at'], 'summary': data['summary'],
                          'rows': display, 'labels': LABELS, 'flags': FLAGS}, ensure_ascii=False).replace('<', '\\u003c')
    page = page.replace('CATALOG_PAYLOAD', payload)
    (output / 'index.html').write_text(page)
    (output / 'README.md').write_text('# Document register scan\n\n'
        + data['generated_at'] + '\n\n'
        'Generated from local files without modifying their content or dates. '
        'Declared review dates are observations, not current factual certification. '
        'File mtime is filesystem evidence only. Domain owner candidates need classification; '
        'frozen/revision/source/history files are separately counted. Symlinks are not traversed.\n\n'
        '[Searchable managed-document view](index.html) · [Full file register](catalog.json)\n')
    return {'record': output.relative_to(root).as_posix(), **data['summary']}
