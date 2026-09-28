import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from harness.structure_audit import audit, headings, inspect

VALID = b'''---
type: note
subject_type: concept
title: Example
checked: null
verification: unverified
---
# Example
## Summary
A definition.
## Explanation
A mechanism.
## Applicability
A boundary.
## Evidence
A source.
'''


class AuditTests(unittest.TestCase):
    def test_valid_and_missing_required_field(self):
        self.assertEqual(inspect('wiki/notes/a.md', VALID)['status'], 'pass')
        row = inspect('wiki/notes/a.md', VALID.replace(b'title: Example\n', b''))
        self.assertEqual(row['status'], 'fail')
        self.assertIn('structure-field', [i['code'] for i in row['issues']])

    def test_order_and_duplicates_are_contract_failures(self):
        raw = VALID.replace(b'## Summary', b'## Explanation', 1).replace(b'## Explanation\nA mechanism.', b'## Summary\nA mechanism.')
        row = inspect('wiki/notes/a.md', raw + b'\n## Evidence\nMore.\n')
        self.assertEqual(row['status'], 'fail')
        self.assertEqual(set(row['form_differences']), {'structure-order', 'structure-duplicate-heading'})

    def test_fenced_examples_and_comments_are_not_headings(self):
        body = '# Real\n````md\n```\n## Fake\n````\n<!--\n## Hidden\n-->\n## Actual\n'
        self.assertEqual(headings(body), [(1, 'Real'), (2, 'Actual')])

    def test_malformed_and_unsupported_never_count_as_pass(self):
        self.assertEqual(inspect('wiki/notes/a.md', b'---\ntype: [\n---\n')['status'], 'fail')
        self.assertEqual(inspect('wiki/sources/original.md', VALID)['status'], 'not-covered')

    def test_denominators_cli_exit_and_no_document_mutation(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            p = root/'wiki/notes/a.md'; p.parent.mkdir(parents=True)
            p.write_bytes(VALID)
            (root/'README.md').write_text('# Entry\n\nBody.')
            result = audit(root)
            self.assertEqual(result['summary']['current_owners'], 2)
            self.assertEqual(result['summary']['covered'], 2)
            self.assertEqual(result['summary']['pass_percent'], 100)
            self.assertEqual(result['roles']['note:concept']['retrieval'], {'absent': 1})
            p.write_bytes(VALID.replace(b'## Evidence', b'## Other'))
            before = p.read_bytes()
            proc = subprocess.run([sys.executable, '-m', 'harness.structure_audit', '--root', name], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 1)
            self.assertEqual(json.loads(proc.stdout)['summary']['failed'], 1)
            self.assertEqual(p.read_bytes(), before)

    def test_product_owners_are_delegated_not_counted_as_passes(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            p = root/'wiki/sources/product/registry.yaml'; p.parent.mkdir(parents=True)
            p.write_text('items: []\n')
            with patch('harness.structure_audit.domains.paths', return_value=[p]):
                report = audit(root)
            self.assertEqual(report['summary']['covered'], 0)
            self.assertIsNone(report['summary']['pass_percent'])
            self.assertEqual(report['responsibility'], {'product-owned': 1})
            self.assertEqual(report['documents'][0]['status'], 'not-covered')
            with patch('harness.structure_audit.paths', return_value=[p]):
                report = audit(root)
            self.assertEqual(report['summary']['unassigned'], 1)
