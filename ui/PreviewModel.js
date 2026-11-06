.pragma library

function finite(value, fallback) {
  value=Number(value)
  return isFinite(value) ? value : fallback
}

function rectangle(value) {
  value=value || {}
  return {x:finite(value.x,0),y:finite(value.y,0),width:Math.max(0,finite(value.width,0)),height:Math.max(0,finite(value.height,0))}
}

function clamp(value, minimum, maximum) { return Math.max(minimum,Math.min(maximum,value)) }

// Dimensions are logical pixels. Every window has its own fixed-aspect image
// viewport. Grouped windows form one row: shrink together while readable, then
// keep all cards in a horizontally scrollable strip instead of a carousel.
function measure(size, width, height, titleVisible, groupCount) {
  width=Math.max(0,finite(width,0)); height=Math.max(0,finite(height,0))
  var count=Math.max(1,Math.floor(finite(groupCount,1)))
  if (!width || !height) return {width:0,height:0,imageWidth:0,imageHeight:0,headerHeight:0,footerHeight:0,inset:0,
    cardWidth:0,cardHeight:0,tileWidth:0,tileHeight:0,gap:0,contentWidth:0,viewportWidth:0,viewportHeight:0,overflow:false,count:count}
  var preferred=size==="small" ? 200 : size==="large" ? 380 : 280
  var inset=Math.min(8,width/4,height/4)
  var insideWidth=Math.max(0,width-inset*2),insideHeight=Math.max(0,height-inset*2)
  var header=titleVisible ? 36 : 0
  // Keep some image room on tiny outputs instead of allowing fixed chrome to
  // push the capture outside the panel.
  header=Math.min(header,insideHeight*.6)
  var maximum=Math.max(0,Math.min(preferred,insideWidth,(insideHeight-header)*1.6))
  var gap=count>1 ? Math.min(8,insideWidth/4) : 0
  var fitting=(insideWidth-gap*(count-1))/count
  var imageWidth=Math.max(0,Math.min(maximum,Math.max(Math.min(120,maximum),fitting)))
  var imageHeight=imageWidth/1.6
  var cardHeight=imageHeight+header,contentWidth=imageWidth*count+gap*(count-1)
  var viewportWidth=Math.min(insideWidth,contentWidth)
  return {width:viewportWidth+inset*2,height:cardHeight+inset*2,
    imageWidth:imageWidth,imageHeight:imageHeight,headerHeight:header,footerHeight:0,inset:inset,
    cardWidth:imageWidth,cardHeight:cardHeight,tileWidth:imageWidth,tileHeight:cardHeight,gap:gap,
    contentWidth:contentWidth,viewportWidth:viewportWidth,viewportHeight:cardHeight,overflow:contentWidth>viewportWidth+.000001,count:count}
}

function contains(rect, x, y, radius) {
  if (!rect || rect.width<=0 || rect.height<=0 || x<rect.x || y<rect.y || x>rect.x+rect.width || y>rect.y+rect.height) return false
  radius=clamp(finite(radius,0),0,Math.min(rect.width,rect.height)/2)
  var px=x-rect.x,py=y-rect.y
  var dx=Math.max(radius-px,0,px-rect.width+radius),dy=Math.max(radius-py,0,py-rect.height+radius)
  return dx*dx+dy*dy<=radius*radius
}

// Compositor positions are global logical coordinates; preview rectangles
// belong to one monitor. Prefer that independent position over latched Qt
// hover state, while retaining native hover before the first cursor sample.
function hoverContacts(source, card, known, position, monitor, qtSource, qtCard, radius) {
  if (!known) return {source:!!source && !!qtSource,card:!!card && !!qtCard,physical:false}
  if (!position || !monitor || !isFinite(position.x) || !isFinite(position.y)
      || !isFinite(monitor.x) || !isFinite(monitor.y))
    return {source:false,card:false,physical:true}
  var x=position.x-monitor.x,y=position.y-monitor.y
  return {source:contains(source,x,y),card:contains(card,x,y,radius),physical:true}
}

function rooms(area, avoid, gap) {
  return {above:clamp(avoid.y-area.y-gap,0,area.height),below:clamp(area.y+area.height-avoid.y-avoid.height-gap,0,area.height),
    left:clamp(avoid.x-area.x-gap,0,area.width),right:clamp(area.x+area.width-avoid.x-avoid.width-gap,0,area.width)}
}

function sideOrder(placement, space, dimensions) {
  var order=["above","below","right","left"],opposite={above:"below",below:"above",left:"right",right:"left"}
  order.sort(function(a,b) {
    var ar=space[a]/Math.max(1,a==="left" || a==="right" ? dimensions.width : dimensions.height)
    var br=space[b]/Math.max(1,b==="left" || b==="right" ? dimensions.width : dimensions.height)
    return br-ar
  })
  if (opposite[placement]) {
    order=order.filter(function(side) { return side!==placement && side!==opposite[placement] })
    order.unshift(opposite[placement]); order.unshift(placement)
  }
  return order
}

function choose(area, avoid, size, titleVisible, groupCount, placement, gap) {
  var full=measure(size,area.width,area.height,titleVisible,groupCount),space=rooms(area,avoid,gap)
  var order=sideOrder(placement,space,full),i,side
  for (i=0;i<order.length;i++) {
    side=order[i]
    if (space[side]>0 && (side==="left" || side==="right" ? full.width<=space[side] : full.height<=space[side]))
      return {side:side,dimensions:full}
  }
  var best=null,bestArea=0
  for (i=0;i<order.length;i++) {
    side=order[i]
    var dimensions=measure(size,side==="left" || side==="right" ? space[side] : area.width,
      side==="above" || side==="below" ? space[side] : area.height,titleVisible,groupCount)
    var visibleCount=Math.min(dimensions.count,(dimensions.viewportWidth+dimensions.gap)/Math.max(1,dimensions.cardWidth+dimensions.gap))
    var imageArea=dimensions.imageWidth*dimensions.imageHeight*visibleCount
    if (imageArea>bestArea+0.000001) { best={side:side,dimensions:dimensions}; bestArea=imageArea }
  }
  return best
}

// Avoid the whole dock when supplied, but keep the preview aligned with its
// hovered icon. A full-screen chooser can leave no room outside itself; in
// that case avoid just the source row before accepting unavoidable overlap.
function previewLayout(anchor, area, size, titleVisible, groupCount, placement, gap, avoidRect) {
  area=rectangle(area); anchor=rectangle(anchor)
  gap=Math.max(0,finite(gap,8))
  var avoid=rectangle(avoidRect || anchor)
  var selected=choose(area,avoid,size,titleVisible,groupCount,placement,gap)
  if (!selected && avoidRect) { avoid=anchor; selected=choose(area,avoid,size,titleVisible,groupCount,placement,gap) }
  if (!selected) selected={side:"above",dimensions:measure(size,area.width,area.height,titleVisible,groupCount)}
  var d=selected.dimensions,side=selected.side,x=anchor.x+(anchor.width-d.width)/2,y=anchor.y+(anchor.height-d.height)/2
  if (side==="above") y=avoid.y-gap-d.height
  else if (side==="below") y=avoid.y+avoid.height+gap
  else if (side==="left") x=avoid.x-gap-d.width
  else x=avoid.x+avoid.width+gap
  return Object.assign({},d,{x:clamp(x,area.x,area.x+area.width-d.width),y:clamp(y,area.y,area.y+area.height-d.height),side:side})
}
