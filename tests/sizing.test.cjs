const assert=require('node:assert/strict')
const fs=require('node:fs')
const vm=require('node:vm')
const model=vm.createContext({})
vm.runInContext(fs.readFileSync(__dirname+'/../ui/Model.js','utf8').replace(/^\.pragma library\s*/,''),model)
const presets=['50','75','100','125','150','175','200','250','300']
const styles=['arc','glide','cascade','spring','swing','matryoshka','matryoshka-hop','jumping']
const near=(actual,expected,why)=>assert.ok(Math.abs(actual-expected)<1e-7,`${why}: ${actual} != ${expected}`)
const plain=value=>JSON.parse(JSON.stringify(value))
function inside(rect,area,why) {
  assert.ok(rect.x>=area.x-1e-7 && rect.y>=area.y-1e-7 && rect.x+rect.width<=area.x+area.width+1e-7 && rect.y+rect.height<=area.y+area.height+1e-7,why)
}

for(const preset of presets) {
  const scale=Number(preset)/100
  near(model.sizeScale(preset),scale,'Preset scale')
  assert.equal(model.iconSize(preset,false),Math.round(44*scale),'Static icon size')
  assert.equal(model.iconSize(preset,true),Math.round(48*scale),'Floating icon size')
}
for(const invalid of [undefined,null,'','unknown','25','400','100foo',NaN,-1]) assert.equal(model.sizeScale(invalid),1,'Invalid size must keep the 100% default')
assert.deepEqual(plain(model.bubblePosition([-20,900],0,1000,600)),[8,544])
assert.deepEqual(plain(model.floatingAnchor(null,1000,600)),[932,276])
assert.deepEqual(plain(model.floatingAnchor([-20,900],1000,600)),[8,536])
for(const args of [[null,3,1000,600,5],[[600,300],1,1000,600,5]]) {
  assert.deepEqual(plain(model.bubblePosition(...args)),plain(model.bubblePosition(...args,48)),'Explicit default bubble size changed legacy placement')
}
assert.deepEqual(plain(model.floatingAnchor(null,1000,600)),plain(model.floatingAnchor(null,1000,600,48,56)))
console.log('Sizing: nine presets, 100% default and legacy optional-argument placement passed')

const screens=[{width:1920,height:1080,reserved:[12,34,20,16]},
  {width:320,height:240,reserved:[0,32,0,0]},
  {width:160.5,height:140.75,reserved:[7.25,19.5,9.75,5.25]},
  {width:38.5,height:32.75,reserved:[2.25,3.5,1.25,2.25]}]
for(const screen of screens) {
  const area=model.usableArea(screen.width,screen.height,screen.reserved)
  for(const preset of presets) for(const floating of [false,true]) {
    const raw=Math.round((floating?48:44)*Number(preset)/100),size=model.iconSize(preset,floating,area)
    assert.ok(Number.isInteger(size) && size>=1 && size<=raw,'Constrained size must stay a positive bounded integer')
    assert.ok(size<=area.width && size<=area.height,'Size did not fit the usable area')
    const factor=size/(floating?48:44),gap=4*factor
    for(const side of ['top','bottom','left','right']) {
      const vertical=side==='left'||side==='right',length=model.dockLength(30,size,gap)+6*factor
      const rect=model.staticDockRect(area,side,vertical?size+6*factor:length,vertical?length:size+6*factor,8*factor,16*factor)
      inside(rect,area,'Scaled static dock escaped a reserved edge')
    }
    if(!floating)continue
    const tail=8*size/48,height=size+tail
    for(const saved of [null,[-500,-500],[screen.width+500,screen.height+500],[screen.width/2,screen.height/2]]) {
      const anchor=model.floatingAnchor(saved,screen.width,screen.height,size,height)
      inside({x:anchor[0],y:anchor[1],width:size,height}, {x:0,y:0,width:screen.width,height:screen.height}, 'Scaled floating anchor escaped its canvas')
      const bubble=model.bubblePosition(saved,0,screen.width,screen.height,4,size)
      inside({x:bubble[0],y:bubble[1],width:size,height:size},{x:0,y:0,width:screen.width,height:screen.height},'Scaled bubble escaped its canvas')
      const snapped=model.floatingPosition(saved,screen.width,screen.height,area,true,height,size)
      inside({x:snapped[0],y:snapped[1],width:size,height},area,'Scaled stack including its tail escaped a reserved edge')
    }
    const keys=Array.from({length:8},(_,i)=>'window:'+i),saved={}
    keys.forEach(key=>saved[key]=[screen.width-56,screen.height/2])
    const points=model.bubbleLayout(keys,saved,{},screen.width,screen.height,area,true,false,size,gap)
    assert.equal(points.length,keys.length,'Sizing dropped a bubble')
    points.forEach(p=>inside({x:p[0],y:p[1],width:size,height:size},area,'Scaled edge bubble escaped its work area'))
    if(screen.width===1920) for(let i=0;i<points.length;i++)for(let j=0;j<i;j++) {
      const a=points[i],b=points[j]
      assert.ok(a[0]>=b[0]+size+gap-1e-7||a[0]+size+gap<=b[0]+1e-7||a[1]>=b[1]+size+gap-1e-7||a[1]+size+gap<=b[1]+1e-7,'Scaled bubble packing lost icon clearance')
    }
  }
}
for(const preset of presets)for(const floating of [false,true])for(const area of [{x:0,y:0,width:0,height:100},{x:0,y:0,width:100,height:0}]) assert.equal(model.iconSize(preset,floating,area),0,'Empty work areas must not allocate icons')
console.log('Sizing: all sides, tiny/fractional outputs, bar reservations, tail clearance and edge packing passed')

