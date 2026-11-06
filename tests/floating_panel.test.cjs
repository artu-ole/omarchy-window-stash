const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
function library(name) {
  const context = vm.createContext({})
  vm.runInContext(fs.readFileSync(__dirname+'/../ui/'+name+'.js', 'utf8').replace(/^\.pragma library\s*/, ''), context)
  return context
}
const model = library('Model'), motion = library('Motion')
const styles = ['arc', 'glide', 'cascade', 'spring', 'swing', 'matryoshka', 'matryoshka-hop']
const near = (actual, expected, why) => assert.ok(Math.abs(actual-expected)<1e-7, `${why}: ${actual} != ${expected}`)
const plain = value => JSON.parse(JSON.stringify(value))
function eased(time, style) {
  const profile = motion.fanProfile(style)
  if (profile.chain) return time
  if (profile.easing === 'back') {
    const t = time-1, s = profile.overshoot
    return 1+t*t*((s+1)*t+s)
  }
  return 1-Math.pow(1-time, profile.easing === 'quint' ? 5 : 3)
}
function rects(layout, area, progress, style) {
  return Array.from({length:layout.capacity}, (_, i) => {
    const destination = model.fanSlot(layout, i, 0)
    const args = [layout.x, layout.y+Math.min(i, 2)*4, destination.x, destination.y, progress, i, layout, area, style]
    const pose = motion.chain(style) ? model.fanChainPose(...args, 0, layout.capacity) : model.fanPose(...args)
    return {...pose, width:48, height:48}
  })
}
function frame(rectangles, layout, area) {
  const projected = model.fanPanelRects(rectangles, layout)
  const bounds = model.fanBounds(projected, 3, 17, layout.horizontal, area)
  const slots = Array.from({length:layout.capacity}, (_,i) => ({...model.fanSlot(layout,i,0),width:48,height:48}))
  const finalBounds = model.fanBounds(slots, 3, 17, layout.horizontal, area)
  const radius = Math.min(model.fanRadius(finalBounds,slots,27,1),bounds.width/2,bounds.height/2)
  return {projected, bounds, radius}
}
assert.equal(model.fanPanelRects([], {capacity:3}).length, 0)
assert.equal(model.fanPanelRects([{x:0,y:0}], {capacity:0}).length, 0)

for (const area of [{x:12,y:34,width:1000,height:720}, {x:0,y:40,width:320,height:200}]) {
  const anchors = [{x:area.x+area.width/2+.375,y:area.y+area.height/2+.625},
    {x:area.x+8.125,y:area.y+8.375}, {x:area.x+area.width-56.125,y:area.y+area.height-64.375}]
  for (const anchor of anchors) for (const horizontal of [false, true]) for (const sign of [-1, 1]) {
    const layout = model.fanLayout(anchor.x+19, anchor.y+31, area, 5, horizontal, 48, 4, 3, 17, sign, 0, anchor)
    for (const style of styles) {
      const frames = []
      for (let i=0;i<=120;i++) {
        const live = rects(layout, area, eased(i/120, style), style)
        const before = plain(live)
        const current = frame(live, layout, area)
        assert.deepEqual(plain(live), before, 'Panel projection mutated icon animation poses')
        for (const r of current.projected) {
          near(horizontal ? r.y : r.x, horizontal ? layout.y : layout.x, 'Panel left the straight rail')
          assert.equal(r.width,48); assert.equal(r.height,48)
        }
        // Cross-axis jumps, tilt metadata and decorative lag must not affect chrome.
        const noisy = live.map((r,j) => ({...r,
          [horizontal ? 'y' : 'x']:r[horizontal ? 'y' : 'x']+Math.sin(i*.4+j)*75,
          width:44+j, height:60-j}))
        assert.deepEqual(plain(frame(noisy,layout,area)), plain(current), 'Airborne artwork resized the panel')
        frames.push(current)
      }
      const first = frames[0], last = frames.at(-1)
      let length = -Infinity
      for (const current of frames) {
        const b = current.bounds, f = first.bounds
        near(horizontal ? b.y : b.x, horizontal ? f.y : f.x, 'Cross-axis panel position changed')
        near(horizontal ? b.height : b.width, horizontal ? f.height : f.width, 'Panel thickness pulsed')
        near(current.radius, first.radius, 'Panel radius pulsed')
        const next = horizontal ? b.width : b.height
        assert.ok(next>=length-1e-7, `Panel contracted while unfolding ${style}/${horizontal}/${sign}: ${next}<${length}`)
        length = next
        assert.ok(b.x>=area.x && b.y>=area.y && b.x+b.width<=area.x+area.width && b.y+b.height<=area.y+area.height)
      }
      length = Infinity
      for (const current of [...frames].reverse()) {
        const next = horizontal ? current.bounds.width : current.bounds.height
        assert.ok(next<=length+1e-7, 'Reverse path grew while folding')
        length = next
      }
      for (const current of [first,last]) for (const r of current.projected) {
        const b = current.bounds, radius = current.radius
        for (const x of [r.x,r.x+r.width]) for (const y of [r.y,r.y+r.height]) {
          const cx = Math.max(b.x+radius,Math.min(b.x+b.width-radius,x))
          const cy = Math.max(b.y+radius,Math.min(b.y+b.height-radius,y))
          assert.ok((x-cx)**2+(y-cy)**2<=Math.max(0,radius-1)**2+.01, 'Rounded panel clipped a static tile')
        }
      }
    }
  }
}
console.log('Floating panel: all styles/axes/signs, fixed thickness/corners, bounded monotonic length, overshoot and reverse paths passed')

