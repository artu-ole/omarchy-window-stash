pragma ComponentBehavior: Bound
import QtQuick
import Quickshell
import qs.Commons
import qs.Commons as Commons
import qs.Ui as Ui
import "Motion.js" as Motion
import "FloatingPreviewModel.js" as Geometry
import "PreviewInteraction.js" as Interaction

// The captured content and its input controls are separate so a later
// interactive-preview mode can replace input routing without changing capture.
Item {
  id:card
  required property var stash
  required property var config
  required property var group
  required property Item coordinateRoot
  required property string screenName
  property bool captureAllowed:true
  property bool interactive:true
  property bool retiring:false
  property bool movable:true
  property bool resizable:true
  property bool held:false
  property bool moving:false
  property bool resizing:false
  property bool expandedTile:false
  property bool folding:false
  property bool unfolding:false
  property real stageIconSize:48
  property var stageOrigin:null
  property bool keyboardSelected:false
  property real maximumHeight:100000
  property real presence:0
  property var sourceSizes:({})
  property real aspectOverride:0
  property int appliedGeometryEpoch:0
  property bool awaitingGeometryCapture:false
  property real expectedSourceAspect:0
  readonly property string geometryWatchKey:"geometry:"+String(Date.now())+":"+String(Math.random())
  property var interactionClipRect:null
  property string claimedInteractionKey:""
  property var leasedRecord:null
  property bool hadNativeInteraction:false
  property int interactionGeometryRevision:0
  property var managementArea:({x:0,y:0,width:coordinateRoot.width,height:coordinateRoot.height})
  readonly property var record:group && group.windows.length ? group.windows[0] : null
  readonly property var displayRecord:interactionBusy && leasedRecord ? leasedRecord : record
  readonly property string geometryIdentityKey:displayRecord ? [displayRecord.id,displayRecord.address,displayRecord.pid,displayRecord.stableId].join(":") : ""
  readonly property var geometryRecord:Geometry.geometryRecord(displayRecord,sourceSizes)
  readonly property string key:"preview:"+(group ? group.key : "")
  readonly property string animations:config.animations || "full"
  readonly property string animationSpeed:config.animationSpeed || "normal"
  readonly property bool titleVisible:config.floatingPreviewTitles==="shown"
  readonly property bool frameVisible:config.floatingPreviewFrame==="shown"
  readonly property var popupColors:Commons.Color.popups
  readonly property var fonts:Style.font
  readonly property var desktop:DesktopEntries.heuristicLookup(displayRecord ? String(displayRecord.app || "") : "")
  readonly property var dimensions:Geometry.dimensions(width,geometryRecord,{x:0,y:0,width:Math.max(1,width),height:Math.max(1,maximumHeight)},titleVisible,frameVisible,aspectOverride)
  readonly property var sourceGeometryState:displayRecord && typeof stash.previewGeometryState==="function" ? stash.previewGeometryState(displayRecord.id) : null
  readonly property bool geometryReady:!resizing && ((!sourceGeometryState && !(displayRecord && displayRecord.previewResized) && customFrameMatches()) || (sourceGeometryState && sourceGeometryState.ready && appliedGeometryEpoch===sourceGeometryState.captureRevision
    && !awaitingGeometryCapture && frameMatchesGeometry()))
  readonly property string geometryReason:resizing ? "Finish resizing to interact" : !geometryReady
    ? sourceGeometryState ? sourceGeometryState.reason || "Waiting for a fresh preview frame…" : "Updating preview proportions…" : ""
  readonly property bool interactionEnabled:config.floatingPreviewInteraction==="on" && typeof stash.beginPreviewInteraction==="function"
  readonly property bool lifecycleAvailable:typeof stash.lifecycleReady!=="boolean" || stash.lifecycleReady
  readonly property bool interactionOwned:typeof stash.endPreviewInteraction==="function" && !!stash.previewInteractionRequest
    && stash.previewInteractionRequest.monitor===screenName && stash.previewInteractionRequest.viewKey===(claimedInteractionKey || key)
  readonly property bool interactionQueued:typeof stash.previewInteractionPendingMatches==="function" && !!record
    && stash.previewInteractionPendingMatches(record.id,screenName,key)
  readonly property bool interactionBusy:interactionOwned || interactionQueued
  readonly property bool interactionRequested:interactionOwned && !!displayRecord && stash.previewInteractionRequest.id===displayRecord.id
  readonly property bool interactionActive:interactionRequested && stash.previewInteractionStatus.state==="active"
  readonly property bool interactionFullyVisible:visibleForInteraction(interactionGeometryRevision)
  readonly property bool nativeHovered:interactionRequested && stash.pointerKnown && Geometry.contains(nativeImageRect(),stash.pointerPosition.x,stash.pointerPosition.y)
  readonly property bool hovered:hover.hovered || pointer.containsMouse || nativeHovered
  readonly property bool live:interactionBusy || (config.floatingPreviewUpdate || "hover")==="live" || ((config.floatingPreviewUpdate || "hover")==="hover" && hovered)
  readonly property bool canMove:interactive && movable && config.floatingPreviewLock!=="locked" && !retiring && !interactionBusy
  readonly property bool canResize:interactive && resizable && config.floatingPreviewSizing!=="preset" && config.floatingPreviewLock!=="locked" && !retiring && !interactionBusy
  readonly property Region inputRegion:Region { item:card; onChanged:card.inputChanged() }
  readonly property bool controlsOutside:interactionBusy && !!interactionBar.placement
  readonly property Region managementRegion:Region { item:interactionBar; onChanged:card.inputChanged() }
  signal inputChanged()
  signal movePressed()
  signal moveRequested(real x,real y)
  signal moveReleased()
  signal moveCanceled()
  signal resizePressed(string corner)
  signal resizeRequested(real dx,real dy,string corner)
  signal resizeReleased()
  signal activated()
  signal contextRequested(real x,real y)
  signal closeRequested()
  signal scrolled(real delta)
  signal sourceAspectObserved(string recordId,real width,real height)
  signal geometryReleased()
  signal sourceGeometryAccepted(var state)
  signal proportionsResetRequested()
  height:dimensions.height
  enabled:interactive && !retiring
  opacity:presence*feedback.visualOpacity
  readonly property real stageMinimumScale:Math.min(1,Math.max(1,stageIconSize)/Math.max(1,width,height))
  scale:Motion.full(animations) ? (folding || unfolding ? stageMinimumScale+(1-stageMinimumScale)*presence : .97+.03*presence) : 1
  transform:Translate {
    x:card.unfolding && card.stageOrigin && Motion.full(card.animations)
      ? (card.stageOrigin.x+card.stageOrigin.width/2-card.x-card.width/2)*(1-card.presence) : 0
    y:card.unfolding && card.stageOrigin && Motion.full(card.animations)
      ? (card.stageOrigin.y+card.stageOrigin.height/2-card.y-card.height/2)*(1-card.presence) : 0
  }
  z:held || resizing ? 20 : hovered ? 10 : 0
  onXChanged:invalidateInteractionGeometry()
  onYChanged:invalidateInteractionGeometry()
  onWidthChanged:invalidateInteractionGeometry()
  onHeightChanged:invalidateInteractionGeometry()
  onPresenceChanged:invalidateInteractionGeometry()
  onScaleChanged:invalidateInteractionGeometry()
  onParentChanged:invalidateInteractionGeometry()
  onHeldChanged:if(!held) geometryReleased()
  onResizingChanged:if(!resizing) geometryReleased()
  onMovingChanged:if(!moving) geometryReleased()
  onRetiringChanged: {if(retiring) endNativeInteraction("retiring");presence=retiring && !interactionBusy ? 0 : 1;syncGeometryVisibility()}
  onInteractiveChanged:if (!interactive) {cancelInteraction();endNativeInteraction("preview-disabled")}
  onCaptureAllowedChanged: {if(!captureAllowed) endNativeInteraction("capture-suspended");syncGeometryVisibility();sourceGeometryUpdate.restart()}
  onVisibleChanged: {if(!visible) endNativeInteraction("preview-hidden");syncGeometryVisibility();sourceGeometryUpdate.restart()}
  onRecordChanged: {
    if(interactionOwned && (!record || stash.previewInteractionRequest.id!==record.id)) endNativeInteraction("preview-source-changed")
  }
  onGeometryIdentityKeyChanged: {
    if(resizing || held || moving) cancelInteraction()
    appliedGeometryEpoch=0;awaitingGeometryCapture=false;expectedSourceAspect=0;syncGeometryVisibility();sourceGeometryUpdate.restart()
  }
  onSourceGeometryStateChanged:sourceGeometryUpdate.restart()
  onDisplayRecordChanged: {if(displayRecord && displayRecord.previewFolded===true) endNativeInteraction("preview-folded");syncGeometryVisibility();sourceGeometryUpdate.restart()}
  onGroupChanged:if(interactionEnabled && claimedInteractionKey && (!group || group.windows.length!==1)) endNativeInteraction("preview-group-changed")
  onKeyChanged:if(claimedInteractionKey && claimedInteractionKey!==key) endNativeInteraction("preview-replaced")
  onInteractionRequestedChanged: {geometryReleased();interactionGeometry.restart()}
  onInteractionActiveChanged:if(interactionActive) hadNativeInteraction=true
  onInteractionBusyChanged: {
    if(!interactionBusy) {
      var releasedId=leasedRecord ? leasedRecord.id : "",refresh=hadNativeInteraction
      leasedRecord=null;claimedInteractionKey="";hadNativeInteraction=false;presence=retiring ? 0 : 1
      if(refresh && releasedId) Qt.callLater(function() {
        if(card && thumbnail && !card.interactionBusy && card.visible && card.captureAllowed && card.record && card.record.id===releasedId
            && typeof thumbnail.refreshFrame==="function") thumbnail.refreshFrame()
      })
    }
    geometryReleased();interactionGeometry.restart()
  }
  onInteractionClipRectChanged:invalidateInteractionGeometry()
  onCanMoveChanged:if (!canMove) cancelInteraction()
  onCanResizeChanged:if (!canResize && resizing) cancelInteraction()
  Behavior on presence { NumberAnimation { duration:card.retiring ? Motion.exit(card.animations,card.animationSpeed) : Motion.enter(card.animations,card.animationSpeed);easing.type:Easing.OutCubic } }
  function cancelInteraction() {
    pointer.suppressed=true
    if(held || moving) moveCanceled()
    if(resizing) resizeReleased()
    resizing=false
  }
  function rectOf(item) {var p=item.mapToItem(coordinateRoot,0,0);return {x:p.x,y:p.y,width:item.width,height:item.height}}
  function invalidateInteractionGeometry() {
    interactionGeometryRevision++
    inputChanged()
    if(interactionGeometry) interactionGeometry.restart()
  }
  function visibleForInteraction(revision) {
    if(!Number.isFinite(revision)) return false
    if(!interactionClipRect) return true
    var image=rectOf(thumbnail),clip=interactionClipRect
    return image.x>=clip.x-.5 && image.y>=clip.y-.5 && image.x+image.width<=clip.x+clip.width+.5 && image.y+image.height<=clip.y+clip.height+.5
  }
  function visualRectOf(item,rect) {
    rect=rect || {x:0,y:0,width:item.width,height:item.height}
    var first=item.mapToItem(coordinateRoot,rect.x,rect.y),last=item.mapToItem(coordinateRoot,rect.x+rect.width,rect.y+rect.height)
    return {x:first.x,y:first.y,width:last.x-first.x,height:last.y-first.y}
  }
  function globalRectOf(item,rect) {
    var monitor=typeof stash.screenMonitor==="function" ? stash.screenMonitor(screenName) : null
    if(!monitor || !item) return null
    var local=visualRectOf(item,rect)
    return {x:monitor.x+local.x,y:monitor.y+local.y,width:local.width,height:local.height}
  }
  function nativeImageRect() {
    var content=typeof thumbnail.contentRect==="function" ? thumbnail.contentRect() : null
    return globalRectOf(thumbnail,content)
  }
  function nativeExcludeRects() {
    var overlays=interactionBar.visible && !controlsOutside ? [globalRectOf(interactionBar)] : []
    var monitor=typeof stash.screenMonitor==="function" ? stash.screenMonitor(screenName) : null
    var clip=monitor && interactionClipRect ? {x:monitor.x+interactionClipRect.x,y:monitor.y+interactionClipRect.y,
      width:interactionClipRect.width,height:interactionClipRect.height} : null
    var excluded=Interaction.exclusions(nativeImageRect(),overlays,clip)
    if(interactionBar.visible && controlsOutside) excluded.push(globalRectOf(interactionBar))
    return excluded
  }
  function interactionReady(allowGroup) {
    return !interactionBusy && interactionEnabled && lifecycleAvailable && geometryReady && !!record
      && record.previewFolded!==true && !(stash.pendingPreviewFoldIds && stash.pendingPreviewFoldIds[record.id])
      && (!unfolding || presence>=.999)
      && (allowGroup || group.windows.length===1) && interactive && visible && captureAllowed && !retiring
      && !held && !moving && !resizing && visibleForInteraction(interactionGeometryRevision) && thumbnail.hasContent && thumbnail.eligible
  }
  function shortcutHit(x,y) {
    if(!Geometry.contains(nativeImageRect(),x,y)) return false
    return !nativeExcludeRects().some(function(rect) {return Geometry.contains(rect,x,y)})
  }
  function shortcutSurfaceHit(x,y) {
    var bounds=globalRectOf(card)
    if(interactionClipRect) {
      var monitor=typeof stash.screenMonitor==="function" ? stash.screenMonitor(screenName) : null
      if(!monitor) return false
      bounds=Interaction.intersection(bounds,{x:monitor.x+interactionClipRect.x,y:monitor.y+interactionClipRect.y,
        width:interactionClipRect.width,height:interactionClipRect.height})
    }
    return Geometry.contains(bounds,x,y)
  }
  function shortcutControlHit(x,y) {return interactionBar.visible && Geometry.contains(globalRectOf(interactionBar),x,y)}
  function shortcutIdentity() {
    return JSON.stringify({key:key,tile:expandedTile,windows:group.windows.map(function(window) {
      return [window.id,window.address,window.pid,window.stableId,window.tag,window.phase]
    })})
  }
  function beginNativeInteraction() {
    if(!interactionReady(false)) return false
    claimedInteractionKey=key
    leasedRecord=record
    var accepted=stash.beginPreviewInteraction(record,screenName,key,nativeImageRect(),nativeExcludeRects())
    if(!accepted) {claimedInteractionKey="";leasedRecord=null}
    return accepted
  }
  function syncNativeInteraction() {
    if(!interactionBusy || !displayRecord) return
    if(!visible || !captureAllowed || !visibleForInteraction(interactionGeometryRevision) || !thumbnail.hasContent || !thumbnail.eligible) {endNativeInteraction("capture-unavailable");return}
    stash.updatePreviewInteraction(displayRecord.id,screenName,claimedInteractionKey || key,nativeImageRect(),nativeExcludeRects())
  }
  function endNativeInteraction(reason) {
    if(typeof stash.endPreviewInteraction!=="function") return
    var request=stash.previewInteractionRequest
    var pending=stash.previewInteractionPendingRequest
    if((request && request.monitor===screenName && request.viewKey===(claimedInteractionKey || key))
        || (pending && pending.monitor===screenName && pending.viewKey===(claimedInteractionKey || key))) stash.endPreviewInteraction(reason)
    if(!interactionBusy) claimedInteractionKey=""
  }
  function restoreCard() {endNativeInteraction("restore");activated()}
  function activatePrimary() {
    if(interactionBusy) return
    if(interactionEnabled && group.windows.length===1 && config.floatingPreviewActivation==="click") beginNativeInteraction()
    else activated()
  }
  function observeSourceAspect() {
    if(!displayRecord || !thumbnail.active || !thumbnail.hasContent || !thumbnail.eligible) return
    var size=thumbnail.sourceSize
    if(Geometry.validSourceSize([size.width,size.height])) sourceAspectObserved(displayRecord.id,size.width,size.height)
  }
  function frameMatchesGeometry() {
    if(!sourceGeometryState) return true
    var size=thumbnail.sourceSize,goal=sourceGeometryState.size,aspect=Number(sourceGeometryState.aspect)
    if(!thumbnail.hasContent || !thumbnail.eligible || !Number.isFinite(aspect) || aspect<=0 || size.width<=0 || size.height<=0) return false
    var scale=goal && goal[0]>0 ? Math.max(1,size.width/goal[0]) : 1
    return Math.abs(size.width-size.height*aspect)<=2*scale
  }
  function customFrameMatches() {
    if(aspectOverride<=0) return true
    var size=thumbnail.sourceSize,original=displayRecord && displayRecord.size
    if(!thumbnail.hasContent || !thumbnail.eligible || size.width<=0 || size.height<=0) return false
    var scale=original && original[0]>0 && original[1]>0 ? Math.max(1,size.width/original[0],size.height/original[1]) : 1
    return Math.abs(size.width-size.height*aspectOverride)<=2*scale
  }
  function syncSourceGeometry() {
    var state=sourceGeometryState
    if(!state || !state.ready || !state.captureRevision || state.captureRevision===appliedGeometryEpoch || resizing || !visible || !captureAllowed || retiring || (displayRecord && displayRecord.previewFolded===true)) return
    appliedGeometryEpoch=state.captureRevision;expectedSourceAspect=Number(state.aspect);awaitingGeometryCapture=true
    sourceGeometryAccepted(state)
    if(typeof thumbnail.restartCapture==="function") thumbnail.restartCapture()
    else awaitingGeometryCapture=false
  }
  function checkGeometryFrame() {
    if(awaitingGeometryCapture && frameMatchesGeometry()) awaitingGeometryCapture=false
  }
  function imageReadyForShape() {return thumbnail.hasContent && thumbnail.eligible}
  function capturedSourceSize() {return thumbnail.sourceSize}
  function syncGeometryVisibility() {
    if(typeof stash.watchPreviewGeometry==="function") stash.watchPreviewGeometry(geometryWatchKey,
      visible && captureAllowed && !retiring && displayRecord && displayRecord.previewFolded!==true ? displayRecord.id : "")
    if(expandedTile && visible && captureAllowed && !retiring && displayRecord && displayRecord.previewResized
        && displayRecord.previewFolded!==true
        && !sourceGeometryState && typeof stash.verifyPreviewGeometry==="function") stash.verifyPreviewGeometry(displayRecord.id)
  }
  function resetProportions() {if(canResize) proportionsResetRequested()}
  function details() {
    var rect=rectOf(card),handles=[]
    var corners=["top-left","top-right","bottom-left","bottom-right"]
    for(var i=0;i<resizeRepeater.count;i++) {var handle=resizeRepeater.itemAt(i);if(handle) handles.push({corner:corners[i],rect:rectOf(handle),visible:handle.opacity>0,enabled:handle.enabled})}
    var edges=["left","right","top","bottom"]
    for(var j=0;j<edgeRepeater.count;j++) {var edge=edgeRepeater.itemAt(j);if(edge) handles.push({corner:edges[j],rect:rectOf(edge),visible:edge.opacity>0,enabled:edge.enabled})}
    return {key:key,recordId:displayRecord ? displayRecord.id : "",rect:rect,x:rect.x,y:rect.y,width:width,height:height,
      imageRect:rectOf(thumbnail),resizeRect:handles.length ? handles[3].rect : null,resizeRects:handles,
      titleVisible:titleVisible,frameVisible:frameVisible,hovered:hovered,held:held,moving:moving,resizing:resizing,aspectOverride:aspectOverride,geometryReady:geometryReady,geometryReason:geometryReason,
      groupCount:group ? group.windows.length : 0,visible:visible,presence:presence,image:thumbnail.details(),
      locked:config.floatingPreviewLock==="locked",resizable:canResize,closeRect:rectOf(closeButton),closeVisible:closeButton.visible,
      interaction:{enabled:interactionEnabled,requested:interactionRequested,queued:interactionQueued,busy:interactionBusy,active:interactionActive,fullyVisible:interactionFullyVisible,
        interactEnabled:interactButton.enabled,
        imageRect:nativeImageRect(),excludeRects:nativeExcludeRects(),controlsVisible:interactionBar.visible,
        controlsOutside:controlsOutside,controlsRect:rectOf(interactionBar),
        interactRect:rectOf(interactButton),restoreRect:rectOf(restoreButton),manageRect:rectOf(manageButton)}}
  }
  HoverHandler {id:hover}
  StashFeedback {
    id:feedback
    animations:card.animations;animationSpeed:card.animationSpeed
    idleOpacity:(card.config.iconOpacity===undefined ? 100 : card.config.iconOpacity)/100
    hot:card.hovered || card.held || card.resizing || card.interactionBusy
    down:card.held || card.resizing
  }
  Ui.BorderSurface {
    anchors.fill:parent
    visible:card.frameVisible
    radius:0
    color:card.popupColors.background
    borderSpec:Border.surfaceSpec("popups","border",card.popupColors.border,Style.normalBorderWidth)
  }
  StashPreviewImage {
    id:thumbnail
    objectName:"floating-preview-source"
    x:card.dimensions.inset;y:card.dimensions.inset+card.dimensions.header
    width:Math.max(1,card.width-card.dimensions.inset*2)
    height:Math.max(1,card.height-card.dimensions.header-card.dimensions.inset*2)
    record:card.displayRecord;stash:card.stash
    mode:card.live ? "live" : "still"
    active:card.captureAllowed && card.visible && !card.retiring && !!card.displayRecord && card.displayRecord.previewFolded!==true
    animations:card.animations;animationSpeed:card.animationSpeed
    onSourceSizeChanged: {sourceObservation.restart();interactionGeometry.restart();geometryFrameCheck.restart()}
    onHasContentChanged: {sourceObservation.restart();interactionGeometry.restart();geometryFrameCheck.restart()}
  }
  Timer {id:sourceObservation;interval:0;onTriggered:card.observeSourceAspect()}
  Timer {id:interactionGeometry;interval:0;onTriggered:card.syncNativeInteraction()}
  Timer {id:sourceGeometryUpdate;interval:0;onTriggered:card.syncSourceGeometry()}
  Timer {id:geometryFrameCheck;interval:0;onTriggered:card.checkGeometryFrame()}
  Rectangle {
    x:card.dimensions.inset;y:card.dimensions.inset
    width:Math.max(0,card.width-card.dimensions.inset*2);height:card.dimensions.header
    visible:card.titleVisible
    color:card.popupColors.background
    Image {
      x:7;y:(parent.height-height)/2;width:18;height:18
      source:Quickshell.iconPath(card.desktop && card.desktop.icon ? String(card.desktop.icon) : "application-x-executable",true)
      sourceSize:Qt.size(width*Screen.devicePixelRatio,height*Screen.devicePixelRatio)
      fillMode:Image.PreserveAspectFit
    }
    Text {
      x:32;y:0;width:Math.max(0,parent.width-64);height:parent.height
      text:card.displayRecord ? card.displayRecord.title : "";textFormat:Text.PlainText
      color:card.popupColors.text;font.family:card.fonts.family;font.pixelSize:card.fonts.bodySmall
      elide:Text.ElideRight;verticalAlignment:Text.AlignVCenter
    }
  }
  Rectangle {
    visible:card.group && card.group.windows.length>1
    x:parent.width-width-6;y:card.dimensions.header+6
    width:Math.max(22,countText.implicitWidth+10);height:22;radius:11
    color:card.popupColors.background
    Text {id:countText;anchors.centerIn:parent;text:String(card.group ? card.group.windows.length : 0);textFormat:Text.PlainText;color:card.popupColors.text;font.family:card.fonts.family;font.pixelSize:card.fonts.caption}
  }
  MouseArea {
    id:pointer
    anchors.fill:parent
    acceptedButtons:Qt.LeftButton | Qt.MiddleButton | Qt.RightButton
    hoverEnabled:true
    cursorShape:card.held ? Qt.ClosedHandCursor : Qt.PointingHandCursor
    property point start:Qt.point(0,0)
    property point origin:Qt.point(0,0)
    property bool dragging:false
    property bool suppressed:false
    onPressed:function(mouse) {
      start=mapToItem(card.coordinateRoot,mouse.x,mouse.y);origin=Qt.point(card.x,card.y)
      dragging=false;suppressed=false
      if(mouse.button===Qt.LeftButton && card.canMove) card.movePressed()
    }
    onPositionChanged:function(mouse) {
      if(!pressed || pressedButtons!==Qt.LeftButton || suppressed) return
      var p=mapToItem(card.coordinateRoot,mouse.x,mouse.y),dx=p.x-start.x,dy=p.y-start.y
      if(dragging || Math.abs(dx)+Math.abs(dy)>6) {
        dragging=true
        if(card.canMove) card.moveRequested(origin.x+dx,origin.y+dy)
        else suppressed=true
      }
    }
    onReleased:function(mouse) {
      if(mouse.button!==Qt.LeftButton || !card.canMove) return
      if(dragging) {suppressed=true;card.moveReleased()}
      else card.moveCanceled()
    }
    onCanceled: {suppressed=true;card.moveCanceled()}
    onClicked:function(mouse) {
      if(suppressed || dragging || card.resizing) return
      if(card.interactionBusy) return
      if(mouse.button===Qt.MiddleButton) card.closeRequested()
      else if(mouse.button===Qt.RightButton) {var p=mapToItem(card.coordinateRoot,mouse.x,mouse.y);card.contextRequested(p.x,p.y)}
      else card.activatePrimary()
    }
    onWheel:function(event) {
      if(card.interactionBusy) {event.accepted=true;return}
      var delta=event.pixelDelta.y || event.pixelDelta.x || event.angleDelta.y || event.angleDelta.x
      card.scrolled(delta);event.accepted=true
    }
  }
  StashActionButton {
    id:closeButton
    objectName:"floating-preview-close"
    z:2
    visible:card.titleVisible && size>0
    x:card.width-width-card.dimensions.inset-3;y:card.dimensions.inset+(card.dimensions.header-height)/2
    size:Math.max(0,Math.min(24,card.dimensions.header-4,card.width-4))
    fontSize:card.fonts.icon;iconText:"×";tooltipText:card.group && card.group.windows.length>1 ? "Close app windows" : "Close window"
    foreground:card.popupColors.text
    animations:card.animations;animationSpeed:card.animationSpeed
    onClicked:card.closeRequested()
  }
  Rectangle {
    anchors.fill:parent
    visible:card.resizing || card.keyboardSelected || card.interactionBusy
    color:"transparent";border.width:1;border.color:Commons.Color.accent
  }
  Ui.BorderSurface {
    id:interactionBar
    readonly property real buttonSize:Math.max(10,Math.min(24,card.width/3-2,card.height-6))
    readonly property var placement:card.interactionBusy ? Interaction.controlsPlacement(card.visualRectOf(card),card.managementArea,width,height) : null
    parent:card.controlsOutside ? card.coordinateRoot : card
    visible:card.visible && (card.interactionEnabled || card.interactionBusy) && !!card.displayRecord
      && (card.group.windows.length===1 || card.interactionBusy)
      && (card.hovered || card.config.floatingPreviewControls==="always" || card.interactionBusy)
    x:card.controlsOutside ? placement.x : Math.max(0,card.width-width-3)
    y:card.controlsOutside ? placement.y : Math.min(3,Math.max(0,card.height-height))
    width:buttonSize*3+4;height:buttonSize+4
    radius:Math.min(Style.cornerRadius,height/2)
    color:card.popupColors.background
    borderSpec:Border.surfaceSpec("popups","border",card.popupColors.border,Style.normalBorderWidth)
    z:card.controlsOutside ? 10000 : 100
    onXChanged: {card.inputChanged();interactionGeometry.restart()}
    onYChanged: {card.inputChanged();interactionGeometry.restart()}
    onParentChanged: {card.inputChanged();interactionGeometry.restart()}
    onVisibleChanged:interactionGeometry.restart()
    onWidthChanged:interactionGeometry.restart()
    onHeightChanged:interactionGeometry.restart()
    MouseArea {anchors.fill:parent;acceptedButtons:Qt.AllButtons}
    StashActionButton {
      id:interactButton
      objectName:"floating-preview-interact"
      property bool activeAtPress:false
      x:2;y:2;size:interactionBar.buttonSize
      iconText:card.interactionBusy ? "■" : "▶"
      tooltipText:card.interactionBusy ? "Stop interacting" : !card.lifecycleAvailable ? "Window Stash support is restarting…"
        : !card.geometryReady ? card.geometryReason
        : !card.interactionFullyVisible ? "Scroll this preview fully into view to interact"
        : card.stash.previewInteractionError ? "Interact: "+card.stash.previewInteractionError : "Interact with this window (Super+left click)"
      foreground:card.interactionBusy ? Commons.Color.accent : card.popupColors.text
      animations:card.animations;animationSpeed:card.animationSpeed
      enabled:card.interactive && (card.interactionBusy || (card.lifecycleAvailable && card.geometryReady && card.interactionFullyVisible && thumbnail.hasContent && thumbnail.eligible))
      onPressed:activeAtPress=card.interactionBusy
      onCanceled:activeAtPress=false
      onClicked: {
        var stopping=activeAtPress || card.interactionBusy;activeAtPress=false
        if(stopping) card.endNativeInteraction("stopped");else card.beginNativeInteraction()
      }
    }
    StashActionButton {
      id:restoreButton
      objectName:"floating-preview-restore"
      x:2+interactionBar.buttonSize;y:2;size:interactionBar.buttonSize
      iconText:"↗";tooltipText:"Restore window"
      foreground:card.popupColors.text;animations:card.animations;animationSpeed:card.animationSpeed
      onClicked:card.restoreCard()
    }
    StashActionButton {
      id:manageButton
      objectName:"floating-preview-manage"
      property bool activeAtPress:false
      x:2+interactionBar.buttonSize*2;y:2;size:interactionBar.buttonSize
      iconText:card.interactionBusy ? "✥" : "≡"
      tooltipText:card.interactionBusy ? "Stop interacting to move or resize" : "Window actions"
      foreground:card.popupColors.text;animations:card.animations;animationSpeed:card.animationSpeed
      onPressed:activeAtPress=card.interactionBusy
      onCanceled:activeAtPress=false
      onClicked: {
        var managing=activeAtPress || card.interactionBusy;activeAtPress=false
        if(managing) card.endNativeInteraction("manage")
        else {var point=mapToItem(card.coordinateRoot,width/2,height/2);card.contextRequested(point.x,point.y)}
      }
    }
  }
  Item {
    id:resizeHandles
    objectName:"floating-preview-resize-handles"
    anchors.fill:parent
    Repeater {
      id:edgeRepeater
      model:["left","right","top","bottom"]
      delegate:MouseArea {
        id:edgeHandle
        required property string modelData
        readonly property bool horizontal:modelData==="left" || modelData==="right"
        readonly property real cornerInset:horizontal ? Math.min(18,card.height/3) : Math.min(18,card.width/3)
        width:horizontal ? Math.min(7,card.width/3) : Math.max(0,card.width-cornerInset*2)
        height:horizontal ? Math.max(0,card.height-cornerInset*2) : Math.min(7,card.height/3)
        x:horizontal ? modelData==="left" ? 0 : card.width-width : cornerInset
        y:horizontal ? cornerInset : modelData==="top" ? 0 : card.height-height
        z:1
        enabled:card.canResize && width>0 && height>0
        opacity:enabled && (card.hovered || pressed) ? 1 : 0
        hoverEnabled:true;acceptedButtons:Qt.LeftButton
        cursorShape:horizontal ? Qt.SizeHorCursor : Qt.SizeVerCursor
        property point start:Qt.point(0,0)
        onPressed:function(mouse) {start=mapToItem(card.coordinateRoot,mouse.x,mouse.y);card.resizing=true;card.resizePressed(modelData)}
        onPositionChanged:function(mouse) {
          if(!pressed) return
          var p=mapToItem(card.coordinateRoot,mouse.x,mouse.y);card.resizeRequested(p.x-start.x,p.y-start.y,modelData)
        }
        onReleased: {card.resizing=false;card.resizeReleased()}
        onCanceled: {card.resizing=false;card.resizeReleased()}
      }
    }
    Repeater {
      id:resizeRepeater
      model:["top-left","top-right","bottom-left","bottom-right"]
      delegate:MouseArea {
        id:resizeHandle
        required property string modelData
        readonly property string corner:modelData
        readonly property bool leftSide:corner.indexOf("left")>=0
        readonly property bool topSide:corner.indexOf("top")>=0
        width:Math.min(18,card.width/3);height:Math.min(18,card.height/3)
        x:leftSide ? 0 : card.width-width;y:topSide ? 0 : card.height-height
        enabled:card.canResize
        opacity:card.canResize && (card.hovered || pressed) ? 1 : 0
        hoverEnabled:true;acceptedButtons:Qt.LeftButton
        cursorShape:leftSide===topSide ? Qt.SizeFDiagCursor : Qt.SizeBDiagCursor
        property point start:Qt.point(0,0)
        Behavior on opacity {NumberAnimation {duration:Motion.duration(card.animations,100,60,card.animationSpeed)}}
        onPressed:function(mouse) {
          start=mapToItem(card.coordinateRoot,mouse.x,mouse.y);card.resizing=true;card.resizePressed(corner)
        }
        onPositionChanged:function(mouse) {
          if(!pressed) return
          var p=mapToItem(card.coordinateRoot,mouse.x,mouse.y);card.resizeRequested(p.x-start.x,p.y-start.y,corner)
        }
        onReleased: {card.resizing=false;card.resizeReleased()}
        onCanceled: {card.resizing=false;card.resizeReleased()}
        Rectangle {
          x:resizeHandle.leftSide ? 3 : parent.width-10;y:resizeHandle.topSide ? 3 : parent.height-4
          width:7;height:1;color:Commons.Color.accent
        }
        Rectangle {
          x:resizeHandle.leftSide ? 3 : parent.width-4;y:resizeHandle.topSide ? 3 : parent.height-10
          width:1;height:7;color:Commons.Color.accent
        }
      }
    }
  }
  Component.onCompleted: {presence=retiring ? 0 : 1;invalidateInteractionGeometry();syncGeometryVisibility()}
  Component.onDestruction: {
    if(typeof stash.watchPreviewGeometry==="function") stash.watchPreviewGeometry(geometryWatchKey,"")
    cancelInteraction();endNativeInteraction("card-destroyed")
  }
}
