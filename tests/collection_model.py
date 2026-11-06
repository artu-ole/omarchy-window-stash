#!/usr/bin/env python3
"""Exercise keyed model timing and delegate identity in an offscreen Qt engine."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='stash-model-test-') as directory:
    folder=Path(directory);ui=folder/'ui';ui.mkdir()
    for name in ('StashCollection.qml','Model.js','Motion.js'):shutil.copy2(ROOT/'ui'/name,ui/name)
    for name in ('runtime','cache','config'):(folder/name).mkdir(mode=0o700)
    (folder/'shell.qml').write_text('''import QtQuick
import Quickshell
import "ui"
import "ui/Motion.js" as Motion
ShellRoot {
  id:root
  property int created:0
  property int phase:0
  property real started:0
  property real originalDeadline:0
  property real shorterDeadline:0
  property int expectedCreated:0
  property var a:({key:"a",app:"A",title:"A",windows:[]})
  property var b:({key:"b",app:"B",title:"B",windows:[]})
  StashCollection { id:model }
  Item {
    Repeater {
      id:view
      model:model
      delegate:Item {
        required property string groupKey
        required property bool retiring
        Component.onCompleted:root.created++
      }
    }
  }
  function check(value,message) { if (!value) throw new Error(message) }
  function startExit(speed) {
    model.animations="full"; model.animationSpeed=speed
    model.sourceGroups=[root.a]
    root.expectedCreated=root.created
    model.sourceGroups=[]
    root.started=Date.now(); root.originalDeadline=model.retireAt.a
    check(model.count===1 && model.get(0).retiring,"Speed case did not start a retained exit")
  }
  Timer {
    interval:20; repeat:true; running:true
    onTriggered: {
      try {
        if (root.phase===0) { model.sourceGroups=[root.a,root.b]; root.phase=1; return }
        if (root.phase===1) {
          check(root.created===2,"Initial delegates missing")
          model.sourceGroups=[]
          check(model.count===2 && model.get(0).retiring,"Removal was not retained")
          model.sourceGroups=[root.b,root.a]
          check(model.count===2 && !model.get(0).retiring && !model.get(1).retiring,"Revival did not cancel retirement")
          check(root.created===2,"Revival or reorder recreated delegates")
          check(model.keys.join(",")==="b,a","Active order is incorrect")
          for (var i=0;i<10;i++) model.reconcile()
          check(root.created===2,"Ordinary refresh recreated delegates")
          model.sourceGroups=[]; root.phase=2; return
        }
        if (root.phase===2) {
          if (model.count>0 || model.busy) return
          check(Object.keys(model.dataByKey).length===0,"Expired data leaked")
          model.sourceGroups=[root.a]; model.sourceGroups=[]
          model.animations="off"
          check(model.count===0 && !model.busy,"Off retained a retiring entry")
          model.sourceGroups=[root.a,root.b]
          check(model.count===2,"Off lost active entries")
          model.sourceGroups=[]
          check(model.count===0 && !model.busy,"Off did not remove immediately")
          root.startExit("ultrafast"); root.phase=3; return
        }
        if (root.phase===3) {
          if (Date.now()-root.started<25) return
          check(model.count===1,"Fast exit disappeared before slowing")
          model.animationSpeed="slow"
          // Ordinary source refreshes must not shorten the newly extended
          // lifetime, even though no source key changed.
          for (var refresh=0;refresh<5;refresh++) model.reconcile()
          root.phase=4; return
        }
        if (root.phase===4) {
          if (Date.now()<root.originalDeadline+40) return
          check(model.count===1 && model.get(0).retiring,"Slowing an exit pruned its delegate at the old fast deadline")
          check(root.created===root.expectedCreated,"Speed change recreated the retiring delegate")
          root.phase=5; return
        }
        if (root.phase===5) {
          if (model.count>0 || model.busy) return
          check(Object.keys(model.dataByKey).length===0,"Slowed exit left expired data")
          root.startExit("slow"); root.phase=6; return
        }
        if (root.phase===6) {
          if (Date.now()-root.started<25) return
          model.animationSpeed="ultrafast"
          root.shorterDeadline=Date.now()+Motion.exit("full","ultrafast")+32
          for (var repeated=0;repeated<5;repeated++) model.reconcile()
          root.phase=7; return
        }
        if (root.phase===7) {
          if (Date.now()<root.shorterDeadline+40) return
          check(Date.now()<root.originalDeadline,"Missed the lifetime-check sampling window")
          check(model.count===1 && model.get(0).retiring,"A faster setting cut off an exit already using slow timing")
          check(root.created===root.expectedCreated,"Speeding an exit recreated its delegate")
          root.phase=8; return
        }
        if (root.phase===8) {
          if (model.count>0 || model.busy) return
          root.startExit("slow"); root.phase=9; return
        }
        if (root.phase===9) {
          if (Date.now()-root.started<25) return
          model.animationSpeed="ultrafast"
          model.sourceGroups=[root.a]
          check(model.count===1 && !model.get(0).retiring,"Speed-change revival did not cancel retirement")
          check(root.created===root.expectedCreated,"Revival after a speed change recreated the delegate")
          root.phase=10; return
        }
        if (root.phase===10) {
          if (Date.now()<root.originalDeadline+40) return
          check(model.count===1 && model.keys.join(",")==="a","An old exit deadline removed a revived delegate")
          model.animations="off"; model.sourceGroups=[]
          check(model.count===0 && !model.busy,"Off did not clear speed-retimed retirement immediately")
          console.log("COLLECTION_PASS")
          Qt.quit()
        }
      } catch (e) { console.error("COLLECTION_FAIL: "+e); Qt.exit(1) }
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
    assert result.returncode==0 and 'COLLECTION_PASS' in output,output
    print('Qt collection: delegate identity, reorder/revival, speed-change exit lifetimes, timed cleanup and immediate Off passed')
