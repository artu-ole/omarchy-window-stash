pragma ComponentBehavior: Bound
import QtQuick
import Quickshell
import Quickshell.Hyprland
import Quickshell.Io
import "ui"
import "ui/Model.js" as Model
import "ui/PreviewVisibility.js" as PreviewVisibility
import "ui/PreviewInteraction.js" as PreviewInteraction

Item {
  id: root
  property var shell: null
  readonly property string pluginId: "community.window-stash"
  readonly property string controller: decodeURIComponent(Qt.resolvedUrl("controller/stash.py").toString().replace(/^file:\/\//,""))
  readonly property var controllerCommand: ["python3",controller]
  property string lifecycleOwner: Date.now().toString(16)+"-"+Math.random().toString(16).slice(2)
  property bool stopping:false
  property bool lifecycleReady: false
  property string lifecycleError: ""
  property var lifecycleWarnings: []
  property var activeShortcuts: ({})
  property var snapshot: ({windows: [], monitors: [], settings: {presentation: "floating", scope: "global", grouping: "window", restoreDestination: "current", iconShape: "auto", sizePreset:"100", floatingDirection: "vertical", floatingAnimation:"arc", dragMotion:"physics", dockSide: "bottom", staticDockLock:"locked", floatingPlacement:"edges", dockCorners:"theme", dockCornerRadius:12, iconFrame:"hidden", dockFrame:"hidden", animations:"full", animationSpeed:"normal", dockOpacity:100, iconOpacity:100, hoverPreview:"off", livePreviewCompatibility:"standard", previewSize:"medium", previewPlacement:"auto", previewTitles:"shown", previewDelay:400, previewHideDelay:200, floatingPreviewSizing:"free", floatingPreviewScale:"100", floatingPreviewUpdate:"hover", floatingPreviewTitles:"hidden", floatingPreviewFrame:"hidden", floatingPreviewLock:"unlocked", floatingPreviewInteraction:"off", floatingPreviewActivation:"explicit", floatingPreviewKeyboard:"mouse", floatingPreviewInteractionFps:"60", floatingPreviewControls:"hover", floatingPreviewFullscreen:"preview", floatingPreviewExitShortcut:"CTRL + ALT + Escape"}, positions: {}})
  property var queue: []
  property bool pendingRefresh: false
  property string lastError: ""
  property string dialogKind: ""
  property string dialogScreen: ""
  property int dialogWorkspace: 1
  property var dialogWindows: []
  property string dialogQuery: ""
  property var dialogGroup: null
  property string dialogDestination: ""
  property var surfaces: []
  property var pressedPointerButtons: ({})
  readonly property bool pointerButtonHeld:Object.keys(pressedPointerButtons).length>0
  property bool pointerKnown:false
  property point pointerPosition:Qt.point(0,0)
  property var bridgeSupportStatus:({state:"unknown"})
  property string bridgeSupportError:""
  property bool bridgeReloadBusy:false
  property string bridgeReloadStage:""
  property bool bridgeReloadComplete:false
  property bool bridgeReloadFailed:false
  property bool bridgeUpdateDeferred:false
  property string bridgeUpdateNotified:""
  property bool bridgeNotificationPending:false
  property int bridgeSupportGeneration:0
  readonly property bool bridgeUpdateRequired:bridgeSupportStatus.state==="update-required"
  readonly property bool bridgeReloadBlocked:bridgeUpdateRequired && bridgeSupportStatus.canReload===false
  readonly property bool bridgeSupportVisible:bridgeUpdateRequired || bridgeReloadBusy || bridgeSupportError!==""
  readonly property string bridgeSupportText:bridgeSupportError || (bridgeReloadBusy
    ? bridgeReloadStage==="building" ? "Building updated preview support…"
      : bridgeReloadStage==="loading" ? "Loading updated preview support…" : "Finishing preview interaction…"
    : "Updated preview support is available. Reload it to apply the update without closing your applications.")
  readonly property bool pointerTracking:root.surfaces.some(function(surface) {
    return surface.previewPending || surface.previewOpen || surface.floatingDockOpen || surface.floatingPreviewsExpanded || surface.contextMenuOpen
  }) || !!previewInteractionRequest
  property var previewCompatibilityRequests: ({})
  property var previewCompatibilityStatus: ({state:"idle",ids:[]})
  property string previewCompatibilityError:""
  readonly property bool capturePollNeeded:snapshot.windows.length>0
    && (snapshot.settings.presentation==="previews" || snapshot.settings.hoverPreview!=="off")
  property var captureState:({known:false,monitors:[],checkedAt:0,error:""})
  property real captureClock:Date.now()
  function captureAllowedFor(screenName) {
    return capturePollNeeded && PreviewVisibility.allowed(captureState,screenName,captureClock)
  }
  readonly property bool captureAllowed:capturePollNeeded && captureState.monitors.some(function(monitor) {
    return !!monitor && root.captureAllowedFor(monitor.name)
  })
  onCapturePollNeededChanged:if (!capturePollNeeded) captureState={known:false,monitors:[],checkedAt:0,error:""}
  readonly property var previewCompatibilityIds: {
    var liveSource=snapshot.settings.hoverPreview==="live"
      || (snapshot.settings.presentation==="previews" && ["hover","live"].indexOf(snapshot.settings.floatingPreviewUpdate)>=0)
    if (bridgeReloadBusy || !captureAllowed || !liveSource || snapshot.settings.livePreviewCompatibility!=="enhanced") return []
    var ids=Object.keys(previewCompatibilityRequests).map(function(key) { return root.previewCompatibilityRequests[key] })
    return ids.filter(function(id,index) { return ids.indexOf(id)===index }).sort().slice(0,128)
  }
  readonly property string previewCompatibilityStamp:JSON.stringify(previewCompatibilityIds)
  readonly property PreviewKeeperHost previewCompatibilityWorker:previewKeeper.item as PreviewKeeperHost
  onPreviewCompatibilityStampChanged:if (previewCompatibilityWorker) previewCompatibilityWorker.send()
  property bool contextOpen:false
  property var previewInteractionRequest:null
  property var previewInteractionPendingRequest:null
  property bool previewInteractionStopping:false
  property string previewInteractionStopReason:""
  property var previewInteractionStatus:({state:"idle"})
  property string previewInteractionError:""
  property int previewInteractionSerial:0
  readonly property string previewInteractionStamp:JSON.stringify(PreviewInteraction.wire(previewInteractionRequest))
  readonly property InteractionHost previewInteractionWorker:interactionKeeper.item as InteractionHost
  onPreviewInteractionStampChanged:if(previewInteractionWorker) previewInteractionWorker.send()
  onCaptureStateChanged:validatePreviewInteraction()
  onCaptureClockChanged:validatePreviewInteraction()
  onSnapshotChanged:validatePreviewInteraction()
  property string contextScreen:""
  property int contextWorkspace:1
  property point contextPoint:Qt.point(0,0)
  property var contextGroup:null
  property var contextIds:[]
  property int contextSerial:0
  property var pendingCloseIds:({})
  property var runningArgs:[]
  property bool closeNotified:false
  readonly property var shortcutKeys:["minimizeShortcut","restoreLastShortcut","restoreOldestShortcut"]
  readonly property bool shortcutsBusy:(worker.running && ["shortcut","interaction-exit-shortcut"].indexOf(runningArgs[0])>=0)
    || queue.some(function(args) { return ["shortcut","interaction-exit-shortcut"].indexOf(args[0])>=0 })
  readonly property string shortcutStamp:JSON.stringify(shortcutKeys.map(function(key) { return snapshot.settings[key] }))
  property var deferredSettings:[]
  property string shortcutSyncError:""
  property bool resetConfirmation:false
  property bool resetting:false
  property int resetSerial:0
  readonly property bool resetBusy:resetting || (worker.running && runningArgs[0]==="reset-settings")
    || queue.some(function(args) { return args[0]==="reset-settings" })
  readonly property bool settingsBusy:resetBusy || shortcutsBusy || previewInteractionStopping || bridgeReloadBusy
  onShortcutStampChanged:shortcutSyncDelay.restart()

  signal pointerClicked(real x,real y,int button)
  signal pointerMoved(real x,real y)
  signal shortcutConfigured(string key,string value)
  signal settingsReset()
  Timer { id:shortcutSyncDelay; interval:0; onTriggered:root.syncShortcuts() }
  function syncShortcuts() {
    if (lifecycle.running && lifecycleReady) lifecycle.write(JSON.stringify({action:"sync"})+"\n")
  }
  function checkpointPreferences() {
    if (lifecycle.running && lifecycleReady) lifecycle.write(JSON.stringify({settings:root.snapshot.settings})+"\n")
  }
  function lifecycleStatus(value) {
    if (value.owner && value.owner!==lifecycleOwner) return
    if (value.state==="error") {
      lifecycleError=value.error || "Window Stash lifecycle support is unavailable"
      lastError=lifecycleError
      return
    }
    if (value.state!=="ready") return
    var first=!lifecycleReady
    lifecycleReady=true; lifecycleError=""
    if (value.warnings) lifecycleWarnings=value.warnings
    if (value.activeShortcuts) activeShortcuts=value.activeShortcuts
    var previous=shortcutSyncError
    shortcutSyncError=Object.keys(value.conflicts || {}).map(function(key) { return value.conflicts[key] }).join("\n")
    if (shortcutSyncError) lastError=shortcutSyncError
    else if (lastError===previous) lastError=""
    if (first) { root.refresh(); root.pump(); root.checkBridgeSupport() }
  }
  Process {
    id:lifecycle
    command:["python3",decodeURIComponent(Qt.resolvedUrl("controller/lifecycle.py").toString().replace(/^file:\/\//,"")),"--owner",root.lifecycleOwner]
    stdinEnabled:true
    running:true
    stdout:SplitParser {
      onRead:function(line) {
        try { root.lifecycleStatus(JSON.parse(line)) }
        catch (error) { root.lifecycleError="Could not read lifecycle support status"; root.lastError=root.lifecycleError }
      }
    }
    stderr:StdioCollector {}
    onExited:function(code) {
      root.lifecycleReady=false
      if (code!==0) {
        root.lifecycleError="Window Stash lifecycle support stopped unexpectedly"
        root.lastError=root.lifecycleError
      }
      if (!root.stopping) lifecycleRestart.restart()
    }
  }
  Timer {
    id:lifecycleRestart
    interval:750
    onTriggered:if (!root.stopping) {
      root.lifecycleOwner=Date.now().toString(16)+"-"+Math.random().toString(16).slice(2)
      lifecycle.running=true
    }
  }
  StashClickObserver {
    id:clickObserver
    watching:root.pointerButtonHeld || !!root.previewInteractionRequest || root.surfaces.some(function(s) { return s.floatingDockOpen || s.floatingPreviewsExpanded || s.contextMenuOpen || s.previewOpen })
    tracking:root.pointerTracking
    onMoved:function(x,y) { root.pointerPosition=Qt.point(x,y); root.pointerKnown=true; root.pointerMoved(x,y) }
    onClicked:function(x,y,button) {
      var held=Object.assign({},root.pressedPointerButtons); held[button]=true
      root.pressedPointerButtons=held
      root.surfaces.forEach(function(surface) { surface.beginPointerFocusHold() })
      root.pointerClicked(x,y,button)
    }
    onReleased:function(x,y,button) {
      var held=Object.assign({},root.pressedPointerButtons); delete held[button]
      root.pressedPointerButtons=held
    }
  }
  function resetPointerHold() { root.pressedPointerButtons={}; clickObserver.resetHeld() }

  function refresh() { refreshDelay.restart() }
  function previewCompatibilityRequest(key,id) {
    var requests=Object.assign({},previewCompatibilityRequests)
    if (id) requests[key]=id
    else delete requests[key]
    previewCompatibilityRequests=requests
  }
  // Authentication services are deliberately private in the host. Use the
  // compositor's passive output state instead of traversing its lock objects.
  Loader {
    active:root.capturePollNeeded
    sourceComponent:Item {
      id:monitorPoll
      property bool outputReady:false
      property bool exited:false
      property bool completed:false
      property bool timedOut:false
      property int exitCode:-1
      property string output:""
      function begin() {
        root.captureClock=Date.now()
        if (query.running) return
        outputReady=false; exited=false; completed=false; timedOut=false; exitCode=-1; output=""
        query.running=true
      }
      function complete() {
        if (!outputReady || !exited || completed || timedOut) return
        completed=true; deadline.stop()
        root.captureClock=Date.now()
        try {
          var monitors=exitCode===0 ? JSON.parse(output) : null
          if (!Array.isArray(monitors)) throw new Error("unreadable")
          root.captureState={known:true,monitors:monitors,checkedAt:root.captureClock,error:""}
        } catch (error) {
          root.captureState={known:false,monitors:[],checkedAt:root.captureClock,error:"Monitor capture state is unavailable"}
        }
        output=""
      }
      Process {
        id:query
        command:["hyprctl","-j","monitors"]
        stdout:StdioCollector { onStreamFinished: { monitorPoll.output=text; monitorPoll.outputReady=true; monitorPoll.complete() } }
        onStarted:deadline.restart()
        onExited:function(code) { monitorPoll.exitCode=code; monitorPoll.exited=true; monitorPoll.complete() }
      }
      Timer {
        id:deadline; interval:2000
        onTriggered: {
          monitorPoll.timedOut=true
          root.captureClock=Date.now()
          root.captureState={known:false,monitors:[],checkedAt:root.captureClock,error:"Monitor capture state timed out"}
          if (query.running) query.signal(9)
        }
      }
      Timer { interval:500; repeat:true; running:true; triggeredOnStart:true; onTriggered:monitorPoll.begin() }
    }
  }
  // The pipe lifetime owns the optional native lease. Hiding the final Live
  // thumbnail destroys the process; EOF/SIGTERM and the native TTL release it.
  Loader {
    id:previewKeeper
    active:root.previewCompatibilityIds.length>0
    sourceComponent:PreviewKeeperHost {}
  }
  component PreviewKeeperHost:Item {
      id:keeperHost
      readonly property bool running:keeper.running
      function send() { if (keeper.running) keeper.write(root.previewCompatibilityStamp+"\n") }
      Process {
        id:keeper
        command:["python3",decodeURIComponent(Qt.resolvedUrl("controller/preview.py").toString().replace(/^file:\/\//,""))]
        stdinEnabled:true
        running:true
        onStarted: {
          root.previewCompatibilityError=""
          root.previewCompatibilityStatus={state:"starting",ids:[]}
          keeperHost.send()
        }
        stdout:SplitParser {
          onRead:function(line) {
            try {
              var value=JSON.parse(line)
              if (["idle","paused","disabled","building","loading","ready","unavailable"].indexOf(value.state)<0) return
              root.previewCompatibilityStatus=value
              if (value.error) root.previewCompatibilityError=String(value.error)
            } catch (error) { root.previewCompatibilityError="Could not read live preview support status" }
          }
        }
        onExited:function(code) {
          if (code!==0 && !root.previewCompatibilityError) root.previewCompatibilityError="Live preview support is unavailable; standard previews remain available"
        }
      }
      Component.onDestruction: {
        root.previewCompatibilityStatus={state:"idle",ids:[]}
        // Image delegates own their request keys. The worker can unload
        // while those delegates still exist (for example during DPMS/lock
        // suspension), and must not mutate the Loader's request dependency.
      }
  }
  function enqueue(args) {
    if(previewInteractionRequest && ["restore","restore-last","restore-oldest","restore-all","minimize","activate","close","close-all","reset-settings"].indexOf(args[0])>=0)
      endPreviewInteraction("window-action")
    var next = queue.slice()
    next.push(args)
    queue = next
    pump()
  }
  function previewInteractionMatches(id,monitor,key) {return PreviewInteraction.matches(previewInteractionRequest,id,monitor,key)}
  function previewInteractionPendingMatches(id,monitor,key) {return PreviewInteraction.matches(previewInteractionPendingRequest,id,monitor,key)}
  function validInteractionTarget(request) {
    return !!request && lifecycleReady && !bridgeReloadBusy && PreviewInteraction.enabled(snapshot.settings) && captureAllowedFor(request.monitor)
      && !pendingCloseIds[request.id] && snapshot.windows.some(function(window) {return window.id===request.id && window.phase==="stashed"})
      && snapshot.monitors.some(function(monitor) {return monitor.name===request.monitor})
  }
  function activatePreviewInteraction(request) {
    if(!validInteractionTarget(request) || previewInteractionRequest || stopping) return false
    previewInteractionError="";previewInteractionStopReason="";previewInteractionStopping=false
    previewInteractionStatus={state:"starting",id:request.id,serial:request.serial}
    previewInteractionRequest=request
    interactionKeeper.active=true
    return true
  }
  function beginPreviewInteraction(record,monitor,key,rect,excludeRects) {
    if(!record || bridgeReloadBusy || pendingCloseIds[record.id] || !lifecycleReady || !captureAllowedFor(monitor)
        || !snapshot.windows.some(function(window) {return window.id===record.id && window.phase==="stashed"})) return false
    var request=PreviewInteraction.request(previewInteractionSerial+1,record.id,monitor,key,rect,excludeRects,snapshot.settings)
    if(!request) return false
    closeContext();closeDialog()
    previewInteractionSerial=request.serial
    if(previewInteractionRequest) {
      previewInteractionPendingRequest=request
      endPreviewInteraction("replaced")
      return true
    }
    return activatePreviewInteraction(request)
  }
  function updatePreviewInteraction(id,monitor,key,rect,excludeRects) {
    if(previewInteractionPendingMatches(id,monitor,key)) {
      previewInteractionPendingRequest=PreviewInteraction.request(previewInteractionPendingRequest.serial,id,monitor,key,rect,excludeRects,snapshot.settings)
      return
    }
    if(!previewInteractionMatches(id,monitor,key)) return
    if(previewInteractionStopping) return
    var request=PreviewInteraction.request(previewInteractionRequest.serial,id,monitor,key,rect,excludeRects,snapshot.settings)
    if(!request) {endPreviewInteraction("geometry-unavailable");return}
    if(JSON.stringify(request)!==JSON.stringify(previewInteractionRequest)) previewInteractionRequest=request
  }
  function endPreviewInteraction(reason) {
    if(reason!=="replaced") previewInteractionPendingRequest=null
    if(!previewInteractionRequest) return
    if(previewInteractionStopping) return
    previewInteractionStopping=true;previewInteractionStopReason=reason || "stopped"
    previewInteractionStatus={state:"stopping",id:previewInteractionRequest.id,serial:previewInteractionRequest.serial,reason:previewInteractionStopReason}
    if(previewInteractionWorker) previewInteractionWorker.stop()
    interactionStopDeadline.restart()
  }
  function finishPreviewInteraction(value) {
    interactionStopDeadline.stop();interactionKillDeadline.stop();interactionExpiryDeadline.stop()
    previewInteractionStatus=value
    previewInteractionRequest=null;previewInteractionStopping=false;previewInteractionStopReason=""
    interactionKeeper.active=false
    Qt.callLater(function() {
      var pending=root.previewInteractionPendingRequest
      if(!pending || root.previewInteractionRequest || root.stopping) return
      root.previewInteractionPendingRequest=null
      root.activatePreviewInteraction(pending)
    })
    Qt.callLater(root.pump)
    Qt.callLater(root.applyDeferredSettings)
  }
  function quarantinePreviewInteraction(reason) {
    if(!previewInteractionRequest) return
    previewInteractionStopping=true;previewInteractionStopReason=reason
    previewInteractionStatus={state:"stopping",id:previewInteractionRequest.id,serial:previewInteractionRequest.serial,reason:reason}
    interactionStopDeadline.stop();interactionKillDeadline.stop()
    // An abnormal worker exit cannot acknowledge native cleanup. Its last
    // renewal expires after 2500 ms; keep management frozen past that limit.
    if(!interactionExpiryDeadline.running) interactionExpiryDeadline.restart()
  }
  function validatePreviewInteraction() {
    if(previewInteractionPendingRequest && !validInteractionTarget(previewInteractionPendingRequest)) previewInteractionPendingRequest=null
    var request=previewInteractionRequest
    if(!request) return
    if(!validInteractionTarget(request)) {
      endPreviewInteraction("preview-unavailable");return
    }
    if(previewInteractionStopping) return
    var next=PreviewInteraction.request(request.serial,request.id,request.monitor,request.viewKey,request.rect,request.excludeRects,snapshot.settings)
    if(JSON.stringify(next)!==JSON.stringify(request)) previewInteractionRequest=next
  }
  function interactionMessage(value,serial) {
    if(!previewInteractionRequest || previewInteractionRequest.serial!==serial) return
    if(!value || ["starting","building","loading","active","ended","idle","unavailable"].indexOf(value.state)<0)
      throw new Error("Invalid interactive preview status")
    if(value.serial!==undefined && value.serial!==serial) return
    if(value.state==="active" && value.id!==previewInteractionRequest.id) throw new Error("Interactive preview target changed")
    if(value.error) previewInteractionError=String(value.error)
    if(["ended","idle"].indexOf(value.state)>=0) {
      // A native outside click permanently ends this activation. Clearing the
      // owner, rather than merely renewing a stale rectangle, prevents re-entry.
      finishPreviewInteraction(value)
    } else if(value.state==="unavailable") quarantinePreviewInteraction("native-unavailable")
    else if(!previewInteractionStopping) previewInteractionStatus=value
  }
  Timer {
    id:interactionStopDeadline;interval:1500
    onTriggered:if(root.previewInteractionRequest && root.previewInteractionStopping) {
      if(root.previewInteractionWorker) root.previewInteractionWorker.terminate(15)
      interactionKillDeadline.restart()
    }
  }
  Timer {
    id:interactionKillDeadline;interval:1000
    onTriggered:if(root.previewInteractionRequest && root.previewInteractionStopping) {
      if(root.previewInteractionWorker) root.previewInteractionWorker.terminate(9)
      root.quarantinePreviewInteraction("release-timeout")
    }
  }
  Timer {
    id:interactionExpiryDeadline;interval:2800
    onTriggered:if(root.previewInteractionRequest) root.finishPreviewInteraction({state:"ended",id:root.previewInteractionRequest.id,
      serial:root.previewInteractionRequest.serial,reason:"native-lease-expired"})
  }
  Loader {
    id:interactionKeeper
    active:false
    sourceComponent:InteractionHost {}
  }
  component InteractionHost:Item {
    id:interactionHost
    readonly property bool running:interactionProcess.running
    property int serial:0
    property bool stopSent:false
    function send() {
      if(!root.previewInteractionStopping && interactionProcess.running && root.previewInteractionRequest && serial===root.previewInteractionRequest.serial)
        interactionProcess.write(root.previewInteractionStamp+"\n")
    }
    function stop() {
      if(interactionProcess.running && !stopSent) {stopSent=true;interactionProcess.write("null\n")}
    }
    function terminate(signal) {if(interactionProcess.running) interactionProcess.signal(signal)}
    Component.onCompleted:serial=root.previewInteractionRequest ? root.previewInteractionRequest.serial : 0
    Process {
      id:interactionProcess
      command:["python3",decodeURIComponent(Qt.resolvedUrl("controller/interaction.py").toString().replace(/^file:\/\//,""))]
      stdinEnabled:true
      running:true
      onStarted: {if(root.previewInteractionStopping) interactionHost.stop();else interactionHost.send()}
      stdout:SplitParser {
        onRead:function(line) {
          try {root.interactionMessage(JSON.parse(line),interactionHost.serial)}
          catch(error) {
            root.previewInteractionError="Could not read interactive preview status"
            root.endPreviewInteraction("invalid-status")
          }
        }
      }
      stderr:StdioCollector {}
      onExited:function(code) {
        if(!root.previewInteractionRequest || root.previewInteractionRequest.serial!==interactionHost.serial) return
        if(code===0) root.finishPreviewInteraction({state:"ended",id:root.previewInteractionRequest.id,serial:interactionHost.serial,
          reason:root.previewInteractionStopReason || "worker-exited"})
        else {
          if(!root.previewInteractionError) root.previewInteractionError="Interactive preview support stopped unexpectedly"
          root.quarantinePreviewInteraction("worker-failed")
        }
      }
    }
  }
  function pump() {
    if (worker.running || !lifecycleReady || previewInteractionStopping || bridgeReloadBusy) return
    if (queue.length === 0) {
      if (pendingRefresh) { pendingRefresh = false; enqueue(["list"]) }
      return
    }
    var next = queue.slice()
    var args = next.shift()
    queue = next
    runningArgs=args; closeNotified=false
    worker.command = controllerCommand.concat(args)
    worker.running = true
  }
  // Updating the native bridge is a separate, explicit action. Pause every
  // helper before unloading so a live delegate cannot reacquire the old API.
  function checkBridgeSupport() {
    if(stopping || !lifecycleReady || bridgeReloadBusy || bridgeProbe.running) return
    bridgeProbe.generation=bridgeSupportGeneration
    bridgeProbe.running=true
  }
  function bridgeSupportMessage(value) {
    if(!value || ["current","absent","update-required","error","busy"].indexOf(value.state)<0)
      throw new Error("Invalid preview support status")
    bridgeSupportStatus=value
    if(value.state==="error") bridgeSupportError=String(value.error || "Could not check preview support")
    if(value.state==="current" || value.state==="absent") {
      bridgeUpdateDeferred=false
      bridgeUpdateNotified=""
      bridgeNotificationPending=false
      if(value.state==="current") bridgeReloadFailed=false
      if(!bridgeReloadBusy && !bridgeReloadFailed) bridgeSupportError=""
    }
    if(value.state==="update-required") {
      if(value.canReload===false) bridgeSupportError=String(value.error || "This preview extension requires a one-time logout and login to apply the update. Running applications will close.")
      else if(!bridgeReloadFailed && !bridgeReloadBusy) bridgeSupportError=""
      var key=String(value.loadedVersion || "unknown")+":"+String(value.expectedVersion || "unknown")+":"+String(value.canReload!==false)
      if(key!==bridgeUpdateNotified && !bridgeUpdateDeferred) {
        bridgeUpdateNotified=key
        bridgeNotificationPending=true
        beginBridgeNotification()
      }
    }
  }
  function beginBridgeNotification() {
    if(!bridgeNotificationPending || stopping || bridgeReloadBusy || !bridgeUpdateRequired || bridgeUpdateDeferred) return
    if(bridgeNotification.running) {
      if(bridgeNotification.supportsReload===bridgeReloadBlocked) bridgeNotification.signal(15)
      return
    }
    bridgeNotification.supportsReload=!bridgeReloadBlocked
    bridgeNotificationPending=false
    bridgeNotification.running=true
  }
  function deferBridgeUpdate() {bridgeUpdateDeferred=true;bridgeNotificationPending=false}
  function reloadPreviewSupport() {
    if(stopping || bridgeReloadBusy || bridgeReloadBlocked || !lifecycleReady || resetBusy || shortcutsBusy) return false
    bridgeSupportError="";bridgeReloadComplete=false;bridgeReloadFailed=false;bridgeReloadStage="stopping"
    bridgeSupportGeneration++
    bridgeReloadBusy=true;bridgeUpdateDeferred=false
    bridgeNotificationPending=false
    previewInteractionPendingRequest=null
    endPreviewInteraction("bridge-update")
    bridgeReloadWait.restart()
    bridgeReloadWaitDeadline.restart()
    return true
  }
  function beginBridgeReload() {
    if(!bridgeReloadBusy || bridgeReload.running || previewInteractionRequest || previewInteractionStopping || worker.running) return
    bridgeReloadWait.stop();bridgeReloadWaitDeadline.stop()
    bridgeReloadStage="building"
    bridgeReload.running=true
    bridgeReloadDeadline.restart()
  }
  function bridgeReloadMessage(value) {
    if(!bridgeReloadBusy || !value || ["building","stopping","loading","ready","error","cancelled"].indexOf(value.state)<0) return
    bridgeReloadStage=value.state
    if(value.state==="error" || value.state==="cancelled" || value.ok===false) {
      bridgeReloadComplete=false
      bridgeSupportError=String(value.error || "Could not reload preview support")
    } else if(value.state==="ready" && value.ok===true) {
      bridgeReloadComplete=true
      bridgeSupportStatus=Object.assign({},value,{state:"current"})
    }
  }
  function finishBridgeReload(code) {
    if(!bridgeReloadBusy) return
    bridgeReloadWait.stop();bridgeReloadWaitDeadline.stop();bridgeReloadDeadline.stop();bridgeReloadKillDeadline.stop()
    if(code!==0 || !bridgeReloadComplete) {
      bridgeReloadFailed=true
      if(!bridgeSupportError) bridgeSupportError="Could not reload preview support. Try again, or log out and back in later."
    } else {
      bridgeSupportError="";bridgeUpdateNotified=""
      previewCompatibilityError="";previewInteractionError=""
      previewCompatibilityStatus={state:"idle",ids:[]}
    }
    bridgeReloadBusy=false;bridgeReloadStage=""
    Qt.callLater(root.checkBridgeSupport)
    Qt.callLater(root.pump)
    Qt.callLater(root.applyDeferredSettings)
  }
  Timer { id:bridgeReloadWait;interval:40;repeat:true;onTriggered:root.beginBridgeReload() }
  Timer {
    id:bridgeReloadWaitDeadline;interval:10000
    onTriggered:if(root.bridgeReloadBusy && !bridgeReload.running) {
      root.bridgeSupportError="Could not pause preview support while another window action is finishing. Try again when ready."
      root.finishBridgeReload(1)
    }
  }
  Timer {
    id:bridgeReloadDeadline;interval:150000
    onTriggered:if(bridgeReload.running) {
      root.bridgeSupportError="Preview support reload timed out. Try again when ready."
      bridgeReload.signal(15);bridgeReloadKillDeadline.restart()
    }
  }
  Timer {id:bridgeReloadKillDeadline;interval:5000;onTriggered:if(bridgeReload.running) bridgeReload.signal(9)}
  Timer { interval:30000;repeat:true;running:root.lifecycleReady && !root.stopping;onTriggered:root.checkBridgeSupport() }
  Process {
    id:bridgeProbe
    property int generation:0
    command:["python3",decodeURIComponent(Qt.resolvedUrl("controller/bridge.py").toString().replace(/^file:\/\//,"")),"status"]
    stdout:StdioCollector {
      onStreamFinished: {
        if(root.bridgeReloadBusy || root.stopping || bridgeProbe.generation!==root.bridgeSupportGeneration) return
        try {root.bridgeSupportMessage(JSON.parse(text))}
        catch(error) {root.bridgeSupportError="Could not read preview support status"}
      }
    }
    stderr:StdioCollector {}
  }
  Process {
    id:bridgeReload
    command:["python3",decodeURIComponent(Qt.resolvedUrl("controller/bridge.py").toString().replace(/^file:\/\//,"")),"reload","--watch-stdin"]
    stdinEnabled:true
    stdout:SplitParser {
      onRead:function(line) {
        try {root.bridgeReloadMessage(JSON.parse(line))}
        catch(error) {root.bridgeSupportError="Could not read preview support reload status"}
      }
    }
    stderr:StdioCollector {}
    onExited:function(code) {Qt.callLater(function() {root.finishBridgeReload(code)})}
  }
  Process {
    id:bridgeNotification
    property bool supportsReload:true
    command:["notify-send","--app-name=Window Stash","--wait","--expire-time=30000"]
      .concat(supportsReload ? ["--action=reload=Reload preview support","--action=later=Later",
      "Window Stash update ready","Reload preview support to apply the update without closing applications."]
      : ["--action=later=Later","Preview support update requires session restart",
        "Log out and back in when convenient to activate updated preview support. Running applications will close."])
    stdout:StdioCollector {
      onStreamFinished: {
        if(root.stopping) return
        if(!root.bridgeUpdateRequired) return
        if(text.trim()==="reload" && !root.bridgeReloadBlocked) root.reloadPreviewSupport()
        else if(text.trim()==="later") root.deferBridgeUpdate()
      }
    }
    stderr:StdioCollector {}
    onExited:Qt.callLater(root.beginBridgeNotification)
  }
  function screenMonitor(name) {
    for (var i = 0; i < snapshot.monitors.length; i++)
      if (snapshot.monitors[i].name === name) return snapshot.monitors[i]
    return null
  }
  function invocationWorkspace(name) {
    var surface=surfaces.find(function(s) { return s.screen.name===name })
    if (surface && surface.activeWorkspaceId!==-1) return surface.activeWorkspaceId
    var monitor=screenMonitor(name)
    return monitor ? monitor.activeWorkspace.id : 1
  }
  function openContext(group,name,point) {
    var m=screenMonitor(name)
    if (!m || !group) return
    endPreviewInteraction("menu")
    resetConfirmation=false
    contextScreen=name; contextWorkspace=invocationWorkspace(name)
    contextPoint=Qt.point(point.x,point.y)
    contextGroup=Object.assign({},group,{windows:group.windows.slice()})
    contextIds=group.windows.map(function(w) { return w.id })
    contextSerial++; contextOpen=true
  }
  function closeContext() { contextOpen=false }
  function contextWindows() {
    return snapshot.windows.filter(function(w) { return contextIds.indexOf(w.id)>=0 })
  }
  function scopeWindows(name,workspace) {
    var m=screenMonitor(name)
    return Model.visibleWindows(snapshot.windows,workspace===undefined ? invocationWorkspace(name) : workspace,snapshot.settings.scope)
  }
  function scopeCount(name) { return scopeWindows(name).length }
  function groupClosing(group) {
    return group && group.windows.some(function(w) { return !!pendingCloseIds[w.id] })
  }
  function closeWindows(windows,name,workspace) {
    var m=screenMonitor(name)
    if (!m) return
    var ids=windows.map(function(w) { return w.id }).filter(function(id,index,all) {
      return all.indexOf(id)===index && !root.pendingCloseIds[id]
        && root.snapshot.windows.some(function(w) { return w.id===id })
    })
    if (!ids.length) return
    var pending=Object.assign({},pendingCloseIds)
    ids.forEach(function(id) { pending[id]=true })
    pendingCloseIds=pending
    enqueue(["close"].concat(ids,["--monitor",name,"--workspace",String(workspace===undefined ? invocationWorkspace(name) : workspace)]))
  }
  function closeGroup(group,name) { if (group) closeWindows(group.windows,name) }
  function closeContextWindows() {
    var windows=contextWindows(),name=contextScreen,workspace=contextWorkspace
    closeContext(); closeDialog(); closeWindows(windows,name,workspace)
  }
  function closeContextAll() {
    var windows=scopeWindows(contextScreen,contextWorkspace),name=contextScreen,workspace=contextWorkspace
    closeContext(); closeDialog(); closeWindows(windows,name,workspace)
  }
  function interactContext() {
    var windows=contextWindows(),name=contextScreen
    closeContext();closeDialog()
    if(windows.length!==1) return
    var surface=surfaces.find(function(item) {return item.screen.name===name})
    if(surface) Qt.callLater(function() {surface.activatePreviewInteraction(windows[0].id)})
  }
  function restoreContext(destination) {
    var windows=contextWindows(),name=contextScreen,workspace=contextWorkspace,group=contextGroup
    closeContext()
    if (!windows.length) return
    if (windows.length===1) {
      closeDialog()
      enqueue(["restore",windows[0].id,"--to",destination,"--monitor",name,"--workspace",String(workspace)])
    } else {
      openDialog("picker",name,windows,group)
      dialogWorkspace=workspace; dialogDestination=destination
    }
  }
  function notifyCloseError(message) {
    if (closeNotified) return
    closeNotified=true
    Quickshell.execDetached(["notify-send","--app-name=Window Stash","Could not close every stashed window",message])
  }
  function finishWorker(code) {
    if (runningArgs[0]==="close") {
      var pending=Object.assign({},pendingCloseIds)
      for (var i=1;i<runningArgs.length && !String(runningArgs[i]).startsWith("--");i++) delete pending[runningArgs[i]]
      pendingCloseIds=pending; pendingRefresh=true
      if (code!==0) {
        if (!lastError) lastError="Close request failed"
        notifyCloseError(lastError)
      }
    }
    if (["shortcut","interaction-exit-shortcut"].indexOf(runningArgs[0])>=0) pendingRefresh=true
    if (runningArgs[0]==="reset-settings") {
      if (resetting && !lastError) lastError="Could not confirm the settings reset"
      resetting=false; pendingRefresh=true
    }
    Qt.callLater(pump)
  }
  function openDialog(kind, name, windows, group) {
    endPreviewInteraction("dialog")
    resetConfirmation=false
    closeContext()
    var m = screenMonitor(name)
    if (!m) return
    dialogScreen = name
    dialogWorkspace = invocationWorkspace(name)
    dialogWindows = windows || []
    dialogGroup = group || null
    dialogQuery = ""
    dialogDestination = ""
    dialogKind = kind
    if(kind==="settings") checkBridgeSupport()
  }
  function closeDialog() { resetConfirmation=false; dialogKind = ""; dialogGroup = null; dialogQuery = "" }
  function askResetSettings() {
    if (dialogKind!=="settings" || settingsBusy || deferredSettings.length) return
    lastError=""; resetConfirmation=true
  }
  function cancelResetSettings() { resetConfirmation=false }
  function resetSettings() {
    if (dialogKind!=="settings" || !resetConfirmation || settingsBusy || deferredSettings.length) return
    resetConfirmation=false; resetting=true; resetSerial++
    deferredSettings=[]; lastError=""; shortcutSyncError=""
    enqueue(["reset-settings","--confirm"])
  }
  function restoreWindow(id, destination) {
    var m = screenMonitor(dialogScreen)
    if (!m) return
    var args = ["restore", id, "--monitor", m.name, "--workspace", String(dialogWorkspace)]
    var chosen = destination || dialogDestination
    if (chosen) args = args.concat(["--to", chosen])
    closeDialog()
    enqueue(args)
  }
  function restoreNativePreviewWindow(id) {
    // Native guards stop passive PiP activation before it can expose SPECIAL.
    // The event is an intent only; normal restore revalidates the exact ledger
    // identity and ownership before changing any application window.
    if(typeof id!=="string" || !/^[0-9a-f]{32}$/.test(id) || !lifecycleReady || stopping
        || pendingCloseIds[id] || !snapshot.windows.some(function(window) {return window.id===id && window.phase==="stashed"})) return false
    function sameRestore(args) {return args.length>1 && args[0]==="restore" && args[1]===id}
    if((worker.running && sameRestore(runningArgs)) || queue.some(sameRestore)) return false
    var name=focusedScreen()
    if(!screenMonitor(name)) return false
    restorePreviewWindow(id,name)
    return true
  }
  function restorePreviewWindow(id,name) {
    if (!screenMonitor(name) || pendingCloseIds[id] || !snapshot.windows.some(function(w) { return w.id===id })) return
    if (dialogKind==="picker" && dialogScreen===name && dialogWindows.some(function(w) { return w.id===id })) {
      restoreWindow(id,""); return
    }
    closeContext(); closeDialog()
    enqueue(["restore",id,"--monitor",name,"--workspace",String(invocationWorkspace(name))])
  }
  function dismissPreviews(exceptScreen) {
    surfaces.forEach(function(s) { if (s.screen.name!==exceptScreen) s.dismissPreview() })
  }
  function selectGroup(group, name) {
    if (group.windows.length > 1) { openDialog("picker", name, group.windows, group); return }
    openDialog("restore", name, group.windows, group)
    restoreWindow(group.windows[0].id, "")
  }
  function setting(key, value) {
    if (!shell) { lastError = "Shell settings are not available"; return }
    if (resetBusy || resetConfirmation || bridgeReloadBusy) return
    if(previewInteractionRequest) {
      deferredSettings=deferredSettings.concat([[key,value]])
      endPreviewInteraction("settings")
      return
    }
    shortcutSyncError=""
    if (key==="floatingPreviewExitShortcut") {
      lastError=""
      enqueue(["interaction-exit-shortcut",String(value)])
      return
    }
    if (shortcutKeys.indexOf(key)>=0) {
      lastError=""
      enqueue(["shortcut",key,String(value)])
      return
    }
    if (shortcutsBusy) {
      deferredSettings=deferredSettings.concat([[key,value]])
      return
    }
    var options = {presentation:["dock","bubbles","floating","previews"], scope:["global","workspace"],
      restoreDestination:["current","original"], grouping:["window","app"],
      iconShape:["auto","circle","square","rounded","squircle"], sizePreset:["50","75","100","125","150","175","200","250","300"], floatingDirection:["vertical","horizontal"], floatingAnimation:["arc","glide","cascade","spring","swing","matryoshka","matryoshka-hop","jumping"], dragMotion:["physics","direct"], dockSide:["bottom","top","left","right"], staticDockLock:["locked","unlocked"], floatingPlacement:["edges","free"], dockCorners:["theme","custom"], iconFrame:["shown","hidden"], dockFrame:["shown","hidden"], animations:["full","reduced","off"],animationSpeed:["slow","relaxed","normal","fast","ultrafast"]}
    options.hoverPreview=["off","still","live"]; options.livePreviewCompatibility=["standard","enhanced"]; options.previewSize=["small","medium","large"]
    options.previewPlacement=["auto","above","below","left","right"]; options.previewTitles=["shown","hidden"]
    options.floatingPreviewSizing=["free","preset"]; options.floatingPreviewScale=options.sizePreset
    options.floatingPreviewUpdate=["still","hover","live"]; options.floatingPreviewTitles=["shown","hidden"]
    options.floatingPreviewFrame=["shown","hidden"]; options.floatingPreviewLock=["locked","unlocked"]
    options.floatingPreviewInteraction=["off","on"]; options.floatingPreviewActivation=["explicit","click"]
    options.floatingPreviewKeyboard=["mouse","click"]; options.floatingPreviewInteractionFps=["30","60"]
    options.floatingPreviewControls=["hover","always"]; options.floatingPreviewFullscreen=["preview","desktop"]
    var numericLimits={dockCornerRadius:64,dockOpacity:100,iconOpacity:100,previewDelay:1500,previewHideDelay:1000}
    if (numericLimits[key] !== undefined) {
      if (!/^(0|[1-9][0-9]{0,3})$/.test(String(value)) || Number(value) > numericLimits[key]) {
        lastError = key === "dockCornerRadius" ? "Dock corner radius must be 0–64 pixels"
          : key === "previewDelay" || key === "previewHideDelay" ? key+" must be a whole number from 0 to "+numericLimits[key]+" milliseconds"
          : "Opacity must be a whole percentage from 0 to 100"
        return
      }
      value = Number(value)
    } else if (!options[key] || options[key].indexOf(value) < 0) { lastError = "Invalid stash setting"; return }
    lastError = ""
    // The host replaces the entry with the supplied settings; it does not
    // merge a patch. Keep the other choices intact on every edit.
    var patch = Object.assign({}, snapshot.settings)
    patch[key] = value
    var next = Object.assign({}, snapshot)
    next.settings = patch
    snapshot = next
    shell.updateEntryInline(pluginId, patch)
    checkpointPreferences()
    refresh()
  }
  function applyDeferredSettings() {
    if (settingsBusy || previewInteractionRequest || resetConfirmation || !deferredSettings.length) return
    var edits=deferredSettings.slice(); deferredSettings=[]
    edits.forEach(function(edit) { root.setting(edit[0],edit[1]) })
  }
  function positionPending(key) {
    function targets(args) { return (args[0]==="position" || args[0]==="preview-position") && args[2]===key }
    return (worker.running && targets(runningArgs)) || queue.some(targets)
  }
  function recordPosition(monitor, key, x, y) {
    var owner=key.indexOf("dock:static:")===0 ? Model.staticDockMonitorKey(monitor) : Model.monitorKey(monitor)
    enqueue(["position", owner, key, String(Math.round(x)), String(Math.round(y))])
  }
  function recordPreviewPosition(monitor,key,x,y,width) {
    enqueue(["preview-position",Model.staticDockMonitorKey(monitor),key,String(Math.round(x)),String(Math.round(y)),String(Math.round(width))])
  }
  function allWindows(name) { openDialog("picker", name, snapshot.windows, null) }
  function focusedScreen() {
    for (var i = 0; i < snapshot.monitors.length; i++)
      if (snapshot.monitors[i].focused) return snapshot.monitors[i].name
    return snapshot.monitors.length ? snapshot.monitors[0].name : ""
  }

  Timer {
    id: refreshDelay
    interval: 70
    onTriggered: {
      if (worker.running || root.queue.length) root.pendingRefresh = true
      else root.enqueue(["list"])
    }
  }
  // A switcher can activate a parked Wayland toplevel directly. Check the
  // compositor's current focus after the initiating transaction completes;
  // never infer activation from a stale UI snapshot or mutate another plugin.
  Timer {
    id:externalActivationDelay
    interval:100
    onTriggered:if (root.lifecycleReady) root.enqueue(["recover-focused"])
  }
  // Reserve changes do not emit workspace events. Refresh while a visible
  // dock or edge-snapped bubble needs to stay clear of bars.
  Timer {
    interval: 1500
    repeat: true
    running: (root.snapshot.settings.presentation === "dock" || root.snapshot.settings.floatingPlacement !== "free") && root.surfaces.some(function(s) { return s.windows.length > 0 })
    onTriggered: root.refresh()
  }
  Process {
    id: worker
    stdout: StdioCollector {
      onStreamFinished: {
        try {
          var result = JSON.parse(text)
          if (result.windows) { root.snapshot = result; Qt.callLater(root.applyDeferredSettings) }
          if (result.action==="close" && result.restored>0) { root.closeContext(); root.closeDialog() }
          if (result.ok === false) {
            var message=result.error || "Window action failed"
            if (root.runningArgs[0]==="shortcuts-sync") {
              var previous=root.shortcutSyncError; root.shortcutSyncError=message
              if (!root.lastError || root.lastError===previous) root.lastError=message
            } else root.lastError=message
            if (root.runningArgs[0]==="close") root.notifyCloseError(root.lastError)
          }
          else if (!result.windows) {
            if (root.runningArgs[0]!=="shortcuts-sync") root.lastError = ""
            else {
              if (root.lastError===root.shortcutSyncError) root.lastError=""
              root.shortcutSyncError=""
            }
            root.pendingRefresh = true
            if (["shortcut","interaction-exit-shortcut"].indexOf(root.runningArgs[0])>=0 && result.key!==undefined && result.binding!==undefined) {
              var next=Object.assign({},root.snapshot), settings=Object.assign({},root.snapshot.settings)
              settings[result.key]=result.binding; next.settings=settings; root.snapshot=next
              root.checkpointPreferences()
              root.shortcutConfigured(result.key,result.binding)
            }
            if (root.runningArgs[0]==="reset-settings" && result.action==="settings-reset" && result.settings) {
              var resetSnapshot=Object.assign({},root.snapshot)
              resetSnapshot.settings=Object.assign({},result.settings)
              root.snapshot=resetSnapshot
              root.checkpointPreferences()
              root.resetting=false
              root.settingsReset()
            }
          }
          if (root.runningArgs[0]==="close") root.pendingRefresh=true
        } catch (error) {
          root.lastError = "Could not read controller response: " + String(error)
          if (root.runningArgs[0]==="close") root.notifyCloseError(root.lastError)
        }
      }
    }
    onExited: function(exitCode) { root.finishWorker(exitCode) }
  }
  FileView {
    path: root.snapshot.statePath || ""
    watchChanges: true
    onFileChanged: { reload(); root.refresh() }
  }
  FileView {
    path: (Quickshell.env("XDG_CONFIG_HOME") || Quickshell.env("HOME") + "/.config") + "/omarchy/shell.json"
    watchChanges: true
    onFileChanged: { reload(); root.refresh() }
  }
  Connections {
    target: Hyprland
    function onRawEvent(event) {
      if (!event) return
      if(event.name==="window-stash-restore") root.restoreNativePreviewWindow(String(event.data || ""))
      if (event.name==="activewindowv2" && root.snapshot.windows.length) externalActivationDelay.restart()
      if (event.name==="configreloaded") {
        shortcutSyncDelay.restart()
        root.pointerKnown=false; root.resetPointerHold()
      }
      if (event.name==="monitorremoved") root.endPreviewInteraction("monitor-removed")
      if (root.contextOpen && (event.name==="workspace" || event.name==="workspacev2" || event.name==="monitorremoved")) root.closeContext()
      if (event.name === "changeworkspaceid") {
        var parts = String(event.data || "").split(",")
        if (parts.length >= 2) root.enqueue(["rebase", parts[0], parts[1]])
      }
      if (/window|workspace|monitor|fullscreen|configreloaded/.test(String(event.name))) root.refresh()
    }
  }
  Connections {
    target: Quickshell
    function onScreensChanged() { root.endPreviewInteraction("screens-changed"); root.closeContext(); root.closeDialog(); root.refresh() }
  }
  Variants {
    model: Quickshell.screens
    delegate: StashSurface { required property var modelData; screen: modelData; stash: root }
  }
  IpcHandler {
    target: "window-stash"
    function status(): string {
      return JSON.stringify({loaded: true, windows: root.snapshot.windows.length,
        lifecycle:{ready:root.lifecycleReady,owner:root.lifecycleOwner,error:root.lifecycleError,warnings:root.lifecycleWarnings},activeShortcuts:root.activeShortcuts,
        windowIds:root.snapshot.windows.map(function(w) { return w.id }),settings: root.snapshot.settings,
        reset:{confirming:root.resetConfirmation,busy:root.resetBusy,serial:root.resetSerial},
        previewCompatibility:{status:root.previewCompatibilityStatus,error:root.previewCompatibilityError,requestedIds:root.previewCompatibilityIds,running:!!root.previewCompatibilityWorker && root.previewCompatibilityWorker.running},
        bridgeSupport:{status:root.bridgeSupportStatus,error:root.bridgeSupportError,busy:root.bridgeReloadBusy,stage:root.bridgeReloadStage,
          deferred:root.bridgeUpdateDeferred,checking:bridgeProbe.running},
        previewInteraction:{request:root.previewInteractionRequest,pendingRequest:root.previewInteractionPendingRequest,stopping:root.previewInteractionStopping,
          status:root.previewInteractionStatus,error:root.previewInteractionError,running:!!root.previewInteractionWorker && root.previewInteractionWorker.running},
        captureVisibility:{known:root.captureState.known,checkedAt:root.captureState.checkedAt,error:root.captureState.error,
          polling:root.capturePollNeeded,allowed:root.captureAllowed,
          screens:root.snapshot.monitors.map(function(m) { return {name:m.name,allowed:root.captureAllowedFor(m.name)} })},
        clickObserverActive:clickObserver.ready,clickObserverCount:clickObserver.clicks,pressedPointerButtons:Object.keys(root.pressedPointerButtons),
        pointer:{known:root.pointerKnown,tracking:root.pointerTracking,x:root.pointerPosition.x,y:root.pointerPosition.y},
        screens: root.snapshot.monitors.map(function(m) { return m.name }), dialog: root.contextOpen ? "menu" : root.dialogKind, context:{open:root.contextOpen,screen:root.contextScreen,workspace:root.contextWorkspace,ids:root.contextIds}, pendingCloseIds:Object.keys(root.pendingCloseIds), error: root.lastError,
        queueLength: root.queue.length, controllerBusy: worker.running,
        surfaces: root.surfaces.map(function(s) { return s.details() })})
    }
    function settings(): void { root.openDialog("settings", root.focusedScreen(), [], null) }
    function all(): void { root.allWindows(root.focusedScreen()) }
    function dismiss(): void { root.endPreviewInteraction("dismissed"); root.closeContext(); root.closeDialog(); root.surfaces.forEach(function(s) { s.dismissFloatingPreviews() }) }
    function refresh(): void { root.refresh() }
    function configure(key: string, value: string): void { root.setting(key, value) }
    function minimize(): void { root.enqueue(["minimize"]) }
    function restoreLast(): void { root.enqueue(["restore-last"]) }
    function restoreOldest(): void { root.enqueue(["restore-oldest"]) }
    function checkPreviewSupport(): void {root.checkBridgeSupport()}
    function reloadPreviewSupport(): void {root.reloadPreviewSupport()}
    function deferPreviewSupport(): void {root.deferBridgeUpdate()}
  }
  Component.onCompleted: refresh()
  Component.onDestruction: {root.stopping=true;root.endPreviewInteraction("service-stopped")}
}
