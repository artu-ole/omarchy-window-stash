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
  property var snapshot: ({windows: [], monitors: [], settings: {presentation: "dock", scope: "global", grouping: "window", restoreDestination: "current", iconShape: "auto", floatingDirection: "vertical", dockSide: "bottom"}, positions: {}})
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
    worker.command = [controller].concat(args)
    worker.running = true
  }
  function screenMonitor(name) {
    for (var i = 0; i < snapshot.monitors.length; i++)
      if (snapshot.monitors[i].name === name) return snapshot.monitors[i]
    return null
  }
  function openDialog(kind, name, windows, group) {
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
      iconShape:["auto","circle","square","rounded","squircle"], floatingDirection:["vertical","horizontal"], dockSide:["bottom","top","left","right"]}
    if (!options[key] || options[key].indexOf(value) < 0) { lastError = "Invalid stash setting"; return }
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
  // Layer-shell reserve changes (including third-party bars appearing) do not
  // emit a workspace event. Refresh only while a static dock is displayed.
  Timer {
    interval: 1500
    repeat: true
    running: root.snapshot.settings.presentation === "dock" && root.surfaces.some(function(s) { return s.windows.length > 0 })
    onTriggered: root.refresh()
  }
  Process {
    id: worker
    stdout: StdioCollector {
      onStreamFinished: {
        try {
          var result = JSON.parse(text)
          if (result.windows) root.snapshot = result
          if (result.ok === false) root.lastError = result.error || "Window action failed"
          else if (!result.windows) { root.lastError = ""; root.pendingRefresh = true }
        } catch (error) { root.lastError = "Could not read controller response: " + String(error) }
      }
    }
    onExited: function(exitCode) { Qt.callLater(root.pump) }
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
      if (event.name === "changeworkspaceid") {
        var parts = String(event.data || "").split(",")
        if (parts.length >= 2) root.enqueue(["rebase", parts[0], parts[1]])
      }
      if (/window|workspace|monitor|fullscreen|configreloaded/.test(String(event.name))) root.refresh()
    }
  }
  Connections {
    target: Quickshell
    function onScreensChanged() { root.closeDialog(); root.refresh() }
  }
  Variants {
    model: Quickshell.screens
    delegate: StashSurface { required property var modelData; screen: modelData; stash: root }
  }
  IpcHandler {
    target: "window-stash"
    function status(): string {
      return JSON.stringify({loaded: true, windows: root.snapshot.windows.length, settings: root.snapshot.settings,
        screens: root.snapshot.monitors.map(function(m) { return m.name }), dialog: root.dialogKind, error: root.lastError,
        queueLength: root.queue.length, controllerBusy: worker.running,
        surfaces: root.surfaces.map(function(s) { return s.details() })})
    }
    function settings(): void { root.openDialog("settings", root.focusedScreen(), [], null) }
    function all(): void { root.allWindows(root.focusedScreen()) }
    function dismiss(): void { root.closeDialog() }
    function refresh(): void { root.refresh() }
    function configure(key: string, value: string): void { root.setting(key, value) }
  }
  Component.onCompleted: refresh()
}
