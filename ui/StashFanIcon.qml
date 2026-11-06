pragma ComponentBehavior: Bound
import QtQuick
import "Model.js" as Model
import "Motion.js" as Motion

Item {
  id:actor
  required property var group
  property var displayGroup:group
  required property var geometry
  required property var area
  property int ordinal:0
  property real stackX:0
  property real stackY:0
  property real destinationX:0
  property real destinationY:0
  property bool slotVisible:true
  property bool expanded:false
  property bool retiring:false
  property bool frameVisible:true
  property string iconShape:"auto"
  property string animations:"full"
  property string unfoldStyle:"arc"
  readonly property var timing:Motion.fanProfile(unfoldStyle)
  property real idleOpacity:1
  property real globalPresence:1
  property bool hasCursor:false
  property bool externalPressed:false
  property real progress:0
  property int motionFrames:0
  property real maxBend:0
  property real maxTilt:0
  property real minScale:1
  property real peakProgress:0
  property bool ready:false
  property real pageWeight:slotVisible ? 1 : 0
  readonly property alias icon:graphic
  readonly property bool moving:spread.running || destinationXAnimation.running || destinationYAnimation.running || pageFade.running
  readonly property real spatialProgress:Motion.full(animations) ? progress : expanded ? 1 : 0
  readonly property var pose:Model.fanPose(stackX,stackY,destinationX,destinationY,spatialProgress,ordinal,geometry,area,unfoldStyle)
  readonly property real stackWeight:ordinal<3 ? 1 : 0
  readonly property real drawWeight:Math.max(0,Math.min(1,stackWeight+(pageWeight-stackWeight)*progress))
  readonly property bool interactive:expanded && slotVisible && !retiring && (ordinal===0 || progress>.85)
  x:pose.x; y:pose.y
  width:geometry.size; height:width
  z:10000-ordinal
  opacity:drawWeight*globalPresence
  scale:Motion.full(animations) ? pose.scale : 1
  rotation:Motion.full(animations) ? pose.tilt : 0
  visible:drawWeight>0 || moving
  signal activated()
  signal contextRequested(real x,real y)
  signal hovered(bool value)
  signal inputChanged()
  signal exited(int frames)
  onXChanged:inputChanged()
  onYChanged:inputChanged()
  onInteractiveChanged:inputChanged()
  onMovingChanged:inputChanged()
  onPoseChanged:if (progress>0 && progress<1) { maxBend=Math.max(maxBend,pose.bend); maxTilt=Math.max(maxTilt,Math.abs(pose.tilt)); minScale=Math.min(minScale,pose.scale) }
  onProgressChanged: { peakProgress=Math.max(peakProgress,progress); if (progress>0 && progress<1) motionFrames++ }
  Behavior on destinationX { enabled:actor.ready && (actor.expanded || actor.progress>0)
    NumberAnimation { id:destinationXAnimation; duration:Motion.move(actor.animations); easing.type:Easing.OutCubic } }
  Behavior on destinationY { enabled:actor.ready && (actor.expanded || actor.progress>0)
    NumberAnimation { id:destinationYAnimation; duration:Motion.move(actor.animations); easing.type:Easing.OutCubic } }
  Behavior on pageWeight { enabled:actor.ready && (actor.expanded || actor.progress>0); NumberAnimation { id:pageFade; duration:Motion.duration(actor.animations,160,90); easing.type:Easing.OutCubic } }
  function retarget() {
    spread.stop()
    if (!ready) return
    if (Math.abs(progress-(expanded ? 1 : 0))<.000001) { progress=expanded ? 1 : 0; return }
    if (animations==="off") { progress=expanded ? 1 : 0; return }
    spread.restart()
  }
  onExpandedChanged: { motionFrames=0; maxBend=0; maxTilt=0; minScale=1; peakProgress=0; if (!expanded) pageFade.complete(); retarget() }
  onAnimationsChanged: {
    if (!Motion.full(animations)) { destinationXAnimation.complete(); destinationYAnimation.complete() }
    if (animations==="off") pageFade.complete()
    retarget()
  }
  SequentialAnimation {
    id:spread
    PauseAnimation { duration:Motion.full(actor.animations) ? Motion.fanDelay(actor.timing,actor.ordinal,actor.expanded,actor.geometry.capacity) : 0 }
    NumberAnimation {
      target:actor; property:"progress"; to:actor.expanded ? 1 : 0
      duration:Motion.duration(actor.animations,actor.expanded ? actor.timing.open : actor.timing.close,100)
      easing.type:!actor.expanded ? Easing.InOutCubic : actor.timing.easing==="back" ? Easing.OutBack : actor.timing.easing==="quint" ? Easing.OutQuint : Easing.OutCubic
      easing.overshoot:actor.timing.overshoot
    }
  }
  StashAnimatedIcon {
    id:graphic
    width:actor.width; height:actor.height
    group:actor.displayGroup
    animations:actor.animations
    idleOpacity:actor.idleOpacity
    retiring:actor.retiring
    bubble:true
    draggable:false
    frameVisible:actor.frameVisible
    iconShape:actor.iconShape
    cursorManaged:true
    hasCursor:actor.hasCursor
    externalPressed:actor.externalPressed
    enabled:actor.interactive
    onActivated:actor.activated()
    onContextRequested:function(x,y) { actor.contextRequested(x,y) }
    onHovered:function(value) { actor.hovered(value) }
    onExited:function(frames) { actor.exited(frames) }
  }
  Component.onCompleted: { ready=true; retarget() }
}
