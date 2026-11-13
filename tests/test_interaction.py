"""Only explicit, current preview targets can acquire native input routing."""
import copy
import contextlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'controller'))
from interaction import FULLSCREEN_REQUIRED, GEOMETRY_PENDING, GEOMETRY_REQUIRED, RESTORE_REASONS, InteractionBridge, InteractionKeeper, configure_exit_shortcut, exit_shortcut, monitor_contains, request, run_loop, status_json
from stash import DEFAULTS, LOCAL_SHORTCUT_DEFAULTS, PLUGIN, SPECIAL, Stash, atomic_json, lua, main as controller_main
from lifecycle import valid_preferences
from test_controller import FakeHypr as ControllerHypr, client as controller_client, monitor as controller_monitor

IDENT = 'a'*32
OTHER = 'b'*32


def record(ident=IDENT):
    return dict(id=ident, address='0x123', pid=42, stableId='18000001',
                tag='window-stash-'+ident, phase='stashed')


def target(**values):
    return dict(dict(id=IDENT, serial=1, monitor='HEADLESS-1', rect=dict(x=100,y=150,width=300,height=200),
                     excludeRects=[], keyboard=False, fps=60, fullscreen='preview'), **values)


class FakeHypr:
    def __init__(self):
        saved = record()
        self.clients = [dict(address=saved['address'],pid=saved['pid'],stableId=saved['stableId'],
                             mapped=True,tags=[saved['tag']],workspace=dict(name=SPECIAL))]
        self.monitors = [dict(name='HEADLESS-1',x=0,y=0,width=1280,height=800,scale=1,transform=0,dpmsStatus=True)]
        self.binds = []
        self.reads = []

    def read(self, subject):
        self.reads.append(subject)
        if subject == 'clients':return copy.deepcopy(self.clients)
        if subject == 'monitors':return copy.deepcopy(self.monitors)
        if subject == 'binds':return copy.deepcopy(self.binds)
        raise AssertionError('Unexpected compositor read '+subject)


class FakeBridge:
    def __init__(self):
        self.calls = []
        self.current = dict(active=True,reason='active')
        self.error = None
        self.on_ensure = lambda: None
        self.on_handoff = lambda: None

    def ensure(self):
        self.calls.append(('ensure',))
        self.on_ensure()

    def interaction_update(self, owner, source, parameters):
        self.calls.append(('update',owner,copy.deepcopy(source),copy.deepcopy(parameters)))
        if self.error:raise self.error
        self.current.setdefault('owner',owner)
        self.current.setdefault('id',source['id'])
        return copy.deepcopy(self.current)

    def interaction_status(self, owner):
        self.calls.append(('status',owner))
        return copy.deepcopy(self.current)

    def interaction_release(self, owner):
        self.calls.append(('release',owner))
        self.current.pop('owner',None)
        self.current.pop('id',None)

    def interaction_handoff(self, owner):
        self.calls.append(('handoff',owner))
        self.on_handoff()


class InteractionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.hypr = FakeHypr()
        self.stash = Stash(self.hypr,root/'run',root/'shell.json',root/'state')
        self.bridge = FakeBridge()
        self.keeper = InteractionKeeper(self.stash,self.bridge)
        self.saved = [record()]
        self.save()
        self.settings()

    def tearDown(self):
        self.temporary.cleanup()

    def save(self):
        atomic_json(self.stash.path,dict(version=1,windows=self.saved))

    def settings(self, **values):
        entry = dict(id=PLUGIN,presentation='previews',floatingPreviewInteraction='on')
        entry.update(values)
        atomic_json(self.stash.config,dict(plugins=[entry]))

    def test_defaults_are_explicit_opt_in_and_invalid_values_fall_back(self):
        expected = dict(floatingPreviewInteraction='off',floatingPreviewActivation='explicit',
                        floatingPreviewKeyboard='mouse',floatingPreviewInteractionFps='60',floatingPreviewControls='hover',
                        floatingPreviewFullscreen='preview',
                        floatingPreviewExitShortcut='CTRL + ALT + Escape')
        self.assertEqual({key:DEFAULTS[key] for key in expected},expected)
        self.settings(**{key:True for key in expected})
        self.assertEqual({key:self.stash.settings()[key] for key in expected},expected)

    def test_requests_have_one_exact_id_bounded_numbers_and_control_regions(self):
        self.assertEqual(request(None),None)
        self.assertEqual(request(target()),target())
        legacy = target();del legacy['fullscreen']
        self.assertEqual(request(legacy)['fullscreen'],'preview')
        invalid = [[], {}, target(id='../'+IDENT),target(serial=True),target(serial=-1),target(serial=2147483648),
                   target(monitor=''),target(monitor='HEADLESS-1\n'),target(keyboard=1),target(fps='60'),
                   target(fps=120),target(fullscreen=True),target(fullscreen='fullscreen'),target(fullscreen=None),
                   target(extra='unrecognized'),target(excludeRects=[target()['rect']]*17)]
        for number in (True,float('nan'),float('inf'),-1,0,32769):
            invalid.append(target(rect=dict(x=0,y=0,width=number,height=200)))
        invalid.append(target(rect=dict(x=0,y=0,width=300)))
        for value in invalid:
            with self.subTest(value=value),self.assertRaises(ValueError):request(value)

    def test_off_other_modes_and_empty_requests_never_load_or_read_compositor(self):
        for settings in (dict(floatingPreviewInteraction='off'),dict(presentation='floating')):
            self.settings(**settings)
            self.assertEqual(self.keeper.sync(target())['state'],'ended')
            self.keeper.activation = None
        self.assertEqual(self.keeper.sync(None)['state'],'idle')
        self.assertEqual(self.hypr.reads,[])
        self.assertEqual(self.bridge.calls,[])

    def test_standard_still_previews_acquire_independent_verified_input_lease(self):
        self.settings(floatingPreviewUpdate='still',livePreviewCompatibility='standard',hoverPreview='off')
        self.assertEqual(self.keeper.sync(target())['state'],'active')
        update = self.bridge.calls[-1]
        self.assertEqual(update[2],dict(id=IDENT,address='0x123',pid=42,stable_id='18000001',tag='window-stash-'+IDENT))
        self.assertEqual(update[3],dict(target(),exitShortcut=dict(modmask=12,key='Escape'),requireSourceGeometry=False))
        self.assertEqual([call[0] for call in self.bridge.calls],['ensure','update'])
        self.assertEqual(self.stash.settings()['livePreviewCompatibility'],'standard')

    def test_replaced_unowned_transitioning_and_duplicated_sources_never_acquire(self):
        for change in (dict(pid=43),dict(stableId='18000002'),dict(tags=[]),dict(workspace=dict(name='1'))):
            with self.subTest(change=change):
                self.hypr.clients[0].update(change)
                self.assertEqual(self.keeper.sync(target())['state'],'ended')
                self.keeper.activation = None
                self.hypr = FakeHypr();self.stash.hypr = self.hypr
        self.saved[0]['phase'] = 'restoring';self.save()
        self.assertEqual(self.keeper.sync(target())['state'],'ended')
        self.keeper.activation = None
        self.saved[0]['phase'] = 'stashed';self.save()
        self.hypr.clients *= 2
        self.assertEqual(self.keeper.sync(target())['state'],'ended')
        self.assertEqual(self.bridge.calls,[])

    def test_geometry_tracks_scaled_rotated_negative_outputs_and_rejects_offscreen_regions(self):
        monitor = dict(name='HEADLESS-1',x=-960,y=-100,width=800,height=1200,scale=1.25,transform=1,dpmsStatus=True)
        self.hypr.monitors = [monitor]
        good = target(rect=dict(x=-900,y=-50,width=300,height=200),
                      excludeRects=[dict(x=-920,y=-80,width=30,height=20)])
        self.assertTrue(monitor_contains(monitor,good['rect']))
        self.assertEqual(self.keeper.sync(good)['state'],'active')
        self.keeper.close()
        for bad in (target(rect=dict(x=-961,y=0,width=100,height=100)),
                    target(rect=dict(x=-100,y=500,width=101,height=100)),
                    target(rect=good['rect'],excludeRects=[dict(x=0,y=0,width=100,height=100)])):
            self.keeper.activation = None
            self.assertEqual(self.keeper.sync(bad)['state'],'ended')

    def test_display_sleep_removal_and_geometry_change_end_and_release(self):
        for change in ('sleep','remove','resize'):
            with self.subTest(change=change):
                self.hypr.monitors = FakeHypr().monitors
                self.keeper.activation = None
                self.keeper.sync(target())
                owner = self.keeper.owner
                if change == 'sleep':self.hypr.monitors[0]['dpmsStatus'] = False
                elif change == 'remove':self.hypr.monitors = []
                else:self.hypr.monitors[0]['width'] = 320
                self.assertEqual(self.keeper.sync(target())['state'],'ended')
                self.assertEqual(self.bridge.calls[-1],('release',owner))

    def test_saved_keyboard_and_frame_rate_policy_override_stale_ui_parameters(self):
        self.settings(floatingPreviewKeyboard='mouse',floatingPreviewInteractionFps='30')
        self.keeper.sync(target(keyboard=True,fps=60))
        self.assertFalse(self.bridge.calls[-1][3]['keyboard'])
        self.assertEqual(self.bridge.calls[-1][3]['fps'],30)
        self.settings(floatingPreviewKeyboard='click')
        result = self.keeper.sync(target(keyboard=True))
        self.assertEqual(result['state'],'ended')
        self.assertEqual(result['reason'],'keyboard-policy-changed')
        self.bridge.current = dict(active=True,reason='active')
        self.keeper.sync(target(serial=2,keyboard=True))
        self.assertTrue(self.bridge.calls[-1][3]['keyboard'])

    def test_folded_source_ends_input_and_cannot_reacquire_from_a_stale_ui_request(self):
        self.keeper.sync(target())
        self.saved[0]['previewFolded'] = True;self.save()
        self.assertEqual(self.keeper.sync(target())['state'], 'ended')
        self.assertEqual(self.bridge.calls[-1], ('release', self.keeper.owner))
        updates = sum(call[0] == 'update' for call in self.bridge.calls)
        self.assertEqual(self.keeper.sync(target(serial=2))['state'], 'ended')
        self.assertEqual(sum(call[0] == 'update' for call in self.bridge.calls), updates)

    def test_fold_committed_after_preflight_but_before_native_acquisition_is_rechecked(self):
        reads = 0
        validated = self.keeper._validated_source
        def between(target_value, settings, saved):
            nonlocal reads
            reads += 1
            result = validated(target_value, settings, saved)
            if reads == 2:
                # This callback is the unlocked post-build snapshot. The next
                # read must reopen the ledger before any native acquisition.
                self.saved[0]['previewFolded'] = True;self.save()
            return result
        self.keeper._validated_source = between
        self.assertEqual(self.keeper.sync(target())['state'], 'ended')
        self.assertEqual(self.bridge.calls, [('ensure',)])

    def test_final_input_update_holds_the_ledger_lock_after_building_outside_it(self):
        import fcntl
        def prepared():
            with (self.stash.directory/'lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        update = self.bridge.interaction_update
        def acquired(owner, identity, parameters):
            with (self.stash.directory/'lock').open('a') as lock:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return update(owner, identity, parameters)
        self.bridge.on_ensure = prepared;self.bridge.interaction_update = acquired
        self.assertEqual(self.keeper.sync(target())['state'], 'active')

    def test_saved_fullscreen_policy_overrides_stale_ui_and_changes_end_the_lease(self):
        self.keeper.sync(target(fullscreen='desktop'))
        self.assertEqual(self.bridge.calls[-1][3]['fullscreen'],'preview')
        self.settings(floatingPreviewFullscreen='desktop')
        state = self.keeper.sync(target(fullscreen='preview'))
        self.assertEqual((state['state'],state['reason']),('ended','fullscreen-policy-changed'))
        self.assertEqual(self.bridge.calls[-1],('release',self.keeper.owner))
        self.keeper.sync(target(serial=2,fullscreen='preview'))
        self.assertEqual(self.bridge.calls[-1][3]['fullscreen'],'desktop')

    def test_resized_source_geometry_guard_comes_from_authoritative_record_not_ui(self):
        self.saved[0]['previewResized'] = True;self.save()
        self.keeper.sync(target())
        self.assertTrue(self.bridge.calls[-1][3]['requireSourceGeometry'])
        with self.assertRaises(ValueError):
            request(target(requireSourceGeometry=False))
        self.keeper.close()
        self.saved[0].pop('previewResized');self.save()
        self.keeper.sync(target(serial=2))
        self.assertFalse(self.bridge.calls[-1][3]['requireSourceGeometry'])

    def test_workspace_scope_uses_fresh_target_monitor_and_releases_when_source_becomes_ineligible(self):
        self.saved[0]['origin'] = dict(id=3,name='3');self.save()
        self.hypr.monitors[0]['activeWorkspace'] = dict(id=4,name='4')
        # Global scope can interact with an owned source from another workspace.
        self.assertEqual(self.keeper.sync(target())['state'],'active')
        owner = self.keeper.owner
        self.settings(scope='workspace')
        self.assertEqual(self.keeper.sync(target())['state'],'ended')
        self.assertEqual(self.bridge.calls[-1],('release',owner))
        # A fresh activation on its source workspace is eligible. Do not infer
        # that workspace from the focused output or a stale frontend snapshot.
        self.hypr.monitors[0]['activeWorkspace'] = dict(id=3,name='3')
        self.assertEqual(self.keeper.sync(target(serial=2))['state'],'active')
        self.hypr.monitors[0]['activeWorkspace'] = dict(id=5,name='5')
        self.assertEqual(self.keeper.sync(target(serial=2))['state'],'ended')
        calls = copy.deepcopy(self.bridge.calls)
        self.assertEqual(self.keeper.sync(target(serial=3))['state'],'ended')
        self.assertEqual(self.bridge.calls,calls,'A stale target reacquired a source hidden by workspace scope')

    def test_workspace_scope_unknown_output_workspace_or_legacy_missing_origin_never_acquires(self):
        self.settings(scope='workspace')
        for active in (None,{},dict(id=True),dict(id='3'),dict(id=3)):
            with self.subTest(active=active):
                self.keeper.activation = None
                self.hypr.monitors[0]['activeWorkspace'] = active
                self.assertEqual(self.keeper.sync(target())['state'],'ended')
        self.assertEqual(self.bridge.calls,[])

    def fallback_fixture(self, destination='original'):
        self.settings(restoreDestination=destination)
        hypr = ControllerHypr()
        hypr.monitors = [controller_monitor('HEADLESS-1')]
        hypr.workspaces = [dict(id=1,name='1',monitor='HEADLESS-1',tiledLayout='dwindle'),
                           dict(id=4,name='4',monitor='HEADLESS-1',tiledLayout='dwindle')]
        hypr.clients[0]['floating'] = True
        control = controller_client('0x9',workspace=4,floating=True,pid=999)
        hypr.clients.append(control)
        normal_read = hypr.read
        hypr.read = lambda subject: [] if subject == 'binds' else normal_read(subject)
        root = self.stash.directory.parent
        stash = Stash(hypr,root/('fallback-'+str(len(list(root.glob('fallback-*'))))),self.stash.config,root/'fallback-state')
        with stash.locked():
            ident = stash.minimize('0x1')['id']
        hypr.monitors[0]['activeWorkspace'] = dict(id=4,name='4')
        saved = copy.deepcopy(stash.state['windows'][0])
        bridge = FakeBridge()
        keeper = InteractionKeeper(stash,bridge)
        wanted = target(id=ident)
        self.assertEqual(keeper.sync(wanted)['state'],'active')
        bridge.current = dict(active=False,owner=keeper.owner,id=ident,reason='modal-dialog',restoreRequested=True)
        return keeper,stash,hypr,bridge,wanted,saved,copy.deepcopy(control)

    def test_native_restore_requests_restore_only_the_exact_parent_before_handoff(self):
        for reason in RESTORE_REASONS:
            with self.subTest(reason=reason):
                keeper,stash,hypr,bridge,wanted,saved,control = self.fallback_fixture()
                bridge.current['reason'] = reason
                def after_parent():
                    parent = hypr.client(saved['address'])
                    self.assertEqual(parent['workspace']['id'],1)
                    self.assertNotIn(saved['tag'],parent['tags'])
                    self.assertEqual(stash.state['windows'],[])
                bridge.on_handoff = after_parent
                value = keeper.sync(wanted)
                self.assertEqual((value['state'],value['restored']),('ended',True))
                parent = hypr.client(saved['address'])
                self.assertEqual((parent['size'],parent['at'],parent['floating']),
                                 (saved['size'],saved['relativePosition'],saved['floating']))
                self.assertEqual(hypr.client(control['address']),control,'Fallback changed an unrelated same-class application')
                self.assertEqual([call[0] for call in bridge.calls],['ensure','update','status','handoff','release'])
                calls = copy.deepcopy(bridge.calls)
                self.assertEqual(keeper.sync(wanted),value)
                self.assertEqual(bridge.calls,calls,'A stale fallback request repeated its restoration or handoff')

    def test_native_restore_fallback_honors_current_workspace_destination(self):
        keeper,stash,hypr,bridge,wanted,saved,control = self.fallback_fixture('current')
        self.assertTrue(keeper.sync(wanted)['restored'])
        self.assertEqual(hypr.client(saved['address'])['workspace']['id'],4)
        self.assertEqual(hypr.client(control['address']),control)

    def test_fullscreen_fallback_finishes_real_restore_before_handoff_and_preserves_request(self):
        keeper,stash,hypr,bridge,wanted,saved,control = self.fallback_fixture()
        bridge.current['reason'] = 'source-fullscreen'
        hypr.client(saved['address']).update(fullscreen=2,fullscreenClient=2)
        dispatch = hypr.dispatch
        def guarded_geometry(name, **args):
            parent = hypr.client(saved['address'])
            if name in ('window.float','window.resize') and (parent['fullscreen'] or parent['fullscreenClient']):
                raise RuntimeError('Window is fullscreen')
            return dispatch(name, **args)
        hypr.dispatch = guarded_geometry
        def handed_off():
            self.assertEqual(stash.state['windows'],[])
            self.assertEqual(hypr.client(saved['address'])['fullscreen'],2)
        bridge.on_handoff = handed_off
        self.assertTrue(keeper.sync(wanted)['restored'])
        self.assertEqual(hypr.client(control['address']),control)
        self.assertEqual(bridge.calls[-2:], [('handoff',keeper.owner),('release',keeper.owner)])

    def test_ordinary_end_reasons_never_restore_even_with_an_unexpected_restore_flag(self):
        for reason in ('outside-click','expired','window-unavailable','workspace-changed','locked','new-window','unknown'):
            with self.subTest(reason=reason):
                keeper,stash,hypr,bridge,wanted,saved,control = self.fallback_fixture()
                bridge.current['reason'] = reason
                commands = copy.deepcopy(hypr.commands)
                self.assertNotIn('restored',keeper.sync(wanted))
                self.assertEqual(hypr.commands,commands)
                self.assertEqual(hypr.client(saved['address'])['workspace']['name'],SPECIAL)
                self.assertFalse(any(call[0]=='handoff' for call in bridge.calls))

    def test_malformed_native_restore_flags_never_authorize_window_mutation(self):
        for flag in (None,False,0,1,'true',[],{}):
            with self.subTest(flag=flag):
                keeper,stash,hypr,bridge,wanted,saved,control = self.fallback_fixture()
                bridge.current['restoreRequested'] = flag
                before = copy.deepcopy(hypr.clients)
                self.assertNotIn('restored',keeper.sync(wanted))
                self.assertEqual(hypr.clients,before)
                self.assertFalse(keeper.acquired)
                self.assertEqual(bridge.calls[-1],('release',keeper.owner))
                self.assertFalse(any(call[0]=='handoff' for call in bridge.calls))

    def test_restore_fallback_rejects_wrong_owner_or_record_id_and_releases_only_its_owner(self):
        for field in ('owner','id'):
            with self.subTest(field=field):
                keeper,stash,hypr,bridge,wanted,saved,control = self.fallback_fixture()
                bridge.current[field] = 'f'*32
                owner = keeper.owner
                commands = copy.deepcopy(hypr.commands)
                with self.assertRaisesRegex(RuntimeError,'restore request does not match'):
                    keeper.sync(wanted)
                self.assertEqual(hypr.commands,commands)
                self.assertEqual(bridge.calls[-1],('release',owner))

    def test_restore_fallback_rechecks_identity_ownership_phase_and_visibility_before_any_move(self):
        for mutation in ('pid','stable','tag','outside','missing','transition','scope','disabled','replaced-ledger'):
            with self.subTest(mutation=mutation):
                keeper,stash,hypr,bridge,wanted,saved,control = self.fallback_fixture()
                parent = hypr.client(saved['address'])
                if mutation == 'pid':parent['pid'] += 1
                elif mutation == 'stable':parent['stableId'] = 'abcdef'
                elif mutation == 'tag':parent['tags'] = []
                elif mutation == 'outside':parent['workspace'] = dict(id=4,name='4')
                elif mutation == 'scope':self.settings(scope='workspace')
                elif mutation == 'disabled':self.settings(floatingPreviewInteraction='off')
                else:
                    with stash.locked():
                        if mutation == 'missing':stash.state['windows'] = []
                        elif mutation == 'transition':stash.state['windows'][0]['phase'] = 'restoring'
                        else:
                            parent['pid'] += 1
                            stash.state['windows'][0]['pid'] = parent['pid']
                        stash.save()
                clients = copy.deepcopy(hypr.clients)
                self.assertFalse(keeper.sync(wanted)['restored'])
                self.assertEqual(hypr.clients,clients,'Fallback mutated a stale, unowned or scope-ineligible source')
                self.assertFalse(any(call[0]=='handoff' for call in bridge.calls))

    def test_legacy_fallback_keeps_bound_native_stable_identity_inside_each_dispatch(self):
        keeper,stash,hypr,bridge,wanted,saved,control = self.fallback_fixture()
        with stash.locked():
            del stash.state['windows'][0]['stableId']
            stash.save()
        original_restore = stash.restore
        replacement = None
        def replace_before_restore(*args, **kwargs):
            nonlocal replacement
            self.assertEqual(kwargs['expected']['stableId'],keeper.bound_source['stable_id'])
            hypr.client(saved['address'])['stableId'] = 'abcdef'
            replacement = copy.deepcopy(hypr.clients)
            return original_restore(*args, **kwargs)
        stash.restore = replace_before_restore
        self.assertFalse(keeper.sync(wanted)['restored'])
        self.assertEqual(hypr.clients,replacement)
        self.assertFalse(any(call[0]=='handoff' for call in bridge.calls))

    def test_failed_fallback_restore_keeps_original_metadata_retryable_and_never_hands_off(self):
        keeper,stash,hypr,bridge,wanted,saved,control = self.fallback_fixture()
        hypr.fail = 'window.resize'
        with self.assertRaisesRegex(RuntimeError,'Injected IPC failure'):keeper.sync(wanted)
        self.assertFalse(keeper.acquired)
        self.assertFalse(any(call[0]=='handoff' for call in bridge.calls))
        pending = json.loads(stash.path.read_text())['windows'][0]
        self.assertEqual(pending['phase'],'restoring')
        for field in ('id','origin','size','relativePosition','floating','tag','pid','stableId'):
            self.assertEqual(pending[field],saved[field])
        hypr.fail = None
        with stash.locked():self.assertEqual(stash.restore(saved['id'])['action'],'restored')
        self.assertEqual(stash.state['windows'],[])
        self.assertEqual(hypr.client(control['address']),control)

    def test_failed_native_handoff_still_releases_after_the_parent_restores(self):
        keeper,stash,hypr,bridge,wanted,saved,control = self.fallback_fixture()
        def reject():raise RuntimeError('Native handoff parent changed')
        bridge.on_handoff = reject
        with self.assertRaisesRegex(RuntimeError,'handoff parent changed'):keeper.sync(wanted)
        self.assertFalse(keeper.acquired)
        self.assertEqual(stash.state['windows'],[])
        self.assertEqual(hypr.client(saved['address'])['workspace']['id'],1)
        self.assertEqual(bridge.calls[-1],('release',keeper.owner))

    def test_active_lease_cannot_adopt_a_coherently_replaced_ledger_and_client_with_the_same_record_id(self):
        self.keeper.sync(target())
        self.saved[0]['pid'] += 1;self.save()
        self.hypr.clients[0]['pid'] += 1
        before = copy.deepcopy(self.hypr.clients)
        value = self.keeper.sync(target())
        self.assertEqual((value['state'],value['reason']),('ended','window-unavailable'))
        self.assertEqual(self.hypr.clients,before)
        self.assertEqual(sum(call[0]=='update' for call in self.bridge.calls),1)

    def test_exit_shortcut_parser_is_canonical_disableable_and_collision_checked_in_every_submap(self):
        self.assertEqual(exit_shortcut('alt+control+esc'),('CTRL + ALT + Escape',dict(modmask=12,key='Escape')))
        self.assertEqual(exit_shortcut(''),('',None))
        self.assertEqual(exit_shortcut('super+shift+a')[1],dict(modmask=65,key='A'))
        for submap in ('','preview-mode','reset'):
            with self.subTest(submap=submap),self.assertRaisesRegex(ValueError,'already assigned'):
                exit_shortcut('CTRL + ALT + Escape',[dict(key='Escape',modmask=12,submap=submap)])
        self.assertEqual(exit_shortcut('CTRL + ALT + Escape',[dict(key='Escape',modmask=12,enabled=False)])[1],
                         dict(modmask=12,key='Escape'))
        for bad in (True,None,'CTRL + CTRL + Escape','CTRL + ALT + Escape\n','SUPER + $(anything)'):
            with self.subTest(value=bad),self.assertRaises(ValueError):exit_shortcut(bad)

    def test_session_exit_configuration_preserves_other_settings_global_actions_and_private_ledger(self):
        data = dict(bar=dict(keep=7),plugins=[dict(id='other.plugin',custom='keep'),
                    dict(id=PLUGIN,presentation='previews',floatingPreviewInteraction='on',minimizeShortcut='SUPER + A')])
        self.stash.config.write_text(json.dumps(data));self.stash.config.chmod(0o640)
        ledger = self.stash.path.read_bytes()
        result = configure_exit_shortcut(self.stash.config,'alt+f10',self.hypr)
        self.assertEqual(result,dict(ok=True,action='interaction-exit-shortcut',key='floatingPreviewExitShortcut',binding='ALT + F10'))
        data['plugins'][1]['floatingPreviewExitShortcut'] = 'ALT + F10'
        self.assertEqual(json.loads(self.stash.config.read_text()),data)
        self.assertEqual(self.stash.config.stat().st_mode & 0o777,0o640)
        self.assertEqual(self.stash.path.read_bytes(),ledger)
        self.assertEqual(self.hypr.reads,['binds'])
        self.assertEqual(self.bridge.calls,[])
        configure_exit_shortcut(self.stash.config,'',self.hypr)
        self.assertEqual(self.hypr.reads,['binds'],'Disabling a local shortcut should not inspect or modify global bindings')
        self.assertEqual(self.stash.settings()['floatingPreviewExitShortcut'],'')

    def test_exit_shortcut_conflicts_change_neither_settings_nor_native_input_and_recheck_after_build(self):
        self.hypr.binds = [dict(key='Escape',modmask=12,description='A desktop action')]
        before = self.stash.config.read_bytes()
        with self.assertRaisesRegex(ValueError,'already assigned'):
            configure_exit_shortcut(self.stash.config,'CTRL + ALT + Escape',self.hypr)
        self.assertEqual(self.stash.config.read_bytes(),before)
        self.hypr.binds = []
        self.bridge.on_ensure = lambda:self.hypr.binds.append(dict(key='Escape',modmask=12,submap='after-native-load'))
        with self.assertRaisesRegex(ValueError,'already assigned'):self.keeper.sync(target())
        self.assertFalse(self.keeper.acquired)
        self.assertFalse(any(call[0] == 'update' for call in self.bridge.calls))

    def test_exit_shortcut_is_worker_owned_and_recompiled_only_for_new_session_or_changed_setting(self):
        self.keeper.sync(target())
        self.assertEqual(self.bridge.calls[-1][3]['exitShortcut'],dict(modmask=12,key='Escape'))
        reads = self.hypr.reads.count('binds')
        self.keeper.sync(target())
        self.assertEqual(self.hypr.reads.count('binds'),reads)
        self.settings(floatingPreviewExitShortcut='ALT + F10')
        self.keeper.sync(target())
        self.assertEqual(self.hypr.reads.count('binds'),reads+1)
        self.assertEqual(self.bridge.calls[-1][3]['exitShortcut'],dict(modmask=8,key='F10'))
        self.settings(floatingPreviewExitShortcut='')
        self.keeper.sync(target())
        self.assertIsNone(self.bridge.calls[-1][3]['exitShortcut'])
        self.assertEqual(self.hypr.reads.count('binds'),reads+1)
        with self.assertRaises(ValueError):request(dict(target(),exitShortcut=dict(modmask=0,key='a')))

    def test_local_exit_chord_round_trips_checkpoint_validation_without_becoming_a_global_action(self):
        value = valid_preferences(dict(floatingPreviewExitShortcut='control+alt+esc',minimizeShortcut='ALT + F9'))
        self.assertEqual(value,dict(floatingPreviewExitShortcut='CTRL + ALT + Escape',minimizeShortcut='ALT + F9'))
        self.assertEqual(valid_preferences(dict(floatingPreviewExitShortcut='')),dict(floatingPreviewExitShortcut=''))
        self.assertNotIn('floatingPreviewExitShortcut',valid_preferences(dict(floatingPreviewExitShortcut=True)))
        self.assertEqual(LOCAL_SHORTCUT_DEFAULTS,dict(floatingPreviewExitShortcut='CTRL + ALT + Escape'))

    def test_controller_exit_shortcut_command_returns_standard_field_acknowledgement(self):
        output = io.StringIO()
        with patch('stash.Stash',return_value=self.stash),contextlib.redirect_stdout(output):
            self.assertEqual(controller_main(['interaction-exit-shortcut','alt+F10']),0)
        value = json.loads(output.getvalue())
        self.assertEqual((value['key'],value['binding']),('floatingPreviewExitShortcut','ALT + F10'))

    def test_build_revalidates_identity_geometry_and_enablement_before_acquiring(self):
        for mutation in (lambda:self.hypr.clients.clear(),lambda:self.hypr.monitors.clear(),
                         lambda:self.settings(floatingPreviewInteraction='off')):
            with self.subTest(mutation=mutation):
                self.hypr.clients = FakeHypr().clients;self.hypr.monitors = FakeHypr().monitors
                self.settings();self.keeper.activation = None
                self.bridge.on_ensure = mutation
                self.assertEqual(self.keeper.sync(target())['state'],'ended')
                self.assertNotEqual(self.bridge.calls[-1][0],'update')

    def test_native_outside_click_is_terminal_and_periodic_sync_cannot_rearm(self):
        self.keeper.sync(target())
        owner = self.keeper.owner
        self.bridge.current = dict(active=False,reason='outside-click')
        ended = self.keeper.sync(target())
        self.assertEqual(ended['state'],'ended');self.assertEqual(ended['reason'],'outside-click')
        self.assertEqual(self.bridge.calls[-1],('release',owner))
        calls = copy.deepcopy(self.bridge.calls)
        self.assertEqual(self.keeper.sync(target()),ended)
        self.assertEqual(self.bridge.calls,calls)
        self.bridge.current = dict(active=True,reason='active')
        self.assertEqual(self.keeper.sync(target(serial=2))['state'],'active')
        self.assertNotEqual(self.keeper.owner,owner)

    def test_explicit_retarget_releases_old_owner_and_never_reuses_it(self):
        self.keeper.sync(target())
        first = self.keeper.owner
        self.bridge.current = dict(active=True,reason='active')
        self.keeper.sync(target(serial=2))
        self.assertNotEqual(self.keeper.owner,first)
        self.assertEqual([call[0] for call in self.bridge.calls],['ensure','update','release','ensure','update'])
        self.assertEqual(self.bridge.calls[2],('release',first))

    def test_partial_acquisition_error_and_eof_release_only_own_lease_once(self):
        self.bridge.error = RuntimeError('Input source changed during acquisition')
        with self.assertRaisesRegex(RuntimeError,'source changed'):self.keeper.sync(target())
        owner = self.keeper.owner
        self.keeper.close();self.keeper.close()
        self.assertEqual(self.bridge.calls[-1],('release',owner))
        self.assertEqual(sum(call[0]=='release' for call in self.bridge.calls),1)
        self.bridge.error = None
        self.bridge.current = dict(active=True,reason='active')
        self.keeper.sync(target(serial=2))
        with patch('interaction.select.select',return_value=([sys.stdin],[],[])),patch('interaction.os.read',return_value=b''):
            self.assertEqual(run_loop(sys.stdin,self.keeper,lambda value:None),0)
        self.assertFalse(self.keeper.acquired)

    def test_wrong_native_source_or_owner_acknowledgement_fails_closed(self):
        for field,value in (('id',OTHER),('owner','b'*32)):
            with self.subTest(field=field):
                self.keeper.activation = None
                self.bridge.current = dict(active=True,reason='active',**{field:value})
                with self.assertRaisesRegex(RuntimeError,'requested window and owner'):
                    self.keeper.sync(target())
                owner = self.keeper.owner
                self.keeper.close()
                self.assertEqual(self.bridge.calls[-1],('release',owner))

    def test_stream_handles_partial_messages_renews_and_exits_on_native_end(self):
        payload = json.dumps(target()).encode()+b'\n'
        real_status = self.bridge.interaction_status
        def end(owner):
            self.bridge.current = dict(active=False,reason='outside-click')
            return real_status(owner)
        self.bridge.interaction_status = end
        emitted = []
        with patch('interaction.select.select',side_effect=[([sys.stdin],[],[]),([sys.stdin],[],[]),([],[],[])]), \
                patch('interaction.os.read',side_effect=[payload[:25],payload[25:]]):
            self.assertEqual(run_loop(sys.stdin,self.keeper,emitted.append),0)
        self.assertEqual([value['state'] for value in emitted],['active','ended'])
        self.assertEqual([call[0] for call in self.bridge.calls],['ensure','update','status','release'])

    def test_bad_or_oversized_stream_always_releases(self):
        for payload in (b'[]\n',b'x'*8193,b'{"id":NaN}\n'):
            with self.subTest(payload=payload[:20]):
                self.keeper.activation = None;self.keeper.sync(target())
                with patch('interaction.select.select',return_value=([sys.stdin],[],[])), \
                        patch('interaction.os.read',return_value=payload),self.assertRaises(ValueError):
                    run_loop(sys.stdin,self.keeper,lambda value:None)
                self.assertFalse(self.keeper.acquired)

    @unittest.skipUnless(shutil.which('lua'),'Standalone Lua interpreter unavailable')
    def test_native_status_marshaling_is_json_with_control_chars_rectangles_and_counts(self):
        reason = 'outside "quoted" \\ slash\nnext\ttext\x00'
        source = ('local status={active=true,keyboard=false,keyboardFocused=true,restoreRequested=true,keyEvents=12,owner="'+IDENT+'",id="'+OTHER+'",reason='+lua(reason)
                  + ',previewFullscreen=true,fullscreen="preview",activationOrigin="client-activate",clientActivationEvents=2,pointerActivationAcknowledgements=2,keyboardActivationAcknowledgements=1,'
                  + 'heldButtons={272,273},fps=60,rect={x=-200,y=50,width=300,height=200}}\n'
                  + 'print((function()\n'+status_json('status')+'\nend)())')
        result = subprocess.run(['lua','-'],input=source,text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
        value = json.loads(result.stdout)
        self.assertIs(value['active'],True);self.assertIs(value['keyboard'],False)
        self.assertIs(value['keyboardFocused'],True);self.assertEqual(value['keyEvents'],12)
        self.assertIs(value['restoreRequested'],True)
        self.assertIs(value['previewFullscreen'],True);self.assertEqual(value['fullscreen'],'preview')
        self.assertEqual(value['activationOrigin'],'client-activate')
        self.assertEqual(value['clientActivationEvents'],2);self.assertEqual(value['pointerActivationAcknowledgements'],2)
        self.assertEqual(value['keyboardActivationAcknowledgements'],1)
        self.assertEqual(value['pointerActivationRemainingMs'],0)
        self.assertEqual(value['reason'],reason);self.assertEqual(value['heldButtons'],2)
        self.assertEqual(value['rect'],dict(x=-200,y=50,width=300,height=200))

    @unittest.skipUnless(shutil.which('lua'),'Standalone Lua interpreter unavailable')
    def test_constrained_fullscreen_requires_native_capability_before_any_acquisition(self):
        version = (Path(__file__).resolve().parents[1]/'native/version.txt').read_text().strip()
        class Native:
            def __init__(self, capability, policy):self.capability=capability;self.policy=policy
            def call(self, method, code):
                self_test.assertEqual(method,'repl')
                prelude = ('hl={plugin={window_stash_preview={'
                    'status=function() return {protocol=1,version='+lua(version)+',capabilities={constrainedFullscreen='+lua(self.capability)+'}} end,'
                    'update=function() end,interaction_release=function() end,interaction_status=function() end,'
                    'interaction_update=function(value) assert(value.fullscreen=='+lua(self.policy)+',"Wrong fullscreen policy");'
                    'return {active=true,id='+lua(IDENT)+',owner='+lua(OTHER)+'} end}}}\n')
                result = subprocess.run(['lua','-'],input=prelude+'print((function()\n'+code+'\nend)())',text=True,capture_output=True)
                if result.returncode:raise RuntimeError(result.stderr)
                return result.stdout
        self_test = self
        identity = dict(id=IDENT,address='0x123',pid=42,stable_id='18000001',tag='window-stash-'+IDENT)
        for capability, policy in ((True,'preview'),(False,'desktop')):
            bridge = InteractionBridge(Native(capability,policy))
            self.assertTrue(bridge.interaction_update(OTHER,identity,target(fullscreen=policy))['active'])
        bridge = InteractionBridge(Native(False,'preview'))
        with self.assertRaisesRegex(RuntimeError,'Reload preview support') as failure:
            bridge.interaction_update(OTHER,identity,target())
        self.assertIn(FULLSCREEN_REQUIRED,str(failure.exception))

    @unittest.skipUnless(shutil.which('lua'),'Standalone Lua interpreter unavailable')
    def test_resized_source_requires_committed_native_geometry_before_input_acquisition(self):
        version = (Path(__file__).resolve().parents[1]/'native/version.txt').read_text().strip()
        identity = dict(id=IDENT,address='0x123',pid=42,stable_id='18000001',tag='window-stash-'+IDENT)
        class Native:
            def __init__(self, state):self.state=state
            def call(self, method, code):
                self_test.assertEqual(method,'repl')
                geometry = ('source_geometry=function(value) assert(value.id=='+lua(IDENT)+' and value.stable_id=="18000001","Wrong source"); '
                            + ('return nil,"Source identity changed"' if self.state=='changed' else 'return {ready='+lua(self.state=='ready')+'}')+' end,')
                prelude = ('hl={plugin={window_stash_preview={status=function() return {protocol=1,version='+lua(version)
                           +',capabilities={sourceGeometry='+lua(self.state!='unsupported')+'}} end,'
                           +'update=function() end,interaction_release=function() end,interaction_status=function() end,'
                           +(geometry if self.state!='missing' else '')
                           +'interaction_update=function(value) '+('' if self.state=='ready' else 'error("UNEXPECTED_ACQUISITION");')
                           +'return {active=true,id='+lua(IDENT)+',owner='+lua(OTHER)+'} end}}}\n')
                result = subprocess.run(['lua','-'],input=prelude+'print((function()\n'+code+'\nend)())',text=True,capture_output=True)
                if result.returncode:raise RuntimeError(result.stderr)
                return result.stdout
        self_test = self
        for state, message in (('pending',GEOMETRY_PENDING),('missing',GEOMETRY_REQUIRED),
                               ('unsupported',GEOMETRY_REQUIRED),('changed','Source identity changed')):
            with self.subTest(state=state),self.assertRaisesRegex(RuntimeError,message) as failure:
                InteractionBridge(Native(state)).interaction_update(OTHER,identity,target(fullscreen='desktop',requireSourceGeometry=True))
            self.assertNotIn('UNEXPECTED_ACQUISITION',str(failure.exception))
        self.assertTrue(InteractionBridge(Native('ready')).interaction_update(
            OTHER,identity,target(fullscreen='desktop',requireSourceGeometry=True))['active'])

    def test_native_status_missing_or_malformed_active_flag_fails_closed(self):
        for value in ('{}','[]','{"active":1}','not-json'):
            with self.subTest(value=value),self.assertRaises((ValueError,RuntimeError)):
                InteractionBridge._status(value)


if __name__ == '__main__':
    unittest.main()
