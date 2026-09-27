from datetime import date
import json
from pathlib import Path
import tempfile
import unittest

from harness.catalog import describe, export, dates, scope_for


class CatalogTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def write(self, name, body):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
        return p

    def test_capture_review_and_mtime_never_become_content_update(self):
        p = self.write('wiki/notes/reference.md', '---\nfetched_at: 2026-04-28\n---\n# Reference\n> 검토 (2026-09-24): source sections reviewed\n')
        row = describe(p, self.root, '2026-09-27')
        self.assertEqual(row['captured_declared'], '2026-04-28')
        self.assertEqual(row['review_recorded'], '2026-09-24')
        self.assertIsNone(row['content_updated_declared'])
        self.assertIn('content-date-unknown', row['flags'])
        self.assertEqual(row['freshness_certification'], 'not-performed')

    def test_example_and_incidental_dates_do_not_count_as_review(self):
        body = '# Example 2026-09-20\n```yaml\nChecked: 2026-09-25\n```\nEvent happened on 2026-09-26\n'
        self.assertEqual(dates({}, body), [])

    def test_future_review_and_explicit_deadline_remain_distinct(self):
        p = self.write('wiki/notes/owner.md', '---\nchecked: 2027-01-01\nstale_after: 2026-09-01\nupdated: wrong\n---\n# Owner\n')
        row = describe(p, self.root, '2026-09-27')
        self.assertIsNone(row['review_recorded'])
        self.assertTrue({'future-date', 'invalid-date', 'review-due'} <= set(row['flags']))

    def test_active_domain_candidates_and_archives_are_not_conflated(self):
        prefix = 'wiki/sources/Dae-Jeong/wiki/'
        self.assertEqual(scope_for(prefix+'products/resume/application-registry.yaml', {}), 'domain-owner-candidate')
        self.assertEqual(scope_for(prefix+'products/resume/submissions/copy.md', {}), 'domain-archive')
        self.assertEqual(scope_for(prefix+'products/report.md', {'status':'historical-snapshot'}), 'domain-archive')
        self.assertEqual(scope_for('wiki/sources/reference/index.md', {}), 'source')

    def test_domain_yaml_numeric_keys_are_valid_and_revision_date_is_explicit(self):
        p = self.write('wiki/sources/Dae-Jeong/wiki/products/claims.yaml',
                       'revised_at: 2026-09-07\nclaims:\n  1: claim-one\n')
        row = describe(p, self.root, '2026-09-27')
        self.assertNotIn('metadata-parse-error', row['flags'])
        self.assertEqual(row['content_updated_declared'], '2026-09-07')

    def test_register_surfaces_silent_metadata_and_embedded_path_errors(self):
        p = self.write('wiki/notes/owner.md', '---\nwiki/sources: []\n---\n{"nodes":[{"file":"missing.md"}]}')
        row = describe(p, self.root, '2026-09-27')
        self.assertTrue({'renamed-metadata-key','structured-data-in-markdown','embedded-file-missing'} <= set(row['flags']))
        self.assertEqual(row['missing_embedded_files'], ['missing.md'])

    def test_export_preserves_sources_escapes_payload_and_never_overwrites_log(self):
        p = self.write('wiki/notes/owner.md', '# </script><script>bad()</script>\nCurrent\n')
        before = p.read_bytes(), p.stat().st_mtime_ns
        result = export(self.root, Path('wiki/log/run'))
        self.assertEqual((p.read_bytes(), p.stat().st_mtime_ns), before)
        raw = (self.root/'wiki/log/run/index.html').read_text()
        self.assertNotIn('</script><script>bad()', raw)
        data = json.loads((self.root/'wiki/log/run/catalog.json').read_text())
        self.assertEqual(data['documents'][0]['path'], 'wiki/notes/owner.md')
        self.assertEqual(result['managed_candidates'], 1)
        with self.assertRaises(ValueError): export(self.root, Path('wiki/log/run'))
        with self.assertRaises(ValueError): export(self.root, Path('outside'))


if __name__ == '__main__':
    unittest.main()
