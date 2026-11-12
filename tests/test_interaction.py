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
from interaction import InteractionBridge, InteractionKeeper, configure_exit_shortcut, exit_shortcut, monitor_contains, request, run_loop, status_json
from stash import DEFAULTS, LOCAL_SHORTCUT_DEFAULTS, PLUGIN, SPECIAL, Stash, atomic_json, lua, main as controller_main
from lifecycle import valid_preferences

IDENT = 'a'*32
OTHER = 'b'*32


def record(ident=IDENT):
    return dict(id=ident, address='0x123', pid=42, stableId='18000001',
                tag='window-stash-'+ident, phase='stashed')


def target(**values):
    return dict(dict(id=IDENT, serial=1, monitor='HEADLESS-1', rect=dict(x=100,y=150,width=300,height=200),
                     excludeRects=[], keyboard=False, fps=60), **values)


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
                        floatingPreviewExitShortcut='CTRL + ALT + Escape')
        self.assertEqual({key:DEFAULTS[key] for key in expected},expected)
        self.settings(**{key:True for key in expected})
        self.assertEqual({key:self.stash.settings()[key] for key in expected},expected)

    def test_requests_have_one_exact_id_bounded_numbers_and_control_regions(self):
        self.assertEqual(request(None),None)
        self.assertEqual(request(target()),target())
        invalid = [[], {}, target(id='../'+IDENT),target(serial=True),target(serial=-1),target(serial=2147483648),
                   target(monitor=''),target(monitor='HEADLESS-1\n'),target(keyboard=1),target(fps='60'),
                   target(fps=120),target(extra='unrecognized'),target(excludeRects=[target()['rect']]*17)]
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
        self.assertEqual(update[3],dict(target(),exitShortcut=dict(modmask=12,key='Escape')))
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
        self.keeper.sync(target(keyboard=True))
        self.assertTrue(self.bridge.calls[-1][3]['keyboard'])

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
        source = ('local status={active=true,keyboard=false,keyboardFocused=true,keyEvents=12,owner="'+IDENT+'",id="'+OTHER+'",reason='+lua(reason)
                  + ',heldButtons={272,273},fps=60,rect={x=-200,y=50,width=300,height=200}}\n'
                  + 'print((function()\n'+status_json('status')+'\nend)())')
        result = subprocess.run(['lua','-'],input=source,text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
        value = json.loads(result.stdout)
        self.assertIs(value['active'],True);self.assertIs(value['keyboard'],False)
        self.assertIs(value['keyboardFocused'],True);self.assertEqual(value['keyEvents'],12)
        self.assertEqual(value['reason'],reason);self.assertEqual(value['heldButtons'],2)
        self.assertEqual(value['rect'],dict(x=-200,y=50,width=300,height=200))

    def test_native_status_missing_or_malformed_active_flag_fails_closed(self):
        for value in ('{}','[]','{"active":1}','not-json'):
            with self.subTest(value=value),self.assertRaises((ValueError,RuntimeError)):
                InteractionBridge._status(value)


if __name__ == '__main__':
    unittest.main()
