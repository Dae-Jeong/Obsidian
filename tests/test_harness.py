from pathlib import Path
import tempfile
import unittest

from harness.check import check
from harness.checkpoint import checkpoint
from harness.documents import parse
from harness.search import search


class HarnessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / ".local/harness/current.sqlite"
        checkpoint(self.root, initialize=True)

    def write(self, path, body):
        p = self.root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
        return p

    def test_duplicate_frontmatter_is_not_silently_accepted(self):
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            parse("x.md", b"---\nid: a\nid: b\n---\n# X")

    def test_process_sections_are_rejected_only_in_current_scope(self):
        self.write('wiki/notes/topic.md', '# Topic\nCurrent\n## 이전 본문 보존\nObsolete')
        self.write('wiki/log/topic.md', '# Topic\n## 변경 이력\nHistorical evidence')
        result = check(self.root)
        self.assertEqual([e['code'] for e in result['issues']], ['history-in-current'])

    def test_history_and_sources_do_not_leak_into_current(self):
        self.write("wiki/notes/topic.md", "# 공유 지식\n중앙 검색 설명")
        self.write("wiki/sources/private.md", "# 공유 원문\n비공개 인용")
        self.write("wiki/log/before.md", "# 공유 과거\n폐기된 판단")
        result = search(self.root, self.db, "공유")
        self.assertEqual([h["path"] for h in result["hits"]], ["wiki/notes/topic.md"])
        history = search(self.root, self.db, "공유", scope="history")
        self.assertEqual([h["path"] for h in history["hits"]], ["wiki/log/before.md"])

    def test_added_deleted_and_changed_documents_refresh_index(self):
        first = self.write("wiki/notes/first.md", "# 문서\n찾기")
        initial = search(self.root, self.db, "찾기")
        self.assertTrue(initial["rebuilt"])
        self.assertFalse(search(self.root, self.db, "찾기")["rebuilt"])
        self.write("wiki/notes/new.md", "# 신규\n찾기")
        first.unlink()
        refreshed = search(self.root, self.db, "찾기")
        self.assertNotEqual(initial["revision"], refreshed["revision"])
        self.assertEqual([h["path"] for h in refreshed["hits"]], ["wiki/notes/new.md"])
        self.write("wiki/notes/new.md", "# 신규\n내용교체")
        self.assertEqual(search(self.root, self.db, "찾기")["hits"], [])

    def test_empty_queries_and_invalid_limits_are_rejected(self):
        for query, limit in [("", 5), (" ", 5), ("term", 0), ("term", 100)]:
            with self.assertRaises(ValueError):
                search(self.root, self.db, query, limit=limit)

    def test_raw_evidence_remains_searchable_with_invalid_frontmatter(self):
        self.write("wiki/sources/original.md", "---\nid: [invalid\n---\n원본 근거")
        result = search(self.root, self.db, "원본", scope="sources")
        self.assertEqual(result["hits"][0]["path"], "wiki/sources/original.md")
        self.write("wiki/notes/invalid.md", "---\nid: [invalid\n---\n원본 근거")
        self.assertFalse(check(self.root)["ok"])

    def test_retrieval_returns_distinct_owners(self):
        self.write("wiki/notes/a.md", "# Query\nquery\n## Other query\nquery\n")
        self.write("wiki/notes/b.md", "# Query\nquery")
        result = search(self.root, self.db, "query", limit=2)
        self.assertEqual(len({hit["path"] for hit in result["hits"]}), 2)

    def test_false_handoff_evidence_and_empty_sections_fail(self):
        self.write("wiki/projects/p/tasks/task.md", "---\nkind: task\nid: p.task\nproject_id: other\nstatus: done\nchecked: yesterday\nevidence: [missing.txt]\n---\n# Task\n## Goal\n\n## Scope\n")
        codes = {e["code"] for e in check(self.root)["issues"]}
        self.assertTrue({"task-project", "task-date", "task-evidence", "task-section"} <= codes)

    def test_missing_links_and_duplicate_ids_fail(self):
        self.write("wiki/notes/a.md", "---\nid: same\n---\n# A\n[missing](missing.md)")
        self.write("wiki/notes/b.md", "---\nid: same\n---\n# B")
        result = check(self.root)
        self.assertFalse(result["ok"])
        self.assertEqual({e["code"] for e in result["issues"]}, {"duplicate-id", "missing-link"})

    def test_unproven_done_and_incomplete_blocker_fail(self):
        for status in ("done", "blocked"):
            self.write(f"wiki/projects/p/tasks/{status}.md", f"---\nkind: task\nid: {status}\nstatus: {status}\n---\n# Task")
        codes = {e["code"] for e in check(self.root)["issues"]}
        self.assertTrue({"task-field", "task-evidence", "task-blocker"} <= codes)

    def test_dependency_cycle_is_rejected(self):
        for identity, dependency in [("a", "b"), ("b", "a")]:
            self.write(f"wiki/projects/p/tasks/{identity}.md", f"---\nkind: task\nid: {identity}\ndepends_on: [{dependency}]\n---\n# Task")
        self.assertIn("dependency-cycle", {e["code"] for e in check(self.root)["issues"]})

    def test_thirty_korean_english_queries_retrieve_expected_owner(self):
        labels = [f"query{i:02d}" for i in range(10)] + [f"주제{i:02d}" for i in range(10)] + [f"혼합API{i:02d}" for i in range(10)]
        for i, label in enumerate(labels):
            self.write(f"wiki/notes/topic-{i}.md", f"# {label}\n검증 대상 {label}\n" + "supporting context\n" * 100)
        for i, label in enumerate(labels):
            hits = search(self.root, self.db, label)["hits"]
            self.assertEqual(hits[0]["path"], f"wiki/notes/topic-{i}.md")
            self.assertTrue(hits[0]["truncated"])
            self.assertLessEqual(len(hits[0]["excerpt"]), 900)
        # One-character Korean substring fallback also works.
        self.assertTrue(search(self.root, self.db, "주")["hits"])


if __name__ == "__main__":
    unittest.main()
