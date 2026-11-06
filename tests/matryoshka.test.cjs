const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
function library(name) {
  const context = vm.createContext({})
  vm.runInContext(fs.readFileSync(__dirname + '/../ui/' + name + '.js', 'utf8').replace(/^\.pragma library\s*/, ''), context)
  return context
}
const model = library('Model'), motion = library('Motion')
const styles = ['matryoshka', 'matryoshka-hop']
const close = (a, b, why) => assert.ok(Math.abs(a-b) < 1e-8, `${why}: ${a} != ${b}`)
const samePoint = (a, b, why) => { close(a.x, b.x, why+' x'); close(a.y, b.y, why+' y') }
function scene(area, anchor, count, horizontal, sign, preferredCurve = 0) {
  const layout = model.fanLayout(anchor.x+24, anchor.y+24, area, count, horizontal, 48, 4, 3, 17, sign, preferredCurve, anchor)
  return {area, anchor, layout}
}
function pose(s, index, progress, style, first = 0, count = s.layout.capacity) {
  const slot = model.fanSlot(s.layout, index, first)
  return model.fanChainPose(s.anchor.x, s.anchor.y+Math.min(index,2)*4,
    slot.x, slot.y, progress, index, s.layout, s.area, style, first, count)
}
const largeArea = {x:12, y:34, width:1000, height:720}

// A group shares one base position. Its small preview offsets are the only
// separation until its lead icon lands and the remainder starts the next leg.
for (const horizontal of [false, true]) for (const sign of [-1, 1]) {
  const s = scene(largeArea, {x:500.375, y:350.625}, 5, horizontal, sign)
  assert.equal(s.layout.capacity, 5)
  for (const style of styles) for (let stage = 0; stage < 4; stage++) {
    const p = (stage+.43)/4
    let base = null
    for (let i = 0; i < 5; i++) {
      const a = pose(s, i, p, style)
      assert.equal(a.stage, stage)
      assert.equal(a.targetSlot, i)
      assert.equal(a.settled, i <= stage)
      if (i <= stage) {
        assert.equal(a.slot,i)
        samePoint(a, model.fanSlot(s.layout, i, 0), 'Deposited icon moved')
      }
      else {
        assert.ok(a.slot>stage && a.slot<stage+1,'Group travel should expose one continuous slot')
        const groupBase = {x:a.x, y:a.y-a.groupOffset}
        if (base) samePoint(groupBase, base, 'Remainder split into independent paths')
        else base = groupBase
        assert.ok(a.groupOffset >= 0 && a.groupOffset <= 8)
      }
    }
    // All actors reach their landing together, then visibly pause before the
    // following leg. One more icon remains deposited after every landing.
    for (let i = 1; i < 5; i++) {
      samePoint(pose(s,i,(stage+.90)/4,style), pose(s,i,(stage+.99)/4,style), 'Landing dwell drifted')
      samePoint(pose(s,i,(stage+1)/4,style), pose(s,i,(stage+.99)/4,style), 'Stage boundary jumped')
      if (i <= stage+1) samePoint(pose(s,i,(stage+.99)/4,style), model.fanSlot(s.layout,i,0), 'Lead did not stay behind')
    }
    if (stage < 3) {
      const lead = stage+1
      samePoint(pose(s,lead,(stage+1.43)/4,style), model.fanSlot(s.layout,lead,0), 'Next leg picked deposited lead back up')
      const next = pose(s,lead+1,(stage+1.43)/4,style)
      assert.ok(Math.abs((horizontal ? next.x : next.y)-(horizontal ? s.layout.x : s.layout.y)-sign*(stage+1)*52) > 1,
        'Remainder did not leave its deposited lead')
    }
  }
}
console.log('Matryoshka: synchronous groups, successive deposits, layered previews, and landing dwell passed')

