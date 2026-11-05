pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Widgets as Widgets
import Quickshell.Wayland
import qs.Commons
import qs.Commons as Commons
import qs.Ui as Ui
import "Model.js" as Model
import "Motion.js" as Motion

PanelWindow {
  id: surface
  readonly property var popupColors: Commons.Color.popups
  readonly property var fonts: Style.font
  readonly property var metrics: Style.spacing
  required property var stash
  readonly property var monitor: stash.screenMonitor(screen.name)
  readonly property int activeWorkspaceId:monitor ? monitor.activeWorkspace.id : -1
  onActiveWorkspaceIdChanged:if (floatingDock) floatingDock.close()
  readonly property var config: stash.snapshot.settings
  readonly property string animations: config.animations || "full"
  readonly property real iconIdleOpacity:(config.iconOpacity === undefined ? 100 : config.iconOpacity)/100
  readonly property real canvasWidth:screen ? screen.width : width
  readonly property real canvasHeight:screen ? screen.height : height
  property var windows: []
  readonly property string groupingMode: config.grouping || "window"
  readonly property var groups: Model.groups(windows, groupingMode)
  property bool dialogOpen: false
  property string renderDialogKind:""
  property var renderDialogWindows:[]
  property string renderDialogQuery:""
  property int dialogFrames:0
  property int createdShelfIcons:0
  property int exitSerial:0
  property var completedExits:[]
  function recordExit(view,key,frames) {
    exitSerial++
    completedExits=completedExits.concat([{serial:exitSerial,view:view,key:key,frames:frames}]).slice(-16)
  }
  property real dialogReveal:dialogOpen ? 1 : 0
  Behavior on dialogReveal { NumberAnimation { id:dialogAnimation; duration:Motion.duration(surface.animations,surface.dialogOpen ? 180 : 140,100); easing.type:Easing.OutCubic } }
  onDialogRevealChanged: {
    if (dialogReveal>0 && dialogReveal<1) dialogFrames++
    if (dialogReveal===0 && !dialogOpen) renderDialogKind=""
  }
  readonly property string dockSide: config.dockSide || "bottom"
  readonly property bool dockFrameVisible: config.dockFrame !== "hidden"
  readonly property bool verticalDock: dockSide === "left" || dockSide === "right"
  readonly property var usableArea: Model.usableArea(canvasWidth, canvasHeight, monitor ? monitor.reserved : [])
  readonly property bool bubbleMode: config.presentation === "bubbles"
  readonly property bool floatingMode: config.presentation === "floating"
  readonly property bool keyboardOpen: dialogOpen || floatingDock.open
  readonly property string monitorKey: monitor ? Model.monitorKey(monitor) : screen.name
  readonly property var savedPositions: stash.snapshot.positions[monitorKey] || ({})
  readonly property bool snapFloating: config.floatingPlacement !== "free"
  property var bubbleDrafts: ({})
  readonly property var bubbleTargets: Model.bubbleLayout(bubblesModel.activeKeys,
    savedPositions, bubbleDrafts, canvasWidth, canvasHeight, usableArea, snapFloating)
  StashCollection { id:shelfModel; sourceGroups:surface.config.presentation==="dock" ? surface.groups : []; animations:surface.animations }
  StashCollection { id:bubblesModel; sourceGroups:surface.bubbleMode ? surface.groups : []; animations:surface.animations }
  onSavedPositionsChanged: {
    var next=Object.assign({},bubbleDrafts)
    Object.keys(next).forEach(function(key) {
      if (JSON.stringify(next[key]) === JSON.stringify(savedPositions[key])) delete next[key]
    })
    if (JSON.stringify(next) !== JSON.stringify(bubbleDrafts)) bubbleDrafts=next
  }
  function finishBubbleMove(key, x, y) {
    var at=bubblesModel.activeKeys.indexOf(key)
    if (at<0 || !bubbleTargets[at]) return
    var next=Object.assign({},bubbleDrafts)
    next[key]=[x,y]; bubbleDrafts=next
    var point=bubbleTargets[at].map(Math.round)
    next=Object.assign({},bubbleDrafts); next[key]=point; bubbleDrafts=next
    stash.recordPosition(monitor,key,point[0],point[1])
  }
  property bool bubbleHeld: false
  property int createdBubbles: 0
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
      if (surface.dialogOpen) {
        surface.renderDialogKind=surface.stash.dialogKind
        surface.renderDialogWindows=surface.stash.dialogWindows.slice()
        surface.renderDialogQuery=surface.stash.dialogQuery
      }
    }
  }
  Connections {
    target: surface.stash
    function onSnapshotChanged() { modelDelay.restart() }
    function onDialogKindChanged() { modelDelay.restart() }
    function onDialogScreenChanged() { modelDelay.restart() }
    function onDialogWindowsChanged() { modelDelay.restart() }
    function onDialogQueryChanged() { modelDelay.restart() }
  }
  function details() {
    var points = [], exiting=[]
    for (var i = 0; i < bubbles.count; i++) {
      var b = bubbles.itemAt(i) as StashIcon
      if (b) (b.retiring ? exiting : points).push({key:b.group.key, x:b.x, y:b.y, width:b.width, height:b.height,
        shape:b.iconShape, radius:b.hitRadius,animating:b.positionAnimating,held:b.positionHeld,appearance:b.appearance()})
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
    var opacityControls=[]
    for (var k=0;k<opacityRows.count;k++) {
      var opacityRow=opacityRows.itemAt(k)
      // qmllint disable missing-property
      if (opacityRow) opacityControls.push({key:opacityRow.modelData.key,value:opacityRow.numberField.value,visible:opacityRow.visible,rect:itemRect(opacityRow.numberField.field)})
      // qmllint enable missing-property
    }
    return {screen:screen.name, width:width, height:height, eligible:windows.length,
      groups:groups.length, visible:visible, bubbles:points,exitingBubbles:exiting,createdBubbles:createdBubbles,
      motion:{mode:animations,exitSerial:exitSerial,completedExits:completedExits,createdShelfIcons:createdShelfIcons,dialogFrames:dialogFrames,shelfBusy:shelfModel.busy,bubbleBusy:bubblesModel.busy,dialogProgress:dialogReveal},
      usableArea:usableArea,
      shelf:{x:shelf.x,y:shelf.y,width:shelf.width,height:shelf.height,side:dockSide,radius:shelf.radius,frameVisible:dockFrameVisible,background:String(shelf.color),
        borderWidth:Math.max(shelf.borderLeft,shelf.borderRight,shelf.borderTop,shelf.borderBottom),
        insets:{left:shelf.insetLeft,right:shelf.insetRight,top:shelf.insetTop,bottom:shelf.insetBottom},feedback:shelfFeedback.details(),
        contentWidth:dockViewport.contentWidth,viewportWidth:dockViewport.width,contentX:dockViewport.contentX,
        contentHeight:dockViewport.contentHeight,viewportHeight:dockViewport.height,contentY:dockViewport.contentY,
        icons:shelfIcons(false),exitingIcons:shelfIcons(true),progress:shelf.reveal,
        animating:shelfWidthAnimation.running || shelfHeightAnimation.running || shelfRevealAnimation.running},
      dialog:{x:dialog.x,y:dialog.y,width:dialog.width,height:dialog.height,visible:dialogOpen && dialogReveal>0.999,rendered:dialog.visible,progress:dialogReveal},
      pickerCount:picker.count, picker:itemRect(picker),
      settingControls:controls,
      opacityControls:opacityControls,
      cornerControl:{visible:radiusRow.visible,value:radiusField.value,rect:itemRect(radiusField.field)},
      floatingDock:floatingDock.details(),
      actions:{here:itemRect(restoreHereButton),original:itemRect(restoreOriginalButton),settings:Object.assign(itemRect(settingsButton),{feedback:settingsButton.feedbackDetails()})},
      theme:{background:String(surface.popupColors.background),foreground:String(surface.popupColors.text),
        accent:String(Commons.Color.accent),fontFamily:surface.fonts.family,bodySize:surface.fonts.body,radius:Style.cornerRadius}}
  }
  function shelfIcons(retiring) {
    var result=[]
    for (var i=0;i<dockIcons.count;i++) {
      var icon=dockIcons.itemAt(i) as StashIcon
      if (icon && icon.retiring===retiring) result.push(Object.assign(itemRect(icon),{key:icon.group.key,appearance:icon.appearance()}))
    }
    return result
  }
  onAnimationsChanged:if (!Motion.full(animations)) {
    shelfWidthAnimation.complete(); shelfHeightAnimation.complete()
    if (animations==="off") { dialogAnimation.complete(); shelfRevealAnimation.complete() }
  }
  onKeyboardOpenChanged: {
    focusPrimed = false
    if (keyboardOpen) primeFocus.restart()
  }
  onDialogOpenChanged: {
    dialogFrames=0
    if (dialogOpen) floatingDock.close()
    else for (var i=0;i<settingRows.count;i++) {
      var row=settingRows.itemAt(i)
      // qmllint disable missing-property
      if (row) row.selector.close()
      // qmllint enable missing-property
    }
  }
  Timer { id: primeFocus; interval: 70; onTriggered: surface.focusPrimed = true }
  color: "transparent"
  anchors { top: true; left: true; bottom: true; right: true }
  exclusionMode: ExclusionMode.Ignore
  WlrLayershell.namespace: "omarchy-window-stash"
  WlrLayershell.layer: WlrLayer.Top
  WlrLayershell.keyboardFocus: keyboardOpen
    ? (focusPrimed ? WlrKeyboardFocus.OnDemand : WlrKeyboardFocus.Exclusive) : WlrKeyboardFocus.None
  visible: shelfModel.count>0 || shelf.reveal>0 || bubblesModel.count>0 || dialogReveal>0 || dialogOpen || floatingDock.present
  mask: Region {
    id: inputMask
    // Keep motion on this surface during a drag, including the gaps between
    // small animated regions. Restore click-through immediately on release.
    regions: surface.dialogOpen || surface.bubbleHeld || floatingDock.held ? [dialogRegion] : surface.floatingMode ? floatingDock.inputRegions
      : surface.bubbleMode ? surface.bubbleRegions : surface.config.presentation==="dock" && surface.groups.length>0 ? [shelfRegion] : []
  }
  // Native dropdown popups may extend beyond the card. While a dialog is
  // open, its surface owns the screen, just like Omarchy's keyboard panels.
  Region { id: dialogRegion; width: surface.width; height: surface.height }
  Region { id: shelfRegion; item: shelf; radius:shelf.radius }

  StashDockSurface {
    id: shelf
    frameOpacity:shelfFeedback.opacityProgress
    HoverHandler { id:shelfHover }
    StashFeedback {
      id:shelfFeedback
      animations:surface.animations
      idleOpacity:(surface.config.dockOpacity === undefined ? 100 : surface.config.dockOpacity)/100
      hot:shelf.enabled && shelfHover.hovered
    }
    readonly property var frameSpec: Border.surfaceSpec("popups", "border", surface.popupColors.border, Style.normalBorderWidth)
    readonly property real frameLeft: Border.left(frameSpec)
    readonly property real frameRight: Border.right(frameSpec)
    readonly property real frameTop: Border.top(frameSpec)
    readonly property real frameBottom: Border.bottom(frameSpec)
    readonly property real crossInset:surface.metrics.xxs + (surface.verticalDock ? Math.min(frameLeft,frameRight) : Math.min(frameTop,frameBottom))
    readonly property real thickness:44 + surface.metrics.xxs*2 + (surface.verticalDock ? frameLeft+frameRight : frameTop+frameBottom)
    readonly property real targetRadius:Model.dockRadius(surface.config.dockCorners,surface.config.dockCornerRadius,Style.cornerRadius,thickness,thickness)
    readonly property real endInset:Model.dockEndInset(targetRadius,crossInset,Math.max(frameLeft,frameRight,frameTop,frameBottom))
    // Retain these insets when the frame is hidden so toggling it keeps positions.
    readonly property real insetLeft:Math.max(surface.metrics.xxs+frameLeft,surface.verticalDock ? 0 : endInset)
    readonly property real insetRight:Math.max(surface.metrics.xxs+frameRight,surface.verticalDock ? 0 : endInset)
    readonly property real insetTop:Math.max(surface.metrics.xxs+frameTop,surface.verticalDock ? endInset : 0)
    readonly property real insetBottom:Math.max(surface.metrics.xxs+frameBottom,surface.verticalDock ? endInset : 0)
    property real reveal:surface.config.presentation==="dock" && surface.groups.length>0 ? 1 : 0
    visible:shelfModel.count>0 || reveal>0
    enabled:surface.config.presentation==="dock" && surface.groups.length>0
    opacity:reveal
    Behavior on reveal { NumberAnimation { id:shelfRevealAnimation; duration:Motion.duration(surface.animations,180,100); easing.type:Easing.OutCubic } }
    readonly property var geometry: Model.staticDockRect(surface.usableArea, surface.dockSide,
      dockRow.implicitWidth + insetLeft + insetRight,
      dockRow.implicitHeight + insetTop + insetBottom,
      Math.max(Style.gapsOut, surface.metrics.lg), surface.metrics.popupPadding)
    width: geometry.width
    height: geometry.height
    x:Model.staticDockRect(surface.usableArea,surface.dockSide,width,height,Math.max(Style.gapsOut,surface.metrics.lg),surface.metrics.popupPadding).x
    y:Model.staticDockRect(surface.usableArea,surface.dockSide,width,height,Math.max(Style.gapsOut,surface.metrics.lg),surface.metrics.popupPadding).y
    Behavior on width { NumberAnimation { id:shelfWidthAnimation; duration:Motion.move(surface.animations); easing.type:Easing.OutCubic } }
    Behavior on height { NumberAnimation { id:shelfHeightAnimation; duration:Motion.move(surface.animations); easing.type:Easing.OutCubic } }
    radius: !surface.dockFrameVisible ? 0 : Model.dockRadius(surface.config.dockCorners, surface.config.dockCornerRadius, Style.cornerRadius, width, height)
    onRadiusChanged: surface.refreshInputMask()
    color: surface.dockFrameVisible ? surface.popupColors.background : "transparent"
    borderSpec: surface.dockFrameVisible ? frameSpec : Border.none()
    Widgets.ClippingRectangle {
      anchors.fill:parent
      radius:shelf.radius
      color:"transparent"
      contentInsideBorder:false
      border.color:"transparent"
      border.width:surface.dockFrameVisible ? Math.max(shelf.frameLeft,shelf.frameRight,shelf.frameTop,shelf.frameBottom) : 0
      Flickable {
        id: dockViewport
        anchors.fill: parent
        anchors.leftMargin: shelf.insetLeft
        anchors.rightMargin: shelf.insetRight
        anchors.topMargin: shelf.insetTop
        anchors.bottomMargin: shelf.insetBottom
        contentWidth: surface.verticalDock ? width : dockRow.implicitWidth
        contentHeight: surface.verticalDock ? dockRow.implicitHeight : height
        clip: true
        flickableDirection: surface.verticalDock ? Flickable.VerticalFlick : Flickable.HorizontalFlick
        boundsBehavior: Flickable.StopAtBounds
        Connections {
          target: surface
          function onDockSideChanged() { dockViewport.cancelFlick(); dockViewport.contentX = 0; dockViewport.contentY = 0 }
        }
        Item {
          id: dockRow
          readonly property real step:44+surface.metrics.sm
          // The final outgoing icons retain their space until their fade ends.
          readonly property int layoutCount:shelfModel.activeKeys.length || shelfModel.count
          readonly property real length:Model.dockLength(layoutCount,44,surface.metrics.sm)
          implicitWidth:surface.verticalDock ? 44 : length
          implicitHeight:surface.verticalDock ? length : 44
          width:implicitWidth; height:implicitHeight
          Repeater {
            id: dockIcons
            model: shelfModel
            delegate: StashAnimatedIcon {
              required property string groupKey
              required retiring
              readonly property int liveIndex:shelfModel.activeKeys.indexOf(groupKey)
              property int lastSlot:0
              onLiveIndexChanged:if (liveIndex>=0) lastSlot=liveIndex
              x:surface.verticalDock ? 0 : Math.max(0,liveIndex>=0 ? liveIndex : lastSlot)*dockRow.step
              y:surface.verticalDock ? Math.max(0,liveIndex>=0 ? liveIndex : lastSlot)*dockRow.step : 0
              Behavior on x { NumberAnimation { duration:Motion.move(surface.animations); easing.type:Easing.OutCubic } }
              Behavior on y { NumberAnimation { duration:Motion.move(surface.animations); easing.type:Easing.OutCubic } }
              group:shelfModel.dataByKey[groupKey] || ({key:groupKey,app:"",title:"",windows:[]})
              animations:surface.animations
              idleOpacity:surface.iconIdleOpacity
              onExited:function(frames) { surface.recordExit("dock",groupKey,frames) }
              Component.onCompleted: { surface.createdShelfIcons++; if (liveIndex>=0) lastSlot=liveIndex }
              enabled:!retiring && surface.config.presentation==="dock"
              frameVisible: surface.config.iconFrame !== "hidden"
              iconShape: surface.config.iconShape || "auto"
              onActivated: surface.stash.selectGroup(group, surface.screen.name)
              onContextRequested: surface.stash.openDialog("menu", surface.screen.name, group.windows, group)
            }
          }
        }
      }
    }
  }
  Repeater {
    id: bubbles
    model: bubblesModel
    delegate: StashAnimatedIcon {
      id: bubbleIcon
      required property string groupKey
      required retiring
      required property int index
      group:bubblesModel.dataByKey[groupKey] || ({key:groupKey,app:"",title:"",windows:[]})
      animations:surface.animations
      idleOpacity:surface.iconIdleOpacity
      onExited:function(frames) { surface.recordExit("bubbles",groupKey,frames) }
      enabled:!retiring && surface.bubbleMode
      onRetiringChanged: {
        if (retiring) { bubbleXAnimation.stop(); bubbleYAnimation.stop() }
        else place()
        surface.refreshInputMask()
      }
      bubble: true
      frameVisible: surface.config.iconFrame !== "hidden"
      onFrameVisibleChanged: surface.refreshInputMask()
      iconShape: surface.config.iconShape || "auto"
      property bool held: false
      property bool motionReady: false
      onXChanged: surface.refreshInputMask()
      onYChanged: surface.refreshInputMask()
      positionHeld: held
      positionAnimating: bubbleXAnimation.running || bubbleYAnimation.running
      Behavior on x { enabled:Motion.full(bubbleIcon.animations) && bubbleIcon.motionReady && !bubbleIcon.held
        NumberAnimation { id:bubbleXAnimation; duration:240; easing.type:Easing.OutCubic } }
      Behavior on y { enabled:Motion.full(bubbleIcon.animations) && bubbleIcon.motionReady && !bubbleIcon.held
        NumberAnimation { id:bubbleYAnimation; duration:240; easing.type:Easing.OutCubic } }
      property Region hitRegion: StashIconRegion {
        originX:bubbleIcon.x; originY:bubbleIcon.y; size:bubbleIcon.retiring ? 0 : bubbleIcon.width
        cornerRadius:bubbleIcon.hitRadius; iconShape:bubbleIcon.inputShape
      }
      function place() {
        var at=bubblesModel.activeKeys.indexOf(groupKey)
        if (held || retiring || at<0 || !surface.bubbleTargets[at]) return
        var position = surface.bubbleTargets[at]
        x = position[0]; y = position[1]
      }
      onDragHeld: function(pressed) {
        surface.bubbleHeld=pressed
        held=pressed
        if (held) { bubbleXAnimation.stop(); bubbleYAnimation.stop() }
        else Qt.callLater(place)
      }
      onActivated: surface.stash.selectGroup(group, surface.screen.name)
      onContextRequested: surface.stash.openDialog("menu", surface.screen.name, group.windows, group)
      onMoved: function(dx, dy) { x = Math.max(0, Math.min(surface.width - width, x + dx)); y = Math.max(24, Math.min(surface.height - height, y + dy)) }
      onDragFinished: surface.finishBubbleMove(group.key,x,y)
      Component.onCompleted: {
        surface.createdBubbles++
        var initial=Model.bubblePosition(surface.savedPositions[group.key],Math.max(0,bubblesModel.activeKeys.indexOf(groupKey)),surface.canvasWidth,surface.canvasHeight,bubblesModel.activeKeys.length)
        x=initial[0]; y=initial[1]
        Qt.callLater(function() { bubbleIcon.motionReady=true; bubbleIcon.place() })
        var next = surface.bubbleRegions.slice(); next.push(hitRegion); surface.bubbleRegions = next
      }
      Component.onDestruction: {
        if (held) surface.bubbleHeld=false
        surface.bubbleRegions = surface.bubbleRegions.filter(function(r) { return r !== hitRegion })
      }
      Connections {
        target: surface
        function onBubbleTargetsChanged() { bubbleIcon.place() }
        function onAnimationsChanged() {
          if (!Motion.full(surface.animations)) { bubbleXAnimation.complete(); bubbleYAnimation.complete() }
          bubbleIcon.place()
        }
      }
    }
  }

  StashFloatingDock {
    id:floatingDock
    onInputChanged: surface.refreshInputMask()
    onIconExited:function(key,frames) { surface.recordExit("floating",key,frames) }
    width:surface.canvasWidth
    height:surface.canvasHeight
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
    visible:surface.dialogOpen || surface.dialogReveal>0
    enabled:surface.dialogOpen
    opacity:surface.dialogReveal
    scale:Motion.full(surface.animations) ? 0.97+surface.dialogReveal*0.03 : 1
    x: (surface.canvasWidth - width) / 2
    y: Math.max(surface.metrics.popupPadding, (surface.canvasHeight - height) / 2)
    width: Math.min(Style.space(560), surface.canvasWidth - surface.metrics.popupPadding * 2)
    height: Math.min(surface.canvasHeight - surface.metrics.popupPadding * 2,
      contents.implicitHeight + surface.metrics.popupPadding * 2 + borderTop + borderBottom)
    radius: Style.cornerRadius
    color: surface.popupColors.background
    borderSpec: Border.surfaceSpec("popups", "border", surface.popupColors.border, Style.normalBorderWidth)
    focus: surface.dialogOpen
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
          text: surface.renderDialogKind === "settings" ? "Window Stash settings" : surface.renderDialogKind === "picker" ? "Stashed windows" : "Window Stash"
          textFormat: Text.PlainText
          color: surface.popupColors.text
          font.family: surface.fonts.family
          font.pixelSize: surface.fonts.title
          font.bold: true
          Layout.fillWidth: true
        }
        StashActionButton { animations:surface.animations;
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
        visible: surface.renderDialogKind === "picker"
        Layout.fillWidth: true
        foreground: surface.popupColors.text
        placeholderText: "Find by title or app…"
        text: surface.renderDialogQuery
        onTextEdited: surface.stash.dialogQuery = text
        Keys.onDownPressed: picker.incrementCurrentIndex()
        Keys.onUpPressed: picker.decrementCurrentIndex()
        onAccepted: if (picker.currentIndex >= 0 && picker.currentIndex < picker.count)
          surface.stash.restoreWindow(picker.model[picker.currentIndex].id, "")
      }
      ListView {
        id: picker
        visible: surface.renderDialogKind === "picker"
        Layout.fillWidth: true
        Layout.preferredHeight: Math.min(Style.space(360), contentHeight)
        clip: true; spacing: surface.metrics.labelGap; currentIndex: 0
        model: surface.renderDialogWindows.filter(function(w) {
          return (w.title + " " + w.app).toLowerCase().indexOf(surface.renderDialogQuery.toLowerCase()) >= 0
            && (!surface.dialogOpen || surface.stash.snapshot.windows.some(function(live) { return live.id === w.id }))
        })
        delegate: StashWindowRow {
          animations:surface.animations
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
        visible: surface.renderDialogKind === "menu"
        Layout.fillWidth: true
        StashButton { animations:surface.animations; id: restoreHereButton; text: "Restore here"; visible: surface.renderDialogWindows.length > 0; Layout.fillWidth: true
          leftAlign: true; focusable: true; foreground: surface.popupColors.text
          onClicked: {
            if (surface.renderDialogWindows.length === 1) surface.stash.restoreWindow(surface.renderDialogWindows[0].id, "current")
            else {
              surface.stash.openDialog("picker", surface.screen.name, surface.renderDialogWindows, surface.stash.dialogGroup)
              surface.stash.dialogDestination = "current"
            }
          }
        }
        StashButton { animations:surface.animations; id: restoreOriginalButton; text: "Restore to original workspace"; visible: surface.renderDialogWindows.length > 0; Layout.fillWidth: true
          leftAlign: true; focusable: true; foreground: surface.popupColors.text
          onClicked: {
            if (surface.renderDialogWindows.length === 1) surface.stash.restoreWindow(surface.renderDialogWindows[0].id, "original")
            else {
              surface.stash.openDialog("picker", surface.screen.name, surface.renderDialogWindows, surface.stash.dialogGroup)
              surface.stash.dialogDestination = "original"
            }
          }
        }
        StashButton { animations:surface.animations; text: "All stashed windows"; Layout.fillWidth: true; leftAlign: true; focusable: true; foreground: surface.popupColors.text
          onClicked: surface.stash.allWindows(surface.screen.name) }
        StashButton { animations:surface.animations; id: settingsButton; text: "Settings"; Layout.fillWidth: true; leftAlign: true; focusable: true; foreground: surface.popupColors.text
          onClicked: surface.stash.openDialog("settings", surface.screen.name, [], null) }
      }
      ColumnLayout {
        visible: surface.renderDialogKind === "settings"
        Layout.fillWidth: true; spacing: surface.metrics.panelGap
        Repeater {
          id: settingRows
          model: [
            {key:"presentation", label:"Appearance", values:["dock","bubbles","floating"],
              labels:["Static dock","Floating bubbles","Floating dock"]},
            {key:"animations", label:"Animations", values:["full","reduced","off"], labels:["Full","Reduced","Off"]},
            {key:"iconFrame", label:"Icon border/background", values:["shown","hidden"], labels:["Shown","Hidden (larger icons)"]},
            {key:"dockFrame", label:"Dock border/background", values:["shown","hidden"], labels:["Shown","Hidden"]},
            {key:"floatingPlacement", label:"Floating placement", values:["edges","free"], labels:["Snap to edges","Free placement"]},
            {key:"dockCorners", label:"Dock corners", values:["theme","custom"], labels:["Follow desktop","Custom"]},
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
              && (modelData.key !== "floatingPlacement" || surface.bubbleMode || surface.floatingMode)
              && (modelData.key !== "dockCorners" || (!surface.bubbleMode && surface.dockFrameVisible))
              && (modelData.key !== "dockFrame" || !surface.bubbleMode)
              && (modelData.key !== "iconShape" || surface.config.iconFrame !== "hidden")
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
        RowLayout {
          id:radiusRow
          visible:!surface.bubbleMode && surface.dockFrameVisible && surface.config.dockCorners === "custom"
          Layout.fillWidth:true
          Text {
            text:"Corner radius (px)"
            color:surface.popupColors.text
            font.family:surface.fonts.family
            font.pixelSize:surface.fonts.body
            Layout.fillWidth:true
          }
          Ui.NumberField {
            id:radiusField
            Layout.preferredWidth:surface.metrics.dropdownWidth
            fieldWidth:surface.metrics.dropdownWidth
            from:0; to:64; stepSize:1
            value:surface.config.dockCornerRadius === undefined ? 12 : surface.config.dockCornerRadius
            foreground:surface.popupColors.text
            onModified:function(value) { surface.stash.setting("dockCornerRadius",value) }
          }
        }
        Repeater {
          id:opacityRows
          model:[{key:"dockOpacity",label:"Dock opacity (%)"},{key:"iconOpacity",label:"Icon opacity (%)"}]
          delegate:RowLayout {
            id:opacityRow
            required property var modelData
            readonly property alias numberField:opacityField
            visible:modelData.key !== "dockOpacity" || (!surface.bubbleMode && surface.dockFrameVisible)
            Layout.fillWidth:true
            Text {
              text:opacityRow.modelData.label
              color:surface.popupColors.text
              font.family:surface.fonts.family
              font.pixelSize:surface.fonts.body
              Layout.fillWidth:true
            }
            Ui.NumberField {
              id:opacityField
              Layout.preferredWidth:surface.metrics.dropdownWidth
              fieldWidth:surface.metrics.dropdownWidth
              from:0; to:100; stepSize:1
              value:surface.config[opacityRow.modelData.key] === undefined ? 100 : surface.config[opacityRow.modelData.key]
              foreground:surface.popupColors.text
              onModified:function(value) { surface.stash.setting(opacityRow.modelData.key,value) }
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
        StashButton { animations:surface.animations; text: "All stashed windows"; focusable: true; foreground: surface.popupColors.text
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
