"""Shortcut persistence/conflicts and isolated Lua handle ownership."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'controller'))
import shortcuts


class FakeIPC:
    def __init__(self, binds=(), owned=()):
        self.binds = list(binds)
        self.owned = list(owned)
        self.calls = []
        self.apply_error = None
        self.on_apply = None

    def __call__(self, *args):
        self.calls.append(args)
        if args[0] == 'repl':
            return json.dumps(self.owned)
        if args[0] == 'binds':
            return json.dumps(self.binds)
        if self.on_apply:
            self.on_apply()
        return self.apply_error or 'ok'


def binding(key='A', mods=64, description='Other action', arg='17', **extra):
    result = dict(key=key, modmask=mods, dispatcher='__lua', arg=arg, description=description, submap='')
    result.update(extra)
    return result


class ShortcutTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.config = Path(self.directory.name)/'shell.json'
        self.original = {'bar': {'position': 'top'}, 'plugins': [
            {'id': 'other.plugin', 'secretPlaceholder': 'unchanged'},
            {'id': shortcuts.PLUGIN, 'presentation': 'floating', 'previewDelay': 321}]}
        self.config.write_text(json.dumps(self.original))

    def test_normalization_supports_common_keys_aliases_and_disabled(self):
        for text, expected in [('shift + meta + control + a', 'SUPER + CTRL + SHIFT + A'),
                               ('alt+f24', 'ALT + F24'), ('win + Enter', 'SUPER + Return'),
                               ('ctrl+PgDn', 'CTRL + Page_Down'), ('SUPER + /', 'SUPER + slash'),
                               ('SHIFT + plus', 'SHIFT + plus'), ('KP_1', 'KP_1'),
                               ('XF86AudioMute', 'XF86AudioMute'), ('  ', '')]:
            self.assertEqual(shortcuts.normalize(text), expected)
        for text in (None, True, 5, 'SUPER', 'CTRL+CTRL+A', 'SUPER+A+B', 'SUPER++A', 'ALT+F25',
                     'mouse:272', 'code:38', 'SUPER + not-a-key', 'SUPER + A\n',
                     'SUPER + A"; error("x")', 'SUPER + é', 'SUPER + '+('A'*97)):
            with self.subTest(text=text), self.assertRaises(ValueError):
                shortcuts.normalize(text)

    def test_legacy_defaults_and_explicit_disabled_are_preserved(self):
        self.assertEqual(shortcuts.settings({}), shortcuts.DEFAULT_SHORTCUTS)
        self.assertEqual(shortcuts.settings({'minimizeShortcut': '', 'restoreLastShortcut': 'ctrl+z',
                                             'restoreOldestShortcut': False}),
                         {'minimizeShortcut': '', 'restoreLastShortcut': 'CTRL + Z', 'restoreOldestShortcut': ''})
        self.assertEqual(shortcuts.settings({'minimizeShortcut': None})['minimizeShortcut'], 'SUPER + A')

    def test_duplicate_or_foreign_conflicts_do_not_change_settings_or_apply(self):
        before = self.config.read_bytes()
        cases = [('restoreOldestShortcut', 'SUPER+Z', FakeIPC()),
                 ('restoreOldestShortcut', 'ALT+F2', FakeIPC([binding('F2', 8)])),
                 ('minimizeShortcut', 'SUPER+A', FakeIPC([binding(description='Window Stash: pretend')]))]
        for key, value, ipc in cases:
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'already'):
                shortcuts.configure(self.config, key, value, ipc)
            self.assertEqual(self.config.read_bytes(), before)
            self.assertFalse(any(args[0] == 'eval' for args in ipc.calls))

    def test_ownership_requires_exact_handles_and_consumes_only_one_duplicate(self):
        owned = binding(description='Window Stash: minimize focused window')
        self.assertEqual(shortcuts.validate(shortcuts.DEFAULT_SHORTCUTS, [owned], [owned]), shortcuts.DEFAULT_SHORTCUTS)
        for changed in ({'arg': '18'}, {'description': 'Changed'}, {'dispatcher': 'exec'}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                shortcuts.validate(shortcuts.DEFAULT_SHORTCUTS, [dict(owned, **changed)], [owned])
        with self.assertRaises(ValueError):
            shortcuts.validate(shortcuts.DEFAULT_SHORTCUTS, [owned, copy.deepcopy(owned)], [owned])

    def test_context_specific_and_explicit_disabled_foreign_bindings(self):
        values = shortcuts.DEFAULT_SHORTCUTS
        for foreign in (binding(enabled=False), binding(disabled=True), binding(submap='resize')):
            self.assertEqual(shortcuts.validate(values, [foreign]), values)
        with self.assertRaises(ValueError):
            shortcuts.validate(values, [binding(submap='resize', submap_universal='true')])

    def test_success_merges_only_target_setting_and_returns_canonical_value(self):
        ipc = FakeIPC()
        result = shortcuts.configure(self.config, 'restoreOldestShortcut', 'alt + shift + f2', ipc)
        expected = copy.deepcopy(self.original)
        expected['plugins'][1]['restoreOldestShortcut'] = 'ALT + SHIFT + F2'
        self.assertEqual(json.loads(self.config.read_text()), expected)
        self.assertEqual(result['key'], 'restoreOldestShortcut')
        self.assertEqual(result['binding'], 'ALT + SHIFT + F2')
        self.assertTrue(result['ok'])
        self.assertEqual([args[0] for args in ipc.calls], ['repl', 'binds', 'eval'])
        self.assertIn("('runtime')", ipc.calls[-1][1])

    def test_conflicts_recheck_under_the_shared_lock_and_serialize_bootstrap(self):
        ipc = FakeIPC()
        with patch.object(shortcuts, '_locked', wraps=shortcuts._locked) as lock:
            shortcuts.configure(self.config, 'restoreOldestShortcut', 'ALT+F2', ipc)
            shortcuts.sync(self.config, ipc)
            shortcuts.disable(self.config, ipc)
        self.assertEqual(lock.call_count, 3)
        self.assertTrue((self.config.parent/'.window-stash-shortcuts.lock').exists())
        self.assertIn('m.disable()', ipc.calls[-1][1])

    def test_apply_failure_never_persists_new_value(self):
        before = self.config.read_bytes()
        ipc = FakeIPC()
        ipc.apply_error = 'error: failed to create binding'
        with self.assertRaisesRegex(RuntimeError, 'failed to create'):
            shortcuts.configure(self.config, 'restoreOldestShortcut', 'ALT+F2', ipc)
        self.assertEqual(self.config.read_bytes(), before)

    def test_persist_failure_restores_previous_runtime_shortcuts(self):
        ipc = FakeIPC()
        before = self.config.read_bytes()
        with patch.object(shortcuts, '_atomic_json', side_effect=OSError('disk unavailable')):
            with self.assertRaises(OSError):
                shortcuts.configure(self.config, 'restoreOldestShortcut', 'ALT+F2', ipc)
        self.assertEqual(self.config.read_bytes(), before)
        applies = [args[1] for args in ipc.calls if args[0] == 'eval']
        self.assertEqual(len(applies), 2)
        self.assertIn('restoreOldestShortcut="ALT + F2"', applies[0])
        self.assertIn('restoreOldestShortcut=""', applies[1])

    def test_unrelated_setting_edit_during_ipc_is_merged(self):
        ipc = FakeIPC()
        def unrelated_edit():
            data = json.loads(self.config.read_text())
            data['plugins'][0]['otherSetting'] = 7
            data['plugins'][1]['iconOpacity'] = 72
            self.config.write_text(json.dumps(data))
        ipc.on_apply = unrelated_edit
        shortcuts.configure(self.config, 'restoreOldestShortcut', 'ALT+F2', ipc)
        result = json.loads(self.config.read_text())
        self.assertEqual(result['plugins'][0]['otherSetting'], 7)
        self.assertEqual(result['plugins'][1]['iconOpacity'], 72)
        self.assertEqual(result['plugins'][1]['restoreOldestShortcut'], 'ALT + F2')

    def test_read_only_export_never_uses_ipc_or_changes_files(self):
        before = self.config.read_bytes()
        result = subprocess.run([sys.executable, str(ROOT/'controller/shortcuts.py'), 'export', str(self.config)],
                                text=True, capture_output=True, env=dict(os.environ, PATH='', PYTHONDONTWRITEBYTECODE='1'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.startswith('return {'))
        self.assertIn('restoreOldestShortcut=""', result.stdout)
        self.assertEqual(self.config.read_bytes(), before)
        self.assertEqual([p.name for p in self.config.parent.iterdir()], ['shell.json'])

    @unittest.skipUnless(shutil.which('lua'), 'Standalone Lua interpreter unavailable')
    def test_exact_lua_handles_reuse_disable_failure_and_async_bootstrap(self):
        script = r'''
local all, timers, executions = {}, {}, {}
local fail
hl = { dsp = { exec_cmd = function(command) return command end } }
function hl.bind(chord, dispatcher, options)
  if chord == fail then error('mock registration failed') end
  local handle = { key = chord:match('([^+]+)$'):match('^%s*(.-)%s*$'), modmask = 64,
    description = options.description, handler = '__lua', arg = tostring(#all + 1), submap = '', enabled = true }
  function handle:set_enabled(value) self.enabled = value end
  function handle:is_enabled() if self.expired then return nil end; return self.enabled end
  all[#all + 1] = handle
  return handle
end
function hl.timer(callback, options) timers[#timers + 1] = { callback, options }; return {} end
function hl.exec_cmd(command) executions[#executions + 1] = command end
local foreign = hl.bind('SUPER + A', 'foreign', {description='Foreign binding'})
local module = assert(loadfile(arg[1]))('runtime')
assert(#timers == 0)
local defaults = {minimizeShortcut='SUPER + A',restoreLastShortcut='SUPER + Z',restoreOldestShortcut=''}
module.apply(defaults, "/tmp/it's stash")
assert(#all == 3 and foreign.enabled)
assert(all[2].enabled and all[3].enabled)
local last = all[3]
module.apply({minimizeShortcut='CTRL + X',restoreLastShortcut='SUPER + Z',restoreOldestShortcut='ALT + F2'}, '/tmp/stash')
assert(not all[2].enabled and foreign.enabled)
assert(#all == 6) -- Binary changes deliberately create independent dispatchers.
local count = #all
module.apply({minimizeShortcut='',restoreLastShortcut='SUPER + Z',restoreOldestShortcut=''}, '/tmp/stash')
module.apply({minimizeShortcut='CTRL + X',restoreLastShortcut='SUPER + Z',restoreOldestShortcut='ALT + F2'}, '/tmp/stash')
assert(#all == count)
local states = {}
for i, h in ipairs(all) do states[i] = h.enabled end
fail = 'CTRL + F9'
local ok = pcall(module.apply, {minimizeShortcut='CTRL + F8',restoreLastShortcut=fail,restoreOldestShortcut=''}, '/tmp/stash')
assert(not ok and #all == count + 1 and not all[#all].enabled)
for i=1,count do assert(all[i].enabled == states[i]) end
module.disable()
assert(foreign.enabled)
for i=2,#all do assert(not all[i].enabled) end
print(module.inspect())
assert(loadfile(arg[1]))()
assert(#timers == 1 and timers[1][2].timeout == 50 and timers[1][2].type == 'oneshot')
assert(#executions == 0)
timers[1][1]()
assert(#executions == 1 and executions[1]:find('python3 ',1,true) == 1)
assert(executions[1]:find(' sync ',1,true))
'''
        path = Path(self.directory.name)/'test.lua'
        path.write_text(script)
        result = subprocess.run(['lua', str(path), str(ROOT/'controller/shortcuts.lua')], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        owned = json.loads(result.stdout)
        self.assertEqual(len(owned), 6)
        self.assertTrue(all(not entry['enabled'] for entry in owned))
        self.assertTrue(all(entry['description'].startswith('Window Stash:') for entry in owned))


if __name__ == '__main__':
    unittest.main()
