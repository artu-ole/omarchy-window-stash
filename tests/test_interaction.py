"""Only explicit, current preview targets can acquire native input routing."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'controller'))
from interaction import InteractionBridge, InteractionKeeper, monitor_contains, request, run_loop, status_json
from stash import DEFAULTS, PLUGIN, SPECIAL, Stash, atomic_json, lua

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
        self.reads = []

    def read(self, subject):
        self.reads.append(subject)
        if subject == 'clients':return copy.deepcopy(self.clients)
        if subject == 'monitors':return copy.deepcopy(self.monitors)
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
                        floatingPreviewKeyboard='mouse',floatingPreviewInteractionFps='60',floatingPreviewControls='hover')
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
        self.assertEqual(update[3],target())
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
