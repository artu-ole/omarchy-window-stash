"""Replacement must prove ownership, drain input and preserve a working bridge."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'controller'))
from bridge import BridgeManager, decode_status
from bridge_runtime import BUSY, bridge_gate

COMMIT = 'a'*40
FINGERPRINT = 'b'*64


def native(version='1.29.0', cooperative=True, **extra):
    result = dict(available=True, protocol=1, version=version, hyprlandHash=COMMIT,
                  owners=0, windows=0, hasPrepare=cooperative, hasCancel=cooperative,
                  hasInteraction=cooperative, inputActive=False, heldButtons=0, heldKeys=0)
    if cooperative:
        result.update(reloadProtocol=1, reloadPending=False, reloadReady=False, pendingButtons=0,
                      pendingKeys=0, fingerprint='c'*64, modulePath='/unset/window-stash-preview.so')
    result.update(extra)
    return result


class FakeHypr:
    def __init__(self):
        self.value = native()
        self.calls = []
        self.locked = False
        self.fail_load = False
        self.fail_build = False
        self.fail_unload = False
        self.wrong_fingerprint = False
        self.author = 'artu-ole'
        self.after_prepare = None

    def read(self, subject):
        if subject == 'version':
            return dict(commit=COMMIT)
        if subject == 'locked':
            return dict(locked=self.locked)
        raise AssertionError(subject)

    def call(self, *args):
        self.calls.append(args)
        if args[0] == 'repl':
            return json.dumps(self.value)
        if args == ('-j', 'plugin', 'list'):
            return json.dumps([dict(name='window-stash-preview', author=self.author, version=self.value.get('version'))])
        if args[:2] == ('plugin', 'unload'):
            if self.fail_unload:
                raise RuntimeError('Unload failed')
            self.value = dict(available=False)
            return 'ok'
        if args[:2] == ('plugin', 'load'):
            path = Path(args[2])
            data = json.loads(path.with_suffix('.so.json').read_text())
            if self.fail_load and data['version'] != '1.29.0':
                raise RuntimeError('Load failed')
            self.value = native(data['version'], fingerprint=data['fingerprint'], modulePath=str(path))
            if self.wrong_fingerprint:
                self.value['fingerprint'] = 'd'*64
            return 'ok'
        raise AssertionError(args)

    def eval(self, code):
        self.calls.append(('eval', code))
        if '.prepare_reload()' in code:
            self.value.update(reloadPending=True, reloadReady=True, owners=0, windows=0, inputActive=False)
            if self.after_prepare:
                self.after_prepare()
        elif '.cancel_reload()' in code:
            self.value.update(reloadPending=False, reloadReady=False)
        else:
            raise AssertionError(code)


class BridgeUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.environment = patch.dict(os.environ, XDG_RUNTIME_DIR=str(self.root/'run'),
                                      HYPRLAND_INSTANCE_SIGNATURE='test', XDG_CACHE_HOME=str(self.root/'cache'))
        self.environment.start()
        self.hypr = FakeHypr()
        self.emitted = []
        self.cancelled = False
        self.manager = BridgeManager(self.hypr, self.emitted.append, lambda: self.cancelled)
        self.old = self.artifact('1.29.0', 'c'*64)
        self.hypr.value['modulePath'] = self.old['path']
        self.builds = 0
        self.manager.build = self.build

    def tearDown(self):
        self.environment.stop()
        self.temporary.cleanup()

    def artifact(self, version, fingerprint):
        path = self.manager.cache/COMMIT/(version+'-'+fingerprint)/'window-stash-preview.so'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'\x7fELF-'+version.encode())
        value = dict(path=str(path), version=version, fingerprint=fingerprint, hyprlandHash=COMMIT, protocol=1)
        path.with_suffix('.so.json').write_text(json.dumps(dict(value, sha256=hashlib.sha256(path.read_bytes()).hexdigest())))
        return value

    def build(self, commit):
        self.assertEqual(commit, COMMIT)
        self.builds += 1
        self.emitted.append(dict(state='building', ok=True))
        if self.hypr.fail_build:
            raise RuntimeError('Compiler failed')
        return self.artifact(self.manager.expected, FINGERPRINT)

    def mutations(self):
        return [call for call in self.hypr.calls if call[0] in ('plugin', 'eval')]

    def test_status_detects_absent_current_and_update_without_mutating(self):
        self.assertEqual(self.manager.status()['state'], 'update-required')
        self.assertTrue(self.manager.status()['canReload'])
        self.hypr.value['version'] = self.manager.expected
        self.assertEqual(self.manager.status()['state'], 'current')
        self.hypr.value['reloadPending'] = True
        self.assertEqual(self.manager.status()['state'], 'update-required')
        self.hypr.value = dict(available=False)
        self.assertEqual(self.manager.status()['state'], 'absent')
        self.assertEqual(self.mutations(), [])

    def test_success_drains_then_loads_exact_immutable_binary_and_verifies_it(self):
        original = Path(self.old['path']).read_bytes()
        result = self.manager.reload()
        self.assertEqual(result['state'], 'ready')
        self.assertEqual(result['previousVersion'], '1.29.0')
        calls = self.mutations()
        self.assertIn('prepare_reload()', calls[0][1])
        self.assertEqual(calls[1], ('plugin', 'unload', self.old['path']))
        self.assertEqual(calls[2], ('plugin', 'load', self.hypr.value['modulePath']))
        self.assertNotEqual(calls[1][2], calls[2][2])
        self.assertEqual(Path(self.old['path']).read_bytes(), original)
        self.assertEqual(self.hypr.value['fingerprint'], FINGERPRINT)
        self.assertEqual([v['state'] for v in self.emitted], ['building', 'stopping', 'loading'])

    def test_current_repeat_needs_no_build_or_mutation(self):
        self.manager.reload()
        self.hypr.calls.clear()
        self.assertEqual(self.manager.reload()['state'], 'ready')
        self.assertEqual(self.builds, 1)
        self.assertEqual(self.mutations(), [])

    def test_failed_build_never_pauses_or_unloads_original(self):
        self.hypr.fail_build = True
        before = copy.deepcopy(self.hypr.value)
        with self.assertRaisesRegex(RuntimeError, 'Compiler failed'):
            self.manager.reload()
        self.assertEqual(self.hypr.value, before)
        self.assertEqual(self.mutations(), [])

    def test_lock_and_cancel_refuse_before_build_or_unload(self):
        for locked, cancelled, message in ((True, False, 'Unlock'), (False, True, 'cancelled')):
            self.hypr.locked, self.cancelled = locked, cancelled
            with self.subTest(locked=locked), self.assertRaisesRegex(RuntimeError, message):
                self.manager.reload()
        self.assertEqual(self.builds, 0)
        self.assertEqual(self.mutations(), [])

    def test_cancellation_after_build_preserves_original(self):
        build = self.manager.build
        def cancel_after_build(commit):
            value = build(commit)
            self.cancelled = True
            return value
        self.manager.build = cancel_after_build
        with self.assertRaisesRegex(RuntimeError, 'cancelled'):
            self.manager.reload()
        self.assertEqual(self.mutations(), [])

    def test_cancellation_after_prepare_resumes_original_without_unload(self):
        self.hypr.after_prepare = lambda: setattr(self, 'cancelled', True)
        with self.assertRaisesRegex(RuntimeError, 'cancelled'):
            self.manager.reload()
        self.assertFalse(self.hypr.value['reloadPending'])
        self.assertTrue(all(call[0] != 'plugin' for call in self.mutations()))

    def test_held_physical_releases_must_drain_before_unload(self):
        def pending():
            self.hypr.value.update(reloadReady=False, pendingKeys=1, pendingButtons=1)
        self.hypr.after_prepare = pending
        with patch('bridge.time.monotonic', side_effect=[0, 6]), self.assertRaisesRegex(RuntimeError, 'Release held'):
            self.manager.reload()
        self.assertFalse(self.hypr.value['reloadPending'])
        self.assertTrue(all(call[0] != 'plugin' for call in self.mutations()))

    def test_release_drain_allows_replacement(self):
        self.hypr.after_prepare = lambda: self.hypr.value.update(reloadReady=False, pendingKeys=1)
        def release(_seconds):
            self.hypr.value.update(reloadReady=True, pendingKeys=0)
        with patch('bridge.time.sleep', side_effect=release):
            self.manager.reload()
        self.assertEqual(self.hypr.value['version'], self.manager.expected)

    def test_unacknowledged_fullscreen_cleanup_preserves_native_with_specific_error(self):
        self.hypr.after_prepare = lambda: self.hypr.value.update(reloadReady=False, pendingFullscreen=1)
        with patch('bridge.time.monotonic', side_effect=[0, 6]), self.assertRaisesRegex(RuntimeError, 'leaving preview fullscreen'):
            self.manager.reload()
        self.assertFalse(self.hypr.value['reloadPending'])
        self.assertTrue(all(call[0] != 'plugin' for call in self.mutations()))

    def test_unsupported_legacy_input_never_builds_or_unloads(self):
        self.hypr.value = native('1.29.1', cooperative=False, hasInteraction=True)
        self.assertFalse(self.manager.status()['canReload'])
        with self.assertRaisesRegex(RuntimeError, 'older interactive bridge'):
            self.manager.reload()
        self.assertEqual(self.builds, 0)
        self.assertEqual(self.mutations(), [])

    def test_legacy_render_bridge_can_drain_without_prepare(self):
        self.hypr.value = native('1.24.0', cooperative=False, modulePath=self.old['path'])
        self.manager.reload()
        self.assertTrue(all(call[0] != 'eval' for call in self.mutations()))
        self.assertEqual(self.hypr.value['version'], self.manager.expected)

    def test_foreign_plugin_owner_or_external_binary_is_preserved(self):
        self.hypr.author = 'someone-else'
        with self.assertRaisesRegex(RuntimeError, 'ownership'):
            self.manager.reload()
        self.hypr.author = 'artu-ole'
        self.hypr.value['modulePath'] = '/tmp/foreign/window-stash-preview.so'
        with self.assertRaisesRegex(RuntimeError, 'outside its owned cache'):
            self.manager.reload()
        self.assertEqual(self.mutations(), [])

    def test_unload_failure_cancels_prepare_and_preserves_old(self):
        self.hypr.fail_unload = True
        with self.assertRaisesRegex(RuntimeError, 'Unload failed'):
            self.manager.reload()
        self.assertFalse(self.hypr.value['reloadPending'])
        self.assertEqual(self.hypr.value['version'], '1.29.0')

    def test_new_load_failure_rolls_back_only_verified_old_artifact(self):
        self.hypr.fail_load = True
        with self.assertRaisesRegex(RuntimeError, 'Load failed'):
            self.manager.reload()
        self.assertEqual(self.hypr.value['version'], '1.29.0')
        self.assertFalse(self.hypr.value['reloadPending'])

    def test_overwritten_legacy_binary_is_never_used_as_rollback(self):
        self.hypr.fail_load = True
        Path(self.old['path']).write_bytes(b'\x7fELFunrelated-new-binary')
        with self.assertRaisesRegex(RuntimeError, 'Load failed'):
            self.manager.reload()
        self.assertFalse(self.hypr.value['available'])
        self.assertEqual(len([call for call in self.hypr.calls if call[:2] == ('plugin', 'load')]), 1)

    def test_loader_pinning_cannot_be_reported_as_success(self):
        self.hypr.wrong_fingerprint = True
        with self.assertRaisesRegex(RuntimeError, 'old native code may still be retained'):
            self.manager.reload()

    def test_closed_progress_pipe_after_unload_still_finishes_replacement(self):
        def broken(value):
            if value['state'] == 'loading':
                raise BrokenPipeError()
        self.manager.emit = broken
        self.assertEqual(self.manager.reload()['state'], 'ready')
        self.assertEqual(self.hypr.value['version'], self.manager.expected)

    def test_cancellation_after_unload_finishes_replacement(self):
        call = self.hypr.call
        def cancel_after_unload(*args):
            result = call(*args)
            if args[:2] == ('plugin', 'unload'):
                self.cancelled = True
            return result
        self.hypr.call = cancel_after_unload
        self.assertEqual(self.manager.reload()['state'], 'ready')

    def test_lost_unload_acknowledgement_is_reconciled(self):
        call = self.hypr.call
        def lost_ack(*args):
            result = call(*args)
            if args[:2] == ('plugin', 'unload'):
                raise RuntimeError('IPC acknowledgement lost')
            return result
        self.hypr.call = lost_ack
        self.assertEqual(self.manager.reload()['state'], 'ready')

    def test_compiler_is_cancelled_and_reaped_without_touching_loaded_bridge(self):
        tools = self.root/'tools'
        tools.mkdir()
        pidfile = self.root/'builder.pid'
        (tools/'build-preview-bridge.py').write_text(
            'import os,time\nfrom pathlib import Path\nPath('+repr(str(pidfile))+').write_text(str(os.getpid()))\ntime.sleep(30)\n')
        start = time.monotonic()
        self.manager.cancelled = lambda: time.monotonic()-start > .3
        with patch('bridge.ROOT', self.root), self.assertRaisesRegex(RuntimeError, 'cancelled'):
            BridgeManager.build(self.manager, COMMIT)
        self.assertLess(time.monotonic()-start, 3)
        with self.assertRaises(ProcessLookupError):
            os.kill(int(pidfile.read_text()), 0)
        self.assertEqual(self.hypr.value['version'], '1.29.0')
        self.assertEqual(self.mutations(), [])

    def test_shell_stdin_eof_cancels_before_any_compositor_call(self):
        script = Path(__file__).resolve().parents[1]/'controller/bridge.py'
        result = subprocess.run([sys.executable, str(script), 'reload', '--watch-stdin'],
                                input='', text=True, capture_output=True, timeout=3)
        self.assertEqual(result.returncode, 1)
        self.assertIn('cancelled', json.loads(result.stdout)['error'])

    def test_shared_gate_blocks_reload_and_exclusive_gate_blocks_acquisition(self):
        with bridge_gate():
            with self.assertRaisesRegex(RuntimeError, BUSY):
                self.manager.reload()
        with bridge_gate(exclusive=True):
            with self.assertRaisesRegex(RuntimeError, BUSY), bridge_gate():
                self.fail('Acquisition entered during replacement')
        with bridge_gate(exclusive=True):
            pass

    def test_malformed_native_status_cannot_authorize_unload(self):
        for change in (dict(owners=True), dict(inputActive=1), dict(pendingKeys=-1),
                       dict(version='../../oops'), dict(hyprlandHash='wrong'), dict(reloadReady='yes'),
                       dict(fingerprint='unsafe'), dict(reloadProtocol=2)):
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                decode_status(json.dumps(dict(self.hypr.value, **change)))
        for missing in ('owners', 'hasInteraction', 'reloadReady', 'modulePath'):
            value = dict(self.hypr.value)
            del value[missing]
            with self.subTest(missing=missing), self.assertRaises(RuntimeError):
                decode_status(json.dumps(value))


if __name__ == '__main__':
    unittest.main()
