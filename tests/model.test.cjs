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
        assert.ok(pose.bend>0 && pose.x>=area.x && pose.y>=area.y && pose.x+48<=area.x+area.width && pose.y+48<=area.y+area.height)
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
