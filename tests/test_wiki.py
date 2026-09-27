import importlib.util
from pathlib import Path
import tempfile
import unittest

from harness import preserve as wiki
from harness.documents import paths as documents

class WikiTests(unittest.TestCase):
    def test_snapshot_survives_edit_and_detects_corruption(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = root / "note.md"
            original = b"original\r\n\x00bytes"
            document.write_bytes(original)
            record = wiki.snapshot(root, ["note.md"], "User correction")
            document.write_text("current")
            self.assertEqual(wiki.verify(root, record), 1)
            copy = record / "before/note.md"
            self.assertEqual(copy.read_bytes(), original)
            copy.write_text("corrupted")
            with self.assertRaises(ValueError):
                wiki.verify(root, record)

    def test_scope_excludes_history_and_raw_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current = ["README.md", "wiki/notes/knowledge/note.md",
                       "wiki/notes/feedback/preference.md"]
            history = ["wiki/log/index.md", "wiki/log/agents.md",
                       "wiki/log/run/before/note.md"]
            source = ["wiki/sources/book/note.md"]
            for name in current + history + source:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("test")
            paths = lambda scope: {p.relative_to(root).as_posix() for p in documents(root, scope)}
            self.assertEqual(paths("current"), set(current))
            self.assertEqual(paths("history"), set(history))
            self.assertIn(source[0], paths("sources"))

    def test_rejects_escape_and_missing_files_before_record_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for value in ("../outside.md", "missing.md"):
                with self.assertRaises(ValueError):
                    wiki.snapshot(root, [value], "change")
            self.assertFalse((root / wiki.LOG).exists())


if __name__ == "__main__":
    unittest.main()
