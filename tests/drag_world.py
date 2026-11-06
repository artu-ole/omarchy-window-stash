#!/usr/bin/env python3
"""Run the shared drag-world wrapper on Qt's offscreen frame clock."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='stash-drag-world-') as directory:
    folder=Path(directory);ui=folder/'ui';ui.mkdir()
    for name in ('DragPhysics.js','StashDragWorld.qml'):shutil.copy2(ROOT/'ui'/name,ui/name)
    for name in ('runtime','cache','config'):(folder/name).mkdir(mode=0o700)
    (folder/'shell.qml').write_text('''import QtQuick
import QtQuick.Window
import Quickshell
import "ui"
ShellRoot {
  id:root
  property int phase:0
  property int step:0
  property int frames:0
  property int positions:0
  property int saved:0
  property real frozenX:0
  property real frozenY:0
  Window {
    width:640; height:480; visible:true
    StashDragWorld {
      id:world
      area:({x:0,y:26,width:640,height:454})
      snapEdges:false
      onMoved:function(key,x,y) { root.positions++ }
      onSettled:function(key,x,y) { root.saved++ }
    }
  }
  function check(value,message) { if (!value) throw new Error(message) }
  Timer {
    interval:20; repeat:true; running:true
    onTriggered: {
      try {
        root.frames++
        if (root.frames>250) throw new Error("Native world failed to settle")
        if (root.phase===0) {
          world.add("icon",80,180,48,48)
          check(!world.active,"Registration caused startup motion")
          world.press("icon");root.phase=1;return
        }
        if (root.phase===1) {
          root.step++;world.drag("icon",80+root.step*18,180)
          check(world.body("icon").held,"Held state did not propagate")
          check(world.body("icon").x===80+root.step*18,"Held position lagged")
          if (root.step===5) { world.release("icon");root.phase=2;root.step=0 }
          return
        }
        if (root.phase===2) {
          root.step++
          if (root.step<5) return
          check(world.body("icon").x>170,"Native frame clock did not advance momentum")
          check(world.body("icon").frames>3,"Motion had no real frame updates")
          world.freeze("icon",true)
          root.frozenX=world.body("icon").x;root.frozenY=world.body("icon").y
          root.phase=3;root.step=0;return
        }
        if (root.phase===3) {
          root.step++
          check(world.body("icon").x===root.frozenX && world.body("icon").y===root.frozenY,"Freeze moved original icon")
          if (root.step<5) return
          world.sync("icon",1,1,48,48)
          check(world.body("icon").x===root.frozenX,"Stale snapshot overrode frozen origin")
          world.freeze("icon",false)
          check(world.body("icon").vx===0,"Unfreeze resurrected old velocity")
          root.phase=4;return
        }
        if (root.phase===4) {
          if (world.active) return
          check(root.saved===1,"Settlement did not persist once")
          world.freeze("icon",true)
          root.frozenX=world.body("icon").x;root.frozenY=world.body("icon").y
          world.physicsEnabled=false;world.snapEdges=true;root.phase=5;root.step=0;return
        }
        if (root.phase===5) {
          check(world.body("icon").x===root.frozenX && world.body("icon").y===root.frozenY,"Setting change moved frozen item")
          root.step++
          if (root.step<5) return
          world.freeze("icon",false);root.phase=6;return
        }
        if (root.phase===6) {
          if (world.active) return
          check(world.body("icon").x===8 || world.body("icon").x===584 || world.body("icon").y===34 || world.body("icon").y===424,"Direct mode missed edge")
          check(root.positions>10,"Native intermediate positions were missing")
          world.remove("icon")
          check(!world.active && world.details().bodies.length===0,"Removed body left simulation running")
          console.log("DRAG_WORLD_PASS")
          Qt.quit()
        }
      } catch (error) { console.error("DRAG_WORLD_FAIL: "+error);Qt.exit(1) }
    }
  }
}
''')
    env=dict(os.environ,QT_QPA_PLATFORM='offscreen',QT_QPA_PLATFORMTHEME='generic',QT_QUICK_CONTROLS_STYLE='Basic',QSG_RHI_BACKEND='software',
             XDG_RUNTIME_DIR=str(folder/'runtime'),XDG_CACHE_HOME=str(folder/'cache'),
             XDG_CONFIG_HOME=str(folder/'config'),DBUS_SESSION_BUS_ADDRESS='unix:path=/dev/null')
    env.pop('WAYLAND_DISPLAY',None);env.pop('DISPLAY',None)
    result=subprocess.run(['qs','-p',str(folder/'shell.qml')],env=env,capture_output=True,text=True,timeout=10)
    output=result.stdout+result.stderr
    assert result.returncode==0 and 'DRAG_WORLD_PASS' in output,output
    assert 'Binding loop' not in output and 'ReferenceError' not in output and 'TypeError' not in output,output
    print('Qt drag world: native frame clock, momentum, frozen origin, saved settlement, Direct edge snap and removal passed')
