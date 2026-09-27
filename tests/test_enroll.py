import hashlib
from pathlib import Path
import tempfile
import unittest

from harness.enroll import enroll


class EnrollmentTests(unittest.TestCase):
    def test_task_becomes_one_owner_and_relative_evidence_keeps_its_target(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            repo = base / "product"
            vault = base / "vault"
            vault.mkdir()
            source = repo / "tasks/work.md"
            source.parent.mkdir(parents=True)
            evidence = repo / "result.txt"
            evidence.write_text("actual output")
            source.write_text("# Work\n[Evidence](../result.txt)")
            raw = source.read_bytes()
            plan = {"files": [{"source": str(source), "target": "projects/p/tasks/work.md", "sha256": hashlib.sha256(raw).hexdigest()}]}
            record = vault / "log/enroll"
            self.assertEqual(enroll(vault, plan, record), 1)
            self.assertEqual(source.resolve(), vault / "projects/p/tasks/work.md")
            self.assertIn("../../../../product/result.txt", source.read_text())
            self.assertEqual((record / "before/projects/p/tasks/work.md").read_bytes(), raw)
            with self.assertRaises(ValueError):
                enroll(vault, plan, vault / "log/again")


if __name__ == "__main__":
    unittest.main()
