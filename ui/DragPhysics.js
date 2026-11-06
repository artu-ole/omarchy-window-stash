.pragma library

// Logical-pixel simulation shared by both floating presentations. All time
// arguments are seconds; callers supply input timestamps, never frame counts.
var FIXED_STEP=1/240
var GAP=4
var FRICTION=4
var REST_SPEED=8

function clamp(v,low,high) { return Math.max(low,Math.min(high,v)) }
function full(w) { return w.animations!=="off" && w.animations!=="reduced" }
function physical(w) { return w.physicsEnabled && full(w) }
function create(options) {
  options=options || {}
  return {bodies:{},order:[],area:options.area || {x:0,y:0,width:1920,height:1080},
    snapEdges:options.snapEdges===undefined ? true : options.snapEdges,
    physicsEnabled:options.physicsEnabled===undefined ? true : options.physicsEnabled,
    animations:options.animations || "full",time:0,accumulator:0,frames:0,
    moved:{},activities:{},settlements:{},configKey:"",overcrowded:false}
}
function bounds(w,b) {
  var a=w.area,mx=Math.min(8,Math.max(0,(a.width-b.width)/2)),my=Math.min(8,Math.max(0,(a.height-b.height)/2))
  return {left:a.x+mx,top:a.y+my,right:Math.max(a.x+mx,a.x+a.width-mx-b.width),bottom:Math.max(a.y+my,a.y+a.height-my-b.height)}
}
function maxSpeed(w) { return Math.max(120,Math.min(8000,3*Math.max(w.area.width,w.area.height))) }
function moved(w,b) { w.moved[b.key]={key:b.key,x:b.x,y:b.y} }
function activity(w,b) { w.activities[b.key]={key:b.key,held:b.held,moving:b.moving,frozen:b.frozen} }
function stop(w,b) {
  b.held=false;b.moving=false;b.vx=0;b.vy=0;b.phase="rest";b.stable=0;b.samples=[]
  activity(w,b)
}
function edgeTargets(w,b,x,y) {
  var r=bounds(w,b),px=clamp(x,r.left,r.right),py=clamp(y,r.top,r.bottom)
  return [{edge:"left",x:r.left,y:py},{edge:"right",x:r.right,y:py},
    {edge:"top",x:px,y:r.top},{edge:"bottom",x:px,y:r.bottom}]
    .sort(function(a,c) { return Math.pow(a.x-x,2)+Math.pow(a.y-y,2)-Math.pow(c.x-x,2)-Math.pow(c.y-y,2) })
}
function updateDensity(w) {
  var width=48,height=48
  w.order.forEach(function(key) { width=Math.max(width,w.bodies[key].width);height=Math.max(height,w.bodies[key].height) })
  var columns=Math.max(0,Math.floor((w.area.width-16+GAP)/(width+GAP)))
  var rows=Math.max(0,Math.floor((w.area.height-16+GAP)/(height+GAP)))
  var capacity=w.snapEdges && columns>1 && rows>1 ? 2*columns+2*rows-4 : columns*rows
  w.overcrowded=w.order.length>capacity
}
function overlaps(a,b,gap) {
  gap=gap===undefined ? GAP : gap
  return a.x<b.x+b.width+gap && a.x+a.width+gap>b.x && a.y<b.y+b.height+gap && a.y+a.height+gap>b.y
}
function validPoint(w,b,x,y) {
  var probe={x:x,y:y,width:b.width,height:b.height}
  return w.order.every(function(key) { var other=w.bodies[key];return other===b || !overlaps(probe,other) })
}
function destination(w,b,x,y,preferred) {
  var r=bounds(w,b)
  x=clamp(x,r.left,r.right);y=clamp(y,r.top,r.bottom)
  if (w.overcrowded) {
    var crowdedEdge=w.snapEdges ? edgeTargets(w,b,x,y)[0] : {x:x,y:y,edge:""}
    return {x:crowdedEdge.x,y:crowdedEdge.y,edge:crowdedEdge.edge,crowded:true}
  }
  if (!w.snapEdges) {
    if (validPoint(w,b,x,y)) return {x:x,y:y,edge:"",crowded:false}
    // Resolve small contact errors at the nearest neighbor boundary before
    // considering a coarser grid slot; resting must not introduce a tile jump.
    var near=[]
    w.order.forEach(function(key) {
      var other=w.bodies[key]
      if (other===b) return
      near.push([other.x-b.width-GAP,y],[other.x+other.width+GAP,y],
        [x,other.y-b.height-GAP],[x,other.y+other.height+GAP])
    })
    near.sort(function(a,c) { return Math.pow(a[0]-x,2)+Math.pow(a[1]-y,2)-Math.pow(c[0]-x,2)-Math.pow(c[1]-y,2) })
    for (var n=0;n<near.length;n++) {
      var nx=clamp(near[n][0],r.left,r.right),ny=clamp(near[n][1],r.top,r.bottom)
      if (validPoint(w,b,nx,ny)) return {x:nx,y:ny,edge:"",crowded:false}
    }
    var step=Math.max(b.width,b.height)+GAP
    var rings=Math.ceil(Math.max(w.area.width,w.area.height)/step)+1
    for (var ring=1;ring<=rings;ring++) {
      var candidates=[]
      for (var j=-ring;j<=ring;j++) {
        candidates.push([x+j*step,y-ring*step],[x+j*step,y+ring*step])
        if (Math.abs(j)!==ring) candidates.push([x-ring*step,y+j*step],[x+ring*step,y+j*step])
      }
      for (var i=0;i<candidates.length;i++) {
        var p=candidates[i],cx=clamp(p[0],r.left,r.right),cy=clamp(p[1],r.top,r.bottom)
        if (validPoint(w,b,cx,cy)) return {x:cx,y:cy,edge:"",crowded:false}
      }
    }
    return {x:x,y:y,edge:"",crowded:true}
  }
  var edges=edgeTargets(w,b,x,y)
  if (preferred) edges.sort(function(a,c) { return (a.edge===preferred ? -1 : 0)-(c.edge===preferred ? -1 : 0) })
  for (var e=0;e<edges.length;e++) {
    var edge=edges[e],vertical=edge.edge==="left" || edge.edge==="right"
    var low=vertical ? r.top : r.left,high=vertical ? r.bottom : r.right,axis=vertical ? y : x
    var slots=[axis,low,high]
    w.order.forEach(function(key) {
      var other=w.bodies[key]
      if (other===b) return
      slots.push((vertical ? other.y : other.x)-(vertical ? b.height : b.width)-GAP,
        (vertical ? other.y+other.height : other.x+other.width)+GAP)
    })
    slots=slots.map(function(v) { return clamp(v,low,high) }).sort(function(a,c) { return Math.abs(a-axis)-Math.abs(c-axis) })
    for (var s=0;s<slots.length;s++) {
      var ex=vertical ? edge.x : slots[s],ey=vertical ? slots[s] : edge.y
      if (validPoint(w,b,ex,ey)) return {x:ex,y:ey,edge:edge.edge,crowded:false}
    }
  }
  return {x:edges[0].x,y:edges[0].y,edge:edges[0].edge,crowded:true}
}
function limit(w,b,rebound) {
  var r=bounds(w,b),x=clamp(b.x,r.left,r.right),y=clamp(b.y,r.top,r.bottom)
  if (x!==b.x) { if ((b.x<r.left && b.vx<0) || (b.x>r.right && b.vx>0)) b.vx=rebound ? -b.vx*.12 : 0;b.x=x }
  if (y!==b.y) { if ((b.y<r.top && b.vy<0) || (b.y>r.bottom && b.vy>0)) b.vy=rebound ? -b.vy*.12 : 0;b.y=y }
}
function add(w,key,x,y,width,height) {
  if (w.bodies[key]) return sync(w,key,x,y,width,height)
  var b={key:key,x:x,y:y,width:width,height:height,vx:0,vy:0,held:false,moving:false,frozen:false,
    phase:"rest",edge:"",collisionDriven:false,targetX:x,targetY:y,startX:x,startY:y,startTime:0,duration:0,
    stable:0,deadline:0,samples:[],lastMove:-Infinity,dirty:false,crowded:false,frames:0,collisions:0}
  w.bodies[key]=b;w.order.push(key);updateDensity(w);limit(w,b,false);moved(w,b);activity(w,b);return b
}
function remove(w,key) {
  delete w.bodies[key];w.order=w.order.filter(function(k) { return k!==key })
  delete w.moved[key];delete w.activities[key];delete w.settlements[key]
  updateDensity(w);w.order.forEach(function(k) { w.bodies[k].crowded=false })
}
function sync(w,key,x,y,width,height) {
  var b=w.bodies[key]
  if (!b) return add(w,key,x,y,width,height)
  var resized=b.width!==width || b.height!==height
  b.width=width;b.height=height;if (resized) updateDensity(w)
  if (!b.held && !b.moving && !b.frozen) { b.x=x;b.y=y;limit(w,b,false);moved(w,b) }
  return b
}
function finish(w,b,point) {
  var p=point || destination(w,b,b.x,b.y,b.edge)
  b.x=Math.round(p.x);b.y=Math.round(p.y);limit(w,b,false)
  b.edge=p.edge;b.crowded=p.crowded;stop(w,b);moved(w,b)
  if (b.dirty) w.settlements[b.key]={key:b.key,x:b.x,y:b.y}
  b.dirty=false
}
function begin(w,b,vx,vy) {
  if (b.frozen) return
  b.held=false;b.collisionDriven=false;b.vx=vx || 0;b.vy=vy || 0;b.stable=0;b.deadline=w.time+2;b.crowded=false
  b.startTime=w.time;b.startX=b.x;b.startY=b.y;b.dirty=true
  var r=bounds(w,b),px=clamp(b.x+b.vx/FRICTION,r.left,r.right),py=clamp(b.y+b.vy/FRICTION,r.top,r.bottom)
  var target=destination(w,b,px,py,"")
  b.edge=target.edge;b.targetX=target.x;b.targetY=target.y
  if (!physical(w)) {
    b.vx=0;b.vy=0
    target=destination(w,b,b.x,b.y,"");b.edge=target.edge;b.targetX=target.x;b.targetY=target.y
    if (!full(w) || !w.snapEdges || Math.hypot(b.x-target.x,b.y-target.y)<.5) { finish(w,b,target);return }
    b.phase="direct";b.duration=.24
  } else b.phase="physics"
  b.moving=true;activity(w,b)
}
function configure(w,area,snapEdges,physicsEnabled,animations) {
  var next={area:area,snapEdges:snapEdges,physicsEnabled:physicsEnabled,animations:animations}
  var signature=JSON.stringify(next)
  if (signature===w.configKey) return false
  w.configKey=signature;w.area={x:area.x,y:area.y,width:area.width,height:area.height}
  w.snapEdges=snapEdges;w.physicsEnabled=physicsEnabled;w.animations=animations;updateDensity(w)
  w.order.forEach(function(key) {
    var b=w.bodies[key];b.crowded=false;limit(w,b,false);moved(w,b)
    // A modal/menu may hold a resting item while its placement setting changes.
    // Keep its exact origin now, but resolve the new rules when it unfreezes.
    if (b.frozen) b.dirty=true
    else if (!b.held) begin(w,b,0,0)
  })
  return true
}
function sample(b,x,y,t) {
  if (b.samples.length && (t<b.samples[b.samples.length-1].t || t-b.samples[b.samples.length-1].t>1)) b.samples=[]
  var last=b.samples.length ? b.samples[b.samples.length-1] : null
  if (!last || Math.hypot(last.x-x,last.y-y)>.2) b.lastMove=t
  if (last && last.t===t) { last.x=x;last.y=y }
  else b.samples.push({x:x,y:y,t:t})
  while (b.samples.length>2 && b.samples[1].t<t-.1) b.samples.shift()
}
function velocity(w,b,t) {
  if (!physical(w) || t-b.lastMove>.12 || b.samples.length<2) return {x:0,y:0}
  var points=b.samples.slice(),last=points[points.length-1]
  if (t>last.t) points.push({x:b.x,y:b.y,t:t})
  var cutoff=t-.1,recent=[]
  for (var i=0;i<points.length;i++) {
    var p=points[i]
    if (p.t<cutoff) {
      var next=points[i+1]
      if (next && next.t>cutoff) {
        var ratio=(cutoff-p.t)/(next.t-p.t)
        recent.push({x:p.x+(next.x-p.x)*ratio,y:p.y+(next.y-p.y)*ratio,t:cutoff})
      }
    } else recent.push(p)
  }
  if (recent.length<2) return {x:0,y:0}
  var weight=0,mt=0,mx=0,my=0
  recent.forEach(function(p,i) { var q=1+i/Math.max(1,recent.length-1);weight+=q;mt+=q*p.t;mx+=q*p.x;my+=q*p.y })
  mt/=weight;mx/=weight;my/=weight
  var denominator=0,nx=0,ny=0
  recent.forEach(function(p,i) { var q=1+i/Math.max(1,recent.length-1),d=p.t-mt;denominator+=q*d*d;nx+=q*d*(p.x-mx);ny+=q*d*(p.y-my) })
  if (denominator<1e-8) return {x:0,y:0}
  var vx=nx/denominator,vy=ny/denominator,speed=Math.hypot(vx,vy),cap=maxSpeed(w)
  if (speed<120) return {x:0,y:0}
  return {x:vx*Math.min(1,cap/speed),y:vy*Math.min(1,cap/speed)}
}
function press(w,key,t) {
  var b=w.bodies[key];if (!b) return
  b.frozen=false;stop(w,b);b.held=true;b.crowded=false;b.samples=[];b.lastMove=t
  sample(b,b.x,b.y,t);activity(w,b)
}
function wake(w,b) {
  if (b.held || b.frozen || b.crowded || b.moving) return
  begin(w,b,0,0);b.collisionDriven=true
}
function nearestBoundary(w,b) {
  var edge=edgeTargets(w,b,b.x,b.y)[0]
  return Math.hypot(edge.x-b.x,edge.y-b.y)<2 ? edge.edge : b.edge
}
function swept(a,b) {
  var ax=a.prevX===undefined ? a.x : a.prevX,ay=a.prevY===undefined ? a.y : a.prevY
  var bx=b.prevX===undefined ? b.x : b.prevX,by=b.prevY===undefined ? b.y : b.prevY
  var dx=(a.x-ax)-(b.x-bx),dy=(a.y-ay)-(b.y-by)
  function times(p,v,low,high) {
    if (Math.abs(v)<1e-9) return p>low && p<high ? [-Infinity,Infinity] : [Infinity,-Infinity]
    var u=(low-p)/v,z=(high-p)/v;return [Math.min(u,z),Math.max(u,z)]
  }
  var tx=times(ax-bx,dx,-a.width-GAP,b.width+GAP),ty=times(ay-by,dy,-a.height-GAP,b.height+GAP)
  var enter=Math.max(tx[0],ty[0]),leave=Math.min(tx[1],ty[1])
  if (enter<0 || enter>1 || leave<enter) return null
  return {time:enter,axis:tx[0]>ty[0] ? "x" : "y",sign:tx[0]>ty[0] ? (dx>0 ? 1 : -1) : (dy>0 ? 1 : -1)}
}
function collisionPairs(w) {
  var grid={},pairs={},result=[],cell=64
  w.order.forEach(function(key) {
    var b=w.bodies[key],x0=Math.min(b.x,b.prevX===undefined ? b.x : b.prevX)-GAP,y0=Math.min(b.y,b.prevY===undefined ? b.y : b.prevY)-GAP
    var x1=Math.max(b.x,b.prevX===undefined ? b.x : b.prevX)+b.width+GAP,y1=Math.max(b.y,b.prevY===undefined ? b.y : b.prevY)+b.height+GAP
    for (var x=Math.floor(x0/cell);x<=Math.floor(x1/cell);x++) for (var y=Math.floor(y0/cell);y<=Math.floor(y1/cell);y++) {
      var slot=x+":"+y,entries=grid[slot] || []
      entries.forEach(function(other) {
        var id=key<other ? key+"\n"+other : other+"\n"+key
        if (!pairs[id]) { pairs[id]=true;result.push([w.bodies[other],b]) }
      })
      entries.push(key);grid[slot]=entries
    }
  })
  return result
}
function resolvePair(w,a,b) {
  if ((!a.held && !a.moving && !b.held && !b.moving) || a.phase==="fallback" || b.phase==="fallback") return
  var ia=a.held || a.frozen || a.crowded ? 0 : 1,ib=b.held || b.frozen || b.crowded ? 0 : 1
  if (ia+ib===0) return
  var overlap=overlaps(a,b),hit=overlap ? null : swept(a,b)
  if (!overlap && !hit) return
  var axis,sign,depth=0
  if (hit) {
    axis=hit.axis;sign=hit.sign
    if (ia) { a.x=a.prevX+(a.x-a.prevX)*hit.time;a.y=a.prevY+(a.y-a.prevY)*hit.time }
    if (ib) { b.x=b.prevX+(b.x-b.prevX)*hit.time;b.y=b.prevY+(b.y-b.prevY)*hit.time }
  } else {
    var ox=Math.min(a.x+a.width+GAP-b.x,b.x+b.width+GAP-a.x),oy=Math.min(a.y+a.height+GAP-b.y,b.y+b.height+GAP-a.y)
    var ae=nearestBoundary(w,a),be=nearestBoundary(w,b)
    var ra=bounds(w,a),rb=bounds(w,b)
    var blockedX=(b.x>=rb.right-.1 && b.x>a.x) || (b.x<=rb.left+.1 && b.x<a.x) || (a.x>=ra.right-.1 && a.x>b.x) || (a.x<=ra.left+.1 && a.x<b.x)
    var blockedY=(b.y>=rb.bottom-.1 && b.y>a.y) || (b.y<=rb.top+.1 && b.y<a.y) || (a.y>=ra.bottom-.1 && a.y>b.y) || (a.y<=ra.top+.1 && a.y<b.y)
    axis=ox<oy ? "x" : "y"
    if (w.snapEdges && (((ae==="left" || ae==="right") && ae===be) || (axis==="x" && blockedX))) axis="y"
    else if (w.snapEdges && (((ae==="top" || ae==="bottom") && ae===be) || (axis==="y" && blockedY))) axis="x"
    var delta=axis==="x" ? b.x+b.width/2-a.x-a.width/2 : b.y+b.height/2-a.y-a.height/2
    if (Math.abs(delta)<.01) {
      var roomPositive=axis==="x" ? rb.right-b.x : rb.bottom-b.y,roomNegative=axis==="x" ? b.x-rb.left : b.y-rb.top
      sign=roomPositive>=roomNegative ? 1 : -1
    } else sign=delta>0 ? 1 : -1
    depth=axis==="x" ? ox : oy
  }
  wake(w,a);wake(w,b)
  a.dirty=true;b.dirty=true;a.collisions++;b.collisions++
  var av=axis==="x" ? a.vx : a.vy,bv=axis==="x" ? b.vx : b.vy,relative=(bv-av)*sign
  var impulse=relative<0 ? -(1+.12)*relative/(ia+ib) : Math.min(180,depth*20)/(ia+ib)
  if (axis==="x") {
    if (ia) a.vx-=impulse*sign
    if (ib) b.vx+=impulse*sign
  } else {
    if (ia) a.vy-=impulse*sign
    if (ib) b.vy+=impulse*sign
  }
  function capNeighbor(body,inverse) {
    if (!inverse || !body.collisionDriven) return
    var speed=Math.hypot(body.vx,body.vy)
    if (speed>480) { body.vx*=480/speed;body.vy*=480/speed }
  }
  capNeighbor(a,ia);capNeighbor(b,ib)
  if (depth>0) {
    var correction=Math.min(4,Math.max(0,depth-.01)*.6)/(ia+ib)
    if (axis==="x") { if (ia) a.x-=sign*correction;if (ib) b.x+=sign*correction }
    else { if (ia) a.y-=sign*correction;if (ib) b.y+=sign*correction }
  }
  limit(w,a,true);limit(w,b,true)
  if (ia) moved(w,a)
  if (ib) moved(w,b)
}
function collisions(w) {
  if (!physical(w) || w.overcrowded) return
  for (var pass=0;pass<3;pass++) collisionPairs(w).forEach(function(pair) { resolvePair(w,pair[0],pair[1]) })
}
function drag(w,key,x,y,t) {
  var b=w.bodies[key];if (!b || !b.held || b.frozen) return
  var r=bounds(w,b);x=clamp(x,r.left,r.right);y=clamp(y,r.top,r.bottom)
  var dx=x-b.x,dy=y-b.y,steps=Math.max(1,Math.ceil(Math.hypot(dx,dy)/8)),sx=b.x,sy=b.y
  var last=b.samples.length ? b.samples[b.samples.length-1] : {t:t-.016,x:sx,y:sy},dt=Math.max(.001,t-last.t)
  b.vx=clamp(dx/dt,-maxSpeed(w),maxSpeed(w));b.vy=clamp(dy/dt,-maxSpeed(w),maxSpeed(w))
  for (var i=1;i<=steps;i++) {
    w.order.forEach(function(k) { var q=w.bodies[k];q.prevX=q.x;q.prevY=q.y })
    b.x=sx+dx*i/steps;b.y=sy+dy*i/steps
    collisions(w)
  }
  if (Math.hypot(dx,dy)>.01) b.dirty=true
  sample(b,b.x,b.y,t);moved(w,b)
}
function release(w,key,t) {
  var b=w.bodies[key];if (!b || !b.held) return
  var v=velocity(w,b,t);b.held=false
  if (!b.dirty) { stop(w,b);return }
  begin(w,b,v.x,v.y)
}
function cancel(w,key,settle) {
  var b=w.bodies[key];if (!b) return
  stop(w,b)
  if (settle && !b.frozen) begin(w,b,0,0)
}
function freeze(w,key,value) {
  var b=w.bodies[key];if (!b || b.frozen===value) return
  if (value) { stop(w,b);b.frozen=true;activity(w,b) }
  else { b.frozen=false;activity(w,b);if (b.dirty) begin(w,b,0,0) }
}
function active(w) { return w.order.some(function(key) { var b=w.bodies[key];return !b.frozen && (b.held || b.moving) }) }
function overlapDepth(w,b) {
  var depth=0
  w.order.forEach(function(key) {
    var other=w.bodies[key]
    if (other!==b && !other.crowded && overlaps(b,other)) depth=Math.max(depth,Math.min(b.x+b.width+GAP-other.x,other.x+other.width+GAP-b.x,b.y+b.height+GAP-other.y,other.y+other.height+GAP-b.y))
  })
  return depth
}
function fallback(w,b) {
  var p=destination(w,b,b.x,b.y,b.edge)
  b.targetX=p.x;b.targetY=p.y;b.edge=p.edge;b.crowded=p.crowded
  b.startX=b.x;b.startY=b.y;b.startTime=w.time;b.duration=.15;b.phase="fallback";b.vx=0;b.vy=0
  if (Math.hypot(b.x-p.x,b.y-p.y)<.5) finish(w,b,p)
}
function tick(w,dt) {
  w.time+=dt
  w.order.forEach(function(key) {
    var b=w.bodies[key];b.prevX=b.x;b.prevY=b.y
    if (!b.moving || b.held || b.frozen) return
    b.frames++
    if (b.phase==="direct" || b.phase==="fallback") {
      var p=clamp((w.time-b.startTime)/b.duration,0,1),e=1-Math.pow(1-p,3)
      b.x=b.startX+(b.targetX-b.startX)*e;b.y=b.startY+(b.targetY-b.startY)*e
      moved(w,b)
      if (p>=1) finish(w,b,{x:b.targetX,y:b.targetY,edge:b.edge,crowded:b.crowded})
      return
    }
    var decay=Math.exp(-FRICTION*dt)
    b.vx*=decay;b.vy*=decay
    if (w.snapEdges) {
      if (b.edge==="left" || b.edge==="right") b.vx+=(400*(b.targetX-b.x)-34*b.vx)*dt
      else b.vy+=(400*(b.targetY-b.y)-34*b.vy)*dt
    }
    var speed=Math.hypot(b.vx,b.vy),cap=b.collisionDriven ? Math.min(480,maxSpeed(w)) : maxSpeed(w)
    if (speed>cap) { b.vx*=cap/speed;b.vy*=cap/speed }
    b.x+=b.vx*dt;b.y+=b.vy*dt;limit(w,b,true);moved(w,b)
  })
  collisions(w)
  w.order.forEach(function(key) {
    var b=w.bodies[key]
    if (!b.moving || b.held || b.frozen || b.phase!=="physics") return
    var normalError=!w.snapEdges ? 0 : b.edge==="left" || b.edge==="right" ? Math.abs(b.x-b.targetX) : Math.abs(b.y-b.targetY)
    if (Math.hypot(b.vx,b.vy)<REST_SPEED && normalError<.5 && overlapDepth(w,b)<.5) b.stable+=dt
    else b.stable=0
    if (b.stable>=.1) finish(w,b)
    else if (w.time>=b.deadline) fallback(w,b)
  })
}
function step(w,elapsed) {
  if (!active(w)) { w.accumulator=0;return }
  w.frames++;w.accumulator+=clamp(elapsed,0,.05)
  var count=0
  while (w.accumulator+1e-10>=FIXED_STEP && count<12) { tick(w,FIXED_STEP);w.accumulator-=FIXED_STEP;count++ }
  if (!active(w)) w.accumulator=0
}
function drain(w) {
  var result={moved:Object.keys(w.moved).map(function(k) { return w.moved[k] }),
    activities:Object.keys(w.activities).map(function(k) { return w.activities[k] }),
    settled:Object.keys(w.settlements).map(function(k) { return w.settlements[k] })}
  w.moved={};w.activities={};w.settlements={};return result
}
function view(w,key) {
  var b=w.bodies[key]
  return b ? {key:key,x:b.x,y:b.y,width:b.width,height:b.height,vx:b.vx,vy:b.vy,held:b.held,moving:b.moving,
    frozen:b.frozen,phase:b.phase,edge:b.edge,collisionDriven:b.collisionDriven,frames:b.frames,collisions:b.collisions,crowded:b.crowded} : null
}
function details(w) {
  return {active:active(w),time:w.time,frames:w.frames,overcrowded:w.overcrowded,bodies:w.order.map(function(key) { return view(w,key) })}
}
