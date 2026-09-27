from pathlib import Path
import tempfile
import unittest

from harness.inventory import inventory


class InventoryTests(unittest.TestCase):
    def test_scopes_and_source_bytes_remain_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bodies = {
                "wiki/sources/basic-memory/feedback/style.md": "# Preference\n",
                "wiki/sources/book/chapter.md": "# Source\n## History\n",
                "Operations/p/tasks/work.md": "---\nid: task-1\n---\n# Work\n## 작업 로그\n",
                "Operations/p/log/run/before.md": "# Before\n",
                "wiki/sources/reference/index.md": "# Source\n",
                "notes/current.md": "# Current\n",
                "sources/original.md": "# Original\n",
                "log/change.md": "# Change\n",
            }
            for name, body in bodies.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(body)
            result = inventory(root)
            entries = {e["path"]: e for e in result["files"]}
            self.assertEqual(entries["wiki/sources/book/chapter.md"]["category"], "source")
            self.assertEqual(entries["notes/current.md"]["category"], "current")
            self.assertEqual(entries["sources/original.md"]["category"], "source")
            self.assertEqual(entries["log/change.md"]["category"], "history")
            self.assertEqual(entries["wiki/sources/reference/index.md"]["category"], "source")
            self.assertEqual(entries["Operations/p/tasks/work.md"]["metadata"]["id"], "task-1")
            self.assertEqual(entries["Operations/p/tasks/work.md"]["history_heading_candidates"], ["## 작업 로그"])
            for name, body in bodies.items():
                self.assertEqual((root / name).read_text(), body)


if __name__ == "__main__":
    unittest.main()
