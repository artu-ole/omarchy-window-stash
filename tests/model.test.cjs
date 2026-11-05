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
