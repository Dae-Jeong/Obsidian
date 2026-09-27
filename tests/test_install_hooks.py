import json
from pathlib import Path
import tempfile
import unittest

from harness.install_hooks import install, merged


class InstallHookTests(unittest.TestCase):
    def test_orca_and_other_settings_survive_and_repeat_is_identical(self):
        original = {'preferences': {'untouched': True}, 'hooks': {'PreToolUse': [
            {'matcher': '*', 'hooks': [{'type': 'command', 'command': 'orca-hook', 'timeout': 10}]}
        ]}}
        for agent in ('codex', 'claude'):
            result = merged(original, '/central/python /central/hooks.py --agent ' + agent, agent)
            self.assertEqual(result['hooks']['PreToolUse'][0], original['hooks']['PreToolUse'][0])
            self.assertEqual(result['preferences'], original['preferences'])
            self.assertEqual(merged(result, '/central/python /central/hooks.py --agent ' + agent, agent), result)

    def test_installer_preserves_full_config_and_is_idempotent(self):
        import sys
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            vault, home = base / 'vault', base / 'home'
            (vault / 'harness').mkdir(parents=True)
            (vault / 'harness/hooks.py').write_text('# fixture')
            target = home / '.claude/settings.json'
            target.parent.mkdir(parents=True)
            before = b'{"custom":true,"hooks":{}}\n'
            target.write_bytes(before)
            result = install(vault, home, Path(sys.executable))
            self.assertEqual((vault / result['record'] / 'before/machine/claude.json').read_bytes(), before)
            self.assertFalse(install(vault, home, Path(sys.executable))['changed'])