// Every hop follows an arch, while the straight variant follows the same
// landing positions without a cross-axis excursion. The original icon stays
// anchored through all stages, regardless of click offset or floating pixels.
for (const horizontal of [false, true]) for (const sign of [-1, 1]) {
  const s = scene(largeArea, {x:500.375, y:350.625}, 5, horizontal, sign)
  for (let stage = 0; stage < 4; stage++) {
    const p = (stage+.43)/4
    for (let i = stage+1; i < 5; i++) {
      const line = pose(s,i,p,'matryoshka'), hop = pose(s,i,p,'matryoshka-hop')
      assert.equal(line.bend, 0)
      close(hop.bend, 28, 'Hop should lift the entire group')
      close(horizontal ? hop.x : hop.y, horizontal ? line.x : line.y, 'Arch changed axial travel')
      close(horizontal ? hop.y-line.y : hop.x-line.x, s.layout.hopSign*hop.bend, 'Arch direction differs within group')
    }
  }
  for (const style of styles) for (let frame = 0; frame <= 100; frame++) {
    const a = pose(s,0,frame/100,style)
    samePoint(a,s.anchor,'Original icon translated')
    assert.equal(a.bend,0); assert.equal(a.tilt,0)
    assert.ok(a.scale>=.992 && a.scale<=1,'Original icon effect exceeds subtle pulse')
  }
}
assert.equal(scene(largeArea,{x:500,y:350},3,true,1).layout.hopSign,-1,'Horizontal hop should lift where there is room')
const nearTop=scene(largeArea,{x:500,y:largeArea.y+8},3,true,1)
assert.equal(nearTop.layout.hopSign,-1,'Top edge should reduce lift without reversing the arch')
assert.equal(nearTop.layout.hopLimit,5,'Top edge must cap lift to the space above the stack')
assert.equal(scene(largeArea,{x:largeArea.x+8,y:350},3,false,1).layout.hopSign,1,'Left edge should send vertical hop right')
assert.equal(scene(largeArea,{x:largeArea.x+largeArea.width-56,y:350},3,false,1).layout.hopSign,-1,'Right edge should send vertical hop left')
console.log('Matryoshka: straight paths, upward horizontal arches, inward vertical direction, and fixed fractional anchor passed')

// Near a reserved top edge the whole remaining stack shares the same smaller
// upward arch. It must never flip downward or flatten individual tail icons by
// clipping, even when restoring a stale downward curve preference.
for (const area of [largeArea,{x:-1000.5,y:73.25,width:1000,height:600}]) {
  for (const topRoom of [0,2,8.625,22.5,90.625]) {
    const anchor={x:area.x+500.375,y:area.y+topRoom}
    for (const sign of [-1,1]) for (const preferredCurve of [-1,0,1]) {
      const s=scene(area,anchor,5,true,sign,preferredCurve)
      assert.equal(s.layout.capacity,5)
      assert.equal(s.layout.hopSign,-1,'Leftward and rightward groups must both hop upward')
      close(s.layout.hopLimit,Math.max(0,Math.min(28,topRoom-3)),'Hop used space below the stack')
      const opening=[]
      for (let frame=0;frame<=100;frame++) {
        const p=frame/100,actors=[]
        let base=null
        for (let i=0;i<5;i++) {
          const line=pose(s,i,p,'matryoshka'),hop=pose(s,i,p,'matryoshka-hop')
          actors.push(hop)
          close(hop.x,line.x,'Upward hop changed horizontal travel')
          assert.ok(hop.y<=line.y+1e-8,'Horizontal group hopped below its straight path')
          close(hop.y,line.y-hop.bend,'Work-area clipping distorted the group arch')
          assert.ok(hop.y>=area.y-1e-8 && hop.y+48<=area.y+area.height+1e-8,'Upward group escaped the usable area')
          if (i===0) samePoint(hop,anchor,'Front icon moved during an upward hop')
          if (frame===0) samePoint(hop,{x:anchor.x,y:anchor.y+Math.min(i,2)*4},'Upward hop changed collapsed endpoint')
          if (frame===100) samePoint(hop,model.fanSlot(s.layout,i,0),'Upward hop changed expanded endpoint')
          if (!hop.settled) {
            const groupBase={x:hop.x,y:hop.y-hop.groupOffset}
            if (base) samePoint(groupBase,base,'Capped upward arch split the remaining stack')
            else base=groupBase
          }
        }
        opening.push(actors)
      }
      for (let stage=0;stage<4;stage++) {
        const apex=pose(s,stage+1,(stage+.43)/4,'matryoshka-hop')
        close(apex.bend,s.layout.hopLimit,'Every leg must share the available upward lift')
      }
      for (let frame=100;frame>=0;frame--) for (let i=0;i<5;i++) {
        const hop=pose(s,i,frame/100,'matryoshka-hop')
        samePoint(hop,opening[frame][i],'Folding retraced a different upward group path')
        close(hop.bend,opening[frame][i].bend,'Folding changed upward arch amplitude')
      }
    }
  }
}
console.log('Matryoshka: both horizontal directions preserve upward group arches at fractional and reserved top edges')

