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
  property real stackLagX:0
  property real stackLagY:0
  property bool stackSettling:false
  property real destinationX:0
  property real destinationY:0
  property bool slotVisible:true
  property bool expanded:false
  property bool retiring:false
  property bool frameVisible:true
  property string iconShape:"auto"
  property string animations:"full"
  property string animationSpeed:"normal"
  property bool previewEnabled:false
  readonly property bool previewReady:interactive && !moving && !stackSettling
  onPreviewReadyChanged:if (previewEnabled && graphic.pointerHovered) hovered(previewReady)
  property string unfoldStyle:"arc"
  readonly property var timing:Motion.fanProfile(unfoldStyle)
  readonly property bool chainStyle:Motion.chain(unfoldStyle)
  readonly property bool sharedMotion:chainStyle && Motion.full(animations)
  property real sharedProgress:0
  property bool sharedMoving:false
  property int chainCount:1
  property int firstIndex:0
  property real idleOpacity:1
  property real globalPresence:1
  property bool hasCursor:false
  property bool externalPressed:false
  property real progress:0
  property real remainingFactor:1
  property bool retiming:false
  property int motionFrames:0
  property real maxBend:0
  property real maxTilt:0
  property real minScale:1
  property real peakProgress:0
  property bool ready:false
  property real pageWeight:slotVisible ? 1 : 0
  readonly property alias icon:graphic
  readonly property real stretchX:jumpStretch.xScale
  readonly property real stretchY:jumpStretch.yScale
  readonly property bool moving:(sharedMotion && sharedMoving) || spread.running || destinationXAnimation.running || destinationYAnimation.running || pageFade.running
  readonly property real visualProgress:sharedMotion ? sharedProgress : progress
  readonly property real spatialProgress:Motion.full(animations) ? visualProgress : expanded ? 1 : 0
  readonly property var basePose:chainStyle
    ? Model.fanChainPose(stackX,stackY,destinationX,destinationY,spatialProgress,ordinal,geometry,area,unfoldStyle,firstIndex,chainCount)
    : Model.fanPose(stackX,stackY,destinationX,destinationY,spatialProgress,ordinal,geometry,area,unfoldStyle)
  // The followers keep settling toward the frozen lead during fan motion.
  // Shared groups converge by the first landing; reversing never resurrects
  // an old, latched drag offset.
  readonly property real lagWeight:Math.max(0,1-Math.max(0,Math.min(1,spatialProgress))*(chainStyle ? Math.max(1,chainCount-1) : 1))
  readonly property var pose:ordinal===0 || (!stackLagX && !stackLagY) || lagWeight===0 ? basePose
    : Object.assign({},basePose,{x:Math.max(area.x,Math.min(area.x+area.width-geometry.size,basePose.x+stackLagX*lagWeight)),
      y:Math.max(area.y,Math.min(area.y+area.height-geometry.size,basePose.y+stackLagY*lagWeight))})
  readonly property real stackWeight:ordinal<3 ? 1 : 0
  readonly property real drawWeight:sharedMotion ? (sharedProgress>0 ? pageWeight : stackWeight)
    : Math.max(0,Math.min(1,stackWeight+(pageWeight-stackWeight)*progress))
  readonly property bool interactive:expanded && slotVisible && !retiring && (ordinal===0 || (sharedMotion ? pose.settled : progress>.85))
  x:pose.x; y:pose.y
  width:geometry.size; height:width
  z:10000-ordinal
  opacity:drawWeight*globalPresence
  scale:Motion.full(animations) ? pose.scale : 1
  rotation:Motion.full(animations) ? pose.tilt : 0
  visible:drawWeight>0 || moving
  signal activated()
  signal closeRequested()
  signal contextRequested(real x,real y)
  signal hovered(bool value)
  signal pointerPressed()
  signal inputChanged()
  signal exited(int frames)
  onXChanged:inputChanged()
  onYChanged:inputChanged()
  onInteractiveChanged:inputChanged()
  onMovingChanged:inputChanged()
  onPoseChanged:if (spatialProgress>0 && spatialProgress<1) { maxBend=Math.max(maxBend,pose.bend); maxTilt=Math.max(maxTilt,Math.abs(pose.tilt)); minScale=Math.min(minScale,pose.scale) }
  onVisualProgressChanged: { peakProgress=Math.max(peakProgress,visualProgress); if (visualProgress>0 && visualProgress<1) motionFrames++ }
  Behavior on destinationX { enabled:actor.ready && (actor.expanded || actor.spatialProgress>0)
    NumberAnimation { id:destinationXAnimation; duration:Motion.move(actor.animations,actor.animationSpeed); easing.type:Easing.OutCubic } }
  Behavior on destinationY { enabled:actor.ready && (actor.expanded || actor.spatialProgress>0)
    NumberAnimation { id:destinationYAnimation; duration:Motion.move(actor.animations,actor.animationSpeed); easing.type:Easing.OutCubic } }
  Behavior on pageWeight { enabled:actor.ready && (actor.expanded || actor.spatialProgress>0); NumberAnimation { id:pageFade; duration:Motion.duration(actor.animations,160,90,actor.animationSpeed); easing.type:Easing.OutCubic } }
  function retarget(changeSpeed) {
    spread.stop()
    retiming=!!changeSpeed
    remainingFactor=changeSpeed ? Math.min(1,Math.abs(progress-(expanded ? 1 : 0))) : 1
    if (!ready) return
    if (sharedMotion) { progress=expanded ? 1 : 0; return }
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
  onAnimationSpeedChanged:retarget(true)
  SequentialAnimation {
    id:spread
    PauseAnimation { duration:actor.retiming ? 0 : Motion.duration(actor.animations,Motion.fanDelay(actor.timing,actor.ordinal,actor.expanded,actor.geometry.capacity),0,actor.animationSpeed) }
    NumberAnimation {
      target:actor; property:"progress"; to:actor.expanded ? 1 : 0
      duration:Math.round(Motion.duration(actor.animations,actor.expanded ? actor.timing.open : actor.timing.close,100,actor.animationSpeed)*actor.remainingFactor)
      easing.type:actor.timing.easing==="linear" ? Easing.Linear : !actor.expanded ? Easing.InOutCubic : actor.timing.easing==="back" ? Easing.OutBack : actor.timing.easing==="quint" ? Easing.OutQuint : Easing.OutCubic
      easing.overshoot:actor.timing.overshoot
    }
  }
  StashAnimatedIcon {
    id:graphic
    width:actor.width; height:actor.height
    transform:Scale {
      id:jumpStretch
      origin.x:actor.geometry.horizontal ? graphic.width/2 : actor.geometry.hopSign<0 ? graphic.width : 0
      origin.y:actor.geometry.horizontal ? graphic.height : graphic.height/2
      xScale:Motion.full(actor.animations) && actor.pose.stretchX!==undefined ? actor.pose.stretchX : 1
      yScale:Motion.full(actor.animations) && actor.pose.stretchY!==undefined ? actor.pose.stretchY : 1
    }
    group:actor.displayGroup
    animations:actor.animations; animationSpeed:actor.animationSpeed
    previewEnabled:actor.previewEnabled
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
    onCloseRequested:actor.closeRequested()
    onContextRequested:function(x,y) { actor.contextRequested(x,y) }
    onHovered:function(value) { actor.hovered(value) }
    onPointerPressed:actor.pointerPressed()
    onExited:function(frames) { actor.exited(frames) }
  }
  Component.onCompleted: { ready=true; retarget() }
}
