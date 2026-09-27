import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from harness.check import check
from harness.checkpoint import checkpoint
from harness.preserve import snapshot


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / 'wiki/notes').mkdir(parents=True)
        self.doc = self.root / 'wiki/notes/owner.md'
        self.doc.write_text('# Owner\nCurrent result\n')
        checkpoint(self.root, initialize=True)

    def test_changed_or_deleted_owner_requires_exact_preserved_bytes(self):
        original = self.doc.read_bytes()
        self.doc.write_text('# Owner\nEdited')
        self.assertEqual(check(self.root)['issues'][0]['code'], 'before-state')
        with self.assertRaises(ValueError):
            checkpoint(self.root)
        self.doc.write_bytes(original)
        snapshot(self.root, ['wiki/notes/owner.md'], 'meaningful change')
        self.doc.unlink()
        self.assertTrue(check(self.root)['ok'])
        checkpoint(self.root)

    def test_tampered_snapshot_does_not_satisfy_preservation(self):
        record = snapshot(self.root, ['wiki/notes/owner.md'], 'change')
        (record / 'before/wiki/notes/owner.md').write_text('tampered')
        self.doc.write_text('# Updated')
        self.assertFalse(check(self.root)['ok'])

    def test_interruption_and_new_filename_are_rejected(self):
        record = self.root / 'wiki/log/update'
        record.mkdir(parents=True)
        (record / 'publication.json').write_text(json.dumps({'status': 'prepared'}))
        (self.root / 'wiki/notes/Final Version.md').write_text('# Duplicate')
        self.assertEqual({x['code'] for x in check(self.root)['issues']}, {'interrupted-update', 'filename'})

    def test_checkpoint_cannot_be_reinitialized(self):
        with self.assertRaises(ValueError):
            checkpoint(self.root, initialize=True)

    def test_foreign_checkpoint_preserves_intermediate_owner_bytes(self):
        from harness.hooks import preserved
        snapshot(self.root, ['wiki/notes/owner.md'], 'session A begins')
        self.doc.write_text('# Owner\nIntermediate result\n')
        checkpoint(self.root)  # Session B finalizes its own work globally.
        self.assertTrue(preserved(self.root, self.doc))
        self.doc.write_text('# Owner\nSession A continues\n')
        self.assertTrue(check(self.root)['ok'])

    def test_failed_checkpoint_snapshot_keeps_previous_baseline(self):
        baseline = self.root / '.local/harness/checkpoint.json'
        previous = baseline.read_bytes()
        snapshot(self.root, ['wiki/notes/owner.md'], 'session A begins')
        self.doc.write_text('# Owner\nIntermediate result\n')
        with patch('harness.preserve.snapshot', side_effect=OSError('disk failure')):
            with self.assertRaisesRegex(OSError, 'disk failure'):
                checkpoint(self.root)
        self.assertEqual(baseline.read_bytes(), previous)

    def test_concurrent_checkpoint_is_rejected_without_advancing(self):
        import fcntl
        baseline = self.root / '.local/harness/checkpoint.json'
        previous = baseline.read_bytes()
        with (baseline.parent / 'checkpoint.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(ValueError, 'checkpoint is already running'):
                checkpoint(self.root)
        self.assertEqual(baseline.read_bytes(), previous)

    def test_drift_during_checkpoint_snapshot_keeps_previous_baseline(self):
        baseline = self.root / '.local/harness/checkpoint.json'
        previous = baseline.read_bytes()
        snapshot(self.root, ['wiki/notes/owner.md'], 'session A begins')
        self.doc.write_text('# Owner\nIntermediate result\n')

        def capture_then_edit(*args):
            record = snapshot(*args)
            self.doc.write_text('# Owner\nConcurrent result\n')
            return record

        with patch('harness.preserve.snapshot', side_effect=capture_then_edit):
            with self.assertRaisesRegex(ValueError, 'Corpus changed'):
                checkpoint(self.root)
        self.assertEqual(baseline.read_bytes(), previous)

    def test_unchanged_checkpoint_does_not_create_snapshot(self):
        with patch('harness.preserve.snapshot') as capture:
            checkpoint(self.root)
        capture.assert_not_called()

    def test_verified_relocation_retains_existing_filename_contract(self):
        import hashlib
        old = 'wiki/notes/2026-01-01-topic.md'
        new = 'wiki/notes/nested/2026-01-01-topic.md'
        raw = b'# Existing owner\nCurrent knowledge\n'
        (self.root / old).write_bytes(raw)
        baseline = self.root / '.local/harness/checkpoint.json'
        data = json.loads(baseline.read_text())
        data['files'][old] = hashlib.sha256(raw).hexdigest()
        baseline.write_text(json.dumps(data))
        record = snapshot(self.root, [old], 'Move the existing owner')
        manifest = record / 'manifest.json'
        data = json.loads(manifest.read_text())
        data['files'][0]['target'] = new
        manifest.write_text(json.dumps(data))
        (self.root / new).parent.mkdir()
        (self.root / old).rename(self.root / new)
        self.assertTrue(check(self.root)['ok'])
        (record / 'before' / old).write_bytes(b'corrupt')
        self.assertEqual({e['code'] for e in check(self.root)['issues']},
                         {'before-state', 'filename'})

    def test_non_markdown_companion_changes_require_preservation(self):
        for suffix in ('.json', '.yaml', '.html', '.svg'):
            with self.subTest(suffix=suffix):
                path = self.root / ('wiki/notes/companion'+suffix)
                path.write_text('original bytes')
                checkpoint(self.root)
                before = path.read_bytes()
                # Corrupt the checkpoint-created copy: its mere existence must not pass.
                name = path.relative_to(self.root)
                for record in (self.root / 'wiki/log').iterdir():
                    copy = record / 'before' / name
                    if copy.is_file():
                        copy.write_text('tampered baseline copy')
                path.write_text('unpreserved edit')
                self.assertIn('before-state', {e['code'] for e in check(self.root)['issues']})
                path.write_bytes(before)
                snapshot(self.root, [path.relative_to(self.root).as_posix()], 'update companion')
                path.write_text('preserved edit')
                self.assertTrue(check(self.root)['ok'])
                checkpoint(self.root)

    def test_registered_source_domain_is_protected_without_promoting_source_to_current(self):
        from harness.documents import paths
        domain = self.root/'wiki/sources/domain'
        domain.mkdir(parents=True)
        registry = self.root/'.local/harness/projects.json'
        registry.write_text(json.dumps({'protected_roots':['wiki/sources/domain']}))
        source = domain/'application-registry.yaml'
        source.write_text('status: pending\n')
        checkpoint(self.root)
        self.assertNotIn(source, list(paths(self.root)))
        for record in (self.root / 'wiki/log').iterdir():
            copy = record / 'before' / source.relative_to(self.root)
            if copy.is_file():
                copy.write_text('tampered baseline copy')
        source.write_text('status: submitted\n')
        self.assertIn('before-state', {e['code'] for e in check(self.root)['issues']})
        source.write_text('status: pending\n')
        snapshot(self.root, ['wiki/sources/domain/application-registry.yaml'], 'domain status update')
        source.write_text('status: submitted\n')
        self.assertTrue(check(self.root)['ok'])
        checkpoint(self.root)
        registry.write_text('{}')
        self.assertIn('checkpoint-invalid', {e['code'] for e in check(self.root)['issues']})

    def test_companion_changes_invalidate_current_revision(self):
        from harness.documents import fingerprint
        p = self.root/'wiki/notes/companion.json'
        p.write_text('{}')
        before = fingerprint(self.root)
        p.write_text('{"changed":true}')
        self.assertNotEqual(before, fingerprint(self.root))
