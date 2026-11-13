pragma ComponentBehavior: Bound
import QtQuick
import Quickshell.Hyprland
import Quickshell.Io
import "PreviewInteraction.js" as Interaction

// A view-only preview has no keyboard focus and cannot reliably read Qt's
// modifier state. The scoped native listener reports a gesture stream; the
// visible card owns corner resizing and source checks before acquiring input.
Item {
  id:shortcut
  required property var stash
  readonly property bool resizeWanted:stash.snapshot.settings.presentation==="previews"
    && stash.snapshot.settings.floatingPreviewSizing!=="preset" && stash.snapshot.settings.floatingPreviewLock!=="locked"
  readonly property bool wanted:!stash.stopping && !stash.bridgeReloadBusy && stash.lifecycleReady
    && (Interaction.enabled(stash.snapshot.settings) || resizeWanted) && stash.captureAllowed
    && stash.snapshot.windows.some(function(record) {return record.phase==="stashed"})
  readonly property string bridgeStamp:JSON.stringify(stash.bridgeSupportStatus)
  property bool attempted:false
  property var status:({state:"idle"})
  readonly property bool cornerReady:resizeWanted && status.state==="ready" && status.cornerResize===true
  property string error:""
  signal gesture(real serial,string phase,real x,real y)

  readonly property string preparePolicy:JSON.stringify([wanted,resizeWanted])
  onPreparePolicyChanged: {
    attempted=false;status={state:"idle"};error=""
    if(prepare.running) prepare.signal(15)
    if(!wanted) {
      prepareDelay.stop()
    } else prepareDelay.restart()
  }
  onBridgeStampChanged: {
    if(stash.bridgeSupportStatus.state==="current") {
      status={state:"idle"};error=""
      attempted=false
      if(wanted) prepareDelay.restart()
    }
  }
  function beginPrepare() {
    if(!wanted || attempted || prepare.running) return
    attempted=true;status={state:"starting"};error="";prepare.running=true
  }
  function message(value) {
    if(!wanted || !value || ["building","loading","ready","disabled","unavailable"].indexOf(value.state)<0) return
    status=value
    error=value.state==="unavailable" ? String(value.error || "Super+left click is unavailable") : ""
  }
  function nativeEvent(name,data) {
    if(name!=="window-stash-super-click" || !wanted) return false
    var parts=String(data || "").split(",")
    if(parts.length!==4 || !/^\d+$/.test(parts[0]) || ["press","move","release","drag-release","cancel"].indexOf(parts[1])<0
        || !parts[2].trim() || !parts[3].trim()) return false
    var serial=Number(parts[0]),x=Number(parts[2]),y=Number(parts[3])
    if(!Number.isInteger(serial) || serial<=0 || serial>4294967295 || !Number.isFinite(x) || !Number.isFinite(y)
        || Math.abs(x)>1000000 || Math.abs(y)>1000000) return false
    gesture(serial,parts[1],x,y)
    return true
  }
  Timer {id:prepareDelay;interval:100;onTriggered:shortcut.beginPrepare()}
  Process {
    id:prepare
    objectName:"preview-shortcut-prepare"
    command:["python3",decodeURIComponent(Qt.resolvedUrl("../controller/interaction.py").toString().replace(/^file:\/\//,"")),"--prepare"]
    stdout:SplitParser {
      onRead:function(line) {
        try {shortcut.message(JSON.parse(line))}
        catch(error) {shortcut.message({state:"unavailable",error:"Could not read Super+left click support status"})}
      }
    }
    stderr:StdioCollector {}
    onExited:function(code) {
      if(shortcut.wanted && code!==0 && !shortcut.error)
        shortcut.message({state:"unavailable",error:"Super+left click support could not start; use the Interact control"})
      if(shortcut.wanted && !shortcut.attempted) prepareDelay.restart()
    }
  }
  Connections {
    target:Hyprland
    function onRawEvent(event) {if(event) shortcut.nativeEvent(event.name,event.data)}
  }
  Component.onCompleted:if(wanted) prepareDelay.restart()
}
