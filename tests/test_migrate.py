import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from harness.migrate import apply, finish, rewrite_links


class MigrationTests(unittest.TestCase):
    def test_table_wikilink_with_escaped_separator_moves(self):
        root = Path('/vault')
        result = rewrite_links(r'[[notes/old/README\|label]]', 'notes/index.md', 'notes/index.md',
                               {'notes/old/README.md': 'log/old/README.md'}, root)
        self.assertEqual(result, r'[[log/old/README\|label]]')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.entries = []
        for source, target, body in [("wiki/a.md", "notes/a.md", "# A\n[B](b.md)"),
                                     ("wiki/b.md", "notes/b.md", "# B\nCurrent")]:
            p = self.root / source
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body)
            self.entries.append({"source": source, "target": target, "sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "rewrite": True})
        self.plan = self.root / "plan.json"
        self.plan.write_text(json.dumps({"files": self.entries}))
        self.record = self.root / "log/run"

    def test_full_bytes_preserved_and_no_old_owner_remains(self):
        apply(self.root, self.plan, self.record)
        self.assertFalse((self.root / "wiki/a.md").exists())
        self.assertEqual((self.record / "before/wiki/a.md").read_text(), "# A\n[B](b.md)")
        self.assertEqual((self.root / "notes/a.md").read_text(), "# A\n[B](b.md)")

    def test_stale_source_rejected_before_live_changes(self):
        (self.root / "wiki/a.md").write_text("another writer")
        with self.assertRaisesRegex(ValueError, "Stale"):
            apply(self.root, self.plan, self.record)
        self.assertFalse((self.root / "notes").exists())

    def test_interrupted_publication_resumes_without_losing_original(self):
        import os
        original = os.replace
        calls = []
        def interrupt(source, target):
            calls.append(target)
            if len(calls) == 2:
                raise OSError("simulated interruption")
            return original(source, target)
        with patch("harness.migrate.os.replace", side_effect=interrupt):
            with self.assertRaises(OSError):
                apply(self.root, self.plan, self.record)
        self.assertTrue((self.root / "wiki/a.md").exists())
        finish(self.root, self.record)
        self.assertTrue((self.root / "notes/b.md").exists())
        self.assertFalse((self.root / "wiki/a.md").exists())
        finish(self.root, self.record)

    def test_relocates_relative_absolute_and_wikilinks(self):
        mapping = {"wiki/a.md": "notes/deep/a.md", "wiki/b.md": "profile.md"}
        text = "[B](b.md#x) [[wiki/b|label]] [B](" + str(self.root / "wiki/b.md") + ")"
        result = rewrite_links(text, "wiki/a.md", "notes/deep/a.md", mapping, self.root)
        self.assertIn("[B](../../profile.md#x)", result)
        self.assertIn("[[profile|label]]", result)
        self.assertIn(str(self.root / "profile.md"), result)


if __name__ == "__main__":
    unittest.main()
