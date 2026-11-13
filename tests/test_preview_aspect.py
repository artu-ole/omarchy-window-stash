"""Source reflow stays private, preserves restoration, and waits for real frames."""
import copy
import fcntl
import io
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'controller'))
from stash import (Hyprland, Stash, SPECIAL, PREFIX, atomic_json, lua, main,
                   preview_source_size, preview_geometry_owner, PREVIEW_MAX_DIMENSION, PREVIEW_MAX_PIXELS)
from bridge_runtime import BUSY, bridge_gate
from test_controller import FakeHypr, FullscreenCleanupIPC


class AspectHypr(FakeHypr):
    def __init__(self):
        super().__init__()
        self.api = True
        self.available = True
        self.ready = [True]
        self.input_active = False
        self.query_count = 0
        self.waits = 0
        self.on_geometry = None
        self.constrain = None
        self.released = []

    def release_preview_geometry(self, ident):
        self.released.append(ident)

    def wait_preview_fullscreen(self, record):
        self.waits += 1

    def preview_geometry(self, record, size=None, expected_size=None, resizing=False):
        if self.on_geometry:
            self.on_geometry(record, size)
        source = self.client(record['address'])
        if (not source or source['pid'] != record['pid'] or source['stableId'] != record['stableId']
                or record['tag'] not in source['tags'] or source['workspace']['name'] != SPECIAL
                or not source['mapped'] or not source['floating'] or source['fullscreen']):
            raise RuntimeError('The preview source changed')
        if (size is not None or resizing) and self.input_active:
            raise RuntimeError('Stop preview interaction before resizing')
        if expected_size is not None and source['size'] != expected_size:
            raise RuntimeError('The preview source changed size; retry the resize')
        if size is not None and size != source['size']:
            self.dispatch_owned('window.resize', record, parked=True, x=size[0], y=size[1], relative=False)
            if self.constrain:
                self.constrain(source)
        ready = self.api and self.ready[min(self.query_count, len(self.ready)-1)]
        self.query_count += 1
        reason = '' if ready else 'frame-pending' if self.api else 'native-source-geometry-unavailable'
        return dict(size=list(source['size']), aspect=source['size'][0]/source['size'][1], ready=ready,
                    nativeRequired=not self.api, reason=reason,
                    nativeAvailable=self.available,
                    nativeGeometry=dict(width=source['size'][0], height=source['size'][1]))


class PreviewAspectTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.hypr = AspectHypr()
        self.hypr.clients[0]['floating'] = True
        self.stash = Stash(self.hypr, self.root/'run', self.root/'shell.json', self.root/'state')
        with self.stash.locked():
            self.ident = self.stash.minimize()['id']
        self.original = copy.deepcopy(self.stash.state['windows'][0])
        self.hypr.commands.clear()

    def tearDown(self):
        self.temporary.cleanup()

    def assert_original_saved(self):
        record = dict(self.stash.state['windows'][0])
        record.pop('previewResized', None)
        self.assertEqual(record, self.original)

    def test_width_and_height_drags_reflow_only_the_selected_axis(self):
        first = self.stash.preview_aspect(self.ident, 2, 'width')
        self.assertEqual(first['size'], [800, 400])
        self.assertEqual(first['aspect'], 2)
        second = self.stash.preview_aspect(self.ident, 1, 'height')
        self.assertEqual(second['size'], [800, 800])
        self.assertEqual(second['requestedSize'], [800, 800])
        self.assertTrue(second['ready'])
        self.assertEqual([name for name, _ in self.hypr.commands], ['window.resize', 'window.resize'])
        self.assertEqual(self.hypr.clients[0]['workspace']['name'], SPECIAL)
        self.assertEqual(self.hypr.clients[0]['at'], [100, 150])
        self.assert_original_saved()

    def test_resize_marker_is_committed_before_source_mutation_and_restore_uses_original_geometry(self):
        def check_marker(_record, size):
            if size is not None:
                saved = json.loads(self.stash.path.read_text())['windows'][0]
                self.assertTrue(saved['previewResized'])
                self.assertEqual(saved['size'], [640, 400])
        self.hypr.on_geometry = check_marker
        self.stash.preview_aspect(self.ident, .5, 'width')
        self.hypr.on_geometry = None
        self.assertEqual(self.hypr.clients[0]['size'], [200, 400])
        with self.stash.locked():
            self.stash.restore(self.ident, 'original')
        self.assertEqual(self.hypr.clients[0]['size'], [640, 400])
        self.assertEqual(self.hypr.clients[0]['at'], [100, 150])
        self.assertTrue(self.hypr.clients[0]['floating'])

    def test_noop_does_not_mark_or_reconfigure_the_source(self):
        saved = self.stash.path.read_bytes()
        result = self.stash.preview_aspect(self.ident, 1.6, 'width', settle=True)
        self.assertFalse(result['changed'])
        self.assertEqual(self.hypr.commands, [])
        self.assertEqual(self.stash.path.read_bytes(), saved)

    def test_readiness_query_is_readonly_even_while_input_is_active(self):
        self.hypr.input_active = True
        saved = self.stash.path.read_bytes()
        result = self.stash.preview_geometry(self.ident)
        self.assertTrue(result['ready'])
        self.assertEqual(self.stash.path.read_bytes(), saved)
        self.assertEqual(self.hypr.commands, [])

    def test_active_input_rejects_resize_before_touching_ledger_or_source(self):
        self.hypr.input_active = True
        saved = self.stash.path.read_bytes()
        with self.assertRaisesRegex(RuntimeError, 'Stop preview interaction'):
            self.stash.preview_aspect(self.ident, 2, 'width')
        self.assertEqual(self.stash.path.read_bytes(), saved)
        self.assertEqual(self.hypr.commands, [])

    def test_stale_identity_private_ownership_and_phase_are_required(self):
        for change in (dict(pid=200), dict(stableId='ff'), dict(tags=[]),
                       dict(workspace=dict(id=2,name='2')), dict(mapped=False),
                       dict(floating=False), dict(fullscreen=2)):
            with self.subTest(change=change):
                source = copy.deepcopy(self.hypr.clients[0])
                self.hypr.clients[0].update(change)
                with self.assertRaises(RuntimeError):
                    self.stash.preview_aspect(self.ident, 2, 'width')
                self.assertEqual(self.hypr.commands, [])
                self.hypr.clients[0] = source
        with self.stash.locked():
            self.stash.state['windows'][0]['phase'] = 'restoring'
            self.stash.save()
        with self.assertRaisesRegex(RuntimeError, 'no longer stashed'):
            self.stash.preview_geometry(self.ident)

    def test_minimum_constraints_return_the_accepted_ratio(self):
        self.hypr.constrain = lambda source:source.update(size=[480, source['size'][1]])
        self.hypr.ready = [False, False, True]
        with patch('stash.time.sleep'):
            result = self.stash.preview_aspect(self.ident, .5, 'width', settle=True)
        self.assertEqual(result['requestedSize'], [200, 400])
        self.assertEqual(result['size'], [480, 400])
        self.assertEqual(result['aspect'], 1.2)
        self.assertTrue(result['ready'])
        self.assert_original_saved()

    def test_slow_client_returns_recoverable_pending_after_a_bounded_wait(self):
        self.hypr.ready = [False]
        clock = [0.0]
        def tick(_seconds):clock[0] += 1
        with patch('stash.time.monotonic', side_effect=lambda:clock[0]), patch('stash.time.sleep', side_effect=tick):
            result = self.stash.preview_aspect(self.ident, 2, 'width', settle=True)
        self.assertFalse(result['ready'])
        self.assertFalse(result['nativeRequired'])
        self.assertLessEqual(clock[0], 3)
        self.assertEqual(len(self.hypr.commands), 1)
        self.assertEqual(self.hypr.clients[0]['workspace']['name'], SPECIAL)
        self.assert_original_saved()

    def test_no_native_api_allows_static_resize_but_never_claims_input_readiness(self):
        self.hypr.api = False
        with patch('stash.time.sleep') as sleep:
            result = self.stash.preview_aspect(self.ident, 2, 'width', settle=True)
        self.assertEqual(result['size'], [800, 400])
        self.assertTrue(result['nativeRequired'])
        self.assertFalse(result['ready'])
        sleep.assert_not_called()

    def test_invalid_aspect_and_axis_leave_all_state_unchanged(self):
        before = self.stash.path.read_bytes()
        for value in (float('nan'), float('inf'), -1, 0, .019, 50.01, True, None, '2'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.stash.preview_aspect(self.ident, value, 'width')
        with self.assertRaises(ValueError):
            self.stash.preview_aspect(self.ident, 2, 'diagonal')
        self.assertEqual(self.stash.path.read_bytes(), before)
        self.assertEqual(self.hypr.commands, [])

    def test_requested_source_dimensions_and_render_area_are_bounded(self):
        for original in ([8192,8192], [100_000,200_000], [640,400], [1,1]):
            for ratio in (.02, .25, 1, 4, 50):
                for axis in ('width','height'):
                    size = preview_source_size(original, ratio, axis)
                    self.assertTrue(all(1 <= value <= PREVIEW_MAX_DIMENSION for value in size))
                    self.assertLessEqual(size[0]*size[1], PREVIEW_MAX_PIXELS)

    def test_shared_gate_and_ledger_span_resize_and_release_on_failure(self):
        class GatedHypr(AspectHypr, Hyprland):pass
        hypr = GatedHypr()
        hypr.clients = copy.deepcopy(self.hypr.clients)
        self.stash.hypr = hypr
        environment = dict(XDG_RUNTIME_DIR=str(self.root/'native-runtime'), HYPRLAND_INSTANCE_SIGNATURE='aspect-gate')
        def verify(_record, _size):
            with self.assertRaisesRegex(RuntimeError, BUSY), bridge_gate(exclusive=True):
                self.fail('Native replacement overlapped source sizing')
            with (self.stash.directory/'lock').open('a') as lock:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        hypr.on_geometry = verify
        with patch.dict(os.environ, environment):
            self.stash.preview_aspect(self.ident, 2, 'width')
            with bridge_gate(exclusive=True):
                with self.assertRaisesRegex(RuntimeError, BUSY):
                    self.stash.preview_aspect(self.ident, 1, 'width')
            hypr.on_geometry = lambda *_args:(_ for _ in ()).throw(RuntimeError('Client disappeared'))
            with self.assertRaisesRegex(RuntimeError, 'Client disappeared'):
                self.stash.preview_aspect(self.ident, 1, 'width')
            with bridge_gate(exclusive=True):
                pass

    def test_position_aspect_extension_is_optional_and_can_be_cleared(self):
        key = 'preview:window:stable'
        base = ['preview-position','output',key,'10','20','300']
        def invoke(arguments):
            with patch('stash.Stash', return_value=self.stash), patch('sys.stdout', new_callable=io.StringIO) as output:
                code = main(arguments)
            return code,json.loads(output.getvalue())
        self.assertEqual(invoke(base+['--aspect','1.75'])[0], 0)
        self.assertEqual(json.loads(self.stash.positions.read_text())['output'][key], [10,20,300,1.75])
        before = self.stash.positions.read_bytes()
        for invalid in ('nan','inf','0','50.01'):
            self.assertEqual(invoke(base+['--aspect',invalid])[0], 1)
            self.assertEqual(self.stash.positions.read_bytes(), before)
        self.assertEqual(invoke(base)[0], 0)
        self.assertEqual(json.loads(self.stash.positions.read_text())['output'][key], [10,20,300])

    def test_first_gesture_loads_native_support_outside_the_ledger_then_rechecks_identity(self):
        class GatedHypr(AspectHypr, Hyprland):pass
        hypr = GatedHypr()
        hypr.clients = copy.deepcopy(self.hypr.clients)
        hypr.api = hypr.available = False
        self.stash.hypr = hypr
        environment = dict(XDG_RUNTIME_DIR=str(self.root/'native-runtime'), HYPRLAND_INSTANCE_SIGNATURE='aspect-autoload')
        def load():
            with (self.stash.directory/'lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(RuntimeError, BUSY), bridge_gate(exclusive=True):
                self.fail('Native replacement overlapped first-use loading')
            hypr.api = hypr.available = True
        with patch.dict(os.environ, environment), patch('preview.PreviewBridge') as bridge:
            bridge.return_value.ensure.side_effect = load
            result = self.stash.preview_aspect(self.ident, 2, 'width')
            bridge.assert_called_once_with(hypr)
        self.assertTrue(result['ready'])
        self.assertEqual(result['size'], [800,400])

    def test_existing_old_native_is_never_automatically_replaced(self):
        class GatedHypr(AspectHypr, Hyprland):pass
        hypr = GatedHypr()
        hypr.clients = copy.deepcopy(self.hypr.clients)
        hypr.api = False
        self.stash.hypr = hypr
        environment = dict(XDG_RUNTIME_DIR=str(self.root/'native-runtime'), HYPRLAND_INSTANCE_SIGNATURE='aspect-existing')
        with patch.dict(os.environ, environment), patch('preview.PreviewBridge') as bridge:
            result = self.stash.preview_aspect(self.ident, 2, 'width')
            bridge.assert_not_called()
        self.assertTrue(result['nativeRequired'])
        self.assertFalse(result['ready'])

    def test_first_use_failure_keeps_static_resize_available_and_releases_on_identity_loss(self):
        class GatedHypr(AspectHypr, Hyprland):pass
        hypr = GatedHypr()
        hypr.clients = copy.deepcopy(self.hypr.clients)
        hypr.api = hypr.available = False
        self.stash.hypr = hypr
        environment = dict(XDG_RUNTIME_DIR=str(self.root/'native-runtime'), HYPRLAND_INSTANCE_SIGNATURE='aspect-build-failure')
        with patch.dict(os.environ, environment), patch('preview.PreviewBridge') as bridge:
            bridge.return_value.ensure.side_effect = RuntimeError('Matching headers unavailable')
            result = self.stash.preview_aspect(self.ident, 2, 'width')
        self.assertEqual(result['size'], [800,400])
        self.assertIn('headers',result['nativeError'])
        hypr.commands.clear()
        def replace():hypr.clients[0]['pid'] += 1
        with patch.dict(os.environ, environment), patch('preview.PreviewBridge') as bridge:
            bridge.return_value.ensure.side_effect = replace
            with self.assertRaisesRegex(RuntimeError, 'identity changed'):
                self.stash.preview_aspect(self.ident, 1, 'width')
        self.assertEqual(hypr.commands, [])
        self.assertEqual(hypr.released, [self.ident])

    def test_cli_aspect_and_geometry_dispatch_without_nested_ledger_lock(self):
        for arguments in (['preview-aspect',self.ident,'2','--axis','width','--settle'], ['preview-geometry',self.ident]):
            with patch('stash.Stash', return_value=self.stash), patch('sys.stdout', new_callable=io.StringIO) as output:
                self.assertEqual(main(arguments), 0)
            self.assertEqual(json.loads(output.getvalue())['id'], self.ident)


@unittest.skipUnless(shutil.which('lua'), 'Standalone Lua interpreter unavailable')
class PreviewAspectLuaTests(unittest.TestCase):
    def setUp(self):
        self.record = dict(id='a'*32,address='0x123',pid=73,stableId='18000001',tag=PREFIX+'a'*32)

    def invoke(self, change='', api=True, geometry=None, size=None, expected=None, resizing=False, replace=False):
        state = dict(pid=73,stable_id=int('18000001',16),tags=[self.record['tag']],workspace=dict(name=SPECIAL),
                     mapped=True,floating=True,fullscreen=0,fullscreen_client=2,size=dict(x=640,y=400))
        def encode(value):
            if isinstance(value,dict):return '{'+','.join(key+'='+encode(item) for key,item in value.items())+'}'
            if isinstance(value,list):return '{'+','.join(map(encode,value))+'}'
            return lua(value)
        geometry = dict(ready=True,width=640,height=400,configuredWidth=640,configuredHeight=400,surfaceWidth=640,surfaceHeight=400,reason='') if geometry is None else geometry
        calls = []
        class Capture:
            def call(_self, method, script):
                self.assertEqual(method,'repl');calls.append(script)
                return ''
        try:
            Hyprland.preview_geometry(Capture(),self.record,size,expected,resizing)
        except json.JSONDecodeError:
            pass
        source = ('local current='+encode(state)+';local original=current;local resized=0;local updates=0;local releases=0\n'
                  +'local replacement='+encode(dict(state,pid=200,size=dict(x=777,y=333)))+'\n'
                  +'hl={get_window=function(_) return current end,plugin={},dsp={window={}},dispatch=function(action) action() end}\n'
                  +'hl.dsp.window.resize=function(args) return function() resized=resized+1;args.window.size={x=args.x,y=args.y};'
                  +('current=replacement;' if replace else '')+' end end\n')
        if api:
            source += ('hl.plugin.window_stash_preview={status=function() return {interaction={active=false},capabilities={sourceGeometry=true}} end,'
                       +'update=function(v) assert(v.owner=='+lua(preview_geometry_owner(self.record['id']))
                       +' and #v.windows==1 and v.windows[1].id=='+lua(self.record['id'])+');updates=updates+1;return {accepted=1} end,'
                       +'release=function(owner) assert(owner=='+lua(preview_geometry_owner(self.record['id']))+');releases=releases+1 end,'
                       +'fullscreen_cleanup_pending=function(_) return false end,source_geometry=function(v) '
                       +'assert(v.id=='+lua(self.record['id'])+' and v.pid==73 and v.stable_id=="18000001" and v.tag=='+lua(self.record['tag'])+');return '+encode(geometry)+' end}\n')
        source += change+'\nlocal ok,result=pcall(function()\n'+calls[0]+'\nend)\n'
        source += 'print(tostring(ok));print(tostring(result));print(resized);print(original.fullscreen_client);print(current.size.x);print(current.size.y);print(updates);print(releases)\n'
        result = subprocess.run(['lua','-'],input=source,text=True,capture_output=True,check=True)
        lines = result.stdout.splitlines()
        self.leases = tuple(map(int,lines[6:8]))
        return lines[0]=='true', lines[1], list(map(int, lines[2:6]))

    def test_atomic_resize_preserves_client_fullscreen_and_reports_accepted_goal(self):
        geometry = dict(ready=False,width=640,height=400,configuredWidth=640,configuredHeight=400,surfaceWidth=640,surfaceHeight=400,reason='frame-pending')
        ok, raw, state = self.invoke(size=[800,400], expected=[640,400], geometry=geometry)
        self.assertTrue(ok,raw)
        packet = json.loads(raw)
        self.assertEqual(packet['size'], [800,400])
        self.assertEqual(packet['nativeGeometry']['width'], 640)
        self.assertFalse(packet['ready'])
        self.assertEqual(state, [1,2,800,400])
        self.assertEqual(self.leases, (1,0))

    def test_stale_identity_and_active_or_fullscreen_sources_never_resize(self):
        for change in ('current.pid=74','current.stable_id=2','current.tags={}',
                       'current.workspace.name="1"','current.mapped=false','current.floating=false','current.fullscreen=2',
                       'hl.plugin.window_stash_preview.status=function() return {interaction={active=true}} end',
                       'hl.plugin.window_stash_preview.fullscreen_cleanup_pending=function() return true end'):
            with self.subTest(change=change):
                ok, _raw, state = self.invoke(change=change,size=[800,400],expected=[640,400])
                self.assertFalse(ok)
                self.assertEqual(state[0], 0)
                self.assertEqual(state[-2:], [640,400])

    def test_replacement_during_dispatch_is_never_adopted(self):
        ok, raw, state = self.invoke(size=[800,400], expected=[640,400], replace=True)
        self.assertFalse(ok)
        self.assertIn('identity changed',raw)
        self.assertEqual(state, [1,2,777,333])

    def test_native_absence_and_noop_are_safe_and_pending_reason_is_escaped(self):
        ok, raw, state = self.invoke(api=False,size=[640,400],expected=[640,400])
        self.assertTrue(ok,raw)
        self.assertTrue(json.loads(raw)['nativeRequired'])
        self.assertFalse(json.loads(raw)['ready'])
        self.assertEqual(state[0],0)
        geometry = dict(ready=False,width=640,height=400,reason='pending "frame"\\next\nline')
        ok, raw, _state = self.invoke(geometry=geometry)
        self.assertTrue(ok,raw)
        self.assertEqual(json.loads(raw)['reason'],geometry['reason'])

    def test_waiting_for_existing_fullscreen_cleanup_does_not_clear_it(self):
        ipc = FullscreenCleanupIPC(self.record,[True,False])
        with patch('stash.time.sleep'):
            Hyprland.wait_preview_fullscreen(ipc,self.record)
        self.assertEqual((ipc.clears,ipc.queries),(0,2))

    def test_pending_queries_renew_only_an_explicit_aspect_owner_and_ready_releases_it(self):
        pending = dict(ready=False,width=640,height=400,reason='frame-pending')
        ok, _raw, _state = self.invoke(geometry=pending)
        self.assertTrue(ok)
        self.assertEqual(self.leases, (0,0))
        self.record['previewResized'] = True
        ok, _raw, _state = self.invoke(geometry=pending)
        self.assertTrue(ok)
        self.assertEqual(self.leases, (1,0))
        ok, _raw, _state = self.invoke()
        self.assertTrue(ok)
        self.assertEqual(self.leases, (0,1))
        self.assertNotEqual(preview_geometry_owner(self.record['id']), preview_geometry_owner('b'*32))

    def test_unavailable_or_disallowed_capture_never_acquires_a_rendering_lease(self):
        self.record['previewResized'] = True
        for reason in ('capture-unavailable','unsupported-source','invalid-source-scale'):
            ok, _raw, _state = self.invoke(geometry=dict(ready=False,width=640,height=400,reason=reason))
            self.assertTrue(ok)
            self.assertEqual(self.leases, (0,1))

    def test_one_settle_loop_throttles_renewals_and_ready_clears_the_clock(self):
        self.record['previewResized'] = True
        hypr = Hyprland()
        scripts = []
        packets = iter((dict(ready=False,leaseRenewed=True), dict(ready=False,leaseRenewed=False),
                        dict(ready=False,leaseRenewed=True), dict(ready=True,leaseRenewed=False)))
        def result(_method, code):
            scripts.append(code)
            value = next(packets)
            return json.dumps(dict(size=[640,400],nativeRequired=False,
                                   reason='' if value['ready'] else 'frame-pending',**value))
        hypr.call = result
        with patch('stash.time.monotonic',side_effect=(0,0,.1,.5,.5,.6)):
            for _ in range(4):
                hypr.preview_geometry(self.record)
        self.assertIn('leaseWanted and true then', scripts[0])
        self.assertIn('leaseWanted and false then', scripts[1])
        self.assertIn('leaseWanted and true then', scripts[2])
        self.assertEqual(hypr._preview_lease_renewals,{})


if __name__ == '__main__':
    unittest.main()
