import json
from pathlib import Path
import tempfile
import unittest

from harness.checkpoint import checkpoint
from harness.search import search


class DomainRetrievalTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.domain = self.root / 'wiki/sources/domain'
        self.domain.mkdir(parents=True)
        self.config = {'protected_roots': ['wiki/sources/domain'], 'current_domains': [{
            'root': 'wiki/sources/domain', 'include': ['profile/**', 'registry.yaml'],
            'exclude': ['**/originals/**'],
            'collections': [{'registry': 'registry.yaml', 'items': 'attempts',
                             'path_field': 'current_source_path', 'fallback_path_field': 'source_path',
                             'strip_prefix': 'wiki/', 'where': {'status': ['active'], 'artifact_state': ['mutable']},
                             'include': ['*.md'], 'exclude': ['old.md']}]}]}
        self.registry = self.root / '.local/harness/projects.json'
        self.registry.parent.mkdir(parents=True)
        self.registry.write_text(json.dumps(self.config))
        self.write('registry.yaml', 'attempts: []\n')
        checkpoint(self.root, initialize=True)
        self.db = self.root / '.local/harness/current.sqlite'

    def write(self, name, text):
        file = self.domain / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text)
        return file

    def test_active_owner_and_structured_registry_are_current_not_originals(self):
        self.write('profile/identity.md', '# identity\n공유 정본')
        self.write('profile/originals/old.md', '# old\n공유 원본')
        self.write('archive.md', '# archive\n공유 기록')
        self.write('registry.yaml', 'attempts:\n- id: 공유원장\n  status: ended\n  artifact_state: frozen\n')
        found = search(self.root, self.db, '공유')
        self.assertEqual({h['path'] for h in found['hits']},
                         {'wiki/sources/domain/profile/identity.md', 'wiki/sources/domain/registry.yaml'})

    def test_mutable_current_pointer_and_frozen_transition(self):
        self.write('attempt/README.md', '# old\n찾기 옛본문')
        selected = self.write('attempt/revisions/current/README.md', '# current\n찾기 현재')
        self.write('attempt/revisions/current/old.md', '# old\n찾기 옛본문')
        self.write('attempt/revisions/current/submissions/s1.md', '# frozen\n찾기 제출')
        registry = ('attempts:\n- id: one\n  status: active\n  artifact_state: mutable\n'
                    '  source_path: wiki/attempt/README.md\n'
                    '  current_source_path: wiki/attempt/revisions/current/README.md\n')
        self.write('registry.yaml', registry)
        found = search(self.root, self.db, '찾기')
        self.assertEqual([h['path'] for h in found['hits']], [str(selected.relative_to(self.root))])
        self.write('registry.yaml', registry.replace('mutable', 'frozen'))
        self.assertEqual(search(self.root, self.db, '찾기')['hits'], [])

    def test_configuration_change_invalidates_index(self):
        self.write('profile/one.md', '# owner\n찾기')
        self.assertTrue(search(self.root, self.db, '찾기')['hits'])
        self.config['current_domains'][0]['include'] = ['registry.yaml']
        self.registry.write_text(json.dumps(self.config))
        result = search(self.root, self.db, '찾기')
        self.assertTrue(result['rebuilt'])
        self.assertEqual(result['hits'], [])

    def test_domain_exclusions_also_cover_registry_selected_owners(self):
        self.write('attempt/originals/README.md', '# frozen\n찾기 원본')
        self.write('registry.yaml', 'attempts:\n- id: one\n  status: active\n  artifact_state: mutable\n  source_path: wiki/attempt/originals/README.md\n')
        self.assertEqual(search(self.root, self.db, '찾기')['hits'], [])

    def test_escape_and_unprotected_root_are_rejected(self):
        self.config['current_domains'][0]['root'] = 'wiki/sources/other'
        self.registry.write_text(json.dumps(self.config))
        with self.assertRaises(ValueError):
            search(self.root, self.db, 'query')
        self.config['current_domains'][0]['root'] = 'wiki/sources/domain'
        self.config['current_domains'][0]['include'] = ['../**']
        self.registry.write_text(json.dumps(self.config))
        with self.assertRaises(ValueError):
            search(self.root, self.db, 'query')

    def test_registry_path_escape_is_rejected(self):
        self.write('registry.yaml', 'attempts:\n- id: one\n  status: active\n  artifact_state: mutable\n  source_path: wiki/../../outside.md\n')
        with self.assertRaises(ValueError):
            search(self.root, self.db, 'query')

    def test_selected_domain_contract_errors_are_checked(self):
        from harness.check import check
        self.write('profile/owner.md', '# Owner\n[broken](missing.md)\n## 이전 본문\nold')
        codes = {e['code'] for e in check(self.root)['issues']}
        self.assertTrue({'missing-link', 'history-in-current'} <= codes)

    def test_hooks_distinguish_current_owner_from_frozen_evidence(self):
        from harness.hooks import role
        current = self.write('profile/owner.md', '# Current')
        frozen = self.write('archive.md', '# Frozen')
        self.assertEqual(role(self.root, current), 'current')
        self.assertEqual(role(self.root, frozen), 'evidence')

    def test_symbolic_link_and_missing_collection_fields_are_rejected(self):
        from harness.check import check
        outside = self.root / 'secret.md'
        outside.write_text('# private')
        (self.domain / 'profile').mkdir()
        (self.domain / 'profile/escape.md').symlink_to(outside)
        with self.assertRaises(ValueError):
            search(self.root, self.db, 'private')
        (self.domain / 'profile/escape.md').unlink()
        del self.config['current_domains'][0]['collections'][0]['items']
        self.registry.write_text(json.dumps(self.config))
        self.assertIn('domain-selection', {e['code'] for e in check(self.root)['issues']})

    def test_malformed_selector_fields_return_diagnostics(self):
        from copy import deepcopy
        from harness.check import check
        baseline = deepcopy(self.config)
        for field, value in [('items', []), ('path_field', {}),
                             ('fallback_path_field', []), ('strip_prefix', 7),
                             ('where', {'status': [{'unexpected': 'mapping'}]})]:
            with self.subTest(field=field):
                self.config = deepcopy(baseline)
                self.config['current_domains'][0]['collections'][0][field] = value
                self.registry.write_text(json.dumps(self.config))
                self.assertIn('domain-selection', {e['code'] for e in check(self.root)['issues']})

    def test_selector_typos_and_missing_domain_are_rejected(self):
        from copy import deepcopy
        from harness.check import check
        baseline = deepcopy(self.config)
        for change in ('typo', 'missing-root', 'missing-exclude'):
            with self.subTest(change=change):
                self.config = deepcopy(baseline)
                domain = self.config['current_domains'][0]
                if change == 'typo':
                    domain['collections'][0]['exlude'] = ['secret.md']
                elif change == 'missing-exclude':
                    del domain['exclude']
                else:
                    self.config['protected_roots'].append('wiki/sources/missing')
                    domain['root'] = 'wiki/sources/missing'
                    domain['collections'] = []
                self.registry.write_text(json.dumps(self.config))
                self.assertIn('domain-selection', {e['code'] for e in check(self.root)['issues']})
