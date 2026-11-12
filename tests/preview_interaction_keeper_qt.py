#!/usr/bin/env python3
"""Execute production interaction-owner lifetime without compositor IPC/input."""
import os
from pathlib import Path
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
service = (ROOT/'Service.qml').read_text()
properties = service[service.index('  property var previewInteractionRequest:'):
                     service.index('  property string contextScreen:')]
api = service[service.index('  function previewInteractionMatches('):service.index('  function pump(')]
api = api.replace('    Process {', '    FakeProcess {')

with tempfile.TemporaryDirectory(prefix='stash-interaction-keeper-') as directory:
    folder = Path(directory)
    for name in ('runtime', 'cache', 'config'):
        (folder/name).mkdir(mode=0o700)
    (folder/'PreviewInteraction.js').write_text((ROOT/'ui/PreviewInteraction.js').read_text())
    (folder/'shell.qml').write_text('''pragma ComponentBehavior: Bound
import QtQuick
import Quickshell
import Quickshell.Io
import "PreviewInteraction.js" as PreviewInteraction
ShellRoot {
  id:root
  property int phase:0
  property int created:0
  property int destroyed:0
  property var sent:[]
  property int firstSerial:0
  property int replacementSerial:0
  property int nativeOwners:0
  property var actor:null
  property bool stopping:false
  property real failedAt:0
  property bool lifecycleReady:true
  property bool readable:true
  property var captureState:({})
  property real captureClock:0
  property var pendingCloseIds:({})
  property var record:({id:"first",phase:"stashed",size:[640,420]})
  property var snapshot:({windows:[record],monitors:[{name:"test"}],settings:{presentation:"previews",floatingPreviewInteraction:"on",floatingPreviewActivation:"explicit",floatingPreviewKeyboard:"mouse",floatingPreviewInteractionFps:"60",floatingPreviewControls:"hover",floatingPreviewUpdate:"still",livePreviewCompatibility:"standard"}})
  function captureAllowedFor(monitor) {return readable && monitor==="test"}
  function closeContext() {}
  function closeDialog() {}
  function pump() {check(!previewInteractionStopping,"Window actions resumed before native release was acknowledged")}
  function applyDeferredSettings() {}
  function policy(key,value) {var next=Object.assign({},snapshot),settings=Object.assign({},snapshot.settings);settings[key]=value;next.settings=settings;snapshot=next}
  function activate(id) {return beginPreviewInteraction(record,"test","view:"+id,{x:30,y:40,width:280,height:180},[])}
  function check(value,message) {if(!value) throw new Error(message)}
  function acknowledgeStop() {
    check(actor && actor.stopping,"Fake compositor did not receive a stop request")
    var serial=actor.activationSerial
    actor.releaseNative()
    interactionMessage({state:"idle",id:""},serial)
  }
  component FakeProcess:Item {
    id:fake
    property bool running:true
    property bool stdinEnabled:false
    property var command:[]
    property var stdout:null
    property var stderr:null
    property bool stopping:false
    property bool nativeOwned:false
    property int activationSerial:0
    signal started()
    signal exited(int code)
    function releaseNative() {if(nativeOwned) {nativeOwned=false;root.nativeOwners--}}
    function signal(number) {running=false;exited(number===15 ? 0 : 137)}
    function write(value) {
      var request=JSON.parse(value);root.sent=root.sent.concat([request])
      if(request===null) stopping=true
      else {
        if(!nativeOwned) {nativeOwned=true;root.nativeOwners++}
        activationSerial=request.serial
      }
    }
    Component.onCompleted: {root.created++;root.actor=fake;Qt.callLater(function() {started()})}
    Component.onDestruction:root.destroyed++
  }
''' + properties + api + '''
  Timer {
    interval:30;repeat:true;running:true
    onTriggered: {
      try {
        if(root.phase===0) {
          check(root.activate("first"),"Explicit activation failed")
          root.firstSerial=root.previewInteractionRequest.serial
        } else if(root.phase===1) {
          check(root.created===1 && root.previewInteractionWorker,"Activation did not create one input worker")
          check(root.sent.length===1 && root.sent[0].serial===root.firstSerial,"Initial activation was not sent exactly once")
          check(root.sent[0].keyboard===false && root.sent[0].fps===60,"Active input options changed")
          root.interactionMessage({state:"active",serial:root.firstSerial,id:"first"},root.firstSerial)
          root.updatePreviewInteraction("first","test","view:first",{x:45,y:55,width:300,height:190},[{x:210,y:55,width:100,height:28}])
        } else if(root.phase===2) {
          check(root.created===1 && root.destroyed===0,"Updating a rectangle restarted the native owner")
          check(root.sent.length===2 && root.sent[1].rect.x===45,"Updated image geometry was not sent")
          check(root.previewInteractionRequest.serial===root.firstSerial,"Geometry changes silently rearmed input")
          root.endPreviewInteraction("manage")
          check(root.previewInteractionStopping && root.previewInteractionRequest && root.nativeOwners===1,"Stop made management available before native release")
          check(root.sent[root.sent.length-1]===null,"Stop did not send a graceful null request")
          var count=root.sent.length
          root.updatePreviewInteraction("first","test","view:first",{x:46,y:56,width:300,height:190},[])
          check(root.sent.length===count,"A rectangle renewal rearmed input while stopping")
        } else if(root.phase===3) {
          check(root.previewInteractionRequest && root.previewInteractionWorker && root.destroyed===0 && root.nativeOwners===1,"Unacknowledged release destroyed its owner")
          root.acknowledgeStop()
        } else if(root.phase===4) {
          check(!root.previewInteractionRequest && !root.previewInteractionWorker && root.destroyed===1 && root.nativeOwners===0,"Acknowledged release did not unlock management")
          root.updatePreviewInteraction("first","test","view:first",{x:45,y:55,width:300,height:190},[])
          check(!root.previewInteractionRequest,"Stale geometry update rearmed a finished interaction")
          check(root.activate("second"),"New explicit activation failed")
          root.replacementSerial=root.previewInteractionRequest.serial
        } else if(root.phase===5) {
          check(root.activate("replacement"),"Replacement intent was not accepted")
          check(root.previewInteractionRequest.serial===root.replacementSerial && root.previewInteractionPendingRequest.serial>root.replacementSerial,"Replacement skipped the old owner's release handshake")
          check(root.created===2 && root.nativeOwners===1,"Replacement acquired a second native owner before release")
          root.updatePreviewInteraction("first","test","view:replacement",{x:60,y:70,width:300,height:190},[])
          check(root.previewInteractionPendingRequest.rect.x===60,"Queued target lost its latest visible rectangle")
          root.acknowledgeStop()
        } else if(root.phase===6) {
          check(root.created===3 && root.nativeOwners===1 && root.previewInteractionRequest.viewKey==="view:replacement","Acknowledged replacement did not acquire exactly one fresh owner")
          root.interactionMessage({state:"ended",serial:root.firstSerial,id:"first",reason:"late"},root.firstSerial)
          check(!!root.previewInteractionRequest,"Late old-worker teardown cleared a replacement")
          check(root.snapshot.settings.floatingPreviewUpdate==="still" && root.snapshot.settings.livePreviewCompatibility==="standard","Interactive capture rewrote idle preview policy")
          root.readable=false;root.captureClock++
          check(root.previewInteractionStopping && root.previewInteractionRequest,"Capture suspension skipped release acknowledgement")
          root.acknowledgeStop()
        } else if(root.phase===7) {
          check(!root.previewInteractionRequest && root.destroyed===3,"Capture suspension retained acknowledged input")
          root.readable=true;root.captureClock++
          check(!root.previewInteractionRequest,"Wake silently rearmed input")
          check(root.activate("fourth"),"Activation after wake failed")
        } else if(root.phase===8) {
          root.policy("floatingPreviewInteraction","off")
          check(root.previewInteractionStopping && root.previewInteractionRequest,"Disabling exposed the old native hit area")
          check(!root.activate("disabled"),"Disabled interaction still accepted activation")
          root.acknowledgeStop()
        } else if(root.phase===9) {
          check(!root.previewInteractionRequest && root.destroyed===4,"Disabled input retained an acknowledged worker")
          root.policy("floatingPreviewInteraction","on")
          check(root.activate("fifth"),"Re-enabled activation failed")
        } else if(root.phase===10) {
          var serial=root.previewInteractionRequest.serial
          root.interactionMessage({state:"unavailable",serial:serial,id:"first",error:"Test native failure"},serial)
          root.actor.running=false;root.actor.exited(1);root.failedAt=Date.now()
          nativeExpiry.restart()
        } else if(root.phase===11) {
          var elapsed=Date.now()-root.failedAt
          if(elapsed<2750) {
            check(root.previewInteractionRequest && root.previewInteractionStopping,"Failed native cleanup unlocked the miniature before lease expiry")
            if(elapsed<2400) check(root.nativeOwners===1,"Test released its native owner prematurely")
            return
          }
          if(root.previewInteractionRequest) return
          check(root.destroyed===5 && root.nativeOwners===0,"Native expiry did not complete quarantined cleanup")
          check(root.previewInteractionError==="Test native failure","Native failure was hidden")
          check(root.activate("sixth"),"Retry activation failed")
        } else if(root.phase===12) {
          var next=Object.assign({},root.snapshot);next.windows=[];root.snapshot=next
          check(root.previewInteractionStopping && root.previewInteractionRequest,"Source removal skipped cleanup acknowledgement")
          root.acknowledgeStop()
        } else if(root.phase===13) {
          check(!root.previewInteractionRequest && root.created===root.destroyed && root.nativeOwners===0,"Source removal left an input owner")
          check(root.record.size.join(",")==="640,420","Input ownership changed restoration dimensions")
          console.log("PREVIEW_INTERACTION_KEEPER_QT_PASS");Qt.quit()
        }
        root.phase++
      } catch(error) {console.error("PREVIEW_INTERACTION_KEEPER_QT_FAIL: "+error);Qt.exit(1)}
    }
  }
  Timer {id:nativeExpiry;interval:2500;onTriggered:if(root.actor) root.actor.releaseNative()}
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
    assert result.returncode == 0 and 'PREVIEW_INTERACTION_KEEPER_QT_PASS' in output, output
    assert not any(message in output for message in ('Binding loop', 'ReferenceError', 'TypeError', 'Cannot assign', 'Cannot read')), output
    print('Qt preview interaction: acknowledged native release, blocked management, queued replacements, stale teardown, capture suspension and bounded failure quarantine passed')
