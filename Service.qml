pragma ComponentBehavior: Bound
import QtQuick
import Quickshell
import Quickshell.Hyprland
import Quickshell.Io
import "ui"
import "ui/Model.js" as Model

Item {
  id: root
  property var shell: null
  readonly property string pluginId: "community.window-stash"
  readonly property string controller: Quickshell.env("HOME") + "/.local/bin/window-stash"
  property var snapshot: ({windows: [], monitors: [], settings: {presentation: "floating", scope: "global", grouping: "window", restoreDestination: "current", iconShape: "auto", sizePreset:"100", floatingDirection: "vertical", floatingAnimation:"arc", dragMotion:"physics", dockSide: "bottom", floatingPlacement: "edges", dockCorners: "theme", dockCornerRadius: 12, iconFrame: "hidden", dockFrame: "hidden", animations: "full", animationSpeed:"normal", dockOpacity:100, iconOpacity:100, hoverPreview:"off", previewSize:"medium", previewPlacement:"auto", previewTitles:"shown", previewDelay:400, previewHideDelay:200}, positions: {}})
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
  property bool contextOpen:false
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
  readonly property bool shortcutsBusy:(worker.running && runningArgs[0]==="shortcut") || queue.some(function(args) { return args[0]==="shortcut" })
  readonly property string shortcutStamp:JSON.stringify(shortcutKeys.map(function(key) { return snapshot.settings[key] }))
  property var deferredSettings:[]
  property string shortcutSyncError:""
  property bool resetConfirmation:false
  property bool resetting:false
  property int resetSerial:0
  readonly property bool resetBusy:resetting || (worker.running && runningArgs[0]==="reset-settings")
    || queue.some(function(args) { return args[0]==="reset-settings" })
  readonly property bool settingsBusy:resetBusy || shortcutsBusy
  onShortcutStampChanged:shortcutSyncDelay.restart()

  signal pointerClicked(real x,real y)
  signal shortcutConfigured(string key,string value)
  signal settingsReset()
  Timer { id:shortcutSyncDelay; interval:0; onTriggered:root.enqueue(["shortcuts-sync"]) }
  StashClickObserver {
    id:clickObserver
    watching:root.surfaces.some(function(s) { return s.floatingDockOpen || s.contextMenuOpen || s.previewOpen })
    onClicked:function(x,y) { root.pointerClicked(x,y) }
  }

  function refresh() { refreshDelay.restart() }
  function enqueue(args) {
    var next = queue.slice()
    next.push(args)
    queue = next
    pump()
  }
  function pump() {
    if (worker.running) return
    if (queue.length === 0) {
      if (pendingRefresh) { pendingRefresh = false; enqueue(["list"]) }
      return
    }
    var next = queue.slice()
    var args = next.shift()
    queue = next
    runningArgs=args; closeNotified=false
    worker.command = [controller].concat(args)
    worker.running = true
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
    if (runningArgs[0]==="shortcut") pendingRefresh=true
    if (runningArgs[0]==="reset-settings") {
      if (resetting && !lastError) lastError="Could not confirm the settings reset"
      resetting=false; pendingRefresh=true
    }
    Qt.callLater(pump)
  }
  function openDialog(kind, name, windows, group) {
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
    if (resetBusy || resetConfirmation) return
    shortcutSyncError=""
    if (shortcutKeys.indexOf(key)>=0) {
      lastError=""
      enqueue(["shortcut",key,String(value)])
      return
    }
    if (shortcutsBusy) {
      deferredSettings=deferredSettings.concat([[key,value]])
      return
    }
    var options = {presentation:["dock","bubbles","floating"], scope:["global","workspace"],
      restoreDestination:["current","original"], grouping:["window","app"],
      iconShape:["auto","circle","square","rounded","squircle"], sizePreset:["50","75","100","125","150","175","200","250","300"], floatingDirection:["vertical","horizontal"], floatingAnimation:["arc","glide","cascade","spring","swing","matryoshka","matryoshka-hop","jumping"], dragMotion:["physics","direct"], dockSide:["bottom","top","left","right"], floatingPlacement:["edges","free"], dockCorners:["theme","custom"], iconFrame:["shown","hidden"], dockFrame:["shown","hidden"], animations:["full","reduced","off"],animationSpeed:["slow","relaxed","normal","fast","ultrafast"]}
    options.hoverPreview=["off","still","live"]; options.previewSize=["small","medium","large"]
    options.previewPlacement=["auto","above","below","left","right"]; options.previewTitles=["shown","hidden"]
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
    refresh()
  }
  function applyDeferredSettings() {
    if (settingsBusy || resetConfirmation || !deferredSettings.length) return
    var edits=deferredSettings.slice(); deferredSettings=[]
    edits.forEach(function(edit) { root.setting(edit[0],edit[1]) })
  }
  function positionPending(key) {
    function targets(args) { return args[0]==="position" && args[2]===key }
    return (worker.running && targets(runningArgs)) || queue.some(targets)
  }
  function recordPosition(monitor, key, x, y) {
    enqueue(["position", Model.monitorKey(monitor), key, String(Math.round(x)), String(Math.round(y))])
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
            if (root.runningArgs[0]==="shortcut" && result.key!==undefined && result.binding!==undefined) {
              var next=Object.assign({},root.snapshot), settings=Object.assign({},root.snapshot.settings)
              settings[result.key]=result.binding; next.settings=settings; root.snapshot=next
              root.shortcutConfigured(result.key,result.binding)
            }
            if (root.runningArgs[0]==="reset-settings" && result.action==="settings-reset" && result.settings) {
              var resetSnapshot=Object.assign({},root.snapshot)
              resetSnapshot.settings=Object.assign({},result.settings)
              root.snapshot=resetSnapshot
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
      if (event.name==="configreloaded") shortcutSyncDelay.restart()
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
    function onScreensChanged() { root.closeContext(); root.closeDialog(); root.refresh() }
  }
  Variants {
    model: Quickshell.screens
    delegate: StashSurface { required property var modelData; screen: modelData; stash: root }
  }
  IpcHandler {
    target: "window-stash"
    function status(): string {
      return JSON.stringify({loaded: true, windows: root.snapshot.windows.length,
        windowIds:root.snapshot.windows.map(function(w) { return w.id }),settings: root.snapshot.settings,
        reset:{confirming:root.resetConfirmation,busy:root.resetBusy,serial:root.resetSerial},
        clickObserverActive:clickObserver.ready,clickObserverCount:clickObserver.clicks,
        screens: root.snapshot.monitors.map(function(m) { return m.name }), dialog: root.contextOpen ? "menu" : root.dialogKind, context:{open:root.contextOpen,screen:root.contextScreen,workspace:root.contextWorkspace,ids:root.contextIds}, pendingCloseIds:Object.keys(root.pendingCloseIds), error: root.lastError,
        queueLength: root.queue.length, controllerBusy: worker.running,
        surfaces: root.surfaces.map(function(s) { return s.details() })})
    }
    function settings(): void { root.openDialog("settings", root.focusedScreen(), [], null) }
    function all(): void { root.allWindows(root.focusedScreen()) }
    function dismiss(): void { root.closeContext(); root.closeDialog() }
    function refresh(): void { root.refresh() }
    function configure(key: string, value: string): void { root.setting(key, value) }
  }
  Component.onCompleted: refresh()
}
