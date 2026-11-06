const assert=require('node:assert/strict')
const fs=require('node:fs'),vm=require('node:vm')
const p=vm.createContext({})
vm.runInContext(fs.readFileSync(__dirname+'/../ui/DragPhysics.js','utf8').replace(/^\.pragma library\s*/,''),p)
const area={x:0,y:26,width:1000,height:700}
const world=(snap=false,enabled=true,animations='full')=>p.create({area,snapEdges:snap,physicsEnabled:enabled,animations})
function add(w,key,x,y,height=48){p.add(w,key,x,y,48,height);p.drain(w)}
function run(w,seconds=3,fps=60){for(let i=0;i<Math.ceil(seconds*fps);i++)p.step(w,1/fps);return p.details(w)}
function launch(w,key,dx,dy,duration=.06,time=0){
  const b=w.bodies[key],sx=b.x,sy=b.y;p.press(w,key,time)
  for(let i=1;i<=6;i++)p.drag(w,key,sx+dx*i/6,sy+dy*i/6,time+duration*i/6)
  p.release(w,key,time+duration)
}
function inside(w){for(const key of w.order){const b=w.bodies[key],r=p.bounds(w,b);assert.ok(b.x>=r.left-.001&&b.x<=r.right+.001&&b.y>=r.top-.001&&b.y<=r.bottom+.001,JSON.stringify(p.view(w,key)))}}
function separated(w){for(let i=0;i<w.order.length;i++)for(let j=0;j<i;j++)assert.ok(!p.overlaps(w.bodies[w.order[i]],w.bodies[w.order[j]],3.5),JSON.stringify(p.details(w)))}
{
 const w=world();add(w,'a',100,200);assert.equal(p.active(w),false);run(w,1);assert.equal(w.bodies.a.x,100)
 p.press(w,'a',1);p.drag(w,'a',200,250,1.05);assert.equal(w.bodies.a.x,200);assert.equal(w.bodies.a.y,250)
 p.release(w,'a',1.05);assert.ok(w.bodies.a.vx>1500&&w.bodies.a.vy>750)
 p.step(w,1/60);assert.ok(w.bodies.a.x>200&&w.bodies.a.y>250)
 run(w);inside(w);assert.equal(p.active(w),false);assert.ok(w.bodies.a.x>500)
 const events=p.drain(w);assert.equal(events.settled.length,1)
}
console.log('Physics: direct pointer tracking, directional momentum, decay and final persistence passed')
{
 const w=world();add(w,'a',100,200);p.press(w,'a',0);p.drag(w,'a',200,200,.05);p.release(w,'a',.25)
 assert.equal(w.bodies.a.vx,0);run(w);assert.equal(w.bodies.a.x,200)
 const tiny=world();add(tiny,'a',100,200);launch(tiny,'a',3,0,.1);assert.equal(tiny.bodies.a.vx,0);run(tiny);assert.equal(tiny.bodies.a.x,103)
 const clock=world();add(clock,'a',100,200);p.press(clock,'a',100);p.drag(clock,'a',200,200,90);p.release(clock,'a',90);assert.equal(clock.bodies.a.vx,0)
}
console.log('Physics: paused/slow release and backwards clock never create accidental flicks')
{
 const results=[]
 for(const fps of [30,60,120,144]){const w=world();add(w,'a',100,200);launch(w,'a',100,40);run(w,3,fps);results.push([w.bodies.a.x,w.bodies.a.y]);inside(w);assert.equal(p.active(w),false)}
 for(const v of results)assert.ok(Math.hypot(v[0]-results[0][0],v[1]-results[0][1])<=1,JSON.stringify(results))
 const stalled=world();add(stalled,'a',100,200);launch(stalled,'a',100,0);p.step(stalled,5);assert.ok(stalled.time<=.05+1e-9);inside(stalled)
}
console.log('Physics: fixed-step motion agrees at30/60/120/144Hz and clamps stalled frames')
{
 const w=world(true);add(w,'a',100,300);launch(w,'a',200,0,.05)
 assert.equal(w.bodies.a.edge,'right','Momentum must affect selected edge')
 for(let i=0;i<180;i++){p.step(w,1/60);inside(w)}
 assert.equal(p.active(w),false);assert.equal(w.bodies.a.x,944)
 const gentle=world(true);add(gentle,'a',100,300);p.press(gentle,'a',0);p.drag(gentle,'a',110,300,.2);p.release(gentle,'a',.5);assert.equal(gentle.bodies.a.edge,'left');run(gentle);assert.equal(gentle.bodies.a.x,8)
}
console.log('Physics: projected landing chooses edge, gentle drop chooses nearest, all motion stays inside reservations')
{
 for(const [enabled,animations] of [[false,'full'],[true,'reduced'],[true,'off']]){
  const w=world(false,enabled,animations);add(w,'a',100,200);launch(w,'a',100,0);assert.equal(w.bodies.a.vx,0);assert.equal(w.bodies.a.x,200);assert.equal(p.active(w),false)
 }
 const direct=world(true,false);add(direct,'a',100,300);launch(direct,'a',10,0,.2);assert.equal(direct.bodies.a.phase,'direct');p.step(direct,.05);assert.ok(direct.bodies.a.x<110&&direct.bodies.a.x>8);run(direct,.25);assert.equal(direct.bodies.a.x,8);assert.equal(p.active(direct),false)
 for(const mode of ['reduced','off']){const w=world(true,true,mode);add(w,'a',100,300);launch(w,'a',10,0);assert.equal(w.bodies.a.x,8);assert.equal(p.active(w),false)}
}
console.log('Physics: Direct full snap takes240ms; Reduced/Off skip inertia, collisions and motion')
{
 const scales=[.4,2/3,1,4/3,2]
 assert.equal(world().animationScale,1,'Legacy worlds retain normal animation speed')
 for(const scale of scales){
  const w=p.create({area,snapEdges:true,physicsEnabled:false,animations:'full',animationScale:scale})
  add(w,'a',100,300);launch(w,'a',10,0,.2)
  const duration=.24*scale
  assert.equal(w.bodies.a.phase,'direct')
  // Equal fractions of the selected duration follow the same easing curve,
  // rather than changing the edge destination or the icon's path.
  p.tick(w,duration/2)
  assert.ok(Math.abs(w.bodies.a.x-20.75)<1e-8,'Speed changed the Direct midpoint')
  assert.equal(w.bodies.a.y,300)
  p.tick(w,duration/2)
  assert.equal(w.bodies.a.x,8);assert.equal(w.bodies.a.y,300);assert.equal(p.active(w),false)

  const framed=p.create({area,snapEdges:true,physicsEnabled:false,animationScale:scale})
  add(framed,'a',100,300);launch(framed,'a',10,0,.2)
  for(let i=0;i<240 && p.active(framed);i++)p.step(framed,1/240)
  assert.ok(framed.time>=duration-1e-10 && framed.time<=duration+1/240+1e-10,
   `Direct settlement did not follow selected speed: scale=${scale}, time=${framed.time}`)
  assert.equal(framed.bodies.a.x,8);assert.equal(p.active(framed),false)

  for(const animations of ['reduced','off']){
   const immediate=p.create({area,snapEdges:true,animations,animationScale:scale})
   add(immediate,'a',100,300);launch(immediate,'a',10,0)
   assert.equal(immediate.bodies.a.x,8);assert.equal(p.active(immediate),false)
  }
 }
}
console.log('Physics: all animation speeds scale Direct timing, preserve its path/endpoints, and respect Reduced/Off')
{
 const scales=[.4,2/3,1,4/3,2]
 const worlds=scales.map(animationScale=>{
  const w=p.create({area,snapEdges:false,animationScale})
  add(w,'a',100,200);launch(w,'a',70,40)
  return w
 })
 const signature=w=>JSON.stringify(p.view(w,'a'))
 for(let frame=0;frame<180;frame++){
  for(const w of worlds)p.step(w,1/60)
  for(const w of worlds)assert.equal(signature(w),signature(worlds[0]),'Animation speed altered physical coasting')
 }
 assert.ok(worlds.every(w=>!p.active(w)))

 const reference=world(),changing=world()
 for(const w of [reference,changing]){add(w,'a',100,200);launch(w,'a',70,40)}
 for(let frame=0;frame<180;frame++){
  if(frame===7 || frame===19 || frame===50){
   const before=signature(changing),configKey=changing.configKey
   changing.animationScale=frame===7 ? 2 : frame===19 ? .4 : 4/3
   assert.equal(signature(changing),before,'Changing speed reset a coasting body')
   assert.equal(changing.configKey,configKey,'Speed changes should not alter physical configuration')
  }
  p.step(reference,1/60);p.step(changing,1/60)
  assert.equal(signature(changing),signature(reference),'Mid-flight speed change altered physical time or velocity')
 }
}
console.log('Physics: animation speed and mid-coast changes leave real-time momentum, velocities and trajectories unchanged')
{
 for(const scale of [.4,2/3,1,4/3,2]){
  const w=p.create({area,snapEdges:true,animationScale:scale})
  add(w,'a',100,300);launch(w,'a',10,0,.2)
  p.fallback(w,w.bodies.a)
  assert.equal(w.bodies.a.phase,'fallback')
  p.tick(w,.15*scale/2)
  assert.ok(Math.abs(w.bodies.a.x-20.75)<1e-8,'Speed changed fallback settling path')
  assert.equal(w.bodies.a.y,300)
  p.tick(w,.15*scale/2)
  assert.equal(w.bodies.a.x,8);assert.equal(p.active(w),false)
 }
}
console.log('Physics: bounded fallback settling follows animation speed without changing its destination')
{
 const w=world();add(w,'a',100,200);launch(w,'a',100,0);p.step(w,.05);const x=w.bodies.a.x
 p.press(w,'a',1);assert.equal(w.bodies.a.x,x);assert.equal(w.bodies.a.vx,0);p.drag(w,'a',320,250,1.05);assert.equal(w.bodies.a.x,320)
 p.release(w,'a',1.05);p.step(w,.02);p.freeze(w,'a',true);const frozen=[w.bodies.a.x,w.bodies.a.y];run(w,1);assert.deepEqual([w.bodies.a.x,w.bodies.a.y],frozen)
 p.sync(w,'a',10,10,48,48);assert.deepEqual([w.bodies.a.x,w.bodies.a.y],frozen)
 p.freeze(w,'a',false);assert.equal(w.bodies.a.vx,0);run(w);inside(w)
}
console.log('Physics: catching/freeze cancels velocity without jumping; stale snapshots cannot move active/frozen bodies')
{
 const w=world();add(w,'a',100,200);add(w,'b',250,200);launch(w,'a',100,0,.05);for(let i=0;i<180;i++){p.step(w,1/60);assert.ok(Math.hypot(w.bodies.b.vx,w.bodies.b.vy)<=480.001)};inside(w);separated(w)
 assert.ok(w.bodies.b.x>250,'Neighbor must be nudged');assert.ok(w.bodies.a.collisions>0&&w.bodies.b.collisions>0)
 assert.equal(p.active(w),false);const saved=p.drain(w).settled.map(v=>v.key);assert.ok(saved.includes('a')&&saved.includes('b'))
 const fast=world();add(fast,'a',100,200);add(fast,'b',400,200);p.press(fast,'a',0);p.drag(fast,'a',600,200,.03);assert.ok(fast.bodies.b.x!==400||fast.bodies.b.y!==200,'Held sweep tunneled through a neighbor');p.release(fast,'a',.03);run(fast);separated(fast);inside(fast)
}
console.log('Physics: soft collisions wake neighbors, persist all displaced icons and sweep fast held motion')
{
 const w=world(true);add(w,'a',700,300);add(w,'b',944,300);launch(w,'a',200,0,.06);run(w);inside(w);separated(w)
 assert.ok(Math.abs(w.bodies.b.y-300)>1,'Occupied edge must allow tangential nudging');assert.equal(p.active(w),false)
 const crowded=p.create({area:{x:0,y:26,width:120,height:100},snapEdges:true});for(let i=0;i<10;i++)add(crowded,'b'+i,8+(i%2)*52,34+(i%2)*10)
 launch(crowded,'b0',40,20,.05);run(crowded,5);inside(crowded);assert.equal(p.active(crowded),false,'Crowded layout must eventually sleep')
}
console.log('Physics: occupied-edge tangential separation and overcrowded sleeping fallback passed')
{
 const w=world();add(w,'a',100,200);launch(w,'a',100,0);p.configure(w,{x:0,y:26,width:320,height:214},false,true,'full');run(w);inside(w)
 launch(w,'a',20,0);p.configure(w,w.area,true,true,'off');inside(w);assert.equal(p.active(w),false)
 p.remove(w,'a');assert.equal(p.active(w),false);assert.equal(p.details(w).bodies.length,0)
}
console.log('Physics: area/settings changes and removal leave no stale motion or body')

