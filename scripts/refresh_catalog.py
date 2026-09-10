#!/usr/bin/env python3
"""Inventory explicitly selected Markdown roots; never copy their bodies."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from urllib.parse import quote

EXCLUDED_DIRS = {
    "node_modules", "vendor", "dist", "build", "output", "tmp", "temp",
    "coverage", "graphify-out", "__pycache__", "target", "logs", "dumps",
}
SENSITIVE_NAMES = re.compile(r"secret|credential|password|private.?key|token.?dump|chat.?log|transcript", re.I)


def scan(root, output):
    records, skipped = [], Counter()
    for directory, children, filenames in os.walk(root, followlinks=False):
        retained = []
        for name in sorted(children):
            child = Path(directory) / name
            if name.startswith('.') or name in EXCLUDED_DIRS or child.is_symlink() or child.resolve() in {output, output.parent}:
                skipped['excluded_directory'] += 1
            else:
                retained.append(name)
        children[:] = retained
        for name in sorted(filenames):
            path = Path(directory) / name
            if path.suffix.lower() not in {'.md', '.mdx'}:
                continue
            if name.startswith('.') or SENSITIVE_NAMES.search(name) or path.is_symlink():
                skipped['excluded_filename'] += 1
                continue
            try:
                if path.stat().st_size > 2_000_000:
                    skipped['oversized'] += 1
                    continue
                raw = path.read_bytes()
                body = raw.decode('utf-8')
                relative = path.relative_to(root).as_posix()
                heading = re.search(r'^#\s+(.+)$', body, re.M)
                title = heading.group(1).strip() if heading else path.stem
                records.append({
                    'path': relative, 'title': title[:200], 'bytes': len(raw),
                    'sha256': hashlib.sha256(raw).hexdigest(),
                    'modified_at': datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
                    'review': 'indexed-only',
                })
            except (OSError, UnicodeError):
                skipped['unreadable'] += 1
    return records, dict(skipped)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', action='append', required=True, help='NAME=/absolute/root')
    parser.add_argument('--output', type=Path, required=True, help='Local ignored Catalog directory')
    args = parser.parse_args()
    output = args.output.resolve()
    sources = {}
    for value in args.source:
        name, path = value.split('=', 1)
        if not re.fullmatch(r'[a-z0-9-]+', name) or name in sources:
            parser.error('Source names must be unique lowercase slugs')
        root = Path(path).resolve()
        if not root.is_dir() or root == output:
            parser.error(f'Invalid source root: {name}')
        sources[name] = root
    output.mkdir(parents=True, exist_ok=True)
    summary = {'generated_at': datetime.now(timezone.utc).isoformat(), 'sources': {}}
    home = ['# PC 문서 카탈로그', '', '문서 제목·출처·수정 시점·hash의 목록이다. 본문을 복제하지 않으며 내용 검증을 의미하지 않는다.', '', '| 자료군 | 문서 수 | 목록 |', '| --- | ---: | --- |']
    for name, root in sources.items():
        records, skipped = scan(root, output)
        groups = Counter(row['path'].split('/')[0] for row in records if '/' in row['path'])
        summary['sources'][name] = {'root': str(root), 'count': len(records), 'skipped': skipped, 'groups': dict(groups)}
        payload = {'source': name, 'root': str(root), 'records': records, 'skipped': skipped}
        (output / f'{name}.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
        lines = [f'# {name}', '', f'원본: `{root}`', '', 'Status: indexed-only. 현재성·사실성·실행 결과는 원본 확인이 필요하다.', '']
        for row in records:
            label = row['title'].replace('[', '(').replace(']', ')').replace('\n', ' ')
            href = quote(str(root / row['path']), safe='/')
            lines.append(f"- [{label}]({href}) — `{row['path']}`")
        (output / f'{name}.md').write_text('\n'.join(lines) + '\n')
        home.append(f'| {name} | {len(records)} | [[{name}]] |')
    home += ['', '숨김 폴더·의존성·빌드 결과·원시 로그 경로·비밀을 나타내는 파일명·2MB 초과 문서는 제외했다. 제목 기반 파일 제외는 완전한 비밀 탐지기가 아니다. 카탈로그는 로컬에만 보관한다.', '', '이 목록에 없는 PC 경로·이미지·PDF·코드 본문·DB·브라우저 데이터는 수집하지 않았다.']
    (output / 'README.md').write_text('\n'.join(home) + '\n')
    (output / 'manifest.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({name: row['count'] for name, row in summary['sources'].items()}, ensure_ascii=False))


if __name__ == '__main__':
    main()
