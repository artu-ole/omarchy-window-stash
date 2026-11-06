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
  property var snapshot: ({windows: [], monitors: [], settings: {presentation: "dock", scope: "global", grouping: "window", restoreDestination: "current", iconShape: "auto", floatingDirection: "vertical", floatingAnimation:"arc", dockSide: "bottom", floatingPlacement: "edges", dockCorners: "theme", dockCornerRadius: 12, iconFrame: "shown", dockFrame: "shown", animations: "full", dockOpacity:100, iconOpacity:100}, positions: {}})
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

  signal pointerClicked(real x,real y)
  StashClickObserver {
    id:clickObserver
    watching:root.surfaces.some(function(s) { return s.floatingDockOpen || s.contextMenuOpen })
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
  function openContext(group,name,point) {
    var m=screenMonitor(name)
    if (!m || !group) return
    contextScreen=name; contextWorkspace=m.activeWorkspace.id
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
    return Model.visibleWindows(snapshot.windows,workspace===undefined ? (m ? m.activeWorkspace.id : -1) : workspace,snapshot.settings.scope)
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
    enqueue(["close"].concat(ids,["--monitor",name,"--workspace",String(workspace===undefined ? m.activeWorkspace.id : workspace)]))
  }
  function closeGroup(group,name) { if (group) closeWindows(group.windows,name) }
  function closeContextWindows() {
    var windows=contextWindows(),name=contextScreen,workspace=contextWorkspace
    closeContext(); closeWindows(windows,name,workspace)
  }
  function closeContextAll() {
    var windows=scopeWindows(contextScreen,contextWorkspace),name=contextScreen,workspace=contextWorkspace
    closeContext(); closeWindows(windows,name,workspace)
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
    Qt.callLater(pump)
  }
  function openDialog(kind, name, windows, group) {
    closeContext()
    var m = screenMonitor(name)
    if (!m) return
    dialogScreen = name
    dialogWorkspace = m.activeWorkspace.id
    dialogWindows = windows || []
    dialogGroup = group || null
    dialogQuery = ""
    dialogDestination = ""
    dialogKind = kind
  }
  function closeDialog() { dialogKind = ""; dialogGroup = null; dialogQuery = "" }
  function restoreWindow(id, destination) {
    var m = screenMonitor(dialogScreen)
    if (!m) return
    var args = ["restore", id, "--monitor", m.name, "--workspace", String(dialogWorkspace)]
    var chosen = destination || dialogDestination
    if (chosen) args = args.concat(["--to", chosen])
    closeDialog()
    enqueue(args)
  }
  function selectGroup(group, name) {
    if (group.windows.length > 1) { openDialog("picker", name, group.windows, group); return }
    openDialog("restore", name, group.windows, group)
    restoreWindow(group.windows[0].id, "")
  }
  function setting(key, value) {
    if (!shell) { lastError = "Shell settings are not available"; return }
    var options = {presentation:["dock","bubbles","floating"], scope:["global","workspace"],
      restoreDestination:["current","original"], grouping:["window","app"],
      iconShape:["auto","circle","square","rounded","squircle"], floatingDirection:["vertical","horizontal"], floatingAnimation:["arc","glide","cascade","spring","swing"], dockSide:["bottom","top","left","right"], floatingPlacement:["edges","free"], dockCorners:["theme","custom"], iconFrame:["shown","hidden"], dockFrame:["shown","hidden"], animations:["full","reduced","off"]}
    var numericLimits={dockCornerRadius:64,dockOpacity:100,iconOpacity:100}
    if (numericLimits[key] !== undefined) {
      if (!/^(0|[1-9][0-9]{0,2})$/.test(String(value)) || Number(value) > numericLimits[key]) {
        lastError = key === "dockCornerRadius" ? "Dock corner radius must be 0–64 pixels" : "Opacity must be a whole percentage from 0 to 100"
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
          if (result.windows) root.snapshot = result
          if (result.ok === false) {
            root.lastError = result.error || "Window action failed"
            if (root.runningArgs[0]==="close") root.notifyCloseError(root.lastError)
          }
          else if (!result.windows) { root.lastError = ""; root.pendingRefresh = true }
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
      return JSON.stringify({loaded: true, windows: root.snapshot.windows.length, settings: root.snapshot.settings,
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
