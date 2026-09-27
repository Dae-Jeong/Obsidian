"""Role contracts: valid populated templates and isolated violations."""
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from harness.documents import parse
from harness.structure import TEMPLATES, check_file, contract, enabled, validate


class StructureTests(unittest.TestCase):
    def populated(self, name):
        text = (TEMPLATES / f'{name}.md').read_text()
        text = text.replace('{{title}}', 'Example').replace('{{date:YYYY-MM-DD}}', '2026-09-27')
        text = text.replace('<project-id>', 'example').replace('<stable-task-name>', 'work')
        text = text.replace('checked: null', 'checked: 2026-09-27')
        return re.sub(r'<!--.*?-->', 'Fixture content for this section.', text, flags=re.S)

    def codes(self, name, text):
        return {e['code'] for e in validate(parse(name, text.encode()))}

    def test_all_eight_populated_forms(self):
        for name in ('project', 'task', 'note', 'note-procedure', 'note-reference', 'note-policy', 'review', 'log'):
            with self.subTest(template=name):
                path = {'project': 'wiki/projects/example/index.md',
                        'task': 'wiki/projects/example/tasks/work.md',
                        'review': 'wiki/projects/example/reviews/work.md',
                        'log': 'wiki/log/run/result.md'}.get(name, 'wiki/notes/example.md')
                self.assertEqual(self.codes(path, self.populated(name)), set())

    def test_note_purpose_selects_required_sections(self):
        text = self.populated('note-procedure').replace('## Verification', '## Other')
        self.assertIn('structure-section', self.codes('wiki/notes/example.md', text))
        text = self.populated('note').replace('subject_type: concept', 'subject_type: unknown')
        self.assertEqual(self.codes('wiki/notes/example.md', text), {'structure-subtype'})

    def test_conditional_sections_may_be_omitted(self):
        text = self.populated('note-procedure')
        text = re.sub(r'## Prerequisites\n.*?(?=## Procedure)', '', text, flags=re.S)
        self.assertEqual(self.codes('wiki/notes/example.md', text), set())

    def test_comments_and_fake_fenced_headings_do_not_satisfy_required_sections(self):
        text = self.populated('task').replace('## Next Action\n\nFixture content for this section.',
                                             '```md\n## Next Action\nnot a section\n```')
        self.assertIn('structure-section', self.codes('wiki/projects/example/tasks/work.md', text))
        text = self.populated('task').replace('## Next Action\n\nFixture content for this section.',
                                             '## Next Action\n\n<!-- Not populated -->')
        self.assertIn('structure-section', self.codes('wiki/projects/example/tasks/work.md', text))

    def test_checked_date_and_verified_claim(self):
        path = 'wiki/notes/example.md'
        text = self.populated('note').replace('checked: 2026-09-27', 'checked: null')
        self.assertEqual(self.codes(path, text), set())
        self.assertIn('structure-date', self.codes(path, text.replace('verification: unverified', 'verification: verified')))
        for value in ('20260927', 'true', '"2026-02-30"', '2026-09-27T00:00:00Z'):
            self.assertIn('structure-date', self.codes(path, self.populated('note').replace('checked: 2026-09-27', 'checked: '+value)))

    def test_placeholder_and_location_mismatch(self):
        path = 'wiki/projects/example/tasks/work.md'
        self.assertIn('structure-placeholder', self.codes(path, self.populated('task').replace('title: "Example"', 'title: "{{title}}"')))
        self.assertIn('structure-project', self.codes(path, self.populated('task').replace('project_id: "example"', 'project_id: "wrong"')))
        text = self.populated('note')+'\n```md\n{{title}}\n```\n'
        self.assertEqual(self.codes('wiki/notes/example.md', text), set())

    def test_new_required_prompt_is_consumed_without_duplicate_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder/'task.md').write_text((TEMPLATES/'task.md').read_text()+'\n## Required Fixture\n\n<!-- Required: example. -->\n')
            with patch('harness.structure.TEMPLATES', folder):
                _, headings = contract('task')
                self.assertIn('Required Fixture', headings)
                self.assertIn('structure-section', self.codes('wiki/projects/example/tasks/work.md', self.populated('task')))

    def test_malformed_metadata_and_outside_scope_return_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            p = root/'wiki/notes/example.md'; p.parent.mkdir(parents=True)
            p.write_text('---\ntype: [\n---\n# Test\n')
            self.assertEqual(check_file(root, p)[0]['code'], 'structure-metadata')
            process = subprocess.run([sys.executable, '-m', 'harness', '--root', directory, 'structure', str(p)], capture_output=True, text=True)
            self.assertEqual(process.returncode, 1)
            self.assertFalse(json.loads(process.stdout)['ok'])
            self.assertEqual(check_file(root, root/'README.md')[0]['code'], 'structure-scope')

    def test_opt_in_requires_exact_supported_version(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertFalse(enabled(root))
            p = root/'.local/harness/projects.json';p.parent.mkdir(parents=True)
            for version in (True, False, 0, 2, '1'):
                p.write_text(json.dumps({'document_contract': version}))
                with self.assertRaises(ValueError): enabled(root)
            p.write_text('{"document_contract":1}')
            self.assertTrue(enabled(root))
