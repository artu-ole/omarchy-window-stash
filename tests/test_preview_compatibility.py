"""The optional native bridge can lease only validated, visible Live sources."""
import copy
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'controller'))
from preview import MISSING_API, RESTART_REQUIRED, PreviewBridge, PreviewKeeper, PreviewStopped, preview_records, request_ids, run_loop
from stash import PLUGIN, SPECIAL, Stash, atomic_json

IDENT = 'a'*32
OTHER = 'b'*32
VERSION = (Path(__file__).resolve().parents[1]/'native/version.txt').read_text().strip()


def record(ident=IDENT, address='0x123'):
    return dict(id=ident, address=address, pid=42, stableId='18000001',
                tag='window-stash-'+ident, phase='stashed')


def client(value=None):
    value = value or record()
    return dict(address=value['address'], pid=value['pid'], stableId=value['stableId'],
                mapped=True, tags=[value['tag']], workspace=dict(name=SPECIAL))


class FakeHypr:
    def __init__(self):
        self.clients = [client()]
        self.reads = []

    def read(self, subject):
        self.reads.append(subject)
        if subject != 'clients':
            raise AssertionError('Unexpected IPC '+subject)
        return copy.deepcopy(self.clients)


class FakeBridge:
    def __init__(self):
        self.calls = []
        self.error = None

    def ensure(self):
        self.calls.append(('ensure',))

    def update(self, owner, records):
        self.calls.append(('update', owner, copy.deepcopy(records)))
        if self.error:
            raise self.error

    def release(self, owner):
        self.calls.append(('release', owner))


class PreviewCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.hypr = FakeHypr()
        self.stash = Stash(self.hypr, root/'run', root/'shell.json', root/'state')
        self.stash.directory.mkdir()
        self.saved = [record()]
        self.save()
        self.settings()
        self.bridge = FakeBridge()
        self.keeper = PreviewKeeper(self.stash, self.bridge)

    def tearDown(self):
        self.temporary.cleanup()

    def save(self):
        atomic_json(self.stash.path, dict(version=1, windows=self.saved))

    def settings(self, mode='live', compatibility='enhanced', **extra):
        atomic_json(self.stash.config, dict(plugins=[dict(id=PLUGIN, hoverPreview=mode,
                                                       livePreviewCompatibility=compatibility, **extra)]))

    def test_ids_are_bounded_exact_and_deduplicated(self):
        self.assertEqual(request_ids([OTHER, IDENT, OTHER]), [IDENT, OTHER])
        for invalid in (None, {}, IDENT, [42], [True], ['../'+IDENT], ['A'*32], ['a'*31], [IDENT]*129):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                request_ids(invalid)

    def test_changed_identity_or_ownership_never_acquires(self):
        patches = [dict(pid=43), dict(stableId='18000002'), dict(mapped=False), dict(tags=[]),
                   dict(tags=['window-stash-'+IDENT+'-other']), dict(workspace=dict(name='1')),
                   dict(workspace=dict(name='special:minimized')), dict(address='0x124')]
        for change in patches:
            with self.subTest(change=change):
                self.hypr.clients = [dict(client(), **change)]
                self.assertEqual(self.keeper.sync([IDENT])['ids'], [])
                self.assertEqual(self.bridge.calls, [])

    def test_duplicate_addresses_never_acquire(self):
        self.hypr.clients.append(client())
        self.assertEqual(self.keeper.sync([IDENT])['ids'], [])
        self.assertEqual(self.bridge.calls, [])

    def test_unowned_or_transitioning_records_never_acquire(self):
        for change in (dict(tag='other'), dict(phase='restoring'), dict(pid=True), dict(pid=0)):
            with self.subTest(change=change):
                self.saved = [dict(record(), **change)]
                self.save()
                self.assertEqual(self.keeper.sync([IDENT])['ids'], [])
        self.assertEqual(self.bridge.calls, [])

    def test_standard_off_still_and_empty_requests_never_load_or_read_clients(self):
        for mode, compatibility, wanted in [('live', 'standard', [IDENT]), ('still', 'enhanced', [IDENT]),
                                             ('off', 'enhanced', [IDENT]), ('live', 'enhanced', [])]:
            with self.subTest(mode=mode, compatibility=compatibility, wanted=wanted):
                self.settings(mode, compatibility)
                self.keeper.sync(wanted)
        self.assertEqual(self.bridge.calls, [])
        self.assertEqual(self.hypr.reads, [])

    def test_floating_cards_acquire_live_sources_independently_of_hover_preview_setting(self):
        for update in ('hover', 'live'):
            for hover in ('off', 'still'):
                with self.subTest(update=update, hover=hover):
                    self.settings(hover, presentation='previews', floatingPreviewUpdate=update)
                    self.assertEqual(self.keeper.sync([IDENT]), dict(state='ready', ids=[IDENT]))
                    self.assertEqual(self.bridge.calls[-1][0], 'update')
                    self.keeper.close()

    def test_floating_cards_still_standard_other_modes_and_no_visible_requests_never_lease(self):
        cases = [('still', 'enhanced', 'previews', [IDENT]), ('hover', 'standard', 'previews', [IDENT]),
                 ('live', 'standard', 'previews', [IDENT]), ('live', 'enhanced', 'floating', [IDENT]),
                 ('hover', 'enhanced', 'bubbles', [IDENT]), ('live', 'enhanced', 'previews', [])]
        for update, compatibility, presentation, wanted in cases:
            with self.subTest(update=update, compatibility=compatibility, presentation=presentation, wanted=wanted):
                self.settings('off', compatibility, presentation=presentation, floatingPreviewUpdate=update)
                self.keeper.sync(wanted)
        self.assertEqual(self.bridge.calls, [])
        self.assertEqual(self.hypr.reads, [])

    def test_card_update_policy_and_presentation_changes_release_owned_rendering(self):
        for change in (dict(floatingPreviewUpdate='still'), dict(presentation='dock'),
                       dict(livePreviewCompatibility='standard')):
            with self.subTest(change=change):
                settings = dict(presentation='previews', floatingPreviewUpdate='live', livePreviewCompatibility='enhanced')
                self.settings('off', settings.pop('livePreviewCompatibility'), **settings)
                self.keeper.sync([IDENT])
                self.bridge.calls.clear()
                settings['livePreviewCompatibility'] = 'enhanced'
                settings.update(change)
                self.settings('off', settings.pop('livePreviewCompatibility'), **settings)
                self.keeper.sync([IDENT])
                self.assertEqual(self.bridge.calls, [('release',self.keeper.owner)])

    def test_only_requested_owned_records_are_sent_with_fresh_identity(self):
        self.saved.append(record(OTHER, '0x124'))
        self.save()
        self.hypr.clients.append(client(self.saved[1]))
        result = self.keeper.sync([IDENT])
        self.assertEqual(result, dict(state='ready', ids=[IDENT]))
        self.assertEqual(self.bridge.calls[-1], ('update', self.keeper.owner,
                         [dict(id=IDENT, address='0x123', pid=42, stable_id='18000001', tag='window-stash-'+IDENT)]))
        self.assertEqual(self.hypr.reads, ['clients'])

    def test_legacy_identity_uses_fresh_stable_id_but_still_requires_ownership(self):
        del self.saved[0]['stableId']
        self.save()
        self.keeper.sync([IDENT])
        self.assertEqual(self.bridge.calls[-1][2][0]['stable_id'], '18000001')

    def test_disabling_setting_or_losing_record_releases_exact_owner(self):
        for mode in ('disabled', 'closed', 'replaced'):
            with self.subTest(mode=mode):
                self.settings()
                self.saved = [record()]
                self.save()
                self.hypr.clients = [client()]
                self.keeper.sync([IDENT])
                self.bridge.calls = []
                if mode == 'disabled':
                    self.settings(compatibility='standard')
                elif mode == 'closed':
                    self.saved = []
                    self.save()
                else:
                    self.hypr.clients[0]['stableId'] = '18000002'
                self.keeper.sync([IDENT])
                self.assertEqual(self.bridge.calls, [('release', self.keeper.owner)])
                self.keeper.close()
                self.assertEqual(len(self.bridge.calls), 1)

    def test_retarget_updates_complete_set_and_empty_releases(self):
        self.saved.append(record(OTHER, '0x124'))
        self.save()
        self.hypr.clients.append(client(self.saved[1]))
        self.keeper.sync([IDENT, OTHER])
        self.keeper.sync([OTHER])
        self.assertEqual([r['id'] for r in self.bridge.calls[-1][2]], [OTHER])
        self.keeper.sync([])
        self.assertEqual(self.bridge.calls[-1], ('release', self.keeper.owner))

    def test_update_failure_still_arms_cleanup(self):
        self.bridge.error = RuntimeError('native update failed')
        with self.assertRaisesRegex(RuntimeError, 'native update failed'):
            self.keeper.sync([IDENT])
        self.keeper.close()
        self.assertEqual(self.bridge.calls[-1], ('release', self.keeper.owner))

    def test_input_eof_and_bad_input_always_release(self):
        self.keeper.sync([IDENT])
        for payload in (b'', b'{}\n', b'x'*65537):
            with self.subTest(payload=payload[:10]):
                self.keeper.sync([IDENT])
                self.bridge.calls = []
                chunks = [payload] if not payload or len(payload) > 65536 else [payload, b'']
                with patch('preview.select.select', return_value=([sys.stdin], [], [])), \
                        patch('preview.os.read', side_effect=chunks):
                    if payload:
                        with self.assertRaises((ValueError, json.JSONDecodeError)):
                            run_loop(sys.stdin, self.keeper, lambda value: None)
                    else:
                        self.assertEqual(run_loop(sys.stdin, self.keeper, lambda value: None), 0)
                self.assertEqual(self.bridge.calls, [('release', self.keeper.owner)])

    def test_keepalive_renews_without_more_input_until_eof(self):
        with patch('preview.select.select', side_effect=[([sys.stdin], [], []), ([], [], []), ([sys.stdin], [], [])]), \
                patch('preview.os.read', side_effect=[json.dumps([IDENT]).encode()+b'\n', b'']):
            emitted = []
            run_loop(sys.stdin, self.keeper, emitted.append)
        self.assertEqual([c[0] for c in self.bridge.calls], ['ensure', 'update', 'ensure', 'update', 'release'])
        self.assertEqual(emitted, [dict(state='ready', ids=[IDENT])])

    def test_reacquire_reemits_ready_after_out_of_band_loading_progress(self):
        self.bridge.generation = 1
        original_update = self.bridge.update
        emitted = []
        def reloading(owner, records):
            if self.bridge.calls:
                emitted.append(dict(state='loading', ids=[]))
                self.bridge.generation += 1
            original_update(owner, records)
        self.bridge.update = reloading
        with patch('preview.select.select', side_effect=[([sys.stdin], [], []), ([], [], []), ([sys.stdin], [], [])]), \
                patch('preview.os.read', side_effect=[json.dumps([IDENT]).encode()+b'\n', b'']):
            run_loop(sys.stdin, self.keeper, emitted.append)
        self.assertEqual([value['state'] for value in emitted], ['loading', 'ready', 'loading', 'ready'])

    def test_existing_bridge_needs_no_build_or_configuration_changes(self):
        class Loaded:
            def __init__(self): self.evals = []
            def eval(self, script): self.evals.append(script)
            def read(self, _subject): raise AssertionError('No build or version IPC is needed')
        ipc = Loaded()
        bridge = PreviewBridge(ipc)
        with patch('preview.subprocess.run') as run:
            bridge.ensure()
            bridge.ensure()
        run.assert_not_called()
        self.assertEqual(len(ipc.evals), 1)

    @unittest.skipUnless(shutil.which('lua'), 'Standalone Lua interpreter unavailable')
    def test_shell_release_update_accepts_unchanged_loaded_native_implementation(self):
        root = Path(self.temporary.name)
        (root/'native').mkdir()
        (root/'native/version.txt').write_text('1.24.0\n')
        manifest = root/'manifest.json'
        manifest.write_text(json.dumps(dict(version='1.25.0')))
        class Loaded:
            def __init__(self): self.calls = 0
            def eval(self, script):
                self.calls += 1
                source = ('hl={plugin={window_stash_preview={status=function() return '
                          '{protocol=1,version="1.24.0"} end,update=function() end}}}\n'+script)
                result = subprocess.run(['lua', '-'], input=source, text=True, capture_output=True)
                if result.returncode:
                    raise RuntimeError(result.stderr)
            def read(self, _subject): raise AssertionError('Compatible loaded code needs no compositor version query')
        ipc = Loaded()
        with patch('preview.ROOT', root), patch('preview.subprocess.run', wraps=subprocess.run) as run:
            for shell_version in ('1.25.0', '2.0.0', None):
                if shell_version is None:
                    manifest.unlink()
                else:
                    manifest.write_text(json.dumps(dict(version=shell_version)))
                bridge = PreviewBridge(ipc)
                self.assertEqual(bridge.version, '1.24.0')
                bridge.ensure()
                self.assertTrue(bridge.ready)
        self.assertEqual(ipc.calls, 3)
        self.assertTrue(all(call.args[0] == ['lua', '-'] for call in run.call_args_list),
                        'An unchanged native bridge must never rebuild or reload after a shell update')

    def test_missing_or_invalid_native_version_refuses_before_ipc(self):
        root = Path(self.temporary.name)
        (root/'native').mkdir()
        version_file = root/'native/version.txt'
        ipc = unittest.mock.Mock()
        with patch('preview.ROOT', root):
            for value in ('', 'development', '1.2', '01.2.3', '1.2.3-extra', '1.2.3\n4.5.6'):
                with self.subTest(value=value):
                    version_file.write_text(value)
                    with self.assertRaisesRegex(RuntimeError, 'Invalid native preview bridge version'):
                        PreviewBridge(ipc)
            version_file.unlink()
            with self.assertRaises(FileNotFoundError):
                PreviewBridge(ipc)
        self.assertEqual(ipc.mock_calls, [])

    def test_wrong_runtime_identity_refuses_to_build(self):
        class Missing:
            def eval(self, _script): raise RuntimeError('missing')
            def read(self, _subject): return dict(commit='unsafe path')
        with patch('preview.subprocess.run') as run, self.assertRaisesRegex(RuntimeError, 'identify the running Hyprland'):
            PreviewBridge(Missing()).ensure()
        run.assert_not_called()

    def test_matching_build_loads_only_its_binary_and_waits_for_lua_api(self):
        events = []
        commit = 'c'*40
        class Installing:
            probes = 0
            def eval(self, _script):
                self.probes += 1
                if self.probes < 4:
                    raise RuntimeError('namespace pending')
            def read(self, subject):
                events.append(('read', subject))
                return dict(commit=commit)
            def call(self, *arguments):
                events.append(arguments)
        def build(arguments, **_kwargs):
            path = arguments[arguments.index('--output')+1]
            self.assertEqual(arguments[arguments.index('--expected-hash')+1], commit)
            return subprocess.CompletedProcess(arguments, 0, json.dumps(dict(path=path, hyprlandHash=commit, protocol=1, version=VERSION)), '')
        progress = []
        with patch.dict(os.environ, {'XDG_CACHE_HOME': str(Path(self.temporary.name)/'cache')}), \
                patch('preview.subprocess.run', side_effect=build), patch('preview.time.sleep'):
            bridge = PreviewBridge(Installing(), progress.append)
            bridge.ensure()
        self.assertTrue(bridge.ready)
        self.assertEqual(events[0], ('read', 'version'))
        self.assertEqual(events[1][:2], ('plugin', 'load'))
        self.assertTrue(events[1][2].endswith('/'+commit+'/window-stash-preview.so'))
        self.assertEqual([item['state'] for item in progress], ['building', 'loading'])

    def test_failed_or_mismatching_build_never_loads_native_code(self):
        class Installing:
            def eval(self, _script): raise RuntimeError('missing')
            def read(self, _subject): return dict(commit='c'*40)
            def call(self, *_arguments): self.fail('Unverified native code must not be loaded')
        ipc = Installing()
        ipc.fail = self.fail
        for code, stdout, stderr in [(1, '', 'missing headers'),
                                     (0, json.dumps(dict(path='/wrong.so', hyprlandHash='b'*40, protocol=1)), '')]:
            with self.subTest(code=code), patch.dict(os.environ, {'XDG_CACHE_HOME': str(Path(self.temporary.name)/'cache')}), \
                    patch('preview.subprocess.run', return_value=subprocess.CompletedProcess([], code, stdout, stderr)), \
                    self.assertRaises(RuntimeError):
                PreviewBridge(ipc).ensure()

    def test_dismissing_preview_during_build_prevents_loading(self):
        class Installing:
            def eval(self, _script): raise RuntimeError('missing')
            def read(self, _subject): return dict(commit='c'*40)
            def call(self, *_arguments): self.fail('A dismissed preview must not load native code')
        ipc = Installing()
        ipc.fail = self.fail
        def build(arguments, **_kwargs):
            path = arguments[arguments.index('--output')+1]
            return subprocess.CompletedProcess(arguments, 0, json.dumps(dict(path=path, hyprlandHash='c'*40, protocol=1, version=VERSION)), '')
        with patch.dict(os.environ, {'XDG_CACHE_HOME': str(Path(self.temporary.name)/'cache')}), \
                patch('preview.subprocess.run', side_effect=build), self.assertRaises(PreviewStopped):
            PreviewBridge(ipc, cancelled=unittest.mock.Mock(side_effect=[False, True])).ensure()

    def test_compositor_reload_reacquires_same_owner_without_reopening_preview(self):
        class Reloading:
            available = True
            def __init__(self): self.loads = []; self.updates = []
            def eval(self, script):
                if not self.available:
                    raise RuntimeError(MISSING_API)
                if '.update({' in script:
                    self.updates.append(script)
            def read(self, subject):
                self.test.assertEqual(subject, 'version')
                return dict(commit='c'*40)
            def call(self, *arguments):
                self.loads.append(arguments)
                self.available = True
        ipc = Reloading()
        ipc.test = self
        bridge = PreviewBridge(ipc)
        bridge.ensure()
        records = [dict(id=IDENT, address='0x123', pid=42, stable_id='18000001', tag='window-stash-'+IDENT)]
        bridge.update('d'*32, records)
        ipc.available = False
        def build(arguments, **_kwargs):
            path = arguments[arguments.index('--output')+1]
            return subprocess.CompletedProcess(arguments, 0, json.dumps(dict(path=path, hyprlandHash='c'*40, protocol=1, version=VERSION)), '')
        with patch.dict(os.environ, {'XDG_CACHE_HOME': str(Path(self.temporary.name)/'cache')}), \
                patch('preview.subprocess.run', side_effect=build) as compile_bridge:
            bridge.update('d'*32, records)
        self.assertEqual(len(ipc.loads), 1)
        self.assertEqual(ipc.loads[0][:2], ('plugin', 'load'))
        self.assertEqual(len(ipc.updates), 2)
        self.assertEqual(ipc.updates[0], ipc.updates[1])
        self.assertTrue(bridge.ready)
        compile_bridge.assert_called_once()

    def test_second_unload_during_reacquire_is_bounded(self):
        class Unavailable:
            def eval(self, _script): raise RuntimeError(MISSING_API)
        bridge = PreviewBridge(Unavailable())
        bridge.ready = True
        with patch.object(bridge, 'ensure') as reload_bridge, self.assertRaisesRegex(RuntimeError, MISSING_API):
            bridge.update('d'*32, [])
        reload_bridge.assert_called_once()

    def test_identity_rejection_never_reloads_native_module(self):
        class Rejected:
            def eval(self, _script): raise RuntimeError('Preview source changed before the compatibility lease was acquired')
        bridge = PreviewBridge(Rejected())
        bridge.ready = True
        with patch.object(bridge, 'ensure') as reload_bridge, self.assertRaisesRegex(RuntimeError, 'Preview source changed'):
            bridge.update('d'*32, [])
        reload_bridge.assert_not_called()

    def test_old_loaded_version_requires_restart_instead_of_loading_over_it(self):
        class OldModule:
            def eval(self, _script): raise RuntimeError(RESTART_REQUIRED)
            def read(self, _subject): raise AssertionError('An incompatible loaded module must not be rebuilt or replaced')
        bridge = PreviewBridge(OldModule())
        with patch('preview.subprocess.run') as build, self.assertRaisesRegex(RuntimeError, 'Restart Hyprland'):
            bridge.ensure()
        build.assert_not_called()
        with patch.object(bridge, 'ensure') as reload_bridge, self.assertRaisesRegex(RuntimeError, 'Restart Hyprland'):
            bridge.update('d'*32, [])
        reload_bridge.assert_not_called()

    @unittest.skipUnless(shutil.which('lua'), 'Standalone Lua interpreter unavailable')
    def test_native_rejection_and_partial_acceptance_cannot_report_ready(self):
        class Script:
            def eval(self, code): self.code = code
        ipc = Script()
        PreviewBridge(ipc).update('d'*32, [dict(id=IDENT, address='0x123', pid=42,
                                              stable_id='18000001', tag='window-stash-'+IDENT)])
        for native_result, success in [('nil,"rejected identity"', False),
                                        ('{accepted=0,requested=1}', False),
                                        ('{accepted=1,requested=1}', True)]:
            source = ('hl={plugin={window_stash_preview={status=function() return {protocol=1,version="'+VERSION+'"} end,'
                      +'update=function(_) return '+native_result+' end}}}\n'+ipc.code)
            result = subprocess.run(['lua', '-'], input=source, text=True, capture_output=True)
            self.assertEqual(result.returncode == 0, success, result.stderr)

    @unittest.skipUnless(shutil.which('lua'), 'Standalone Lua interpreter unavailable')
    def test_old_version_or_protocol_is_rejected_even_with_update_function(self):
        class Script:
            def eval(self, code): self.code = code
        ipc = Script()
        PreviewBridge(ipc).update('d'*32, [])
        for info in ('{protocol=1,version="old"}', '{protocol=2,version="'+VERSION+'"}'):
            source = ('hl={plugin={window_stash_preview={status=function() return '+info+' end,'
                      +'update=function(_) error("Mismatching native code must not run") end}}}\n'+ipc.code)
            result = subprocess.run(['lua', '-'], input=source, text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(RESTART_REQUIRED, result.stderr)
            self.assertNotIn('Mismatching native code must not run', result.stderr)


if __name__ == '__main__':
    unittest.main()
