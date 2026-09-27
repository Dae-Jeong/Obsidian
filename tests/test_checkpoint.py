import json
from pathlib import Path
import tempfile
import unittest

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
