pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Widgets as Widgets
import Quickshell.Hyprland
import qs.Commons
import qs.Commons as Commons
import qs.Ui as Ui
import "Model.js" as Model
import "Motion.js" as Motion

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
  signal inputChanged()
  signal iconExited(string key,int frames)
  property bool active: false
  property bool expanded: false
  property bool grabReady: false
  readonly property bool requestedHorizontal: config.floatingDirection === "horizontal"
  property bool horizontal: false
  readonly property bool dockFrameVisible: config.dockFrame !== "hidden"
  readonly property bool snapEdges: config.floatingPlacement !== "free"
  readonly property var usableArea: Model.usableArea(width,height,monitor ? monitor.reserved : [])
  property var pendingPosition: null
  property bool motionReady: false
  property bool held: false
  property real anchorX: 0
  property real anchorY: 0
  property var displayWindows: []
  readonly property var displayGroups:iconModel.entries
  readonly property string animations:config.animations || "full"
  property var expansionDirection: null
  property int createdIcons: 0
  property int openingFrames: 0
  property int closingFrames: 0
  readonly property var popupColors: Commons.Color.popups
  readonly property var metrics: Style.spacing
  readonly property var panelBorder: Border.surfaceSpec("popups","border",popupColors.border,Style.normalBorderWidth)
  readonly property real gap: metrics.sm
  readonly property real inset: metrics.xxs + Math.max(Border.left(panelBorder), Border.right(panelBorder),
    Border.top(panelBorder), Border.bottom(panelBorder))
  readonly property real targetRadius:Model.dockRadius(config.dockCorners,config.dockCornerRadius,Style.cornerRadius,44+inset*2+6,44+inset*2+6)
  readonly property real endInset:Math.max(inset,Model.dockEndInset(targetRadius,inset,
    Math.max(Border.left(panelBorder),Border.right(panelBorder),Border.top(panelBorder),Border.bottom(panelBorder))))
  readonly property int stackDepth: Math.min(3, displayWindows.length)
  readonly property int tail: Math.max(0, stackDepth - 1) * 4
  property real stackTail: tail
  property real handleOpacity: active ? 1 : 0
  property real reveal: open ? 1 : 0
  readonly property bool open: active && expanded && windows.length > 1
  readonly property bool present: active || handleOpacity > 0 || reveal > 0
  readonly property bool animating: revealAnimation.running || handleAnimation.running || tailAnimation.running || extentAnimation.running || iconModel.busy || front.artworkAnimating
  readonly property var frontGroup: ({app:displayWindows.length ? displayWindows[0].app : "", windows:displayWindows,
    title:displayWindows.length === 1 ? displayWindows[0].title : displayWindows.length + " stashed windows · Click to expand"})
  readonly property var geometry: Model.floatingPanel(anchorX, anchorY, handle.height, width, height,
    displayGroups.length, inset, gap, 44, horizontal ? Math.ceil(footer.implicitWidth) : Math.ceil(footer.implicitHeight), expansionDirection, horizontal, endInset)
  property real panelExtent: horizontal ? geometry.width : geometry.height
  visible: present
  focus: open
  Keys.onEscapePressed: close()
  Keys.onDownPressed: navigate(1)
  Keys.onUpPressed: navigate(-1)
  Keys.onRightPressed:function(event) { if (horizontal) navigate(1); else event.accepted=false }
  Keys.onLeftPressed:function(event) { if (horizontal) navigate(-1); else event.accepted=false }
  Keys.onReturnPressed: if (open && list.currentIndex >= 0 && list.currentIndex < displayGroups.length)
    activate(displayGroups[list.currentIndex])
  Behavior on stackTail { NumberAnimation { id:tailAnimation; duration:Motion.duration(dock.animations,180,0); easing.type:Easing.OutCubic } }
  Behavior on handleOpacity { NumberAnimation { id:handleAnimation; duration:Motion.duration(dock.animations,180,100); easing.type:Easing.OutCubic } }
  Behavior on reveal { NumberAnimation { id:revealAnimation; duration:Motion.duration(dock.animations,dock.open ? 200 : 160,100); easing.type:Easing.OutCubic } }
  Behavior on panelExtent {
    enabled:dock.open && dock.reveal > 0.99
    NumberAnimation { id:extentAnimation; duration:Motion.move(dock.animations); easing.type:Easing.OutCubic }
  }
  Behavior on anchorX { enabled:Motion.full(dock.animations) && dock.motionReady && !dock.held
    NumberAnimation { id:snapXAnimation; duration:240; easing.type:Easing.OutCubic } }
  Behavior on anchorY { enabled:Motion.full(dock.animations) && dock.motionReady && !dock.held
    NumberAnimation { id:snapYAnimation; duration:240; easing.type:Easing.OutCubic } }
  StashCollection {
    id:iconModel
    sourceGroups:dock.active ? dock.groups : []
    animations:dock.open && dock.reveal>.99 ? dock.animations : "off"
    hold:!dock.open && dock.reveal>0
    onReconciled:dock.repairSelection()
  }
  function syncGroups() { if (iconModel) iconModel.reconcile() }
  function repairSelection() {
    if (!list || !iconModel) return
    if (!iconModel.count) { list.currentIndex=-1; return }
    var at=Math.max(0,Math.min(list.currentIndex,iconModel.count-1))
    if (!iconModel.get(at).retiring) { list.currentIndex=at; return }
    for (var i=at+1;i<iconModel.count;i++) if (!iconModel.get(i).retiring) { list.currentIndex=i; return }
    for (var j=at-1;j>=0;j--) if (!iconModel.get(j).retiring) { list.currentIndex=j; return }
    list.currentIndex=-1
  }
  function navigate(delta) {
    var next=list.currentIndex+delta
    while (next>=0 && next<iconModel.count) {
      if (!iconModel.get(next).retiring) { list.currentIndex=next; return }
      next+=delta
    }
  }
  onAnimationsChanged:if (!Motion.full(animations)) {
    snapXAnimation.complete(); snapYAnimation.complete(); tailAnimation.complete(); extentAnimation.complete()
    if (animations==="off") { revealAnimation.complete(); handleAnimation.complete() }
  }

  function place() {
    if (held) return
    var point = Model.floatingPosition(pendingPosition || savedPosition,width,height,usableArea,snapEdges,48+tail)
    if (Math.abs(anchorX-point[0])>0.01) anchorX=point[0]
    if (Math.abs(anchorY-point[1])>0.01) anchorY=point[1]
  }
  function close() { expanded = false }
  function preview(index) {
    var window = displayWindows[Math.min(displayWindows.length - 1, index + 1)]
    return {app:window ? window.app : "",title:"",windows:window ? [window] : []}
  }
  function activate(group) {
    if (!group || !groups.some(function(g) { return g.key===group.key })) return
    close()
    stash.selectGroup(group, screenName)
  }
  function context(group) {
    close()
    stash.openDialog("menu", screenName, group ? group.windows : windows, group)
  }
  function details() {
    var icons = [], exiting=[]
    for (var i = 0; i < list.count; i++) {
      var row = list.itemAtIndex(i) as StashDockRow
      var item = row ? row.icon : null
      if (item) {
        var point = item.mapToItem(dock, 0, 0);
        (item.retiring ? exiting : icons).push({key:item.group.key,x:point.x,y:point.y,width:item.width,height:item.height,appearance:item.appearance()})
      }
    }
    var footerPoint=footer.mapToItem(dock,0,0)
    return {active:active,expanded:open,orientation:horizontal ? "horizontal" : "vertical",animating:animating,progress:reveal,createdIcons:createdIcons,currentIndex:list.currentIndex,currentKey:list.currentIndex>=0 && list.currentIndex<iconModel.count ? iconModel.get(list.currentIndex).groupKey : "",
      animation:{openingFrames:openingFrames,closingFrames:closingFrames},grabActive:grab.active,snapping:snapXAnimation.running || snapYAnimation.running,windows:windows.length,groups:groups.length,
      handle:{held:held,x:handle.x,y:handle.y,width:handle.width,height:handle.height,opacity:handleOpacity,appearance:front.appearance()},
      panel:{x:panel.x,y:panel.y,width:panel.width,height:panel.height,radius:panel.radius,frameVisible:dockFrameVisible,background:String(panel.color),
        borderWidth:Math.max(panel.borderLeft,panel.borderRight,panel.borderTop,panel.borderBottom),targetHeight:geometry.height,targetWidth:geometry.width,inset:inset,endInset:endInset,visible:panel.visible,down:geometry.down,right:geometry.right},
      footer:{x:footerPoint.x,y:footerPoint.y,width:footer.width,height:footer.height,feedback:footer.feedbackDetails()},
      contentHeight:list.contentHeight,viewportHeight:list.height,contentY:list.contentY,
      contentWidth:list.contentWidth,viewportWidth:list.width,contentX:list.contentX,icons:icons,exitingIcons:exiting}
  }
  onAnchorXChanged: inputChanged()
  onAnchorYChanged: inputChanged()
  onStackTailChanged: inputChanged()
  onSavedPositionChanged: {
    if (pendingPosition && JSON.stringify(pendingPosition) === JSON.stringify(savedPosition)) pendingPosition=null
    place()
  }
  onSnapEdgesChanged: { close(); place() }
  onUsableAreaChanged: place()
  onTailChanged: place()
  onWidthChanged: place()
  onHeightChanged: place()
  onActiveChanged: {
    inputChanged()
    if (!active) close()
    if (open || reveal === 0) syncGroups()
  }
  onWindowsChanged: {
    if (windows.length) displayWindows=windows.slice()
    if (windows.length <= 1) close()
  }
  onGroupsChanged: if (open || reveal === 0) syncGroups()
  onRequestedHorizontalChanged: { close(); if (reveal === 0) horizontal=requestedHorizontal }
  onRevealChanged: {
    inputChanged()
    if (reveal > 0 && reveal < 1) {
      if (open) openingFrames++
      else closingFrames++
    }
    if (!open && reveal === 0) { expansionDirection=null; horizontal=requestedHorizontal; syncGroups() }
  }
  onOpenChanged: {
    grabReady=false
    if (open) {
      openingFrames=0
      syncGroups()
      expansionDirection=Model.floatingPanel(anchorX,anchorY,handle.height,width,height,
        displayGroups.length,inset,gap,44,horizontal ? Math.ceil(footer.implicitWidth) : Math.ceil(footer.implicitHeight),undefined,horizontal,endInset).forward
      grabDelay.restart()
      Qt.callLater(function() { if (dock.open) dock.forceActiveFocus() })
    } else closingFrames=0
  }
  Timer { id:grabDelay; interval:100; onTriggered:dock.grabReady=dock.open }
  Component.onCompleted: { horizontal=requestedHorizontal; place(); Qt.callLater(function() { dock.motionReady=true }); if (windows.length) displayWindows=windows.slice(); syncGroups() }

  readonly property var inputRegions: !active ? [] : open
    ? [frontRegion, middleRegion, backRegion, panelRegion] : [frontRegion, middleRegion, backRegion]
  StashIconRegion { id: frontRegion; originX: dock.anchorX; originY: dock.anchorY
    size:48; cornerRadius:front.hitRadius; iconShape:front.inputShape }
  StashIconRegion { id: middleRegion; originX: dock.anchorX; originY: dock.anchorY + Math.min(4,dock.stackTail)
    size:dock.stackTail > 0 ? 48 : 0; cornerRadius:front.hitRadius; iconShape:front.inputShape }
  StashIconRegion { id: backRegion; originX: dock.anchorX; originY: dock.anchorY + Math.min(8,dock.stackTail)
    size:dock.stackTail > 4 ? 48 : 0; cornerRadius:front.hitRadius; iconShape:front.inputShape }
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
    enabled:dock.active
    Repeater {
      model: dock.active || dock.handleOpacity > 0 ? 2 : 0
      delegate: StashIcon {
        required property int index
        readonly property int layerNumber:2-index
        y:Math.min(layerNumber*4,dock.stackTail)
        opacity:dock.stackDepth > layerNumber ? 1 : 0
        visible:opacity > 0
        Behavior on opacity { NumberAnimation { duration:Motion.duration(dock.animations,140,100); easing.type:Easing.OutCubic } }
        group:dock.preview(layerNumber-1)
        animations:dock.animations
        presence:dock.handleOpacity
        bubble:true; frameVisible:dock.config.iconFrame !== "hidden"; iconShape:front.iconShape; enabled:false
        hasCursor:drag.containsMouse || dock.open
        externalPressed:drag.pressed
      }
    }
    StashIcon {
      id: front
      group:dock.frontGroup
      animations:dock.animations
      presence:dock.handleOpacity
      frameVisible:dock.config.iconFrame !== "hidden"
      onFrameVisibleChanged:dock.inputChanged()
      bubble:true
      iconShape:dock.config.iconShape || "auto"
      hasCursor:drag.containsMouse || dock.open
      externalPressed:drag.pressed
      enabled:false
    }
    Ui.PanelToolTip { visible: drag.containsMouse && !drag.pressed && !dock.open; text:dock.frontGroup.title }
    MouseArea {
      id: drag
      anchors.fill: parent
      acceptedButtons: Qt.LeftButton | Qt.RightButton
      hoverEnabled:true
      preventStealing:true
      cursorShape:Qt.PointingHandCursor
      property point start
      property bool dragging:false
      onPressed: function(mouse) {
        start=Qt.point(mouse.x,mouse.y); dragging=false
        if (mouse.button === Qt.LeftButton) { dock.held=true; snapXAnimation.stop(); snapYAnimation.stop() }
      }
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
      function finishDrag() {
        dock.held=false
        var point=Model.floatingPosition([dock.anchorX,dock.anchorY],dock.width,dock.height,dock.usableArea,dock.snapEdges,48+dock.tail).map(Math.round)
        dock.pendingPosition=point
        dock.place()
        dock.stash.recordPosition(dock.monitor,"dock:floating",point[0],point[1])
      }
      onCanceled: finishDrag()
      onReleased: function(mouse) {
        if (dragging) { finishDrag(); return }
        dock.held=false
        dock.place()
        if (mouse.button === Qt.RightButton) dock.context(null)
        else if (dock.windows.length === 1) dock.activate(dock.groups[0])
        else dock.expanded=!dock.expanded
      }
    }
  }
  Ui.BorderSurface {
    id: panel
    visible:dock.reveal > 0
    enabled:dock.open
    clip:true
    opacity:Motion.full(dock.animations) ? Math.min(1,dock.reveal*2) : dock.reveal
    x:Math.round(dock.horizontal ? (dock.geometry.forward ? dock.anchorX+48+dock.gap : dock.anchorX-dock.gap-width) : dock.geometry.x)
    y:Math.round(dock.horizontal ? dock.geometry.y : (dock.geometry.forward ? dock.anchorY+handle.height+dock.gap : dock.anchorY-dock.gap-height))
    width:dock.horizontal ? Math.round(dock.panelExtent*(Motion.full(dock.animations) ? dock.reveal : 1)) : dock.geometry.width
    height:dock.horizontal ? dock.geometry.height : Math.round(dock.panelExtent*(Motion.full(dock.animations) ? dock.reveal : 1))
    radius:!dock.dockFrameVisible ? 0 : Model.dockRadius(dock.config.dockCorners,dock.config.dockCornerRadius,Style.cornerRadius,width,height)
    onRadiusChanged:dock.inputChanged()
    color:dock.dockFrameVisible ? dock.popupColors.background : "transparent"
    borderSpec:dock.dockFrameVisible ? dock.panelBorder : Border.none()
    Widgets.ClippingRectangle {
      anchors.fill:parent
      radius:panel.radius
      color:"transparent"
      contentInsideBorder:false
      border.color:"transparent"
      border.width:dock.dockFrameVisible ? Math.max(Border.left(dock.panelBorder),Border.right(dock.panelBorder),Border.top(dock.panelBorder),Border.bottom(dock.panelBorder)) : 0
      GridLayout {
        columns:dock.horizontal ? 2 : 1
        x:(dock.horizontal && !dock.geometry.forward ? panel.width-dock.panelExtent : 0)+(dock.horizontal ? dock.endInset : dock.inset)
        y:(!dock.horizontal && !dock.geometry.forward ? panel.height-dock.panelExtent : 0)+(dock.horizontal ? dock.inset : dock.endInset)
        width:Math.max(0,(dock.horizontal ? dock.panelExtent : panel.width)-(dock.horizontal ? dock.endInset : dock.inset)*2)
        height:Math.max(0,(dock.horizontal ? panel.height : dock.panelExtent)-(dock.horizontal ? dock.inset : dock.endInset)*2)
        rowSpacing:dock.gap
        columnSpacing:dock.gap
        ListView {
          id:list
          Layout.fillWidth:true
          Layout.fillHeight:true
          spacing:dock.gap
          clip:true
          boundsBehavior:Flickable.StopAtBounds
          orientation:dock.horizontal ? ListView.Horizontal : ListView.Vertical
          model:iconModel
          currentIndex:0
          delegate:StashDockRow {
            id:entry
            required property string groupKey
            required retiring
            animations:dock.animations
            required property int index
            readonly property var liveGroup:iconModel.dataByKey[groupKey] || null
            property var lastGroup:({key:groupKey,app:"",title:"",windows:[]})
            onLiveGroupChanged:if (liveGroup) lastGroup=liveGroup
            Component.onCompleted: { dock.createdIcons++; if (liveGroup) lastGroup=liveGroup }
            group:lastGroup
            onExited:function(frames) { dock.iconExited(groupKey,frames) }
            enabled:index >= 0 && dock.open && !retiring
            width:dock.horizontal ? 44 : list.width
            height:dock.horizontal ? list.height : 44
            frameVisible:dock.config.iconFrame !== "hidden"
            iconShape:dock.config.iconShape || "auto"
            hasCursor:ListView.isCurrentItem
            onHovered: function(isHovered) { if (isHovered) list.currentIndex=index }
            onActivated:dock.activate(group)
            onContextRequested:dock.context(group)
          }
          displaced:Transition { NumberAnimation { properties:"x,y"; duration:Motion.move(dock.animations); easing.type:Easing.OutCubic } }
          Controls.ScrollBar.vertical:Controls.ScrollBar {
            id:scrollbar
            policy:dock.horizontal ? Controls.ScrollBar.AlwaysOff : Controls.ScrollBar.AsNeeded
            padding:0
            contentItem:Rectangle {
              implicitWidth:dock.metrics.xxs
              radius:Style.cornerRadius
              color:Commons.Color.accent
              opacity:scrollbar.active ? 0.6 : 0
            }
            background:Item {}
          }
          Controls.ScrollBar.horizontal:Controls.ScrollBar {
            id:horizontalScrollbar
            policy:dock.horizontal ? Controls.ScrollBar.AsNeeded : Controls.ScrollBar.AlwaysOff
            padding:0
            contentItem:Rectangle {
              implicitHeight:dock.metrics.xxs
              radius:Style.cornerRadius
              color:Commons.Color.accent
              opacity:horizontalScrollbar.active ? 0.6 : 0
            }
            background:Item {}
          }
        }
        StashButton {
          animations:dock.animations
          id:footer
          Layout.fillWidth:!dock.horizontal
          Layout.alignment:Qt.AlignCenter
          Layout.preferredWidth:Math.ceil(implicitWidth)
          Layout.preferredHeight:Math.ceil(implicitHeight)
          iconText:"󰇙"
          focusable:true
          tooltipText:"Window Stash settings and all windows"
          foreground:dock.popupColors.text
          onClicked:dock.context(null)
        }
      }
    }
  }
}
