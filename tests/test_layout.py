from pathlib import Path
import tempfile
import unittest

from harness.layout import issues, walk
from harness.documents import paths


class LayoutTests(unittest.TestCase):
    def test_hidden_files_empty_directories_and_local_reports_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / '.forgotten').mkdir()
            (root / '.local/harness').mkdir(parents=True)
            (root / '.local/harness/report.json').write_text('{}')
            (root / 'wiki/.obsidian').mkdir(parents=True)
            self.assertEqual({e['path'] for e in issues(root)},
                             {'.forgotten', '.local/harness/report.json', 'wiki/.obsidian'})

    def test_exclusion_is_exact_and_inventory_does_not_follow_symlinks(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'Operations/thready').mkdir(parents=True)
            (root / 'Operations/thready/.original').write_bytes(b'original')
            (root / 'Operations/other').mkdir()
            (root / 'wiki').mkdir()
            (root / 'wiki/loop').symlink_to(root, target_is_directory=True)
            self.assertEqual({e['path'] for e in issues(root)}, {'Operations', 'wiki/loop'})
            entries = {p.relative_to(root).as_posix(): k for p, k in walk(root)}
            self.assertEqual(entries['wiki/loop'], 'symlink')
            self.assertIn('Operations/thready/.original', entries)

    def test_sources_are_not_current_search_or_validation_owners(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for name in ['wiki/sources/reference/old.md', 'wiki/projects/p/index.md']:
                p = root / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text('# Owner')
            self.assertEqual([p.relative_to(root).as_posix() for p in paths(root)],
                             ['wiki/projects/p/index.md'])

    def test_managed_entrypoints_and_directory_casing_are_enforced(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            folder = root / 'wiki/notes/Topic'
            folder.mkdir(parents=True)
            (folder / 'README.md').write_text('# Duplicate')
            (folder / '_map.md').write_text('# Duplicate')
            self.assertEqual({e['path'] for e in issues(root)}, {
                'wiki/notes/Topic', 'wiki/notes/Topic/README.md', 'wiki/notes/Topic/_map.md'})
            (folder / 'README.md').rename(folder / 'index.md')
            (folder / '_map.md').unlink()
            folder.rename(folder.with_name('topic'))
            self.assertEqual(issues(root), [])
