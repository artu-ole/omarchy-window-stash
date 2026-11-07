const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const code = fs.readFileSync(__dirname + '/../ui/Model.js', 'utf8').replace(/^\.pragma library\s*/, '')
const ctx = vm.createContext({}); vm.runInContext(code, ctx)
const windows = [
  {id:'a',app:'Browser',title:'A',order:1,origin:{id:1}},
  {id:'b',app:'Browser',title:'B',order:3,origin:{id:2}},
  {id:'c',app:'Terminal',title:'C',order:2,origin:{id:1}}
]
const visible = ctx.visibleWindows(windows,1,'workspace')
assert.equal(visible.map(x=>x.id).join(','),'c,a')
assert.equal(ctx.visibleWindows(windows,1,'global').map(x=>x.id).join(','),'b,c,a')
assert.equal(ctx.groups(windows,'window').length,3)
const apps=ctx.groups(ctx.visibleWindows(windows,1,'global'),'app')
assert.equal(apps.length,2); assert.equal(apps[0].windows.length,2)
assert.equal(apps[0].windows[0].id,'b')
assert.equal(ctx.bubblePosition([-20,900],0,1000,600).join(','),'8,544')
assert.notEqual(ctx.bubblePosition(null,0,1000,600).join(','),ctx.bubblePosition(null,1,1000,600).join(','))
console.log('Model: scope, order, grouping, and bubble placement passed')

assert.equal(ctx.iconRadius('auto',48,true,0),24)
assert.equal(ctx.iconRadius('auto',44,false,3),3)
assert.equal(ctx.iconRadius('circle',48,false,0),24)
assert.equal(ctx.iconRadius('square',48,true,12),0)
assert.ok(ctx.iconRadius('rounded',48,true,0)>0 && ctx.iconRadius('rounded',48,true,0)<24)
const bands=ctx.squircleBands(48,48)
for (let y=0;y<48;y++) for (let x=0;x<48;x++) {
  const covered=bands.some(b=>x>=b.x && x<b.x+b.width && y>=b.y && y<b.y+b.height)
  const inside=((x+0.5-24)/24)**4+((y+0.5-24)/24)**4<=1
  assert.equal(covered,inside,`Squircle input mismatch at ${x},${y}`)
}
const contour=ctx.squirclePath(48,48,0,0,0,0,false)
assert.ok(contour.startsWith('M ') && contour.endsWith(' Z'))
assert.ok(!/NaN|Infinity/.test(contour))
console.log('Model: shape defaults and exact squircle input coverage passed')

assert.equal(ctx.floatingAnchor(null,1000,600).join(','),'932,276')
assert.equal(ctx.floatingAnchor([-20,900],1000,600).join(','),'8,536')
for (const scale of [1,1.25,1.5,2]) for (const frame of [44,48]) {
  const size=ctx.alignedIconSize(frame,28,scale)
  const pixels=Math.round(size*scale)
  assert.ok(Math.abs(size*scale-pixels)<1e-6)
  assert.equal((Math.round(frame*scale)-pixels)%2,0,'Artwork must be centered without half-pixel offsets')
}
for (const scale of [1,1.25,1.5,2]) for (const frame of [44,48]) {
  for (const shape of ['circle','square','rounded','squircle']) {
    const radius=ctx.iconRadius(shape,frame,frame===48,0)
    const size=ctx.artworkSize(frame,36,radius,shape,1.5,scale)
    assert.ok(size>28 && size<frame,'Compact artwork should use more of its frame')
    assert.equal((Math.round(frame*scale)-Math.round(size*scale))%2,0)
    const half=(size-1/scale)/2, inner=frame/2-1.5, r=Math.max(0,Math.min(inner,radius-1.5))
    const limit=shape==='squircle' ? inner*Math.pow(0.5,0.25) : inner-r+r/Math.sqrt(2)
    assert.ok(half<=limit+0.5/scale,'Artwork corners exceed their shape clearance')
  }
}
console.log('Model: compact artwork remains centered with shape-aware corner clearance')

