pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Widgets as Widgets
import Quickshell.Wayland
import Quickshell.Hyprland
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
  readonly property var liveMonitor:Hyprland.monitorFor(screen)
  readonly property int activeWorkspaceId:liveMonitor && liveMonitor.activeWorkspace ? liveMonitor.activeWorkspace.id : monitor ? monitor.activeWorkspace.id : -1
  onActiveWorkspaceIdChanged: { if (floatingDock) floatingDock.close(); if (windowPreview) windowPreview.dismiss(true); if (contextMenuOpen && stash.contextWorkspace!==activeWorkspaceId) stash.closeContext(); if (modelDelay) modelDelay.restart() }
  readonly property var config: stash.snapshot.settings
  readonly property string animations: config.animations || "full"
  readonly property string animationSpeed:config.animationSpeed || "normal"
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
  Behavior on dialogReveal { NumberAnimation { id:dialogAnimation; duration:Motion.duration(surface.animations,surface.dialogOpen ? 180 : 140,100,surface.animationSpeed); easing.type:Easing.OutCubic } }
  onDialogRevealChanged: {
    if (dialogReveal>0 && dialogReveal<1) dialogFrames++
    if (dialogReveal===0 && !dialogOpen) renderDialogKind=""
  }
  readonly property string dockSide: config.dockSide || "bottom"
  readonly property bool dockFrameVisible: config.dockFrame !== "hidden"
  readonly property bool verticalDock: dockSide === "left" || dockSide === "right"
  readonly property var usableArea: Model.usableArea(canvasWidth, canvasHeight, monitor ? monitor.reserved : [])
  readonly property real requestedStaticIconSize:Model.iconSize(config.sizePreset,false,usableArea)
  readonly property real requestedFloatingIconSize:Model.iconSize(config.sizePreset,true,usableArea)
  property real staticIconSize:44
  property real floatingIconSize:48
  readonly property real staticScale:staticIconSize/44
  readonly property real floatingScale:floatingIconSize/48
  readonly property real dockGap:Math.max(1,metrics.sm*staticScale)
  readonly property real dockInset:metrics.xxs*staticScale
  property bool sizeResizing:false
  property bool sizingReady:false
  function updateSizes() {
    sizeResizing=true
    shelfWidthAnimation.complete(); shelfHeightAnimation.complete()
    staticIconSize=requestedStaticIconSize; floatingIconSize=requestedFloatingIconSize
    Qt.callLater(function() { surface.sizeResizing=false; surface.refreshInputMask() })
  }
  onRequestedStaticIconSizeChanged:if(sizingReady) updateSizes()
  onRequestedFloatingIconSizeChanged:if(sizingReady) updateSizes()
  readonly property bool bubbleMode: config.presentation === "bubbles"
  readonly property bool floatingMode: config.presentation === "floating"
  readonly property bool floatingDockOpen:floatingDock.open
  readonly property bool previewOpen:windowPreview.opened
  readonly property bool previewsEnabled:(config.hoverPreview || "off")!=="off"
  readonly property string previewLayoutKey:JSON.stringify([config.presentation,config.scope,config.grouping,config.dockSide,config.floatingDirection,config.sizePreset])
  onPreviewLayoutKeyChanged:if (windowPreview) windowPreview.dismiss(true)
  function dismissPreview() { windowPreview.dismiss(true) }
  readonly property bool contextMenuOpen:stash.contextOpen && stash.contextScreen===screen.name
  readonly property bool keyboardOpen: dialogOpen || floatingDock.open || contextMenuOpen
  onContextMenuOpenChanged: {
    refreshInputMask()
    if (contextMenuOpen) floatingDock.close("menu")
    else Qt.callLater(function() {
      if (surface.contextMenuOpen || !surface.dialogOpen) return
      if (surface.stash.dialogKind==="picker") search.forceActiveFocus()
      else if (surface.stash.dialogKind!=="") dialog.forceActiveFocus()
    })
  }
  readonly property string monitorKey: monitor ? Model.monitorKey(monitor) : screen.name
  readonly property var savedPositions: stash.snapshot.positions[monitorKey] || ({})
  readonly property bool snapFloating: config.floatingPlacement !== "free"
  readonly property alias dragWorld:motionWorld
  function bubbleForKey(key:string):StashIcon {
    for (var i=0;i<bubbles.count;i++) {
      var icon=bubbles.itemAt(i) as StashIcon
      if (icon && icon.group.key===key) return icon
    }
    return null
  }
  function updateBubbleGrab() {
    var anyHeld=false
    for (var i=0;i<bubbles.count;i++) {
      var icon=bubbles.itemAt(i) as StashIcon
      if (icon && icon.positionHeld && !icon.retiring) { anyHeld=true;break }
    }
    bubbleHeld=anyHeld
  }
  StashDragWorld {
    id:motionWorld
    area:surface.usableArea
    snapEdges:surface.snapFloating
    physicsEnabled:surface.config.dragMotion!=="direct"
    animations:surface.animations; animationSpeed:surface.animationSpeed
    onMoved:function(key,x,y) {
      var icon=surface.bubbleForKey(key)
      if (icon && !icon.retiring) { icon.x=x;icon.y=y }
    }
    onActivityChanged:function(key,held,moving) {
      var icon=surface.bubbleForKey(key)
      if (!icon) return
      icon.positionHeld=held;icon.positionAnimating=moving
      surface.updateBubbleGrab()
    }
    onSettled:function(key,x,y) {
      if (surface.bubbleForKey(key)) surface.finishBubbleMove(key,x,y)
    }
  }
  property var bubbleDrafts: ({})
  readonly property var bubbleTargets: Model.bubbleLayout(bubblesModel.activeKeys,
    savedPositions, bubbleDrafts, canvasWidth, canvasHeight, usableArea, snapFloating,false,floatingIconSize,Math.max(1,metrics.sm*floatingScale))
  StashCollection { id:shelfModel; sourceGroups:surface.config.presentation==="dock" ? surface.groups : []; animations:surface.animations; animationSpeed:surface.animationSpeed }
  StashCollection { id:bubblesModel; sourceGroups:surface.bubbleMode ? surface.groups : []; animations:surface.animations; animationSpeed:surface.animationSpeed }
  onSavedPositionsChanged: {
    var next=Object.assign({},bubbleDrafts)
    Object.keys(next).forEach(function(key) {
      if (JSON.stringify(next[key]) === JSON.stringify(savedPositions[key])) delete next[key]
    })
    if (JSON.stringify(next) !== JSON.stringify(bubbleDrafts)) bubbleDrafts=next
  }
  function finishBubbleMove(key, x, y) {
    if (bubblesModel.activeKeys.indexOf(key)<0) return
    var point=[Math.round(x),Math.round(y)],next=Object.assign({},bubbleDrafts)
    next[key]=point
    if (JSON.stringify(next)!==JSON.stringify(bubbleDrafts)) bubbleDrafts=next
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
        surface.activeWorkspaceId, surface.config.scope)
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
  function settingItems() {
    var rows=[],repeaters=[generalRows,placementRows,iconRows,dockRows,motionRows,previewRows]
    for (var i=0;i<repeaters.length;i++) {
      if (!repeaters[i]) continue
      for (var j=0;j<repeaters[i].count;j++) {
        var row=repeaters[i].itemAt(j)
        if (row) rows.push(row)
      }
    }
    return rows
  }
  component SettingChoice:RowLayout {
    id:settingRow
    required property var modelData
    readonly property alias selector:settingDropdown
    visible:(["previewSize","previewPlacement","previewTitles"].indexOf(modelData.key)<0 || surface.previewsEnabled)
      && ((modelData.key!=="floatingDirection" && modelData.key!=="floatingAnimation") || surface.floatingMode)
      && (modelData.key!=="dockSide" || surface.config.presentation==="dock")
      && (modelData.key!=="floatingPlacement" || surface.bubbleMode || surface.floatingMode)
      && (modelData.key!=="dragMotion" || surface.bubbleMode || surface.floatingMode)
      && (modelData.key!=="dockCorners" || (!surface.bubbleMode && surface.dockFrameVisible))
      && (modelData.key!=="dockFrame" || !surface.bubbleMode)
      && (modelData.key!=="iconShape" || surface.config.iconFrame!=="hidden")
    Layout.fillWidth:true
    Text {
      text:settingRow.modelData.label
      wrapMode:Text.Wrap; Layout.minimumWidth:0; Layout.fillWidth:true
      color:surface.popupColors.text
      font.family:surface.fonts.family; font.pixelSize:surface.fonts.body
    }
    Ui.Dropdown {
      id:settingDropdown
      Layout.preferredWidth:Math.min(surface.metrics.dropdownWidth,settingsViewport.width*.55)
      showLabel:false
      options:settingRow.modelData.values.map(function(value,i) { return {value:value,label:settingRow.modelData.labels[i]} })
      Component.onCompleted:value=surface.config[settingRow.modelData.key]
      Connections {
        target:surface
        function onConfigChanged() { settingDropdown.value=surface.config[settingRow.modelData.key] }
      }
      onChanged:function(value) { surface.stash.setting(settingRow.modelData.key,value) }
    }
  }
  component SettingNumber:RowLayout {
    id:settingRow
    required property var modelData
    readonly property alias numberField:settingNumber
    visible:(modelData.key!=="dockCornerRadius" || (!surface.bubbleMode && surface.dockFrameVisible && surface.config.dockCorners==="custom"))
      && (modelData.key!=="dockOpacity" || (!surface.bubbleMode && surface.dockFrameVisible))
      && (["previewDelay","previewHideDelay"].indexOf(modelData.key)<0 || surface.previewsEnabled)
    Layout.fillWidth:true
    Text {
      text:settingRow.modelData.label
      wrapMode:Text.Wrap; Layout.minimumWidth:0; Layout.fillWidth:true
      color:surface.popupColors.text
      font.family:surface.fonts.family; font.pixelSize:surface.fonts.body
    }
    Ui.NumberField {
      id:settingNumber
      Layout.preferredWidth:Math.min(surface.metrics.dropdownWidth,settingsViewport.width*.55)
      fieldWidth:Math.min(surface.metrics.dropdownWidth,settingsViewport.width*.55)
      from:0; to:settingRow.modelData.maximum; stepSize:settingRow.modelData.stepSize || 1
      value:surface.config[settingRow.modelData.key]===undefined ? settingRow.modelData.defaultValue : surface.config[settingRow.modelData.key]
      foreground:surface.popupColors.text
      onModified:function(value) { surface.stash.setting(settingRow.modelData.key,value) }
    }
  }
  function details() {
    var menuDetails=contextMenu.details()
    var currentDialog=menuDetails.opened ? {x:menuDetails.rect.x,y:menuDetails.rect.y,width:menuDetails.rect.width,height:menuDetails.rect.height,visible:menuDetails.visible,rendered:menuDetails.rendered,progress:menuDetails.progress}
      : {x:dialog.x,y:dialog.y,width:dialog.width,height:dialog.height,visible:dialogOpen && dialogReveal>0.999,rendered:dialog.visible,progress:dialogReveal}
    var points = [], exiting=[]
    for (var i = 0; i < bubbles.count; i++) {
      var b = bubbles.itemAt(i) as StashIcon
      if (b) (b.retiring ? exiting : points).push({key:b.group.key, x:b.x, y:b.y, width:b.width, height:b.height,
        shape:b.iconShape, radius:b.hitRadius,animating:b.positionAnimating,held:b.positionHeld,appearance:b.appearance()})
    }
    var controls = []
    var rows=settingItems()
    for (var j=0;j<rows.length;j++) {
      var row=rows[j] as SettingChoice
      if (row) controls.push({key:row.modelData.key,section:row.modelData.section,value:row.selector.value,
        open:row.selector.popupOpen,visible:row.visible, rect:itemRect(row.selector)})
    }
    var opacityControls=[]
    var opacityItems=[iconOpacityRow,dockOpacityRow]
    for (var k=0;k<opacityItems.length;k++) {
      var opacityRow=opacityItems[k] as SettingNumber
      if (opacityRow) opacityControls.push({key:opacityRow.modelData.key,value:opacityRow.numberField.value,visible:opacityRow.visible,rect:itemRect(opacityRow.numberField.field)})
    }
    var shortcutControls=[]
    for (var n=0;n<shortcutRows.count;n++) {
      var shortcut=shortcutRows.itemAt(n) as StashShortcutField
      if (shortcut) shortcutControls.push(Object.assign({section:"shortcuts"},shortcut.details(surface.contentItem)))
    }
    return {screen:screen.name,workspaceId:activeWorkspaceId, width:width, height:height, eligible:windows.length,
      groups:groups.length, visible:visible, bubbles:points,exitingBubbles:exiting,createdBubbles:createdBubbles,
      motion:{mode:animations,speed:animationSpeed,exitSerial:exitSerial,completedExits:completedExits,createdShelfIcons:createdShelfIcons,dialogFrames:dialogFrames,shelfBusy:shelfModel.busy,bubbleBusy:bubblesModel.busy,dialogProgress:dialogReveal,dragWorld:motionWorld.details()},
      usableArea:usableArea,
      shelf:{x:shelf.x,y:shelf.y,width:shelf.width,height:shelf.height,side:dockSide,radius:shelf.radius,frameVisible:dockFrameVisible,background:String(shelf.color),
        borderWidth:Math.max(shelf.borderLeft,shelf.borderRight,shelf.borderTop,shelf.borderBottom),
        insets:{left:shelf.insetLeft,right:shelf.insetRight,top:shelf.insetTop,bottom:shelf.insetBottom},feedback:shelfFeedback.details(),
        contentWidth:dockViewport.contentWidth,viewportWidth:dockViewport.width,contentX:dockViewport.contentX,
        contentHeight:dockViewport.contentHeight,viewportHeight:dockViewport.height,contentY:dockViewport.contentY,
        icons:shelfIcons(false),exitingIcons:shelfIcons(true),progress:shelf.reveal,
        animating:shelfWidthAnimation.running || shelfHeightAnimation.running || shelfRevealAnimation.running},
      dialog:currentDialog,contextMenu:menuDetails,
      pickerCount:picker.count, picker:itemRect(picker),
      settingControls:controls,
      settingSections:[{key:"general",title:generalHeader.text,rect:itemRect(generalHeader)},
        {key:"placement",title:placementHeader.text,rect:itemRect(placementHeader)},
        {key:"appearance",title:appearanceHeader.text,rect:itemRect(appearanceHeader)},
        {key:"motion",title:motionHeader.text,rect:itemRect(motionHeader)},
        {key:"previews",title:previewsHeader.text,rect:itemRect(previewsHeader)},
        {key:"shortcuts",title:shortcutsHeader.text,rect:itemRect(shortcutsHeader)}],
      settingsScroll:{rect:itemRect(settingsViewport),contentY:settingsViewport.contentY,contentHeight:settingsViewport.contentHeight},shortcutControls:shortcutControls,
      opacityControls:opacityControls,
      cornerControl:{visible:radiusRow.visible,value:radiusRow.numberField.value,rect:itemRect(radiusRow.numberField.field)},
      floatingDock:floatingDock.details(),
      preview:windowPreview.details(),
      actions:{here:contextMenu.actionRect("here"),original:contextMenu.actionRect("original"),settings:contextMenu.actionRect("settings")},
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
    else {
      var rows=settingItems()
      for (var i=0;i<rows.length;i++) {
        var row=rows[i] as SettingChoice
        if (row) row.selector.close()
      }
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
  visible: shelfModel.count>0 || shelf.reveal>0 || bubblesModel.count>0 || dialogReveal>0 || dialogOpen || floatingDock.present || contextMenu.visible || windowPreview.visible
  mask: Region {
    id: inputMask
    // Keep motion on this surface during a drag, including the gaps between
    // small animated regions. Restore click-through immediately on release.
    regions: surface.dialogOpen || surface.bubbleHeld || floatingDock.held ? [dialogRegion]
      : (surface.floatingMode ? floatingDock.inputRegions : surface.bubbleMode ? surface.bubbleRegions
          : surface.config.presentation==="dock" && surface.groups.length>0 ? [shelfRegion] : [])
        .concat(surface.contextMenuOpen ? [contextRegion] : [])
        .concat(windowPreview.opened ? [previewRegion] : [])
  }
  // Native dropdown popups may extend beyond the card. While a dialog is
  // open, its surface owns the screen, just like Omarchy's keyboard panels.
  Region { id: dialogRegion; width: surface.width; height: surface.height }
  Region { id: shelfRegion; item: shelf; radius:shelf.radius }
  Region { id:previewRegion; item:windowPreview; radius:windowPreview.cornerRadius }
  Region { id: contextRegion; item:contextMenu; radius:contextMenu.radius }

  StashDockSurface {
    id: shelf
    frameOpacity:shelfFeedback.opacityProgress
    HoverHandler { id:shelfHover }
    StashFeedback {
      id:shelfFeedback
      animations:surface.animations; animationSpeed:surface.animationSpeed
      idleOpacity:(surface.config.dockOpacity === undefined ? 100 : surface.config.dockOpacity)/100
      hot:shelf.enabled && shelfHover.hovered
    }
    readonly property var frameSpec: Border.surfaceSpec("popups", "border", surface.popupColors.border, Style.normalBorderWidth)
    readonly property real frameLeft: Border.left(frameSpec)
    readonly property real frameRight: Border.right(frameSpec)
    readonly property real frameTop: Border.top(frameSpec)
    readonly property real frameBottom: Border.bottom(frameSpec)
    readonly property real crossInset:surface.dockInset + (surface.verticalDock ? Math.min(frameLeft,frameRight) : Math.min(frameTop,frameBottom))
    readonly property real thickness:surface.staticIconSize + surface.dockInset*2 + (surface.verticalDock ? frameLeft+frameRight : frameTop+frameBottom)
    readonly property real targetRadius:Model.dockRadius(surface.config.dockCorners,surface.config.dockCornerRadius,Style.cornerRadius,thickness,thickness)
    readonly property real endInset:Model.dockEndInset(targetRadius,crossInset,Math.max(frameLeft,frameRight,frameTop,frameBottom))
    // Retain these insets when the frame is hidden so toggling it keeps positions.
    readonly property real insetLeft:Math.max(surface.dockInset+frameLeft,surface.verticalDock ? 0 : endInset)
    readonly property real insetRight:Math.max(surface.dockInset+frameRight,surface.verticalDock ? 0 : endInset)
    readonly property real insetTop:Math.max(surface.dockInset+frameTop,surface.verticalDock ? endInset : 0)
    readonly property real insetBottom:Math.max(surface.dockInset+frameBottom,surface.verticalDock ? endInset : 0)
    property real reveal:surface.config.presentation==="dock" && surface.groups.length>0 ? 1 : 0
    visible:shelfModel.count>0 || reveal>0
    enabled:surface.config.presentation==="dock" && surface.groups.length>0
    opacity:reveal
    Behavior on reveal { NumberAnimation { id:shelfRevealAnimation; duration:Motion.duration(surface.animations,180,100,surface.animationSpeed); easing.type:Easing.OutCubic } }
    readonly property var geometry: Model.staticDockRect(surface.usableArea, surface.dockSide,
      dockRow.implicitWidth + insetLeft + insetRight,
      dockRow.implicitHeight + insetTop + insetBottom,
      Math.max(Style.gapsOut, surface.metrics.lg), surface.metrics.popupPadding)
    width: geometry.width
    height: geometry.height
    x:Model.staticDockRect(surface.usableArea,surface.dockSide,width,height,Math.max(Style.gapsOut,surface.metrics.lg),surface.metrics.popupPadding).x
    y:Model.staticDockRect(surface.usableArea,surface.dockSide,width,height,Math.max(Style.gapsOut,surface.metrics.lg),surface.metrics.popupPadding).y
    Behavior on width { enabled:!surface.sizeResizing; NumberAnimation { id:shelfWidthAnimation; duration:Motion.move(surface.animations,surface.animationSpeed); easing.type:Easing.OutCubic } }
    Behavior on height { enabled:!surface.sizeResizing; NumberAnimation { id:shelfHeightAnimation; duration:Motion.move(surface.animations,surface.animationSpeed); easing.type:Easing.OutCubic } }
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
          readonly property real step:surface.staticIconSize+surface.dockGap
          // The final outgoing icons retain their space until their fade ends.
          readonly property int layoutCount:shelfModel.activeKeys.length || shelfModel.count
          readonly property real length:Model.dockLength(layoutCount,surface.staticIconSize,surface.dockGap)
          implicitWidth:surface.verticalDock ? surface.staticIconSize : length
          implicitHeight:surface.verticalDock ? length : surface.staticIconSize
          width:implicitWidth; height:implicitHeight
          Repeater {
            id: dockIcons
            model: shelfModel
            delegate: StashAnimatedIcon {
              id:shelfIcon
              required property string groupKey
              required retiring
              readonly property int liveIndex:shelfModel.activeKeys.indexOf(groupKey)
              property int lastSlot:0
              onLiveIndexChanged:if (liveIndex>=0) lastSlot=liveIndex
              x:surface.verticalDock ? 0 : Math.max(0,liveIndex>=0 ? liveIndex : lastSlot)*dockRow.step
              y:surface.verticalDock ? Math.max(0,liveIndex>=0 ? liveIndex : lastSlot)*dockRow.step : 0
              Behavior on x { enabled:!surface.sizeResizing; NumberAnimation { id:shelfXAnimation; duration:Motion.move(surface.animations,surface.animationSpeed); easing.type:Easing.OutCubic } }
              Behavior on y { enabled:!surface.sizeResizing; NumberAnimation { id:shelfYAnimation; duration:Motion.move(surface.animations,surface.animationSpeed); easing.type:Easing.OutCubic } }
              Connections {
                target:surface
                function onSizeResizingChanged() { if (surface.sizeResizing) { shelfXAnimation.complete();shelfYAnimation.complete() } }
              }
              group:shelfModel.dataByKey[groupKey] || ({key:groupKey,app:"",title:"",windows:[]})
              animations:surface.animations; animationSpeed:surface.animationSpeed
              sizeScale:surface.staticScale
              idleOpacity:surface.iconIdleOpacity
              onExited:function(frames) { surface.recordExit("dock",groupKey,frames) }
              Component.onCompleted: { surface.createdShelfIcons++; if (liveIndex>=0) lastSlot=liveIndex }
              enabled:!retiring && surface.config.presentation==="dock"
              frameVisible: surface.config.iconFrame !== "hidden"
              iconShape: surface.config.iconShape || "auto"
              previewEnabled:surface.previewsEnabled
              onHovered:function(value) { windowPreview.request(group,shelfIcon,value,"dock",surface.itemRect(shelf)) }
              onPointerPressed:windowPreview.dismiss(true)
              onActivated: surface.stash.selectGroup(group, surface.screen.name)
              onCloseRequested:surface.stash.closeGroup(group,surface.screen.name)
      onContextRequested:function(x,y) { surface.stash.openContext(group,surface.screen.name,shelfIcon.mapToItem(surface.contentItem,x,y)) }
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
      animations:surface.animations; animationSpeed:surface.animationSpeed
      idleOpacity:surface.iconIdleOpacity
      previewEnabled:surface.previewsEnabled
      onHovered:function(value) { windowPreview.request(group,bubbleIcon,value,"bubble",null) }
      onExited:function(frames) { surface.recordExit("bubbles",groupKey,frames) }
      enabled:!retiring && surface.bubbleMode
      onRetiringChanged: {
        if (retiring) unregisterBody()
        else registerBody()
        surface.refreshInputMask()
      }
      bubble: true
      property real activeSize:48
      width:activeSize
      sizeScale:activeSize/48
      frameVisible: surface.config.iconFrame !== "hidden"
      onFrameVisibleChanged: surface.refreshInputMask()
      iconShape: surface.config.iconShape || "auto"
      readonly property bool held:positionHeld
      property bool registered:false
      property bool initialized:false
      function resizeBody() {
        if (!initialized || retiring || positionHeld || activeSize===surface.floatingIconSize) return
        var previous=[x,y]
        unregisterBody()
        activeSize=surface.floatingIconSize
        var at=bubblesModel.activeKeys.indexOf(groupKey)
        var target=surface.snapFloating && at>=0 ? surface.bubbleTargets[at] : null
        var point=target || Model.floatingPosition(previous,surface.canvasWidth,surface.canvasHeight,surface.usableArea,
          surface.snapFloating,width,width)
        x=point[0]; y=point[1]
        surface.dragWorld.add(groupKey,x,y,width,height); registered=true
        var body=surface.dragWorld.body(groupKey)
        if (body) { x=body.x;y=body.y }
        updateFrozen(); surface.refreshInputMask()
      }
      Timer { id:bubbleSizeUpdate; interval:0; onTriggered:bubbleIcon.resizeBody() }
      onPositionHeldChanged:if (!positionHeld) bubbleSizeUpdate.restart()
      property string lastSaved:""
      onXChanged: surface.refreshInputMask()
      onYChanged: surface.refreshInputMask()
      property Region hitRegion: StashIconRegion {
        originX:bubbleIcon.x; originY:bubbleIcon.y; size:bubbleIcon.retiring ? 0 : bubbleIcon.width
        cornerRadius:bubbleIcon.hitRadius; iconShape:bubbleIcon.inputShape
      }
      function registerBody() {
        if (registered || retiring || !surface.bubbleMode) return
        var at=Math.max(0,bubblesModel.activeKeys.indexOf(groupKey))
        var initial=initialized ? [x,y] : surface.bubbleTargets[at]
          || Model.bubblePosition(surface.savedPositions[groupKey],at,surface.canvasWidth,surface.canvasHeight,bubblesModel.activeKeys.length,width)
        if (!initialized && !surface.savedPositions[groupKey]) {
          var slot=surface.dragWorld.availablePosition(groupKey,initial[0],initial[1],width,height)
          initial=[slot.x,slot.y]
        }
        x=initial[0];y=initial[1]
        lastSaved=JSON.stringify(surface.savedPositions[groupKey] || null)
        surface.dragWorld.add(groupKey,x,y,width,height)
        registered=true
        var body=surface.dragWorld.body(groupKey)
        if (body) { x=body.x;y=body.y;positionHeld=body.held;positionAnimating=body.moving }
        updateFrozen()
      }
      function unregisterBody() {
        if (!registered) return
        if (surface.dragWorld) surface.dragWorld.remove(groupKey)
        registered=false
        positionHeld=false;positionAnimating=false;surface.updateBubbleGrab()
      }
      function updateFrozen() {
        if (!registered) return
        var ownsMenu=surface.contextMenuOpen && surface.stash.contextGroup && surface.stash.contextGroup.key===groupKey
        surface.dragWorld.freeze(groupKey,surface.stash.dialogKind!=="" || Boolean(ownsMenu) || surface.stash.groupClosing(group))
      }
      function applySaved() {
        if (!registered || retiring) return
        var saved=surface.savedPositions[groupKey],stamp=JSON.stringify(saved || null)
        if (stamp===lastSaved) return
        lastSaved=stamp
        var draft=surface.bubbleDrafts[groupKey]
        // Old controller acknowledgements cannot undo a newer resting point.
        if (draft && JSON.stringify(draft)!==stamp) {
          if (surface.stash.positionPending(groupKey)) return
          var next=Object.assign({},surface.bubbleDrafts);delete next[groupKey];surface.bubbleDrafts=next
        }
        var body=surface.dragWorld.body(groupKey)
        if (!body || body.held || body.moving || body.frozen) return
        var at=bubblesModel.activeKeys.indexOf(groupKey),target=at>=0 ? surface.bubbleTargets[at] : null
        if (target) surface.dragWorld.sync(groupKey,target[0],target[1],width,height)
      }
      onPointerPressed:function(button) { windowPreview.dismiss(true); if (registered && button!==Qt.LeftButton) surface.dragWorld.cancel(groupKey,false) }
      onDragHeld:function(pressed) {
        if (!registered) return
        if (pressed && !surface.stash.groupClosing(group)) surface.dragWorld.press(groupKey)
        else { positionHeld=false;surface.updateBubbleGrab() }
      }
      onActivated: { if (activeSize!==surface.floatingIconSize) { surface.dragWorld.cancel(groupKey,false);return }; if (!surface.stash.groupClosing(group)) { surface.dragWorld.cancel(groupKey,false);surface.stash.selectGroup(group,surface.screen.name) } }
      onCloseRequested: { surface.dragWorld.cancel(groupKey,false);surface.stash.closeGroup(group,surface.screen.name) }
      onContextRequested:function(x,y) {
        surface.dragWorld.cancel(groupKey,false)
        surface.stash.openContext(group,surface.screen.name,bubbleIcon.mapToItem(surface.contentItem,x,y))
      }
      onMoved:function(dx,dy) { if (registered) surface.dragWorld.drag(groupKey,x+dx,y+dy) }
      onDragFinished:if (registered) surface.dragWorld.release(groupKey)
      Component.onCompleted: {
        surface.createdBubbles++
        activeSize=surface.floatingIconSize
        registerBody();initialized=true
        var next=surface.bubbleRegions.slice();next.push(hitRegion);surface.bubbleRegions=next
      }
      Component.onDestruction: {
        unregisterBody()
        surface.bubbleRegions=surface.bubbleRegions.filter(function(r) { return r!==hitRegion })
      }
      Connections {
        target:surface
        function onSavedPositionsChanged() { bubbleIcon.applySaved() }
        function onFloatingIconSizeChanged() { bubbleSizeUpdate.restart() }
      }
      Connections {
        target:surface.stash
        function onContextGroupChanged() { bubbleIcon.updateFrozen() }
        function onContextOpenChanged() { bubbleIcon.updateFrozen() }
        function onDialogKindChanged() { bubbleIcon.updateFrozen() }
        function onPendingCloseIdsChanged() { bubbleIcon.updateFrozen() }
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
    preview:windowPreview
    dragWorld:surface.dragWorld
    hostWindow:surface
    monitor:surface.monitor
    screenName:surface.screen.name
    config:surface.config
    groups:surface.groups
    windows:surface.windows
    savedPosition:surface.savedPositions["dock:floating"]
    active:surface.floatingMode && surface.groups.length > 0
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
        StashActionButton { animations:surface.animations; animationSpeed:surface.animationSpeed;
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
          id:savedWindowRow
          animations:surface.animations; animationSpeed:surface.animationSpeed
          required property var modelData
          required property int index
          width: picker.width
          height: implicitHeight
          windowData: modelData
          previewEnabled:surface.previewsEnabled
          onHovered:function(value) { windowPreview.request({key:"window:"+modelData.id,app:modelData.app,title:modelData.title,windows:[modelData]},savedWindowRow,value,"picker",surface.itemRect(dialog)) }
          onPointerPressed:windowPreview.dismiss(true)
          hasCursor: ListView.isCurrentItem
          onPointed: picker.currentIndex = index
          onActivated: surface.stash.restoreWindow(modelData.id, "")
          onContextRequested:function(x,y) { surface.stash.openContext({key:"window:"+modelData.id,app:modelData.app,title:modelData.title,windows:[modelData]},surface.screen.name,savedWindowRow.mapToItem(surface.contentItem,x,y)) }
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
      Flickable {
        id:settingsViewport
        visible:surface.renderDialogKind === "settings"
        Layout.fillWidth:true; Layout.fillHeight:true
        Layout.preferredHeight:Math.min(contentHeight,Math.max(0,surface.canvasHeight-surface.metrics.popupPadding*2-120))
        contentWidth:width; contentHeight:settingsContents.implicitHeight
        boundsBehavior:Flickable.StopAtBounds
        flickableDirection:Flickable.VerticalFlick
        clip:true
        ColumnLayout {
          id:settingsContents
          width:Math.max(0,settingsViewport.width-surface.metrics.sm*2)
          height:implicitHeight
          spacing:surface.metrics.panelGap
          Ui.PanelSectionHeader { id:generalHeader; text:"General"; Layout.fillWidth:true; foreground:surface.popupColors.text }
          Repeater {
            id:generalRows
            model:[
              {key: "presentation", label: "Display mode", values: ["dock", "bubbles", "floating"], labels: ["Static dock", "Floating bubbles", "Floating dock"], section: "general"},
              {key: "scope", label: "Stash visibility", values: ["global", "workspace"], labels: ["Global", "Current workspace"], section: "general"},
              {key: "grouping", label: "Icon grouping", values: ["window", "app"], labels: ["One per window", "One per app"], section: "general"},
              {key: "restoreDestination", label: "Restore destination", values: ["current", "original"], labels: ["Current workspace", "Original workspace"], section: "general"}
            ]
            delegate:SettingChoice {}
          }
          StashButton { animations:surface.animations; animationSpeed:surface.animationSpeed; text:"All stashed windows"; focusable:true; foreground:surface.popupColors.text
            onClicked:surface.stash.allWindows(surface.screen.name) }
          Ui.PanelSeparator { Layout.fillWidth:true; foreground:surface.popupColors.text }
          Ui.PanelSectionHeader { id:placementHeader; text:"Placement"; Layout.fillWidth:true; foreground:surface.popupColors.text }
          Repeater {
            id:placementRows
            model:[
              {key: "dockSide", label: "Dock side", values: ["bottom", "top", "left", "right"], labels: ["Bottom", "Top", "Left", "Right"], section: "placement"},
              {key: "floatingDirection", label: "Floating dock direction", values: ["vertical", "horizontal"], labels: ["Vertical", "Horizontal"], section: "placement"},
              {key: "floatingPlacement", label: "Floating placement", values: ["edges", "free"], labels: ["Snap to edges", "Free placement"], section: "placement"}
            ]
            delegate:SettingChoice {}
          }
          Ui.PanelSeparator { Layout.fillWidth:true; foreground:surface.popupColors.text }
          Ui.PanelSectionHeader { id:appearanceHeader; text:"Appearance"; Layout.fillWidth:true; foreground:surface.popupColors.text }
          Repeater {
            id:iconRows
            model:[
              {key: "iconFrame", label: "Icon border/background", values: ["shown", "hidden"], labels: ["Shown", "Hidden (larger icons)"], section: "appearance"},
              {key: "iconShape", label: "Icon shape", values: ["auto", "circle", "square", "rounded", "squircle"], labels: ["Automatic", "Circle", "Square", "Rounded square", "Squircle"], section: "appearance"},
              {key: "sizePreset", label: "Icon and dock size", values: ["50", "75", "100", "125", "150", "175", "200", "250", "300"], labels: ["50%", "75%", "100% (Default)", "125%", "150%", "175%", "200%", "250%", "300%"], section: "appearance"}
            ]
            delegate:SettingChoice {}
          }
          SettingNumber { id:iconOpacityRow; modelData:({key: "iconOpacity", label: "Icon opacity (%)", maximum: 100, defaultValue: 100, section: "appearance"}) }
          Repeater {
            id:dockRows
            model:[
              {key: "dockFrame", label: "Dock border/background", values: ["shown", "hidden"], labels: ["Shown", "Hidden"], section: "appearance"},
              {key: "dockCorners", label: "Dock corners", values: ["theme", "custom"], labels: ["Follow desktop", "Custom"], section: "appearance"}
            ]
            delegate:SettingChoice {}
          }
          SettingNumber { id:radiusRow; modelData:({key: "dockCornerRadius", label: "Corner radius (px)", maximum: 64, defaultValue: 12, section: "appearance"}) }
          SettingNumber { id:dockOpacityRow; modelData:({key: "dockOpacity", label: "Dock opacity (%)", maximum: 100, defaultValue: 100, section: "appearance"}) }
          Ui.PanelSeparator { Layout.fillWidth:true; foreground:surface.popupColors.text }
          Ui.PanelSectionHeader { id:motionHeader; text:"Motion"; Layout.fillWidth:true; foreground:surface.popupColors.text }
          Repeater {
            id:motionRows
            model:[
              {key: "animations", label: "Animations", values: ["full", "reduced", "off"], labels: ["Full", "Reduced", "Off"], section: "motion"},
              {key: "animationSpeed", label: "Animation speed", values: ["slow", "relaxed", "normal", "fast", "ultrafast"], labels: ["Slow (0.5×)", "Relaxed (0.75×)", "Normal", "Fast (1.5×)", "Ultrafast (2.5×)"], section: "motion"},
              {key: "dragMotion", label: "Drag motion", values: ["physics", "direct"], labels: ["Physics", "Direct"], section: "motion"},
              {key: "floatingAnimation", label: "Unfold animation", values: ["arc", "glide", "cascade", "spring", "swing", "matryoshka", "matryoshka-hop", "jumping"], labels: ["Arc", "Glide", "Cascade", "Spring", "Swing", "Matryoshka", "Matryoshka hops", "Jumping"], section: "motion"}
            ]
            delegate:SettingChoice {}
          }
          Ui.PanelSeparator { Layout.fillWidth:true; foreground:surface.popupColors.text }
          Ui.PanelSectionHeader { id:previewsHeader; text:"Previews"; Layout.fillWidth:true; foreground:surface.popupColors.text }
          Repeater {
            id:previewRows
            model:[
              {key: "hoverPreview", label: "Hover preview", values: ["off", "still", "live"], labels: ["Off", "Still image", "Live"], section: "previews"},
              {key: "previewSize", label: "Preview size", values: ["small", "medium", "large"], labels: ["Small", "Medium", "Large"], section: "previews"},
              {key: "previewPlacement", label: "Preview placement", values: ["auto", "above", "below", "left", "right"], labels: ["Automatic", "Above", "Below", "Left", "Right"], section: "previews"},
              {key: "previewTitles", label: "Preview titles", values: ["shown", "hidden"], labels: ["Shown", "Hidden"], section: "previews"}
            ]
            delegate:SettingChoice {}
          }
          Repeater {
            id:previewTimingRows
            model:[
              {key: "previewDelay", label: "Preview delay (ms)", maximum: 1500, defaultValue: 400, stepSize: 50, section: "previews"},
              {key: "previewHideDelay", label: "Preview hide delay (ms)", maximum: 1000, defaultValue: 200, stepSize: 50, section: "previews"}
            ]
            delegate:SettingNumber {}
          }
          Ui.PanelSeparator { Layout.fillWidth:true; foreground:surface.popupColors.text }
          Ui.PanelSectionHeader { id:shortcutsHeader; text:"Keyboard shortcuts"; Layout.fillWidth:true; foreground:surface.popupColors.text }
          Repeater {
            id:shortcutRows
            model:[{key:"minimizeShortcut",label:"Minimize window",defaultValue:"SUPER + A"},
              {key:"restoreLastShortcut",label:"Restore newest (last in, first out)",defaultValue:"SUPER + Z"},
              {key:"restoreOldestShortcut",label:"Restore oldest (first in, first out)",defaultValue:""}]
            delegate:StashShortcutField {
              required property var modelData
              stash:surface.stash; settingKey:modelData.key; label:modelData.label
              binding:surface.config[modelData.key]===undefined ? modelData.defaultValue : surface.config[modelData.key]
              defaultBinding:modelData.defaultValue
              animations:surface.animations; animationSpeed:surface.animationSpeed; foreground:surface.popupColors.text
            }
          }
          Item { Layout.fillWidth:true; Layout.preferredHeight:surface.metrics.xxs }
        }
        Controls.ScrollBar.vertical:Controls.ScrollBar {
          id:settingsScrollbar
          contentItem:Rectangle { implicitWidth:surface.metrics.sm; radius:Style.cornerRadius
            color:Style.hoverStateColor(surface.popupColors.text,Commons.Color.accent); opacity:settingsScrollbar.active ? .6 : 0 }
          background:Item {}
        }
      }
    }
  }
  StashPreview {
    id:windowPreview
    stash:surface.stash
    config:surface.config
    area:surface.usableArea
    coordinateRoot:surface.contentItem
    screenName:surface.screen.name
    blocked:surface.stash.contextOpen || (surface.stash.dialogKind!=="" && surface.stash.dialogKind!=="picker")
      || surface.bubbleHeld || floatingDock.held
    onInputChanged:surface.refreshInputMask()
    onRestoring:floatingDock.close("restore")
  }
  StashContextMenu {
    id:contextMenu
    stash:surface.stash
    host:surface
    screenName:surface.screen.name
    area:surface.usableArea
    animations:surface.animations; animationSpeed:surface.animationSpeed
    onInputChanged:surface.refreshInputMask()
  }
  Component.onCompleted: {
    sizingReady=true;updateSizes()
    var next = stash.surfaces.slice(); next.push(surface); stash.surfaces = next
    modelDelay.restart()
  }
  Component.onDestruction: if (stash) stash.surfaces = stash.surfaces.filter(function(s) { return s !== surface })
}
