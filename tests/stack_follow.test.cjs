const assert=require('node:assert/strict')
const fs=require('node:fs')
const vm=require('node:vm')
const p=vm.createContext({})
vm.runInContext(fs.readFileSync(__dirname+'/../ui/StackFollow.js','utf8').replace(/^\.pragma library\s*/,''),p)
const area={x:12,y:26,width:1200,height:760}
const rates=[.5,.75,1,1.5,2.5]
const near=(a,b,message,tolerance=1e-8)=>assert.ok(Math.abs(a-b)<=tolerance,`${message}: ${a} != ${b}`)
function world(rate=1,count=5,enabled=true){const w=p.create();p.sync(w,300,260,count,area,48,enabled,rate);return w}
function set(w,x,y){p.sync(w,x,y,w.count,w.area,w.size,w.enabled,w.rate)}
function inside(w){for(let i=1;i<Math.min(w.count,3);i++){const a=p.pose(w,i);assert.ok(a.x>=w.area.x-1e-8&&a.x+48<=w.area.x+w.area.width+1e-8);assert.ok(a.y>=w.area.y-1e-8&&a.y+48<=w.area.y+w.area.height+1e-8);assert.ok(Math.hypot(a.x-w.x,a.y-(w.y+i*4))<=(i===1?64:96)+1e-8)}}
function run(w,seconds=2,fps=120){for(let i=0;i<Math.ceil(seconds*fps)&&p.active(w);i++){p.step(w,1/fps);inside(w)}}
function drag(w,dx,dy,duration=.3,fps=120){const x=w.x,y=w.y;for(let i=1;i<=Math.round(duration*fps);i++){set(w,x+dx*i/Math.round(duration*fps),y+dy*i/Math.round(duration*fps));p.step(w,1/fps);inside(w)}}
function resting(w){assert.equal(p.active(w),false);for(let i=0;i<3;i++){const a=p.pose(w,i);near(a.x,w.x,'Settled horizontal stack');near(a.y,w.y+i*4,'Settled vertical preview offset')}}

