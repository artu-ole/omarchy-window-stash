#!/usr/bin/env python3
"""Exercise the production bridge-update UI state machine without desktop IPC."""
import os
from pathlib import Path
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
source = (ROOT/'Service.qml').read_text()
properties = source[source.index('  property var bridgeSupportStatus:'):
                    source.index('  readonly property bool pointerTracking:')]
api = source[source.index('  // Updating the native bridge'):
             source.index('  function screenMonitor(')]
api = api.replace('  Process {', '  FakeProcess {')

with tempfile.TemporaryDirectory(prefix='stash-bridge-upgrade-ui-') as directory:
    folder = Path(directory)
    for name in ('runtime', 'cache', 'config'):
        (folder/name).mkdir(mode=0o700)
    (folder/'shell.qml').write_text('''pragma ComponentBehavior: Bound
import QtQuick
import Quickshell
import Quickshell.Io
ShellRoot {
  id:root
  property int phase:0
  property int ticks:0
  property int reloads:0
  property int notifications:0
  property int pumps:0
  property bool stopping:false
  property bool lifecycleReady:true
  property bool resetBusy:false
  property bool shortcutsBusy:false
  property var previewInteractionRequest:({id:"source",serial:1})
  property var previewInteractionPendingRequest:({id:"replacement",serial:2})
  property bool previewInteractionStopping:false
  property string previewCompatibilityError:"Old bridge error"
  property string previewInteractionError:"Old interaction error"
  property var previewCompatibilityStatus:({state:"unavailable"})
  QtObject {id:worker;property bool running:false}
  function endPreviewInteraction(reason) {
    if(previewInteractionRequest) previewInteractionStopping=true
    check(reason==="bridge-update","Reload ended interaction with the wrong reason")
  }
  function pump() {root.pumps++}
  function applyDeferredSettings() {}
  function check(value,message) {if(!value) throw new Error(message)}
  function mismatch() {bridgeSupportMessage({ok:true,state:"update-required",loadedVersion:"1.24.0",expectedVersion:"1.29.1"})}
  component FakeProcess:Item {
    property bool running:false
    property bool stdinEnabled:false
    property var command:[]
    property var stdout:null
    property var stderr:null
    signal exited(int code)
    function signal(value) {running=false;exited(value)}
    onRunningChanged:if(running) {
      if(command[0]==="notify-send") root.notifications++
      else if(command[command.length-1]==="reload") {
        check(!root.previewInteractionRequest && !root.previewInteractionStopping,"Reload began before acknowledged interaction release")
        check(root.bridgeReloadBusy,"Reload began without blocking reacquisition")
        root.reloads++
      }
    }
  }
''' + properties + api + '''
  Timer {
    interval:30;repeat:true;running:true
    onTriggered: {
      try {
        if(root.phase===0) {
          root.mismatch()
          check(root.bridgeUpdateRequired && root.bridgeSupportVisible,"A bridge mismatch was not exposed")
          check(root.notifications===1 && root.previewInteractionRequest && !root.previewInteractionStopping,"Detection interrupted input or did not notify")
          bridgeNotification.running=false
          root.mismatch()
          check(root.notifications===1,"An unchanged mismatch repeatedly notified")
          root.deferBridgeUpdate()
          check(root.bridgeUpdateDeferred && root.bridgeSupportVisible,"Later removed the persistent update action")
          root.resetBusy=true
          check(!root.reloadPreviewSupport(),"Reload raced a settings reset")
          root.resetBusy=false;root.shortcutsBusy=true
          check(!root.reloadPreviewSupport(),"Reload raced shortcut updates")
          root.shortcutsBusy=false
          check(root.reloadPreviewSupport(),"Explicit reload did not start")
          check(root.bridgeReloadBusy && root.previewInteractionStopping && !root.previewInteractionPendingRequest,"Reload did not stop input and cancel queued re-entry")
          check(!root.reloadPreviewSupport(),"Repeated reload was accepted")
        } else if(root.phase===1) {
          check(root.reloads===0 && !bridgeReload.running,"Reload unloaded before release acknowledgement")
          root.previewInteractionRequest=null;root.previewInteractionStopping=false
          worker.running=true
          root.ticks=0
        } else if(root.phase===2) {
          check(root.reloads===0,"Reload raced an existing window action")
          if(++root.ticks<3) return
          worker.running=false
        } else if(root.phase===3) {
          if(root.reloads!==1) return
          root.bridgeReloadMessage({state:"building",ok:true})
          check(root.bridgeSupportText.indexOf("Building")===0,"Build progress was not exposed")
          root.bridgeReloadMessage({state:"loading",ok:true})
          check(root.bridgeSupportText.indexOf("Loading")===0,"Load progress was not exposed")
          root.bridgeReloadMessage({state:"ready",ok:true,loadedVersion:"1.29.1",expectedVersion:"1.29.1"})
          check(root.bridgeReloadBusy,"Ready status resumed helpers before the process exited")
          bridgeReload.running=false
          root.finishBridgeReload(0)
          check(!root.bridgeReloadBusy && !root.bridgeUpdateRequired && !root.bridgeSupportError,"Successful reload kept update/error state")
          check(!root.previewInteractionRequest && !root.previewInteractionPendingRequest,"Reload rearmed interactive input")
          check(!root.previewCompatibilityError && !root.previewInteractionError,"Successful reload retained old helper errors")
        } else if(root.phase===4) {
          root.mismatch()
          check(root.notifications===2,"A fresh bridge upgrade did not notify")
          check(root.reloadPreviewSupport(),"A later reload could not start")
        } else if(root.phase===5) {
          if(root.reloads!==2) return
          root.bridgeReloadMessage({state:"error",ok:false,error:"Compiler missing; existing bridge retained"})
          bridgeReload.running=false
          root.finishBridgeReload(1)
          check(!root.bridgeReloadBusy && root.bridgeUpdateRequired,"Build failure froze helpers or lost mismatch")
          check(root.bridgeSupportError.indexOf("Compiler missing")===0 && root.bridgeSupportVisible,"Build failure lost its actionable error")
          root.reloadPreviewSupport()
        } else if(root.phase===6) {
          if(root.reloads!==3) return
          bridgeReload.running=false
          root.finishBridgeReload(0)
          check(!root.bridgeReloadBusy && root.bridgeSupportError!=="","Missing success acknowledgement was accepted")
          root.bridgeSupportMessage({state:"absent",ok:true,expectedVersion:"1.29.1"})
          check(root.bridgeSupportError!=="" && root.bridgeSupportVisible,"An absent bridge hid reload failure details")
          root.bridgeSupportMessage({state:"current",ok:true,expectedVersion:"1.29.1",loadedVersion:"1.29.1"})
          check(!root.bridgeSupportVisible && !root.bridgeUpdateDeferred,"Verified current bridge retained stale update state")
          root.bridgeSupportMessage({state:"absent",ok:true,expectedVersion:"1.29.1"})
          check(!root.bridgeUpdateRequired,"Fresh installation incorrectly required an update")
          root.stopping=true
          bridgeProbe.running=false
          root.checkBridgeSupport()
          check(!bridgeProbe.running,"A stopping service started another status helper")
          console.log("BRIDGE_UPGRADE_QT_PASS");Qt.quit()
        }
        root.phase++
      } catch(error) {console.error("BRIDGE_UPGRADE_QT_FAIL: "+error);Qt.exit(1)}
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
    assert result.returncode == 0 and 'BRIDGE_UPGRADE_QT_PASS' in output, output
    assert not any(message in output for message in ('Binding loop', 'ReferenceError', 'TypeError', 'Cannot assign', 'Cannot read')), output
    print('Qt bridge update: proactive/deferred notification, acknowledged input release, action serialization, progress, failure recovery and explicit re-entry passed')
