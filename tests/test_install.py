"""Check that installer consent precedes all user-file changes."""
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('stash_installer', ROOT / 'tools/install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallerConsentTests(unittest.TestCase):
    def test_noninteractive_install_and_removal_do_not_write_without_consent(self):
        for arguments in ([], ['--uninstall']):
            with self.subTest(arguments=arguments), tempfile.TemporaryDirectory() as directory:
                home = Path(directory)
                env = dict(os.environ, HOME=directory, XDG_CONFIG_HOME=str(home / '.config'),
                           XDG_STATE_HOME=str(home / '.local/state'), PYTHONDONTWRITEBYTECODE='1')
                result = subprocess.run([sys.executable, str(ROOT / 'tools/install.py'), *arguments],
                                        cwd=directory, env=env, stdin=subprocess.DEVNULL,
                                        capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('pass --yes', result.stderr)
                self.assertEqual(list(home.iterdir()), [])

    def test_declining_confirmation_aborts(self):
        paths = [Path('unused') for _ in range(5)]
        with patch.object(sys, 'stdin') as stdin, patch('builtins.input', return_value='n'), \
                patch.object(sys, 'stderr', io.StringIO()):
            stdin.isatty.return_value = True
            with self.assertRaisesRegex(RuntimeError, 'Cancelled; no files changed'):
                installer.confirm_changes(*paths, False, False)

    def test_explicit_yes_does_not_require_terminal_or_prompt(self):
        paths = [Path('unused') for _ in range(5)]
        with patch('builtins.input', side_effect=AssertionError('Unexpected prompt')), \
                patch.object(sys, 'stderr', io.StringIO()):
            installer.confirm_changes(*paths, False, True)


if __name__ == '__main__':
    unittest.main()
