#!/usr/bin/env python3
"""Exercise the production preview worker's QML lifetime without compositor IPC."""
import os
from pathlib import Path
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
service = (ROOT/'Service.qml').read_text()
# Execute the actual production properties, request API and Loader lifecycle.
# Only the spawned process is replaced; this suite never connects to Hyprland.
properties = service[service.index('  property var previewCompatibilityRequests:'):
                     service.index('  property bool contextOpen:')]
request_api = service[service.index('  function previewCompatibilityRequest('):
                      service.index('  // Authentication services')]
worker = service[service.index('  // The pipe lifetime'):
                 service.index('  function enqueue(')].replace('      Process {', '      FakeProcess {')

with tempfile.TemporaryDirectory(prefix='stash-preview-keeper-') as directory:
    folder = Path(directory)
    for name in ('runtime', 'cache', 'config'):
        (folder/name).mkdir(mode=0o700)
    (folder/'PreviewVisibility.js').write_text((ROOT/'ui/PreviewVisibility.js').read_text())
    (folder/'shell.qml').write_text('''pragma ComponentBehavior: Bound
import QtQuick
import Quickshell
import Quickshell.Io
import "PreviewVisibility.js" as PreviewVisibility
ShellRoot {
  id:root
  property int phase:0
  property int created:0
  property int destroyed:0
  property var sent:[]
  property var a:null
  property var b:null
  property var c:null
  property var snapshot:({windows:[{id:"first"}],settings:{presentation:"previews",hoverPreview:"off",floatingPreviewUpdate:"hover",livePreviewCompatibility:"enhanced"}})
  component FakeProcess:Item {
    property bool running:true
    property bool stdinEnabled:false
    property var command:[]
    property var stdout:null
    signal started()
    signal exited(int code)
    function write(value) {root.sent=root.sent.concat([JSON.parse(value)])}
    Component.onCompleted: {root.created++;Qt.callLater(function() {started()})}
    Component.onDestruction:root.destroyed++
  }
  component PreviewOwner:QtObject {
    required property string key
    required property string recordId
    Component.onCompleted:root.previewCompatibilityRequest(key,recordId)
    Component.onDestruction:root.previewCompatibilityRequest(key,"")
  }
  Component {id:ownerFactory;PreviewOwner {}}
''' + properties + request_api + worker + '''
  function check(value,message) {if(!value) throw new Error(message)}
  function readable(enabled) {
    captureClock=Date.now()
    captureState={known:true,checkedAt:captureClock,monitors:[{name:"test",width:1280,height:800,dpmsStatus:enabled,solitaryBlockedBy:[]}],error:""}
  }
  function policy(update,presentation) {
    var next=Object.assign({},snapshot),settings=Object.assign({},snapshot.settings)
    settings.floatingPreviewUpdate=update;settings.presentation=presentation || "previews"
    next.settings=settings;snapshot=next
  }
  Timer {
    interval:30;repeat:true;running:true
    onTriggered: {
      try {
        if(root.phase===0) {
          root.readable(true)
          root.a=ownerFactory.createObject(root,{key:"owner-a",recordId:"first"})
          root.b=ownerFactory.createObject(root,{key:"owner-b",recordId:"first"})
        } else if(root.phase===1) {
          check(root.created===1 && root.previewCompatibilityWorker,"Visible live sources did not create one worker")
          check(root.previewCompatibilityIds.join(",")==="first","Duplicate source leases were not deduplicated")
          check(root.sent.length && root.sent[root.sent.length-1].join(",")==="first","Worker did not receive its complete source set")
          root.readable(false)
        } else if(root.phase===2) {
          check(!root.previewCompatibilityWorker && root.destroyed===1,"DPMS suspension retained the worker")
          check(Object.keys(root.previewCompatibilityRequests).length===2,"Worker destruction deleted live delegate requests")
          check(root.previewCompatibilityStatus.state==="idle","Suspended worker kept stale status")
          root.readable(true)
        } else if(root.phase===3) {
          check(root.created===2 && root.previewCompatibilityWorker,"Wake did not reacquire the existing source owners")
          root.a.destroy();root.a=null
        } else if(root.phase===4) {
          check(root.previewCompatibilityIds.join(",")==="first" && root.destroyed===1,"One delegate removal stopped another delegate's lease")
          root.b.destroy();root.b=null
        } else if(root.phase===5) {
          check(!root.previewCompatibilityWorker && !Object.keys(root.previewCompatibilityRequests).length,"Last delegate destruction retained the worker or stale request")
          root.a=ownerFactory.createObject(root,{key:"owner-c",recordId:"second"})
          root.b=ownerFactory.createObject(root,{key:"owner-d",recordId:"third"})
        } else if(root.phase===6) {
          check(root.previewCompatibilityIds.join(",")==="second,third","Multiple source owners did not share the aggregate worker")
          root.policy("still")
        } else if(root.phase===7) {
          check(!root.previewCompatibilityWorker && Object.keys(root.previewCompatibilityRequests).length===2,"Policy suspension lost ownership or kept rendering")
          root.policy("live")
        } else if(root.phase===8) {
          check(root.previewCompatibilityWorker && root.previewCompatibilityIds.join(",")==="second,third","Policy resume did not restore source requests")
          root.a.destroy();root.b.destroy();root.a=null;root.b=null
          root.c=ownerFactory.createObject(root,{key:"replacement",recordId:"fourth"})
        } else if(root.phase===9) {
          check(root.previewCompatibilityIds.join(",")==="fourth" && Object.keys(root.previewCompatibilityRequests).length===1,"Old teardown discarded a replacement owner")
          root.policy("still","floating");root.c.destroy();root.c=null
        } else if(root.phase===10) {
          check(!root.previewCompatibilityWorker && !Object.keys(root.previewCompatibilityRequests).length,"Leaving preview mode retained rendering or stale ownership")
          check(root.created===root.destroyed,"Worker lifetimes leaked")
          console.log("PREVIEW_KEEPER_QT_PASS");Qt.quit()
        }
        root.phase++
      } catch(error) {console.error("PREVIEW_KEEPER_QT_FAIL: "+error);Qt.exit(1)}
    }
  }
}
''')
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen', QT_QPA_PLATFORMTHEME='generic',
               QSG_RHI_BACKEND='software', XDG_RUNTIME_DIR=str(folder/'runtime'),
               XDG_CACHE_HOME=str(folder/'cache'), XDG_CONFIG_HOME=str(folder/'config'),
               DBUS_SESSION_BUS_ADDRESS='unix:path=/dev/null')
    for key in ('WAYLAND_DISPLAY', 'DISPLAY', 'HYPRLAND_INSTANCE_SIGNATURE'):
        env.pop(key, None)
    result = subprocess.run(['qs', '-p', str(folder/'shell.qml')], env=env,
                            capture_output=True, text=True, timeout=8)
    output = result.stdout+result.stderr
    assert result.returncode == 0 and 'PREVIEW_KEEPER_QT_PASS' in output, output
    assert not any(message in output for message in ('Binding loop', 'ReferenceError', 'TypeError', 'Cannot assign', 'Cannot read')), output
    print('Qt preview keeper: DPMS/policy suspend-resume, shared leases, exact delegate cleanup and replacement ownership passed')
