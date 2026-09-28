import json
import os
from unittest.mock import patch
from pathlib import Path
import subprocess
import tempfile
import unittest

from harness.context import context, git_common, git_environment


class ContextTests(unittest.TestCase):
    def test_topic_candidates_preserve_task_and_exclude_history(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / '.local/harness').mkdir(parents=True)
            project = root / 'wiki/projects/writer'
            (project / 'tasks').mkdir(parents=True)
            (project / 'index.md').write_text('# Writer\n## Knowledge Routes\nUse the writing owner.')
            (project / 'tasks/work.md').write_text('---\nid: writer.work\nstatus: active\n---\n# Scope\nFull authorization and limits')
            (root / '.local/harness/projects.json').write_text(json.dumps({'projects': [
                {'id': 'writer', 'root': str(root), 'documents': 'wiki/projects/writer'}]}))
            notes = root / 'wiki/notes'
            notes.mkdir()
            for number in range(7):
                (notes / f'guide-{number}.md').write_text(f'# Resume portfolio guide\nSelect relevant experience {number}.')
            for scope in ('log', 'sources'):
                folder = root / 'wiki' / scope
                folder.mkdir()
                (folder / 'old.md').write_text('# Resume portfolio guide\nHistorical advice is not current.')
            result = context(root, root, 'writer.work', query='resume portfolio guide')
            self.assertIn('Full authorization', result['tasks'][0]['content'])
            candidates = result['knowledge']['hits']
            self.assertEqual(len(candidates), 5)
            self.assertTrue(all(hit['path'].startswith('wiki/notes/') for hit in candidates))
            self.assertTrue(all('excerpt' not in hit and hit['sha256'] for hit in candidates))
            self.assertIn('writing owner', result['navigation'][0]['content'])
            self.assertEqual(context(root, root)['navigation'], result['navigation'])
            self.assertEqual(result['knowledge']['verification'], 'retrieval-only')
            before = result['knowledge']['revision']
            (notes / 'guide-0.md').write_text('# Resume portfolio guide\nUpdated selection advice.')
            refreshed = context(root, root, query='resume portfolio guide')['knowledge']
            self.assertNotEqual(before, refreshed['revision'])
            self.assertTrue(refreshed['rebuilt'])
            self.assertEqual(context(root, root, query='unrelated topic')['knowledge']['hits'], [])
            with self.assertRaisesRegex(ValueError, 'nonempty'):
                context(root, root, query='   ')
            self.assertNotIn('knowledge', context(root, root))
            (root / 'wiki/index.md').write_text('# Map\n## Knowledge Routes\n' + 'route ' * 500)
            navigation = context(root, root)['navigation']
            self.assertEqual(len(navigation), 2)
            self.assertEqual(len(navigation[0]['content']), 2400)
            self.assertTrue(navigation[0]['truncated'])
            self.assertEqual(navigation[0]['links_relative_to'], 'wiki')

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
