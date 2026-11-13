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

for(const titles of [false,true]) for(const frame of [false,true]) {
  for(const source of [record,{size:[100,5000]},{size:[5000,100]}]) {
    const initial=geometry.dimensions(280,source,area,titles,frame)
    // Keep extreme cards inside the work area before testing both anchors.
    const original={x:area.x+(area.width-initial.width)/2,y:area.y+(area.height-initial.height)/2,width:initial.width,height:initial.height}
    const restore=JSON.stringify(source)
    for(const corner of ['top-left','top-right','bottom-left','bottom-right']) {
      for(const delta of [[0,0],[90,5],[5,90],[-100000,100000],[100000,-100000],[100000,100000],[-100000,-100000]]) {
        const result=geometry.resize(original,source,area,...delta,corner,titles,frame,0,true)
        bounded(result,area)
        assert.ok(result.aspect>=.02 && result.aspect<=50)
        near((result.width-initial.inset*2)/(result.height-initial.header-initial.inset*2),result.aspect)
        near(corner.includes('left') ? result.x+result.width : result.x,corner.includes('left') ? original.x+original.width : original.x)
        near(corner.includes('top') ? result.y+result.height : result.y,corner.includes('top') ? original.y+original.height : original.y)
        if(delta.every(value=>value===0)) for(const key of ['x','y','width','height']) near(result[key],original[key])
        assert.equal(JSON.stringify(source),restore,'Free corner resizing changed original restore geometry')
      }
    }
  }
  const initial=geometry.dimensions(280,record,area,titles,frame)
  const original={x:400,y:250,width:initial.width,height:initial.height}
  for(const corner of ['top-left','top-right','bottom-left','bottom-right']) {
    const dx=corner.includes('left') ? -60 : 60,dy=corner.includes('top') ? -15 : 15
    const result=geometry.resize(original,record,area,dx,dy,corner,titles,frame,0,true)
    near(result.width,original.width+60);near(result.height,original.height+15)
    assert.ok(Math.abs(result.aspect-initial.aspect)>.01,'Free corner retained the original aspect')
  }
}
console.log('Floating preview free corners: independent dimensions, all opposite anchors, chrome, aspect limits, small shapes and monitor bounds passed')

for(const titles of [false,true]) for(const frame of [false,true]) {
  const initial=geometry.dimensions(280,record,area,titles,frame)
  const original={x:400,y:250,width:initial.width,height:initial.height}
  const restore=JSON.stringify(record)
  for(const edge of ['left','right','top','bottom']) for(const delta of [[0,0],[110,75],[-10000,-10000],[10000,10000]]) {
    const rect=geometry.resize(original,record,area,...delta,edge,titles,frame)
    bounded(rect,area)
    near((rect.width-initial.inset*2)/(rect.height-initial.header-initial.inset*2),rect.aspect)
    if(edge==='left' || edge==='right') {
      near(rect.y,original.y);near(rect.height,original.height)
      near(edge==='left' ? rect.x+rect.width : rect.x,edge==='left' ? original.x+original.width : original.x)
    } else {
      near(rect.x,original.x);near(rect.width,original.width)
      near(edge==='top' ? rect.y+rect.height : rect.y,edge==='top' ? original.y+original.height : original.y)
    }
    if(delta.every(value=>value===0)) for(const key of ['x','y','width','height']) near(rect[key],original[key])
    for(const corner of ['top-left','top-right','bottom-left','bottom-right']) {
      const scaled=geometry.resize(rect,record,area,35,25,corner,titles,frame,rect.aspect)
      bounded(scaled,area)
      near((scaled.width-initial.inset*2)/(scaled.height-initial.header-initial.inset*2),rect.aspect)
    }
    assert.equal(JSON.stringify(record),restore,'Changing preview proportions mutated original restore geometry')
  }
}
// Naturally narrow/short cards must not jump to the normal minimum on press.
for(const size of [[100,5000],[5000,100]]) {
  const natural=geometry.dimensions(280,{size},area,false,false)
  const rect={x:area.x,y:area.y,width:natural.width,height:natural.height}
  for(const edge of ['left','right','top','bottom']) {
    const result=geometry.resize(rect,{size},area,0,0,edge,false,false)
    for(const key of ['x','y','width','height']) near(result[key],rect[key])
  }
}
console.log('Floating preview proportions: anchored side drags, chrome-aware ratio, proportional custom corners and no press jumps passed')

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

const customSaved={'preview:window:0':[300,250,350,2.4]}
for(const titles of [false,true]) for(const frame of [false,true]) for(const sizing of ['free','preset']) {
  const custom=geometry.layout(groups.slice(0,1),customSaved,{},area,{edges:false,titles,frame,sizing,scale:50})
  const value=custom.cards['preview:window:0'],c=geometry.chrome(titles,frame)
  near(value.aspectOverride,2.4)
  near((value.width-c.inset*2)/(value.height-c.header-c.inset*2),2.4)
  near(value.width,sizing==='free' ? 350 : 140)
}
for(const invalid of [0,-1,NaN,Infinity,.001,1000,'invalid']) {
  const value=geometry.layout(groups.slice(0,1),{'preview:window:0':[300,250,350,invalid]}, {},area,{edges:false}).cards['preview:window:0']
  near(value.aspectOverride,0);near(value.width/value.height,640/420)
}
assert.deepEqual(customSaved['preview:window:0'],[300,250,350,2.4])
console.log('Floating preview proportions: optional saved content ratio survives chrome/preset changes; legacy and malformed tuples stay natural')

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

const original={id:'tiled',size:[600,900],pid:42,address:'0x42'}
const observed={tiled:[1200,600]}
const adjusted=geometry.geometryRecord(original,observed)
assert.notEqual(adjusted,original)
assert.deepEqual(Array.from(adjusted.size),[1200,600])
assert.deepEqual(original.size,[600,900],'Capturing a tiled client mutated its restore dimensions')
assert.equal(adjusted.pid,original.pid)
assert.equal(adjusted.address,original.address)
assert.equal(geometry.geometryRecord(original,{}),original,'An uncaptured window lost its fallback original dimensions')
assert.ok(geometry.sameAspect([1200,600],[2400,1200]),'Same-aspect resolution change should not reflow')
assert.ok(!geometry.sameAspect([1200,600],[1200,900]))
assert.ok(!geometry.sameAspect([0,0],[1200,600]))
const geometryGroups=geometry.geometryGroups([{key:'app:test',windows:[original]}],observed)
const adapted=geometry.layout(geometryGroups,{}, {},area,{edges:false})
near(adapted.cards['preview:app:test'].width/adapted.cards['preview:app:test'].height,2)
const groupAdapted=geometry.groupGrid([adjusted],{x:900,y:200,width:280,height:140},area,false,false,280)
near(groupAdapted.cells.tiled.width/groupAdapted.cells.tiled.height,2)
const resizedAdapted=geometry.resize({x:200,y:200,width:280,height:140},adjusted,area,90,45,'bottom-right',false,false)
near(resizedAdapted.width/resizedAdapted.height,2)
assert.deepEqual(original.size,[600,900])
console.log('Floating preview capture geometry: verified source aspect drives layout, group tiles and resize without changing restore records')