for (const [w,h] of [[320,240],[1024,576],[1920,1080],[600,1000]]) {
  for (const reserved of [[],[0,26,0,0],[21,48,37,19]]) {
    const area=ctx.usableArea(w,h,reserved)
    for (const side of ['bottom','top','left','right']) {
      const vertical=side==='left'||side==='right'
      for (const count of [1,3,50]) {
        const length=ctx.dockLength(count,44,4)+6
        const p=ctx.staticDockRect(area,side,vertical?50:length,vertical?length:50,8,16)
        assert.ok(p.width>=0 && p.height>=0)
        assert.ok(p.x>=area.x && p.y>=area.y)
        assert.ok(p.x+p.width<=area.x+area.width && p.y+p.height<=area.y+area.height)
        if(vertical) {
          assert.ok(Math.abs(p.y+p.height/2-area.y-area.height/2)<=0.5)
          assert.equal(side==='left'?p.x-area.x:area.x+area.width-p.x-p.width,8)
        } else {
          assert.ok(Math.abs(p.x+p.width/2-area.x-area.width/2)<=0.5)
          assert.equal(side==='top'?p.y-area.y:area.y+area.height-p.y-p.height,8)
        }
      }
    }
  }
}
for(const side of ['bottom','top','left','right']) {
  const p=ctx.staticDockRect(ctx.usableArea(5,5,[]),side,50,500,8,16)
  assert.ok(p.x>=0 && p.y>=0 && p.x+p.width<=5 && p.y+p.height<=5)
}
console.log('Model: all four dock sides respect reserved edges, centering, and overflow bounds')

const staticAreas=[
  ctx.usableArea(1920,1080,[21,48,37,19]),
  ctx.usableArea(320,240,[12,34,20,16]),
  {x:-125.25,y:43.5,width:713.5,height:498.25},
  {x:3.5,y:7.25,width:5,height:3},
  {x:0,y:0,width:0,height:0},
]
for(const area of staticAreas) for(const side of ['top','bottom','left','right']) {
  const vertical=side==='left'||side==='right',axis=vertical?'y':'x',length=vertical?'height':'width'
  for(const desiredLength of [0,50,174,5000]) {
    const desiredWidth=vertical?50:desiredLength,desiredHeight=vertical?desiredLength:50
    const defaults=ctx.staticDockRect(area,side,desiredWidth,desiredHeight,8,16)
    const center=area[axis]+Math.round((area[length]-defaults[length])/2)
    assert.equal(defaults[axis],center,'Default position changed the original rounded center')
    assert.equal(ctx.staticDockRect(area,side,desiredWidth,desiredHeight,8,16,.5)[axis],center)
    let previous=-Infinity
    for(const fraction of [0,.125,.25,.5,.75,.875,1]) {
      const rect=ctx.staticDockRect(area,side,desiredWidth,desiredHeight,8,16,fraction)
      assert.ok(Object.values(rect).every(Number.isFinite),'Static position produced nonfinite geometry')
      assert.ok(rect.width>=0 && rect.height>=0)
      assert.ok(rect.x>=area.x && rect.y>=area.y)
      assert.ok(rect.x+rect.width<=area.x+area.width+1e-7 && rect.y+rect.height<=area.y+area.height+1e-7,
        'Dragging escaped the reserved work area')
      assert.ok(rect[axis]>=previous,'Increasing the saved fraction moved the dock backwards')
      previous=rect[axis]
      assert.equal(vertical?rect.x:rect.y,vertical?defaults.x:defaults.y,'Dragging changed the side gap')
      const margin=Math.min(16,area[length]/2)
      const travel=Math.max(0,area[length]-rect[length]-margin*2)
      const inverse=ctx.staticDockPosition(area,side,desiredWidth,desiredHeight,8,16,rect[axis],fraction)
      if(travel>0) assert.ok(Math.abs(inverse-fraction)<=.500001/travel,'Position inverse lost more than pixel rounding')
      else assert.equal(inverse,fraction,'An overflowing dock erased its saved position')
    }
    assert.equal(ctx.staticDockPosition(area,side,desiredWidth,desiredHeight,8,16,-1e6,.3),
      area[length]-defaults[length]-Math.min(16,area[length]/2)*2>0?0:.3)
    assert.equal(ctx.staticDockPosition(area,side,desiredWidth,desiredHeight,8,16,1e6,.7),
      area[length]-defaults[length]-Math.min(16,area[length]/2)*2>0?1:.7)
  }
}
console.log('Model: static dock positions preserve centering, all four side gaps, inverse dragging and reserved/tiny/overflow bounds')

