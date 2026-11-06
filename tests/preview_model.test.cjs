const assert=require('node:assert/strict')
const fs=require('node:fs')
const vm=require('node:vm')
const model=vm.createContext({})
vm.runInContext(fs.readFileSync(__dirname+'/../ui/PreviewModel.js','utf8').replace(/^\.pragma library\s*/,''),model)
const close=(a,b,message)=>assert.ok(Math.abs(a-b)<1e-7,`${message}: ${a} != ${b}`)
function bounded(rect,area) {
  for (const key of ['x','y','width','height','imageWidth','imageHeight','headerHeight','footerHeight','inset',
    'cardWidth','cardHeight','tileWidth','tileHeight','gap','contentWidth','viewportWidth','viewportHeight','count'])
    assert.ok(Number.isFinite(rect[key]),'Nonfinite '+key)
  assert.ok(rect.width>=0 && rect.height>=0 && rect.imageWidth>=0 && rect.imageHeight>=0)
  assert.ok(rect.x>=area.x-1e-7 && rect.y>=area.y-1e-7,'Preview escaped reserved top/left')
  assert.ok(rect.x+rect.width<=area.x+area.width+1e-7,'Preview escaped right edge')
  assert.ok(rect.y+rect.height<=area.y+area.height+1e-7,'Preview escaped bottom edge')
  close(rect.width,rect.viewportWidth+rect.inset*2,'Strip viewport and horizontal chrome disagree')
  close(rect.height,rect.imageHeight+rect.headerHeight+rect.footerHeight+rect.inset*2,'Image and vertical chrome disagree')
  close(rect.imageWidth,rect.imageHeight*1.6,'Viewport changed aspect ratio')
  close(rect.cardWidth,rect.imageWidth,'Card width changed the thumbnail viewport')
  close(rect.cardHeight,rect.imageHeight+rect.headerHeight,'Card height changed the thumbnail/title allocation')
  close(rect.tileWidth,rect.cardWidth,'Tile width alias disagrees')
  close(rect.tileHeight,rect.cardHeight,'Tile height alias disagrees')
  close(rect.viewportHeight,rect.cardHeight,'Strip viewport clips its cards vertically')
  close(rect.contentWidth,rect.count*rect.cardWidth+Math.max(0,rect.count-1)*rect.gap,'Grouped row lost a window or added a trailing gap')
  assert.ok(rect.viewportWidth<=rect.contentWidth+1e-7,'Strip viewport exceeds its content')
  assert.equal(rect.overflow,rect.contentWidth>rect.viewportWidth+.000001,'Overflow flag disagrees with the actual row')
  assert.equal(rect.footerHeight,0,'Carousel footer should not consume space')
}
const overlaps=(a,b)=>a.x<b.x+b.width-1e-7 && a.x+a.width>b.x+1e-7 && a.y<b.y+b.height-1e-7 && a.y+a.height>b.y+1e-7
const area={x:12,y:34,width:1600,height:1100}
const center={x:area.x+area.width/2-24,y:area.y+area.height/2-24,width:48,height:48}

for (const [size,width] of [['small',200],['medium',280],['large',380]]) {
  const result=model.previewLayout(center,area,size,true,3,'auto',8)
  bounded(result,area)
  close(result.imageWidth,width,'Preset thumbnail width')
  assert.equal(result.headerHeight,36)
  assert.equal(result.footerHeight,0)
  assert.equal(result.inset,8)
  assert.equal(result.count,3)
  close(result.contentWidth,width*3+result.gap*2,'Grouped preview omitted a thumbnail')
  assert.equal(result.overflow,false,'A readable group should show all its windows together')
  const plain=model.previewLayout(center,area,size,false,1,'auto',8)
  assert.equal(plain.headerHeight,0)
  assert.equal(plain.footerHeight,0)
  assert.equal(plain.imageWidth,width)
}
console.log('Preview geometry: size presets, per-window titles and side-by-side aspect-preserving thumbnails passed')

for (const side of ['above','below','left','right']) {
  const result=model.previewLayout(center,area,'medium',true,2,side,8)
  assert.equal(result.side,side,'Available preferred side was not honored')
  bounded(result,area)
  assert.ok(!overlaps(result,center),'Preferred placement covered its source')
  if(side==='above')close(result.y+result.height,center.y-8,'Above gap')
  if(side==='below')close(result.y,center.y+center.height+8,'Below gap')
  if(side==='left')close(result.x+result.width,center.x-8,'Left gap')
  if(side==='right')close(result.x,center.x+center.width+8,'Right gap')
}
for (const [anchor,preference,expected] of [
  [{x:area.x,y:center.y,width:48,height:48},'left','right'],
  [{x:area.x+area.width-48,y:center.y,width:48,height:48},'right','left'],
  [{x:center.x,y:area.y,width:48,height:48},'above','below'],
  [{x:center.x,y:area.y+area.height-48,width:48,height:48},'below','above']
]) {
  assert.equal(model.previewLayout(anchor,area,'medium',true,3,preference,8).side,expected,'Unavailable preferred side did not flip')
  assert.equal(model.previewLayout(anchor,area,'medium',true,1,'auto',8).side,expected,'Single-window automatic placement did not face away from the edge')
  const grouped=model.previewLayout(anchor,area,'medium',true,3,'auto',8)
  bounded(grouped,area)
  assert.ok(!overlaps(grouped,anchor),'Grouped automatic placement covered the edge source')
}
console.log('Preview geometry: preferred sides, edge flipping and automatic inward placement passed')

