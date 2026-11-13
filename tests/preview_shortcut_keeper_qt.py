#!/usr/bin/env python3
"""Exercise shortcut preparation and native event validation without a desktop."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT/'ui/StashPreviewShortcut.qml').read_text()
source = source.replace('  Process {', '  FakeProcess {')
source = source.replace('  required property var stash', '''
  component FakeProcess:Item {
    property bool running:false
    property var command:[]
    property var stdout:null
    property var stderr:null
    property int starts:0
    property int kills:0
    signal exited(int code)
    onRunningChanged:if(running) starts++
    function finish(code) {running=false;exited(code)}
    function signal(number) {kills++;finish(number)}
  }
  required property var stash''')

with tempfile.TemporaryDirectory(prefix='stash-shortcut-keeper-') as directory:
    folder = Path(directory)
    for name in ('runtime', 'cache', 'config'):
        (folder/name).mkdir(mode=0o700)
    (folder/'StashPreviewShortcut.qml').write_text(source)
    (folder/'PreviewInteraction.js').write_text((ROOT/'ui/PreviewInteraction.js').read_text())
    (folder/'shell.qml').write_text('''pragma ComponentBehavior: Bound
import QtQuick
import Quickshell
ShellRoot {
  id:root
  property int phase:0
  property int ticks:0
  property var received:[]
  QtObject {
    id:fake
    property bool stopping:false
    property bool bridgeReloadBusy:false
    property bool lifecycleReady:true
    property bool captureAllowed:true
    property var bridgeSupportStatus:({state:"absent"})
    property var snapshot:({settings:{presentation:"previews",floatingPreviewInteraction:"off"},windows:[{id:"one",phase:"stashed"}]})
  }
  StashPreviewShortcut {
    id:shortcut;stash:fake
    onGesture:function(serial,phase,x,y) {root.received=root.received.concat([{serial:serial,phase:phase,x:x,y:y}])}
  }
  function check(value,message) {if(!value) throw new Error(message)}
  function process() {return shortcut.children.find(function(item) {return item.objectName==="preview-shortcut-prepare"})}
  function enabled(value) {fake.snapshot={settings:{presentation:"previews",floatingPreviewInteraction:value ? "on" : "off"},windows:[{id:"one",phase:"stashed"}]}}
  Timer {
    interval:30;repeat:true;running:true
    onTriggered: {
      try {
        root.ticks++
        if(root.phase===0) {
          check(!shortcut.wanted && process().starts===0,"Disabled interaction loaded native code")
          check(!shortcut.nativeEvent("window-stash-super-click","1,press,100,200"),"Disabled shortcut accepted a gesture")
          enabled(true);root.phase=1;root.ticks=0
        } else if(root.phase===1 && root.ticks>=6) {
          check(shortcut.wanted && process().starts===1 && process().running,"Standard/Still activation did not prepare before the first click")
          check(process().command[process().command.length-1]==="--prepare","Preparation tried to create an input owner")
          shortcut.message({state:"building"});check(shortcut.status.state==="building","Build progress was lost")
          shortcut.message({state:"ready"});process().finish(0)
          check(shortcut.status.state==="ready" && !shortcut.error,"Prepared support did not become ready")
          root.phase=2;root.ticks=0
        } else if(root.phase===2 && root.ticks>=6) {
          check(process().starts===1,"Snapshot updates repeatedly prepared native support")
          var invalid=["","0,press,1,2","-1,press,1,2","4294967296,press,1,2","1.5,press,1,2","NaN,press,1,2",
            "1,unknown,1,2","1,press,NaN,2","1,press,1,Infinity","1,press,,2","1,press,1, ","1,press,1000001,2","1,press,1,2,3"]
          invalid.forEach(function(value) {check(!shortcut.nativeEvent("window-stash-super-click",value),"Malformed event accepted: "+value)})
          check(!shortcut.nativeEvent("custom","1,press,1,2"),"Unrelated event accepted")
          check(root.received.length===0,"Invalid events reached the cards")
          check(shortcut.nativeEvent("window-stash-super-click","4294967295,press,-1200.5,260.25"),"Valid negative-origin event rejected")
          check(shortcut.nativeEvent("window-stash-super-click","4294967295,release,-1200.5,260.25"),"Valid release rejected")
          check(shortcut.nativeEvent("window-stash-super-click","2,cancel,-1200,260"),"Valid cancellation rejected")
          check(root.received.length===3 && root.received[0].x===-1200.5,"Event parser lost exact global coordinates")
          enabled(false);enabled(true);root.phase=3;root.ticks=0
        } else if(root.phase===3 && root.ticks>=6) {
          check(process().starts===2,"Enabling interaction did not retry support")
          shortcut.message({state:"unavailable",error:"Reload preview support"});process().finish(1)
          check(shortcut.error==="Reload preview support","Legacy bridge update guidance was lost")
          root.phase=4;root.ticks=0
        } else if(root.phase===4 && root.ticks>=6) {
          check(process().starts===2,"Failed support retried in a loop")
          fake.bridgeReloadBusy=true
          check(!shortcut.wanted && !shortcut.nativeEvent("window-stash-super-click","3,press,1,2"),"Reload permitted a new activation")
          fake.bridgeReloadBusy=false;fake.bridgeSupportStatus={state:"current",loadedVersion:"new"}
          root.phase=5;root.ticks=0
        } else if(root.phase===5 && root.ticks>=6) {
          check(process().starts===3 && process().running,"Completed native reload did not prepare the shortcut again")
          fake.captureAllowed=false
          check(!process().running && process().kills===1 && shortcut.status.state==="idle","Hiding previews did not cancel preparation")
          fake.captureAllowed=true;root.phase=6;root.ticks=0
        } else if(root.phase===6 && root.ticks>=6) {
          check(process().starts===4,"Resuming visible previews did not prepare support")
          shortcut.message({state:"ready"});process().finish(0)
          fake.stopping=true
          check(!shortcut.wanted,"Plugin shutdown left activation enabled")
          console.log("PREVIEW_SHORTCUT_KEEPER_QT_PASS");Qt.quit()
        }
      } catch(error) {console.error("PREVIEW_SHORTCUT_KEEPER_QT_FAIL: "+error);Qt.exit(1)}
    }
  }
}
''')
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen', QT_QPA_PLATFORMTHEME='generic',
               QT_QUICK_CONTROLS_STYLE='Basic', QSG_RHI_BACKEND='software',
               XDG_RUNTIME_DIR=str(folder/'runtime'), XDG_CACHE_HOME=str(folder/'cache'),
               XDG_CONFIG_HOME=str(folder/'config'), DBUS_SESSION_BUS_ADDRESS='unix:path=/dev/null')
    for key in ('WAYLAND_DISPLAY', 'DISPLAY', 'HYPRLAND_INSTANCE_SIGNATURE'):
        env.pop(key, None)
    result = subprocess.run(['qs', '-p', str(folder/'shell.qml')], env=env,
                            capture_output=True, text=True, timeout=10)
    output = result.stdout+result.stderr
    assert result.returncode == 0 and 'PREVIEW_SHORTCUT_KEEPER_QT_PASS' in output, output
    assert not any(message in output for message in ('Binding loop', 'ReferenceError', 'TypeError', 'Cannot assign', 'Cannot read')), output
    print('Qt shortcut preparation: opt-in lifecycle, one attempt, native reload recovery, cancellation and bounded native-event validation passed')