const staticArea=ctx.usableArea(640,480,[17,41,29,23])
for(const side of ['top','bottom','left','right']) {
  const vertical=side==='left'||side==='right',axis=vertical?'y':'x'
  for(const fraction of [0,.13755,.5,.82,1]) {
    const saved=[fraction*10000,0]
    const first=ctx.staticDockRect(staticArea,side,vertical?50:150,vertical?150:50,8,16,ctx.staticDockSavedPosition(saved))
    for(const count of [1,3,50,2,1]) {
      const length=ctx.dockLength(count,44,4)+6
      const rect=ctx.staticDockRect(staticArea,side,vertical?50:length,vertical?length:50,8,16,ctx.staticDockSavedPosition(saved))
      assert.ok(rect.x>=staticArea.x && rect.y>=staticArea.y)
      assert.ok(rect.x+rect.width<=staticArea.x+staticArea.width && rect.y+rect.height<=staticArea.y+staticArea.height)
      assert.equal(ctx.staticDockSavedPosition(saved),fraction,'Resize or overflow changed the normalized stored position')
    }
    const restored=ctx.staticDockRect(staticArea,side,vertical?50:150,vertical?150:50,8,16,ctx.staticDockSavedPosition(saved))
    assert.equal(restored[axis],first[axis],'Growing and shrinking a dock moved its restored position')
  }
}
for(const [saved,expected] of [[[0,0],0],[[10000,0],1],[[2375.5,0],.23755]])
  assert.equal(ctx.staticDockSavedPosition(saved),expected)
for(const saved of [null,undefined,[],[5000],[5000,0,0],['5000',0],[5000,'0'],[5000,1],
  [NaN,0],[Infinity,0],[-1,0],[10001,0],{0:0,1:0,length:2}])
  assert.equal(ctx.staticDockSavedPosition(saved),.5,'Malformed stored position did not fall back to center')
console.log('Model: static position storage keeps fractional basis points and survives growth, overflow and shrink without drifting')

const validStatic=[staticArea,'bottom',180,50,8,16]
const centered=JSON.stringify(ctx.staticDockRect(...validStatic))
for(const invalid of [undefined,null,NaN,Infinity,-Infinity,'0','1',false,{}]) {
  assert.equal(JSON.stringify(ctx.staticDockRect(...validStatic,invalid)),centered)
  assert.equal(ctx.staticDockPosition(...validStatic,invalid,.27),.27)
}
assert.equal(JSON.stringify(ctx.staticDockRect(...validStatic,-2)),JSON.stringify(ctx.staticDockRect(...validStatic,0)))
assert.equal(JSON.stringify(ctx.staticDockRect(...validStatic,2)),JSON.stringify(ctx.staticDockRect(...validStatic,1)))
assert.equal(ctx.staticDockPosition(staticArea,'bottom',5000,50,8,16,200,NaN),.5)
assert.equal(ctx.staticDockPosition(staticArea,'bottom',5000,50,8,16,200,2),1)
for(const args of [
  [null,'bottom',NaN,Infinity,NaN,Infinity],
  [{x:NaN,y:Infinity,width:NaN,height:-50},'left',Infinity,-1,-8,'16'],
  [{x:Number.MAX_VALUE,y:-Number.MAX_VALUE,width:Number.MAX_VALUE,height:Number.MAX_VALUE},'top',Number.MAX_VALUE,50,8,16],
]) {
  const rect=ctx.staticDockRect(...args,.8)
  assert.ok(Object.values(rect).every(Number.isFinite),'Malformed static geometry was not finite')
  assert.ok(rect.width>=0 && rect.height>=0)
  const inverse=ctx.staticDockPosition(...args,300,.8)
  assert.ok(Number.isFinite(inverse) && inverse>=0 && inverse<=1)
}
console.log('Model: static dragging clamps fractions, validates coordinates and keeps malformed geometry finite')

