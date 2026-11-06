pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Window
import Quickshell
import Quickshell.Hyprland
import qs.Commons
import qs.Commons as Commons
import qs.Ui as Ui
import "Model.js" as Model
import "Motion.js" as Motion

Item {
  id:dock
  required property var stash
  required property var dragWorld
  required property var hostWindow
  required property var monitor
  required property string screenName
  required property var config
  required property var groups
  required property var windows
  property var savedPosition
  property bool active:false
  property bool expanded:false
  property bool grabReady:false
  property bool held:false
  property bool bodyMoving:false
  readonly property string bodyKey:"dock:floating"
  readonly property bool motionFrozen:open || reveal>0 || actorsMoving
    || (stash.contextOpen && stash.contextScreen===screenName)
    || stash.dialogKind!=="" || (groups.length>0 && stash.groupClosing(groups[0]))
  property bool motionReady:false
  property bool closeForPlacement:false
  property bool placementPending:false
  property string lastDismissal:""
  property var pendingPosition:null
  property real anchorX:0
  property real anchorY:0
  property real pivotX:anchorX+24
  property real pivotY:anchorY+24
  property int fanSign:0
  property int fanCurve:0
  property int firstIndex:0
  property string selectedKey:""
  property bool horizontal:false
  property string activeAnimation:"arc"
  readonly property string requestedAnimation:config.floatingAnimation || "arc"
  readonly property var fanTiming:Motion.fanProfile(activeAnimation)
  property int createdIcons:0
  property int openingFrames:0
  property int closingFrames:0
  property var actorRegions:[]
  readonly property string animations:config.animations || "full"
  readonly property real iconIdleOpacity:(config.iconOpacity === undefined ? 100 : config.iconOpacity)/100
  readonly property bool requestedHorizontal:config.floatingDirection === "horizontal"
  readonly property bool snapEdges:config.floatingPlacement !== "free"
  readonly property bool dockFrameVisible:config.dockFrame !== "hidden"
  readonly property var usableArea:Model.usableArea(width,height,monitor ? monitor.reserved : [])
  // Monitor snapshots replace reserved arrays even when their values match.
  readonly property string areaKey:JSON.stringify(usableArea)
  readonly property var popupColors:Commons.Color.popups
  readonly property var metrics:Style.spacing
  readonly property var panelBorder:Border.surfaceSpec("popups","border",popupColors.border,Style.normalBorderWidth)
  readonly property real borderWidth:Math.max(Border.left(panelBorder),Border.right(panelBorder),Border.top(panelBorder),Border.bottom(panelBorder))
  readonly property real gap:metrics.sm
  readonly property real tileSize:48
  readonly property real inset:metrics.xxs+borderWidth
  readonly property real targetRadius:Model.dockRadius(config.dockCorners,config.dockCornerRadius,Style.cornerRadius,tileSize+inset*2,tileSize+inset*2)
  readonly property real endInset:Math.max(inset,Model.dockEndInset(targetRadius,inset,borderWidth))
  readonly property int groupCount:iconModel.activeKeys.length
  readonly property int tail:Math.max(0,Math.min(3,groupCount)-1)*4
  property real stackTail:tail
  property real handleOpacity:active ? 1 : 0
  property real reveal:open ? 1 : 0
  readonly property bool open:active && expanded && windows.length>1
  readonly property int currentIndex:iconModel.activeKeys.indexOf(selectedKey)
  readonly property var geometry:Model.fanLayout(pivotX,pivotY,usableArea,groupCount || iconModel.count,horizontal,tileSize,gap,inset,endInset,fanSign,fanCurve,{x:anchorX,y:anchorY})
  readonly property int maxFirst:Math.max(0,groupCount-geometry.capacity)
  readonly property bool overflow:maxFirst>0
  property bool actorsMoving:false
  readonly property bool windowActive:Window.active
  readonly property bool animating:actorsMoving || revealAnimation.running || handleAnimation.running || tailAnimation.running || iconModel.busy
  readonly property bool present:active || handleOpacity>0 || reveal>0 || actorsMoving
  readonly property var currentRects:actorRects(false)
  readonly property var finalRects:actorRects(true)
  readonly property var bounds:Model.fanBounds(currentRects,inset,endInset,horizontal,usableArea)
  readonly property var finalBounds:Model.fanBounds(finalRects,inset,endInset,horizontal,usableArea)
  signal inputChanged()
  signal iconExited(string key,int frames)
  visible:present
  focus:open
  HoverHandler { id:fanHover; onHoveredChanged:dock.updateLeaveTimer() }
  readonly property int leaveTimeout:800
  function updateLeaveTimer() {
    if (!open || fanHover.hovered || pan.active) leaveDelay.stop()
    else if (!leaveDelay.running) leaveDelay.start()
  }
  Timer { id:leaveDelay; interval:dock.leaveTimeout; onTriggered:if (dock.open && !fanHover.hovered && !pan.active) dock.close("pointer-leave") }
  Connections {
    target:dock.stash
    function onPointerClicked(x,y) {
      if (!dock.open || !dock.monitor) return
      var px=x-dock.monitor.x,py=y-dock.monitor.y
      if (!dock.panelContains(px,py)) dock.close("outside-click")
    }
  }
  function panelContains(x,y) {
    var px=x-panel.x,py=y-panel.y,r=panel.radius
    if (px<0 || py<0 || px>panel.width || py>panel.height) return false
    var dx=Math.max(r-px,0,px-panel.width+r),dy=Math.max(r-py,0,py-panel.height+r)
    return dx*dx+dy*dy<=r*r
  }
  Keys.onEscapePressed:close("escape")
  Keys.onReturnPressed:if (open && currentIndex>=0) activate(iconModel.dataByKey[selectedKey])
  // Navigation follows the physical direction of the fan.
  Keys.onDownPressed:navigate(geometry.sign)
  Keys.onUpPressed:navigate(-geometry.sign)
  Keys.onRightPressed:function(event) { if (horizontal) navigate(geometry.sign); else event.accepted=false }
  Keys.onLeftPressed:function(event) { if (horizontal) navigate(-geometry.sign); else event.accepted=false }
  Behavior on stackTail { NumberAnimation { id:tailAnimation; duration:Motion.duration(dock.animations,180,0); easing.type:Easing.OutCubic } }
  Behavior on handleOpacity { NumberAnimation { id:handleAnimation; duration:Motion.duration(dock.animations,180,100); easing.type:Easing.OutCubic } }
  Behavior on reveal { NumberAnimation { id:revealAnimation; duration:Motion.duration(dock.animations,(dock.open ? dock.fanTiming.open : dock.fanTiming.close)+Math.min(dock.fanTiming.limit,Math.max(0,dock.geometry.capacity-1)*dock.fanTiming.stagger),100); easing.type:Easing.OutCubic } }
  onMotionFrozenChanged:freezeUpdate.restart()
  Timer { id:freezeUpdate; interval:0; onTriggered:if (dock.dragWorld) dock.dragWorld.freeze(dock.bodyKey,dock.motionFrozen) }
  Connections {
    target:dock.dragWorld
    function onMoved(key,x,y) { if (key===dock.bodyKey) { dock.anchorX=x; dock.anchorY=y } }
    function onActivityChanged(key,isHeld,moving) {
      if (key!==dock.bodyKey) return
      dock.held=isHeld; dock.bodyMoving=moving
      if (!isHeld && !moving && !dock.motionFrozen && dock.placementPending) positionUpdate.restart()
    }
    function onSettled(key,x,y) {
      if (key!==dock.bodyKey || !dock.active) return
      dock.pendingPosition=[Math.round(x),Math.round(y)]; dock.placementPending=false
      if (!dock.savedPosition || Math.abs(dock.savedPosition[0]-x)>.5 || Math.abs(dock.savedPosition[1]-y)>.5)
        dock.stash.recordPosition(dock.monitor,key,x,y)
    }
  }

  StashCollection {
    id:iconModel
    sourceGroups:dock.config.presentation==="floating" ? dock.groups : []
    animations:dock.animations
    hold:!dock.open && (dock.reveal>0 || dock.actorsMoving)
    onReconciled: { dock.repairSelection(); motionUpdate.restart() }
  }
  function hasMovingActors() {
    for (var i=0;i<actors.count;i++) { var actor=actors.itemAt(i) as StashFanIcon; if (actor && actor.moving) return true }
    return false
  }
  function actorRects(finalPose) {
    var result=[]
    for (var i=0;i<actors.count;i++) {
      var actor=actors.itemAt(i) as StashFanIcon
      if (!actor || actor.retiring || (finalPose ? !actor.slotVisible : actor.drawWeight<.01)) continue
      result.push({x:finalPose ? actor.destinationX : actor.x,y:finalPose ? actor.destinationY : actor.y,width:tileSize,height:tileSize})
    }
    return result
  }
  function frontActor() {
    for (var i=0;i<actors.count;i++) {
      var actor=actors.itemAt(i) as StashFanIcon
      if (actor && actor.ordinal===0 && !actor.retiring) return actor
    }
    return null
  }
  function repairSelection() {
    firstIndex=Math.max(0,Math.min(firstIndex,maxFirst))
    if (groupCount && currentIndex<0) selectedKey=iconModel.activeKeys[Math.min(firstIndex,groupCount-1)]
    else if (!groupCount) selectedKey=""
  }
  function selectIndex(index) {
    if (index<0 || index>=groupCount) return
    selectedKey=iconModel.activeKeys[index]
    if (index<firstIndex) firstIndex=index
    else if (index>=firstIndex+geometry.capacity) firstIndex=Math.min(maxFirst,index-geometry.capacity+1)
  }
  function navigate(delta) { if (open) { selectIndex(Math.max(0,Math.min(groupCount-1,currentIndex+delta))); if (!fanHover.hovered) leaveDelay.restart() } }
  function setFirst(index) {
    firstIndex=Math.max(0,Math.min(maxFirst,index))
    if (currentIndex<firstIndex || currentIndex>=firstIndex+geometry.capacity) selectedKey=iconModel.activeKeys[firstIndex] || ""
  }
  function unfoldAt(x,y) {
    dragWorld.cancel(bodyKey,false); dragWorld.freeze(bodyKey,true)
    placementPending=false
    var reversing=(actorsMoving || reveal>0) && horizontal===requestedHorizontal
    if (!reversing) { horizontal=requestedHorizontal; activeAnimation=requestedAnimation; fanSign=0; fanCurve=0 }
    pivotX=x; pivotY=y; firstIndex=0
    selectedKey=iconModel.activeKeys[0] || ""
    fanSign=geometry.sign; fanCurve=geometry.curveSign
    expanded=true
  }
  function close(reason) { leaveDelay.stop(); if (expanded) lastDismissal=reason || "dismiss"; expanded=false }
  function finishClose() {
    if (!open && !actorsMoving && reveal===0) {
      horizontal=requestedHorizontal; activeAnimation=requestedAnimation; fanSign=0; fanCurve=0; firstIndex=0
      freezeUpdate.restart()
      if (placementPending) positionUpdate.restart()
    }
  }
  function place() {
    if (!motionReady || !dragWorld) { placementPending=true; return }
    if (!active) { dragWorld.remove(bodyKey); return }
    var body=dragWorld.body(bodyKey)
    if (body && (body.width!==tileSize || body.height!==tileSize+tail))
      dragWorld.sync(bodyKey,body.x,body.y,tileSize,tileSize+tail)
    if (body && (body.held || body.moving || body.frozen)) { placementPending=true; return }
    placementPending=false
    var point=Model.floatingPosition(pendingPosition || savedPosition,width,height,usableArea,snapEdges,tileSize+tail)
    if (!body) dragWorld.add(bodyKey,point[0],point[1],tileSize,tileSize+tail)
    else dragWorld.sync(bodyKey,point[0],point[1],tileSize,tileSize+tail)
    freezeUpdate.restart()
  }
  function schedulePlacement(closeFan) { placementPending=true; closeForPlacement=closeForPlacement || closeFan; positionUpdate.restart() }
  Timer {
    id:positionUpdate; interval:0
    onTriggered: { if (dock.closeForPlacement) dock.close("geometry"); dock.closeForPlacement=false; dock.place() }
  }
  function activate(group) {
    if (!group || !groups.some(function(g) { return g.key===group.key })) return
    dragWorld.cancel(bodyKey,false); close("restore"); stash.selectGroup(group,screenName)
  }
  function context(group,point) {
    var target=group || groups[0]
    if (!target) return
    dragWorld.cancel(bodyKey,false)
    stash.openContext(target,screenName,point)
    close("menu")
  }
  function details() {
    var icons=[],exiting=[],states=[]
    for (var i=0;i<actors.count;i++) {
      var actor=actors.itemAt(i) as StashFanIcon
      if (!actor) continue
      var record={key:actor.group.key,x:actor.x,y:actor.y,width:actor.width,height:actor.height,appearance:actor.icon.appearance(),progress:actor.progress,moving:actor.moving,frames:actor.motionFrames,maxBend:actor.maxBend,maxTilt:actor.maxTilt,minScale:actor.minScale,peakProgress:actor.peakProgress,rotation:actor.rotation,scale:actor.scale,slotVisible:actor.slotVisible}
      states.push(record)
      if ((open || reveal>0) && actor.slotVisible && actor.drawWeight>.01) (actor.retiring ? exiting : icons).push(record)
    }
    icons.sort(function(a,b) { return iconModel.activeKeys.indexOf(a.key)-iconModel.activeKeys.indexOf(b.key) })
    var front=frontActor()
    return {active:active,expanded:open,orientation:horizontal ? "horizontal" : "vertical",style:activeAnimation,animating:animating,progress:reveal,
      createdIcons:createdIcons,currentIndex:currentIndex,currentKey:selectedKey,actors:states,firstIndex:firstIndex,capacity:geometry.capacity,
      dismissal:{hovered:fanHover.hovered,pending:leaveDelay.running,timeout:leaveTimeout},
      pointer:{x:pivotX,y:pivotY},fan:{sign:geometry.sign,curveSign:geometry.curveSign},lastDismissal:lastDismissal,
      animation:{openingFrames:openingFrames,closingFrames:closingFrames},grabActive:open && windowActive,snapping:bodyMoving,windows:windows.length,groups:groups.length,
      handle:{held:held,x:anchorX,y:anchorY,width:tileSize,height:tileSize+stackTail,opacity:handleOpacity,appearance:front ? front.icon.appearance() : null},
      panel:{x:panel.x,y:panel.y,width:panel.width,height:panel.height,radius:panel.radius,frameVisible:dockFrameVisible,background:String(panel.color),
        borderWidth:dockFrameVisible ? borderWidth : 0,targetHeight:finalBounds.height,targetWidth:finalBounds.width,inset:inset,endInset:endInset,visible:panel.visible,down:geometry.forward && !horizontal,right:geometry.forward && horizontal,feedback:panelFeedback.details()},
      contentHeight:horizontal ? tileSize : Model.dockLength(groupCount,tileSize,gap),viewportHeight:horizontal ? tileSize : geometry.span,contentY:horizontal ? 0 : firstIndex*geometry.step,
      contentWidth:horizontal ? Model.dockLength(groupCount,tileSize,gap) : tileSize,viewportWidth:horizontal ? geometry.span : tileSize,contentX:horizontal ? firstIndex*geometry.step : 0,icons:icons,exitingIcons:exiting}
  }
  onAnchorXChanged:inputChanged()
  onAnchorYChanged:inputChanged()
  onStackTailChanged:inputChanged()
  onWindowActiveChanged:if (open && grabReady && !windowActive) updateLeaveTimer()
  Timer { id:motionUpdate; interval:0; onTriggered: { dock.actorsMoving=dock.hasMovingActors(); dock.finishClose() } }
  onSavedPositionChanged: {
    if (pendingPosition && JSON.stringify(pendingPosition)===JSON.stringify(savedPosition)) pendingPosition=null
    schedulePlacement(false)
  }
  onSnapEdgesChanged:schedulePlacement(true)
  onAreaKeyChanged:schedulePlacement(true)
  onTailChanged:schedulePlacement(false)
  onWidthChanged:schedulePlacement(true)
  onHeightChanged:schedulePlacement(true)
  onRequestedAnimationChanged:if (!open && !actorsMoving && reveal===0) activeAnimation=requestedAnimation
  onRequestedHorizontalChanged: { close(); motionUpdate.restart() }
  onActiveChanged: { inputChanged(); if (!active) { close(); if (dragWorld) dragWorld.remove(bodyKey); held=false; bodyMoving=false } else schedulePlacement(false) }
  onWindowsChanged:if (windows.length<=1) close()
  onAnimationsChanged:if (!Motion.full(animations)) {
    tailAnimation.complete()
    if (animations==="off") { revealAnimation.complete(); handleAnimation.complete() }
  }
  onRevealChanged: {
    inputChanged()
    if (reveal>0 && reveal<1) { if (open) openingFrames++; else closingFrames++ }
    motionUpdate.restart()
  }
  onOpenChanged: {
    inputChanged(); grabReady=false; updateLeaveTimer()
    if (open) {
      openingFrames=0; grabDelay.restart()
      Qt.callLater(function() { if (dock.open) dock.forceActiveFocus() })
    } else closingFrames=0
  }
  Timer { id:grabDelay; interval:100; onTriggered:dock.grabReady=dock.open }
  Component.onCompleted: { horizontal=requestedHorizontal; motionReady=true; schedulePlacement(false) }
  Component.onDestruction:if (dragWorld) dragWorld.remove(bodyKey)
  Connections {
    target:Hyprland
    function onRawEvent(event) {
      if (!dock.open || !event) return
      if (event.name==="workspace" || event.name==="workspacev2") dock.close(event.name)
      else if (event.name==="activewindowv2" || event.name==="focusedmon") dock.updateLeaveTimer()
    }
  }

  readonly property var inputRegions:!active ? [] : open ? actorRegions.concat([panelRegion]) : [frontRegion,middleRegion,backRegion]
  StashIconRegion { id:frontRegion; originX:dock.anchorX; originY:dock.anchorY; size:48; iconShape:dock.config.iconFrame==="hidden" ? "square" : dock.config.iconShape || "auto"
    cornerRadius:dock.config.iconFrame==="hidden" ? 0 : Model.iconRadius(dock.config.iconShape || "auto",48,true,Style.cornerRadius) }
  StashIconRegion { id:middleRegion; originX:dock.anchorX; originY:dock.anchorY+Math.min(4,dock.stackTail); size:dock.stackTail>0 ? 48 : 0; iconShape:frontRegion.iconShape; cornerRadius:frontRegion.cornerRadius }
  StashIconRegion { id:backRegion; originX:dock.anchorX; originY:dock.anchorY+Math.min(8,dock.stackTail); size:dock.stackTail>4 ? 48 : 0; iconShape:frontRegion.iconShape; cornerRadius:frontRegion.cornerRadius }
  Region { id:panelRegion; item:panel; radius:panel.radius }
  StashDockSurface {
    id:panel
    z:-1
    x:dock.bounds.x; y:dock.bounds.y; width:dock.bounds.width; height:dock.bounds.height
    visible:dock.reveal>0
    opacity:dock.reveal
    frameOpacity:panelFeedback.opacityProgress
    radius:dock.dockFrameVisible ? Model.fanRadius(dock.bounds,dock.currentRects,dock.targetRadius,dock.borderWidth) : 0
    color:dock.dockFrameVisible ? dock.popupColors.background : "transparent"
    borderSpec:dock.dockFrameVisible ? dock.panelBorder : Border.none()
    onXChanged:dock.inputChanged()
    onYChanged:dock.inputChanged()
    onWidthChanged:dock.inputChanged()
    onHeightChanged:dock.inputChanged()
    onRadiusChanged:dock.inputChanged()
    StashFeedback { id:panelFeedback; animations:dock.animations; idleOpacity:(dock.config.dockOpacity===undefined ? 100 : dock.config.dockOpacity)/100; hot:dock.open && fanHover.hovered }
  }
  WheelHandler {
    enabled:dock.open && dock.overflow
    target:null
    onWheel:function(event) {
      var delta=dock.horizontal ? (event.angleDelta.x || event.angleDelta.y) : event.angleDelta.y
      if (delta) dock.setFirst(dock.firstIndex+(delta>0 ? -1 : 1))
      event.accepted=true
    }
  }
  DragHandler {
    id:pan
    enabled:dock.open && dock.overflow
    target:null
    acceptedButtons:Qt.LeftButton
    property int beganAt:0
    onActiveChanged: { if (active) beganAt=dock.firstIndex; dock.updateLeaveTimer() }
    onActiveTranslationChanged:if (active) {
      var delta=dock.horizontal ? activeTranslation.x : activeTranslation.y
      dock.setFirst(beganAt-Math.round(delta/(dock.geometry.step*dock.geometry.sign)))
    }
  }
  Repeater {
    id:actors
    model:iconModel
    delegate:StashFanIcon {
      id:actor
      required property string groupKey
      required retiring
      readonly property int liveIndex:iconModel.activeKeys.indexOf(groupKey)
      property int lastIndex:Math.max(0,liveIndex)
      onLiveIndexChanged:if (liveIndex>=0) lastIndex=liveIndex
      ordinal:liveIndex>=0 ? liveIndex : lastIndex
      group:iconModel.dataByKey[groupKey] || ({key:groupKey,app:"",title:"",windows:[]})
      displayGroup:ordinal===0 && !dock.open ? {key:group.key,app:group.app,windows:dock.windows.length ? dock.windows : group.windows,title:dock.windows.length===1 ? group.title : dock.windows.length+" stashed windows · Click to expand"} : group
      geometry:dock.geometry
      area:dock.usableArea
      readonly property var slot:Model.fanSlot(dock.geometry,ordinal,dock.firstIndex)
      destinationX:slot.x; destinationY:slot.y
      slotVisible:slot.shown
      stackX:dock.anchorX; stackY:dock.anchorY+Math.min(ordinal,2)*4
      expanded:dock.open
      globalPresence:dock.handleOpacity
      animations:dock.animations
      unfoldStyle:dock.activeAnimation
      idleOpacity:dock.iconIdleOpacity
      frameVisible:dock.config.iconFrame!=="hidden"
      iconShape:dock.config.iconShape || "auto"
      hasCursor:dock.open ? dock.selectedKey===groupKey : stackHover.hovered
      externalPressed:!dock.open && drag.pressed
      onActivated:dock.activate(group)
      onCloseRequested:dock.stash.closeGroup(group,dock.screenName)
      onContextRequested:function(x,y) { dock.context(group,actor.mapToItem(dock.hostWindow.contentItem,x,y)) }
      onHovered:function(value) { if (value && actor.interactive && !pan.active && !actor.moving) dock.selectIndex(actor.ordinal) }
      onInputChanged: { dock.inputChanged(); motionUpdate.restart() }
      onExited:function(frames) { dock.iconExited(groupKey,frames) }
      property Region hitRegion:StashIconRegion { originX:actor.x; originY:actor.y; size:actor.interactive ? 48 : 0; iconShape:actor.icon.inputShape; cornerRadius:actor.icon.hitRadius }
      Component.onCompleted: { dock.createdIcons++; var next=dock.actorRegions.slice(); next.push(hitRegion); dock.actorRegions=next }
      Component.onDestruction:dock.actorRegions=dock.actorRegions.filter(function(region) { return region!==hitRegion })
    }
  }
  Item {
    id:handle
    z:20000
    x:dock.anchorX; y:dock.anchorY; width:48; height:48+dock.stackTail
    enabled:dock.active && !dock.open
    HoverHandler { id:stackHover }
    Ui.PanelToolTip { visible:stackHover.hovered && !drag.pressed && !dock.open; text:dock.windows.length===1 ? dock.windows[0].title : dock.windows.length+" stashed windows · Click to expand" }
    MouseArea {
      id:drag
      anchors.fill:parent
      acceptedButtons:Qt.LeftButton | Qt.RightButton | Qt.MiddleButton
      hoverEnabled:true
      preventStealing:true
      cursorShape:Qt.PointingHandCursor
      property point start
      property bool dragging:false
      onPressed:function(mouse) {
        start=Qt.point(mouse.x,mouse.y); dragging=false
        if (mouse.button===Qt.LeftButton && !dock.stash.groupClosing(dock.groups[0])) dock.dragWorld.press(dock.bodyKey)
        else dock.dragWorld.cancel(dock.bodyKey,false)
      }
      onPositionChanged:function(mouse) {
        if (!pressed || pressedButtons!==Qt.LeftButton) return
        var dx=mouse.x-start.x,dy=mouse.y-start.y
        if (dragging || Math.abs(dx)+Math.abs(dy)>6) {
          dragging=true
          var point=Model.floatingAnchor([dock.anchorX+dx,dock.anchorY+dy],dock.width,dock.height)
          dock.dragWorld.drag(dock.bodyKey,point[0],point[1])
        }
      }
      function finishDrag() { dock.dragWorld.release(dock.bodyKey) }
      onCanceled:if (dock.held) finishDrag()
      onReleased:function(mouse) {
        if (dragging) { finishDrag(); return }
        if (mouse.button===Qt.LeftButton && dock.stash.groupClosing(dock.groups[0])) return
        dock.dragWorld.cancel(dock.bodyKey,false)
        if (mouse.button===Qt.MiddleButton) { if (containsMouse) dock.stash.closeGroup(dock.groups[0],dock.screenName) }
        else if (mouse.button===Qt.RightButton) dock.context(dock.groups[0],dock.mapToItem(dock.hostWindow.contentItem,dock.anchorX+mouse.x,dock.anchorY+mouse.y))
        else if (dock.windows.length===1) dock.activate(dock.groups[0])
        else dock.unfoldAt(dock.anchorX+mouse.x,dock.anchorY+mouse.y)
      }
    }
  }
}
