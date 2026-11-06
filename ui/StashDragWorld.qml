pragma ComponentBehavior: Bound
import QtQuick
import "DragPhysics.js" as Physics
import "Motion.js" as Motion

// Owns all floating item positions on one monitor. Delegates react to moved;
// they must not place competing Behaviors on the same x/y properties.
Item {
  id:world
  property var area:({x:0,y:0,width:1920,height:1080})
  property bool physicsEnabled:true
  property string animations:"full"
  property string animationSpeed:"normal"
  property bool snapEdges:true
  property bool active:false
  property int revision:0
  property var simulation:Physics.create({})
  signal moved(string key,real x,real y)
  signal settled(string key,real x,real y)
  signal activityChanged(string key,bool held,bool moving)
  function flush() {
    var events=Physics.drain(simulation)
    active=Physics.active(simulation)
    if (events.moved.length || events.activities.length || events.settled.length) revision++
    events.moved.forEach(function(p) { world.moved(p.key,p.x,p.y) })
    events.activities.forEach(function(p) { world.activityChanged(p.key,p.held,p.moving) })
    events.settled.forEach(function(p) { world.settled(p.key,p.x,p.y) })
  }
  function configure() { simulation.animationScale=1/Motion.speedRatio(animationSpeed);Physics.configure(simulation,area,snapEdges,physicsEnabled,animations);flush() }
  function availablePosition(key,x,y,width,height) {
    return Physics.destination(simulation,{key:key,width:width,height:height},x,y,"")
  }
  function add(key,x,y,width,height) { configure();Physics.add(simulation,key,x,y,width,height);flush() }
  function remove(key) { Physics.remove(simulation,key);flush() }
  function sync(key,x,y,width,height) { configure();Physics.sync(simulation,key,x,y,width,height);flush() }
  function press(key) { configure();Physics.press(simulation,key,Date.now()/1000);flush() }
  function drag(key,x,y) { Physics.drag(simulation,key,x,y,Date.now()/1000);flush() }
  function release(key) { Physics.release(simulation,key,Date.now()/1000);flush() }
  function cancel(key,settle) { Physics.cancel(simulation,key,settle===undefined ? true : settle);flush() }
  function freeze(key,value) { Physics.freeze(simulation,key,value);flush() }
  function body(key) { return Physics.view(simulation,key) }
  function details() { return Physics.details(simulation) }
  onAreaChanged:configUpdate.restart()
  onPhysicsEnabledChanged:configUpdate.restart()
  onAnimationsChanged:configUpdate.restart()
  onAnimationSpeedChanged:if (simulation) simulation.animationScale=1/Motion.speedRatio(animationSpeed)
  onSnapEdgesChanged:configUpdate.restart()
  Timer { id:configUpdate; interval:0; onTriggered:world.configure() }
  FrameAnimation {
    running:world.active
    onTriggered: { Physics.step(world.simulation,frameTime);world.flush() }
  }
  Component.onCompleted:configure()
}