const anonymousOutput={name:'HEADLESS-1',make:'',model:'',serial:'',description:''}
assert.equal(ctx.monitorKey(anonymousOutput),'|||','Static fallback changed existing floating/bubble identity')
assert.equal(ctx.staticDockMonitorKey(anonymousOutput),'output:HEADLESS-1')
assert.equal(ctx.staticDockMonitorKey({...anonymousOutput}),ctx.staticDockMonitorKey(anonymousOutput),
  'An anonymous output lost its stable named fallback')
assert.notEqual(ctx.staticDockMonitorKey({...anonymousOutput,name:'HEADLESS-2'}),ctx.staticDockMonitorKey(anonymousOutput),
  'Anonymous outputs shared a static position')
assert.equal(ctx.staticDockMonitorKey({name:'DP-1'}),'output:DP-1')
assert.equal(ctx.staticDockMonitorKey({name:'DP-2',make:' ',model:'\t',serial:'',description:''}),'output:DP-2')
const identifiedOutput={name:'DP-3',make:'Display vendor',model:'Panel',serial:'001',description:'Physical display'}
assert.equal(ctx.staticDockMonitorKey(identifiedOutput),ctx.monitorKey(identifiedOutput))
assert.equal(ctx.staticDockMonitorKey({...identifiedOutput,name:'DP-4'}),ctx.monitorKey(identifiedOutput),
  'An identified display lost its existing connector-independent identity')
assert.equal(ctx.staticDockMonitorKey(null),'output:')
console.log('Model: static docks isolate anonymous output names while preserving existing real-display and floating identities')

for(const [w,h] of [[320,240],[1920,1080],[600,1000]]) {
  const area=ctx.usableArea(w,h,[12,34,20,16])
  for(const p of [[w/2,h/2],[0,h/2],[w,h/2],[w/2,0],[w/2,h]]) {
    for(const height of [48,56]) {
      const target=ctx.floatingPosition(p,w,h,area,true,height)
      const [x,y]=target
      assert.ok(x>=area.x+8 && x+48<=area.x+area.width-8)
      assert.ok(y>=area.y+8 && y+height<=area.y+area.height-8)
      assert.ok(x===area.x+8 || x+48===area.x+area.width-8 || y===area.y+8 || y+height===area.y+area.height-8)
      assert.equal(ctx.floatingPosition(target,w,h,area,true,height).join(','),target.join(','),'Snap must be stable')
    }
    assert.equal(ctx.floatingPosition(p,w,h,area,false,56).join(','),ctx.floatingAnchor(p,w,h).join(','))
  }
  const keys=Array.from({length:12},(_,i)=>'window:'+i),saved={}
  keys.forEach(key=>saved[key]=[w-70,h/2])
  const positions=ctx.bubbleLayout(keys,saved,{},w,h,area,true)
  for(let i=0;i<positions.length;i++) {
    const [x,y]=positions[i]
    assert.ok(x===area.x+8 || x+48===area.x+area.width-8 || y===area.y+8 || y+48===area.y+area.height-8)
    for(let j=0;j<i;j++) {
      const [a,b]=positions[j]
      assert.ok(x>=a+52 || x+52<=a || y>=b+52 || y+52<=b,'Edge bubbles must remain separate')
    }
  }
  const free=ctx.bubbleLayout(['a'],{a:[w/2,h/2]},{},w,h,area,false)[0]
  assert.equal(free.join(','),ctx.bubblePosition([w/2,h/2],0,w,h,1).join(','))
}
console.log('Model: edge snapping, bar clearance, stable targets, bubble packing and free placement passed')

assert.equal(ctx.dockRadius('theme',12,7,200,50),7)
assert.equal(ctx.dockRadius('custom',0,7,200,50),0)
assert.equal(ctx.dockRadius('custom',12,7,200,50),12)
assert.equal(ctx.dockRadius('custom',64,7,200,50),25)
assert.equal(ctx.dockRadius('custom',64,7,50,200),25)
assert.equal(ctx.dockRadius('custom',12,7,0,56),0)
for(const invalid of [undefined,null,'12',-1,65,NaN,Infinity]) assert.equal(ctx.dockRadius('custom',invalid,7,200,50),7)
console.log('Model: independent dock rounding, theme fallback, and small-panel radius limits passed')