{
 const w=world();add(w,'a',300,220);p.freeze(w,'a',true)
 p.configure(w,w.area,true,true,'full');run(w,.5)
 assert.equal(w.bodies.a.x,300);assert.equal(w.bodies.a.y,220);assert.equal(p.active(w),false)
 p.freeze(w,'a',false);run(w);inside(w)
 assert.ok(w.bodies.a.x===8||w.bodies.a.x===944||w.bodies.a.y===34||w.bodies.a.y===670)
 assert.equal(p.active(w),false)
}
console.log('Physics: frozen resting items apply deferred placement settings only after unfreeze')

{
 for(const fps of [30,60,120,144]){
  const w=p.create({area:{x:0,y:26,width:2000,height:900},snapEdges:false})
  add(w,'a',100,300);add(w,'b',700,300);launch(w,'a',200,0,.03)
  for(let i=0;i<3*fps;i++){
   p.step(w,1/fps)
   assert.ok(w.bodies.a.x<=w.bodies.b.x || Math.abs(w.bodies.a.y-w.bodies.b.y)>=52,'Fast coasting body tunneled through its neighbor')
   assert.ok(Math.hypot(w.bodies.b.vx,w.bodies.b.vy)<=480.001)
  }
  separated(w);inside(w);assert.equal(p.active(w),false)
 }
 const w=p.create({area:{x:0,y:26,width:320,height:214},snapEdges:true})
 for(let i=0;i<70;i++)add(w,'dense'+i,8+(i%5)*52,34+(i%3)*52)
 assert.equal(w.overcrowded,true)
 launch(w,'dense0',200,100);run(w,3)
 assert.equal(p.active(w),false);assert.equal(w.bodies.dense0.collisions,0,'Impossible density should use bounded fallback rather than an expensive contact loop')
}
console.log('Physics: high-speed coasting never tunnels at any refresh rate, and impossible density uses bounded fallback')