const fan={x:650,y:area.y+8,width:56,height:area.height-16}
const fanIcon={x:654,y:center.y,width:48,height:48}
const outsideFan=model.previewLayout(fanIcon,area,'large',true,8,'auto',8,fan)
assert.ok(!overlaps(outsideFan,fan),'Preview covered neighboring floating-dock icons')
assert.ok(outsideFan.side==='left' || outsideFan.side==='right')
const shelf={x:area.x+200,y:area.y+area.height-54,width:area.width-400,height:54}
const aboveShelf=model.previewLayout({x:center.x,y:shelf.y+3,width:48,height:48},area,'medium',true,3,'auto',8,shelf)
assert.equal(aboveShelf.side,'above')
assert.ok(!overlaps(aboveShelf,shelf),'Preview covered neighboring static-dock icons')
const fullChooser=model.previewLayout(center,area,'medium',true,3,'auto',8,area)
assert.ok(!overlaps(fullChooser,center),'Full-screen avoidance did not fall back to the hovered row')
assert.ok(fullChooser.imageWidth>0)
console.log('Preview geometry: full-dock avoidance and full-screen chooser fallback passed')

const small={x:0,y:26,width:320,height:214}
const smallAnchor={x:136,y:109,width:48,height:48}
const compact=model.previewLayout(smallAnchor,small,'medium',true,7,'auto',8)
bounded(compact,small)
assert.ok(!overlaps(compact,smallAnchor),'Small output placed its preview over the hovered icon')
assert.ok(compact.imageWidth>=100,'Small output unnecessarily reduced its image')
assert.ok(compact.side==='left' || compact.side==='right','Small output failed to choose the usable axis')
assert.ok(compact.headerHeight>0)
assert.equal(compact.footerHeight,0)
assert.ok(compact.overflow && compact.contentWidth>compact.viewportWidth,'Small groups must retain every card in the scrollable row')
console.log('Preview geometry: small-output shrinking preserves the hover source and accessible grouped row')

for (const width of [160,320,640,1280,1920]) for (const height of [90,240,1080]) {
  let previousWidth=Infinity
  for (const count of [1,2,3,8,32]) {
    const d=model.measure('medium',width,height,true,count)
    assert.ok(d.imageWidth<=280 && d.imageWidth<=previousWidth+1e-7,'Adding windows enlarged a thumbnail')
    previousWidth=d.imageWidth
    assert.ok(d.width<=width && d.height<=height,'Grouped measurement escaped its available area')
    const maximum=Math.min(280,width-d.inset*2,(height-d.inset*2-d.headerHeight)*1.6)
    const fitting=(width-d.inset*2-d.gap*(count-1))/count
    if (fitting>=120 && maximum>=120) {
      assert.equal(d.overflow,false,'A row that fits at readable size should not scroll')
      assert.ok(d.imageWidth>=120,'A fitting group was needlessly shrunk below readable width')
    }
    if (fitting<120 && maximum>=120) {
      close(d.imageWidth,120,'Overflow should retain readable thumbnails')
      assert.equal(d.overflow,true,'A wide group lost access to its remaining windows')
    }
    if (maximum<120) close(d.imageWidth,maximum,'Tiny areas must constrain cards below the normal readable minimum')
    close(d.contentWidth,d.imageWidth*count+d.gap*(count-1),'Every grouped window must have one card')
  }
}
const fitted=model.measure('large',700,600,true,3)
close(fitted.contentWidth,fitted.viewportWidth,'Three windows should shrink evenly to fit a moderate row')
assert.ok(fitted.imageWidth>=120 && fitted.imageWidth<380)
const overflowing=model.measure('large',700,600,true,8)
assert.ok(overflowing.overflow && overflowing.contentWidth>overflowing.viewportWidth)
close(overflowing.imageWidth,120,'Many windows should stay readable behind horizontal scrolling')
console.log('Preview geometry: even group resizing, readable minimum, all-card content widths and bounded overflow passed')

