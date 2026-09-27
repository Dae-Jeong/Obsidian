import json
import os
from unittest.mock import patch
from pathlib import Path
import subprocess
import tempfile
import unittest

from harness.context import context, git_common, git_environment


class ContextTests(unittest.TestCase):
    def test_two_repositories_and_worktree_resolve_independently(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = base / 'vault'
            (root / '.local/harness').mkdir(parents=True)
            entries = []
            for name in ('alpha', 'beta'):
                repo = base / name
                repo.mkdir()
                def git(*args):
                    return subprocess.run(['git', '-C', str(repo), *args], check=True,
                                          capture_output=True, text=True, env=git_environment())
                git('init', '-q')
                expected = git_common(repo)
                with patch.dict(os.environ, {'GIT_DIR': str(base / 'wrong-repository'),
                                             'GIT_INDEX_FILE': str(base / 'foreign-index')}):
                    self.assertEqual(git_common(repo), expected)
                git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                    'commit', '--allow-empty', '-qm', 'fixture')
                docs = root / 'wiki/projects' / name / 'tasks'
                docs.mkdir(parents=True)
                (docs.parent / 'index.md').write_text(f'# {name}')
                (docs / 'work.md').write_text(f'---\nid: {name}.work\nstatus: active\n---\n# Scope\nOnly {name}')
                entries.append({'id': name, 'root': str(repo), 'git_common_dir': git_common(repo),
                                'documents': f'wiki/projects/{name}'})
                if name == 'alpha':
                    worktree = base / 'alpha-attempt'
                    git('worktree', 'add', '--detach', str(worktree))
            (root / '.local/harness/projects.json').write_text(json.dumps({'projects': entries}))
            self.assertEqual(context(root, base / 'alpha')['project_id'], 'alpha')
            self.assertEqual(context(root, base / 'beta')['project_id'], 'beta')
            selected = context(root, worktree, 'alpha.work')
            self.assertIn('Only alpha', selected['tasks'][0]['content'])
            with self.assertRaises(ValueError):
                context(root, base / 'beta', 'alpha.work')
            with self.assertRaises(ValueError):
                context(root, base)