{
 const w=world();resting(w)
 drag(w,180,0)
 const front=p.pose(w,0),first=p.pose(w,1),second=p.pose(w,2)
 assert.equal(front.x,480);assert.equal(front.y,260)
 assert.ok(first.x<front.x-15,'First trailer did not visibly lag')
 assert.ok(second.x<first.x-10,'Second trailer did not follow the first')
 near(first.y,264,'Horizontal drag changed preview offset');near(second.y,268,'Horizontal drag changed back offset')
 assert.equal(p.active(w),true)
 const before=p.pose(w,2);p.step(w,1/60);assert.ok(p.pose(w,2).x>before.x,'Released trailer did not catch up')
 run(w);resting(w)
}
console.log('Stack follow: fixed leading icon, visible cascaded lag and exact released-stack settlement passed')
{
 const w=world();drag(w,160,0,.25)
 const velocity=w.followers[0].vx,previous=p.pose(w,1)
 set(w,w.x-3,w.y-3);p.step(w,1/240)
 assert.ok(w.followers[0].vx>0 && velocity>0,'Turning discarded existing follower momentum')
 assert.ok(p.pose(w,1).x>previous.x,'Follower did not curve through the reversal')
 drag(w,-180,-100,.4)
 assert.ok(p.pose(w,1).y>w.y+4,'Vertical reversal did not leave a trailing icon')
 run(w);resting(w)
}
console.log('Stack follow: two-dimensional turns retain follower momentum without changing the lead passed')
{
 const cadences=[[0,0,0,0,0,0],[1,1,1,1,1,1],[2,0,4,1,3,0],[1,6,1,4,0,2]]
 for(const rate of rates)for(const fps of [30,60,120,144])for(const direction of [-1,1])for(const axis of ['x','y'])for(const cadence of cadences){
  const w=world(rate),origin=w[axis]
  function ordered(){
   const lead=p.pose(w,0)[axis]
   const first=p.pose(w,1)[axis]-(axis==='y'?4:0)
   const second=p.pose(w,2)[axis]-(axis==='y'?8:0)
   assert.ok((first-lead)*direction<=1e-6,`First follower overtook a straight drag: ${rate}/${fps}/${axis}/${direction}`)
   assert.ok((second-first)*direction<=1e-6,`Back follower overtook its link: ${rate}/${fps}/${axis}/${direction}`)
  }
  function frame(){
   // Match the QML wrapper: input updates are quantized, and it can sync the
   // unchanged target repeatedly between pointer events and render frames.
   p.sync(w,w.x,w.y,w.count,w.area,w.size,true,w.rate)
   p.step(w,1/fps);inside(w);ordered()
  }
  for(let event=0;event<cadence.length;event++){
   const next=origin+direction*(event+1)*30
   set(w,axis==='x'?next:w.x,axis==='y'?next:w.y)
   ordered()
   for(let idle=0;idle<cadence[event];idle++)frame()
  }
  for(let frameIndex=0;frameIndex<2*fps && p.active(w);frameIndex++)frame()
  resting(w)
 }
}
console.log('Stack follow: quantized pointer bursts and idle frames never propel followers ahead or break their chain passed')
{
 const times=[],lag=[]
 for(const rate of rates){
  const w=world(rate);drag(w,180,0)
  const gentle=world(rate);drag(gentle,60,0);lag.push(gentle.x-p.pose(gentle,1).x)
  let elapsed=0
  while(p.active(w)&&elapsed<2){p.step(w,1/240);elapsed+=1/240}
  assert.ok(elapsed<2,`Slow trailer failed to sleep: ${rate}, ${elapsed}`);resting(w);times.push(elapsed)
 }
 for(let i=1;i<rates.length;i++){
  assert.ok(times[i]<times[i-1],`Higher speed did not catch up sooner: ${times}`)
  assert.ok(lag[i]<lag[i-1],`Higher speed did not tighten following: ${lag}`)
 }
 const w=world();drag(w,160,70);const before=w.followers.map(v=>({...v}))
 p.sync(w,w.x,w.y,w.count,w.area,w.size,true,.5)
 assert.deepEqual(w.followers.map(v=>({...v})),before,'Speed change reset the follower pose/velocity')
 run(w);resting(w)
}
console.log('Stack follow: all five animation rates change lag/catch-up speed and preserve live motion passed')
{
 const positions=[]
 for(const fps of [30,60,120,144]){
  const w=world();drag(w,180,70,.5,fps)
  positions.push([p.pose(w,1).x,p.pose(w,1).y,p.pose(w,2).x,p.pose(w,2).y])
  run(w,2,fps);resting(w)
 }
 for(const a of positions)for(let i=0;i<a.length;i++)near(a[i],positions[0][i],'Refresh-rate-dependent following',.4)
 const stalled=world();set(stalled,400,300);p.step(stalled,5);inside(stalled)
 const normal=world();set(normal,400,300);p.step(normal,.05)
 for(let i=1;i<3;i++){near(p.pose(stalled,i).x,p.pose(normal,i).x,'Stalled frame horizontal clamp');near(p.pose(stalled,i).y,p.pose(normal,i).y,'Stalled frame vertical clamp')}
 const before=JSON.stringify(stalled.followers)
 for(const dt of [0,-1,NaN,Infinity])p.step(stalled,dt)
 assert.equal(JSON.stringify(stalled.followers),before,'Invalid elapsed time changed follower motion')
}
console.log('Stack follow: frame-rate stability, bounded stalled frames and invalid-clock handling passed')
{
 for(const rate of rates)for(const point of [[12,26],[1164,26],[12,730],[1164,730]]){
  const w=world(rate);set(w,...point);p.step(w,1/60);inside(w)
  for(let i=0;i<10;i++){set(w,point[0]===12?1164:12,point[1]===26?730:26);p.step(w,1/60);inside(w);set(w,...point);p.step(w,1/60);inside(w)}
  run(w);resting(w)
 }
 const w=world();drag(w,160,40)
 p.reset(w);resting(w)
 drag(w,60,-20);p.sync(w,w.x,w.y,w.count,w.area,48,false,1);resting(w)
 set(w,w.x+70,w.y+10);resting(w)
 for(const count of [0,1,2,3,7]){p.sync(w,300,260,count,area,48,true,1);assert.equal(p.active(w),false)}
 drag(w,100,30);p.sync(w,100,100,7,{x:0,y:40,width:400,height:300},48,true,1);resting(w)
 assert.equal(p.pose(w,20).y,108,'Hidden actors should retain their fixed collapsed preview offset')
 const tiny=p.create();p.sync(tiny,4,4,3,{x:0,y:0,width:20,height:20},48,true,1);set(tiny,10,12);p.step(tiny,.02)
 assert.ok(Number.isFinite(p.pose(tiny,2).x+p.pose(tiny,2).y),'Tiny output produced an invalid follower pose')
}
console.log('Stack follow: edge bounds, bounded lag, explicit reset, policy/count changes and hidden actors passed')
