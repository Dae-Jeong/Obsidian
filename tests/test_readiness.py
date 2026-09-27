"""Failure injection for preservation and current-context entry points."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from harness.check import check
from harness.checkpoint import checkpoint
from harness.context import context
from harness.search import build, search


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.folder = self.root / 'wiki/projects/example'
        self.folder.mkdir(parents=True)
        (self.folder / 'index.md').write_text('# Example\ncurrent context')
        checkpoint(self.root, initialize=True)
        self.baseline = self.root / '.local/harness/checkpoint.json'
        (self.baseline.parent / 'projects.json').write_text(json.dumps({'projects': [
            {'id': 'example', 'root': str(self.root), 'documents': 'wiki/projects/example'}
        ]}))
        self.db = self.baseline.parent / 'current.sqlite'

    def journal(self, raw):
        path = self.root / 'wiki/log/run/publication.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(raw)
        return path

    def test_missing_checkpoint_rejects_check_and_cli(self):
        self.baseline.unlink()
        self.assertIn('checkpoint-missing', {e['code'] for e in check(self.root)['issues']})
        result = subprocess.run([sys.executable, '-m', 'harness', '--root', str(self.root), 'check'],
                                text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(json.loads(result.stdout)['ok'])

    def test_corrupt_checkpoint_is_diagnostic_not_success_or_crash(self):
        for raw in ('{', 'null', '[]', '{}', '{"files":[]}',
                    '{"files":{"../outside.md":"bad"},"revision":"bad"}'):
            with self.subTest(raw=raw):
                self.baseline.write_text(raw)
                self.assertIn('checkpoint-invalid', {e['code'] for e in check(self.root)['issues']})
                with self.assertRaises(ValueError):
                    checkpoint(self.root)

    def test_prepared_batch_blocks_cached_and_uncached_current_readers(self):
        search(self.root, self.db, 'context')
        self.journal('{"status":"prepared"}')
        for operation in (lambda: search(self.root, self.db, 'context'),
                          lambda: build(self.root, self.db),
                          lambda: context(self.root, self.root)):
            with self.assertRaisesRegex(ValueError, 'migration|publication'):
                operation()
        self.db.unlink()
        with self.assertRaises(ValueError):
            search(self.root, self.db, 'context')
        self.assertFalse(self.db.exists())

    def test_malformed_publication_blocks_readers(self):
        for raw in ('{', 'null', '[]', '{}', '{"status":"unknown"}'):
            with self.subTest(raw=raw):
                self.journal(raw)
                with self.assertRaises(ValueError):
                    context(self.root, self.root)
                with self.assertRaises(ValueError):
                    search(self.root, self.db, 'context')

    def test_history_remains_available_for_repair_and_applied_batch_resumes(self):
        self.journal('{"status":"prepared"}')
        (self.root / 'wiki/log/run/evidence.md').write_text('# Repair\ncontext')
        result = search(self.root, self.db.with_name('history.sqlite'), 'context', scope='history')
        self.assertTrue(result['hits'])
        self.journal('{"status":"applied"}')
        self.assertTrue(search(self.root, self.db, 'context')['hits'])
        self.assertEqual(context(self.root, self.root)['tasks'], [])

    def test_missing_index_or_document_directory_is_not_an_empty_project(self):
        (self.folder / 'index.md').unlink()
        with self.assertRaisesRegex(ValueError, 'index|owner'):
            context(self.root, self.root)
        self.folder.rmdir()
        with self.assertRaisesRegex(ValueError, 'index|owner'):
            context(self.root, self.root)

    def test_missing_workspace_is_not_valid_context(self):
        with self.assertRaisesRegex(ValueError, 'Workspace|workspace'):
            context(self.root, self.root / 'missing')

    def test_registered_owner_cannot_escape_vault(self):
        registry = self.baseline.parent / 'projects.json'
        data = json.loads(registry.read_text())
        data['projects'][0]['documents'] = '../outside'
        registry.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            context(self.root, self.root)

    def test_publication_change_during_context_is_rejected(self):
        def concurrent_writer(workspace):
            self.journal('{"status":"applied"}')
            return None
        with patch('harness.context.git_common', side_effect=concurrent_writer):
            with self.assertRaisesRegex(ValueError, 'Publication changed'):
                context(self.root, self.root)

    def test_bootstrap_does_not_bypass_document_or_publication_validation(self):
        self.baseline.unlink()
        self.journal('{"status":"prepared"}')
        with self.assertRaises(ValueError):
            checkpoint(self.root, initialize=True)
        self.journal('{"status":"applied"}')
        (self.folder / 'index.md').write_text('# Index\n[missing](missing.md)')
        with self.assertRaises(ValueError):
            checkpoint(self.root, initialize=True)
        self.assertFalse(self.baseline.exists())
