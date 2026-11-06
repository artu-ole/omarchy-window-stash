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
  readonly property var popupColors:Commons.Color.popups
  readonly property var fonts:Style.font
  readonly property bool pending:showDelay.running
  signal inputChanged()
  signal restoring()
  x:layout.x; y:layout.y; width:layout.width; height:layout.height
  z:100000
  visible:reveal>0 && records.length>0
  enabled:opened
  opacity:reveal
  clip:true
  onXChanged:inputChanged()
  onYChanged:inputChanged()
  onWidthChanged:inputChanged()
  onHeightChanged:inputChanged()
  onOpenedChanged:inputChanged()
  onRevealChanged: {
    inputChanged()
    if (!opened && reveal===0) { sourceGroup=null; selectedId="" }
  }
  onBlockedChanged:if (blocked) dismiss(true)
  onModeChanged:if (!previewEnabled) dismiss(true)
  onHoveredChanged: { if (hovered) hideDelay.stop(); else scheduleHide() }
  onRecordsChanged: {
    if (sourceGroup && !records.length) dismiss(true)
    else if (records.length && !records.some(function(w) { return w.id===selectedId })) selectedId=records[0].id
  }
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
  function choose(delta) {
    if (!opened || records.length<2) return
    selectedId=records[(index+delta+records.length)%records.length].id
  }
  function restore() {
    if (!record) return
    var id=record.id
    restoring(); dismiss(false); stash.restorePreviewWindow(id,screenName)
  }
  function closeWindow() {
    if (!record) return
    var window=record
    dismiss(false); stash.closeContext(); stash.closeDialog(); stash.closeWindows([window],screenName)
  }
  function context(x,y) {
    if (!record) return
    var window=record
    dismiss(true)
    stash.openContext({key:"window:"+window.id,app:window.app,title:window.title,windows:[window]},screenName,Qt.point(x,y))
  }
  function all() {
    var group=sourceGroup,windows=records.slice()
    dismiss(true); stash.openDialog("picker",screenName,windows,group)
  }
  function rectOf(item) {
    var p=item.mapToItem(coordinateRoot,0,0)
    return {x:p.x,y:p.y,width:item.width,height:item.height}
  }
  function details() {
    var image=thumbnail.details()
    image.rect=rectOf(thumbnail)
    return {animationSpeed:animationSpeed,fadeDuration:revealAnimation.duration,enabled:previewEnabled,opened:opened,rendered:visible,pending:pending,progress:reveal,
      hovered:hovered,sourceHovered:sourceHovered,groupKey:sourceGroup ? sourceGroup.key : "",recordId:record ? record.id : "",
      index:index,count:records.length,rect:{x:x,y:y,width:width,height:height},side:layout.side,sourceRect:sourceRect,
      image:image,imageRect:image.rect,previousRect:rectOf(previous),nextRect:rectOf(next),moreRect:rectOf(more)}
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
  Text {
    x:preview.layout.inset; y:preview.layout.inset
    width:preview.layout.imageWidth; height:preview.layout.headerHeight
    visible:height>0
    text:preview.record ? preview.record.title : ""
    textFormat:Text.PlainText
    color:preview.popupColors.text
    font.family:preview.fonts.family; font.pixelSize:preview.fonts.bodySmall
    verticalAlignment:Text.AlignVCenter; elide:Text.ElideRight
  }
  StashPreviewImage {
    id:thumbnail
    x:preview.layout.inset; y:preview.layout.inset+preview.layout.headerHeight
    width:preview.layout.imageWidth; height:preview.layout.imageHeight
    record:preview.record
    mode:preview.opened ? preview.mode : "still"
    active:preview.visible
    animations:preview.animations; animationSpeed:preview.animationSpeed
  }
  MouseArea {
    anchors.fill:parent
    acceptedButtons:Qt.LeftButton | Qt.MiddleButton | Qt.RightButton
    cursorShape:Qt.PointingHandCursor
    onClicked:function(mouse) {
      if (mouse.button===Qt.MiddleButton) preview.closeWindow()
      else if (mouse.button===Qt.RightButton) { const p=mapToItem(preview.coordinateRoot,mouse.x,mouse.y); preview.context(p.x,p.y) }
      else preview.restore()
    }
  }
  WheelHandler {
    enabled:preview.opened && preview.records.length>1
    target:null
    onWheel:function(event) {
      var delta=event.angleDelta.y || event.angleDelta.x || event.pixelDelta.y || event.pixelDelta.x
      if (delta && !wheelGate.running) { preview.choose(delta>0 ? -1 : 1); wheelGate.restart() }
      event.accepted=true
    }
  }
  Timer { id:wheelGate; interval:120 }
  Item {
    id:footer
    visible:preview.records.length>1
    x:preview.layout.inset; y:thumbnail.y+thumbnail.height
    width:preview.layout.imageWidth; height:preview.layout.footerHeight
    StashActionButton {
      id:previous
      anchors.left:parent.left; anchors.verticalCenter:parent.verticalCenter
      size:Math.min(28,footer.height); iconText:"‹"; tooltipText:"Previous window"
      animations:preview.animations; animationSpeed:preview.animationSpeed; foreground:preview.popupColors.text
      onClicked:preview.choose(-1)
    }
    Text {
      anchors.left:previous.right; anchors.right:next.left; height:parent.height
      text:(preview.index+1)+" / "+preview.records.length
      color:preview.popupColors.text; font.family:preview.fonts.family; font.pixelSize:preview.fonts.caption
      horizontalAlignment:Text.AlignHCenter; verticalAlignment:Text.AlignVCenter; elide:Text.ElideRight
    }
    StashActionButton {
      id:next
      anchors.right:more.left; anchors.verticalCenter:parent.verticalCenter
      size:Math.min(28,footer.height); iconText:"›"; tooltipText:"Next window"
      animations:preview.animations; animationSpeed:preview.animationSpeed; foreground:preview.popupColors.text
      onClicked:preview.choose(1)
    }
    StashActionButton {
      id:more
      anchors.right:parent.right; anchors.verticalCenter:parent.verticalCenter
      size:Math.min(28,footer.height); iconText:"󰍉"; tooltipText:"All windows"
      animations:preview.animations; animationSpeed:preview.animationSpeed; foreground:preview.popupColors.text
      onClicked:preview.all()
    }
  }
}
