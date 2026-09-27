import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from harness.checkpoint import checkpoint
from harness.hooks import handle, recover, pending_issues, role
from harness.preserve import snapshot


class HookTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.doc = self.root / 'wiki/notes/owner.md'
        self.doc.parent.mkdir(parents=True)
        self.doc.write_text('# Owner\nCurrent\n')
        checkpoint(self.root, initialize=True)
        (self.root / '.local/harness/projects.json').write_text(json.dumps({'projects': [{'root': str(self.root)}]}))

    def event(self, agent='claude', event='PreToolUse', session='one', path=None, **extra):
        path = path or self.doc
        data = {'session_id': session, 'hook_event_name': event, 'cwd': str(self.root),
                'tool_name': 'Write', 'tool_input': {'file_path': str(path), 'content': '# New'}}
        if agent == 'codex':
            data.update(tool_name='apply_patch', tool_input={'command': f'*** Begin Patch\n*** Update File: {path}\n@@\n-Current\n+New\n*** End Patch'})
        data.update(extra)
        return handle(self.root, agent, data)

    def deny(self, result, code):
        self.assertEqual(result['hookSpecificOutput']['permissionDecision'], 'deny')
        self.assertIn(code, result['hookSpecificOutput']['permissionDecisionReason'])

    def test_both_agents_deny_unpreserved_edit(self):
        for agent in ('codex', 'claude'):
            self.deny(self.event(agent), 'before-state')
        self.assertEqual(self.doc.read_text(), '# Owner\nCurrent\n')

    def test_valid_preservation_and_finalize_allow_stop(self):
        snapshot(self.root, ['wiki/notes/owner.md'], 'update')
        self.assertEqual(self.event(), {})
        self.doc.write_text('# Owner\nNew\n')
        self.event(event='PostToolUse')
        self.assertEqual(pending_issues(self.root), [])
        self.assertEqual(self.event(event='Stop')['decision'], 'block')
        checkpoint(self.root)
        self.assertEqual(self.event(event='Stop', stop_hook_active=True), {})

    def test_tampered_or_stale_snapshot_cannot_authorize_edit(self):
        record = snapshot(self.root, ['wiki/notes/owner.md'], 'update')
        (record / 'before/wiki/notes/owner.md').write_text('wrong')
        self.deny(self.event(), 'before-state')

    def test_foreign_writer_and_pending_checkpoint_are_blocked(self):
        snapshot(self.root, ['wiki/notes/owner.md'], 'update')
        self.event('claude')
        self.deny(self.event('codex', session='two'), 'writer-conflict')
        with self.assertRaisesRegex(ValueError, 'hook-pending'):
            checkpoint(self.root)
        recover(self.root, 'claude', 'one')
        self.assertEqual(self.event('codex', session='two'), {})

    def test_tool_failure_releases_own_pending_edit(self):
        snapshot(self.root, ['wiki/notes/owner.md'], 'update')
        self.event()
        self.event(event='PostToolUseFailure')
        self.assertFalse(pending_issues(self.root))

    def test_repeated_failure_stops_continuation_without_passing(self):
        self.event(event='SessionStart')
        self.doc.write_text('# Owner\n[bad](missing.md)')
        first = self.event(event='Stop')
        self.assertEqual(first['decision'], 'block')
        second = self.event(event='Stop', stop_hook_active=True)
        self.assertNotIn('decision', second)
        self.assertIn('handoff-required', second['systemMessage'])

    def test_preserved_repair_is_allowed_despite_existing_content_error(self):
        self.doc.write_text('# Owner\n[bad](missing.md)')
        snapshot(self.root, ['wiki/notes/owner.md'], 'repair')
        self.assertEqual(self.event(), {})

    def test_absolute_target_from_outside_workspace_is_checked(self):
        self.deny(self.event(cwd='/tmp'), 'before-state')

    def test_read_only_and_unrelated_targets_do_not_require_tasks(self):
        self.assertEqual(self.event(event='Stop'), {})
        self.assertEqual(self.event(path=Path('/tmp/other.md')), {})
        self.assertEqual(self.event(path=self.root / 'orchestration/example.md'), {})

    def test_immutable_original_and_nonmarkdown_preservation(self):
        original = self.root / 'wiki/sources/source.txt'
        original.parent.mkdir(parents=True)
        original.write_text('original')
        self.deny(self.event(path=original), 'evidence-immutable')
        companion = self.doc.with_suffix('.html')
        companion.write_text('<p>Current</p>')
        self.deny(self.event(path=companion), 'before-state')
        snapshot(self.root, ['wiki/notes/owner.html'], 'update')
        self.assertEqual(self.event(path=companion), {})

    def test_bad_new_name_is_denied_before_write(self):
        self.deny(self.event(path=self.doc.with_name('Final Version.md')), 'filename')

    def test_missing_checkpoint_is_denied(self):
        (self.root / '.local/harness/checkpoint.json').unlink()
        self.deny(self.event(), 'checkpoint-missing')

    def test_cli_errors_use_actual_blocking_protocol(self):
        payload = {'session_id': 'test', 'hook_event_name': 'PreToolUse',
                   'cwd': str(self.root), 'tool_name': 'apply_patch', 'tool_input': {'command': 'invalid'}}
        script = Path(__file__).resolve().parents[1] / 'harness/hooks.py'
        proc = subprocess.run([sys.executable, str(script), '--agent', 'codex', '--root', str(self.root)],
                              input=json.dumps(payload), text=True, capture_output=True)
        self.assertEqual(proc.returncode, 0)
        self.deny(json.loads(proc.stdout), 'hook-unavailable')

    def test_shell_bypass_is_detected_at_stop_not_claimed_prevented(self):
        self.event(tool_name='Bash', tool_input={'command': 'external script'})
        self.doc.write_text('# Unpreserved\n')
        response = self.event(event='PostToolUse', tool_name='Bash', tool_input={'command': 'external script'})
        self.assertIn('document-check', response['hookSpecificOutput']['additionalContext'])
        self.assertEqual(self.event(event='Stop')['decision'], 'block')