for(const preset of presets)for(const floating of [false,true]) {
  const size=model.iconSize(preset,floating),factor=size/(floating?48:44)
  for(const dpr of [1,1.25,1.5,2])for(const shape of ['circle','square','rounded','squircle'])for(const frameless of [false,true]) {
    const radius=model.iconRadius(shape,size,floating,4),inset=1.5
    const art=model.artworkSize(size,36*factor,radius,shape,inset,dpr,frameless,factor)
    assert.ok(art>0 && art<=size,'Artwork escaped its scaled tile')
    near(art*dpr,Math.round(art*dpr),'Artwork pixel alignment')
    assert.equal((Math.round(size*dpr)-Math.round(art*dpr))%2,0,'Artwork lost centered pixel parity')
    if(!frameless) {
      const inner=Math.max(0,size/2-inset),r=Math.max(0,Math.min(inner,radius-inset))
      const limit=shape==='squircle'?inner*Math.pow(.5,.25):inner-r+r/Math.sqrt(2)
      assert.ok((art-1/dpr)/2<=limit+.5/dpr,'Artwork corners exceeded the frame pixel-alignment allowance')
    }
    assert.ok(model.iconContains(size/2,size/2,size,shape,radius),'Scaled icon center lost input')
    for(const [x,y]of [[-1,size/2],[size,size/2],[size/2,-1],[size/2,size]]) assert.equal(model.iconContains(x,y,size,shape,radius),false,'Input leaked beyond the scaled icon')
    assert.equal(model.iconContains(.01,.01,size,shape,radius),shape==='square','Scaled rounded input did not match its visible corner')
  }
}
console.log('Sizing: pixel-centered artwork, rounded frame clearance and matching hit extents passed')

for(const screen of screens.slice(0,3)) {
  const area=model.usableArea(screen.width,screen.height,screen.reserved)
  for(const preset of presets) {
    const size=model.iconSize(preset,true,area),gap=4*size/48,tailStep=4*size/48
    const anchors=[{x:area.x+Math.min(8,(area.width-size)/2),y:area.y},
      {x:area.x+Math.max(0,area.width-size-8),y:area.y+Math.max(0,area.height-size-2*tailStep-8)},
      {x:area.x+(area.width-size)/2,y:area.y+(area.height-size-2*tailStep)/2}]
    for(const anchor of anchors)for(const horizontal of [false,true])for(const sign of [-1,1]) {
      const layout=model.fanLayout(anchor.x+size/2,anchor.y+size/2,area,30,horizontal,size,gap,3*size/48,17*size/48,sign,0,anchor)
      near(layout.tailStep,tailStep,'Fan tail did not scale with its icons')
      near(layout.step,size+gap,'Fan gap did not scale with its icons')
      assert.ok(layout.capacity>=1 && layout.capacity<=30,'Scaled fan lost its bounded capacity')
      for(const style of styles)for(let ordinal=0;ordinal<layout.capacity;ordinal++)for(const p of [0,.06,.12,.25,.4,.68,.8,.95,1]) {
        const target=model.fanSlot(layout,ordinal,0),sy=anchor.y+Math.min(ordinal,2)*tailStep
        const args=[anchor.x,sy,target.x,target.y,p,ordinal,layout,area,style]
        const pose=style.startsWith('matryoshka')?model.fanChainPose(...args,0,layout.capacity):model.fanPose(...args)
        inside({x:pose.x,y:pose.y,width:size,height:size},area,'Scaled animation escaped its reserved work area')
        if(ordinal===0) {near(pose.x,anchor.x,'Scaled front moved horizontally');near(pose.y,anchor.y,'Scaled front moved vertically')}
        if(p===0)near(pose.y,sy,'Collapsed stack lost its scaled tail offset')
        if(p===1){near(pose.x,target.x,'Scaled fan missed its destination');near(pose.y,target.y,'Scaled fan missed its destination')}
      }
    }
  }
}
console.log('Sizing: all fan styles preserve scaled tails, both axes/signs, overflow bounds and exact endpoints')