for(const frame of [44,48]) for(const scale of [1,1.25,1.5,2]) {
  const size=ctx.artworkSize(frame,36,frame/2,'circle',1.5,scale,true)
  assert.ok(size>ctx.artworkSize(frame,36,frame/2,'circle',1.5,scale,false))
  assert.ok(size*1.04<frame,'Frameless hover must fit its tile')
  assert.equal((Math.round(frame*scale)-Math.round(size*scale))%2,0)
}
console.log('Model: larger frameless artwork remains centered and hover fits its tile')

for(const [old,next] of [
  [['a','b','c'],['a','c']], [['a','b','c'],['d','a','c']],
  [['a','b','c'],['c','a']], [['a','b'],[]], [[],['a','b']],
  [['a','b','c'],['b','d','c','a']], [['a','b'],['d']]
]) {
  const merged=ctx.reconcileKeys(old,next)
  assert.deepEqual(Array.from(merged.filter(k=>next.includes(k))),next)
  assert.equal(new Set(merged).size,merged.length)
  assert.deepEqual(Array.from(ctx.reconcileKeys(merged,next)),Array.from(merged),'Repeated refresh must preserve retiring slots')
  assert.equal(merged.length,new Set([...old,...next]).size)
}
assert.equal(ctx.reconcileKeys(['a','b','c'],['a','c']).join(','),'a,b,c')
console.log('Model: stable keyed arrivals, retiring slots, reorder and revival passed')

// Rectangular tiles must fit inside the inner rounded border at both ends.
for (const thickness of [44,50,56,62]) for (const border of [0,1,2]) {
  for (const crossInset of [border+1,border+2,border+3.5,8]) for (const requested of [0,7,12,24,64]) {
    const radius=ctx.dockRadius('custom',requested,0,thickness,200)
    const end=Math.max(crossInset,ctx.dockEndInset(radius,crossInset,border))
    const inner=Math.max(0,radius-border),offset=Math.max(0,radius-crossInset)
    const along=Math.max(0,radius-end)
    assert.ok(offset*offset+along*along<=inner*inner+1e-6,
      `Tile clips its rounded end: thickness=${thickness}, radius=${radius}, inset=${crossInset}`)
    assert.ok(Number.isInteger(ctx.dockEndInset(radius,crossInset,border)))
    if (radius<=crossInset) assert.equal(end,crossInset,'Small corners must keep compact spacing')
  }
}
for (const count of [0,1,2,3,30]) {
  assert.equal(ctx.dockLength(count,44,4),count*44+Math.max(0,count-1)*4,'Docks must have no trailing gap')
}
console.log('Model: icons-only dock lengths and single-icon sizing passed')

for (const area of [{x:0,y:26,width:2560,height:1574},{x:0,y:40,width:320,height:200},{x:12,y:30,width:640,height:450}]) {
  for (const horizontal of [false,true]) for (const count of [1,3,30]) {
    for (const point of [[area.x+12,area.y+12],[area.x+area.width-12,area.y+area.height-12],[area.x+area.width/2,area.y+area.height/2]]) {
      const fan=ctx.fanLayout(...point,area,count,horizontal,48,4,3,17)
      assert.ok(point[0]>=fan.x && point[0]<=fan.x+48 && point[1]>=fan.y && point[1]<=fan.y+48,'Newest icon must cover the pointer')
      assert.ok(fan.capacity>=1 && fan.capacity<=count)
      const rects=[]
      for (let i=0;i<fan.capacity;i++) {
        const slot=ctx.fanSlot(fan,i,0)
        assert.ok(slot.shown && slot.x>=area.x && slot.y>=area.y && slot.x+48<=area.x+area.width && slot.y+48<=area.y+area.height)
        rects.push({...slot,width:48,height:48})
        const pose=ctx.fanPose(area.x+8,area.y+8,slot.x,slot.y,.5,i,fan,area)
        assert.ok(pose.bend>=0 && (fan.curveLimit===0 || pose.bend>0) && pose.x>=area.x && pose.y>=area.y && pose.x+48<=area.x+area.width && pose.y+48<=area.y+area.height)
        const end=ctx.fanPose(area.x+8,area.y+8,slot.x,slot.y,1,i,fan,area)
        assert.ok(Math.abs(end.x-slot.x)<1e-6 && Math.abs(end.y-slot.y)<1e-6)
      }
      const bounds=ctx.fanBounds(rects,3,17,horizontal,area)
      assert.ok(bounds.x>=area.x && bounds.y>=area.y && bounds.x+bounds.width<=area.x+area.width && bounds.y+bounds.height<=area.y+area.height)
      const radius=ctx.fanRadius(bounds,rects,27,1)
      for (const r of rects) for (const x of [r.x,r.x+48]) for (const y of [r.y,r.y+48]) {
        const cx=Math.max(bounds.x+radius,Math.min(bounds.x+bounds.width-radius,x))
        const cy=Math.max(bounds.y+radius,Math.min(bounds.y+bounds.height-radius,y))
        assert.ok((x-cx)**2+(y-cy)**2<=Math.max(0,radius-1)**2+.01,'Fan radius clips a square icon')
      }
      const locked=ctx.fanLayout(...point,area,count,horizontal,48,4,3,17,fan.sign)
      assert.equal(locked.sign,fan.sign)
    }
  }
}
console.log('Model: cursor-first fans, both axes, edge bounds, curved paths and safe rounded backgrounds passed')

