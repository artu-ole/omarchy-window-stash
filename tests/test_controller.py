import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "controller"))
from stash import Stash, SPECIAL, PLUGIN, atomic_json, eligible, lua, restored_geometry


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

    def read(self, name):
        return copy.deepcopy(dict(clients=self.clients,monitors=self.monitors,workspaces=self.workspaces,
                                  activewindow=self.client(self.active))[name])

    def client(self, address):
        return next((c for c in self.clients if c["address"]==address),None)

    def eval(self, code): self.commands.append(code)

    def dispatch(self, dispatcher, **kw):
        action = dispatcher
        self.commands.append((action,kw))
        if action==self.fail: raise RuntimeError("Injected IPC failure")
        c=self.client(kw.get("window", "address:"+self.active).removeprefix("address:"))
        if action=="window.tag":
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
