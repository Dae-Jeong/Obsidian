from pathlib import Path
import tempfile
import unittest

from harness.retrieval import read


class ReadTests(unittest.TestCase):
    def test_selected_parent_includes_children_and_boundaries_with_stable_paging(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / 'wiki/notes/guide.md'
            path.parent.mkdir(parents=True)
            path.write_text('---\nverification: partial\nretrieval:\n  description: Retry design\n  use_when: Review only\n  role: guidance\n  aliases: [retry]\n  sections: [Design]\n---\n# Guide\n## Design\nChoice\n### Detail\n' + 'details ' * 150 + '\n## Applicability\nNot production proof\n## Evidence\nOriginal source\n## Other\nUNSELECTED')
            first = read(root, 'wiki/notes/guide.md', limit=500)
            self.assertTrue(first['truncated'])
            self.assertEqual(first['verification'], 'retrieval-only')
            self.assertEqual(first['declared_verification'], 'partial')
            self.assertIn('### Detail', first['content'])
            self.assertEqual(first['sections'], ['Design', 'Applicability', 'Evidence'])
            content = first['content']
            page = first
            while page['next_offset'] is not None:
                page = read(root, 'wiki/notes/guide.md', limit=500, offset=page['next_offset'], expected_hash=first['sha256'])
                content += page['content']
            self.assertIn('Not production proof', content)
            self.assertIn('Original source', content)
            self.assertNotIn('UNSELECTED', content)
            with self.assertRaisesRegex(ValueError, 'section'):
                read(root, 'wiki/notes/guide.md', selected=['Missing'])
            path.write_text(path.read_text() + '\nChanged')
            with self.assertRaisesRegex(ValueError, 'changed'):
                read(root, 'wiki/notes/guide.md', expected_hash=first['sha256'])

    def test_scope_symlinks_and_task_handoff_are_not_silently_truncated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            notes = root / 'wiki/notes'
            notes.mkdir(parents=True)
            (root / 'secret.md').write_text('outside current scope')
            (notes / 'link.md').symlink_to(root / 'secret.md')
            for path in ('secret.md', '../outside.md', 'wiki/notes/link.md'):
                with self.assertRaises(ValueError):
                    read(root, path)
            owner = notes / 'plain.md'
            owner.write_text('# Plain\nRead explicitly')
            with self.assertRaisesRegex(ValueError, 'Choose sections'):
                read(root, 'wiki/notes/plain.md')
            self.assertIn('Read explicitly', read(root, 'wiki/notes/plain.md', selected=['Plain'])['content'])
            task = root / 'wiki/projects/test/tasks/work.md'
            task.parent.mkdir(parents=True)
            task.write_text('# Scope\nFull authorization')
            with self.assertRaisesRegex(ValueError, 'full Task'):
                read(root, task.relative_to(root).as_posix(), selected=['Scope'])
