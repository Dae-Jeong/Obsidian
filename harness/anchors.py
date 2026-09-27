"""Check local Markdown/Obsidian fragments against actual headings or IDs."""
import re
from urllib.parse import unquote, urlsplit

from harness.documents import parse
from harness.structure import prose


def anchors(raw, html=False):
    text = raw.decode('utf-8')
    if not html:
        text = prose(parse('target', raw).body)
    result = set(re.findall(r'\b(?:id|name)=[\"\']([^\"\']+)[\"\']', text))
    if html:
        return result
    result.update('^'+x for x in re.findall(r'(?:^|\s)\^([\w-]+)\s*$', text, re.M))
    counts = {}
    for heading in re.findall(r'^#{1,6}[ \t]+(.+?)[ \t]*#*[ \t]*$', text, re.M):
        heading = re.sub(r'!?\[([^\]]+)\]\([^)]*\)', r'\1', heading)
        heading = re.sub(r'<[^>]*>', '', heading).strip()
        heading = re.sub(r'[`*_~]', '', heading)
        result.add(heading.casefold())
        slug = ''.join(c for c in heading.lower() if c.isalnum() or c in ' _-').replace(' ', '-')
        occurrence = counts.get(slug, 0)
        counts[slug] = occurrence+1
        result.add(slug + (f'-{occurrence}' if occurrence else ''))
    return result


def fragment_issue(root, document, value, wiki, resolve):
    if '#' not in value or urlsplit(value).scheme:
        return None
    fragment = unquote(value.split('#', 1)[1]).rstrip('\\')
    if not fragment:
        return None
    target = document if value.startswith('#') else resolve(root, document, value, wiki)
    if target is None or not target.is_file() or target.suffix.lower() not in {'.md', '.html', '.htm'}:
        return None
    values = anchors(target.read_bytes(), target.suffix.lower() != '.md')
    if fragment in values or (wiki and fragment.casefold() in values):
        return None
    return {'path': document.relative_to(root).as_posix(), 'code': 'missing-anchor', 'message': value}
