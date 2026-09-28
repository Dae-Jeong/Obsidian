import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from harness.documents import parse
from harness.check import check
from harness.retrieval import metadata
from harness.search import search


class RetrievalTests(unittest.TestCase):
    def test_metadata_rejects_invalid_roles_lengths_and_missing_sections(self):
        def doc(fields):
            return parse('wiki/notes/example.md', ('---\nretrieval:\n' + fields + '\n---\n## Use\nAdvice').encode())
        valid = '  description: Choose a transaction boundary\n  use_when: Designing retries\n  role: guidance\n  aliases: [idempotency]\n  sections: [Use]'
        self.assertEqual(metadata(doc(valid))['sections'], ['Use'])
        for bad in (valid.replace('guidance', 'truth'), valid.replace('[Use]', '[Missing]'),
                    valid.replace('Choose a transaction boundary', 'x' * 241),
                    valid + '\n  unknown: value', valid.replace('[idempotency]', 'idempotency')):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                metadata(doc(bad))
        self.assertEqual(metadata(parse('plain.md', b'# Plain\nBody')), {})

    def test_brief_alias_lookup_rebuild_and_no_body_leak(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            notes = root / 'wiki/notes'
            notes.mkdir(parents=True)
            owner = notes / 'guide.md'
            owner.write_text('---\ntitle: Retry design\nchecked: 2026-09-10\nverification: partial\nretrieval:\n  description: Separate state and delivery\n  use_when: Choosing transaction boundaries\n  role: guidance\n  aliases: [멱등성]\n  sections: [Applicability]\n---\n## Applicability\n' + 'PRIVATE_BODY ' * 150)
            database = root / 'index.sqlite'
            database.parent.mkdir(exist_ok=True)
            with closing(sqlite3.connect(database)) as db:
                db.execute('CREATE TABLE meta (key TEXT, value TEXT)')
            result = search(root, database, '멱등성', brief=True)
            self.assertTrue(result['rebuilt'])
            hit = result['hits'][0]
            self.assertEqual(hit['retrieval']['role'], 'guidance')
            self.assertEqual(hit['checked'], '2026-09-10')
            self.assertNotIn('PRIVATE_BODY', json.dumps(result))
            self.assertNotIn('excerpt', hit)
            full = search(root, database, '멱등성')
            self.assertFalse(full['rebuilt'])
            self.assertIn('PRIVATE_BODY', full['hits'][0]['excerpt'])
            owner.write_text(owner.read_text().replace('멱등성', '동시성'))
            self.assertEqual(search(root, database, '멱등성', brief=True)['hits'], [])
            self.assertEqual(len(search(root, database, '동시성', brief=True)['hits']), 1)
            owner.write_text(owner.read_text().replace('sections: [Applicability]', 'sections: [Missing]'))
            issues = check(root, initialize=True)['issues']
            self.assertTrue(any(issue['code'] == 'retrieval-metadata' for issue in issues))
            with self.assertRaisesRegex(ValueError, 'unique existing sections'):
                search(root, database, '동시성', brief=True)
