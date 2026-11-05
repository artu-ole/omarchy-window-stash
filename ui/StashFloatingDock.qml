pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Hyprland
import qs.Commons
import qs.Commons as Commons
import qs.Ui as Ui
import "Model.js" as Model

Item {
  id: dock
  required property var stash
  required property var hostWindow
  required property var monitor
  required property string screenName
  required property var config
  required property var groups
  required property var windows
  property var savedPosition
  property bool active: false
  property bool expanded: false
  property bool grabReady: false
  property real anchorX: 0
  property real anchorY: 0
  property var displayWindows: []
  property var displayGroups: []
  property var expansionDirection: null
  property int createdIcons: 0
  property int openingFrames: 0
  property int closingFrames: 0
  readonly property var popupColors: Commons.Color.popups
  readonly property var metrics: Style.spacing
  readonly property var panelBorder: Border.surfaceSpec("popups","border",popupColors.border,Style.normalBorderWidth)
  readonly property real inset: metrics.controlGap + Math.max(Border.left(panelBorder), Border.right(panelBorder),
    Border.top(panelBorder), Border.bottom(panelBorder))
  readonly property int stackDepth: Math.min(3, displayWindows.length)
  readonly property int tail: Math.max(0, stackDepth - 1) * 4
  property real stackTail: tail
  property real handleOpacity: active ? 1 : 0
  property real reveal: open ? 1 : 0
  readonly property bool open: active && expanded && windows.length > 1
  readonly property bool present: active || handleOpacity > 0 || reveal > 0
  readonly property bool animating: revealAnimation.running || handleAnimation.running || tailAnimation.running || extentAnimation.running
  readonly property var frontGroup: ({app:displayWindows.length ? displayWindows[0].app : "", windows:displayWindows,
    title:displayWindows.length === 1 ? displayWindows[0].title : displayWindows.length + " stashed windows · Click to expand"})
  readonly property var geometry: Model.floatingPanel(anchorX, anchorY, handle.height, width, height,
    displayGroups.length, inset, metrics.controlGap, 44, footer.implicitHeight, expansionDirection)
  property real panelExtent: geometry.height
  visible: present
  focus: open
  Keys.onEscapePressed: close()
  Keys.onDownPressed: list.incrementCurrentIndex()
  Keys.onUpPressed: list.decrementCurrentIndex()
  Keys.onReturnPressed: if (open && list.currentIndex >= 0 && list.currentIndex < groups.length)
    activate(displayGroups[list.currentIndex])
  Behavior on stackTail { NumberAnimation { id:tailAnimation; duration:180; easing.type:Easing.OutCubic } }
  Behavior on handleOpacity { NumberAnimation { id:handleAnimation; duration:140; easing.type:Easing.OutCubic } }
  Behavior on reveal { NumberAnimation { id:revealAnimation; duration:dock.open ? 200 : 160; easing.type:Easing.OutCubic } }
  Behavior on panelExtent {
    enabled:dock.open && dock.reveal > 0.99
    NumberAnimation { id:extentAnimation; duration:180; easing.type:Easing.OutCubic }
  }
  ListModel { id:iconModel }

  // Keep delegate objects and scroll position through ordinary IPC refreshes.
  // During collapse, retain the old rows until the clipped reveal finishes.
  function syncGroups() {
    if (!iconModel) return
    var next = active ? groups.slice() : []
    displayGroups = next
    for (var i = 0; i < next.length; i++) {
      if (i < iconModel.count && iconModel.get(i).groupKey === next[i].key) continue
      var at = -1
      for (var j = i + 1; j < iconModel.count; j++) {
        if (iconModel.get(j).groupKey === next[i].key) { at = j; break }
      }
      if (at >= 0) iconModel.move(at, i, 1)
      else iconModel.insert(i, {groupKey:next[i].key})
    }
    if (iconModel.count > next.length) iconModel.remove(next.length, iconModel.count-next.length)
  }

  function place() {
    var point = Model.floatingAnchor(savedPosition, width, height)
    anchorX = point[0]; anchorY = point[1]
  }
  function close() { expanded = false }
  function preview(index) {
    var window = displayWindows[Math.min(displayWindows.length - 1, index + 1)]
    return {app:window ? window.app : "",title:"",windows:window ? [window] : []}
  }
  function activate(group) {
    close()
    stash.selectGroup(group, screenName)
  }
  function context(group) {
    close()
    stash.openDialog("menu", screenName, group ? group.windows : windows, group)
  }
  function details() {
    var icons = []
    for (var i = 0; i < list.count; i++) {
      var row = list.itemAtIndex(i) as StashDockRow
      var item = row ? row.icon : null
      if (item) {
        var point = item.mapToItem(dock, 0, 0)
        icons.push({key:item.group.key,x:point.x,y:point.y,width:item.width,height:item.height,appearance:item.appearance()})
      }
    }
    return {active:active,expanded:open,animating:animating,progress:reveal,createdIcons:createdIcons,
      animation:{openingFrames:openingFrames,closingFrames:closingFrames},grabActive:grab.active,windows:windows.length,groups:groups.length,
      handle:{x:handle.x,y:handle.y,width:handle.width,height:handle.height,opacity:handleOpacity,appearance:front.appearance()},
      panel:{x:panel.x,y:panel.y,width:panel.width,height:panel.height,targetHeight:geometry.height,inset:inset,visible:panel.visible,down:geometry.down},
      contentHeight:list.contentHeight,viewportHeight:list.height,contentY:list.contentY,icons:icons}
  }
  onSavedPositionChanged: place()
  onWidthChanged: place()
  onHeightChanged: place()
  onActiveChanged: {
    if (!active) close()
    if (open || reveal === 0) syncGroups()
  }
  onWindowsChanged: {
    if (windows.length) displayWindows=windows.slice()
    if (windows.length <= 1) close()
  }
  onGroupsChanged: if (open || reveal === 0) syncGroups()
  onRevealChanged: {
    if (reveal > 0 && reveal < 1) {
      if (open) openingFrames++
      else closingFrames++
    }
    if (!open && reveal === 0) { expansionDirection=null; syncGroups() }
  }
  onOpenChanged: {
    grabReady=false
    if (open) {
      openingFrames=0
      syncGroups()
      expansionDirection=Model.floatingPanel(anchorX,anchorY,handle.height,width,height,
        displayGroups.length,inset,metrics.controlGap,44,footer.implicitHeight).down
      grabDelay.restart()
      Qt.callLater(function() { if (dock.open) dock.forceActiveFocus() })
    } else closingFrames=0
  }
  Timer { id:grabDelay; interval:100; onTriggered:dock.grabReady=dock.open }
  Component.onCompleted: { place(); if (windows.length) displayWindows=windows.slice(); syncGroups() }

  readonly property Region inputRegion: Region {
    regions: !dock.active ? [] : dock.open ? [frontRegion, middleRegion, backRegion, panelRegion] : [frontRegion, middleRegion, backRegion]
  }
  StashIconRegion { id: frontRegion; originX: dock.anchorX; originY: dock.anchorY
    size:48; cornerRadius:front.hitRadius; iconShape:front.iconShape }
  StashIconRegion { id: middleRegion; originX: dock.anchorX; originY: dock.anchorY + Math.min(4,dock.stackTail)
    size:dock.stackTail > 0 ? 48 : 0; cornerRadius:front.hitRadius; iconShape:front.iconShape }
  StashIconRegion { id: backRegion; originX: dock.anchorX; originY: dock.anchorY + Math.min(8,dock.stackTail)
    size:dock.stackTail > 4 ? 48 : 0; cornerRadius:front.hitRadius; iconShape:front.iconShape }
  Region { id: panelRegion; item: panel; radius: panel.radius }
  HyprlandFocusGrab {
    id:grab
    windows: [dock.hostWindow]
    active: dock.open && dock.grabReady
    onCleared: dock.close()
  }

  Item {
    id: handle
    x: dock.anchorX; y: dock.anchorY
    width:48; height:48 + dock.stackTail
    opacity:dock.handleOpacity
    enabled:dock.active
    Repeater {
      model: dock.active || dock.handleOpacity > 0 ? 2 : 0
      delegate: StashIcon {
        required property int index
        readonly property int layerNumber:2-index
        y:Math.min(layerNumber*4,dock.stackTail)
        opacity:dock.stackDepth > layerNumber ? 1 : 0
        visible:opacity > 0
        Behavior on opacity { NumberAnimation { duration:140; easing.type:Easing.OutCubic } }
        group:dock.preview(layerNumber-1)
        bubble:true; iconShape:front.iconShape; enabled:false
      }
    }
    StashIcon {
      id: front
      group:dock.frontGroup
      bubble:true
      iconShape:dock.config.iconShape || "auto"
      hasCursor:drag.containsMouse || dock.open
      enabled:false
    }
    Ui.PanelToolTip { visible: drag.containsMouse && !drag.pressed && !dock.open; text:dock.frontGroup.title }
    MouseArea {
      id: drag
      anchors.fill: parent
      acceptedButtons: Qt.LeftButton | Qt.RightButton
      hoverEnabled:true
      cursorShape:Qt.PointingHandCursor
      property point start
      property bool dragging:false
      onPressed: function(mouse) { start=Qt.point(mouse.x,mouse.y); dragging=false }
      onPositionChanged: function(mouse) {
        if (!pressed || pressedButtons !== Qt.LeftButton) return
        var dx=mouse.x-start.x, dy=mouse.y-start.y
        if (dragging || Math.abs(dx)+Math.abs(dy)>6) {
          if (!dragging) dock.close()
          dragging=true
          var point=Model.floatingAnchor([dock.anchorX+dx,dock.anchorY+dy],dock.width,dock.height)
          dock.anchorX=point[0]; dock.anchorY=point[1]
        }
      }
      onReleased: function(mouse) {
        if (dragging) { dock.stash.recordPosition(dock.monitor,"dock:floating",dock.anchorX,dock.anchorY); return }
        if (mouse.button === Qt.RightButton) dock.context(null)
        else if (dock.windows.length === 1) dock.activate(dock.frontGroup)
        else dock.expanded=!dock.expanded
      }
    }
  }
  Ui.BorderSurface {
    id: panel
    visible:dock.reveal > 0
    enabled:dock.open
    clip:true
    opacity:Math.min(1,dock.reveal*2)
    x:Math.round(dock.geometry.x)
    y:Math.round(dock.geometry.down ? dock.anchorY+handle.height+dock.metrics.controlGap : dock.anchorY-dock.metrics.controlGap-height)
    width:dock.geometry.width; height:Math.round(dock.panelExtent*dock.reveal)
    radius:Style.cornerRadius
    color:dock.popupColors.background
    borderSpec:dock.panelBorder
    ColumnLayout {
      x:dock.inset
      y:dock.geometry.down ? dock.inset : panel.height-dock.panelExtent+dock.inset
      width:panel.width-dock.inset*2
      height:Math.max(0,dock.panelExtent-dock.inset*2)
      spacing:dock.metrics.controlGap
      ListView {
        id:list
        Layout.fillWidth:true
        Layout.fillHeight:true
        spacing:dock.metrics.controlGap
        clip:true
        boundsBehavior:Flickable.StopAtBounds
        model:iconModel
        currentIndex:0
        delegate:StashDockRow {
          id:entry
          required property string groupKey
          required property int index
          readonly property var liveGroup:dock.displayGroups.find(function(g) { return g.key === entry.groupKey })
          property var lastGroup:({key:groupKey,app:"",title:"",windows:[]})
          onLiveGroupChanged:if (liveGroup) lastGroup=liveGroup
          Component.onCompleted: { dock.createdIcons++; if (liveGroup) lastGroup=liveGroup }
          group:lastGroup
          enabled:index >= 0 && dock.open
          width:list.width
          iconShape:dock.config.iconShape || "auto"
          hasCursor:ListView.isCurrentItem
          onHovered: function(isHovered) { if (isHovered) list.currentIndex=index }
          onActivated:dock.activate(group)
          onContextRequested:dock.context(group)
        }
        add:Transition { NumberAnimation { property:"opacity"; from:0; to:1; duration:140; easing.type:Easing.OutCubic } }
        remove:Transition { NumberAnimation { property:"opacity"; to:0; duration:120; easing.type:Easing.OutCubic } }
        displaced:Transition { NumberAnimation { properties:"x,y"; duration:180; easing.type:Easing.OutCubic } }
        Controls.ScrollBar.vertical:Controls.ScrollBar {
          id:scrollbar
          contentItem:Rectangle {
            implicitWidth:dock.metrics.xxs
            radius:Style.cornerRadius
            color:Commons.Color.accent
            opacity:scrollbar.active ? 0.6 : 0
          }
          background:Item {}
        }
      }
      Ui.Button {
        id:footer
        Layout.fillWidth:true
        iconText:"󰇙"
        focusable:true
        tooltipText:"Window Stash settings and all windows"
        foreground:dock.popupColors.text
        onClicked:dock.context(null)
      }
    }
  }
}
