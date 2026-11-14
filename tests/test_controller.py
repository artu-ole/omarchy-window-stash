import copy
import json
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "controller"))
from stash import Stash, Hyprland, SPECIAL, LEGACY_SPECIAL, PREFIX, PLUGIN, DEFAULTS, LOCAL_SHORTCUT_DEFAULTS, atomic_json, eligible, lua, restored_geometry, main
import shortcuts
from bridge_runtime import BUSY, bridge_gate


def monitor(name="eDP-2", ident=0, x=0, width=1920):
    return dict(name=name,id=ident,x=x,y=0,width=width,height=1080,scale=1,transform=0,
                make=name,model="test",serial=str(ident),description=name,reserved=[0,26,0,0],
                focused=ident==0,activeWorkspace=dict(id=1 if ident==0 else 11,name="1"),
                specialWorkspace=dict(id=0,name=""))


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
        self.preview_fullscreen={}

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

    def clear_preview_fullscreen(self, record):
        current = self.client(record['address'])
        if (not current or current['pid'] != record['pid'] or current.get('stableId') != record['stableId']
                or record['tag'] not in current.get('tags', []) or current['workspace']['name'] != SPECIAL):
            raise RuntimeError('Stashed window identity changed')
        stable = current.get('stableId')
        if stable in self.preview_fullscreen:
            current['fullscreenClient'] = self.preview_fullscreen.pop(stable)

    def park_owned(self, record, parked=False):
        # The production adapter sends one guarded Lua transaction. This fake
        # models its actions against client state so controller failure and
        # restoration behavior remain observable without a compositor.
        current = self.client(record["address"])
        if not current or not current["floating"]:
            self.dispatch_owned("window.float", record, parked=parked, action="on")
        else:
            if (current["pid"] != record["pid"]
                    or (record.get("stableId") and current.get("stableId") != record["stableId"])
                    or record["tag"] not in current.get("tags", [])
                    or (parked and current["workspace"]["name"] != (SPECIAL if parked is True else parked))):
                raise RuntimeError("Stashed window identity changed")
        if not self.client(record["address"])["floating"]:
            raise RuntimeError("The window could not be parked as floating")
        if self.client(record["address"])["size"] != record["size"]:
            self.dispatch_owned("window.resize", record, parked=parked,
                                x=record["size"][0], y=record["size"][1], relative=False)
        self.dispatch_owned("window.move", record, parked=parked, workspace=SPECIAL, follow=False)
        if self.client(record["address"])["size"] != record["size"]:
            self.dispatch_owned("window.resize", record, parked=True,
                                x=record["size"][0], y=record["size"][1], relative=False)

    def scrolling_width(self, record):
        c=self.client(record["address"])
        if (not c or c["pid"] != record["pid"]
                or (record.get("stableId") and c.get("stableId") != record["stableId"])
                or record["tag"] not in c.get("tags", [])):
            raise RuntimeError("Stashed window identity changed")
        return c.get("scrollingFraction")

    def release_external(self, record, workspace, native_floating=False):
        # Model the production transaction's destination/identity checks.
        c = self.client(record["address"])
        if (not c or c["pid"] != record["pid"]
                or (record.get("stableId") and c.get("stableId") != record["stableId"])
                or record["tag"] not in c.get("tags", [])
                or c["workspace"]["name"] != workspace["name"]):
            raise RuntimeError("Stashed window identity changed")
        if not record["floating"]:
            if native_floating:
                self.dispatch_owned("window.tag", record, parked=workspace["name"], tag="+omarchy-mode-floated")
            if c["floating"] != native_floating:
                self.dispatch_owned("window.float", record, parked=workspace["name"],
                                    action="on" if native_floating else "off")
            if self.client(record["address"])["floating"] != native_floating:
                raise RuntimeError("A window rule prevented release of parking state")
        self.dispatch_owned("window.tag", record, parked=workspace["name"], tag="-"+record["tag"])

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


