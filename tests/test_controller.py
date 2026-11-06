import copy
import json
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "controller"))
from stash import Stash, Hyprland, SPECIAL, PLUGIN, atomic_json, eligible, lua, restored_geometry, main


def monitor(name="eDP-2", ident=0, x=0, width=1920):
    return dict(name=name,id=ident,x=x,y=0,width=width,height=1080,scale=1,transform=0,
                make=name,model="test",serial=str(ident),description=name,reserved=[0,26,0,0],
                focused=ident==0,activeWorkspace=dict(id=1 if ident==0 else 11,name="1"))


def client(address="0x1", workspace=1, floating=False, pid=100):
    return dict(address=address,pid=pid,stableId=address,title="Test",**{"class":"test-app"},
                workspace=dict(id=workspace,name=str(workspace)),monitor=0,at=[100,150],size=[640,400],
                floating=floating,pinned=False,fullscreen=0,fullscreenClient=0,grouped=[],tags=[],mapped=True)


class FakeHypr:
    def __init__(self):
        self.clients=[client()]
        self.monitors=[monitor()]
        self.workspaces=[dict(id=1,name="1",monitor="eDP-2",tiledLayout="dwindle")]
        self.active="0x1"
        self.commands=[]
        self.fail=None
        self.on_read=None
        self.on_close=None

    def read(self, name):
        if self.on_read: self.on_read(name)
        return copy.deepcopy(dict(clients=self.clients,monitors=self.monitors,workspaces=self.workspaces,
                                  activewindow=self.client(self.active))[name])

    def client(self, address):
        return next((c for c in self.clients if c["address"]==address),None)

    def eval(self, code): self.commands.append(code)

    def dispatch_owned(self, dispatcher, record, parked=False, **kw):
        c = self.client(record["address"])
        if (not c or c["pid"] != record["pid"] or c.get("stableId") != record.get("stableId")
                or record["tag"] not in c.get("tags", [])
                or (parked and c["workspace"]["name"] != SPECIAL)):
            raise RuntimeError("Stashed window identity changed")
        self.dispatch(dispatcher, window="address:" + record["address"], **{k:v for k,v in kw.items() if k != "window"})

    def close_stashed(self, record):
        self.dispatch_owned("window.close", record, parked=True)

    def dispatch(self, dispatcher, **kw):
        action = dispatcher
        self.commands.append((action,kw))
        if action==self.fail: raise RuntimeError("Injected IPC failure")
        c=self.client(kw.get("window", "address:"+self.active).removeprefix("address:"))
        if action=="window.close":
            if self.on_close: self.on_close(c)
            else: self.clients.remove(c)
        elif action=="window.tag":
            tag=kw["tag"]
            if tag.startswith("+"): c["tags"].append(tag[1:])
            else: c["tags"].remove(tag[1:])
        elif action=="window.move":
            if "workspace" in kw:
                ws=kw["workspace"]
                c["workspace"]=dict(id=-99 if ws==SPECIAL else int(ws),name=ws)
            elif "x" in kw: c["at"]=[kw["x"],kw["y"]]
        elif action=="window.float": c["floating"]=kw["action"]=="on"
        elif action=="window.resize": c["size"]=[kw["x"],kw["y"]]
        elif action=="window.pin": c["pinned"]=not c["pinned"] if kw["action"]=="toggle" else kw["action"]=="set"
        elif action=="window.fullscreen_state":
            c["fullscreen"]=kw["internal"]; c["fullscreenClient"]=kw["client"]
        elif action=="focus":
            if "window" in kw: self.active=kw["window"].removeprefix("address:")
            if "workspace" in kw:
                self.monitors[0]["activeWorkspace"]=dict(id=int(kw["workspace"]),name=kw["workspace"])


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.hypr=FakeHypr()
        self.stash=Stash(self.hypr,self.root/"run",self.root/"shell.json",self.root/"state")
        self.stash.directory.mkdir()

    def tearDown(self): self.temp.cleanup()

    def settings(self, **values): atomic_json(self.stash.config,dict(plugins=[dict(id=PLUGIN,**values)]))

    def test_snapshot_and_restore_floating_geometry(self):
        self.hypr.clients[0]["floating"]=True
        result=self.stash.minimize()
        self.hypr.clients[0]["at"]=[900,800]
        self.hypr.clients[0]["size"]=[300,200]
        self.stash.restore(result["id"],"current")
        self.assertEqual(self.hypr.clients[0]["at"],[100,150])
        self.assertEqual(self.hypr.clients[0]["size"],[640,400])
        self.assertTrue(self.hypr.clients[0]["floating"])
        self.assertEqual(self.stash.state["windows"],[])

    def test_lifo_and_scope(self):
        first=self.stash.minimize()["id"]
        self.hypr.clients.append(client("0x2",workspace=2))
        self.hypr.active="0x2"
        second=self.stash.minimize()["id"]
        self.settings(scope="workspace")
        self.hypr.monitors[0]["activeWorkspace"]["id"]=1
        self.assertEqual(self.stash.restore_last()["id"],first)
        self.assertEqual(self.stash.restore_last()["action"],"noop")
        self.settings(scope="global")
        self.assertEqual(self.stash.restore_last()["id"],second)

    def test_drag_motion_setting_and_legacy_default(self):
        self.settings(presentation="bubbles")
        self.assertEqual(self.stash.settings()["dragMotion"], "physics")
        self.settings(dragMotion="direct")
        self.assertEqual(self.stash.settings()["dragMotion"], "direct")
        self.settings(dragMotion="invalid")
        self.assertEqual(self.stash.settings()["dragMotion"], "physics")

    def test_floating_animation_settings_and_legacy_default(self):
        self.settings(presentation="floating")
        self.assertEqual(self.stash.settings()["floatingAnimation"], "arc")
        for style in ("arc", "glide", "cascade", "spring", "swing", "matryoshka", "matryoshka-hop"):
            self.settings(presentation="floating", floatingAnimation=style, animations="reduced")
            self.assertEqual(self.stash.settings()["floatingAnimation"], style)
            self.assertEqual(self.stash.settings()["animations"], "reduced")
        self.settings(floatingAnimation="invalid")
        self.assertEqual(self.stash.settings()["floatingAnimation"], "arc")

    def test_icon_shape_settings_and_legacy_default(self):
        self.settings(presentation="bubbles", scope="workspace")
        self.assertEqual(self.stash.settings()["iconShape"], "auto")

        for shape in ("auto", "circle", "square", "rounded", "squircle"):
            self.settings(presentation="bubbles", scope="workspace", iconShape=shape)
            settings = self.stash.settings()
            self.assertEqual(settings["iconShape"], shape)
            self.assertEqual(settings["presentation"], "bubbles")
            self.assertEqual(settings["scope"], "workspace")
        self.settings(iconShape="invalid")
        self.assertEqual(self.stash.settings()["iconShape"], "auto")

    def test_floating_dock_presentation_preserves_other_choices(self):
        self.settings(presentation="floating", scope="workspace", grouping="app", iconShape="squircle")
        self.assertEqual(self.stash.settings(),dict(presentation="floating",scope="workspace",
            grouping="app",iconShape="squircle",restoreDestination="current",floatingDirection="vertical",floatingAnimation="arc",dragMotion="physics",dockSide="bottom",floatingPlacement="edges",dockCorners="theme",dockCornerRadius=12,iconFrame="shown",dockFrame="shown",animations="full",animationSpeed="normal",dockOpacity=100,iconOpacity=100,
            hoverPreview="off",previewSize="medium",previewPlacement="auto",previewTitles="shown",previewDelay=400,previewHideDelay=200))

    def test_hover_preview_defaults_and_legacy_settings(self):
        self.settings(presentation="bubbles", scope="workspace", iconOpacity=72)
        result = self.stash.settings()
        for key, value in dict(hoverPreview="off", previewSize="medium", previewPlacement="auto",
                               previewTitles="shown", previewDelay=400, previewHideDelay=200).items():
            self.assertEqual(result[key], value)
        self.assertEqual((result["presentation"], result["scope"], result["iconOpacity"]),
                         ("bubbles", "workspace", 72))

    def test_hover_preview_choices_preserve_other_settings(self):
        choices = dict(hoverPreview=("off", "still", "live"), previewSize=("small", "medium", "large"),
                       previewPlacement=("auto", "above", "below", "left", "right"),
                       previewTitles=("shown", "hidden"))
        defaults = dict(hoverPreview="off", previewSize="medium", previewPlacement="auto", previewTitles="shown")
        for key, values in choices.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    settings = dict(hoverPreview="live", previewSize="large", previewPlacement="right",
                                    previewTitles="hidden", previewDelay=321, previewHideDelay=87,
                                    presentation="floating", grouping="app", iconShape="circle")
                    settings[key] = value
                    self.settings(**settings)
                    result = self.stash.settings()
                    for setting, expected in settings.items():
                        self.assertEqual(result[setting], expected)
            for invalid in ("invalid", "", None, True, False, 1, [], {}):
                with self.subTest(key=key, invalid=invalid):
                    self.settings(**{key: invalid, "previewDelay": 321, "previewHideDelay": 87,
                                     "presentation": "floating", "grouping": "app"})
                    result = self.stash.settings()
                    self.assertEqual(result[key], defaults[key])
                    self.assertEqual((result["previewDelay"], result["previewHideDelay"],
                                      result["presentation"], result["grouping"]), (321, 87, "floating", "app"))

    def test_hover_preview_timing_validation(self):
        for key, other, maximum, default in (("previewDelay", "previewHideDelay", 1500, 400),
                                             ("previewHideDelay", "previewDelay", 1000, 200)):
            for value in (0, 1, 123, maximum-1, maximum):
                with self.subTest(key=key, value=value):
                    self.settings(**{key: value, other: 73, "hoverPreview": "live", "previewSize": "large"})
                    result = self.stash.settings()
                    self.assertEqual(result[key], value)
                    self.assertEqual((result[other], result["hoverPreview"], result["previewSize"]), (73, "live", "large"))
            for invalid in (-1, maximum+1, 1.0, 3.5, "400", "0", True, False, None, [], {}):
                with self.subTest(key=key, invalid=invalid):
                    self.settings(**{key: invalid, other: 73, "hoverPreview": "still", "previewTitles": "hidden"})
                    result = self.stash.settings()
                    self.assertEqual(result[key], default)
                    self.assertEqual((result[other], result["hoverPreview"], result["previewTitles"]), (73, "still", "hidden"))

    def test_floating_direction_defaults_and_validation(self):
        self.settings(presentation="floating")
        self.assertEqual(self.stash.settings()["floatingDirection"],"vertical")
        for direction in ("horizontal","vertical"):
            self.settings(presentation="floating",floatingDirection=direction,iconShape="circle")
            self.assertEqual(self.stash.settings()["floatingDirection"],direction)
            self.assertEqual(self.stash.settings()["iconShape"],"circle")
        self.settings(floatingDirection="invalid")
        self.assertEqual(self.stash.settings()["floatingDirection"],"vertical")

    def test_dock_side_defaults_and_validation(self):
        self.assertEqual(self.stash.settings()["dockSide"], "bottom")
        for side in ("bottom", "top", "left", "right"):
            self.settings(dockSide=side, iconShape="squircle", floatingDirection="horizontal")
            self.assertEqual(self.stash.settings()["dockSide"], side)
            self.assertEqual(self.stash.settings()["iconShape"], "squircle")
            self.assertEqual(self.stash.settings()["floatingDirection"], "horizontal")
        self.settings(dockSide="invalid")
        self.assertEqual(self.stash.settings()["dockSide"], "bottom")

    def test_floating_placement_defaults_and_validation(self):
        self.assertEqual(self.stash.settings()["floatingPlacement"], "edges")
        for mode in ("edges", "free"):
            self.settings(floatingPlacement=mode, presentation="floating", dockSide="left")
            self.assertEqual(self.stash.settings()["floatingPlacement"], mode)
            self.assertEqual(self.stash.settings()["dockSide"], "left")
        self.settings(floatingPlacement="invalid")
        self.assertEqual(self.stash.settings()["floatingPlacement"], "edges")

    def test_dock_corner_settings_and_numeric_validation(self):
        self.assertEqual(self.stash.settings()["dockCorners"], "theme")
        self.assertEqual(self.stash.settings()["dockCornerRadius"], 12)
        for value in (0, 7, 12, 32, 64):
            self.settings(dockCorners="custom", dockCornerRadius=value, iconShape="circle")
            self.assertEqual(self.stash.settings()["dockCorners"], "custom")
            self.assertEqual(self.stash.settings()["dockCornerRadius"], value)
            self.assertEqual(self.stash.settings()["iconShape"], "circle")
        for value in (-1, 65, 1.5, True, None, "12", [], {}):
            self.settings(dockCorners="invalid", dockCornerRadius=value)
            self.assertEqual(self.stash.settings()["dockCorners"], "theme")
            self.assertEqual(self.stash.settings()["dockCornerRadius"], 12)

    def test_independent_frame_visibility_defaults_and_validation(self):
        self.assertEqual(self.stash.settings()["iconFrame"], "shown")
        self.assertEqual(self.stash.settings()["dockFrame"], "shown")
        for icons in ("shown", "hidden"):
            for dock in ("shown", "hidden"):
                self.settings(iconFrame=icons, dockFrame=dock, iconShape="circle", dockCorners="custom", dockCornerRadius=17)
                result=self.stash.settings()
                self.assertEqual((result["iconFrame"],result["dockFrame"]), (icons,dock))
                self.assertEqual((result["iconShape"],result["dockCorners"],result["dockCornerRadius"]), ("circle","custom",17))
        self.settings(iconFrame=False, dockFrame="invalid")
        self.assertEqual(self.stash.settings()["iconFrame"], "shown")
        self.assertEqual(self.stash.settings()["dockFrame"], "shown")

    def test_animation_speed_defaults_and_legacy_settings(self):
        self.assertEqual(self.stash.settings()["animationSpeed"], "normal")
        self.settings(presentation="floating", animations="reduced", hoverPreview="live", previewDelay=321)
        result = self.stash.settings()
        self.assertEqual(result["animationSpeed"], "normal")
        self.assertEqual((result["presentation"], result["animations"], result["hoverPreview"], result["previewDelay"]),
                         ("floating", "reduced", "live", 321))

    def test_animation_speed_choices_and_validation(self):
        for mode in ("full", "reduced", "off"):
            for speed in ("slow", "relaxed", "normal", "fast", "ultrafast"):
                with self.subTest(mode=mode, speed=speed):
                    self.settings(animationSpeed=speed, animations=mode, presentation="bubbles", iconOpacity=72,
                                  floatingAnimation="matryoshka-hop", previewHideDelay=87)
                    result = self.stash.settings()
                    self.assertEqual(result["animationSpeed"], speed)
                    self.assertEqual((result["animations"], result["presentation"], result["iconOpacity"],
                                      result["floatingAnimation"], result["previewHideDelay"]),
                                     (mode, "bubbles", 72, "matryoshka-hop", 87))
        for invalid in ("invalid", "", "FAST", "ultra-fast", "1.5", 1, 1.5, True, False, None, [], {}):
            with self.subTest(invalid=invalid):
                self.settings(animationSpeed=invalid, animations="reduced", presentation="floating", iconOpacity=72,
                              hoverPreview="still", previewDelay=321)
                result = self.stash.settings()
                self.assertEqual(result["animationSpeed"], "normal")
                self.assertEqual((result["animations"], result["presentation"], result["iconOpacity"],
                                  result["hoverPreview"], result["previewDelay"]),
                                 ("reduced", "floating", 72, "still", 321))

    def test_animation_modes_default_and_validation(self):
        self.assertEqual(self.stash.settings()["animations"], "full")
        for mode in ("full", "reduced", "off"):
            self.settings(animations=mode, presentation="floating", iconFrame="hidden")
            self.assertEqual(self.stash.settings()["animations"], mode)
            self.assertEqual(self.stash.settings()["iconFrame"], "hidden")
        self.settings(animations="invalid")
        self.assertEqual(self.stash.settings()["animations"], "full")

    def test_opacity_percentages_are_independent_validated_integers(self):
        for key in ("dockOpacity", "iconOpacity"):
            self.settings()
            self.assertEqual(self.stash.settings()[key], 100)
            other = "iconOpacity" if key == "dockOpacity" else "dockOpacity"
            for value in (0, 1, 35, 99, 100):
                self.settings(**{key: value, other: 72})
                self.assertEqual(self.stash.settings()[key], value)
                self.assertEqual(self.stash.settings()[other], 72)
            for invalid in (-1, 101, 50.0, 3.5, "35", True, False, None):
                self.settings(**{key: invalid})
                self.assertEqual(self.stash.settings()[key], 100)

    def test_restore_destination_capture(self):
        ident=self.stash.minimize()["id"]
        self.stash.restore(ident,"current",workspace=7)
        self.assertEqual(self.hypr.clients[0]["workspace"]["id"],7)

    def test_original_and_disconnected_slot_fallback(self):
        self.hypr.clients[0]["workspace"]=dict(id=13,name="13")
        ident=self.stash.minimize()["id"]
        record=self.stash.state["windows"][0]
        record["monitor"]="disconnected"
        self.stash.restore(ident,"original",workspace=2)
        self.assertEqual(self.hypr.clients[0]["workspace"]["id"],3)

    def test_state_survives_controller_recreation(self):
        ident=self.stash.minimize()["id"]
        other=Stash(self.hypr,self.root/"run",self.stash.config,self.root/"state")
        with other.locked(): self.assertEqual(other.listing()["windows"][0]["id"],ident)

    def test_closed_and_reused_address_is_not_restored(self):
        ident=self.stash.minimize()["id"]
        self.hypr.clients[0]["pid"]=101
        self.assertEqual(self.stash.restore(ident)["action"],"noop")
        self.assertNotEqual(self.hypr.clients[0]["workspace"]["id"],1)

    def test_unmanaged_special_workspace_untouched(self):
        self.hypr.clients[0]["workspace"]=dict(id=-99,name="special:scratchpad")
        self.assertEqual(self.stash.minimize()["action"],"noop")
        self.assertFalse(self.hypr.commands)

    def test_partial_restore_remains_recoverable(self):
        ident=self.stash.minimize()["id"]
        self.hypr.fail="window.float"
        with self.assertRaises(RuntimeError): self.stash.restore(ident)
        self.assertEqual(len(self.stash.listing()["windows"]),1)
        self.assertIn("lastError",self.stash.state["windows"][0])
        self.hypr.fail=None
        self.assertEqual(self.stash.restore(ident)["action"],"restored")

    def test_fullscreen_and_pinned_state(self):
        self.hypr.clients[0].update(fullscreen=2,fullscreenClient=2,pinned=True,floating=True)
        ident=self.stash.minimize()["id"]
        self.assertFalse(self.hypr.clients[0]["pinned"])
        self.stash.restore(ident)
        self.assertEqual(self.hypr.clients[0]["fullscreen"],2)
        self.assertTrue(self.hypr.clients[0]["pinned"])

    def test_external_restore_prunes_metadata(self):
        self.stash.minimize()
        self.hypr.clients[0]["workspace"]=dict(id=4,name="4")
        self.assertEqual(self.stash.listing()["windows"],[])

    def test_close_confirmed_window_does_not_touch_unstashed_app_windows(self):
        ident = self.stash.minimize()["id"]
        self.hypr.clients.append(client("0x2", pid=100))
        result = self.stash.close([ident, ident, "missing"])
        self.assertTrue(result["ok"])
        self.assertEqual((result["closed"], result["restored"]), (1, 0))
        self.assertEqual([c["address"] for c in self.hypr.clients], ["0x2"])
        self.assertEqual(self.stash.state["windows"], [])
        self.assertEqual(sum(c[0] == "window.close" for c in self.hypr.commands if isinstance(c, tuple)), 1)
        self.assertTrue(any(r["id"] == "missing" and r["action"] == "noop" for r in result["results"]))

    def test_close_waits_for_delayed_disappearance_and_finishes_early(self):
        ident = self.stash.minimize()["id"]
        clock = [0.0]
        requested = []
        def on_close(c): requested.append((c["address"], clock[0] + .3))
        def on_read(subject):
            if subject == "clients" and requested and clock[0] >= requested[0][1]:
                self.hypr.clients = [c for c in self.hypr.clients if c["address"] != requested[0][0]]
            elif subject == "clients" and requested:
                self.assertEqual(len(self.stash.state["windows"]), 1, "Ledger removed before actual close")
        self.hypr.on_close = on_close
        self.hypr.on_read = on_read
        with patch('stash.time.monotonic', side_effect=lambda: clock[0]), patch('stash.time.sleep', side_effect=lambda dt: clock.__setitem__(0, clock[0] + dt)):
            result = self.stash.close([ident])
        self.assertTrue(result["ok"])
        self.assertEqual(result["closed"], 1)
        self.assertLess(clock[0], .75)
        self.assertFalse(any(c[0] == "window.move" and c[1].get("workspace") != SPECIAL for c in self.hypr.commands if isinstance(c, tuple)))

    def test_close_batch_uses_one_grace_and_restores_survivors_for_prompts(self):
        first = self.stash.minimize()["id"]
        self.hypr.clients.append(client("0x2", workspace=2, floating=True))
        second = self.stash.minimize("0x2")["id"]
        self.hypr.on_close = lambda c: None
        clock = [0.0]
        with patch('stash.time.monotonic', side_effect=lambda: clock[0]), patch('stash.time.sleep', side_effect=lambda dt: clock.__setitem__(0, clock[0] + dt)):
            result = self.stash.close([first, second], workspace=7)
        self.assertTrue(result["ok"])
        self.assertEqual(result["restored"], 2)
        self.assertAlmostEqual(clock[0], .75)
        self.assertEqual({c["workspace"]["id"] for c in self.hypr.clients}, {7})
        self.assertEqual(self.stash.state["windows"], [])
        self.assertEqual(sum(c[0] == "window.close" for c in self.hypr.commands if isinstance(c, tuple)), 2)

    def test_close_all_respects_workspace_and_global_scope(self):
        first = self.stash.minimize()["id"]
        self.hypr.clients.append(client("0x2", workspace=2))
        second = self.stash.minimize("0x2")["id"]
        self.settings(scope="workspace")
        result = self.stash.close_all(workspace=1)
        self.assertEqual([r["id"] for r in result["results"]], [first])
        self.assertEqual([r["id"] for r in self.stash.state["windows"]], [second])
        self.settings(scope="global")
        result = self.stash.close_all(workspace=1)
        self.assertEqual([r["id"] for r in result["results"]], [second])
        self.assertEqual(self.stash.state["windows"], [])

    def test_close_ignores_unowned_reused_and_externally_restored_windows(self):
        for change in ('pid', 'stableId', 'tag', 'workspace'):
            with self.subTest(change=change):
                self.hypr = FakeHypr()
                self.stash.hypr = self.hypr
                self.stash.state["windows"] = []
                ident = self.stash.minimize()["id"]
                c = self.hypr.clients[0]
                if change == 'pid': c['pid'] += 1
                elif change == 'stableId': c['stableId'] = 'replacement'
                elif change == 'tag': c['tags'] = []
                else: c['workspace'] = dict(id=8, name='8')
                before = len(self.hypr.commands)
                result = self.stash.close([ident])
                self.assertEqual(result['results'][0]['action'], 'noop')
                self.assertFalse(any(c[0] == 'window.close' for c in self.hypr.commands[before:] if isinstance(c, tuple)))
                self.assertEqual(len(self.hypr.clients), 1)

    def test_close_dispatch_guard_catches_identity_change_after_query(self):
        ident = self.stash.minimize()["id"]
        original = self.hypr.close_stashed
        def replace(record):
            self.hypr.clients[0]['stableId'] = 'replacement'
            return original(record)
        self.hypr.close_stashed = replace
        result = self.stash.close([ident])
        self.assertFalse(result['ok'])
        self.assertEqual(result['failed'], 1)
        self.assertEqual(len(self.hypr.clients), 1)
        self.assertFalse(any(c[0] == 'window.close' for c in self.hypr.commands if isinstance(c, tuple)))

    def test_close_partial_dispatch_failure_preserves_failed_target(self):
        first = self.stash.minimize()["id"]
        self.hypr.clients.append(client("0x2"))
        second = self.stash.minimize("0x2")["id"]
        original = self.hypr.close_stashed
        def dispatch(record):
            if record['id'] == first: raise RuntimeError('close refused')
            return original(record)
        self.hypr.close_stashed = dispatch
        result = self.stash.close([first, second])
        self.assertFalse(result['ok'])
        self.assertEqual((result['closed'], result['failed']), (1, 1))
        self.assertIn('close refused', result['error'])
        self.assertEqual([r['id'] for r in self.stash.state['windows']], [first])
        self.assertEqual(self.stash.state['windows'][0]['lastError'], 'close refused')

    def test_close_restore_failure_keeps_recovery_metadata(self):
        ident = self.stash.minimize()["id"]
        self.hypr.on_close = lambda c: None
        self.hypr.fail = 'window.float'
        clock = [0.0]
        with patch('stash.time.monotonic', side_effect=lambda: clock[0]), patch('stash.time.sleep', side_effect=lambda dt: clock.__setitem__(0, clock[0] + dt)):
            result = self.stash.close([ident], workspace=3)
        self.assertFalse(result['ok'])
        self.assertEqual(result['failed'], 1)
        self.assertEqual(self.stash.listing()['windows'][0]['id'], ident)
        self.assertIn('lastError', self.stash.state['windows'][0])

    def test_close_survivor_identity_is_guarded_through_restoration(self):
        ident = self.stash.minimize()["id"]
        self.hypr.on_close = lambda c: None
        original = self.hypr.dispatch
        def dispatch(name, **args):
            if name == 'focus' and 'monitor' in args:
                self.hypr.clients[0]['stableId'] = 'replacement'
            return original(name, **args)
        self.hypr.dispatch = dispatch
        clock = [0.0]
        before = len(self.hypr.commands)
        with patch('stash.time.monotonic', side_effect=lambda: clock[0]), patch('stash.time.sleep', side_effect=lambda dt: clock.__setitem__(0, clock[0] + dt)):
            result = self.stash.close([ident], workspace=3)
        self.assertEqual(result['closed'], 1)
        self.assertEqual(self.hypr.clients[0]['workspace']['name'], SPECIAL)
        self.assertFalse(any(c[0] == 'window.move' for c in self.hypr.commands[before:] if isinstance(c, tuple)))

    def test_close_native_guard_validates_inside_dispatch_and_does_not_kill(self):
        ident = self.stash.minimize()["id"]
        h = Hyprland()
        calls = []
        h.eval = calls.append
        h.close_stashed(self.stash.state['windows'][0])
        self.assertEqual(len(calls), 1)
        code = calls[0]
        self.assertIn('w.pid == 100', code)
        self.assertIn('w.stable_id == 1', code)
        self.assertIn('w.workspace.name == "special:minimized"', code)
        self.assertIn('window-stash-' + ident, code)
        self.assertIn('hl.dispatch(hl.dsp.window.close({window = w}))', code)
        self.assertNotIn('window.kill', code)

    def test_close_poll_failure_does_not_speculatively_restore_or_remove(self):
        ident = self.stash.minimize()["id"]
        self.hypr.on_close = lambda c: None
        reads = [0]
        def on_read(subject):
            if subject == 'clients':
                reads[0] += 1
                if reads[0] >= 2: raise RuntimeError('compositor unavailable')
        self.hypr.on_read = on_read
        before = len(self.hypr.commands)
        result = self.stash.close([ident])
        self.assertFalse(result['ok'])
        self.assertEqual(result['failed'], 1)
        self.assertEqual(self.stash.state['windows'][0]['id'], ident)
        self.assertEqual(self.stash.state['windows'][0]['lastError'], 'compositor unavailable')
        self.assertFalse(any(c[0] == 'window.move' for c in self.hypr.commands[before:] if isinstance(c, tuple)))

    def test_close_cli_reports_partial_failure_with_nonzero_status(self):
        ident = self.stash.minimize()["id"]
        self.hypr.fail = 'window.close'
        with patch('stash.Stash', return_value=self.stash), patch('sys.stdout', new_callable=io.StringIO) as output:
            code = main(['close', ident, '--monitor', 'eDP-2', '--workspace', '3'])
        result = json.loads(output.getvalue())
        self.assertEqual(code, 1)
        self.assertFalse(result['ok'])
        self.assertEqual(result['results'][0]['id'], ident)
        self.assertEqual(result['results'][0]['action'], 'failed')

    def test_close_native_guard_normalizes_hexadecimal_ipc_stable_id(self):
        self.stash.minimize()
        record = dict(self.stash.state['windows'][0], stableId='1800001e')
        h = Hyprland()
        calls = []
        h.eval = calls.append
        h.close_stashed(record)
        self.assertIn('w.stable_id == ' + str(int('1800001e', 16)), calls[0])

    def test_rebase(self):
        self.stash.minimize()
        self.stash.rebase(1,4)
        self.assertEqual(self.stash.state["windows"][0]["origin"]["id"],4)

    def test_geometry_cross_scale_rotation(self):
        record=dict(size=[1000,800],relativePosition=[1700,900])
        m=monitor(width=1280); m.update(scale=1.25,x=-1024,transform=0)
        x,y,w,h=restored_geometry(record,m)
        self.assertGreaterEqual(x,-1024)
        self.assertLessEqual(x+w,0)
        self.assertGreaterEqual(y,26)
        self.assertLessEqual(y+h,864)

    def test_lua_string_encoding(self):
        self.assertEqual(lua('"\\\n'), '"\\"\\\\\\010"')
        self.assertNotIn("\n",lua("a\nb"))
        self.assertIn("\\",lua("å"))


if __name__=="__main__": unittest.main()
