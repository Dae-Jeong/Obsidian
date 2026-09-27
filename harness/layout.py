"""Complete structural audit, including hidden files and empty directories."""
import os
import re
from pathlib import Path

ROOT_NAMES = {'AGENTS.md', 'README.md', 'wiki', 'docs', 'harness', 'tests',
              'Makefile', 'pyproject.toml', 'uv.lock', '.git', '.gitignore',
              '.gitmodules', '.githooks', '.obsidian', '.local', '.venv',
              'orchestration'}
WIKI_NAMES = {'index.md', 'profile.md', 'notes', 'projects', 'sources', 'log'}
LOCAL_FILES = {'harness/projects.json', 'harness/checkpoint.json',
               'harness/hook-state.sqlite', 'harness/hook-state.sqlite-journal',
               'harness/current.sqlite', 'harness/sources.sqlite', 'harness/history.sqlite'}
EXCLUSIONS = ()
BOUNDARIES = {'.git', '.venv', 'orchestration'}


def excluded(name):
    return any(name == p or name.startswith(p + '/') for p in EXCLUSIONS)


def walk(root):
    """Never follow directory symlinks; expose each runtime boundary explicitly."""
    def visit(folder):
        for p in sorted(folder.iterdir()):
            name = p.relative_to(root).as_posix()
            if p.is_symlink():
                yield p, 'symlink'
            elif name in BOUNDARIES:
                yield p, 'runtime-boundary'
            elif p.is_dir():
                yield p, 'directory'
                yield from visit(p)
            else:
                yield p, 'file'
    yield from visit(root)


def issues(root):
    errors = []
    def error(p, message):
        errors.append({'path': p.relative_to(root).as_posix(), 'code': 'layout', 'message': message})
    for p in root.iterdir():
        if p.name not in ROOT_NAMES:
            error(p, 'Unassigned root entry; assign an owner before adding files')
    if (root / 'wiki').is_dir():
        for p in (root / 'wiki').iterdir():
            if p.name not in WIKI_NAMES:
                error(p, 'Unassigned Wiki entry')
    for area in ('wiki/notes', 'wiki/projects'):
        folder = root / area
        if not folder.exists():
            continue
        for p, kind in walk(folder):
            if kind == 'directory' and not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', p.name):
                error(p, 'Managed document directories require lowercase kebab-case')
            if kind == 'file' and p.name in {'README.md', '_map.md'}:
                error(p, 'Managed document entrypoints must use index.md')
    if (root / '.local').is_dir():
        for p, kind in walk(root / '.local'):
            name = p.relative_to(root / '.local').as_posix()
            if kind == 'directory' and name == 'harness':
                continue
            if kind != 'file' or name not in LOCAL_FILES:
                error(p, '.local permits only registered machine state and search databases')
    return errors
