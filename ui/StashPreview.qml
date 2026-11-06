pragma ComponentBehavior: Bound
import QtQuick
import qs.Commons
import qs.Commons as Commons
import qs.Ui as Ui
import "Motion.js" as Motion
import "PreviewModel.js" as PreviewModel

Item {
  id:preview
  required property var stash
  required property var config
  required property var area
  required property Item coordinateRoot
  required property string screenName
  property bool blocked:false
  property var sourceItem:null
  property var sourceGroup:null
  property string sourceKind:""
  property var sourceRect:({x:0,y:0,width:0,height:0})
  property var avoidRect:null
  property bool sourceHovered:false
  property string selectedId:""
  property bool opened:false
  property int createdTiles:0
  property int wheelEvents:0
  property real wheelDelta:0
  property real reveal:opened ? 1 : 0
  readonly property string mode:config.hoverPreview || "off"
  readonly property bool previewEnabled:mode!=="off"
  readonly property string animations:config.animations || "full"
  readonly property string animationSpeed:config.animationSpeed || "normal"
  readonly property bool hovered:cardHover.hovered
  readonly property bool fromFloating:sourceKind==="floating"
  readonly property real cornerRadius:Math.min(Style.cornerRadius,layout.inset*2,width/2,height/2)
  readonly property var records:sourceGroup ? sourceGroup.windows.map(function(w) {
    return stash.snapshot.windows.find(function(live) { return live.id===w.id })
  }).filter(function(w) { return !!w }) : []
  readonly property var record:records.find(function(w) { return w.id===selectedId }) || records[0] || null
  readonly property int index:record ? records.findIndex(function(w) { return w.id===record.id }) : -1
  readonly property var layout:PreviewModel.previewLayout(sourceRect,area,config.previewSize || "medium",
    config.previewTitles!=="hidden",records.length,config.previewPlacement || "auto",8,avoidRect)
  readonly property string rowLayoutKey:JSON.stringify([layout.cardWidth,layout.cardHeight,layout.gap,layout.viewportWidth,layout.contentWidth])
  onRowLayoutKeyChanged:reflowDelay.restart()
  readonly property var popupColors:Commons.Color.popups
  readonly property var fonts:Style.font
  readonly property bool pending:showDelay.running
  signal inputChanged()
  signal restoring()
  x:layout.x; y:layout.y; width:layout.width; height:layout.height
  z:100000
  visible:reveal>0 && records.length>0 && !pending
  enabled:opened
  opacity:reveal
  clip:true
  onXChanged:inputChanged()
  onYChanged:inputChanged()
  onWidthChanged:inputChanged()
  onHeightChanged:inputChanged()
  onRevealChanged: {
    inputChanged()
    // An outgoing fade can finish while the next icon waits for its delay.
    if (!opened && reveal===0 && !pending) { sourceGroup=null; selectedId="" }
  }
  onBlockedChanged:if (blocked) dismiss(true)
  onModeChanged:if (!previewEnabled) dismiss(true)
  onHoveredChanged: { if (hovered) hideDelay.stop(); else scheduleHide() }
  onRecordsChanged: {
    if (sourceGroup && !records.length) dismiss(true)
    else if (records.length && !records.some(function(w) { return w.id===selectedId })) selectedId=records[0].id
  }
  onOpenedChanged: { inputChanged(); if (!opened) wheelScroll.stop() }
  Behavior on reveal { NumberAnimation { id:revealAnimation; duration:Motion.duration(preview.animations,150,100,preview.animationSpeed); easing.type:Easing.OutCubic } }
  onAnimationsChanged:if (animations==="off") revealAnimation.complete()

  function usable() {
    if (!previewEnabled || blocked || !sourceItem || !sourceItem.visible || !sourceItem.enabled || !records.length) return false
    if (sourceItem.previewReady===false || stash.groupClosing(sourceGroup)) return false
    return sourceKind==="picker" ? stash.dialogKind==="picker" && stash.dialogScreen===screenName : stash.dialogKind===""
  }
  function syncSource() {
    if (!sourceItem || !sourceGroup) return
    var group=sourceKind==="picker" ? {key:"window:"+sourceItem.windowData.id,windows:[sourceItem.windowData]}
      : sourceItem.group
    if (!group || group.key!==sourceGroup.key) { dismiss(true); return }
    sourceGroup=Object.assign({},group,{windows:group.windows.slice()})
  }
  function request(group,item,value,kind,avoid) {
    if (!value) {
      if (sourceItem===item) { sourceHovered=false; scheduleHide() }
      return
    }
    if (!previewEnabled || blocked || !group || !group.windows.length || !item) return
    if (sourceItem===item && sourceGroup && sourceGroup.key===group.key) {
      sourceGroup=Object.assign({},group,{windows:group.windows.slice()})
      sourceHovered=true; hideDelay.stop()
      return
    }
    dismiss(true)
    strip.contentX=0
    sourceGroup=Object.assign({},group,{windows:group.windows.slice()})
    selectedId=group.windows[0].id; sourceItem=item; sourceKind=kind
    var point=item.mapToItem(coordinateRoot,0,0)
    sourceRect={x:point.x,y:point.y,width:item.width,height:item.height}
    avoidRect=avoid || sourceRect; sourceHovered=true
    if (usable()) showDelay.restart()
    else dismiss(true)
  }
  function dismiss(immediate) {
    showDelay.stop(); hideDelay.stop(); opened=false; sourceHovered=false; sourceItem=null
    if (immediate) revealAnimation.complete()
    if (reveal===0) { sourceGroup=null; selectedId="" }
  }
  function scheduleHide() { if (!sourceHovered && !hovered && (opened || showDelay.running)) hideDelay.restart() }
  function containsPoint(x,y) { return opened && PreviewModel.contains({x:preview.x,y:preview.y,width:width,height:height},x,y,cornerRadius) }
  function windowById(id) { return records.find(function(w) { return w.id===id }) || null }
  function restore(id) {
    if (!windowById(id)) return
    restoring(); dismiss(false); stash.restorePreviewWindow(id,screenName)
  }
  function closeWindow(id) {
    var window=windowById(id)
    if (!window) return
    dismiss(false); stash.closeContext(); stash.closeDialog(); stash.closeWindows([window],screenName)
  }
  function context(id,x,y) {
    var window=windowById(id)
    if (!window) return
    dismiss(true)
    stash.openContext({key:"window:"+window.id,app:window.app,title:window.title,windows:[window]},screenName,Qt.point(x,y))
  }
  function rectOf(item) {
    var p=item.mapToItem(coordinateRoot,0,0)
    return {x:p.x,y:p.y,width:item.width,height:item.height}
  }
  function details() {
    var tiles=[],selected=null
    for (var i=0;i<tileRepeater.count;i++) {
      var tile=tileRepeater.itemAt(i) as PreviewTile
      if (!tile) continue
      var item=tile.details()
      tiles.push(item)
      if (item.recordId===selectedId) selected=item
    }
    selected=selected || tiles[0] || null
    var image=selected ? selected.image : {hasContent:false,captureActive:false,live:false,recordId:"",sourceSize:{width:0,height:0},
      fadeDuration:Motion.duration(animations,140,90,animationSpeed),animationSpeed:animationSpeed,status:"unavailable"}
    image.rect=selected ? selected.imageRect : {x:x,y:y,width:0,height:0}
    return {animationSpeed:animationSpeed,fadeDuration:revealAnimation.duration,enabled:previewEnabled,opened:opened,rendered:visible,pending:pending,progress:reveal,
      hovered:hovered,sourceHovered:sourceHovered,groupKey:sourceGroup ? sourceGroup.key : "",recordId:record ? record.id : "",
      index:index,count:records.length,rect:{x:x,y:y,width:width,height:height},side:layout.side,sourceRect:sourceRect,
      image:image,imageRect:image.rect,tiles:tiles,createdTiles:createdTiles,viewportRect:rectOf(strip),contentX:strip.contentX,
      contentWidth:strip.contentWidth,overflow:layout.overflow,
      scrolling:{events:wheelEvents,delta:wheelDelta,target:wheelScroll.to,running:wheelScroll.running,dragging:strip.dragging,flicking:strip.flicking}}
  }
  Timer {
    id:showDelay
    interval:preview.config.previewDelay===undefined ? 400 : preview.config.previewDelay
    onTriggered:if (preview.sourceHovered && preview.usable()) {
      preview.stash.dismissPreviews(preview.screenName); preview.opened=true
    } else preview.dismiss(true)
  }
  Timer {
    id:hideDelay
    interval:preview.config.previewHideDelay===undefined ? 200 : preview.config.previewHideDelay
    onTriggered:if (!preview.sourceHovered && !preview.hovered) preview.dismiss(false)
  }
  Timer {
    interval:60; repeat:true; running:preview.opened || showDelay.running
    onTriggered: {
      if (!preview.usable()) { preview.dismiss(true); return }
      var p=preview.sourceItem.mapToItem(preview.coordinateRoot,0,0)
      if (Math.abs(p.x-preview.sourceRect.x)>1 || Math.abs(p.y-preview.sourceRect.y)>1) preview.dismiss(true)
    }
  }
  Connections {
    target:preview.stash
    function onPointerClicked(x,y) {
      var monitor=preview.stash.screenMonitor(preview.screenName)
      if (!monitor || !preview.opened) return
      x-=monitor.x; y-=monitor.y
      if (!preview.containsPoint(x,y) && !PreviewModel.contains(preview.sourceRect,x,y)) preview.dismiss(true)
    }
    function onDialogKindChanged() { if (!preview.usable()) preview.dismiss(true) }
    function onContextOpenChanged() { if (preview.stash.contextOpen) preview.dismiss(true) }
    function onPendingCloseIdsChanged() { if (preview.stash.groupClosing(preview.sourceGroup)) preview.dismiss(true) }
  }
  Connections {
    target:preview.sourceItem
    ignoreUnknownSignals:true
    function onGroupChanged() { preview.syncSource() }
    function onWindowDataChanged() { preview.syncSource() }
  }
  HoverHandler { id:cardHover }
  Ui.BorderSurface {
    anchors.fill:parent
    radius:preview.cornerRadius
    color:preview.popupColors.background
    borderSpec:Border.surfaceSpec("popups","border",preview.popupColors.border,Style.normalBorderWidth)
  }
  // Keep delegates keyed across metadata refreshes so Still frames stay put.
  StashCollection {
    id:tileModel
    sourceGroups:preview.records.map(function(w) { return {key:w.id,window:w} })
    animations:"off"
  }
  Timer {
    id:reflowDelay; interval:0
    onTriggered: {
      wheelScroll.stop()
      strip.contentX=Math.max(0,Math.min(strip.contentX,strip.contentWidth-strip.width))
    }
  }
  component PreviewTile:Item {
    id:tile
    Component.onCompleted:preview.createdTiles++
    required property string groupKey
    required property bool retiring
    readonly property var windowData:(tileModel.dataByKey[groupKey] || {}).window || null
    readonly property int ordinal:tileModel.keys.indexOf(groupKey)
    readonly property bool inViewport:x+width>strip.contentX+.01 && x<strip.contentX+strip.width-.01
    x:ordinal*(preview.layout.cardWidth+preview.layout.gap)
    width:preview.layout.cardWidth; height:preview.layout.cardHeight
    function details() {
      return {recordId:groupKey,rect:preview.rectOf(tile),imageRect:preview.rectOf(thumbnail),closeRect:preview.rectOf(closeButton),
        closeVisible:preview.visible && closeButton.visible,visible:preview.visible && inViewport,image:thumbnail.details()}
    }
    HoverHandler {
      id:tileHover
      onHoveredChanged:if (hovered && preview.opened) preview.selectedId=tile.groupKey
    }
    Ui.BorderSurface {
      anchors.fill:parent
      radius:Math.min(Style.cornerRadius,8)
      color:tileHover.hovered ? Style.hoverFillFor(preview.popupColors.text,Commons.Color.accent) : "transparent"
      borderSpec:Border.none()
      Behavior on color { ColorAnimation { duration:Motion.duration(preview.animations,130,90,preview.animationSpeed) } }
    }
    Text {
      x:4; y:0
      width:Math.max(0,parent.width-closeButton.width-12); height:preview.layout.headerHeight
      visible:height>0
      text:tile.windowData ? tile.windowData.title : ""
      textFormat:Text.PlainText
      color:preview.popupColors.text
      font.family:preview.fonts.family; font.pixelSize:preview.fonts.bodySmall
      verticalAlignment:Text.AlignVCenter; elide:Text.ElideRight
    }
    StashPreviewImage {
      id:thumbnail
      x:0; y:preview.layout.headerHeight
      width:preview.layout.imageWidth; height:preview.layout.imageHeight
      record:tile.windowData
      mode:preview.opened ? preview.mode : "still"
      active:preview.visible && tile.inViewport
      animations:preview.animations; animationSpeed:preview.animationSpeed
    }
    MouseArea {
      anchors.fill:parent
      acceptedButtons:Qt.LeftButton | Qt.MiddleButton | Qt.RightButton
      cursorShape:Qt.PointingHandCursor
      onClicked:function(mouse) {
        if (mouse.button===Qt.MiddleButton) preview.closeWindow(tile.groupKey)
        else if (mouse.button===Qt.RightButton) {
          const p=mapToItem(preview.coordinateRoot,mouse.x,mouse.y)
          preview.context(tile.groupKey,p.x,p.y)
        } else preview.restore(tile.groupKey)
      }
    }
    StashActionButton {
      id:closeButton
      visible:preview.layout.headerHeight>0 && size>0
      x:parent.width-width-2
      y:(preview.layout.headerHeight-height)/2
      size:Math.max(0,Math.min(24,parent.width-4,preview.layout.headerHeight-4))
      fontSize:Math.max(1,Math.min(preview.fonts.icon,size-4))
      iconText:"×"; tooltipText:"Close window"
      foreground:preview.popupColors.text
      animations:preview.animations; animationSpeed:preview.animationSpeed
      onClicked:preview.closeWindow(tile.groupKey)
    }
  }
  Flickable {
    id:strip
    x:preview.layout.inset; y:preview.layout.inset
    width:preview.layout.viewportWidth; height:preview.layout.cardHeight
    contentWidth:preview.layout.contentWidth; contentHeight:height
    flickableDirection:Flickable.HorizontalFlick
    boundsBehavior:Flickable.StopAtBounds
    interactive:preview.layout.overflow
    clip:true
    onDraggingChanged:if (dragging) wheelScroll.stop()
    Repeater {
      id:tileRepeater
      model:tileModel
      delegate:PreviewTile {}
    }
  }
  // Wheel-only overlay leaves all button presses and drags to the tiles.
  MouseArea {
    x:strip.x; y:strip.y; width:strip.width; height:strip.height
    acceptedButtons:Qt.NoButton
    enabled:preview.opened && preview.layout.overflow
    onWheel:function(event) {
      preview.wheelEvents++
      var delta=event.pixelDelta.x || event.pixelDelta.y
      if (!delta) delta=(event.angleDelta.x || event.angleDelta.y)/2
      preview.wheelDelta=delta
      if (delta) {
        strip.cancelFlick()
        var destination=Math.max(0,Math.min(strip.contentWidth-strip.width,(wheelScroll.running ? wheelScroll.to : strip.contentX)-delta))
        wheelScroll.stop(); wheelScroll.from=strip.contentX; wheelScroll.to=destination; wheelScroll.restart()
      }
      event.accepted=true
    }
  }
  NumberAnimation {
    id:wheelScroll
    target:strip; property:"contentX"
    duration:Motion.move(preview.animations,preview.animationSpeed); easing.type:Easing.OutCubic
  }
  Rectangle {
    visible:preview.layout.overflow
    height:Math.min(2,preview.layout.inset/2)
    width:Math.min(strip.width,Math.max(16,strip.width*strip.width/Math.max(1,strip.contentWidth)))
    x:strip.x+(strip.width-width)*strip.contentX/Math.max(1,strip.contentWidth-strip.width)
    y:preview.height-(preview.layout.inset+height)/2
    radius:height/2
    color:preview.popupColors.text
    opacity:.45
  }
}
