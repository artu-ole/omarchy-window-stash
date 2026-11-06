const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
function library(name) {
  const context = vm.createContext({})
  vm.runInContext(fs.readFileSync(__dirname+'/../ui/'+name+'.js','utf8').replace(/^\.pragma library\s*/,''),context)
  return context
}
const model=library('Model'),motion=library('Motion')
const near=(actual,expected,why) => assert.ok(Math.abs(actual-expected)<1e-7,`${why}: ${actual} != ${expected}`)
const point=(actual,expected,why) => {near(actual.x,expected.x,why+' x');near(actual.y,expected.y,why+' y')}
const profile=motion.fanProfile('jumping')
assert.equal(profile.name,'jumping','Jumping must have its own selectable profile')
assert.equal(profile.easing,'linear','Jump stages need an unwarped timeline')
assert.equal(motion.chain('jumping'),false,'Each icon must jump from the original stack')
assert.ok(profile.stagger>0 && profile.limit>0 && profile.limit<=200,'Individual departures must have a bounded stagger')
assert.ok(profile.open>200 && profile.open<1000 && profile.close>150 && profile.close<1000,'Full motion must have bounded flight/landing time')
assert.equal(typeof model.fanJumpPose,'function')

function scene(area,anchor,count,horizontal,sign,preferredCurve=0) {
  const layout=model.fanLayout(anchor.x+24,anchor.y+24,area,count,horizontal,48,4,3,17,sign,preferredCurve,anchor)
  function pose(i,p) {
    const start={x:anchor.x,y:anchor.y+Math.min(i,2)*4},end=model.fanSlot(layout,i,0)
    return model.fanPose(start.x,start.y,end.x,end.y,p,i,layout,area,'jumping')
  }
  return {area,anchor,layout,pose}
}

// Observe choreography rather than duplicating its easing equations: an
// anticipation, an airborne trip, two diminishing rebounds, and an exact rest.
const ample={x:12,y:34,width:1200,height:800}
const center={x:ample.x+500.375,y:ample.y+350.625}
for (const horizontal of [false,true]) for (const sign of [-1,1]) {
  const s=scene(ample,center,5,horizontal,sign)
  const launch=s.pose(2,.06),air=s.pose(2,.4),land=s.pose(2,.68),end=model.fanSlot(s.layout,2,0)
  point(launch,{x:center.x,y:center.y+8},'Anticipation left the stack early')
  assert.ok(Math.abs(launch.stretchX-launch.stretchY)>.04,'Takeoff needs visible squash')
  assert.ok(Math.abs(air.stretchX-air.stretchY)>.02,'Flight needs visible stretch')
  assert.ok(air.bend>1,'Jump must leave its straight travel path')
  point(land,end,'First landing must arrive at the chosen slot')
  assert.ok(Math.abs(land.stretchX-land.stretchY)>.04,'Landing needs a visible compression')
  const rebounds=[]
  let before=s.pose(2,.68).bend,current=s.pose(2,.681).bend
  for (let frame=682;frame<=1000;frame++) {
    const next=s.pose(2,frame/1000).bend
    if (current>before && current>=next && current>.1) rebounds.push(current)
    before=current;current=next
  }
  assert.ok(rebounds.length>=2,'Landing should visibly rebound and settle')
  assert.ok(rebounds[0]<air.bend,'First rebound must be smaller than the flight')
  for (let i=1;i<rebounds.length;i++) assert.ok(rebounds[i]<rebounds[i-1],'Successive rebounds must lose energy')
}
console.log('Jumping: bounded stagger, launch squash, airborne stretch, landing compression and diminishing rebounds passed')

