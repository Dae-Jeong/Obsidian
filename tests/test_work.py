import os
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from harness.work import manifest, differences, repository
from harness import work
from harness.context import git_environment


class WorkObservationTests(unittest.TestCase):
    def test_session_identity_rejects_agent_prefix_inside_raw_id(self):
        for valid in ('codex:one', 'claude:session-1', 'kiro:real-session'):
            work.identity(valid)
        for invalid in ('codex:codex:one', 'claude:claude:one', 'kiro:kiro:one', 'unknown:one', 'kiro:', 'codex:', 'codex: one', 'codex:one\n'):
            with self.assertRaises(ValueError):
                work.identity(invalid)

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.git('init', '-q')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.git('config', 'user.name', 'Fixture')

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.root), *args],
                              capture_output=True, text=True, check=True, env=git_environment())

    def test_changes_include_content_add_delete_and_executable_mode(self):
        code = self.root / 'code.py'
        code.write_text('one')
        self.git('add', 'code.py')
        before = manifest(self.root)
        code.write_text('two')
        added = self.root / 'a file\nwith newline.py'
        added.write_text('new')
        after = manifest(self.root)
        self.assertEqual(set(differences(before, after)), {'code.py', added.name})
        before = after
        code.chmod(0o755)
        self.assertEqual(set(differences(before, manifest(self.root))), {'code.py'})
        before = manifest(self.root)
        code.unlink()
        self.assertEqual(differences(before, manifest(self.root))['code.py']['after'], None)

    def test_ignored_files_and_symlink_targets_are_not_read(self):
        (self.root / '.gitignore').write_text('ignored/\n')
        ignored = self.root / 'ignored'
        ignored.mkdir()
        target = ignored / 'private'
        target.write_text('one')
        link = self.root / 'link'
        link.symlink_to(target)
        before = manifest(self.root)
        self.assertNotIn('ignored/private', before)
        target.write_text('two')
        self.assertEqual(manifest(self.root), before)
        link.unlink()
        link.symlink_to('elsewhere')
        self.assertEqual(set(differences(before, manifest(self.root))), {'link'})

    def test_tracked_path_replaced_by_parent_symlink_is_not_followed(self):
        folder = self.root / 'folder'
        folder.mkdir()
        (folder / 'code.py').write_text('tracked')
        self.git('add', 'folder/code.py')
        (folder / 'code.py').unlink()
        folder.rmdir()
        target = self.root / 'ignored'
        target.mkdir()
        (self.root / '.gitignore').write_text('ignored/\n')
        (target / 'code.py').write_text('outside')
        folder.symlink_to(target, target_is_directory=True)
        before = manifest(self.root)
        (target / 'code.py').write_text('changed outside')
        self.assertEqual(manifest(self.root), before)
        self.assertEqual(before['folder/code.py'], 'ancestor-symlink')

    def test_worktrees_remain_distinct_and_non_git_is_explicit(self):
        (self.root / 'code.py').write_text('main')
        self.git('add', 'code.py')
        self.git('commit', '-qm', 'initial')
        with tempfile.TemporaryDirectory() as second:
            linked = Path(second) / 'linked'
            self.git('worktree', 'add', '-q', '-b', 'other', str(linked))
            (linked / 'code.py').write_text('other')
            self.assertEqual(repository(linked), linked.resolve())
            self.assertNotEqual(manifest(linked), manifest(self.root))
        with tempfile.TemporaryDirectory() as outside:
            with self.assertRaisesRegex(ValueError, 'Git worktree'):
                repository(Path(outside))

    def test_foreign_git_environment_cannot_redirect_observation(self):
        from unittest.mock import patch
        (self.root / 'code.py').write_text('owned')
        with patch.dict(os.environ, {'GIT_DIR': '/does/not/exist', 'GIT_WORK_TREE': '/tmp'}):
            self.assertEqual(repository(self.root), self.root)
            self.assertIn('code.py', manifest(self.root))