const motion=vm.createContext({})
vm.runInContext(fs.readFileSync(__dirname+'/../ui/Motion.js','utf8').replace(/^\.pragma library\s*/,''),motion)
const styles=['arc','glide','cascade','spring','swing']
assert.equal(motion.fanProfile('unknown').name,'arc')
assert.equal(new Set(styles.map(s=>JSON.stringify(motion.fanProfile(s)))).size,5)
const sampleArea={x:0,y:26,width:1000,height:700}
const sampleFan=ctx.fanLayout(500,350,sampleArea,3,true,48,4,3,17)
const samples=styles.map(s=>ctx.fanPose(600,300,500,350,.5,2,sampleFan,sampleArea,s))
assert.equal(new Set(samples.map(p=>[p.x,p.y,p.scale,p.tilt].join(','))).size,5,'All five paths must be visually distinct')
for (const style of styles) for (const horizontal of [false,true]) {
  const profile=motion.fanProfile(style)
  assert.ok(profile.open+profile.limit<800,'Unfold must finish within the pointer-leave grace period')
  assert.equal(motion.duration('off',profile.open,100),0)
  assert.equal(motion.duration('reduced',profile.open,100),100)
  for (const point of [[12,38],[988,714],[500,350]]) {
    const fan=ctx.fanLayout(...point,sampleArea,3,horizontal,48,4,3,17)
    const slot=ctx.fanSlot(fan,2,0)
    for (const progress of [0,.15,.5,.85,1,1.08]) {
      const pose=ctx.fanPose(600,300,slot.x,slot.y,progress,2,fan,sampleArea,style)
      const radians=pose.tilt*Math.PI/180,extent=24*pose.scale*(Math.abs(Math.cos(radians))+Math.abs(Math.sin(radians)))
      assert.ok(pose.x+24-extent>=sampleArea.x-.001 && pose.x+24+extent<=1000.001)
      assert.ok(pose.y+24-extent>=sampleArea.y-.001 && pose.y+24+extent<=726.001,'Rotated icon escaped work area')
      if (progress===0 || progress===1) {
        assert.equal(pose.scale,1);assert.ok(Math.abs(pose.tilt)<1e-9)
        assert.ok(Math.abs(pose.x-(progress ? slot.x : 600))<1e-9 && Math.abs(pose.y-(progress ? slot.y : 300))<1e-9)
      }
    }
  }
}
const cascade=motion.fanProfile('cascade')
assert.ok(motion.fanDelay(cascade,2,true,3)>motion.fanDelay(cascade,0,true,3))
assert.ok(motion.fanDelay(cascade,2,false,3)<motion.fanDelay(cascade,0,false,3))
console.log('Motion: five distinct fan profiles, stable endpoints, rotated bounds, capped timing and reverse cascade passed')