const areas=[ample,{x:-700.5,y:73.25,width:1000.5,height:600.75},{x:0,y:32,width:320,height:208}]
let checked=0
for (const area of areas) {
  const anchors=[{x:area.x+area.width/2+.375,y:area.y+area.height/2+.625},
    {x:area.x+8.125,y:area.y},{x:area.x+8.125,y:area.y+2.375},
    {x:area.x+8.125,y:area.y+8.625},
    {x:area.x+area.width-56.125,y:area.y+8.625},
    {x:area.x+area.width-56.125,y:area.y+area.height-64.375}]
  for (const anchor of anchors) for (const horizontal of [false,true]) for (const sign of [-1,1]) {
    for (const preferredCurve of [-1,0,1]) for (const count of [1,4,30]) {
      const s=scene(area,anchor,count,horizontal,sign,preferredCurve)
      if (horizontal) {assert.equal(s.layout.hopSign,-1);assert.equal(s.layout.curveSign,-1)}
      for (let ordinal=0;ordinal<s.layout.capacity;ordinal++) {
        const start={x:anchor.x,y:anchor.y+Math.min(ordinal,2)*4},end=model.fanSlot(s.layout,ordinal,0),opening=[]
        let previous=null
        for (let frame=0;frame<=160;frame++) {
          const p=frame/160,pose=s.pose(ordinal,p)
          opening.push(pose)
          for (const key of ['x','y','bend','scale','tilt','stretchX','stretchY']) assert.ok(Number.isFinite(pose[key]),'Jump produced non-finite '+key)
          assert.ok(pose.x>=area.x-1e-7 && pose.y>=area.y-1e-7 && pose.x+48<=area.x+area.width+1e-7 && pose.y+48<=area.y+area.height+1e-7,'Jump escaped the usable work area')
          assert.ok(pose.stretchX>0 && pose.stretchX<=1 && pose.stretchY>0 && pose.stretchY<=1,'Squash/stretch overflowed its icon tile')
          assert.equal(pose.scale,1);assert.equal(pose.tilt,0)
          assert.ok(pose.bend>=0 && pose.bend<=s.layout.hopLimit+1e-7,'Jump exceeded the safe cross-axis excursion')
          if (ordinal===0) {
            point(pose,anchor,'Original front moved')
            assert.equal(pose.bend,0);assert.equal(pose.stretchX,1);assert.equal(pose.stretchY,1)
          } else {
            // Recover travel from the unchanged longitudinal coordinate. This
            // keeps the baseline independent of the animation's easing math.
            const delta=horizontal ? end.x-start.x : end.y-start.y
            const travel=(horizontal ? pose.x-start.x : pose.y-start.y)/delta
            assert.ok(travel>=-1e-7 && travel<=1+1e-7,'Jump overshot its destination along the row')
            if (horizontal) {
              const baseline=start.y+(end.y-start.y)*travel
              near(pose.y,baseline-pose.bend,'Horizontal jump bent below or clipped its baseline')
            } else {
              near(pose.x,start.x+pose.bend*s.layout.hopSign,'Vertical jump ignored its chosen side')
            }
          }
          if (frame===0 || frame===160) {
            point(pose,frame===0 ? start : end,'Jump changed exact endpoint')
            assert.equal(pose.bend,0);assert.equal(pose.stretchX,1);assert.equal(pose.stretchY,1)
          }
          if (horizontal && anchor.y-area.y<=3) assert.equal(pose.bend,0,'No room above must flatten the jump rather than send it downward')
          if (previous) assert.ok(Math.hypot(pose.x-previous.x,pose.y-previous.y)<s.layout.span/12+8,'Jump teleported between adjacent frames')
          previous=pose;checked++
        }
        for (let frame=160;frame>=0;frame--) {
          const actual=s.pose(ordinal,frame/160),reference=opening[frame]
          for (const key of ['x','y','bend','stretchX','stretchY']) near(actual[key],reference[key],'Folding must retrace the same continuous jump')
        }
        for (const boundary of [.12,.68,1]) {
          const before=s.pose(ordinal,Math.max(0,boundary-1e-7)),after=s.pose(ordinal,Math.min(1,boundary+1e-7))
          assert.ok(Math.hypot(after.x-before.x,after.y-before.y)<.001,'Stage boundary introduced a position jump')
          assert.ok(Math.abs(after.stretchX-before.stretchX)<.00001,'Stage boundary introduced a horizontal deformation jump')
          assert.ok(Math.abs(after.stretchY-before.stretchY)<.00001,'Stage boundary introduced a vertical deformation jump')
        }
      }
    }
  }
}
console.log('Jumping: '+checked+' frames cover both axes/signs, reserved/fractional edges, fixed origin, exact endpoints and reverse paths')
