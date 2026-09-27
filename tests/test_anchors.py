import tempfile
from pathlib import Path
import unittest

from harness.anchors import anchors, fragment_issue
from harness.check import check, link_target


class AnchorTests(unittest.TestCase):
    def test_markdown_slugs_unicode_duplicates_inline_markup_and_code(self):
        raw = '# A **bold** [link](https://example.com)\n## 한글 제목\n## Repeat\n## Repeat\n```md\n## Fake\n```\n'.encode()
        values = anchors(raw)
        self.assertTrue({'a-bold-link', '한글-제목', 'repeat', 'repeat-1'} <= values)
        self.assertNotIn('fake', values)

    def test_obsidian_blocks_and_html_ids(self):
        self.assertIn('^sample', anchors(b'A paragraph ^sample\n'))
        self.assertIn('diagram', anchors(b'<div id="diagram">Example</div>', html=True))

    def test_existing_file_with_missing_heading_fails_but_real_heading_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            p = root/'wiki/notes/example.md';p.parent.mkdir(parents=True)
            p.write_text('# Example\n[Target](target.md#missing)\n')
            t = p.with_name('target.md');t.write_text('# Present\ntext\n')
            result = check(root, initialize=True)
            self.assertEqual([e['code'] for e in result['issues']], ['missing-anchor'])
            p.write_text('# Example\n[Target](target.md#present)\n')
            self.assertTrue(check(root, initialize=True)['ok'])

    def test_same_document_encoded_and_wiki_heading_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            p = root/'wiki/notes/example.md';p.parent.mkdir(parents=True)
            p.write_text('# 한글 제목\ntext\n')
            for value, wiki in (('#%ED%95%9C%EA%B8%80-%EC%A0%9C%EB%AA%A9', False),
                                ('wiki/notes/example#한글 제목', True)):
                self.assertIsNone(fragment_issue(root, p, value, wiki, link_target))
            self.assertEqual(fragment_issue(root, p, '#absent', False, link_target)['code'], 'missing-anchor')
            self.assertIsNone(fragment_issue(root, p, 'https://example.com/#absent', False, link_target))
