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
ShellRoot {
  id:root
  property int created:0
  property int phase:0
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
    print('Qt collection: native delegate identity, reorder/revival, timed cleanup and immediate Off passed')
