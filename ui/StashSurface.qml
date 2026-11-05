pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Wayland
import qs.Commons
import qs.Commons as Commons
import qs.Ui as Ui
import "Model.js" as Model

PanelWindow {
  id: surface
  readonly property var popupColors: Commons.Color.popups
  readonly property var fonts: Style.font
  readonly property var metrics: Style.spacing
  required property var stash
  readonly property var monitor: stash.screenMonitor(screen.name)
  readonly property var config: stash.snapshot.settings
  property var windows: []
  readonly property var groups: Model.groups(windows, config.grouping)
  property bool dialogOpen: false
  readonly property string dockSide: config.dockSide || "bottom"
  readonly property bool verticalDock: dockSide === "left" || dockSide === "right"
  readonly property var usableArea: Model.usableArea(width, height, monitor ? monitor.reserved : [])
  readonly property bool bubbleMode: config.presentation === "bubbles"
  readonly property bool floatingMode: config.presentation === "floating"
  readonly property bool keyboardOpen: dialogOpen || floatingDock.open
  readonly property string monitorKey: monitor ? Model.monitorKey(monitor) : screen.name
  readonly property var savedPositions: stash.snapshot.positions[monitorKey] || ({})
  property var bubbleRegions: []
  property bool focusPrimed: false
  // Explicitly invalidate the composed mask after animated geometry changes.
  // https://quickshell.org/docs/v0.3.0/types/Quickshell/Region/#sig.changed
  function refreshInputMask() { inputUpdate.restart() }
  Timer { id:inputUpdate; interval:0; onTriggered:inputMask.changed() }
  onWidthChanged: refreshInputMask()
  onHeightChanged: refreshInputMask()
  function itemRect(item) {
    var point = item.mapToItem(surface.contentItem, 0, 0)
    return {x:point.x, y:point.y, width:item.width, height:item.height}
  }
  // Model changes map/unmap layer surfaces. Apply them outside binding
  // evaluation so the compositor's synchronous geometry updates cannot
  // recursively re-evaluate the visibility model.
  Timer {
    id: modelDelay
    interval: 1
    onTriggered: {
      var nextWindows = Model.visibleWindows(surface.stash.snapshot.windows,
        surface.monitor ? surface.monitor.activeWorkspace.id : -1, surface.config.scope)
      // Reserve-only refreshes must preserve delegates, active drags and hover.
      if (JSON.stringify(nextWindows) !== JSON.stringify(surface.windows)) surface.windows = nextWindows
      surface.dialogOpen = surface.stash.dialogKind !== "" && surface.stash.dialogScreen === surface.screen.name
    }
  }
  Connections {
    target: surface.stash
    function onSnapshotChanged() { modelDelay.restart() }
    function onDialogKindChanged() { modelDelay.restart() }
    function onDialogScreenChanged() { modelDelay.restart() }
  }
  function details() {
    var points = []
    for (var i = 0; i < bubbles.count; i++) {
      var b = bubbles.itemAt(i) as StashIcon
      if (b) points.push({key:b.group.key, x:b.x, y:b.y, width:b.width, height:b.height,
        shape:b.iconShape, radius:b.hitRadius})
    }
    var controls = []
    for (var j = 0; j < settingRows.count; j++) {
      var row = settingRows.itemAt(j)
      // Repeater.itemAt() is typed as Item; its delegate adds these properties.
      // qmllint disable missing-property
      if (row) controls.push({key:row.modelData.key, value:row.selector.value,
        open:row.selector.popupOpen, rect:itemRect(row.selector)})
      // qmllint enable missing-property
    }
    return {screen:screen.name, width:width, height:height, eligible:windows.length,
      groups:groups.length, visible:visible, bubbles:points,
      usableArea:usableArea,
      shelf:{x:shelf.x,y:shelf.y,width:shelf.width,height:shelf.height,side:dockSide,
        contentWidth:dockViewport.contentWidth,viewportWidth:dockViewport.width,contentX:dockViewport.contentX,
        contentHeight:dockViewport.contentHeight,viewportHeight:dockViewport.height,contentY:dockViewport.contentY,
        icons:Array.from({length:dockIcons.count},function(_,i) { return itemRect(dockIcons.itemAt(i)) }),
        more:itemRect(dockMore)},
      dialog:{x:dialog.x,y:dialog.y,width:dialog.width,height:dialog.height,visible:dialog.visible},
      pickerCount:picker.count, picker:itemRect(picker),
      settingControls:controls,
      floatingDock:floatingDock.details(),
      actions:{here:itemRect(restoreHereButton),original:itemRect(restoreOriginalButton),settings:itemRect(settingsButton)},
      theme:{background:String(surface.popupColors.background),foreground:String(surface.popupColors.text),
        accent:String(Commons.Color.accent),fontFamily:surface.fonts.family,bodySize:surface.fonts.body,radius:Style.cornerRadius}}
  }
  onKeyboardOpenChanged: {
    focusPrimed = false
    if (keyboardOpen) primeFocus.restart()
  }
  onDialogOpenChanged: if (dialogOpen) floatingDock.close()
  Timer { id: primeFocus; interval: 70; onTriggered: surface.focusPrimed = true }
  color: "transparent"
  anchors { top: true; left: true; bottom: true; right: true }
  exclusionMode: ExclusionMode.Ignore
  WlrLayershell.namespace: "omarchy-window-stash"
  WlrLayershell.layer: WlrLayer.Top
  WlrLayershell.keyboardFocus: keyboardOpen
    ? (focusPrimed ? WlrKeyboardFocus.OnDemand : WlrKeyboardFocus.Exclusive) : WlrKeyboardFocus.None
  visible: groups.length > 0 || dialogOpen || (floatingMode && floatingDock.present)
  mask: Region {
    id: inputMask
    regions: surface.dialogOpen ? [dialogRegion] : surface.floatingMode ? floatingDock.inputRegions
      : surface.bubbleMode ? surface.bubbleRegions : [shelfRegion]
  }
  // Native dropdown popups may extend beyond the card. While a dialog is
  // open, its surface owns the screen, just like Omarchy's keyboard panels.
  Region { id: dialogRegion; width: surface.width; height: surface.height }
  Region { id: shelfRegion; item: shelf }

  Ui.BorderSurface {
    id: shelf
    visible: surface.config.presentation === "dock" && surface.groups.length > 0
    readonly property var geometry: Model.staticDockRect(surface.usableArea, surface.dockSide,
      dockRow.implicitWidth + surface.metrics.xxs * 2 + borderLeft + borderRight,
      dockRow.implicitHeight + surface.metrics.xxs * 2 + borderTop + borderBottom,
      Math.max(Style.gapsOut, surface.metrics.lg), surface.metrics.popupPadding)
    width: geometry.width
    height: geometry.height
    x: geometry.x
    y: geometry.y
    radius: Style.cornerRadius
    color: surface.popupColors.background
    borderSpec: Border.surfaceSpec("popups", "border", surface.popupColors.border, Style.normalBorderWidth)
    Flickable {
      id: dockViewport
      anchors.fill: parent
      anchors.leftMargin: surface.metrics.xxs + shelf.borderLeft
      anchors.rightMargin: surface.metrics.xxs + shelf.borderRight
      anchors.topMargin: surface.metrics.xxs + shelf.borderTop
      anchors.bottomMargin: surface.metrics.xxs + shelf.borderBottom
      contentWidth: surface.verticalDock ? width : dockRow.implicitWidth
      contentHeight: surface.verticalDock ? dockRow.implicitHeight : height
      clip: true
      flickableDirection: surface.verticalDock ? Flickable.VerticalFlick : Flickable.HorizontalFlick
      boundsBehavior: Flickable.StopAtBounds
      Connections {
        target: surface
        function onDockSideChanged() { dockViewport.cancelFlick(); dockViewport.contentX = 0; dockViewport.contentY = 0 }
      }
      Grid {
        id: dockRow
        columns: surface.verticalDock ? 1 : surface.groups.length + 1
        rowSpacing: surface.metrics.sm
        columnSpacing: surface.metrics.sm
        Repeater {
          id: dockIcons
          model: surface.groups
          delegate: StashIcon {
            required property var modelData
            group: modelData
            iconShape: surface.config.iconShape || "auto"
            onActivated: surface.stash.selectGroup(group, surface.screen.name)
            onContextRequested: surface.stash.openDialog("menu", surface.screen.name, group.windows, group)
          }
        }
        Ui.Button {
          id: dockMore
          iconText: "󰇙"; width: surface.verticalDock ? 44 : 32; height: surface.verticalDock ? 32 : 44
          focusable: true
          foreground: surface.popupColors.text
          tooltipText: "Window Stash settings and all windows"
          onClicked: surface.stash.openDialog("menu", surface.screen.name, [], null)
        }
      }
    }
  }
  Repeater {
    id: bubbles
    model: surface.bubbleMode ? surface.groups : []
    delegate: StashIcon {
      id: bubble
      required property var modelData
      required property int index
      group: modelData
      bubble: true
      iconShape: surface.config.iconShape || "auto"
      readonly property var saved: surface.savedPositions[group.key]
      property Region hitRegion: StashIconRegion {
        originX:bubble.x; originY:bubble.y; size:bubble.width
        cornerRadius:bubble.hitRadius; iconShape:bubble.iconShape
      }
      function place() {
        var position = Model.bubblePosition(saved, index, surface.width, surface.height, surface.groups.length)
        x = position[0]; y = position[1]
      }
      onSavedChanged: place()
      onActivated: surface.stash.selectGroup(group, surface.screen.name)
      onContextRequested: surface.stash.openDialog("menu", surface.screen.name, group.windows, group)
      onMoved: function(dx, dy) { x = Math.max(0, Math.min(surface.width - width, x + dx)); y = Math.max(24, Math.min(surface.height - height, y + dy)) }
      onDragFinished: surface.stash.recordPosition(surface.monitor, group.key, x, y)
      Component.onCompleted: {
        place()
        var next = surface.bubbleRegions.slice(); next.push(hitRegion); surface.bubbleRegions = next
      }
      Component.onDestruction: surface.bubbleRegions = surface.bubbleRegions.filter(function(r) { return r !== hitRegion })
      Connections {
        target: surface
        function onWidthChanged() { bubble.place() }
        function onHeightChanged() { bubble.place() }
        function onGroupsChanged() { bubble.place() }
      }
    }
  }

  StashFloatingDock {
    id:floatingDock
    onInputChanged: surface.refreshInputMask()
    anchors.fill:parent
    stash:surface.stash
    hostWindow:surface
    monitor:surface.monitor
    screenName:surface.screen.name
    config:surface.config
    groups:surface.groups
    windows:surface.windows
    savedPosition:surface.savedPositions["dock:floating"]
    active:surface.floatingMode && surface.groups.length > 0 && !surface.dialogOpen
  }

  MouseArea {
    anchors.fill: parent
    visible: surface.dialogOpen
    onClicked: surface.stash.closeDialog()
  }
  Ui.BorderSurface {
    id: dialog
    visible: surface.dialogOpen
    x: (surface.width - width) / 2
    y: Math.max(surface.metrics.popupPadding, (surface.height - height) / 2)
    width: Math.min(Style.space(560), surface.width - surface.metrics.popupPadding * 2)
    height: Math.min(surface.height - surface.metrics.popupPadding * 2,
      contents.implicitHeight + surface.metrics.popupPadding * 2 + borderTop + borderBottom)
    radius: Style.cornerRadius
    color: surface.popupColors.background
    borderSpec: Border.surfaceSpec("popups", "border", surface.popupColors.border, Style.normalBorderWidth)
    focus: visible
    onVisibleChanged: if (visible) Qt.callLater(function() {
      if (search.visible) search.forceActiveFocus()
      else dialog.forceActiveFocus()
    })
    Keys.onEscapePressed: surface.stash.closeDialog()
    MouseArea { anchors.fill: parent } // Keep clicks on card padding inside the dialog.
    ColumnLayout {
      id: contents
      anchors.fill: parent
      anchors.leftMargin: surface.metrics.popupPadding + dialog.borderLeft
      anchors.rightMargin: surface.metrics.popupPadding + dialog.borderRight
      anchors.topMargin: surface.metrics.popupPadding + dialog.borderTop
      anchors.bottomMargin: surface.metrics.popupPadding + dialog.borderBottom
      spacing: surface.metrics.rowGap
      RowLayout {
        Layout.fillWidth: true
        Text {
          text: surface.stash.dialogKind === "settings" ? "Window Stash settings" : surface.stash.dialogKind === "picker" ? "Stashed windows" : "Window Stash"
          textFormat: Text.PlainText
          color: surface.popupColors.text
          font.family: surface.fonts.family
          font.pixelSize: surface.fonts.title
          font.bold: true
          Layout.fillWidth: true
        }
        Ui.PanelActionButton {
          iconText: "󰅖"
          tooltipText: "Close"
          focusable: true
          foreground: surface.popupColors.text
          onClicked: surface.stash.closeDialog()
        }
      }
      Ui.PanelSeparator { Layout.fillWidth: true; foreground: surface.popupColors.text }
      Text {
        visible: surface.stash.lastError !== ""
        text: surface.stash.lastError
        textFormat: Text.PlainText
        color: Commons.Color.urgent
        font.family: surface.fonts.family
        font.pixelSize: surface.fonts.body
        wrapMode: Text.Wrap; Layout.fillWidth: true
      }
      Ui.TextField {
        id: search
        visible: surface.stash.dialogKind === "picker"
        Layout.fillWidth: true
        foreground: surface.popupColors.text
        placeholderText: "Find by title or app…"
        text: surface.stash.dialogQuery
        onTextEdited: surface.stash.dialogQuery = text
        Keys.onDownPressed: picker.incrementCurrentIndex()
        Keys.onUpPressed: picker.decrementCurrentIndex()
        onAccepted: if (picker.currentIndex >= 0 && picker.currentIndex < picker.count)
          surface.stash.restoreWindow(picker.model[picker.currentIndex].id, "")
      }
      ListView {
        id: picker
        visible: surface.stash.dialogKind === "picker"
        Layout.fillWidth: true
        Layout.preferredHeight: Math.min(Style.space(360), contentHeight)
        clip: true; spacing: surface.metrics.labelGap; currentIndex: 0
        model: surface.stash.dialogWindows.filter(function(w) {
          return (w.title + " " + w.app).toLowerCase().indexOf(surface.stash.dialogQuery.toLowerCase()) >= 0
            && surface.stash.snapshot.windows.some(function(live) { return live.id === w.id })
        })
        delegate: StashWindowRow {
          required property var modelData
          required property int index
          width: picker.width
          height: implicitHeight
          windowData: modelData
          hasCursor: ListView.isCurrentItem
          onPointed: picker.currentIndex = index
          onActivated: surface.stash.restoreWindow(modelData.id, "")
          onContextRequested: surface.stash.openDialog("menu", surface.screen.name, [modelData], {windows:[modelData]})
        }
        Controls.ScrollBar.vertical: Controls.ScrollBar {
          id: pickerScrollbar
          contentItem: Rectangle {
            implicitWidth: surface.metrics.sm
            radius: Style.cornerRadius
            color: Style.hoverStateColor(surface.popupColors.text, Commons.Color.accent)
            opacity: pickerScrollbar.active ? 0.6 : 0
          }
          background: Item {}
        }
      }
      Text {
        visible: picker.visible && picker.count === 0
        text: "No stashed windows"
        color: Qt.darker(surface.popupColors.text, 1.4)
        font.family: surface.fonts.family
        font.pixelSize: surface.fonts.body
      }
      ColumnLayout {
        visible: surface.stash.dialogKind === "menu"
        Layout.fillWidth: true
        Ui.Button { id: restoreHereButton; text: "Restore here"; visible: surface.stash.dialogWindows.length > 0; Layout.fillWidth: true
          leftAlign: true; focusable: true; foreground: surface.popupColors.text
          onClicked: {
            if (surface.stash.dialogWindows.length === 1) surface.stash.restoreWindow(surface.stash.dialogWindows[0].id, "current")
            else {
              surface.stash.openDialog("picker", surface.screen.name, surface.stash.dialogWindows, surface.stash.dialogGroup)
              surface.stash.dialogDestination = "current"
            }
          }
        }
        Ui.Button { id: restoreOriginalButton; text: "Restore to original workspace"; visible: surface.stash.dialogWindows.length > 0; Layout.fillWidth: true
          leftAlign: true; focusable: true; foreground: surface.popupColors.text
          onClicked: {
            if (surface.stash.dialogWindows.length === 1) surface.stash.restoreWindow(surface.stash.dialogWindows[0].id, "original")
            else {
              surface.stash.openDialog("picker", surface.screen.name, surface.stash.dialogWindows, surface.stash.dialogGroup)
              surface.stash.dialogDestination = "original"
            }
          }
        }
        Ui.Button { text: "All stashed windows"; Layout.fillWidth: true; leftAlign: true; focusable: true; foreground: surface.popupColors.text
          onClicked: surface.stash.allWindows(surface.screen.name) }
        Ui.Button { id: settingsButton; text: "Settings"; Layout.fillWidth: true; leftAlign: true; focusable: true; foreground: surface.popupColors.text
          onClicked: surface.stash.openDialog("settings", surface.screen.name, [], null) }
      }
      ColumnLayout {
        visible: surface.stash.dialogKind === "settings"
        Layout.fillWidth: true; spacing: surface.metrics.panelGap
        Repeater {
          id: settingRows
          model: [
            {key:"presentation", label:"Appearance", values:["dock","bubbles","floating"],
              labels:["Static dock","Floating bubbles","Floating dock"]},
            {key:"dockSide", label:"Dock side", values:["bottom","top","left","right"], labels:["Bottom","Top","Left","Right"]},
            {key:"floatingDirection", label:"Floating dock direction", values:["vertical","horizontal"], labels:["Vertical","Horizontal"]},
            {key:"scope", label:"Stash visibility", values:["global","workspace"], labels:["Global","Current workspace"]},
            {key:"restoreDestination", label:"Restore destination", values:["current","original"], labels:["Current workspace","Original workspace"]},
            {key:"grouping", label:"Icon grouping", values:["window","app"], labels:["One per window","One per app"]},
            {key:"iconShape", label:"Icon shape", values:["auto","circle","square","rounded","squircle"],
              labels:["Automatic","Circle","Square","Rounded square","Squircle"]}
          ]
          delegate: RowLayout {
            id: settingRow
            required property var modelData
            readonly property alias selector: settingDropdown
            visible:(modelData.key !== "floatingDirection" || surface.floatingMode)
              && (modelData.key !== "dockSide" || surface.config.presentation === "dock")
            Layout.fillWidth: true
            Text {
              text: settingRow.modelData.label
              color: surface.popupColors.text
              font.family: surface.fonts.family
              font.pixelSize: surface.fonts.body
              Layout.fillWidth: true
            }
            Ui.Dropdown {
              id: settingDropdown
              Layout.preferredWidth: surface.metrics.dropdownWidth
              showLabel: false
              options: settingRow.modelData.values.map(function(value, i) {
                return {value:value, label:settingRow.modelData.labels[i]}
              })
              Component.onCompleted: value = surface.config[settingRow.modelData.key]
              Connections {
                target: surface
                function onConfigChanged() { settingDropdown.value = surface.config[settingRow.modelData.key] }
              }
              onChanged: function(value) { surface.stash.setting(settingRow.modelData.key, value) }
            }
          }
        }
        Ui.PanelSeparator { Layout.fillWidth: true; foreground: surface.popupColors.text }
        Text {
          text: "Super+A: minimize focused window\nSuper+Z: restore most recently minimized"
          color: Qt.darker(surface.popupColors.text, 1.4)
          font.family: surface.fonts.family
          font.pixelSize: surface.fonts.caption
        }
        Ui.Button { text: "All stashed windows"; focusable: true; foreground: surface.popupColors.text
          onClicked: surface.stash.allWindows(surface.screen.name) }
      }
    }
  }
  Component.onCompleted: {
    var next = stash.surfaces.slice(); next.push(surface); stash.surfaces = next
    modelDelay.restart()
  }
  Component.onDestruction: if (stash) stash.surfaces = stash.surfaces.filter(function(s) { return s !== surface })
}
