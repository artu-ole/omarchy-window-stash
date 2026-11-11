"""Confirmed, transactional preference reset without touching parked windows."""
import copy
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'controller'))
import shortcuts
import stash


class FakeIPC:
    def __init__(self, bindings=(), owned=()):
        self.bindings = list(bindings)
        self.owned = list(owned)
        self.calls = []
        self.on_apply = None
        self.apply_error = None

    def __call__(self, *args):
        self.calls.append(args)
        if args[0] == 'repl':
            return json.dumps(self.owned)
        if args[0] == 'binds':
            return json.dumps(self.bindings)
        if self.on_apply:
            self.on_apply()
        return self.apply_error or 'ok'

    @property
    def applies(self):
        return [args[1] for args in self.calls if args[0] == 'eval']


def binding(key='D', arg='17'):
    return dict(key=key, modmask=64, dispatcher='__lua', arg=arg,
                description='Window Stash: minimize focused window', submap='')


class ResetSettingsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.config = self.root/'shell.json'
        entry = {key: next(value for value in reversed(list(stash.CHOICES[key])) if value != default)
                 for key, default in stash.DEFAULTS.items() if key not in shortcuts.DEFAULT_SHORTCUTS}
        entry.update(id=shortcuts.PLUGIN, enabled=False, hostMetadata={'keep': True},
                     minimizeShortcut='ALT + F8', restoreLastShortcut='ALT + F9', restoreOldestShortcut='ALT + F10')
        self.original = {'bar': {'position': 'top'}, 'plugins': [
            {'id': 'other.plugin', 'setting': 7}, entry]}
        self.config.write_text(json.dumps(self.original))
        self.config.chmod(0o640)
        self.state = self.root/'state.json'
        self.state.write_text(json.dumps({'version': 1, 'windows': [{'id': 'parked-window'}]}))
        self.positions = self.root/'positions.json'
        self.positions.write_text(json.dumps({'output': {'window:parked-window': [321, 234],
                                                        'preview:window:parked-window': [120,200,380]}}))
        self.before_state = self.state.read_bytes()
        self.before_positions = self.positions.read_bytes()

    def read(self):
        return json.loads(self.config.read_text())

    def reset(self, ipc):
        return shortcuts.reset_settings(self.config, stash.DEFAULTS, ipc, binary=self.root/'window-stash')

    def assert_preserved_windows(self):
        self.assertEqual(self.state.read_bytes(), self.before_state)
        self.assertEqual(self.positions.read_bytes(), self.before_positions)

    def test_all_canonical_defaults_reset_together_preserving_host_metadata_and_permissions(self):
        ipc = FakeIPC()
        with patch.object(shortcuts, '_locked', wraps=shortcuts._locked) as lock:
            result = self.reset(ipc)
        expected = copy.deepcopy(self.original)
        expected['plugins'][1].update(stash.DEFAULTS)
        self.assertEqual(self.read(), expected)
        self.assertEqual(result, dict(ok=True, action='settings-reset', settings=stash.DEFAULTS,
                                     shortcuts=shortcuts.DEFAULT_SHORTCUTS))
        self.assertEqual(lock.call_count, 1)
        self.assertEqual([args[0] for args in ipc.calls], ['repl', 'binds', 'eval'])
        self.assertIn('minimizeShortcut="SUPER + D"', ipc.applies[0])
        self.assertIn('restoreLastShortcut="SUPER + Z"', ipc.applies[0])
        self.assertIn('restoreOldestShortcut="SUPER + ALT + Z"', ipc.applies[0])
        self.assertEqual(stat.S_IMODE(self.config.stat().st_mode), 0o640)
        self.assertEqual(list(self.root.glob('.window-stash-shortcuts-*')), [])
        self.assert_preserved_windows()

    def test_reset_without_confirmation_never_constructs_ledger_calls_ipc_or_writes(self):
        before = {path.name: path.read_bytes() for path in self.root.iterdir()}
        with patch.dict(os.environ, XDG_CONFIG_HOME=str(self.root)), \
             patch.object(stash, 'Stash', side_effect=AssertionError('Ledger must not be constructed')), \
             patch.object(shortcuts, 'reset_settings') as reset, \
             patch.object(shortcuts, '_run') as ipc, redirect_stdout(io.StringIO()) as output:
            self.assertEqual(stash.main(['reset-settings']), 1)
        self.assertFalse(json.loads(output.getvalue())['ok'])
        self.assertIn('--confirm', output.getvalue())
        reset.assert_not_called()
        ipc.assert_not_called()
        self.assertEqual({path.name: path.read_bytes() for path in self.root.iterdir()}, before)

    def test_confirmed_cli_uses_reset_transaction_without_a_ledger_or_window_calls(self):
        expected = dict(ok=True, action='settings-reset', settings=stash.DEFAULTS,
                        shortcuts=shortcuts.DEFAULT_SHORTCUTS)
        with patch.object(stash, 'Stash', side_effect=AssertionError('Ledger must not be constructed')), \
             patch.object(shortcuts, 'reset_settings', return_value=expected) as reset, \
             redirect_stdout(io.StringIO()) as output:
            self.assertEqual(stash.main(['reset-settings', '--confirm']), 0)
        reset.assert_called_once_with(None, stash.DEFAULTS)
        self.assertEqual(json.loads(output.getvalue()), expected)
        self.assert_preserved_windows()

    def test_foreign_or_duplicate_default_binding_conflict_leaves_settings_and_runtime_unchanged(self):
        before = self.config.read_bytes()
        owned = binding()
        for ipc in (FakeIPC([owned]), FakeIPC([owned, owned], [owned])):
            with self.subTest(bindings=ipc.bindings), self.assertRaisesRegex(ValueError, 'already assigned'):
                self.reset(ipc)
            self.assertEqual(self.config.read_bytes(), before)
            self.assertEqual(ipc.applies, [])
        self.assert_preserved_windows()

    def test_exact_owned_default_handles_are_reused_without_being_treated_as_conflicts(self):
        owned = binding()
        ipc = FakeIPC([owned], [owned])
        self.reset(ipc)
        self.assertEqual(len(ipc.applies), 1)
        self.assertEqual({key: self.read()['plugins'][1][key] for key in stash.DEFAULTS}, stash.DEFAULTS)

    def test_apply_failure_never_writes_preferences(self):
        before = self.config.read_bytes()
        ipc = FakeIPC()
        ipc.apply_error = 'Failed to create managed shortcut'
        with patch.object(shortcuts, '_atomic_json') as persist, \
             self.assertRaisesRegex(RuntimeError, 'Failed to create'):
            self.reset(ipc)
        persist.assert_not_called()
        self.assertEqual(len(ipc.applies), 1)
        self.assertEqual(self.config.read_bytes(), before)
        self.assert_preserved_windows()

    def test_persist_failure_rolls_back_every_previous_shortcut(self):
        before = self.config.read_bytes()
        ipc = FakeIPC()
        with patch.object(shortcuts, '_atomic_json', side_effect=OSError('disk unavailable')), \
             self.assertRaisesRegex(OSError, 'disk unavailable'):
            self.reset(ipc)
        self.assertEqual(self.config.read_bytes(), before)
        self.assertEqual(len(ipc.applies), 2)
        for key, chord in shortcuts.settings(self.original['plugins'][1]).items():
            self.assertIn(key+'="'+chord+'"', ipc.applies[1])
        self.assert_preserved_windows()

    def test_unrelated_concurrent_edits_merge_without_losing_latest_host_fields(self):
        ipc = FakeIPC()

        def update():
            data = self.read()
            data['bar']['position'] = 'bottom'
            data['plugins'][0]['newSetting'] = 42
            data['plugins'][1]['hostMetadata'] = {'new': 'preserved'}
            data['plugins'][1]['newHostField'] = 'preserved'
            self.config.write_text(json.dumps(data))

        ipc.on_apply = update
        self.reset(ipc)
        data = self.read()
        self.assertEqual(data['bar']['position'], 'bottom')
        self.assertEqual(data['plugins'][0]['newSetting'], 42)
        self.assertEqual(data['plugins'][1]['hostMetadata'], {'new': 'preserved'})
        self.assertEqual(data['plugins'][1]['newHostField'], 'preserved')
        self.assertEqual({key: data['plugins'][1][key] for key in stash.DEFAULTS}, stash.DEFAULTS)
        self.assertEqual(len(ipc.applies), 1)
        self.assert_preserved_windows()

    def test_concurrent_managed_edits_reject_reset_preserve_edit_and_roll_back_bindings(self):
        other_presentation = next(value for value in stash.CHOICES['presentation']
                                  if value != self.original['plugins'][1]['presentation'])
        for key, value in (('presentation', other_presentation), ('minimizeShortcut', 'CTRL + F8'),
                           ('sizePreset', '175'), ('dockOpacity', True)):
            with self.subTest(key=key):
                self.config.write_text(json.dumps(self.original))
                ipc = FakeIPC()

                def update():
                    data = self.read()
                    data['plugins'][1][key] = value
                    self.config.write_text(json.dumps(data))

                ipc.on_apply = update
                with self.assertRaisesRegex(RuntimeError, 'Settings changed'):
                    self.reset(ipc)
                expected = copy.deepcopy(self.original)
                expected['plugins'][1][key] = value
                self.assertEqual(self.read(), expected)
                self.assertEqual(len(ipc.applies), 2)
                self.assertIn('minimizeShortcut="ALT + F8"', ipc.applies[1])
        self.assert_preserved_windows()

    def test_missing_setting_added_during_reset_is_a_concurrent_managed_edit(self):
        data = self.read()
        del data['plugins'][1]['sizePreset']
        self.config.write_text(json.dumps(data))
        ipc = FakeIPC()

        def update():
            data = self.read()
            data['plugins'][1]['sizePreset'] = '100'
            self.config.write_text(json.dumps(data))

        ipc.on_apply = update
        with self.assertRaisesRegex(RuntimeError, 'Settings changed'):
            self.reset(ipc)
        self.assertEqual(self.read()['plugins'][1]['sizePreset'], '100')
        self.assertEqual(len(ipc.applies), 2)

    def test_boolean_numeric_edit_is_not_confused_with_an_equal_integer(self):
        data = self.read()
        data['plugins'][1]['dockOpacity'] = 1
        self.config.write_text(json.dumps(data))
        ipc = FakeIPC()

        def update():
            data = self.read()
            data['plugins'][1]['dockOpacity'] = True
            self.config.write_text(json.dumps(data))

        ipc.on_apply = update
        with self.assertRaisesRegex(RuntimeError, 'Settings changed'):
            self.reset(ipc)
        self.assertIs(self.read()['plugins'][1]['dockOpacity'], True)
        self.assertEqual(len(ipc.applies), 2)

    def test_rollback_failure_reports_both_the_original_and_restore_error(self):
        ipc = FakeIPC()
        outputs = iter(['ok', 'previous shortcut restore failed'])
        ipc.on_apply = lambda: setattr(ipc, 'apply_error', next(outputs))
        with patch.object(shortcuts, '_atomic_json', side_effect=OSError('disk unavailable')), \
             self.assertRaisesRegex(RuntimeError, 'disk unavailable.*restore previous shortcuts.*restore failed'):
            self.reset(ipc)
        self.assertEqual(len(ipc.applies), 2)
        self.assertEqual(self.read(), self.original)


if __name__ == '__main__':
    unittest.main()