for (const style of styles) for (const horizontal of [false,true]) {
  for (const origin of [{x:8,y:34},{x:944,y:662},{x:500.375,y:350.625}]) {
    for (const offset of [2,9,41,46]) {
      const fan=ctx.fanLayout(origin.x+offset,origin.y+offset,sampleArea,3,horizontal,48,4,3,17,0,0,origin)
      assert.equal(fan.x,origin.x);assert.equal(fan.y,origin.y)
      const slot=ctx.fanSlot(fan,0,0)
      for (let frame=0;frame<=108;frame++) {
        const p=ctx.fanPose(origin.x,origin.y,slot.x,slot.y,frame/100,0,fan,sampleArea,style)
        assert.equal(p.x,origin.x,'Front icon must never translate, including during overshoot')
        assert.equal(p.y,origin.y)
        assert.equal(p.bend,0)
        assert.ok(Math.abs(p.tilt)<=1 && p.scale>=.979 && p.scale<=1,'Front effect must remain subtle')
      }
    }
  }
}
console.log('Motion: original icon stays fixed for every style, axis, click offset and fractional anchor')

// Horizontal curves always lift relative to their straight path, including a
// leftward fan and an already-open fan carrying an old downward preference.
// The collapsed tail starts below the anchor, so compare against its moving
// straight baseline rather than the anchor itself.
for (const area of [sampleArea,{x:-1000.5,y:73.25,width:1000,height:600}]) {
  for (const topRoom of [0,2,8.625,22.5,90.625,area.height-56]) {
    const anchor={x:area.x+500.375,y:area.y+topRoom}
    for (const sign of [-1,1]) for (const preferredCurve of [-1,0,1]) {
      const fan=ctx.fanLayout(anchor.x+24,anchor.y+24,area,5,true,48,4,3,17,sign,preferredCurve,anchor)
      assert.equal(fan.sign,sign)
      assert.equal(fan.capacity,5)
      assert.equal(fan.curveSign,-1,'Horizontal curvature must ignore a stale downward preference')
      assert.equal(fan.hopSign,-1,'Horizontal hops must always lift')
      assert.equal(fan.curveLimit,Math.max(0,Math.min(18,topRoom-3)),'Curve must use only room above the usable area')
      assert.equal(fan.hopLimit,Math.max(0,Math.min(28,topRoom-3)),'Hop must use only room above the usable area')
      for (const style of styles) for (let i=0;i<fan.capacity;i++) {
        const start={x:anchor.x,y:anchor.y+Math.min(i,2)*4},end=ctx.fanSlot(fan,i,0),opening=[]
        for (let frame=0;frame<=20;frame++) {
          const p=frame/20,line=ctx.fanPose(start.x,start.y,end.x,end.y,p,i,fan,area,'glide')
          const pose=ctx.fanPose(start.x,start.y,end.x,end.y,p,i,fan,area,style)
          opening.push(pose)
          assert.ok(Math.abs(pose.x-line.x)<1e-8,'Horizontal curve changed axial travel')
          assert.ok(pose.y<=line.y+1e-8,'Horizontal curve bent below its straight path')
          assert.ok(Math.abs(pose.y-(line.y-pose.bend))<1e-8,'Top clipping changed the upward curve')
          assert.ok(pose.y>=area.y && pose.y+48<=area.y+area.height,'Upward curve escaped the usable area')
          if (i===0) {
            assert.equal(pose.x,anchor.x);assert.equal(pose.y,anchor.y);assert.equal(pose.bend,0)
          }
          if (frame===0 || frame===20) {
            const endpoint=frame===0 ? start : end
            assert.equal(pose.x,endpoint.x);assert.equal(pose.y,endpoint.y)
            assert.equal(pose.bend,0)
          }
          if (topRoom<=3 || style==='glide' || style==='cascade') assert.equal(pose.bend,0,'No room above must flatten the curve instead of bending downward')
          else if (i>0 && frame===10) assert.ok(pose.bend>0,'Available space above must produce an upward arch')
        }
        for (let frame=20;frame>=0;frame--) {
          const p=ctx.fanPose(start.x,start.y,end.x,end.y,frame/20,i,fan,area,style)
          assert.equal(p.x,opening[frame].x);assert.equal(p.y,opening[frame].y);assert.equal(p.bend,opening[frame].bend)
        }
      }
    }
  }
}
console.log('Motion: horizontal curves always lift in both directions, flatten at reserved top edges, and retrace with fixed endpoints')
