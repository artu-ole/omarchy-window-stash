import copy
import json
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "controller"))
from stash import Stash, Hyprland, SPECIAL, LEGACY_SPECIAL, PLUGIN, atomic_json, eligible, lua, restored_geometry, main


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

    def dispatch_identity(self, dispatcher, record, **kw):
        c = self.client(record["address"])
        if (not c or c["pid"] != record["pid"]
                or (record.get("stableId") and c.get("stableId") != record["stableId"])):
            raise RuntimeError("Stashed window identity changed")
        self.dispatch(dispatcher, window="address:" + record["address"], **{k:v for k,v in kw.items() if k != "window"})

    def dispatch_owned(self, dispatcher, record, parked=False, **kw):
        c = self.client(record["address"])
        if (not c or c["pid"] != record["pid"]
                or (record.get("stableId") and c.get("stableId") != record["stableId"])
                or record["tag"] not in c.get("tags", [])
                or (parked and c["workspace"]["name"] != (SPECIAL if parked is True else parked))):
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

    def legacy_record(self):
        ident = self.stash.minimize()["id"]
        self.hypr.clients[0]["workspace"] = dict(id=-98, name=LEGACY_SPECIAL)
        self.hypr.commands.clear()
        return ident, self.stash.state["windows"][0]

    def test_private_workspace_migration_preserves_metadata_and_native_minimized_windows(self):
        self.hypr.clients[0].update(floating=True, size=[777, 444], at=[220, 170])
        ident, record = self.legacy_record()
        before = copy.deepcopy(record)
        native = client("0x2", workspace=-98, pid=200)
        native.update(workspace=dict(id=-98, name=LEGACY_SPECIAL), tags=["omarchy-minimized-from-2"])
        unrelated = client("0x3", workspace=-98, pid=300)
        unrelated.update(workspace=dict(id=-98, name=LEGACY_SPECIAL), tags=["window-stash-without-ledger"])
        untouched = copy.deepcopy([native, unrelated])
        self.hypr.clients.extend([native, unrelated])
        snapshot = self.stash.listing()
        self.assertEqual(snapshot["windows"], [before])
        self.assertEqual(self.hypr.clients[0]["workspace"]["name"], SPECIAL)
        self.assertEqual(self.hypr.clients[1:], untouched)
        self.assertEqual(self.hypr.commands, [("window.move", dict(window="address:0x1", workspace=SPECIAL, follow=False))])
        self.stash.listing()
        self.assertEqual(len(self.hypr.commands), 1, "Migration must be idempotent")
        self.assertEqual(self.stash.restore(ident)["action"], "restored")
        self.assertEqual(self.hypr.clients[0]["size"], [777, 444])
        self.assertEqual(self.hypr.clients[0]["at"], [220, 170])

    def test_restore_migrates_legacy_record_before_restoring(self):
        ident, _ = self.legacy_record()
        self.assertEqual(self.stash.restore(ident, "current", workspace=3)["action"], "restored")
        moves = [command[1]["workspace"] for command in self.hypr.commands
                 if isinstance(command, tuple) and command[0] == "window.move"]
        self.assertEqual(moves, [SPECIAL, "3"])
        self.assertEqual(self.stash.state["windows"], [])

    def test_legacy_migration_requires_exact_identity_and_tag(self):
        for index, change in enumerate(("pid", "stableId", "tag")):
            with self.subTest(change=change):
                hypr, stash = self.race_fixture("legacy-unowned-"+str(index))
                stash.minimize()
                target = hypr.clients[0]
                target["workspace"] = dict(id=-98, name=LEGACY_SPECIAL)
                if change == "pid": target["pid"] += 1
                elif change == "stableId": target["stableId"] = "0x222"
                else: target["tags"] = [target["tags"][0]+"-lookalike"]
                untouched = copy.deepcopy(target)
                hypr.commands.clear()
                self.assertEqual(stash.listing()["windows"], [])
                self.assertEqual(hypr.clients[0], untouched)
                self.assertEqual(hypr.commands, [])

    def test_legacy_migration_rechecks_identity_atomically_before_move(self):
        _, record = self.legacy_record()
        replacement = copy.deepcopy(self.hypr.clients[0])
        replacement["stableId"] = "0x222"
        before = copy.deepcopy(replacement)
        original = self.hypr.dispatch_owned
        def replace_before_dispatch(*args, **kwargs):
            self.hypr.clients = [replacement]
            return original(*args, **kwargs)
        self.hypr.dispatch_owned = replace_before_dispatch
        with self.assertRaisesRegex(RuntimeError, "identity changed"):
            self.stash.listing()
        self.assertEqual(self.hypr.clients, [before])
        self.assertEqual(self.hypr.commands, [])
        self.assertEqual(self.stash.state["windows"][0]["id"], record["id"])

    def test_legacy_migration_failure_keeps_record_retryable(self):
        _, record = self.legacy_record()
        before = copy.deepcopy(record)
        self.hypr.fail = "window.move"
        with self.assertRaisesRegex(RuntimeError, "Injected IPC failure"):
            self.stash.listing()
        retained = self.stash.state["windows"][0]
        for key in ("id", "origin", "size", "relativePosition", "order", "floating"):
            self.assertEqual(retained[key], before[key])
        self.assertEqual(retained["phase"], "restoring")
        self.assertEqual(json.loads(self.stash.path.read_text())["windows"][0], retained)
        self.assertEqual(self.hypr.clients[0]["workspace"]["name"], LEGACY_SPECIAL)
        self.hypr.fail = None
        self.assertEqual(self.stash.listing()["windows"][0]["phase"], "stashed")
        self.assertEqual(self.hypr.clients[0]["workspace"]["name"], SPECIAL)

    def test_legacy_migration_guard_checks_source_workspace_inside_dispatch(self):
        _, record = self.legacy_record()
        hypr = Hyprland()
        calls = []
        hypr.eval = calls.append
        hypr.dispatch_owned("window.move", record, parked=LEGACY_SPECIAL, workspace=SPECIAL, follow=False)
        self.assertEqual(len(calls), 1)
        code = calls[0]
        self.assertIn('w.workspace.name == "'+LEGACY_SPECIAL+'"', code)
        self.assertIn('workspace = "'+SPECIAL+'"', code)
        self.assertLess(code.index('if not owned'), code.index('hl.dispatch'))

    def test_native_floating_workspace_defers_minimize_to_native_dock(self):
        self.hypr.clients[0]["tags"] = ["omarchy-floating-workspace", "omarchy-mode-floated"]
        untouched = copy.deepcopy(self.hypr.clients[0])
        result = self.stash.minimize()
        self.assertEqual(result["action"], "noop")
        self.assertIn("Omarchy's dock", result["reason"])
        self.assertEqual(self.hypr.clients[0], untouched)
        self.assertEqual(self.stash.state["windows"], [])
        self.assertEqual(self.hypr.commands, [])

    def test_individual_floating_windows_on_tiled_workspaces_remain_supported(self):
        self.hypr.clients[0].update(floating=True, tags=["omarchy-floating-workspace-lookalike"])
        self.assertEqual(self.stash.minimize()["action"], "minimized")

    def test_native_floating_workspace_tag_does_not_block_existing_restore(self):
        ident = self.stash.minimize()["id"]
        self.hypr.clients[0]["tags"].append("omarchy-floating-workspace")
        self.assertEqual(self.stash.restore(ident)["action"], "restored")

    def save_mode(self, workspace, mode):
        directory = self.stash.positions.parent.parent/"workspace-layouts"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory/(str(workspace)+".lua")
        fields = 'default = "'+mode+'"' if workspace == "default" else 'workspace = "'+str(workspace)+'", mode = "'+mode+'"'
        path.write_text('o.workspace_mode({ '+fields+' })\n')
        return path

    def test_generated_native_mode_files_honor_explicit_layout_and_floating_default(self):
        self.assertFalse(self.stash.native_floating_workspace("3"))
        self.save_mode("default", "floating")
        self.assertTrue(self.stash.native_floating_workspace("3"))
        for mode in ("dwindle", "scrolling"):
            self.save_mode(3, mode)
            self.assertFalse(self.stash.native_floating_workspace("3"))
        self.save_mode(3, "floating")
        self.assertTrue(self.stash.native_floating_workspace("3"))
        for workspace in ("name:3", "special:window-stash", "0", "-1", "2147483648", "3/../default"):
            self.assertFalse(self.stash.native_floating_workspace(workspace))

    def test_native_mode_file_parser_is_bounded_and_never_evaluates_lua(self):
        path = self.save_mode(3, "floating")
        with patch('stash.subprocess.run', side_effect=AssertionError("Mode parsing started a process")):
            for text in (
                'o.workspace_mode({ workspace = "4", mode = "floating" })',
                'o.workspace_mode({ workspace = "3", mode = "floating" }); os.execute("false")',
                '-- o.workspace_mode({ workspace = "3", mode = "floating" })',
                'o.workspace_mode({ workspace = "3", mode = "floating" })'+" "*4097,
                'local mode = "floating"',
            ):
                with self.subTest(text=text[:80]):
                    path.write_text(text)
                    self.assertFalse(self.stash.native_floating_workspace("3"))
        path.write_bytes(b'\xff')
        self.assertFalse(self.stash.native_floating_workspace("3"))

    def test_restore_tiled_window_into_native_floating_mode_skips_scrolling_and_claims_it(self):
        ident = self.stash.minimize()["id"]
        self.save_mode(3, "floating")
        self.hypr.workspaces.append(dict(id=3, name="3", monitor="eDP-2", tiledLayout="scrolling"))
        before = len(self.hypr.commands)
        self.assertEqual(self.stash.restore(ident, "current", workspace=3)["action"], "restored")
        self.assertTrue(self.hypr.clients[0]["floating"])
        self.assertEqual(self.hypr.clients[0]["workspace"]["id"], 3)
        self.assertIn("omarchy-mode-floated", self.hypr.clients[0]["tags"])
        self.assertFalse(any(isinstance(command, str) for command in self.hypr.commands[before:]),
                         "Native floating restore ran the scrolling reinsertion path")

    def test_restore_individually_floating_window_into_native_mode_preserves_geometry_without_claim(self):
        self.hypr.clients[0].update(floating=True, at=[240, 170], size=[777, 444])
        ident = self.stash.minimize()["id"]
        self.save_mode("default", "floating")
        self.hypr.clients[0].update(at=[900, 600], size=[300, 200])
        self.stash.restore(ident, "current", workspace=3)
        self.assertTrue(self.hypr.clients[0]["floating"])
        self.assertEqual(self.hypr.clients[0]["at"], [240, 170])
        self.assertEqual(self.hypr.clients[0]["size"], [777, 444])
        self.assertNotIn("omarchy-mode-floated", self.hypr.clients[0]["tags"])

    def test_explicit_tiled_destination_overrides_native_floating_default(self):
        ident = self.stash.minimize()["id"]
        self.save_mode("default", "floating")
        self.save_mode(3, "scrolling")
        before = len(self.hypr.commands)
        self.stash.restore(ident, "current", workspace=3)
        self.assertFalse(self.hypr.clients[0]["floating"])
        self.assertNotIn("omarchy-mode-floated", self.hypr.clients[0]["tags"])
        self.assertTrue(any(isinstance(command, str) for command in self.hypr.commands[before:]))

    def race_fixture(self, name):
        hypr = FakeHypr()
        root = self.root/name
        stash = Stash(hypr, root/"run", root/"shell.json", root/"state")
        stash.directory.mkdir(parents=True)
        return hypr, stash

    def test_minimize_rechecks_identity_atomically_before_initial_tag(self):
        for index, change in enumerate(("pid", "stableId", "closed")):
            with self.subTest(change=change):
                hypr, stash = self.race_fixture("initial-"+str(index))
                replacement = client(workspace=7, pid=200 if change == "pid" else 100)
                replacement["stableId"] = "0x222" if change == "stableId" else "0x1"
                untouched = copy.deepcopy(replacement)
                original_save = stash.save
                def replace_after_snapshot():
                    original_save()
                    if stash.state["windows"][0]["phase"] == "preparing":
                        hypr.clients = [] if change == "closed" else [replacement]
                stash.save = replace_after_snapshot
                with self.assertRaises(RuntimeError):
                    stash.minimize()
                self.assertEqual(hypr.clients, [] if change == "closed" else [untouched])
                self.assertEqual(hypr.commands, [], "The replacement was mutated before identity validation")
                self.assertEqual(stash.state["windows"][0]["phase"], "restoring")
                self.assertEqual(stash.state["windows"][0]["pid"], 100)

    def test_minimize_guards_every_mutation_after_tagging(self):
        variants = ({}, {"fullscreen": 2}, {"pinned": True}, {"grouped": ["0x1", "0x2"]})
        for index, state in enumerate(variants):
            with self.subTest(state=state):
                hypr, stash = self.race_fixture("after-tag-"+str(index))
                hypr.clients[0].update(state)
                replacement = client(workspace=7, pid=200)
                replacement["stableId"] = "0x222"
                untouched = copy.deepcopy(replacement)
                original_dispatch = hypr.dispatch
                def replace_after_tag(name, **args):
                    result = original_dispatch(name, **args)
                    if name == "window.tag" and args["tag"].startswith("+"):
                        hypr.clients = [replacement]
                    return result
                hypr.dispatch = replace_after_tag
                with self.assertRaises(RuntimeError):
                    stash.minimize()
                self.assertEqual(hypr.clients, [untouched])
                self.assertEqual([command[0] for command in hypr.commands], ["window.tag"])

    def test_minimize_checks_identity_before_reporting_success(self):
        hypr, stash = self.race_fixture("minimize-final-read")
        replacement = client(workspace=-99, pid=200)
        replacement["workspace"]["name"] = SPECIAL
        untouched = copy.deepcopy(replacement)
        original_dispatch = hypr.dispatch
        def replace_after_move(name, **args):
            result = original_dispatch(name, **args)
            if name == "window.move" and args.get("workspace") == SPECIAL:
                hypr.clients = [replacement]
            return result
        hypr.dispatch = replace_after_move
        with self.assertRaisesRegex(RuntimeError, "identity changed"):
            stash.minimize()
        self.assertEqual(hypr.clients, [untouched])
        self.assertEqual(stash.listing()["windows"], [])

    def test_minimize_does_not_save_replacement_geometry_after_fullscreen_reset(self):
        hypr, stash = self.race_fixture("fullscreen-read")
        hypr.clients[0].update(fullscreen=2, floating=True)
        replacement = client(workspace=7, pid=200)
        replacement.update(stableId="0x222", size=[333, 222], at=[400, 300])
        untouched = copy.deepcopy(replacement)
        original_dispatch = hypr.dispatch
        def replace_after_fullscreen(name, **args):
            result = original_dispatch(name, **args)
            if name == "window.fullscreen_state":
                hypr.clients = [replacement]
            return result
        hypr.dispatch = replace_after_fullscreen
        with self.assertRaisesRegex(RuntimeError, "identity changed"):
            stash.minimize()
        self.assertEqual(hypr.clients, [untouched])
        self.assertEqual(stash.state["windows"][0]["size"], [640, 400])
        self.assertEqual(stash.state["windows"][0]["relativePosition"], [100, 150])

    def test_guarded_restore_supports_legacy_records_without_stable_id(self):
        ident = self.stash.minimize()["id"]
        del self.stash.state["windows"][0]["stableId"]
        self.assertEqual(self.stash.restore(ident)["action"], "restored")
        self.assertEqual(self.hypr.clients[0]["tags"], [])
        self.assertEqual(self.stash.state["windows"], [])

    def test_partial_minimize_failure_keeps_tagged_window_recoverable(self):
        self.hypr.fail = "window.move"
        with self.assertRaises(RuntimeError):
            self.stash.minimize()
        record = self.stash.listing()["windows"][0]
        self.assertEqual(record["phase"], "restoring")
        self.assertIn(record["tag"], self.hypr.clients[0]["tags"])
        self.hypr.fail = None
        self.assertEqual(self.stash.restore(record["id"])["action"], "restored")
        self.assertEqual(self.hypr.clients[0]["tags"], [])

    def test_normal_restore_rechecks_identity_and_ownership_before_mutating(self):
        for index, change in enumerate(("pid", "stableId", "tag", "closed")):
            with self.subTest(change=change):
                hypr, stash = self.race_fixture("restore-"+str(index))
                ident = stash.minimize()["id"]
                replacement = client(workspace=7, pid=200 if change == "pid" else 100)
                replacement["stableId"] = "0x222" if change == "stableId" else "0x1"
                untouched = copy.deepcopy(replacement)
                original_dispatch = hypr.dispatch
                def replace_before_restore(name, **args):
                    if name == "focus" and "monitor" in args:
                        hypr.clients = [] if change == "closed" else [replacement]
                    return original_dispatch(name, **args)
                hypr.dispatch = replace_before_restore
                before = len(hypr.commands)
                with self.assertRaises(RuntimeError):
                    stash.restore(ident, "current", workspace=2)
                self.assertEqual(hypr.clients, [] if change == "closed" else [untouched])
                self.assertFalse(any(command[0].startswith("window.") or "window" in command[1]
                                     for command in hypr.commands[before:] if isinstance(command, tuple)))

    def test_normal_restore_rechecks_between_window_mutations(self):
        hypr, stash = self.race_fixture("restore-after-move")
        hypr.clients[0]["floating"] = True
        ident = stash.minimize()["id"]
        replacement = client(workspace=7, pid=200)
        replacement["stableId"] = "0x222"
        untouched = copy.deepcopy(replacement)
        original_dispatch = hypr.dispatch
        def replace_after_move(name, **args):
            result = original_dispatch(name, **args)
            if name == "window.move" and args.get("workspace") == "2":
                hypr.clients = [replacement]
            return result
        hypr.dispatch = replace_after_move
        before = len(hypr.commands)
        with self.assertRaises(RuntimeError):
            stash.restore(ident, "current", workspace=2)
        self.assertEqual(hypr.clients, [untouched])
        self.assertEqual([command[0] for command in hypr.commands[before:] if isinstance(command, tuple)],
                         ["focus", "focus", "window.move"])

    def test_initial_tag_and_scrolling_restore_validate_inside_one_lua_call(self):
        ident = self.stash.minimize()["id"]
        record = self.stash.state["windows"][0]
        hypr = Hyprland()
        calls = []
        hypr.eval = calls.append
        hypr.dispatch_identity("window.tag", record, tag="+"+record["tag"])
        self.assertEqual(len(calls), 1)
        code = calls[0]
        self.assertIn("w.pid == 100", code)
        self.assertIn("w.stable_id == 1", code)
        self.assertNotIn("local owned", code, "Initial tagging must work before ownership exists")
        self.assertLess(code.index("w.stable_id"), code.index("hl.dispatch"))
        self.assertIn('hl.dispatch(hl.dsp.window.tag({window = w, tag = "+window-stash-'+ident+'"}))', code)
        before = len(self.hypr.commands)
        self.stash.restore(ident)
        scrolling = next(command for command in self.hypr.commands[before:] if isinstance(command, str))
        self.assertIn("w.pid == 100", scrolling)
        self.assertIn("w.stable_id == 1", scrolling)
        self.assertLess(scrolling.index("if not owned"), scrolling.index("hl.dispatch"))

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

    def test_fifo_uses_stash_order_and_preserves_lifo(self):
        self.hypr.clients.extend([client("0x2"),client("0x3")])
        with patch('stash.time.time_ns',side_effect=[100,200,300]):
            first=self.stash.minimize("0x1")["id"]
            second=self.stash.minimize("0x2")["id"]
            third=self.stash.minimize("0x3")["id"]
        # The ledger's array order is not the user's stash order.
        self.stash.state["windows"].reverse()
        self.assertEqual(self.stash.restore_oldest()["id"],first)
        self.assertEqual(self.stash.restore_last()["id"],third)
        self.assertEqual(self.stash.restore_oldest()["id"],second)
        self.assertEqual(self.stash.restore_oldest(),dict(ok=True,action="noop"))

    def test_fifo_respects_invoking_workspace_and_global_scope(self):
        self.hypr.clients[0]["workspace"]=dict(id=2,name="2")
        first=self.stash.minimize("0x1")["id"]
        self.hypr.clients.extend([client("0x2"),client("0x3")])
        second=self.stash.minimize("0x2")["id"]
        third=self.stash.minimize("0x3")["id"]
        self.hypr.monitors[0]["activeWorkspace"]=dict(id=4,name="4")
        self.settings(scope="workspace")
        self.assertEqual(self.stash.restore_oldest(monitor="eDP-2",workspace=1)["id"],second)
        self.assertEqual(self.stash.restore_oldest(workspace=1)["id"],third)
        self.assertEqual(self.stash.restore_oldest(workspace=1)["action"],"noop")
        self.assertEqual(self.hypr.client("0x1")["workspace"]["name"],SPECIAL)
        self.settings(scope="global")
        self.assertEqual(self.stash.restore_oldest(workspace=7)["id"],first)
        self.assertEqual(self.hypr.client("0x1")["workspace"]["id"],7)

    def test_fifo_skips_closed_and_reused_oldest_windows(self):
        self.hypr.clients.extend([client("0x2"),client("0x3")])
        self.stash.minimize("0x1")
        self.stash.minimize("0x2")
        third=self.stash.minimize("0x3")["id"]
        self.hypr.clients.remove(self.hypr.client("0x1"))
        self.hypr.client("0x2")["pid"]=101
        self.assertEqual(self.stash.restore_oldest()["id"],third)
        self.assertEqual(self.hypr.client("0x2")["workspace"]["name"],SPECIAL)
        self.assertEqual(self.stash.state["windows"],[])

    def test_fifo_retries_oldest_after_partial_restore_failure(self):
        first=self.stash.minimize("0x1")["id"]
        self.hypr.clients.append(client("0x2"))
        second=self.stash.minimize("0x2")["id"]
        self.hypr.fail="window.float"
        with self.assertRaises(RuntimeError):self.stash.restore_oldest()
        self.assertEqual({r["id"] for r in self.stash.state["windows"]},{first,second})
        self.hypr.fail=None
        self.assertEqual(self.stash.restore_oldest()["id"],first)
        self.assertEqual(self.stash.restore_oldest()["id"],second)

    def test_fifo_destination_setting_and_cli_override(self):
        self.hypr.clients[0]["workspace"]=dict(id=2,name="2")
        first=self.stash.minimize("0x1")["id"]
        self.hypr.clients.append(client("0x2",workspace=3))
        second=self.stash.minimize("0x2")["id"]
        self.settings(restoreDestination="original")
        self.assertEqual(self.stash.restore_oldest(workspace=7)["id"],first)
        self.assertEqual(self.hypr.client("0x1")["workspace"]["id"],2)
        with patch('stash.Stash',return_value=self.stash),patch('sys.stdout',new_callable=io.StringIO) as output:
            code=main(['restore-oldest','--to','current','--monitor','eDP-2','--workspace','7'])
        result=json.loads(output.getvalue())
        self.assertEqual(code,0)
        self.assertEqual(result["id"],second)
        self.assertEqual(result["workspace"]["id"],7)

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
        for style in ("arc", "glide", "cascade", "spring", "swing", "matryoshka", "matryoshka-hop", "jumping"):
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
            grouping="app",iconShape="squircle",sizePreset="100",restoreDestination="current",floatingDirection="vertical",floatingAnimation="arc",dragMotion="physics",dockSide="bottom",floatingPlacement="edges",dockCorners="theme",dockCornerRadius=12,iconFrame="hidden",dockFrame="hidden",animations="full",animationSpeed="normal",dockOpacity=100,iconOpacity=100,
            hoverPreview="off",previewSize="medium",previewPlacement="auto",previewTitles="shown",previewDelay=400,previewHideDelay=200,
            minimizeShortcut="SUPER + A",restoreLastShortcut="SUPER + Z",restoreOldestShortcut=""))

    def test_size_preset_default_and_legacy_settings(self):
        self.assertEqual(self.stash.settings()["sizePreset"], "100")
        self.settings(presentation="floating", scope="workspace", iconShape="circle", dockOpacity=72)
        result = self.stash.settings()
        self.assertEqual(result["sizePreset"], "100")
        self.assertEqual((result["presentation"], result["scope"], result["iconShape"], result["dockOpacity"]),
                         ("floating", "workspace", "circle", 72))

    def test_size_preset_choices_and_validation(self):
        for presentation in ("dock", "bubbles", "floating"):
            for size in ("50", "75", "100", "125", "150", "175", "200", "250", "300"):
                with self.subTest(presentation=presentation, size=size):
                    self.settings(sizePreset=size, presentation=presentation, animations="reduced", iconOpacity=72)
                    result = self.stash.settings()
                    self.assertEqual((result["sizePreset"], result["presentation"], result["animations"], result["iconOpacity"]),
                                     (size, presentation, "reduced", 72))
        for invalid in ("invalid", "", "25", "350", "100%", "100.0", "0100", 50, 100, 300, None, True, False, [], {}):
            with self.subTest(invalid=invalid):
                self.settings(sizePreset=invalid, presentation="bubbles", grouping="app", iconShape="squircle")
                result = self.stash.settings()
                self.assertEqual((result["sizePreset"], result["presentation"], result["grouping"], result["iconShape"]),
                                 ("100", "bubbles", "app", "squircle"))

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
        defaults = self.stash.settings()
        self.assertEqual((defaults["presentation"], defaults["floatingPlacement"], defaults["dragMotion"],
                          defaults["animations"], defaults["animationSpeed"], defaults["iconFrame"], defaults["dockFrame"]),
                         ("floating", "edges", "physics", "full", "normal", "hidden", "hidden"))
        for icons in ("shown", "hidden"):
            for dock in ("shown", "hidden"):
                self.settings(iconFrame=icons, dockFrame=dock, iconShape="circle", dockCorners="custom", dockCornerRadius=17)
                result=self.stash.settings()
                self.assertEqual((result["iconFrame"],result["dockFrame"]), (icons,dock))
                self.assertEqual((result["iconShape"],result["dockCorners"],result["dockCornerRadius"]), ("circle","custom",17))
        self.settings(iconFrame=False, dockFrame="invalid")
        self.assertEqual(self.stash.settings()["iconFrame"], "hidden")
        self.assertEqual(self.stash.settings()["dockFrame"], "hidden")

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

    def blank_monitor_fixture(self, name):
        hypr, stash = self.race_fixture(name)
        current = monitor("HEADLESS-1", 0)
        origin = monitor("HEADLESS-2", 1, x=1920)
        for output in (current, origin):
            output.update(make="", model="", serial="", description="")
        current["activeWorkspace"] = dict(id=9, name="9")
        origin["activeWorkspace"] = dict(id=19, name="19")
        hypr.monitors = [current, origin]
        hypr.workspaces = [dict(id=9, name="9", monitor=current["name"]),
                           dict(id=19, name="19", monitor=origin["name"])]
        hypr.clients[0].update(monitor=1, workspace=dict(id=19, name="19"))
        stash.minimize()
        current["activeWorkspace"] = dict(id=9, name="9")
        return hypr, stash, current, origin

    def test_disconnected_blank_origin_uses_slot_when_workspace_migrated(self):
        hypr, stash, current, origin = self.blank_monitor_fixture("blank-disconnected")
        record = stash.state["windows"][0]
        self.assertEqual(record["monitor"], "|||")
        self.assertEqual(record["monitorName"], origin["name"])
        hypr.monitors = [current]
        hypr.workspaces[1]["monitor"] = current["name"]
        target, output = stash.destination(record, "original", current["name"], 9)
        self.assertEqual((target, output["name"]), ("9", current["name"]))
        result = stash.restore(record["id"], "original", current["name"], 9)
        self.assertEqual(result["workspace"]["id"], 9)

    def test_connected_blank_origin_recreates_workspace_on_exact_output(self):
        hypr, stash, current, origin = self.blank_monitor_fixture("blank-connected")
        record = stash.state["windows"][0]
        # Empty original workspaces disappear while the window is parked.
        # The first blank output in monitors must not substitute for the origin.
        hypr.workspaces = [hypr.workspaces[0]]
        target, output = stash.destination(record, "original", current["name"], 9)
        self.assertEqual((target, output["name"]), ("19", origin["name"]))
        # A deliberate workspace migration still follows its actual owner while
        # the origin output remains connected, matching physical-output behavior.
        hypr.workspaces.append(dict(id=19, name="19", monitor=current["name"]))
        target, output = stash.destination(record, "original", current["name"], 9)
        self.assertEqual((target, output["name"]), ("19", current["name"]))

    def test_blank_legacy_origin_without_output_name_uses_slot_fallback(self):
        hypr, stash, current, origin = self.blank_monitor_fixture("blank-legacy")
        base = stash.state["windows"][0]
        for fingerprint in ("|||", "", None):
            for name in ("", None, "missing"):
                with self.subTest(fingerprint=fingerprint, name=name):
                    record = dict(base, monitor=fingerprint)
                    if name == "missing":
                        record.pop("monitorName")
                    else:
                        record["monitorName"] = name
                    target, output = stash.destination(record, "original", current["name"], 9)
                    self.assertEqual((target, output["name"]), ("9", current["name"]))
        record = dict(base)
        record.pop("monitor")
        record.pop("monitorName")
        target, output = stash.destination(record, "original", current["name"], 9)
        self.assertEqual((target, output["name"]), ("9", current["name"]))

    def test_physical_origin_fingerprint_survives_connector_rename_and_legacy_name(self):
        hypr, stash = self.race_fixture("physical-reconnect")
        hypr.clients[0]["workspace"] = dict(id=13, name="13")
        stash.minimize()
        base = stash.state["windows"][0]
        self.assertNotEqual(base["monitor"], "|||")
        # The same display can return through a differently named connector.
        hypr.monitors[0]["name"] = "DP-3"
        hypr.workspaces = []
        for missing_name in (False, True):
            with self.subTest(missing_name=missing_name):
                record = dict(base)
                if missing_name:
                    record.pop("monitorName")
                target, output = stash.destination(record, "original", "DP-3", 9)
                self.assertEqual((target, output["name"]), ("13", "DP-3"))

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
        self.assertIn('w.workspace.name == "special:window-stash"', code)
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
