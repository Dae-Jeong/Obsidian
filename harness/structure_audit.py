"""Read-only census of current-owner form; templates remain the contract owner."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import yaml

from harness import domains, structure
from harness.documents import parse, paths
from harness.retrieval import metadata


def headings(body):
    return [(level, title) for _, level, title in structure.heading_rows(body)]


def inspect(path, raw):
    kind = structure.role(path)
    row = {'path': path, 'sha256': hashlib.sha256(raw).hexdigest(),
           'role': kind, 'status': 'not-covered', 'issues': [], 'form_differences': [],
           'retrieval': 'not-applicable'}
    if kind is None:
        row['reason'] = 'No shared role template; entry, docs or product-owned schema'
        return row
    try:
        doc = parse(path, raw)
        row['role'] = kind + ':' + str(doc.metadata.get('subject_type', 'unknown')) if kind == 'note' else kind
        row['issues'] = structure.validate(doc)
        row['retrieval'] = 'absent'
        if 'retrieval' in doc.metadata:
            try:
                metadata(doc)
                row['retrieval'] = 'valid'
            except (ValueError, TypeError) as exc:
                row['retrieval'] = 'invalid'
                row['issues'].append({'path': path, 'code': 'retrieval-metadata', 'message': str(exc)})
        actual = headings(doc.body)
        h2 = [title for level, title in actual if level == 2]
        row['h2'] = h2
        try:
            _, required = structure.contract(kind, doc.metadata.get('subject_type'))
        except (ValueError, TypeError):
            required = []
        row['required_h2'] = required
        form_codes = {'structure-title', 'structure-duplicate-heading', 'structure-order'}
        row['form_differences'] = [i['code'] for i in row['issues'] if i['code'] in form_codes]
        row['status'] = 'fail' if row['issues'] else 'pass'
    except (ValueError, TypeError, UnicodeError, yaml.YAMLError) as exc:
        row['status'] = 'fail'
        row['issues'] = [{'path': path, 'code': 'structure-metadata', 'message': str(exc)}]
    return row


def audit(root):
    owners = sorted(set(paths(root)) | set(domains.paths(root)))
    rows = [inspect(p.relative_to(root).as_posix(), p.read_bytes()) for p in owners]
    selected_domains = {p.relative_to(root).as_posix() for p in domains.paths(root)}
    for row in rows:
        if row['role']:
            row['responsibility'] = 'basic-form' if row['role'] == 'document' else 'role-template'
            row['validator'] = 'harness.structure.validate'
        elif row['path'] in selected_domains:
            row['responsibility'] = 'product-owned'
            row['validator'] = 'Product entry/schema plus harness.check syntax, links and preservation'
            row['reason'] = 'Selected current_domain; product schema is not replaced by a Note template or certified by this audit'
        else:
            row['responsibility'] = 'unassigned'
            row['validator'] = None
    responsibility = dict(Counter(r['responsibility'] for r in rows))
    groups = {}
    for role in sorted({row['role'] or 'not-covered' for row in rows}):
        group = [r for r in rows if (r['role'] or 'not-covered') == role]
        covered = sum(r['status'] != 'not-covered' for r in group)
        passed = sum(r['status'] == 'pass' for r in group)
        groups[role] = {'total': len(group), 'passed': passed,
                        'failed': sum(r['status'] == 'fail' for r in group),
                        'pass_percent': round(100 * passed / covered, 2) if covered else None,
                        'form_difference_files': sum(bool(r['form_differences']) for r in group),
                        'retrieval': dict(Counter(r['retrieval'] for r in group))}
    covered = sum(r['status'] != 'not-covered' for r in rows)
    passed = sum(r['status'] == 'pass' for r in rows)
    return {'generated_at': datetime.now(timezone.utc).isoformat(),
            'verification': 'structure-only',
            'responsibility': responsibility,
            'rules': {'contract': 'harness/structure.py and harness/templates/',
                      'form_differences': 'Enforced H1 count, unique H2 and template order including present conditional sections',
                      'retrieval': 'Optional declaration coverage, absence is not a contract failure',
                      'excluded': 'Log and unselected original sources; no content correctness or freshness scoring'},
            'summary': {'current_owners': len(rows), 'covered': covered,
                        'not_covered': len(rows)-covered, 'passed': passed, 'failed': covered-passed,
                        'pass_percent': round(100 * passed / covered, 2) if covered else None,
                        'form_difference_files': sum(bool(r['form_differences']) for r in rows),
                        'unassigned': responsibility.get('unassigned', 0)},
            'roles': groups,
            'diagnostics': dict(Counter(i['code'] for r in rows for i in r['issues'])),
            'documents': rows}


def markdown(report):
    s = report['summary']
    lines = ['# Document structure measurement', '', f"Measured: {report['generated_at']}", '',
             f"Current owners: {s['current_owners']}; role-covered: {s['covered']}; outside shared form contracts: {s['not_covered']}.",
             f"Contract pass: {s['passed']}; fail: {s['failed']}; pass rate among covered: {s['pass_percent']}%.",
             f"Files violating form rules: {s['form_difference_files']}.", '',
             '| Role | Total | Pass | Fail | Form differences |', '| --- | ---: | ---: | ---: | ---: |']
    for role, counts in report['roles'].items():
        lines.append(f"| {role} | {counts['total']} | {counts['passed']} | {counts['failed']} | {counts['form_difference_files']} |")
    lines += ['', '## Responsibility', '', *[f'- {k}: {v}' for k, v in report['responsibility'].items()], '', '## Interpretation', '', *[f'- {k}: {v}' for k, v in report['rules'].items()],
              '', '## Files requiring inspection', '', '| Path | Contract errors | Form differences |', '| --- | --- | --- |']
    for row in report['documents']:
        if row['issues'] or row['form_differences']:
            lines.append(f"| {row['path']} | {', '.join(i['code'] for i in row['issues'])} | {', '.join(row['form_differences'])} |")
    lines += ['', 'Full per-file inventory, hashes, headings and optional metadata coverage: report.json.', '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--format', choices=('json', 'markdown'), default='json')
    args = parser.parse_args()
    result = audit(args.root.resolve())
    print(markdown(result) if args.format == 'markdown' else json.dumps(result, ensure_ascii=False, indent=2))
    return int(bool(result['summary']['failed'] or result['summary']['unassigned']))


if __name__ == '__main__':
    raise SystemExit(main())
