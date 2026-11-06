.pragma library

// The front icon belongs to the drag world. Only its two decorative followers
// are simulated here, so their catch-up never changes the pointer or momentum.
var STEP=1/240
var OMEGA=24
var OFFSET=4
var POSITION_EPSILON=.05
var VELOCITY_EPSILON=.5

function finite(value, fallback) {
  value=Number(value)
  return isFinite(value) ? value : fallback
}
function clamp(value, low, high) { return Math.max(low,Math.min(high,value)) }
function rectangle(area) {
  area=area || {}
  return {x:finite(area.x,0),y:finite(area.y,0),
    width:Math.max(0,finite(area.width,1920)),height:Math.max(0,finite(area.height,1080))}
}
function create() {
  return {x:0,y:0,previousX:0,previousY:0,count:0,size:48,area:rectangle(null),
    enabled:false,rate:1,configured:false,configuration:"",running:false,
    followers:[{x:0,y:4,vx:0,vy:0},{x:0,y:8,vx:0,vy:0}]}
}
function bounded(state,x,y) {
  var area=state.area
  return {x:clamp(x,area.x,area.x+Math.max(0,area.width-state.size)),
    y:clamp(y,area.y,area.y+Math.max(0,area.height-state.size))}
}
function rest(state,ordinal) { return bounded(state,state.x,state.y+Math.min(2,Math.max(0,ordinal))*OFFSET) }
function reset(state) {
  for (var i=0;i<state.followers.length;i++) {
    var target=rest(state,i+1),follower=state.followers[i]
    follower.x=target.x; follower.y=target.y; follower.vx=0; follower.vy=0
  }
  state.previousX=state.x; state.previousY=state.y; state.running=false
}
function nearRest(state) {
  for (var i=0;i<Math.min(2,state.count-1);i++) {
    var follower=state.followers[i],target=rest(state,i+1)
    if (Math.hypot(follower.x-target.x,follower.y-target.y)>POSITION_EPSILON
        || Math.hypot(follower.vx,follower.vy)>VELOCITY_EPSILON) return false
  }
  return true
}
function sync(state,x,y,count,area,size,enabled,rate) {
  var nextArea=rectangle(area),nextCount=Math.max(0,Math.floor(finite(count,0)))
  var nextSize=Math.max(1,finite(size,48)),nextEnabled=!!enabled && nextCount>1
  var signature=JSON.stringify([nextCount,nextSize,nextEnabled,nextArea.x,nextArea.y,nextArea.width,nextArea.height])
  state.x=finite(x,state.x); state.y=finite(y,state.y)
  state.count=nextCount; state.size=nextSize; state.area=nextArea; state.enabled=nextEnabled
  rate=finite(rate,1); state.rate=rate>0 ? clamp(rate,.1,4) : 1
  if (!state.configured || signature!==state.configuration || !nextEnabled) {
    state.configuration=signature; state.configured=true; reset(state)
  } else {
    state.running=!nearRest(state)
    if (!state.running) reset(state)
  }
}

// Exact critically damped spring integration for a linearly moving target.
// Substeps bound the second link's approximation of the first link's curve.
function axis(position,velocity,start,end,seconds,omega) {
  var targetVelocity=(end-start)/seconds
  var offset=position-start+2*targetVelocity/omega
  var relativeVelocity=velocity-targetVelocity
  var linear=relativeVelocity+omega*offset,decay=Math.exp(-omega*seconds)
  return {position:end-2*targetVelocity/omega+(offset+linear*seconds)*decay,
    velocity:targetVelocity+(relativeVelocity-omega*linear*seconds)*decay}
}
function limited(state,follower,ordinal,leadX,leadY) {
  var target=bounded(state,leadX,leadY+ordinal*OFFSET)
  var dx=follower.x-target.x,dy=follower.y-target.y,maximum=ordinal===1 ? 64 : 96
  var distance=Math.hypot(dx,dy)
  if (distance>maximum) {
    var nx=dx/distance,ny=dy/distance
    follower.x=target.x+nx*maximum; follower.y=target.y+ny*maximum
    // A pointer can jump between input samples. Projecting the lag limit must
    // not transfer that apparent lead velocity into the decorative spring.
    var away=follower.vx*nx+follower.vy*ny
    if (away>0) { follower.vx-=away*nx; follower.vy-=away*ny }
  }
  var point=bounded(state,follower.x,follower.y)
  if (point.x!==follower.x && (follower.x-point.x)*follower.vx>0) follower.vx=0
  if (point.y!==follower.y && (follower.y-point.y)*follower.vy>0) follower.vy=0
  follower.x=point.x; follower.y=point.y
}
function step(state,seconds) {
  if (!state.enabled || state.count<2) { reset(state); return }
  seconds=finite(seconds,0)
  if (seconds<=0 || !state.running) return
  seconds=Math.min(.05,seconds)
  var subdivisions=Math.max(1,Math.ceil(seconds/STEP)),dt=seconds/subdivisions
  var startX=state.previousX,startY=state.previousY
  var omega=OMEGA*state.rate
  for (var frame=0;frame<subdivisions;frame++) {
    var fraction=frame/subdivisions,nextFraction=(frame+1)/subdivisions
    var beforeX=startX+(state.x-startX)*fraction,beforeY=startY+(state.y-startY)*fraction
    var leadX=startX+(state.x-startX)*nextFraction,leadY=startY+(state.y-startY)*nextFraction
    var afterX=leadX,afterY=leadY
    for (var i=0;i<Math.min(2,state.count-1);i++) {
      var follower=state.followers[i],oldX=follower.x,oldY=follower.y
      var from=bounded(state,beforeX,beforeY+OFFSET),to=bounded(state,afterX,afterY+OFFSET)
      var horizontal=axis(follower.x,follower.vx,from.x,to.x,dt,omega)
      var vertical=axis(follower.y,follower.vy,from.y,to.y,dt,omega)
      follower.x=horizontal.position; follower.y=vertical.position
      follower.vx=horizontal.velocity; follower.vy=vertical.velocity
      limited(state,follower,i+1,leadX,leadY)
      beforeX=oldX; beforeY=oldY; afterX=follower.x; afterY=follower.y
    }
  }
  state.previousX=state.x; state.previousY=state.y
  state.running=!nearRest(state)
  if (!state.running) reset(state)
}
function pose(state,ordinal) {
  ordinal=Math.max(0,Math.floor(finite(ordinal,0)))
  if (ordinal===0) return {x:state.x,y:state.y}
  if (!state.enabled || ordinal>2 || ordinal>=state.count) return rest(state,ordinal)
  var source=state.followers[ordinal-1],copy={x:source.x,y:source.y,vx:source.vx,vy:source.vy}
  limited(state,copy,ordinal,state.x,state.y)
  return {x:copy.x,y:copy.y}
}
function active(state) { return !!state.running }