// Paging removes the old edge tile before its successor finishes moving into
// that slot. Extra live end clearance must not temporarily round the frame.
for (const horizontal of [false,true]) for (const sign of [-1,1]) {
  const area = {x:0,y:40,width:400,height:360}
  const along = sign>0 ? (horizontal ? area.x : area.y)+12.375
    : (horizontal ? area.x+area.width : area.y+area.height)-48-12.375
  const anchor = horizontal ? {x:along,y:area.y+70.625} : {x:area.x+70.625,y:along}
  const layout = model.fanLayout(anchor.x+24,anchor.y+24,area,5,horizontal,48,4,3,17,sign,0,anchor)
  let radius, minimumOld=Infinity, maximumOld=-Infinity
  for (let step=0;step<=40;step++) {
    const live = Array.from({length:layout.capacity}, (_,i) => {
      const from=model.fanSlot(layout,Math.min(i+1,layout.capacity-1),0),to=model.fanSlot(layout,i,0)
      return {x:from.x+(to.x-from.x)*step/40,y:from.y+(to.y-from.y)*step/40,width:48,height:48}
    })
    const current=frame(live,layout,area)
    if (radius===undefined) radius=current.radius
    near(current.radius,radius,'Paging changed the settled corner radius')
    const old=model.fanRadius(current.bounds,current.projected,27,1)
    minimumOld=Math.min(minimumOld,old); maximumOld=Math.max(maximumOld,old)
  }
  assert.ok(maximumOld-minimumOld>2,'Paging fixture did not reproduce the old corner pulse')
}
console.log('Floating panel: edge-clamped corners remain stable while paging successors reflow')

// Match actual input shapes, including their transparent rounded corners.
for (const shape of ['square','rounded','circle','squircle','auto']) {
  const size = 48, radius = model.iconRadius(shape,size,true,12)
  const bands = model.squircleBands(size,size)
  for (let y=0;y<size;y++) for (let x=0;x<size;x++) {
    let expected
    if (shape==='squircle') expected = bands.some(b=>x>=b.x && x<b.x+b.width && y>=b.y && y<b.y+b.height)
    else {
      const px=x+.5, py=y+.5
      const dx=Math.max(radius-px,0,px-size+radius),dy=Math.max(radius-py,0,py-size+radius)
      expected = dx*dx+dy*dy<=radius*radius
    }
    assert.equal(model.iconContains(x+.5,y+.5,size,shape,radius),expected, `${shape} input mismatch at ${x},${y}`)
  }
  assert.ok(model.iconContains(24,24,size,shape,radius), 'Icon center is not clickable')
  assert.equal(model.iconContains(.01,.01,size,shape,radius), shape==='square', 'Transparent corner became clickable')
  for (const [x,y] of [[-1,24],[24,-1],[48,24],[24,48],[-.01,0],[0,48.01]]) {
    assert.equal(model.iconContains(x,y,size,shape,radius),false, 'Icon input escaped its tile')
  }
  assert.equal(model.iconContains(0,0,0,shape,radius),false)
}
console.log('Floating panel: airborne-icon containment matches square, rounded, circle and squircle input regions')