class FullscreenCleanupIPC:
    """Run the production adapter against a small stateful native Lua API."""
    def __init__(self, record, pending, capability=True, query=True, on_clear=None):
        self.record = record
        self.pending = pending
        self.capability = capability
        self.query = query
        self.on_clear = on_clear
        self.clears = 0
        self.queries = 0

    def eval(self, script):
        value = self.pending[min(self.queries,len(self.pending)-1)]
        response = ('return nil,'+lua(str(value))) if isinstance(value,Exception) else 'return '+lua(value)
        identity = dict(id=self.record['id'],address=self.record['address'],pid=self.record['pid'],
                        stable_id=self.record['stableId'],tag=self.record['tag'])
        checks = ';'.join('assert(v.'+key+'=='+lua(value)+',"Changed cleanup identity")' for key,value in identity.items())
        functions = ('status=function() return {capabilities={constrainedFullscreen='+lua(self.capability)+'}} end,'
                     'clear_fullscreen=function(v) '+checks+';clears=clears+1;return true end')
        if self.query:
            functions += ',fullscreen_cleanup_pending=function(v) '+checks+';queries=queries+1;'+response+' end'
        prelude = ('local clears='+str(self.clears)+';local queries='+str(self.queries)+'\n'
                   'hl={plugin={window_stash_preview={'+functions+'}}}\n')
        program = (prelude+'local ok,err=pcall(function()\n'+script+'\nend)\n'
                   'print(tostring(ok));print(clears);print(queries);print(tostring(err))')
        result = subprocess.run(['lua','-'],input=program,text=True,capture_output=True,check=True)
        lines = result.stdout.splitlines()
        cleared_before = self.clears
        self.clears,self.queries = int(lines[1]),int(lines[2])
        if self.clears != cleared_before and self.on_clear:
            self.on_clear()
        if lines[0] != 'true':
            raise RuntimeError('\n'.join(lines[3:]))


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

    def test_full_width_tiled_sources_keep_original_sizes_when_parked_sequentially(self):
        self.hypr.clients[0].update(size=[1251,750], at=[-1251,30])
        self.hypr.clients.append(dict(client("0x2"),size=[1256,750],at=[12,30]))
        original_dispatch = self.hypr.dispatch
        tiled_arrivals = []
        def private_layout(name, **args):
            result = original_dispatch(name, **args)
            if name == "window.move" and args.get("workspace") == SPECIAL:
                arrived = self.hypr.client(args["window"].removeprefix("address:"))
                if not arrived["floating"]:
                    tiled_arrivals.append(arrived["address"])
                    for target in self.hypr.clients:
                        if target["workspace"]["name"] == SPECIAL and not target["floating"]:
                            target["size"] = [621,750]
                # Moving to a different monitor can adjust floating geometry.
                # The final resize must restore only the incoming source.
                arrived["size"] = [900,600]
            return result
        self.hypr.dispatch = private_layout
        first = self.stash.minimize("0x1")["id"]
        first_record = copy.deepcopy(self.stash.state["windows"][0])
        self.stash.minimize("0x2")
        self.assertEqual(tiled_arrivals, [], "A tiled arrival let the private layout resize a parked client")
        self.assertEqual([target["size"] for target in self.hypr.clients], [[1251,750],[1256,750]])
        self.assertTrue(all(target["floating"] and target["workspace"]["name"] == SPECIAL for target in self.hypr.clients))
        self.assertTrue(all(record["floating"] is False for record in self.stash.state["windows"]))
        self.assertEqual(next(record for record in self.stash.state["windows"] if record["id"] == first), first_record)
        self.assertEqual(first_record["relativePosition"], [-1251,30])
        self.assertFalse(any(isinstance(action,tuple) and action[0] == "window.move" and "x" in action[1]
                             for action in self.hypr.commands), "Parking applied an origin screen position to the private workspace")
        self.stash.restore(first, "original")
        self.assertFalse(self.hypr.client("0x1")["floating"], "An originally tiled window restored as floating")
        self.assertEqual(self.hypr.client("0x2")["size"], [1256,750])

    def test_scrolling_fraction_is_saved_before_detaching_or_parking_and_remains_immutable(self):
        self.hypr.clients[0].update(scrollingFraction=.31,grouped=["0x1","0x2"])
        original=self.hypr.dispatch
        def mutate_layout(name,**args):
            result=original(name,**args)
            if name=="window.move" and (args.get("out_of_group") or args.get("workspace")==SPECIAL):
                self.hypr.clients[0]["scrollingFraction"]=.5
            return result
        self.hypr.dispatch=mutate_layout
        ident=self.stash.minimize()["id"]
        record=copy.deepcopy(self.stash.state["windows"][0])
        self.assertEqual(record["scrollingWidth"],.31)
        self.assertEqual(self.stash.listing()["windows"],[record])
        self.hypr.clients[0].update(floating=False,size=[320,200])
        self.assertEqual(self.stash.listing()["windows"],[record],"Parking upgrade rewrote saved column fraction")
        self.stash.restore(ident)
        self.assertTrue(any(isinstance(code,str) and 'local savedColumnWidth = 0.31' in code for code in self.hypr.commands))

    def test_scrolling_fraction_snapshot_validates_finite_bounds_and_uses_owned_repl_guard(self):
        hypr=Hyprland();calls=[]
        record=dict(address="0x1",pid=100,stableId="0x1",tag="window-stash-test")
        for output,wanted in (("0.31",.31),("1",1),("0.001",.001),("0",None),("-1",None),
                              ("1.01",None),("nan",None),("inf",None),("nil",None)):
            def call(*args):calls.append(args);return output
            hypr.call=call
            self.assertEqual(hypr.scrolling_width(record),wanted)
        self.assertTrue(all(args[0]=="repl" and "w.pid == 100" in args[1]
                            and "w.stable_id == 1" in args[1] and '"window-stash-test"' in args[1]
                            for args in calls))

    @unittest.skipUnless(shutil.which("lua"), "Standalone Lua interpreter unavailable")
    def test_scrolling_reinsertion_preserves_singleton_and_vertical_fractions_without_losing_pixel_widths(self):
        prelude='''local calls={}
local ws={name="1",tiled_layout="scrolling"}
local w={address="0x1",pid=100,stable_id=1,tags={"window-stash-test"},workspace=ws,floating=false,
 size={x=initialX,y=750},layout={column={width=.5,index=0}}}
local other={address="0x2",workspace=ws,floating=false,layout={column={width=.5,index=1}}}
hl={get_window=function() return w end,get_workspace=function() return ws end,
 get_workspace_windows=function() return multi and {w,other} or {w} end,
 get_config=function(key) assert(key=="scrolling.fullscreen_on_one_column");return forced end,
 dsp={window={}},dispatch=function(action) action() end}
hl.dsp.focus=function(args) return function() table.insert(calls,"focus") end end
hl.dsp.window.float=function(args) return function()
 args.window.floating=args.action=="on"
 if args.action=="off" then args.window.layout.column={width=.5,index=multi and 2 or 0} end
end end
hl.dsp.layout=function(message) return function()
 local fraction=tonumber(message:match("colresize (.+)"));assert(fraction)
 table.insert(calls,"column:"..fraction);w.layout.column.width=fraction
 if vertical then w.size.y=750*fraction elseif not forced then w.size.x=1260*fraction end
end end
hl.dsp.window.resize=function(args) return function()
 table.insert(calls,"resize");assert(args.relative==false)
 if not vertical then w.layout.column.width=w.layout.column.width+(args.x-w.size.x)/1260 end
 if not forced then w.size.x=args.x end
end end
'''
        cases=(
            ("full-singleton",1,True,False,False,1256,1251,1,False),
            ("narrow-hidden-singleton",.31,True,False,False,1256,1256,.31,False),
            ("vertical",.78,False,True,True,1260,1260,.78,False),
            ("ordinary-narrow",.31,False,True,False,630,390,390/1260,True),
            ("ordinary-wide",.78,False,True,False,630,980,980/1260,True),
            ("legacy-full-singleton",None,True,False,False,1256,1251,1,False),
            ("legacy-vertical",None,False,True,True,1260,1260,.5,True),
        )
        for name,fraction,forced,multi,vertical,initial_x,saved_x,wanted_fraction,resized in cases:
            with self.subTest(case=name):
                expected=dict(address="0x1",pid=100,stableId="0x1",tag="window-stash-test")
                if fraction is not None:expected["scrollingWidth"]=fraction
                self.hypr.commands.clear()
                self.stash.append_scrolling("0x1","1",saved_x,expected)
                code=self.hypr.commands[-1]
                variables='initialX=%s;forced=%s;multi=%s;vertical=%s\n' % tuple(map(lua,(initial_x,forced,multi,vertical)))
                assertions='''assert(math.abs(w.layout.column.width-%s)<.000001,"Incorrect restored column fraction: "..w.layout.column.width)
local resized=false;for _,action in ipairs(calls) do if action=="resize" then resized=true end end
assert(resized==%s,"Unexpected absolute client resize")
assert(not w.floating)
''' % (lua(wanted_fraction),lua(resized))
                if resized and not vertical:assertions+='assert(w.size.x=='+lua(saved_x)+')\n'
                result=subprocess.run(["lua","-"],input=variables+prelude+'local function restore_column()\n'+code+'\nend\nrestore_column()\n'+assertions,text=True,capture_output=True)
                self.assertEqual(result.returncode,0,result.stderr)

    def test_invalid_saved_scrolling_fraction_is_never_inserted_into_lua(self):
        for invalid in (True,False,-1,0,2,float("nan"),float("inf"),"os.execute('false')"):
            with self.subTest(value=invalid):
                self.hypr.commands.clear()
                self.stash.append_scrolling("0x1","1",640,
                    dict(address="0x1",pid=100,tag="window-stash-test",scrollingWidth=invalid))
                self.assertIn("local savedColumnWidth = nil",self.hypr.commands[-1])

    def test_existing_owned_tiled_stash_records_upgrade_once_without_rewriting_restore_metadata(self):
        ident = self.stash.minimize()["id"]
        saved = copy.deepcopy(self.stash.state["windows"][0])
        self.hypr.clients[0].update(floating=False,size=[300,750])
        self.hypr.commands.clear()
        result = self.stash.listing()
        self.assertEqual(result["windows"], [saved])
        self.assertTrue(self.hypr.clients[0]["floating"])
        self.assertEqual(self.hypr.clients[0]["size"], saved["size"])
        self.assertEqual(self.hypr.clients[0]["workspace"]["name"], SPECIAL)
        actions = list(self.hypr.commands)
        self.stash.listing()
        self.assertEqual(self.hypr.commands, actions, "A settled source was configured on every listing")
        self.assertEqual(self.stash.restore(ident)["action"], "restored")
        self.assertFalse(self.hypr.clients[0]["floating"])

    def test_tiled_parking_upgrade_never_adopts_unowned_or_replaced_clients(self):
        for index, change in enumerate((dict(pid=101),dict(stableId="0x222"),dict(tags=[]))):
            with self.subTest(change=change):
                hypr, stash = self.race_fixture("park-upgrade-unowned-"+str(index))
                stash.minimize()
                hypr.clients[0].update(floating=False,size=[300,750],**change)
                untouched = copy.deepcopy(hypr.clients)
                hypr.commands.clear()
                self.assertEqual(stash.listing()["windows"], [])
                self.assertEqual(hypr.clients, untouched)
                self.assertEqual(hypr.commands, [])

    def test_tiled_parking_upgrade_rechecks_private_membership_and_identity_inside_transaction(self):
        ident = self.stash.minimize()["id"]
        self.hypr.clients[0].update(floating=False,size=[300,750])
        original = self.hypr.park_owned
        for replacement in (dict(client(),workspace=dict(id=7,name="7"),floating=False),
                            dict(copy.deepcopy(self.hypr.clients[0]),stableId="0x222")):
            replacement["tags"] = [self.stash.state["windows"][0]["tag"]]
            before = copy.deepcopy(replacement)
            def replace_then_park(record, parked=False):
                self.hypr.clients = [replacement]
                return original(record, parked=parked)
            self.hypr.park_owned = replace_then_park
            self.stash.state["windows"][0]["phase"] = "stashed"
            self.stash.state["windows"][0].pop("lastError",None)
            self.hypr.clients = [dict(copy.deepcopy(before),stableId="0x1",workspace=dict(id=-99,name=SPECIAL))]
            self.hypr.commands.clear()
            retained = self.stash.listing()["windows"][0]
            self.assertIn("identity changed",retained["lastError"])
            self.assertEqual(self.hypr.clients, [before])
            self.assertEqual(self.hypr.commands, [])
            self.assertEqual(self.stash.state["windows"][0]["id"], ident)
            self.assertEqual(self.stash.state["windows"][0]["phase"], "restoring")
        self.hypr.park_owned = original

    def test_failed_private_parking_repair_does_not_block_listing_neighbors_or_explicit_restore(self):
        ident = self.stash.minimize()["id"]
        self.hypr.clients.append(client("0x2"))
        neighbor = self.stash.minimize("0x2")["id"]
        self.hypr.clients[0].update(floating=False,size=[300,750])
        saved = copy.deepcopy(self.stash.state["windows"][0])
        original = self.hypr.park_owned
        attempts = []
        def refuse_private_repair(record, parked=False):
            attempts.append(record["id"])
            if record["id"] == ident:
                raise RuntimeError("Private workspace rule refuses floating")
            return original(record,parked=parked)
        self.hypr.park_owned = refuse_private_repair
        result = self.stash.listing()
        self.assertEqual({record["id"] for record in result["windows"]},{ident,neighbor})
        retained = next(record for record in result["windows"] if record["id"] == ident)
        self.assertEqual(retained["phase"],"restoring")
        self.assertIn("refuses floating",retained["lastError"])
        for key in ("size","relativePosition","floating","origin","monitor","order"):
            self.assertEqual(retained[key],saved[key])
        self.stash.listing()
        self.assertEqual(attempts,[ident],"A failed private repair was retried on every listing")
        self.assertEqual(self.stash.restore(ident)["action"],"restored")
        self.assertEqual(attempts,[ident],"Explicit recovery retried the same rejected private parking")
        self.assertFalse(self.hypr.client("0x1")["floating"])
        self.assertEqual(self.hypr.client("0x1")["workspace"]["id"],1)
        self.assertEqual(self.hypr.client("0x2")["workspace"]["name"],SPECIAL)

    def test_failed_minimize_can_restore_without_retrying_failed_private_parking(self):
        original = self.hypr.park_owned
        attempts = []
        def failed_after_move(record, parked=False):
            attempts.append(record["id"])
            original(record,parked=parked)
            self.hypr.client(record["address"]).update(floating=False,size=[300,750])
            raise RuntimeError("Private geometry rule rejected the final parking")
        self.hypr.park_owned = failed_after_move
        with self.assertRaisesRegex(RuntimeError,"rejected the final parking"):
            self.stash.minimize()
        retained = self.stash.state["windows"][0]
        self.assertEqual(retained["phase"],"restoring")
        self.assertEqual(retained["size"],[640,400])
        self.assertEqual(self.stash.restore(retained["id"])["action"],"restored")
        self.assertEqual(len(attempts),1,"Restore was trapped by the same private geometry failure")
        self.assertFalse(self.hypr.clients[0]["floating"])
        self.assertEqual(self.hypr.clients[0]["workspace"]["id"],1)

    def test_partial_parking_failures_remain_recoverable_with_original_tiling_metadata(self):
        for index, failed in enumerate(("window.float", "window.resize", "window.move")):
            with self.subTest(failed=failed):
                hypr, stash = self.race_fixture("parking-failure-"+str(index))
                hypr.clients[0].update(size=[1251,750],at=[-1251,30])
                if failed == "window.resize":
                    original_dispatch = hypr.dispatch
                    def adjust_on_move(name, **args):
                        result = original_dispatch(name, **args)
                        if name == "window.move" and args.get("workspace") == SPECIAL:
                            hypr.clients[0]["size"] = [900,600]
                        return result
                    hypr.dispatch = adjust_on_move
                hypr.fail = failed
                with self.assertRaisesRegex(RuntimeError,"Injected IPC failure"):
                    stash.minimize()
                retained = stash.state["windows"][0]
                self.assertEqual((retained["size"],retained["relativePosition"],retained["floating"]),
                                 ([1251,750],[-1251,30],False))
                self.assertEqual(retained["phase"], "restoring")
                self.assertEqual(json.loads(stash.path.read_text())["windows"][0],retained)
                hypr.fail = None
                self.assertEqual(stash.restore(retained["id"])["action"], "restored")
                self.assertFalse(hypr.clients[0]["floating"])

    def test_parking_verification_refuses_silent_size_or_floating_rule_failures(self):
        for index, blocked in enumerate(("window.float", "window.resize")):
            with self.subTest(blocked=blocked):
                hypr, stash = self.race_fixture("parking-rule-"+str(index))
                original_dispatch = hypr.dispatch
                def blocked_action(name, **args):
                    if name == blocked:
                        if blocked == "window.resize":hypr.clients[0]["size"]=[320,240]
                        return
                    result = original_dispatch(name,**args)
                    if blocked == "window.resize" and name == "window.move" and args.get("workspace") == SPECIAL:
                        hypr.clients[0]["size"]=[320,240]
                    return result
                hypr.dispatch = blocked_action
                with self.assertRaisesRegex(RuntimeError,"parked as floating|retain its saved size"):
                    stash.minimize()
                retained = stash.state["windows"][0]
                self.assertEqual(retained["size"],[640,400])
                self.assertFalse(retained["floating"])
                self.assertEqual(retained["phase"],"restoring")
                hypr.dispatch = original_dispatch
                self.assertEqual(stash.restore(retained["id"])["action"],"restored")

    def test_tiled_parking_accepts_client_minimum_without_changing_restore_geometry(self):
        self.hypr.clients[0].update(size=[296,190], scrollingFraction=.31)
        original_dispatch = self.hypr.dispatch
        def clamp_floating(name, **args):
            result = original_dispatch(name, **args)
            current = self.hypr.clients[0]
            if current["floating"] and name in ("window.float", "window.resize"):
                current["size"] = [max(340,current["size"][0]), max(200,current["size"][1])]
            return result
        self.hypr.dispatch = clamp_floating
        ident = self.stash.minimize()["id"]
        self.assertEqual(self.hypr.clients[0]["size"], [340,200])
        record = copy.deepcopy(self.stash.state["windows"][0])
        self.assertEqual((record["size"],record["scrollingWidth"],record["floating"],record["phase"]),
                         ([296,190],.31,False,"stashed"))
        self.assertEqual(self.stash.listing()["windows"][0],record)
        with patch.object(self.stash,"append_scrolling") as append:
            self.assertEqual(self.stash.restore(ident,"original")["action"],"restored")
            self.assertEqual(append.call_args.args[2],296)
            self.assertEqual(append.call_args.args[3]["scrollingWidth"],.31)
        self.assertFalse(self.hypr.clients[0]["floating"])
        self.assertEqual(self.stash.state["windows"],[])

    def test_parking_rejects_shrinking_invalid_and_originally_floating_size_changes(self):
        for index,(floating,size) in enumerate(((False,[700,399]),(False,[0,400]),
                                               (False,[float("nan"),400]),(False,[True,400]),
                                               (False,[1_000_001,400]),(False,[700]),
                                               (True,[700,400]))):
            with self.subTest(floating=floating,size=size):
                hypr,stash = self.race_fixture("parking-minimum-"+str(index))
                hypr.clients[0]["floating"] = floating
                original = hypr.park_owned
                def change_size(record, parked=False):
                    original(record,parked=parked)
                    hypr.clients[0]["size"] = size
                hypr.park_owned = change_size
                with self.assertRaisesRegex(RuntimeError,"retain its saved size"):
                    stash.minimize()
                record = stash.state["windows"][0]
                self.assertEqual(record["size"],[640,400])
                self.assertEqual(record["floating"],floating)
                self.assertEqual(record["phase"],"restoring")

    @unittest.skipUnless(shutil.which("lua"), "Standalone Lua interpreter unavailable")
    def test_native_parking_transaction_has_exact_guards_order_and_no_private_tiling_arrival(self):
        record = dict(address="0x1",pid=100,stableId="0x1",tag="window-stash-test",size=[1251,750])
        hypr = Hyprland()
        calls = []
        hypr.eval = calls.append
        hypr.park_owned(record)
        self.assertEqual(len(calls),1,"Parking must be one compositor transaction")
        code = calls[0]
        prelude = '''local events={}
local original={pid=100,stable_id=1,tags={"window-stash-test"},workspace={name="1"},floating=false,size={x=1251,y=750},suspended=false}
local current=original
local neighbor={workspace={name="special:window-stash"},floating=true,size={x=1256,y=750},suspended=true}
local replacement={pid=200,stable_id=2,tags={},workspace={name="7"},floating=false,size={x=333,y=222}}
hl={get_window=function(selector) assert(selector=="address:0x1");return current end,dsp={window={}},dispatch=function(action) action() end}
hl.dsp.window.float=function(args) return function() table.insert(events,"float");args.window.floating=true end end
hl.dsp.window.resize=function(args) return function()
  table.insert(events,"resize");assert(args.window.floating,"Resize was applied to a tiled window")
  assert(args.x==1251 and args.y==750 and args.relative==false)
  args.window.size={x=args.x,y=args.y};args.window.suspended=false
end end
hl.dsp.window.move=function(args) return function()
  table.insert(events,"move");assert(args.window.floating,"Private workspace received a tiled arrival")
  assert(args.workspace=="special:window-stash" and args.follow==false and args.x==nil and args.y==nil)
  if args.window.workspace.name==args.workspace then return end
  args.window.workspace={name=args.workspace};args.window.suspended=true
  if adjust_size_after_move then args.window.size={x=900,y=600} end
  if replace_after_move then current=replacement end
  if tile_after_move then args.window.floating=false end
end end
'''
        success = prelude+code+'''assert(table.concat(events,",")=="float,move")
assert(original.size.x==1251 and original.size.y==750 and original.floating)
assert(original.workspace.name=="special:window-stash")
assert(original.suspended,"Unnecessary resize woke a naturally suspended source")
assert(neighbor.size.x==1256 and neighbor.size.y==750 and neighbor.suspended)
print("PARK_OK")
'''
        result = subprocess.run(["lua","-"],input=success,text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn("PARK_OK",result.stdout)
        for setup, expected_events in (
                ('original.size={x=640,y=400}', 'float,resize,move'),
                ('original.workspace={name="special:window-stash"};original.floating=true;original.suspended=true', 'move')):
            unchanged = prelude+setup+'\n'+code+'''assert(table.concat(events,",")=="'''+expected_events+'''")
assert(original.size.x==1251 and original.size.y==750 and original.suspended)
assert(neighbor.size.x==1256 and neighbor.size.y==750 and neighbor.suspended)
'''
            result = subprocess.run(["lua","-"],input=unchanged,text=True,capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr)
        adjusted = prelude+'adjust_size_after_move=true\n'+code+'''assert(table.concat(events,",")=="float,move,resize")
assert(original.size.x==1251 and original.size.y==750 and original.floating)
assert(neighbor.size.x==1256 and neighbor.size.y==750 and neighbor.suspended)
'''
        result = subprocess.run(["lua","-"],input=adjusted,text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
        for change in ('current.pid=200','current.stable_id=2','current.tags={"window-stash-test-lookalike"}'):
            rejected = prelude+change+'\nlocal ok=pcall(function()\n'+code+'end)\nassert(not ok and #events==0)\n'
            result = subprocess.run(["lua","-"],input=rejected,text=True,capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr)
        raced = prelude+'replace_after_move=true\nlocal ok=pcall(function()\n'+code+'''end)
assert(not ok and table.concat(events,",")=="float,move")
assert(replacement.size.x==333 and replacement.size.y==222 and not replacement.floating)
'''
        result = subprocess.run(["lua","-"],input=raced,text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
        refused = prelude+'tile_after_move=true\nlocal ok=pcall(function()\n'+code+'''end)
assert(not ok and table.concat(events,",")=="float,move")
assert(neighbor.size.x==1256 and neighbor.size.y==750)
'''
        result = subprocess.run(["lua","-"],input=refused,text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)

        calls.clear()
        hypr.park_owned(record,parked=True)
        denied = prelude+'local ok=pcall(function()\n'+calls[0]+'end)\nassert(not ok and #events==0)\n'
        result = subprocess.run(["lua","-"],input=denied,text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_snapshot_separates_canonical_shortcut_defaults_from_saved_overrides(self):
        self.settings(minimizeShortcut="CTRL + F8", restoreLastShortcut="ALT + F9", restoreOldestShortcut="")
        snapshot = self.stash.listing()
        self.assertEqual(snapshot["settings"]["minimizeShortcut"], "CTRL + F8")
        self.assertEqual(snapshot["settings"]["restoreLastShortcut"], "ALT + F9")
        self.assertEqual(snapshot["shortcutDefaults"], dict(shortcuts.DEFAULT_SHORTCUTS,**LOCAL_SHORTCUT_DEFAULTS))
        snapshot["shortcutDefaults"]["minimizeShortcut"] = ""
        self.assertEqual(self.stash.listing()["shortcutDefaults"], dict(shortcuts.DEFAULT_SHORTCUTS,**LOCAL_SHORTCUT_DEFAULTS))

    def test_external_focus_restores_owned_parked_window_and_geometry(self):
        self.hypr.clients[0]["floating"] = True
        ident = self.stash.minimize()["id"]
        self.hypr.clients[0].update(at=[800, 600], size=[320, 200])
        self.hypr.active = "0x1"
        self.hypr.monitors[0]["specialWorkspace"] = dict(id=-99, name=SPECIAL)
        result = self.stash.recover_focused()
        self.assertEqual(result["id"], ident)
        self.assertEqual(result["action"], "restored")
        self.assertEqual(self.hypr.clients[0]["workspace"]["id"], 1)
        self.assertEqual(self.hypr.clients[0]["at"], [100, 150])
        self.assertEqual(self.hypr.clients[0]["size"], [640, 400])

    def test_external_focus_preserves_unrelated_focus_and_rejects_reused_identity(self):
        self.stash.minimize()
        self.hypr.monitors[0]["specialWorkspace"] = dict(id=-99, name=SPECIAL)
        self.hypr.clients.append(client("0x2", pid=200))
        self.hypr.active = "0x2"
        self.hypr.commands.clear()
        self.assertEqual(self.stash.recover_focused()["action"], "noop")
        self.assertEqual(self.hypr.commands, [])
        self.hypr.active = "0x1"
        self.hypr.clients[0]["stableId"] = "0xf"
        self.assertEqual(self.stash.recover_focused()["action"], "noop")
        self.assertEqual(self.hypr.commands, [])

    def test_external_focus_requires_ownership_tag_and_private_workspace(self):
        self.stash.minimize()
        self.hypr.monitors[0]["specialWorkspace"] = dict(id=-99, name=SPECIAL)
        original = copy.deepcopy(self.hypr.clients[0])
        self.hypr.commands.clear()
        self.hypr.clients[0]["tags"] = []
        self.assertEqual(self.stash.recover_focused()["action"], "noop")
        self.hypr.clients[0].update(original)
        self.hypr.clients[0]["workspace"] = dict(id=1, name="1")
        self.assertEqual(self.stash.recover_focused()["action"], "noop")
        self.assertEqual(self.hypr.commands, [])

    def test_external_focus_ignores_hidden_stale_focus_without_matching_visible_special_workspace(self):
        ident = self.stash.minimize()["id"]
        self.hypr.clients[0]["visible"] = False
        base = copy.deepcopy(self.hypr.monitors[0])
        missing = copy.deepcopy(base)
        missing.pop("specialWorkspace")
        unrelated = copy.deepcopy(base)
        unrelated["specialWorkspace"] = dict(id=-98, name="special:another-app")
        other = monitor("HDMI-A-1", 1, 1920)
        other["specialWorkspace"] = dict(id=-99, name=SPECIAL)
        for name, monitors in (("missing", [missing]), ("closed", [base]),
                               ("unrelated", [unrelated]), ("other monitor", [base, other])):
            with self.subTest(name=name):
                self.hypr.monitors = copy.deepcopy(monitors)
                self.hypr.commands.clear()
                self.assertEqual(self.stash.recover_focused()["action"], "noop")
                self.assertEqual(self.hypr.commands, [])
                self.assertEqual(self.stash.state["windows"][0]["id"], ident)
                self.assertEqual(self.hypr.clients[0]["workspace"]["name"], SPECIAL)

    def test_external_focus_honors_original_destination(self):
        self.settings(restoreDestination="original")
        self.stash.minimize()
        self.hypr.monitors[0]["activeWorkspace"] = dict(id=3, name="3")
        self.hypr.monitors[0]["specialWorkspace"] = dict(id=-99, name=SPECIAL)
        self.assertEqual(self.stash.recover_focused()["workspace"]["id"], 1)

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
            grouping="app",iconShape="squircle",sizePreset="100",restoreDestination="current",floatingDirection="vertical",floatingAnimation="arc",dragMotion="physics",dockSide="bottom",staticDockLock="locked",floatingPlacement="edges",dockCorners="theme",dockCornerRadius=12,iconFrame="hidden",dockFrame="hidden",animations="full",animationSpeed="normal",dockOpacity=100,iconOpacity=100,
            hoverPreview="off",livePreviewCompatibility="standard",previewSize="medium",previewPlacement="auto",previewTitles="shown",previewDelay=400,previewHideDelay=200,
            floatingPreviewSizing="free",floatingPreviewScale="100",floatingPreviewUpdate="hover",floatingPreviewResizeRate="realtime",floatingPreviewTitles="hidden",floatingPreviewFrame="hidden",floatingPreviewLock="unlocked",
            floatingPreviewInteraction="off",floatingPreviewInteractionResize="off",floatingPreviewActivation="explicit",floatingPreviewKeyboard="mouse",floatingPreviewInteractionFps="60",floatingPreviewControls="hover",floatingPreviewFullscreen="preview",
            floatingPreviewExitShortcut="CTRL + ALT + Escape",
            minimizeShortcut="SUPER + D",restoreLastShortcut="SUPER + Z",restoreOldestShortcut="SUPER + ALT + Z"))

    def test_floating_previews_default_without_changing_existing_presentation_or_hover_settings(self):
        self.settings(presentation="bubbles", scope="workspace", grouping="app", hoverPreview="off", iconOpacity=63)
        result = self.stash.settings()
        expected = dict(floatingPreviewSizing="free", floatingPreviewScale="100", floatingPreviewUpdate="hover", floatingPreviewResizeRate="realtime",
                        floatingPreviewTitles="hidden", floatingPreviewFrame="hidden", floatingPreviewLock="unlocked")
        self.assertEqual({key: result[key] for key in expected}, expected)
        self.assertEqual((result["presentation"], result["scope"], result["grouping"], result["hoverPreview"], result["iconOpacity"]),
                         ("bubbles", "workspace", "app", "off", 63))

    def test_floating_previews_choices_and_invalid_values_are_independent(self):
        choices = dict(floatingPreviewSizing=("free", "preset"), floatingPreviewResizeRate=("realtime", "balanced", "release"),
                       floatingPreviewScale=("50", "75", "100", "125", "150", "175", "200", "250", "300"),
                       floatingPreviewUpdate=("still", "hover", "live"), floatingPreviewTitles=("shown", "hidden"),
                       floatingPreviewFrame=("shown", "hidden"), floatingPreviewLock=("locked", "unlocked"),
                       floatingPreviewInteractionResize=("off", "on"))
        for key, values in choices.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    self.settings(**{key:value}, presentation="previews", hoverPreview="off", scope="workspace", iconOpacity=63)
                    result = self.stash.settings()
                    self.assertEqual(result[key], value)
                    self.assertEqual((result["presentation"], result["hoverPreview"], result["scope"], result["iconOpacity"]),
                                     ("previews", "off", "workspace", 63))
            for invalid in ("invalid", "", True, False, None, 1, 100, [], {}):
                with self.subTest(key=key, invalid=invalid):
                    self.settings(**{key:invalid}, presentation="previews", hoverPreview="still")
                    result = self.stash.settings()
                    self.assertEqual(result[key], DEFAULTS[key])
                    self.assertEqual((result["presentation"], result["hoverPreview"]), ("previews", "still"))

    def test_preview_card_geometry_persists_separately_without_changing_window_restore_geometry(self):
        self.hypr.clients[0]["floating"] = True
        ident = self.stash.minimize()["id"]
        self.hypr.commands.clear()
        before_state = self.stash.path.read_bytes()
        expected = {"output-a":{"window:0x1":[321,234], "dock:floating":[450,600]}}
        atomic_json(self.stash.positions, expected)
        for output, key, geometry in (("output-a", "preview:window:0x1", [120, 200, 380]),
                                       ("output-b", "preview:app:test-app", [-20, 90, 640]),
                                       ("output-a", "preview:window:0x1", [145, 240, 500])):
            with patch("stash.Stash", return_value=self.stash), patch("sys.stdout", new_callable=io.StringIO) as stdout:
                code = main(["preview-position", output, key, *map(str, geometry)])
            self.assertEqual(code, 0, stdout.getvalue())
            self.assertEqual(json.loads(stdout.getvalue()), dict(ok=True))
            expected.setdefault(output, {})[key] = geometry
        restarted = Stash(self.hypr,self.root/"run",self.root/"shell.json",self.root/"state")
        with restarted.locked():
            self.assertEqual(restarted.listing()["positions"], expected)
        self.assertEqual(self.stash.path.read_bytes(), before_state)
        self.assertEqual(self.hypr.commands, [], "Preview placement and sizing must not mutate the stashed window")
        self.hypr.clients[0].update(at=[900,800],size=[300,200])
        self.stash.restore(ident,"current")
        self.assertEqual(self.hypr.clients[0]["at"], [100,150])
        self.assertEqual(self.hypr.clients[0]["size"], [640,400])

    def test_invalid_preview_geometry_never_overwrites_any_saved_position(self):
        atomic_json(self.stash.positions, {"output-a":{"preview:window:0x1":[120,200,380],"window:0x1":[321,234]}})
        before = self.stash.positions.read_bytes()
        for key, geometry in (("window:0x1", [1,2,100]), ("preview:", [1,2,100]),
                               ("preview:window:0x1", [1,2,0]), ("preview:window:0x1", [1,2,-1]),
                               ("preview:window:0x1", [1,2,1_000_001]),
                               ("preview:window:0x1", [1_000_001,2,100]),
                               ("preview:window:0x1", [1,-1_000_001,100])):
            with self.subTest(key=key, geometry=geometry), patch("stash.Stash", return_value=self.stash), \
                    patch("sys.stdout", new_callable=io.StringIO) as stdout:
                self.assertEqual(main(["preview-position", "output-a", key, *map(str,geometry)]), 1)
                self.assertFalse(json.loads(stdout.getvalue())["ok"])
                self.assertEqual(self.stash.positions.read_bytes(), before)
        for invalid in ("nan", "inf", "-inf", "2.5", "100.0", "true"):
            with self.subTest(invalid=invalid), patch("sys.stderr", new_callable=io.StringIO), self.assertRaises(SystemExit):
                main(["preview-position", "output-a", "preview:window:0x1", "1", "2", invalid])
            self.assertEqual(self.stash.positions.read_bytes(), before)

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

    def test_static_dock_lock_defaults_validation_and_settings_preservation(self):
        positions = {"output-a": {"dock:static:bottom": [1250, 0], "dock:static:left": [8750, 0]},
                     "output-b": {"dock:static:bottom": [6500, 0]}}
        atomic_json(self.stash.positions, positions)
        saved = self.stash.positions.read_bytes()
        self.settings(presentation="dock", dockSide="left", scope="workspace", iconOpacity=62)
        self.assertEqual(self.stash.settings()["staticDockLock"], "locked")
        for value in ("locked", "unlocked", "invalid", "", None, True, False, 0, 1, [], {}):
            with self.subTest(value=value):
                self.settings(staticDockLock=value, presentation="dock", dockSide="left", scope="workspace", iconOpacity=62)
                before = self.stash.config.read_bytes()
                result = self.stash.listing()
                expected = value if value in ("locked", "unlocked") else "locked"
                self.assertEqual(result["settings"]["staticDockLock"], expected)
                self.assertEqual((result["settings"]["presentation"], result["settings"]["dockSide"],
                                  result["settings"]["scope"], result["settings"]["iconOpacity"]),
                                 ("dock", "left", "workspace", 62))
                self.assertEqual(result["positions"], positions)
                self.assertEqual(self.stash.positions.read_bytes(), saved)
                self.assertEqual(self.stash.config.read_bytes(), before)

    def test_static_edge_position_cli_restart_and_reset_preserve_saved_placements(self):
        expected = {"output-a": {"window:unchanged": [321, 234], "dock:floating": [450, 600]}}
        atomic_json(self.stash.positions, expected)
        sides = ("bottom", "top", "left", "right")
        for output, values in (("output-a", (0, 2500, 7500, 10000)), ("output-b", (10000, 7500, 2500, 0))):
            for side, normalized in zip(sides, values):
                key = "dock:static:"+side
                with patch("stash.Stash", return_value=self.stash), patch("sys.stdout", new_callable=io.StringIO) as stdout:
                    code = main(["position", output, key, str(normalized), "0"])
                self.assertEqual(code, 0, stdout.getvalue())
                self.assertEqual(json.loads(stdout.getvalue()), dict(ok=True))
                expected.setdefault(output, {})[key] = [normalized, 0]
        self.assertEqual(self.stash.listing()["positions"], expected)
        self.settings(staticDockLock="unlocked", presentation="dock", dockSide="right")
        restarted = Stash(self.hypr, self.root/"run", self.root/"shell.json", self.root/"state")
        with restarted.locked():
            snapshot = restarted.listing()
        self.assertEqual(snapshot["settings"]["staticDockLock"], "unlocked")
        self.assertEqual(snapshot["positions"], expected)
        positions_before = self.stash.positions.read_bytes()
        state_before = self.stash.path.read_bytes()
        entry = dict(id=PLUGIN, staticDockLock="unlocked", dockSide="right", enabled=False, hostMetadata={"keep": True})
        other = dict(id="another.plugin", value=7)
        atomic_json(self.stash.config, dict(plugins=[other, entry]))
        def runner(*args):
            return "[]" if args[0] in ("repl", "binds") else "ok"
        result = shortcuts.reset_settings(self.stash.config, DEFAULTS, runner=runner, binary=self.root/"window-stash")
        self.assertEqual(result["settings"]["staticDockLock"], "locked")
        config = json.loads(self.stash.config.read_text())
        self.assertEqual(config["plugins"][0], other)
        self.assertEqual(config["plugins"][1], dict(entry, **DEFAULTS))
        self.assertEqual(self.stash.positions.read_bytes(), positions_before)
        self.assertEqual(self.stash.path.read_bytes(), state_before)
        self.assertEqual(self.stash.listing()["positions"], expected)
        self.assertEqual(self.hypr.commands, [], "Saving and resetting placements must not mutate windows")

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

    def test_preview_fullscreen_clears_before_restore_and_preserves_original_real_fullscreen(self):
        for number, (floating, original_mode, legacy) in enumerate(((True,0,False),(False,0,True),(True,2,False))):
            with self.subTest(floating=floating, original=original_mode, legacy=legacy):
                hypr, stash = self.race_fixture('preview-fullscreen-'+str(number))
                hypr.clients[0].update(floating=floating,fullscreen=original_mode,fullscreenClient=original_mode)
                ident = stash.minimize()['id']
                saved = copy.deepcopy(stash.state['windows'][0])
                if legacy:
                    del stash.state['windows'][0]['stableId']
                current = hypr.clients[0]
                current['fullscreenClient'] = 2
                hypr.preview_fullscreen[current['stableId']] = 0
                self.assertEqual(stash.restore(ident)['action'],'restored')
                self.assertEqual((current['fullscreen'],current['fullscreenClient']),(original_mode,original_mode))
                self.assertEqual(current['size'],saved['size'])
                self.assertEqual(hypr.preview_fullscreen,{})
                self.assertEqual(stash.state['windows'],[])

    def test_preview_fullscreen_clear_is_not_saved_as_a_fullscreen_retry_request(self):
        self.hypr.clients[0]['floating'] = True
        ident = self.stash.minimize()['id']
        current = self.hypr.clients[0]
        self.hypr.preview_fullscreen[current['stableId']] = 0
        current['fullscreenClient'] = 2
        self.hypr.fail = 'window.resize'
        with self.assertRaisesRegex(RuntimeError,'Injected IPC failure'):
            self.stash.restore(ident)
        retained = self.stash.state['windows'][0]
        self.assertNotIn('restoreFullscreen',retained)
        self.assertEqual((retained['fullscreen'],retained['fullscreenClient']),(0,0))
        self.hypr.fail = None
        self.stash.restore(ident)
        self.assertEqual((current['fullscreen'],current['fullscreenClient']),(0,0))

    def test_preview_fullscreen_cleanup_rechecks_source_identity_before_any_restore_mutation(self):
        ident = self.stash.minimize()['id']
        replacement = client(pid=200)
        replacement['stableId'] = '0x222'
        def replace(_record):
            self.hypr.clients = [replacement]
        self.hypr.clear_preview_fullscreen = replace
        before = len(self.hypr.commands)
        self.assertEqual(self.stash.restore(ident)['action'],'noop')
        self.assertEqual(self.hypr.commands[before:],[])
        self.assertEqual(replacement,client(pid=200) | dict(stableId='0x222'))

    def test_native_replacement_gate_blocks_restore_before_ipc_or_ledger_changes(self):
        ident = self.stash.minimize()['id']
        before = copy.deepcopy(self.stash.state)
        before_file = self.stash.path.read_bytes()
        self.stash.hypr = Hyprland()
        environment = dict(XDG_RUNTIME_DIR=str(self.root/'bridge-runtime'),
                           HYPRLAND_INSTANCE_SIGNATURE='restore-gate-test')
        with patch.dict(os.environ,environment), patch.object(self.stash.hypr,'read') as read:
            with bridge_gate(exclusive=True), self.assertRaisesRegex(RuntimeError,BUSY):
                self.stash.restore(ident,'current',monitor='eDP-2',workspace=1,expected=before['windows'][0])
            read.assert_not_called()
        self.assertEqual(self.stash.state,before)
        self.assertEqual(self.stash.path.read_bytes(),before_file)

    def test_restore_holds_shared_native_gate_through_completion_and_releases_it_on_errors(self):
        self.stash.hypr = Hyprland()
        environment = dict(XDG_RUNTIME_DIR=str(self.root/'bridge-runtime'),
                           HYPRLAND_INSTANCE_SIGNATURE='restore-gate-test')
        def finish(*args):
            self.assertEqual(args,('exact-id','original','eDP-2',3,{'stableId':'18000001'}))
            with self.assertRaisesRegex(RuntimeError,BUSY), bridge_gate(exclusive=True):
                self.fail('Native replacement entered during a restore')
            return {'ok':True,'action':'restored'}
        with patch.dict(os.environ,environment), patch.object(self.stash,'_restore',side_effect=finish):
            self.assertEqual(self.stash.restore('exact-id','original','eDP-2',3,{'stableId':'18000001'})['action'],'restored')
            with bridge_gate(exclusive=True):
                pass
        with patch.dict(os.environ,environment), patch.object(self.stash,'_restore',side_effect=RuntimeError('Restore failed')):
            with self.assertRaisesRegex(RuntimeError,'Restore failed'):
                self.stash.restore('exact-id')
            with bridge_gate(exclusive=True):
                pass

    @unittest.skipUnless(shutil.which('lua'),'Standalone Lua interpreter unavailable')
    def test_preview_fullscreen_clear_lua_checks_optional_api_and_exact_identity(self):
        record = dict(id='a'*32,address='0x123',pid=73,stableId='18000001',tag=PREFIX+'a'*32)
        class Capture:
            def __init__(self):self.scripts=[]
            def eval(self, script):self.scripts.append(script)
        capture = Capture()
        Hyprland.clear_preview_fullscreen(capture,record)
        for api, success in (('',True),
            ('clear_fullscreen=function(v) assert(v.id=="'+record['id']+'" and v.address=="0x123" and v.pid==73 '
             'and v.stable_id=="18000001" and v.tag=="'+record['tag']+'"); return false end',True),
            ('clear_fullscreen=function() return nil,"changed identity" end',False)):
            prelude = 'hl={plugin={window_stash_preview={'+api+'}}}\n'
            program = prelude+';\n'.join('(function()\n'+script+'\nend)()' for script in capture.scripts)
            result = subprocess.run(['lua','-'],input=program,text=True,capture_output=True)
            self.assertEqual(result.returncode==0,success,result.stderr)

    @unittest.skipUnless(shutil.which('lua'),'Standalone Lua interpreter unavailable')
    def test_preview_fullscreen_cleanup_waits_for_exact_original_configure_ack(self):
        record = dict(id='a'*32,address='0x123',pid=73,stableId='18000001',tag=PREFIX+'a'*32)
        ipc = FullscreenCleanupIPC(record,[True,True,False])
        with patch('stash.time.sleep') as sleep:
            Hyprland.clear_preview_fullscreen(ipc,record)
        self.assertEqual((ipc.clears,ipc.queries),(1,3))
        self.assertEqual(sleep.call_args_list,[unittest.mock.call(.05),unittest.mock.call(.05)])

    @unittest.skipUnless(shutil.which('lua'),'Standalone Lua interpreter unavailable')
    def test_preview_fullscreen_cleanup_missing_ack_api_is_refused_before_clear(self):
        record = dict(id='a'*32,address='0x123',pid=73,stableId='18000001',tag=PREFIX+'a'*32)
        ipc = FullscreenCleanupIPC(record,[False],query=False)
        with self.assertRaisesRegex(RuntimeError,'Reload preview support'):
            Hyprland.clear_preview_fullscreen(ipc,record)
        self.assertEqual((ipc.clears,ipc.queries),(0,0))
        ipc.capability = False
        Hyprland.clear_preview_fullscreen(ipc,record)
        self.assertEqual((ipc.clears,ipc.queries),(1,0),'A legacy bridge with no cleanup API should remain optional')

    @unittest.skipUnless(shutil.which('lua'),'Standalone Lua interpreter unavailable')
    def test_preview_fullscreen_cleanup_invalid_or_stale_query_never_retries(self):
        record = dict(id='a'*32,address='0x123',pid=73,stableId='18000001',tag=PREFIX+'a'*32)
        for response, message in (('pending','Could not read'),(RuntimeError('Changed cleanup identity'),'Changed cleanup identity')):
            ipc = FullscreenCleanupIPC(record,[response])
            with self.subTest(response=response),patch('stash.time.sleep') as sleep,self.assertRaisesRegex(RuntimeError,message):
                Hyprland.clear_preview_fullscreen(ipc,record)
            self.assertEqual((ipc.clears,ipc.queries),(1,1))
            sleep.assert_not_called()

    @unittest.skipUnless(shutil.which('lua'),'Standalone Lua interpreter unavailable')
    def test_preview_fullscreen_cleanup_timeout_keeps_the_window_stashed_without_snapshot_mutation(self):
        ident = self.stash.minimize()['id']
        record = self.stash.state['windows'][0]
        current = self.hypr.clients[0]
        current['fullscreenClient'] = 2
        before = copy.deepcopy(self.stash.state)
        before_file = self.stash.path.read_bytes()
        ipc = FullscreenCleanupIPC(record,[True],on_clear=lambda:current.update(fullscreenClient=0))
        self.hypr.clear_preview_fullscreen = lambda value:Hyprland.clear_preview_fullscreen(ipc,value)
        clock = [0.0]
        def tick(_seconds):clock[0] += 1.5
        before_commands = len(self.hypr.commands)
        with patch('stash.time.monotonic',side_effect=lambda:clock[0]),patch('stash.time.sleep',side_effect=tick), \
                self.assertRaisesRegex(RuntimeError,'window remains stashed'):
            self.stash.restore(ident)
        self.assertEqual((ipc.clears,ipc.queries),(1,3))
        self.assertEqual(self.hypr.commands[before_commands:],[])
        self.assertEqual(current['workspace']['name'],SPECIAL)
        self.assertEqual(current['size'],record['size'])
        self.assertEqual(self.stash.state,before)
        self.assertEqual(self.stash.path.read_bytes(),before_file)

    def test_fullscreen_requested_while_hidden_is_cleared_for_restore_then_reapplied(self):
        for floating, internal, client_mode in ((False,2,2),(True,1,0),(True,0,2)):
            with self.subTest(floating=floating,internal=internal,client=client_mode):
                hypr,stash=self.race_fixture("restore-live-fullscreen-"+str(floating)+str(internal)+str(client_mode))
                hypr.clients[0]["floating"]=floating
                ident=stash.minimize()["id"]
                hypr.clients[0].update(fullscreen=internal,fullscreenClient=client_mode)
                dispatch=hypr.dispatch
                def reject_fullscreen_geometry(name,**args):
                    source=hypr.client("0x1")
                    if name in ("window.float","window.resize") and (source["fullscreen"] or source["fullscreenClient"]):
                        raise RuntimeError("Window is fullscreen")
                    return dispatch(name,**args)
                hypr.dispatch=reject_fullscreen_geometry
                self.assertEqual(stash.restore(ident)["action"],"restored")
                source=hypr.client("0x1")
                self.assertEqual((source["fullscreen"],source["fullscreenClient"]),(internal,client_mode))
                self.assertEqual(source["floating"],floating)
                self.assertEqual(stash.state["windows"],[])

    def test_partial_fullscreen_restore_retains_new_request_without_changing_original_snapshot(self):
        self.hypr.clients[0]["floating"]=True
        ident=self.stash.minimize()["id"]
        original=copy.deepcopy(self.stash.state["windows"][0])
        self.hypr.clients[0].update(fullscreen=2,fullscreenClient=1)
        self.hypr.fail="window.resize"
        with self.assertRaisesRegex(RuntimeError,"Injected IPC failure"):
            self.stash.restore(ident)
        pending=self.stash.state["windows"][0]
        self.assertEqual(pending["restoreFullscreen"],[2,1])
        for field in ("fullscreen","fullscreenClient","size","relativePosition","floating","origin"):
            self.assertEqual(pending[field],original[field])
        self.assertEqual((self.hypr.clients[0]["fullscreen"],self.hypr.clients[0]["fullscreenClient"]),(0,0))
        self.hypr.fail=None
        self.assertEqual(self.stash.restore(ident)["action"],"restored")
        self.assertEqual((self.hypr.clients[0]["fullscreen"],self.hypr.clients[0]["fullscreenClient"]),(2,1))
        self.assertEqual(self.stash.state["windows"],[])

    def test_external_restore_prunes_metadata(self):
        self.stash.minimize()
        self.hypr.clients[0]["workspace"]=dict(id=4,name="4")
        self.assertEqual(self.stash.listing()["windows"],[])
        self.assertFalse(self.hypr.clients[0]["floating"], "External restore leaked temporary parking state")
        self.assertEqual(self.hypr.clients[0]["tags"], [])

    def test_external_move_releases_parking_in_chosen_workspace_without_focus_or_geometry_changes(self):
        self.hypr.clients[0].update(fullscreen=2,fullscreenClient=2)
        self.stash.minimize()
        self.hypr.clients.append(client("0x2",workspace=7,pid=200))
        self.hypr.active = "0x2"
        self.hypr.clients[0].update(workspace=dict(id=4,name="4"),at=[777,333],size=[1111,555],
                                    pinned=True,fullscreen=1,fullscreenClient=1)
        neighbor = copy.deepcopy(self.hypr.clients[1])
        self.hypr.commands.clear()
        self.assertEqual(self.stash.listing()["windows"], [])
        c = self.hypr.clients[0]
        self.assertEqual((c["workspace"],c["at"],c["size"]),(dict(id=4,name="4"),[777,333],[1111,555]))
        self.assertFalse(c["floating"])
        self.assertEqual((c["pinned"],c["fullscreen"],c["fullscreenClient"]),(True,1,1))
        self.assertEqual(self.hypr.active,"0x2")
        self.assertEqual(self.hypr.clients[1],neighbor)
        self.assertEqual([name for name,_ in self.hypr.commands],["window.float","window.tag"])

    def test_external_move_into_native_floating_workspace_claims_originally_tiled_source(self):
        self.stash.minimize()
        self.save_mode(4,"floating")
        self.hypr.clients[0].update(workspace=dict(id=4,name="4"),at=[777,333],size=[1111,555])
        self.hypr.commands.clear()
        self.assertEqual(self.stash.listing()["windows"], [])
        self.assertTrue(self.hypr.clients[0]["floating"])
        self.assertEqual(self.hypr.clients[0]["tags"],["omarchy-mode-floated"])
        self.assertEqual([name for name,_ in self.hypr.commands],["window.tag","window.tag"])
        self.assertEqual((self.hypr.clients[0]["at"],self.hypr.clients[0]["size"]),([777,333],[1111,555]))

    def test_external_move_preserves_explicit_floating_source_state_and_geometry(self):
        for index, floating in enumerate((False,True)):
            with self.subTest(floating=floating):
                hypr,stash=self.race_fixture("external-original-floating-"+str(index))
                hypr.clients[0]["floating"]=True
                stash.minimize()
                hypr.clients[0].update(workspace=dict(id=4,name="4"),floating=floating,
                                        at=[777,333],size=[1111,555],pinned=True,fullscreen=1)
                expected=copy.deepcopy(hypr.clients[0]);expected["tags"]=[]
                hypr.commands.clear()
                self.assertEqual(stash.listing()["windows"],[])
                self.assertEqual(hypr.clients[0],expected)
                self.assertEqual([name for name,_ in hypr.commands],["window.tag"])

    def test_external_release_rechecks_identity_ownership_and_destination_at_transaction(self):
        changes=(dict(pid=101),dict(stableId="0x222"),dict(tags=[]),dict(workspace=dict(id=7,name="7")))
        for index,change in enumerate(changes):
            with self.subTest(change=change):
                hypr,stash=self.race_fixture("external-release-race-"+str(index))
                stash.minimize()
                hypr.clients[0]["workspace"]=dict(id=4,name="4")
                original=hypr.release_external
                untouched=[]
                def replace_then_release(record,workspace,native_floating=False):
                    hypr.clients[0].update(change)
                    untouched.append(copy.deepcopy(hypr.clients[0]))
                    return original(record,workspace,native_floating)
                hypr.release_external=replace_then_release
                hypr.commands.clear()
                retained=stash.listing()["windows"][0]
                self.assertEqual(retained["phase"],"restoring")
                self.assertEqual(hypr.clients,[untouched[0]])
                self.assertEqual(hypr.commands,[])

    def test_external_release_failure_keeps_original_restore_metadata_and_recovery(self):
        ident=self.stash.minimize()["id"]
        original=copy.deepcopy(self.stash.state["windows"][0])
        self.hypr.clients[0]["workspace"]=dict(id=4,name="4")
        dispatch=self.hypr.dispatch
        def refuse_float(name,**args):
            if name!="window.float":return dispatch(name,**args)
        self.hypr.dispatch=refuse_float
        retained=self.stash.listing()["windows"][0]
        self.assertEqual(retained["phase"],"restoring")
        self.assertIn("prevented release",retained["lastError"])
        for key in ("size","relativePosition","floating","origin","order"):
            self.assertEqual(retained[key],original[key])
        self.hypr.dispatch=dispatch
        self.assertEqual(self.stash.restore(ident,"original")["action"],"restored")
        self.assertEqual(self.hypr.clients[0]["workspace"]["id"],1)
        self.assertFalse(self.hypr.clients[0]["floating"])

    @unittest.skipUnless(shutil.which("lua"), "Standalone Lua interpreter unavailable")
    def test_external_release_lua_checks_exact_destination_and_identity_without_focus_or_resize(self):
        record=dict(address="0x1",pid=100,stableId="0x1",tag="window-stash-test",floating=False)
        hypr=Hyprland();calls=[];hypr.eval=calls.append
        prelude='''local events={}
local current={pid=100,stable_id=1,tags={"window-stash-test"},workspace={name="4"},floating=true}
local original=current
local replacement={pid=200,stable_id=2,tags={},workspace={name="4"},floating=true}
hl={get_window=function(selector) assert(selector=="address:0x1");return current end,dsp={window={}},dispatch=function(action) action() end}
hl.dsp.window.float=function(args) return function()
 table.insert(events,"float:"..args.action);args.window.floating=args.action=="on"
 if replace_after_float then current=replacement end
 if block_float then args.window.floating=true end
end end
hl.dsp.window.tag=function(args) return function()
 table.insert(events,"tag:"..args.tag)
 if args.tag:sub(1,1)=="+" then table.insert(args.window.tags,args.tag:sub(2))
 else for i,tag in ipairs(args.window.tags) do if tag==args.tag:sub(2) then table.remove(args.window.tags,i);break end end end
end end
'''
        hypr.release_external(record,dict(id=4,name="4"))
        code=calls.pop()
        def execute(body):
            result=subprocess.run(["lua","-"],input=prelude+body,text=True,capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr)
        execute(code+'assert(not original.floating and #original.tags==0)\nassert(table.concat(events,",")=="float:off,tag:-window-stash-test")')
        for change in ('current.pid=200','current.stable_id=2','current.tags={"window-stash-test-lookalike"}',
                       'current.workspace.name="7"'):
            execute(change+'\nlocal ok=pcall(function()\n'+code+'end)\nassert(not ok and #events==0)')
        execute('replace_after_float=true\nlocal ok=pcall(function()\n'+code+'end)\nassert(not ok and #events==1 and #replacement.tags==0 and replacement.floating)')
        execute('block_float=true\nlocal ok=pcall(function()\n'+code+'end)\nassert(not ok and #events==1 and #original.tags==1)')
        hypr.release_external(record,dict(id=4,name="4"),native_floating=True)
        execute(calls.pop()+'assert(original.floating and #original.tags==1 and original.tags[1]=="omarchy-mode-floated")\nassert(table.concat(events,",")=="tag:+omarchy-mode-floated,tag:-window-stash-test")')

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
