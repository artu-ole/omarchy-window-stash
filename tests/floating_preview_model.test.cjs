const assert=require('node:assert/strict')
const fs=require('node:fs')
const vm=require('node:vm')
const geometry=vm.createContext({})
vm.runInContext(fs.readFileSync(__dirname+'/../ui/FloatingPreviewModel.js','utf8').replace(/^\.pragma library\s*/,''),geometry)
const near=(a,b)=>assert.ok(Math.abs(a-b)<1e-6,`${a} != ${b}`)
function bounded(rect,area) {
  for(const name of ['x','y','width','height']) assert.ok(Number.isFinite(rect[name]),name)
  assert.ok(rect.width>0 && rect.height>0)
  assert.ok(rect.x>=area.x-1e-6 && rect.y>=area.y-1e-6)
  assert.ok(rect.x+rect.width<=area.x+area.width+1e-6)
  assert.ok(rect.y+rect.height<=area.y+area.height+1e-6)
}
const overlaps=(a,b)=>a.x<b.x+b.width-1e-6 && a.x+a.width>b.x+1e-6 && a.y<b.y+b.height-1e-6 && a.y+a.height>b.y+1e-6
const record={id:'a',size:[640,420]}
const area={x:12,y:26,width:1280,height:774}
for(const titles of [false,true]) for(const frame of [false,true]) for(const size of [[640,420],[420,640],[100,3000],[3000,100]]) {
  const source={id:'source',size}
  for(const width of [1,80,280,840,100000]) {
    const dimensions=geometry.dimensions(width,source,area,titles,frame)
    near((dimensions.width-dimensions.inset*2)/(dimensions.height-dimensions.header-dimensions.inset*2),size[0]/size[1])
    bounded({...dimensions,x:area.x,y:area.y},area)
  }
}
console.log('Floating preview sizing: original aspect, optional chrome and monitor bounds passed')

for(const corner of ['top-left','top-right','bottom-left','bottom-right']) for(const delta of [[90,60],[-700,-500],[100000,100000]]) {
  const original={x:400,y:250,width:280,height:280*420/640}
  const saved=JSON.stringify(original)
  const rect=geometry.resize(original,record,area,...delta,corner,false,false)
  bounded(rect,area)
  near(rect.width/rect.height,640/420)
  if(corner.includes('left')) near(rect.x+rect.width,original.x+original.width)
  else near(rect.x,original.x)
  if(corner.includes('top')) near(rect.y+rect.height,original.y+original.height)
  else near(rect.y,original.y)
  assert.equal(JSON.stringify(original),saved,'Resize mutated the source window geometry')
}
console.log('Floating preview resizing: all corners hold their opposite anchor without changing source geometry')

const groups=Array.from({length:40},(_,i)=>({key:'window:'+i,windows:[{id:String(i),size:[640,420]}]}))
const saved={'preview:window:0':[300,250,350],'window:0':[900,600]}
for(const edges of [false,true]) for(const tiny of [area,{x:0,y:26,width:320,height:214},{x:0,y:0,width:50,height:40}]) {
  const seen=new Set()
  const initial=geometry.layout(groups,saved,{},tiny,{edges})
  for(let page=0;page<initial.pages;page++) {
    const layout=geometry.layout(groups,saved,{},tiny,{edges,page})
    const visible=Object.entries(layout.cards).filter(([,card])=>card.visible)
    assert.ok(visible.length>0 && visible.length<=layout.capacity)
    for(const [key,card] of visible) {bounded(card,tiny);assert.ok(!seen.has(key));seen.add(key)}
    for(let i=0;i<visible.length;i++) for(let j=0;j<i;j++) assert.ok(!overlaps(visible[i][1],visible[j][1]),'Saved and new cards overlap')
    // Unpositioned slots do not overlap, even when a stash exceeds a monitor.
    const unsaved=visible.filter(([key])=>!saved[key]).map(([,card])=>card)
    for(let i=0;i<unsaved.length;i++) for(let j=0;j<i;j++) assert.ok(!overlaps(unsaved[i],unsaved[j]))
  }
  assert.equal(seen.size,groups.length,'Overflow lost access to a window')
}
const remembered=geometry.layout(groups.slice(0,1),saved,{},area,{edges:false})
near(remembered.cards['preview:window:0'].width,350)
near(remembered.cards['preview:window:0'].x,300)
near(remembered.cards['preview:window:0'].y,250)
const preset=geometry.layout(groups.slice(0,1),saved,{},area,{sizing:'preset',scale:50})
near(preset.cards['preview:window:0'].width,140)
const direct=geometry.layout(groups.slice(0,1),saved,{},area,{sizing:'free',scale:50})
near(direct.cards['preview:window:0'].width,350)
console.log('Floating preview placement: independent saved dimensions, preset/free modes and accessible paged overflow passed')

const baseline=geometry.layout(groups.slice(0,2),{}, {},area,{edges:false})
const occupied=baseline.cards['preview:window:1']
const occupiedSave={'preview:window:0':[occupied.x,occupied.y,occupied.width]}
const placed=geometry.layout(groups.slice(0,2),occupiedSave,{},area,{edges:false})
near(placed.cards['preview:window:0'].x,occupied.x)
near(placed.cards['preview:window:0'].y,occupied.y)
assert.ok(!overlaps(placed.cards['preview:window:0'],placed.cards['preview:window:1']),'New card covered an existing saved card')
for(const card of Object.values(geometry.layout(groups.slice(0,10),{}, {},area,{edges:true}).cards)) {
  const mx=Math.min(8,(area.width-card.width)/2),my=Math.min(8,(area.height-card.height)/2)
  assert.ok(Math.abs(card.x-area.x-mx)<1e-6 || Math.abs(card.x+card.width-area.x-area.width+mx)<1e-6 || Math.abs(card.y-area.y-my)<1e-6 || Math.abs(card.y+card.height-area.y-area.height+my)<1e-6,'Edge gravity placed a resting card in the interior')
}
console.log('Floating preview allocation: saved-card priority, collision-free new slots and true edge placement passed')

for(const count of [2,3,8,32]) {
  const records=groups.slice(0,count).map(group=>group.windows[0])
  const grid=geometry.groupGrid(records,{x:900,y:200,width:280,height:184},area,false,false,280)
  bounded(grid,area)
  assert.equal(Object.keys(grid.cells).length,count)
  assert.ok(grid.columns>1,'A roomy monitor must show grouped windows side by side')
  const cells=Object.values(grid.cells)
  for(let i=0;i<cells.length;i++) {
    near(cells[i].width/cells[i].height,640/420)
    assert.ok(cells[i].x+cells[i].width<=grid.width+1e-6)
    assert.ok(cells[i].y+cells[i].height<=grid.contentHeight+1e-6)
    for(let j=0;j<i;j++) assert.ok(!overlaps(cells[i],cells[j]))
  }
  assert.equal(grid.overflow,grid.contentHeight>grid.height+.01)
}
assert.equal(geometry.aspect({size:[0,0]}),1.6)
assert.equal(geometry.aspect(null),1.6)
console.log('Floating preview groups: wrapping exact-window tiles, aspect preservation and explicit scroll overflow passed')