class WorkRecordTests(unittest.TestCase):
    git = WorkObservationTests.git

    def setUp(self):
        WorkObservationTests.setUp(self)
        self.vault = self.root / 'vault'
        (self.vault / '.local/harness').mkdir(parents=True)
        docs = self.vault / 'wiki/projects/example'
        (docs / 'tasks').mkdir(parents=True)
        (docs / 'index.md').write_text('# Project')
        self.task = docs / 'tasks/work.md'
        self.task.write_text('---\nid: example.work\nstatus: active\n---\n# Work\n## Current Result\nInitial result\n## Next Action\nPerform work')
        (self.root / '.gitignore').write_text('vault/\n')
        (self.vault / '.local/harness/projects.json').write_text(json.dumps({'projects': [{
            'id': 'example', 'root': str(self.root), 'documents': 'wiki/projects/example'}]}))
        self.code = self.root / 'code.py'
        self.code.write_text('initial')
        self.evidence = self.vault / 'wiki/log/result.md'
        self.evidence.parent.mkdir(parents=True)
        self.evidence.write_text('# Result\nActual isolated execution evidence')
        self.key = 'codex:one'

    def bind(self, key=None):
        return work.bind(self.vault, key or self.key, self.root, 'example.work')

    def begin(self, tool='one', key=None, selected=('code.py',)):
        return work.begin(self.vault, key or self.key, tool, self.root, selected)

    def finish(self, tool='one', key=None):
        return work.finish(self.vault, key or self.key, tool)

    def record(self, **kwargs):
        return work.record(self.vault, self.key, 'wiki/log/result.md', **kwargs)

    def test_code_changes_need_binding_updated_task_and_evidence(self):
        self.begin()
        self.code.write_text('changed')
        self.finish()
        self.assertIn('work-task-missing', work.status(self.vault, self.key)['issues'])
        self.bind()
        with self.assertRaisesRegex(ValueError, 'Task'):
            self.record()
        self.task.write_text(self.task.read_text() + '\nCompleted change; next verify integration')
        with self.assertRaisesRegex(ValueError, 'evidence'):
            work.record(self.vault, self.key, 'wiki/log/missing.md')
        result = self.record()
        self.assertTrue((self.vault / result['evidence']).is_file())
        self.assertEqual(work.status(self.vault, self.key)['issues'], [])

    def test_kiro_manual_cli_observation_records_only_after_task_update(self):
        import sys
        def cli(*args):
            return subprocess.run([sys.executable, '-m', 'harness', '--root', str(self.vault),
                                   'work', *args, '--agent', 'kiro', '--session', 'real-session'],
                                  cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
        self.assertEqual(cli('bind', str(self.root), '--task', 'example.work').returncode, 0)
        self.assertEqual(cli('begin', str(self.root), '--tool', 'edit-1', '--target', 'code.py').returncode, 0)
        self.code.write_text('kiro change')
        self.assertEqual(cli('finish', '--tool', 'edit-1').returncode, 0)
        self.assertNotEqual(cli('record', '--evidence', 'wiki/log/result.md').returncode, 0)
        self.task.write_text(self.task.read_text() + '\nKiro change verified; next action completed')
        result = cli('record', '--evidence', 'wiki/log/result.md')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        receipt = json.loads((self.vault / json.loads(result.stdout)['evidence']).read_text())
        self.assertEqual(receipt['session'], 'kiro:real-session')
        self.assertEqual(work.status(self.vault, 'kiro:real-session')['issues'], [])

    def test_recorded_work_becomes_unrecorded_after_another_edit(self):
        self.bind()
        self.begin()
        self.code.write_text('first')
        self.finish()
        self.task.write_text(self.task.read_text() + '\nFirst result')
        self.record()
        self.begin('two')
        self.code.write_text('second')
        self.finish('two')
        with self.assertRaisesRegex(ValueError, 'Task'):
            self.record()

    def test_metadata_only_task_change_does_not_satisfy_handoff(self):
        self.bind()
        self.begin()
        self.code.write_text('changed')
        self.finish()
        self.task.write_text(self.task.read_text().replace('status: active', 'status: review'))
        with self.assertRaisesRegex(ValueError, 'handoff'):
            self.record()

    def test_handoff_updated_before_tool_finishes_does_not_record_later_change(self):
        self.bind()
        self.begin()
        self.task.write_text(self.task.read_text() + '\nPremature handoff')
        self.code.write_text('later change')
        self.finish()
        with self.assertRaisesRegex(ValueError, 'Task'):
            self.record()

    def test_unknown_tool_window_requires_reconciliation(self):
        self.bind()
        self.begin(selected=None)
        self.code.write_text('cannot prove writer from shell window')
        self.finish()
        self.task.write_text(self.task.read_text() + '\nInspected observed result')
        with self.assertRaisesRegex(ValueError, 'overlap'):
            self.record()

    def test_drift_during_record_does_not_clear_unrecorded_state(self):
        from unittest.mock import patch
        self.bind()
        self.begin()
        self.code.write_text('observed')
        self.finish()
        self.task.write_text(self.task.read_text() + '\nResult')
        original = work.manifest
        calls = []
        def observing(path):
            result = original(path)
            calls.append(True)
            if len(calls) == 1:
                self.code.write_text('drift during record')
            return result
        with patch.object(work, 'manifest', side_effect=observing):
            with self.assertRaisesRegex(ValueError, 'drift'):
                self.record()
        self.assertIn('work-unrecorded', work.status(self.vault, self.key)['issues'])

    def test_begin_capture_and_registration_do_not_lose_peer_overlap(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event, Lock
        from unittest.mock import patch
        self.bind()
        self.bind('claude:two')
        captured, peer_done = Event(), Event()
        guard = Lock()
        first = [True]
        original = work.manifest
        def observing(path):
            with guard:
                outer = first[0]
                first[0] = False
            result = original(path)
            if outer:
                captured.set()
                peer_done.wait(0.5)
            return result
        def peer():
            self.begin(key='claude:two')
            self.code.write_text('peer change')
            self.finish(key='claude:two')
            peer_done.set()
        with patch.object(work, 'manifest', side_effect=observing), ThreadPoolExecutor(max_workers=2) as pool:
            outer = pool.submit(self.begin)
            self.assertTrue(captured.wait(2))
            other = pool.submit(peer)
            outer.result(timeout=5)
            other.result(timeout=5)
        self.finish()
        self.assertIn('work-ambiguous', work.status(self.vault, self.key)['issues'])

    def test_other_session_changes_do_not_dirty_explicit_read_only_call(self):
        self.bind()
        self.begin(selected=())
        self.code.write_text('foreign change')
        self.finish()
        self.assertEqual(work.status(self.vault, self.key)['issues'], [])

    def test_overlap_requires_explicit_reconciliation_and_keeps_owner_limits(self):
        self.bind()
        self.bind('claude:two')
        self.begin()
        self.begin(key='claude:two')
        self.code.write_text('overlapping')
        self.finish()
        self.finish(key='claude:two')
        self.task.write_text(self.task.read_text() + '\nReconciled writers and actual result')
        with self.assertRaisesRegex(ValueError, 'overlap'):
            self.record()
        receipt = self.record(reconciliation='Both writers stopped; inspected actual file and Task')
        body = json.loads((self.vault / receipt['evidence']).read_text())
        self.assertTrue(body['observations'][0]['ambiguous'])
        self.assertIn('work-unrecorded', work.status(self.vault, 'claude:two')['issues'])

    def test_interrupted_call_survives_and_recovery_does_not_record_work(self):
        self.bind()
        self.begin()
        self.code.write_text('interrupted')
        self.assertIn('work-pending', work.status(self.vault, self.key)['issues'])
        with self.assertRaisesRegex(ValueError, 'pending'):
            self.record()
        work.reconcile(self.vault, self.key, 'one', 'Writer termination confirmed; actual files inspected')
        self.assertIn('work-unrecorded', work.status(self.vault, self.key)['issues'])
        self.assertNotIn('work-pending', work.status(self.vault, self.key)['issues'])

    def test_changed_observation_cannot_be_recorded_after_unobserved_drift(self):
        self.bind()
        self.begin()
        self.code.write_text('observed')
        self.finish()
        self.task.write_text(self.task.read_text() + '\nResult')
        self.code.write_text('foreign later drift')
        with self.assertRaisesRegex(ValueError, 'drift'):
            self.record()

    def test_evidence_swap_after_containment_check_is_rejected(self):
        from unittest.mock import patch
        self.bind()
        self.begin()
        self.code.write_text('observed')
        self.finish()
        self.task.write_text(self.task.read_text() + '\nResult')
        outside = self.vault / 'outside.txt'
        outside.write_text('not Log evidence')
        original = work.manifest
        def observing(path):
            result = original(path)
            if not self.evidence.is_symlink():
                self.evidence.unlink()
                self.evidence.symlink_to(outside)
            return result
        with patch.object(work, 'manifest', side_effect=observing):
            with self.assertRaisesRegex(ValueError, '[Ee]vidence'):
                self.record()
        self.assertIn('work-unrecorded', work.status(self.vault, self.key)['issues'])

    def test_fifo_evidence_is_rejected_without_waiting_for_a_writer(self):
        import sys
        fifo = self.evidence.with_name('fifo')
        os.mkfifo(fifo)
        command = ('from pathlib import Path; from harness.work import evidence_hash; '
                   'import sys; evidence_hash(Path(sys.argv[1]), "wiki/log/fifo")')
        result = subprocess.run([sys.executable, '-c', command, str(self.vault)],
                                capture_output=True, text=True, timeout=2)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('regular file', result.stderr)

    def test_swapped_log_parent_cannot_receive_receipt_outside_log(self):
        from unittest.mock import patch
        self.bind()
        self.begin()
        self.code.write_text('observed')
        self.finish()
        self.task.write_text(self.task.read_text() + '\nResult')
        outside = self.vault / 'outside-log'
        outside.mkdir()
        (outside / 'result.md').write_text(self.evidence.read_text())
        log = self.vault / 'wiki/log'
        original = work.manifest
        def observing(path):
            result = original(path)
            if not log.is_symlink():
                log.rename(log.with_name('log-original'))
                log.symlink_to(outside, target_is_directory=True)
            return result
        with patch.object(work, 'manifest', side_effect=observing):
            with self.assertRaises(ValueError):
                self.record()
        self.assertEqual([p.name for p in outside.iterdir()], ['result.md'])

    def test_changed_observation_can_be_reconciled_without_losing_original(self):
        self.bind()
        self.begin()
        self.code.write_text('observed')
        observed = manifest(self.root)['code.py']
        self.finish()
        self.code.write_text('actual reconciled state')
        work.reconcile(self.vault, self.key, 'one', 'Both writers stopped; inspected current state')
        self.task.write_text(self.task.read_text() + '\nActual reconciled result and next action')
        result = self.record(reconciliation='Inspected both writer results')
        receipt = json.loads((self.vault / result['evidence']).read_text())
        call = receipt['observations'][0]
        self.assertEqual(call['changes']['code.py']['after'], observed)
        self.assertEqual(call['reconciled_state']['code.py'], manifest(self.root)['code.py'])
        self.assertTrue(call['ambiguous'])

    def test_reconciling_older_call_requires_another_handoff_update(self):
        self.bind()
        self.begin('older')
        self.code.write_text('older')
        self.finish('older')
        self.begin('newer')
        self.code.write_text('newer')
        self.finish('newer')
        self.task.write_text(self.task.read_text() + '\nPrior handoff')
        work.reconcile(self.vault, self.key, 'older', 'Inspected current state after both calls')
        with self.assertRaisesRegex(ValueError, 'Task'):
            self.record(reconciliation='Resolved older observation')

    def test_wrong_task_and_pending_rebinding_are_rejected(self):
        with self.assertRaises(ValueError):
            work.bind(self.vault, self.key, self.root, 'different.task')
        self.bind()
        self.begin()
        other = self.task.with_name('other.md')
        other.write_text('---\nid: example.other\nstatus: active\n---\n# Other')
        with self.assertRaisesRegex(ValueError, 'unfinished'):
            work.bind(self.vault, self.key, self.root, 'example.other')

    def test_cli_reports_pending_and_rejects_incomplete_identity(self):
        import sys
        self.bind()
        self.begin()
        command = [sys.executable, '-m', 'harness', '--root', str(self.vault), 'work', 'status']
        result = subprocess.run(command + ['--workspace', str(self.root)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('work-pending', json.loads(result.stdout)['issues'])
        result = subprocess.run(command + ['--agent', 'codex'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('both', json.loads(result.stderr)['error'])


class WorkTerminalTests(unittest.TestCase):
    """Session terminal linkage: explicit ID, own Orca handle, or unknown."""
    setUp = WorkRecordTests.setUp
    git = WorkRecordTests.git
    begin = WorkRecordTests.begin

    def env(self, handle=None):
        from unittest.mock import patch
        values = {k: v for k, v in os.environ.items() if k != work.TERMINAL_ENV}
        if handle is not None:
            values[work.TERMINAL_ENV] = handle
        return patch.dict(os.environ, values, clear=True)

    def bind(self, terminal=None, task='example.work'):
        return work.bind(self.vault, self.key, self.root, task, terminal)['sessions'][0]

    def link(self):
        row = work.status(self.vault, self.key)['sessions'][0]
        return row['terminal'], row['terminal_source']

    def test_old_schema_migrates_idempotently_and_preserves_rows(self):
        import sqlite3
        from contextlib import closing
        path = self.vault / '.local/harness/hook-state.sqlite'
        with closing(sqlite3.connect(path)) as db, db:
            db.execute('CREATE TABLE sessions (id TEXT PRIMARY KEY, revision TEXT NOT NULL, dirty INTEGER NOT NULL DEFAULT 0, retries INTEGER NOT NULL DEFAULT 0, failure TEXT, verdict TEXT, evidence TEXT)')
            db.execute('CREATE TABLE work_sessions (id TEXT PRIMARY KEY, workspace TEXT NOT NULL, project TEXT NOT NULL, task TEXT, task_path TEXT, task_hash TEXT, handoff_hash TEXT)')
            db.execute('CREATE TABLE work_calls (id INTEGER PRIMARY KEY, session TEXT NOT NULL, tool TEXT NOT NULL, before_state TEXT NOT NULL, targets TEXT, task_hash TEXT, handoff_hash TEXT, state TEXT NOT NULL, changes TEXT, ambiguous INTEGER NOT NULL DEFAULT 0, reconciliation TEXT, reconciled_state TEXT, UNIQUE(session,tool))')
            db.execute("INSERT INTO sessions(id,revision) VALUES ('s','r')")
            db.execute("INSERT INTO work_sessions VALUES ('codex:old','/w','p','t','tp','th','hh')")
            db.execute("INSERT INTO work_calls(session,tool,before_state,state) VALUES ('codex:old','x','{}','changed')")

        def snapshot():
            with closing(sqlite3.connect(path)) as db:
                return {t: db.execute(f'SELECT * FROM {t} ORDER BY 1').fetchall()
                        for t in ('sessions', 'work_sessions', 'work_calls')}, \
                       [r[1] for r in db.execute('PRAGMA table_info(work_sessions)')]
        before, _ = snapshot()
        for _ in range(2):
            work.database(self.vault).close()
        after, columns = snapshot()
        self.assertEqual(columns, ['id', 'workspace', 'project', 'task', 'task_path', 'task_hash',
                                   'handoff_hash', 'terminal', 'terminal_source'])
        self.assertEqual(after['sessions'], before['sessions'])
        self.assertEqual(after['work_calls'], before['work_calls'])
        self.assertEqual([row[:7] for row in after['work_sessions']], before['work_sessions'])
        self.assertEqual([row[7:] for row in after['work_sessions']], [(None, None)])

    def test_explicit_terminal_wins_over_env(self):
        with self.env('term_env'):
            row = self.bind('tmux:%3')
        self.assertEqual((row['terminal'], row['terminal_source']), ('tmux:%3', 'explicit'))

    def test_env_handle_is_recorded_with_orca_prefix(self):
        with self.env('term_abc'):
            row = self.bind()
        self.assertEqual((row['terminal'], row['terminal_source']), ('orca:term_abc', 'env'))

    def test_no_value_leaves_terminal_unknown_or_unchanged(self):
        with self.env():
            self.bind()
            self.assertEqual(self.link(), (None, None))
        with self.env('term_a'):
            self.bind()
        with self.env():
            self.bind()
        self.assertEqual(self.link(), ('orca:term_a', 'env'))

    def test_rebind_updates_terminal_when_new_value_supplied(self):
        with self.env('term_a'):
            self.bind()
            self.bind('manual-1')
            self.assertEqual(self.link(), ('manual-1', 'explicit'))
        with self.env('term_b'):
            self.bind()
        self.assertEqual(self.link(), ('orca:term_b', 'env'))
        other = self.task.with_name('other.md')
        other.write_text('---\nid: example.other\nstatus: active\n---\n# Other\n## Current Result\nR\n## Next Action\nN')
        with self.env('term_c'):
            row = self.bind(task='example.other')
        self.assertEqual((row['task'], row['terminal']), ('example.other', 'orca:term_c'))

    def test_invalid_terminal_is_rejected_without_creating_a_session(self):
        for value in ('', 'a b', 'tab\there', 'x' * (work.TERMINAL_LIMIT + 1), 'nl\n'):
            with self.env(), self.assertRaises(ValueError):
                self.bind(value)
        with self.env('bad handle'), self.assertRaisesRegex(ValueError, 'ORCA_TERMINAL_HANDLE'):
            self.bind()
        self.assertEqual(work.status(self.vault)['sessions'], [])

    def test_existing_bind_rules_still_apply_with_terminal(self):
        with self.env('term_a'):
            self.bind()
            self.begin()
            other = self.task.with_name('other.md')
            other.write_text('---\nid: example.other\nstatus: active\n---\n# Other')
            with self.assertRaisesRegex(ValueError, 'unfinished'):
                self.bind('manual', task='example.other')
        self.assertEqual(self.link(), ('orca:term_a', 'env'))
        elsewhere = self.root / 'elsewhere'
        elsewhere.mkdir()
        subprocess.run(['git', '-C', str(elsewhere), 'init', '-q'], check=True, env=git_environment())
        with self.assertRaisesRegex(ValueError, 'worktrees'):
            work.bind(self.vault, self.key, elsewhere, 'example.work', 'manual')

    def test_session_created_by_observation_captures_own_handle(self):
        with self.env('term_hook'):
            self.begin()
        self.assertEqual(self.link(), ('orca:term_hook', 'env'))
        with self.env('bad handle'):
            self.begin(tool='two', key='codex:two')
        row = work.status(self.vault, 'codex:two')['sessions'][0]
        self.assertEqual((row['terminal'], row['terminal_source']), (None, None))

    def test_cli_bind_and_status_expose_terminal(self):
        import sys
        base = [sys.executable, '-m', 'harness', '--root', str(self.vault), 'work']
        identity = ['--agent', 'codex', '--session', 'one']
        env = {k: v for k, v in os.environ.items() if k != work.TERMINAL_ENV}
        env[work.TERMINAL_ENV] = 'term_cli'
        result = subprocess.run(base + ['bind', str(self.root), '--task', 'example.work'] + identity,
                                capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run(base + ['status'] + identity, capture_output=True, text=True, env=env)
        session = json.loads(result.stdout)['sessions'][0]
        self.assertEqual((session['terminal'], session['terminal_source']), ('orca:term_cli', 'env'))
        result = subprocess.run(base + ['bind', str(self.root), '--task', 'example.work', '--terminal', 'pts/4'] + identity,
                                capture_output=True, text=True, env=env)
        session = json.loads(result.stdout)['sessions'][0]
        self.assertEqual((session['terminal'], session['terminal_source']), ('pts/4', 'explicit'))
        result = subprocess.run(base + ['bind', str(self.root), '--task', 'example.work', '--terminal', 'a b'] + identity,
                                capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, 1)
        self.assertIn('--terminal', json.loads(result.stderr)['error'])


class WorkRecoveryMatrixTests(unittest.TestCase):
    setUp = WorkRecordTests.setUp
    git = WorkRecordTests.git
    bind = WorkRecordTests.bind
    begin = WorkRecordTests.begin
    finish = WorkRecordTests.finish
    record = WorkRecordTests.record

    def test_explicit_ignored_edit_is_recorded_and_drift_checked(self):
        from unittest.mock import patch
        (self.root / '.gitignore').write_text('vault/\n.artifacts/\n')
        folder = self.root / '.artifacts'
        folder.mkdir()
        target = folder / 'fixture.py'
        target.write_text('before')
        self.bind()
        self.begin(selected=('.artifacts/fixture.py',))
        target.write_text('after')
        self.finish()
        self.assertIn('work-unrecorded', work.status(self.vault, self.key)['issues'])
        self.task.write_text(self.task.read_text() + '\nVerified ignored fixture; next done')
        target.write_text('unobserved drift')
        with self.assertRaisesRegex(ValueError, 'drift'):
            self.record()
        target.write_text('after')
        result = self.record()
        receipt = json.loads((self.vault / result['evidence']).read_text())
        self.assertEqual(result['recorded'], 1)
        self.assertEqual(set(receipt['observations'][0]['changes']), {'.artifacts/fixture.py'})

    def test_noop_explains_scope_and_does_not_claim_no_changes_anywhere(self):
        self.bind()
        self.begin()
        self.finish()
        result = self.record()
        self.assertEqual(result['recorded'], 0)
        self.assertEqual(result['reason'], 'no_unrecorded_observations')
        self.assertIn('ignored', result['scope'])

    def test_disjoint_concurrent_calls_keep_separate_receipts(self):
        self.bind()
        self.bind('claude:two')
        other = self.root / 'other.py'
        other.write_text('initial')
        self.begin()
        self.begin(key='claude:two', selected=('other.py',))
        self.code.write_text('A')
        other.write_text('B')
        self.finish()
        self.finish(key='claude:two')
        self.task.write_text(self.task.read_text() + '\nBoth file results verified')
        a = self.record()
        self.assertIn('work-unrecorded', work.status(self.vault, 'claude:two')['issues'])
        b = work.record(self.vault, 'claude:two', 'wiki/log/result.md')
        for result, key, file in ((a, self.key, 'code.py'), (b, 'claude:two', 'other.py')):
            receipt = json.loads((self.vault / result['evidence']).read_text())
            self.assertEqual(receipt['session'], key)
            self.assertEqual(set(receipt['observations'][0]['changes']), {file})
            self.assertFalse(receipt['observations'][0]['ambiguous'])

    def test_receipt_failure_preserves_obligation_and_retry_records_once(self):
        from unittest.mock import patch
        self.bind()
        self.begin()
        self.code.write_text('real change')
        self.finish()
        self.task.write_text(self.task.read_text() + '\nVerified change and resume record')
        with patch.object(work, 'write_receipt', side_effect=OSError('injected record interruption')):
            with self.assertRaises(OSError):
                self.record()
        self.assertIn('work-unrecorded', work.status(self.vault, self.key)['issues'])
        result = self.record()
        self.assertEqual(result['recorded'], 1)
        retry = self.record()
        self.assertEqual(retry['recorded'], 0)
        self.assertEqual(len(list((self.vault / 'wiki/log').glob('*/record.json'))), 1)

    def test_process_dies_after_write_successor_sees_and_recovers(self):
        self.bind()
        script = (
            'from pathlib import Path; import os; from harness import work; '
            f'root=Path({str(self.vault)!r}); workspace=Path({str(self.root)!r}); '
            f'work.begin(root, {self.key!r}, "crashed", workspace, ["code.py"]); '
            '(workspace / "code.py").write_text("persisted before crash"); os._exit(17)'
        )
        import sys
        child = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True)
        self.assertEqual(child.returncode, 17, child.stderr)
        from harness.context import context
        successor = context(self.vault, self.root, 'example.work')
        self.assertTrue(any(c['session'] == self.key and c['state'] == 'pending'
                            for c in successor['unfinished_work']))
        self.assertEqual(work.status(self.vault, 'codex:successor')['issues'], [])
        with self.assertRaisesRegex(ValueError, 'pending'):
            self.record()
        work.reconcile(self.vault, self.key, 'crashed', 'Child exited 17; bytes inspected')
        self.task.write_text(self.task.read_text() + '\nRecovered persisted bytes; next record')
        result = self.record(reconciliation='Child exit and persisted bytes verified')
        receipt = json.loads((self.vault / result['evidence']).read_text())
        self.assertEqual(receipt['session'], self.key)
        self.assertEqual(receipt['observations'][0]['changes']['code.py']['after'], manifest(self.root)['code.py'])


    def test_crash_after_receipt_write_does_not_commit_completion(self):
        import sys
        self.bind()
        self.begin()
        self.code.write_text('changed before receipt')
        self.finish()
        self.task.write_text(self.task.read_text() + '\nVerified change; finish record')
        script = f"""from pathlib import Path
import os
from harness import work
original = work.write_receipt
def interrupted(root, payload):
    original(root, payload)
    os._exit(19)
work.write_receipt = interrupted
work.record(Path({str(self.vault)!r}), {self.key!r}, 'wiki/log/result.md')
"""
        child = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True)
        self.assertEqual(child.returncode, 19, child.stderr)
        self.assertIn('work-unrecorded', work.status(self.vault, self.key)['issues'])
        # A receipt file alone is not a committed record: SQLite rolled back.
        self.assertEqual(len(list((self.vault / 'wiki/log').glob('*/record.json'))), 1)
        result = self.record()
        self.assertEqual(result['recorded'], 1)
        self.assertEqual(work.status(self.vault, self.key)['issues'], [])
        self.assertEqual(self.record()['recorded'], 0)

    def test_two_processes_record_disjoint_changes_without_cross_attribution(self):
        from contextlib import ExitStack
        import sys
        self.bind()
        self.bind('claude:two')
        (self.root / 'other.py').write_text('initial')
        with ExitStack() as stack:
            children = []
            for key, name in ((self.key, 'code.py'), ('claude:two', 'other.py')):
                script = f"""from pathlib import Path
import sys
from harness import work
root = Path({str(self.vault)!r})
workspace = Path({str(self.root)!r})
work.begin(root, {key!r}, 'parallel', workspace, [{name!r}])
print('ready', flush=True)
sys.stdin.readline()
(workspace / {name!r}).write_text({key!r})
work.finish(root, {key!r}, 'parallel')
"""
                child = stack.enter_context(subprocess.Popen([sys.executable, '-c', script],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
                children.append(child)
            for child in children:
                self.assertEqual(child.stdout.readline().strip(), 'ready')
            for child in children:
                child.stdin.write('go\n')
                child.stdin.flush()
            for child in children:
                _, stderr = child.communicate(timeout=10)
                self.assertEqual(child.returncode, 0, stderr)
        self.task.write_text(self.task.read_text() + '\nBoth child processes completed; verify records')
        for key, name in ((self.key, 'code.py'), ('claude:two', 'other.py')):
            result = work.record(self.vault, key, 'wiki/log/result.md')
            receipt = json.loads((self.vault / result['evidence']).read_text())
            self.assertEqual(receipt['session'], key)
            self.assertEqual(set(receipt['observations'][0]['changes']), {name})
            self.assertFalse(receipt['observations'][0]['ambiguous'])
