import json
import unittest
from contextlib import closing

import test_work
from harness.checkpoint import checkpoint
from harness.hooks import handle, control_command
from harness import work
from harness.preserve import snapshot
from unittest.mock import patch


class WorkHookTests(unittest.TestCase):
    git = test_work.WorkRecordTests.git

    def setUp(self):
        test_work.WorkRecordTests.setUp(self)
        self.task.write_text(self.task.read_text().replace('status: active', 'status: active\nproject_id: example\nchecked: 2026-09-27') + '\n## Goal\nTest paired work.\n## Scope\nFixture only.\n## Acceptance Criteria\nPaired changes require records.\n')
        config = self.vault / '.local/harness/projects.json'
        data = json.loads(config.read_text())
        data['work_contract'] = 1
        config.write_text(json.dumps(data))
        checkpoint(self.vault, initialize=True)

    def event(self, event, agent='codex', session='one', tool='edit', name='apply_patch', data=None, cwd=None):
        return handle(self.vault, agent, {
            'session_id': session, 'hook_event_name': event,
            'cwd': str(cwd or self.root), 'tool_use_id': tool, 'tool_name': name,
            'tool_input': data or {'command': f'*** Begin Patch\n*** Update File: {self.code}\n@@\n-initial\n+changed\n*** End Patch'},
        })

    def test_code_change_requires_task_and_record_for_both_agents(self):
        for agent in ('codex', 'claude'):
            with self.subTest(agent=agent):
                self.assertEqual(self.event('PreToolUse', agent=agent), {})
                self.code.write_text(agent)
                self.event('PostToolUse', agent=agent)
                response = self.event('Stop', agent=agent)
                self.assertEqual(response['decision'], 'block')
                self.assertIn('work-task-missing', response['reason'])

    def test_failed_tool_partial_write_is_retained(self):
        self.event('PreToolUse', agent='claude')
        self.code.write_text('partial')
        self.event('PostToolUseFailure', agent='claude')
        state = work.status(self.vault, 'claude:one')
        self.assertIn('work-unrecorded', state['issues'])
        self.assertNotIn('work-pending', state['issues'])

    def test_failure_without_tool_input_uses_saved_pair(self):
        self.event('PreToolUse', agent='claude')
        self.code.write_text('partial')
        handle(self.vault, 'claude', {'session_id': 'one', 'hook_event_name': 'PostToolUseFailure', 'tool_use_id': 'edit'})
        self.assertIn('work-unrecorded', work.status(self.vault, 'claude:one')['issues'])

    def test_denied_document_edit_does_not_create_work_pending(self):
        response = self.event('PreToolUse', name='Write', data={'file_path': str(self.task)})
        self.assertEqual(response['hookSpecificOutput']['permissionDecision'], 'deny')
        self.assertFalse(work.status(self.vault, 'codex:one')['issues'])

    def test_disabling_contract_cannot_drop_unfinished_obligation(self):
        self.event('PreToolUse')
        config = self.vault / '.local/harness/projects.json'
        data = json.loads(config.read_text())
        data['work_contract'] = 0
        config.write_text(json.dumps(data))
        self.assertIn('work-pending', self.event('Stop')['reason'])

    def test_reconcile_releases_paired_call_but_requires_changed_work_record(self):
        self.event('PreToolUse')
        self.code.write_text('interrupted')
        work.reconcile(self.vault, 'codex:one', 'edit', 'Fixture writer stopped; current code inspected')
        response = self.event('Stop')
        self.assertIn('work-unrecorded', response['reason'])
        self.assertNotIn('work-pending', response['reason'])

    def test_post_retries_after_work_finish_before_document_stage(self):
        self.event('PreToolUse')
        self.code.write_text('changed')
        work.finish(self.vault, 'codex:one', 'edit')
        self.event('PostToolUse')
        self.assertIn('work-unrecorded', self.event('Stop')['reason'])

    def test_recorded_work_allows_stop(self):
        work.bind(self.vault, 'codex:one', self.root, 'example.work')
        self.event('PreToolUse')
        self.code.write_text('changed')
        self.event('PostToolUse')
        snapshot(self.vault, [str(self.task.relative_to(self.vault))], 'Update handoff')
        self.task.write_text(self.task.read_text().replace('Initial result', 'Fixture code changed and verified'))
        work.record(self.vault, 'codex:one', str(self.evidence.relative_to(self.vault)))
        checkpoint(self.vault)
        self.assertEqual(self.event('Stop'), {})

    def test_pair_registration_failure_rolls_back_work_observation(self):
        from harness import hooks
        calls = 0
        def fail_at_pair(root):
            nonlocal calls
            calls += 1
            # Explicit product-code edits return before the document fingerprint;
            # this read happens inside the paired work transaction.
            raise RuntimeError('injected pair registration failure')
        with patch.object(hooks, 'fingerprint', side_effect=fail_at_pair):
            with self.assertRaisesRegex(RuntimeError, 'injected'):
                self.event('PreToolUse')
        self.assertEqual(calls, 1)
        self.assertFalse(work.status(self.vault, 'codex:one')['issues'])
        self.assertEqual(self.event('PreToolUse'), {})

    def test_code_target_keeps_symlink_leaf_identity(self):
        target = self.root / 'outside-target'
        target.write_text('outside')
        self.code.unlink()
        self.code.symlink_to(target)
        self.event('PreToolUse')
        self.code.unlink()
        self.code.symlink_to('other-target')
        self.event('PostToolUse')
        with closing(work.database(self.vault)) as db:
            row = db.execute('SELECT changes FROM work_calls WHERE session=?', ('codex:one',)).fetchone()
        self.assertEqual(set(json.loads(row[0])), {'code.py'})

    def test_missing_and_duplicate_ids_are_denied(self):
        response = self.event('PreToolUse', tool=None)
        self.assertIn('tool-id-missing', json.dumps(response))
        self.event('PreToolUse')
        self.assertIn('tool-id-duplicate', json.dumps(self.event('PreToolUse')))

    def test_reconcile_after_finished_work_releases_stranded_pair(self):
        self.event('PreToolUse')
        self.code.write_text('changed')
        work.finish(self.vault, 'codex:one', 'edit')
        work.reconcile(self.vault, 'codex:one', 'edit', 'Stopped fixture inspected after failed post')
        self.assertNotIn('work-pending', self.event('Stop')['reason'])

    def test_successor_sees_interrupted_call(self):
        self.event('PreToolUse')
        response = self.event('SessionStart', session='successor')
        self.assertIn('codex:one', json.dumps(response))
        self.assertIn('work-pending', json.dumps(response))
        self.assertEqual(self.event('Stop', session='successor'), {})

    def test_read_only_session_does_not_inherit_foreign_revision(self):
        self.event('SessionStart', session='reader')
        self.task.write_text(self.task.read_text() + '\nForeign writer result\n')
        self.event('PostToolUse', session='reader', name='Read', data={'file_path': str(self.task)})
        self.assertEqual(self.event('Stop', session='reader'), {})

    def test_work_control_is_not_observed_but_chained_command_is(self):
        command = 'uv run python -m harness work status --agent codex --session one'
        self.event('PreToolUse', name='Bash', data={'command': command}, cwd=self.vault)
        self.assertFalse(work.status(self.vault, 'codex:one')['issues'])
        self.event('PreToolUse', tool='chain', name='Bash', data={'command': command + ' && touch code.py'})
        self.assertIn('work-pending', work.status(self.vault, 'codex:one')['issues'])

    def test_control_parser_rejects_shell_execution_and_wrong_cwd(self):
        pure = 'uv run python -m harness work record --agent codex --session one --evidence wiki/log/result.md'
        self.assertTrue(control_command(self.vault, self.vault, pure))
        self.assertFalse(control_command(self.vault, self.root, pure))
        for suffix in ('; touch file', ' > file', '\ntrue', ' $(touch file)', ' `touch file`', ' *', ' ~/file'):
            self.assertFalse(control_command(self.vault, self.vault, pure + suffix))

    def test_explicit_root_control_requires_same_root(self):
        base = f'python -m harness --root {self.vault} work status'
        self.assertTrue(control_command(self.vault, self.vault, base))
        self.assertFalse(control_command(self.vault, self.vault, 'python -m harness --root /tmp work status'))

    def test_project_can_switch_to_central_cli_without_observing_itself(self):
        command = f'cd {self.vault} && uv run python -m harness work status'
        self.assertTrue(control_command(self.vault, self.root, command))
        for bad in (command + ' && touch file', command.replace('&&', ';'),
                    command.replace(str(self.vault), '/tmp'), command + ' > result'):
            self.assertFalse(control_command(self.vault, self.root, bad))

    def test_context_exposes_unfinished_calls_with_task_owner(self):
        from harness.context import context
        work.bind(self.vault, 'codex:one', self.root, 'example.work')
        self.event('PreToolUse')
        result = context(self.vault, self.root, 'example.work')
        self.assertEqual(result['unfinished_work'][0]['session'], 'codex:one')
        self.assertEqual(result['unfinished_work'][0]['task'], 'example.work')
        self.assertEqual(result['unfinished_work'][0]['state'], 'pending')
        self.assertIn('content', result['tasks'][0])

    def test_session_context_identifies_own_session(self):
        message = json.dumps(self.event('SessionStart', session='reader'))
        self.assertIn('Session ID: reader', message)
        self.assertIn('--agent codex --session reader', message)

    def test_session_start_delivers_actual_routes_to_both_agents(self):
        (self.vault / 'wiki/index.md').write_text('# Map\n## Knowledge Routes\nShared guide route')
        (self.task.parent.parent / 'index.md').write_text('# Project\n## Knowledge Routes\nProduct contract route')
        for agent in ('codex', 'claude'):
            message = self.event('SessionStart', agent=agent, session='route-reader')['hookSpecificOutput']['additionalContext']
            self.assertIn('Shared guide route', message)
            self.assertIn('Product contract route', message)
            self.assertIn('links_relative_to', message)
            self.assertIn(str(self.vault), message)

    def test_unknown_shell_document_change_still_checks_preservation(self):
        self.event('PreToolUse', name='Bash', data={'command': 'external-script'})
        self.task.write_text(self.task.read_text() + '\nUnpreserved edit\n')
        response = self.event('PostToolUse', name='Bash', data={'command': 'external-script'})
        self.assertIn('document-check', json.dumps(response))
        self.assertEqual(self.event('Stop')['decision'], 'block')


    def test_pure_control_batch_does_not_observe_itself(self):
        command = 'uv run python -m harness work status\nuv run python -m harness check'
        self.event('PreToolUse', name='Bash', data={'command': command}, cwd=self.vault)
        self.assertEqual(work.status(self.vault, 'codex:one')['issues'], [])
        self.assertTrue(control_command(self.vault, self.root, f'cd {self.vault} && ' + command))
        for suffix in ('\ntouch code.py', ' && touch code.py', '\ncd /tmp', '\npython -c "pass"'):
            self.assertFalse(control_command(self.vault, self.vault, command + suffix))

    def test_pure_record_control_does_not_hide_existing_pending_writer(self):
        work.bind(self.vault, 'codex:one', self.root, 'example.work')
        self.event('PreToolUse', tool='writer')
        command = 'uv run python -m harness work record --agent codex --session one --evidence wiki/log/result.md\nuv run python -m harness check'
        self.event('PreToolUse', tool='record', name='Bash', data={'command': command}, cwd=self.vault)
        state = work.status(self.vault, 'codex:one')
        self.assertEqual([c['tool'] for c in state['sessions'][0]['calls']], ['writer'])
        with self.assertRaisesRegex(ValueError, 'pending'):
            work.record(self.vault, 'codex:one', 'wiki/log/result.md')


    def test_ignored_code_is_observed_but_central_document_is_not_code(self):
        work.bind(self.vault, 'codex:one', self.root, 'example.work')
        (self.root / '.gitignore').write_text('vault/\n.artifacts/\n')
        ignored = self.root / '.artifacts/fixture.py'
        ignored.parent.mkdir()
        ignored.write_text('before')
        self.event('PreToolUse', name='Write', data={'file_path': str(ignored)})
        ignored.write_text('after')
        self.event('PostToolUse', name='Write', data={'file_path': str(ignored)})
        self.assertIn('work-unrecorded', work.status(self.vault, 'codex:one')['issues'])
        snapshot(self.vault, [str(self.task.relative_to(self.vault))], 'Document-only handoff')
        self.event('PreToolUse', tool='task', name='Write', data={'file_path': str(self.task)})
        self.task.write_text(self.task.read_text().replace('Initial result', 'Ignored target verified; next done'))
        self.event('PostToolUse', tool='task', name='Write', data={'file_path': str(self.task)})
        result = work.record(self.vault, 'codex:one', 'wiki/log/result.md')
        self.assertEqual(result['recorded'], 1)
        self.assertEqual(work.status(self.vault, 'codex:one')['issues'], [])