for (const scale of [1,1.25,1.5,2]) {
  for (const dimensions of [[2560,1548],[320,214],[140,114],[64,64],[1,1],[0,0]]) {
    const work={x:12.375/scale,y:34.625/scale,width:dimensions[0]/scale,height:dimensions[1]/scale}
    const size=Math.min(48,work.width,work.height)
    const anchors=[
      {x:work.x,y:work.y,width:size,height:size},
      {x:work.x+work.width-size,y:work.y,width:size,height:size},
      {x:work.x,y:work.y+work.height-size,width:size,height:size},
      {x:work.x+work.width-size,y:work.y+work.height-size,width:size,height:size},
      {x:work.x+(work.width-size)/2,y:work.y+(work.height-size)/2,width:size,height:size}
    ]
    for(const anchor of anchors)for(const preset of ['small','medium','large'])for(const title of [false,true])for(const count of [1,8])for(const side of ['auto','above','below','left','right']) {
      const result=model.previewLayout(anchor,work,preset,title,count,side,8)
      bounded(result,work)
      assert.equal(JSON.stringify(result),JSON.stringify(model.previewLayout(anchor,work,preset,title,count,side,8)),'Placement is not deterministic')
      if(result.width>0 && result.height>0) {
        assert.ok(model.contains(result,result.x+result.width/2,result.y+result.height/2))
        assert.ok(!model.contains(result,result.x-1,result.y))
      }
      if(work.width>=320 && work.height>=214)assert.ok(!overlaps(result,anchor),'Usable monitor preview covered its source')
    }
  }
}
assert.ok(!model.contains(null,0,0))
assert.ok(!model.contains({x:0,y:0,width:0,height:0},0,0))
console.log('Preview geometry: reservations, fractional scales, tiny areas, deterministic bounds and input containment passed')

const rounded={x:10.375,y:20.625,width:100,height:60}
for(const radius of [0,5,12,30,1000]) {
  const r=Math.min(radius,30)
  for(const [x,y] of [[0,0],[100,0],[0,60],[100,60]])
    assert.equal(model.contains(rounded,rounded.x+x,rounded.y+y,radius),r===0,'Transparent rounded corner was treated as clickable')
  for(const [x,y] of [[50,0],[50,60],[0,30],[100,30],[50,30]])
    assert.ok(model.contains(rounded,rounded.x+x,rounded.y+y,radius),'Rounded straight edge or center was excluded')
  if(r>0) {
    assert.ok(!model.contains(rounded,rounded.x+r*.1,rounded.y+r*.1,radius),'Rounded corner cutout was included')
    assert.ok(model.contains(rounded,rounded.x+r*.5,rounded.y+r*.5,radius),'Visible rounded corner was excluded')
  }
}
assert.ok(model.contains(rounded,rounded.x+2,rounded.y+1,5),'Point on the rounded arc was excluded')
assert.ok(!model.contains(rounded,rounded.x+1.99,rounded.y+1,5),'Point outside the rounded arc was included')
assert.ok(model.contains(rounded,rounded.x,rounded.y,-5),'Negative radius did not clamp to square')
assert.equal(model.contains(rounded,rounded.x+1,rounded.y+1,1000),model.contains(rounded,rounded.x+1,rounded.y+1,30),'Oversized radius did not clamp to half the short side')
assert.ok(!model.contains(rounded,rounded.x-.01,rounded.y+30,12))
assert.ok(!model.contains({x:0,y:0,width:0,height:0},0,0,12))
console.log('Preview geometry: rounded hit regions match visible corners and clamp oversized radii')

// Native pointer positions override stale item hover independently for the
// source and the card, including outputs left/above the primary output.
const sourceBox={x:1258,y:1545,width:44,height:44}
const cardBox={x:1130,y:1310,width:296,height:227}
const output={x:-1920,y:-240}
function contact(x,y,qtSource=true,qtCard=true,known=true,card=cardBox) {
  return model.hoverContacts(sourceBox,card,known,{x:x+output.x,y:y+output.y},output,qtSource,qtCard,12)
}
assert.deepEqual(JSON.parse(JSON.stringify(contact(6,32))),{source:false,card:false,physical:true},
  'Latched Qt hover kept an unrelated restored-window preview alive')
assert.equal(contact(1280,1567,false,false).source,true,'A fresh native enter was discarded because Qt had not caught up')
assert.equal(contact(1280,1567,false,false).card,false)
assert.equal(contact(1200,1400,true,false).source,false)
assert.equal(contact(1200,1400,true,false).card,true,'Source-to-preview transfer did not keep the actual hovered card alive')
assert.equal(contact(cardBox.x,cardBox.y).card,false,'A transparent rounded corner kept the preview open')
assert.equal(contact(1200,1400,true,true,true,null).card,false,'A closed card retained physical hover')
assert.equal(contact(6,32,true,false,false).source,true,'Unknown native position lost the Qt fallback')
assert.equal(contact(6,32,true,false,false).card,false)
assert.equal(model.hoverContacts(null,null,false,null,null,true,true,12).source,false,'A missing source retained Qt hover')
assert.equal(model.hoverContacts(null,null,false,null,null,true,true,12).card,false,'A missing card retained Qt hover')
assert.equal(model.hoverContacts(sourceBox,cardBox,true,{x:NaN,y:1},output,true,true,12).source,false,
  'Invalid native coordinates fell back to stale Qt hover')
console.log('Preview hover: native source/card bounds, stale Qt state, negative monitor offsets, rounded corners and unknown-position fallback passed')
