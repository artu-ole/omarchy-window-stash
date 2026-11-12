pragma ComponentBehavior: Bound
import QtQuick
import Quickshell
import qs.Commons
import qs.Commons as Commons
import qs.Ui as Ui
import "Motion.js" as Motion
import "FloatingPreviewModel.js" as Geometry

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
  property bool keyboardSelected:false
  property real maximumHeight:100000
  property real presence:0
  property var sourceSizes:({})
  readonly property var record:group && group.windows.length ? group.windows[0] : null
  readonly property var geometryRecord:Geometry.geometryRecord(record,sourceSizes)
  readonly property string key:"preview:"+(group ? group.key : "")
  readonly property string animations:config.animations || "full"
  readonly property string animationSpeed:config.animationSpeed || "normal"
  readonly property bool titleVisible:config.floatingPreviewTitles==="shown"
  readonly property bool frameVisible:config.floatingPreviewFrame==="shown"
  readonly property var popupColors:Commons.Color.popups
  readonly property var fonts:Style.font
  readonly property var desktop:DesktopEntries.heuristicLookup(record ? String(record.app || "") : "")
  readonly property var dimensions:Geometry.dimensions(width,geometryRecord,{x:0,y:0,width:Math.max(1,width),height:Math.max(1,maximumHeight)},titleVisible,frameVisible)
  readonly property bool hovered:hover.hovered || pointer.containsMouse
  readonly property bool live:(config.floatingPreviewUpdate || "hover")==="live" || ((config.floatingPreviewUpdate || "hover")==="hover" && hovered)
  readonly property bool canMove:interactive && movable && config.floatingPreviewLock!=="locked" && !retiring
  readonly property bool canResize:interactive && resizable && config.floatingPreviewSizing!=="preset" && config.floatingPreviewLock!=="locked" && !retiring
  readonly property Region inputRegion:Region { item:card; onChanged:card.inputChanged() }
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
  height:dimensions.height
  enabled:interactive && !retiring
  opacity:presence*feedback.visualOpacity
  scale:Motion.full(animations) ? .97+.03*presence : 1
  z:held || resizing ? 20 : hovered ? 10 : 0
  onXChanged:inputChanged()
  onYChanged:inputChanged()
  onWidthChanged:inputChanged()
  onHeightChanged:inputChanged()
  onPresenceChanged:inputChanged()
  onHeldChanged:if(!held) geometryReleased()
  onResizingChanged:if(!resizing) geometryReleased()
  onMovingChanged:if(!moving) geometryReleased()
  onRetiringChanged:presence=retiring ? 0 : 1
  onInteractiveChanged:if (!interactive) cancelInteraction()
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
  function observeSourceAspect() {
    if(!record || !thumbnail.active || !thumbnail.hasContent || !thumbnail.eligible) return
    var size=thumbnail.sourceSize
    if(Geometry.validSourceSize([size.width,size.height])) sourceAspectObserved(record.id,size.width,size.height)
  }
  function details() {
    var rect=rectOf(card),handles=[]
    var corners=["top-left","top-right","bottom-left","bottom-right"]
    for(var i=0;i<resizeRepeater.count;i++) {var handle=resizeRepeater.itemAt(i);if(handle) handles.push({corner:corners[i],rect:rectOf(handle),visible:handle.opacity>0,enabled:handle.enabled})}
    return {key:key,recordId:record ? record.id : "",rect:rect,x:rect.x,y:rect.y,width:width,height:height,
      imageRect:rectOf(thumbnail),resizeRect:handles.length ? handles[3].rect : null,resizeRects:handles,
      titleVisible:titleVisible,frameVisible:frameVisible,hovered:hovered,held:held,moving:moving,resizing:resizing,
      groupCount:group ? group.windows.length : 0,visible:visible,presence:presence,image:thumbnail.details(),
      locked:config.floatingPreviewLock==="locked",resizable:canResize,closeRect:rectOf(closeButton),closeVisible:closeButton.visible}
  }
  HoverHandler {id:hover}
  StashFeedback {
    id:feedback
    animations:card.animations;animationSpeed:card.animationSpeed
    idleOpacity:(card.config.iconOpacity===undefined ? 100 : card.config.iconOpacity)/100
    hot:card.hovered || card.held || card.resizing
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
    record:card.record;stash:card.stash
    mode:card.live ? "live" : "still"
    active:card.captureAllowed && card.visible && !card.retiring
    animations:card.animations;animationSpeed:card.animationSpeed
    onSourceSizeChanged:sourceObservation.restart()
    onHasContentChanged:sourceObservation.restart()
  }
  Timer {id:sourceObservation;interval:0;onTriggered:card.observeSourceAspect()}
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
      text:card.record ? card.record.title : "";textFormat:Text.PlainText
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
      if(mouse.button===Qt.MiddleButton) card.closeRequested()
      else if(mouse.button===Qt.RightButton) {var p=mapToItem(card.coordinateRoot,mouse.x,mouse.y);card.contextRequested(p.x,p.y)}
      else card.activated()
    }
    onWheel:function(event) {
      var delta=event.pixelDelta.y || event.pixelDelta.x || event.angleDelta.y || event.angleDelta.x
      card.scrolled(delta);event.accepted=true
    }
  }
  StashActionButton {
    id:closeButton
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
    visible:card.resizing || card.keyboardSelected
    color:"transparent";border.width:1;border.color:Commons.Color.accent
  }
  Item {
    id:resizeHandles
    anchors.fill:parent
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
  Component.onCompleted:presence=retiring ? 0 : 1
  Component.onDestruction:cancelInteraction()
}
