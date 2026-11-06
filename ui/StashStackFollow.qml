pragma ComponentBehavior: Bound
import QtQuick
import "StackFollow.js" as Follow
import "Motion.js" as Motion

// Decorative followers have no drag-world bodies or persistent positions.
// Their clock must never freeze or retime the lead body's actual momentum.
Item {
  id:follow
  property real leadX:0
  property real leadY:0
  property int count:0
  property real size:48
  property var area:({x:0,y:0,width:1920,height:1080})
  property bool eligible:false
  property bool driving:false
  property string animationSpeed:"normal"
  property string identity:""
  property bool active:false
  property bool tracking:false
  property var simulation:Follow.create()
  property var positions:[]
  property int frames:0
  signal updated()

  function configure() {
    if (!eligible || count<2) tracking=false
    else if (driving) tracking=true
    Follow.sync(simulation,leadX,leadY,Math.min(3,count),area,size,eligible && tracking,Motion.speedRatio(animationSpeed))
  }
  function publish() {
    var moving=Follow.active(simulation)
    if (!driving && !moving && tracking) {
      tracking=false
      Follow.sync(simulation,leadX,leadY,Math.min(3,count),area,size,false,Motion.speedRatio(animationSpeed))
    }
    var next=[Follow.pose(simulation,0),Follow.pose(simulation,1),Follow.pose(simulation,2)]
    var changed=moving!==active || JSON.stringify(next)!==JSON.stringify(positions)
    active=moving
    if (changed) { positions=next; updated() }
  }
  function sync() { configure(); publish() }
  function reset() {
    configure(); Follow.reset(simulation); publish()
  }
  function pose(ordinal) {
    var index=Math.max(0,Math.min(2,ordinal))
    if (index===0) return {x:leadX,y:leadY}
    if (!tracking && !active) return {x:leadX,y:leadY+index*4}
    return positions[index] || {x:leadX,y:leadY+index*4}
  }
  function details() {
    return {active:active,tracking:tracking,eligible:eligible,driving:driving,speed:animationSpeed,frames:frames,
      positions:[pose(0),pose(1),pose(2)]}
  }
  // Coalesce the lead's x/y notifications into one target sample. Press and
  // policy changes initialize immediately, before the first pointer movement.
  onLeadXChanged:syncDelay.restart()
  onLeadYChanged:syncDelay.restart()
  onCountChanged:sync()
  onAreaChanged:sync()
  onSizeChanged:sync()
  onEligibleChanged:sync()
  onDrivingChanged:sync()
  onAnimationSpeedChanged:sync()
  onIdentityChanged:reset()
  Timer { id:syncDelay; interval:0; onTriggered:follow.sync() }
  FrameAnimation {
    running:follow.eligible && follow.count>1 && follow.tracking && (follow.driving || follow.active)
    onTriggered: {
      follow.configure()
      Follow.step(follow.simulation,frameTime)
      follow.frames++
      follow.publish()
    }
  }
  Component.onCompleted:sync()
}
