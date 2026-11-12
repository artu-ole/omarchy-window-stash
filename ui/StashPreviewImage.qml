pragma ComponentBehavior: Bound
import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Hyprland
import Quickshell.Wayland
import qs.Commons
import qs.Commons as Commons
import "Motion.js" as Motion
import "PreviewCapture.js" as Capture

Item {
  id: image
  property var record:null
  property var stash:null
  property string mode:"still"
  property bool active:false
  property string animations:"full"
  property string animationSpeed:"normal"
  readonly property var popupColors:Commons.Color.popups
  readonly property var fonts:Style.font
  readonly property var metrics:Style.spacing
  readonly property string identityKey:Capture.key(record)
  readonly property var candidates:Hyprland.toplevels.values
  readonly property var candidate: {
    var wanted=record ? Capture.address(record.address) : ""
    if (!wanted) return null
    for (var i=0;i<candidates.length;i++)
      if (Capture.address(candidates[i].address)===wanted) return candidates[i]
    return null
  }
  readonly property var candidateIpc:candidate ? candidate.lastIpcObject : null
  readonly property var sourceHandle:candidate ? candidate.wayland : null
  property var verifiedClient:null
  property var acceptedHandle:null
  property bool failed:false
  property bool checking:false
  property bool captured:false
  property string failureReason:""
  property int requestSerial:0
  readonly property bool eligible:active && !failed && !!acceptedHandle && sourceHandle===acceptedHandle
    && Capture.matches(record,verifiedClient) && Capture.matches(record,candidateIpc)
  readonly property string compatibilityKey:"preview:"+String(Date.now())+":"+String(Math.random())
  readonly property bool compatibilityRequested:eligible && mode==="live" && !!stash
    && stash.snapshot.settings.livePreviewCompatibility==="enhanced"
  function syncCompatibility() { if (stash) stash.previewCompatibilityRequest(compatibilityKey,compatibilityRequested && record ? record.id : "") }
  onCompatibilityRequestedChanged:syncCompatibility()
  onIdentityKeyChanged: { begin(); syncCompatibility() }
  readonly property CaptureItem captureView:captureLoader.item as CaptureItem
  readonly property bool hasContent:!!captureView && captureView.hasContent
  readonly property size sourceSize:hasContent && eligible ? captureView.sourceSize : Qt.size(0,0)
  readonly property string status:!active || failed ? "unavailable" : hasContent ? "ready" : "loading"
  readonly property var desktop:DesktopEntries.heuristicLookup(record ? String(record.app || "") : "")
  readonly property string appIcon:desktop && desktop.icon ? String(desktop.icon) : "application-x-executable"
  visible:active
  clip:true

  function unavailable(reason) {
    if (!active) return
    failureReason=reason || "stream-ended"
    captured=false; failed=true; checking=false; acceptedHandle=null; verifiedClient=null
    deadline.stop()
  }
  function acceptCandidate() {
    if (!active || failed || !verifiedClient || !candidate || !sourceHandle) return
    if (Capture.matches(record,verifiedClient) && Capture.matches(record,candidateIpc)) acceptedHandle=sourceHandle
  }
  function begin() {
    requestSerial++
    captured=false; checking=false; acceptedHandle=null; verifiedClient=null; failed=false; failureReason=""
    deadline.stop()
    if (!active) return
    if (!Capture.validRecord(record)) { unavailable("invalid-record"); return }
    Hyprland.refreshToplevels()
    deadline.restart()
    var wanted=identityKey,serial=requestSerial
    Qt.callLater(function() { if (image.active && image.identityKey===wanted && image.requestSerial===serial && !image.failed) image.checking=true })
  }
  function verified(client,requestKey,serial) {
    if (!active || requestKey!==identityKey || serial!==requestSerial || failed) return
    if (!Capture.matches(record,client)) { unavailable("identity-mismatch"); return }
    verifiedClient=client
    acceptCandidate()
  }
  function details() {
    return {animationSpeed:animationSpeed,fadeDuration:captureFade.duration,hasContent:hasContent,status:status,
      sourceSize:{width:sourceSize.width,height:sourceSize.height},
      live:eligible && mode==="live",captureActive:captureLoader.active && !!captureView,recordId:record ? record.id : "",
      failure:failureReason,validRecord:Capture.validRecord(record),candidate:!!candidate,handle:!!sourceHandle,
      nativeIdentity:Capture.matches(record,candidateIpc),verified:!!verifiedClient,eligible:eligible,
      nativeFields:{pid:!!record && !!candidateIpc && candidateIpc.pid===record.pid,
        stable:!!record && !!candidateIpc && Capture.stableId(candidateIpc.stableId)===Capture.stableId(record.stableId),
        parked:!!candidateIpc && !!candidateIpc.workspace && candidateIpc.workspace.name==="special:window-stash",
        mapped:!!candidateIpc && candidateIpc.mapped===true,
        tags:!!candidateIpc && !!candidateIpc.tags ? candidateIpc.tags.length : 0}}
  }
  function contentRect() {
    return captureView && hasContent ? captureView.contentRect() : null
  }
  onActiveChanged:begin()
  onCandidateIpcChanged: {
    if (acceptedHandle && !Capture.matches(record,candidateIpc)) unavailable()
    else acceptCandidate()
  }
  onSourceHandleChanged: {
    if (acceptedHandle && sourceHandle!==acceptedHandle) unavailable()
    else acceptCandidate()
  }
  onHasContentChanged: {
    if (hasContent) { captured=true; deadline.stop() }
    else if (captured && active) unavailable()
  }
  Timer {
    id:deadline; interval:1000
    onTriggered: {
      if (image.compatibilityRequested && image.stash
          && ["starting","building","loading"].indexOf(image.stash.previewCompatibilityStatus.state)>=0) { restart(); return }
      if (!image.hasContent) image.unavailable(image.acceptedHandle ? "frame-timeout" : "window-handle-unavailable")
    }
  }
  Connections {
    target:Hyprland
    function onRawEvent(event) {
      if (!image.active || !image.record || !event) return
      if ((event.name==="closewindow" || event.name==="openwindow")
          && Capture.address(String(event.data || "").split(",")[0])===Capture.address(image.record.address)) image.unavailable()
    }
  }
  Connections {
    target:image.acceptedHandle
    function onClosed() { image.unavailable() }
  }

  // A one-shot fresh IPC snapshot closes the stale-metadata gap in
  // refreshToplevels(), which has no public completion acknowledgement.
  Loader {
    id:identityLoader
    active:image.checking
    sourceComponent:Item {
      id:identityCheck
      property string requestKey:""
      property int serial:0
      property bool exited:false
      property bool outputReady:false
      property int exitCode:-1
      property bool delivered:false
      property string output:""
      function complete() {
        if (!exited || !outputReady || delivered) return
        delivered=true
        if (requestKey!==image.identityKey || serial!==image.requestSerial || !image.active) return
        if (exitCode!==0) { image.unavailable(); return }
        var client
        try { client=Capture.findClient(image.record,JSON.parse(output)) }
        catch (error) { image.unavailable(); return }
        var wanted=requestKey,completedSerial=serial
        output=""
        image.verified(client,wanted,completedSerial)
        if (image.failed) return
        Qt.callLater(function() {
          if (image.identityKey===wanted && image.requestSerial===completedSerial) image.checking=false
        })
      }
      Process {
        id:lookup
        command:["hyprctl","-j","clients"]
        stdout:StdioCollector {
          onStreamFinished: { identityCheck.output=text; identityCheck.outputReady=true; identityCheck.complete() }
        }
        onExited:function(code) {
          identityCheck.exitCode=code; identityCheck.exited=true; identityCheck.complete()
        }
      }
      Component.onCompleted: { requestKey=image.identityKey; serial=image.requestSerial; lookup.running=true }
    }
  }
  component CaptureItem:Item {
    readonly property bool hasContent:view.hasContent
    readonly property size sourceSize:view.sourceSize
    function contentRect() {return {x:view.x,y:view.y,width:view.width,height:view.height}}
    ScreencopyView {
      id:view
      anchors.centerIn:parent
      constraintSize:Qt.size(parent.width,parent.height)
      width:Math.min(parent.width,implicitWidth)
      height:Math.min(parent.height,implicitHeight)
      captureSource:image.acceptedHandle
      paintCursor:false
      live:image.mode==="live"
      onStopped:image.unavailable()
    }
  }
  Loader {
    id:captureLoader
    anchors.fill:parent
    active:image.eligible
    sourceComponent:CaptureItem {}
    opacity:image.hasContent ? 1 : 0
    Behavior on opacity { NumberAnimation { id:captureFade; duration:Motion.duration(image.animations,140,90,image.animationSpeed); easing.type:Easing.OutCubic } }
  }
  Column {
    anchors.centerIn:parent
    width:Math.max(0,Math.min(parent.width-16,240))
    spacing:image.metrics.sm
    visible:!image.hasContent
    Image {
      id:fallback
      anchors.horizontalCenter:parent.horizontalCenter
      width:Math.min(32,parent.width); height:width
      source:Quickshell.iconPath(image.appIcon,true)
      fillMode:Image.PreserveAspectFit
      sourceSize:Qt.size(width*Screen.devicePixelRatio,height*Screen.devicePixelRatio)
      smooth:true
    }
    Text {
      width:parent.width
      text:image.status==="loading" ? "Loading preview…" : "Preview unavailable"
      color:image.popupColors.text
      opacity:.7
      horizontalAlignment:Text.AlignHCenter
      elide:Text.ElideRight
      textFormat:Text.PlainText
      font.family:image.fonts.family
      font.pixelSize:image.fonts.caption
    }
  }
  Component.onCompleted: { begin(); syncCompatibility() }
  Component.onDestruction:if (stash) stash.previewCompatibilityRequest(compatibilityKey,"")
}
