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
for (const [w,h] of [[640,360],[1920,1080],[320,240]]) {
  for (const saved of [[8,32],[w-56,h-64],[w/2,h/2]]) {
    const [x,y]=ctx.floatingAnchor(saved,w,h)
    for (const count of [1,3,30]) {
      const p=ctx.floatingPanel(x,y,56,w,h,count,5,8,44,30)
      assert.ok(p.x>=8 && p.x+p.width<=w-8)
      assert.ok(p.y>=8 && p.y+p.height<=h-8)
      assert.ok(p.height>0)
      assert.ok(p.down ? p.y>=y+56 : p.y+p.height<=y)
    }
  }
}
console.log('Model: floating anchor, expansion bounds, and overflow geometry passed')

for (const scale of [1,1.25,1.5,2]) for (const frame of [44,48]) {
  const size=ctx.alignedIconSize(frame,28,scale)
  const pixels=Math.round(size*scale)
  assert.ok(Math.abs(size*scale-pixels)<1e-6)
  assert.equal((Math.round(frame*scale)-pixels)%2,0,'Artwork must be centered without half-pixel offsets')
}
const locked=ctx.floatingPanel(500,500,56,1920,1080,100,9,8,44,30,true)
assert.equal(locked.down,true)
assert.ok(locked.y+locked.height<=1072,'An open dock grows into scrolling instead of jumping sides')
console.log('Model: crisp centered artwork and stable expansion direction passed')

for (const [w,h] of [[320,240],[640,360],[1920,1080]]) {
  for (const saved of [[8,32],[w-56,h-64],[w/2,h/2]]) {
    const [x,y]=ctx.floatingAnchor(saved,w,h)
    for (const count of [1,3,30]) {
      const p=ctx.floatingPanel(x,y,56,w,h,count,9,8,44,33,undefined,true)
      assert.ok(p.x>=8 && p.x+p.width<=w-8)
      assert.ok(p.y>=8 && p.y+p.height<=h-8)
      assert.ok(p.width>0)
      assert.ok(p.forward ? p.x>=x+48 : p.x+p.width<=x)
    }
  }
}
assert.equal(ctx.floatingPanel(8,400,56,1920,1080,5,9,8,44,33,undefined,true).right,true)
assert.equal(ctx.floatingPanel(1864,400,56,1920,1080,5,9,8,44,33,undefined,true).right,false)
console.log('Model: horizontal dock bounds and left/right expansion passed')

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
