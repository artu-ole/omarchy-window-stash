#!/usr/bin/env python3
"""Exercise production resize coalescing, epochs and readiness without IPC/input."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
service = (ROOT/'Service.qml').read_text()
properties = service[service.index('  property var previewGeometryStates:'):service.index('  readonly property string previewInteractionStamp:')]
api = service[service.index('  function previewGeometryCommand('):service.index('  function previewInteractionMatches(')]
with tempfile.TemporaryDirectory(prefix='stash-geometry-keeper-') as directory:
    folder = Path(directory)
    for name in ('runtime','cache','config'):
        (folder/name).mkdir(mode=0o700)
    (folder/'shell.qml').write_text('''pragma ComponentBehavior: Bound
import QtQuick
import Quickshell
ShellRoot {
  id:root
  property int phase:0
  property int ticks:0
  property var queue:[]
  property var runningArgs:[]
  property var snapshot:({windows:[{id:"first",phase:"stashed"}]})
  property var pendingCloseIds:({})
  property var previewInteractionRequest:null
  property int firstEpoch:0
  property int currentEpoch:0
  QtObject {id:worker;property bool running:false}
  function enqueue(args) {queue=queue.concat([args])}
  function endPreviewInteraction(reason) {throw new Error("Unexpected input owner")}
  function check(value,message) {if(!value) throw new Error(message)}
''' + properties + api + '''
  Timer {
    interval:100;repeat:true;running:true
    onTriggered: {
      try {
        if(root.phase===0) {
          watchPreviewGeometry("visible-card","first")
          check(!requestPreviewAspect("absent",2,"width",false),"An unowned source entered the resize queue")
          requestPreviewAspect("first",1.5,"width",false)
          requestPreviewAspect("first",2,"width",false)
          requestPreviewAspect("first",2.5,"width",false)
          check(queue.length===0,"Pointer resize bypassed the coalescing delay")
          firstEpoch=previewGeometryState("first").epoch
        } else if(root.phase===1) {
          check(queue.length===1 && queue[0][2]==="2.5","Resize did not coalesce to the latest ratio")
          runningArgs=queue[0];queue=[];worker.running=true
          requestPreviewAspect("first",3,"width",false)
          previewGeometryResult({ok:true,id:"first",ready:true,aspect:2.5,size:[1000,400]},runningArgs,firstEpoch)
          check(!previewGeometryState("first").ready && previewGeometryState("first").requestedAspect===3,"A stale completed resize unlocked input")
        } else if(root.phase===2) {
          requestPreviewAspect("first",3.2,"width",true)
          check(queue.length===1 && queue[0][2]==="3.2" && queue[0].indexOf("--settle")>=0,"Release did not replace the queued draft with a final settle")
          runningArgs=queue[0];queue=[];worker.running=false
          currentEpoch=previewGeometryState("first").epoch
          previewGeometryResult({ok:true,id:"first",ready:false,aspect:3.2,size:[960,300],nativeRequired:false,reason:"Awaiting client"},runningArgs,currentEpoch)
          check(previewGeometryState("first").pending,"An unsettled capable source stopped being polled")
          watchPreviewGeometry("visible-card","");root.phase=20;ticks=0;return
        } else if(root.phase===20) {
          if(++ticks<3) return
          check(queue.length===0,"A hidden source retained readiness polling")
          watchPreviewGeometry("visible-card","first");ticks=0;root.phase=3;return
        } else if(root.phase===3) {
          if(!queue.length && ++ticks<5) return
          check(queue.length===1 && queue[0][0]==="preview-geometry","Pending source did not receive one read-only query")
          pollPreviewGeometry();check(queue.length===1,"Repeated polling duplicated an outstanding query")
          previewGeometryResult({ok:true,id:"first",ready:true,aspect:3.1,size:[930,300],nativeRequired:false},queue[0],currentEpoch)
          check(previewGeometryState("first").ready && previewGeometryState("first").aspect===3.1 && previewGeometryState("first").captureRevision===currentEpoch,"Accepted client proportions did not produce a fresh capture revision")
          queue=[]
          requestPreviewAspect("first",1.6,"height",true)
          currentEpoch=previewGeometryState("first").epoch
          previewGeometryResult({ok:true,id:"first",ready:false,aspect:1.6,size:[960,600],nativeRequired:true,reason:"Update preview support"},queue[0],currentEpoch)
          queue=[];ticks=0
        } else if(root.phase===4) {
          if(++ticks<4) return
          check(queue.length===0 && !previewGeometryState("first").ready && previewGeometryState("first").nativeRequired,"Missing native capability polled forever or enabled input")
          snapshot={windows:[]};prunePreviewGeometry()
          check(Object.keys(previewGeometryStates).length===0 && Object.keys(previewGeometryDrafts).length===0,"Removed windows retained resize ownership")
          console.log("PREVIEW_GEOMETRY_KEEPER_QT_PASS");Qt.quit()
        }
        root.phase++
      } catch(error) {console.error("PREVIEW_GEOMETRY_KEEPER_QT_FAIL: "+error);Qt.exit(1)}
    }
  }
}
''')
    env=dict(os.environ,QT_QPA_PLATFORM='offscreen',QT_QPA_PLATFORMTHEME='generic',QT_QUICK_CONTROLS_STYLE='Basic',QSG_RHI_BACKEND='software',XDG_RUNTIME_DIR=str(folder/'runtime'),XDG_CACHE_HOME=str(folder/'cache'),XDG_CONFIG_HOME=str(folder/'config'),DBUS_SESSION_BUS_ADDRESS='unix:path=/dev/null')
    for key in ('WAYLAND_DISPLAY','DISPLAY','HYPRLAND_INSTANCE_SIGNATURE'):
        env.pop(key,None)
    result=subprocess.run(['qs','-p',str(folder/'shell.qml')],env=env,capture_output=True,text=True,timeout=10)
    output=result.stdout+result.stderr
    assert result.returncode==0 and 'PREVIEW_GEOMETRY_KEEPER_QT_PASS' in output,output
    assert not any(message in output for message in ('Binding loop','ReferenceError','TypeError','Cannot assign','Cannot read')),output
    print('Qt preview geometry: coalesced resize, final settle, stale epochs, accepted geometry, bounded polling ownership and missing-native input gate passed')