// Sample complete trajectories on every axis, direction, work-area edge, and
// overflow count. The shared pose has no direction-dependent state, so
// gathering must retrace precisely the same path, including partial reversals.
for (const area of [largeArea,{x:21,y:48,width:320,height:200},{x:0,y:26,width:130,height:114}]) {
  const anchors = [
    {x:area.x+8,y:area.y+8},
    {x:area.x+area.width-56,y:area.y+8},
    {x:area.x+8,y:area.y+area.height-56},
    {x:area.x+area.width-56,y:area.y+area.height-56},
    {x:area.x+area.width/2-24+.375,y:area.y+area.height/2-28+.625}
  ]
  for (const anchor of anchors) for (const horizontal of [false,true]) for (const sign of [-1,1]) {
    for (const total of [1,2,3,50]) {
      const s=scene(area,anchor,total,horizontal,sign)
      for (const style of styles) for (const first of [0,Math.max(0,total-s.layout.capacity)]) {
        for (const p of [.03,.12,.45,.79,.96]) {
          let base=null
          for(let i=first;i<first+s.layout.capacity;i++) {
            const a=pose(s,i,p,style,first)
            if(a.settled) continue
            const b={x:a.x,y:a.y-a.groupOffset}
            if(base) samePoint(b,base,'Work-area bounds distorted the group silhouette')
            else base=b
          }
        }
        for (let i=first;i<first+s.layout.capacity;i++) {
          const collapsed={x:anchor.x,y:anchor.y+Math.min(i,2)*4},destination=model.fanSlot(s.layout,i,first)
          samePoint(pose(s,i,0,style,first),collapsed,'Collapsed endpoint changed')
          samePoint(pose(s,i,1,style,first),destination,'Expanded endpoint changed')
          const opening=[]
          for(let frame=0;frame<=100;frame++) {
            const p=frame/100,a=pose(s,i,p,style,first)
            opening.push(a)
            assert.ok(Number.isFinite(a.x+a.y+a.scale+a.bend))
            assert.ok(a.x>=area.x-1e-8 && a.x+48<=area.x+area.width+1e-8,'Chain escaped horizontal work area')
            assert.ok(a.y>=area.y-1e-8 && a.y+48<=area.y+area.height+1e-8,'Chain escaped vertical work area')
            assert.ok(a.scale>0 && a.scale<=1 && a.tilt===0)
          }
          for(let frame=100;frame>=0;frame--) {
            const a=pose(s,i,frame/100,style,first),b=opening[frame]
            samePoint(a,b,'Collection follows a different path'); close(a.bend,b.bend,'Reverse arch changed')
          }
          // A paging Behavior can continue changing the supplied destination
          // after the shared timeline has finished.
          const a=model.fanChainPose(anchor.x,collapsed.y,destination.x+.25,destination.y+.5,1,i,s.layout,area,style,first)
          samePoint(a,{x:destination.x+.25,y:destination.y+.5},'Full-open pose stopped following destination')
        }
      }
    }
  }
}
console.log('Matryoshka: exact endpoints, overflow pages, one-icon fans, bounded tail height, and reverse trajectories passed')

const legacy = {
  arc:{name:'arc',open:330,close:280,stagger:14,limit:72,easing:'back',overshoot:.45},
  glide:{name:'glide',open:260,close:220,stagger:0,limit:0,easing:'cubic',overshoot:0},
  cascade:{name:'cascade',open:340,close:260,stagger:48,limit:192,easing:'quint',overshoot:0},
  spring:{name:'spring',open:460,close:340,stagger:18,limit:90,easing:'back',overshoot:1.5},
  swing:{name:'swing',open:390,close:310,stagger:22,limit:110,easing:'cubic',overshoot:0}
}
for(const [style,expected] of Object.entries(legacy)) {
  const profile=motion.fanProfile(style)
  assert.deepEqual(JSON.parse(JSON.stringify(profile)),expected,'Existing profile changed')
  assert.equal(motion.chain(style),false)
  for(const count of [1,2,5,30]) for(const opening of [false,true]) {
    const old=(opening?expected.open:expected.close)+Math.min(expected.limit,(count-1)*expected.stagger)
    assert.equal(motion.fanDuration(profile,opening,count),old,'Existing total timing changed')
  }
}
assert.equal(motion.fanProfile('unknown').name,'arc')
for(const style of styles) {
  const profile=motion.fanProfile(style),hop=style==='matryoshka-hop'
  assert.equal(motion.chain(style),true); assert.equal(profile.chain,true)
  for(const count of [0,1,2,3,5,30]) for(const opening of [false,true]) {
    const expected=count<=1 ? (hop?210:180) : Math.min(opening?(hop?740:680):(hop?680:600),(count-1)*(opening?(hop?210:170):(hop?190:150)))
    assert.equal(motion.fanDuration(profile,opening,count),expected)
    for(const ordinal of [0,1,4,29]) assert.equal(motion.fanDelay(profile,ordinal,opening,count),0,'Chain actors must use one unstaggered clock')
  }
}
console.log('Motion: seven profiles, bounded chain duration, one shared clock, and unchanged legacy timing passed')
