.pragma library

// Thumbnail geometry is independent of the client window's real geometry.
// All coordinates are logical pixels in one monitor's usable area.
function finite(value, fallback) { value=Number(value);return isFinite(value) ? value : fallback }
function clamp(value, low, high) { return Math.max(low,Math.min(high,value)) }
function rectangle(value) {
  value=value || {}
  return {x:finite(value.x,0),y:finite(value.y,0),width:Math.max(1,finite(value.width,1)),height:Math.max(1,finite(value.height,1))}
}
function aspect(record) {
  var size=record && record.size
  return size && finite(size[0],0)>0 && finite(size[1],0)>0 ? clamp(Number(size[0])/Number(size[1]),.02,50) : 1.6
}
function chrome(titles, frame) { return {header:titles ? 32 : 0,inset:frame ? 2 : 0} }
function dimensions(requested, record, area, titles, frame) {
  area=rectangle(area)
  var c=chrome(titles,frame),ratio=aspect(record)
  c.header=Math.min(c.header,Math.max(0,area.height-1))
  c.inset=Math.min(c.inset,Math.max(0,(area.width-1)/2),Math.max(0,(area.height-c.header-1)/2))
  var maximum=Math.max(1,Math.min(area.width,(area.height-c.header-c.inset*2)*ratio+c.inset*2))
  var minimum=Math.min(120,maximum)
  var width=clamp(finite(requested,280),minimum,maximum)
  return {width:width,height:(width-c.inset*2)/ratio+c.header+c.inset*2,header:c.header,inset:c.inset,aspect:ratio,minimum:minimum,maximum:maximum}
}
function position(rect, area) {
  area=rectangle(area)
  return {x:clamp(finite(rect.x,area.x),area.x,area.x+area.width-rect.width),
    y:clamp(finite(rect.y,area.y),area.y,area.y+area.height-rect.height)}
}
function resize(rect, record, area, dx, dy, corner, titles, frame) {
  area=rectangle(area)
  var sx=corner.indexOf("left")>=0 ? -1 : 1,sy=corner.indexOf("top")>=0 ? -1 : 1
  var ratio=aspect(record),anchorX=sx<0 ? rect.x+rect.width : rect.x,anchorY=sy<0 ? rect.y+rect.height : rect.y
  var widthDelta=Math.abs(dx)>=Math.abs(dy)*ratio ? sx*dx : sy*dy*ratio
  var available={x:0,y:0,width:sx<0 ? anchorX-area.x : area.x+area.width-anchorX,
    height:sy<0 ? anchorY-area.y : area.y+area.height-anchorY}
  var d=dimensions(rect.width+widthDelta,record,available,titles,frame)
  var result={x:sx<0 ? anchorX-d.width : anchorX,y:sy<0 ? anchorY-d.height : anchorY,width:d.width,height:d.height}
  var point=position(result,area);result.x=point.x;result.y=point.y
  return result
}
function contains(rect, x, y) { return !!rect && x>=rect.x && y>=rect.y && x<=rect.x+rect.width && y<=rect.y+rect.height }
function intersects(a,b) { return a.x<b.x+b.width && a.x+a.width>b.x && a.y<b.y+b.height && a.y+a.height>b.y }
function placement(preferred, dimensions, occupied, area, candidates, edges) {
  var probe={x:preferred.x,y:preferred.y,width:dimensions.width,height:dimensions.height}
  var mx=Math.min(8,Math.max(0,(area.width-dimensions.width)/2)),my=Math.min(8,Math.max(0,(area.height-dimensions.height)/2))
  var left=area.x+mx,right=area.x+area.width-mx-dimensions.width,top=area.y+my,bottom=area.y+area.height-my-dimensions.height
  function bounded(point) {
    var result={x:clamp(point.x,left,right),y:clamp(point.y,top,bottom)}
    if(!edges) return result
    var choices=[{x:right,y:result.y},{x:left,y:result.y},{x:result.x,y:top},{x:result.x,y:bottom}]
    choices.sort(function(a,b) {return Math.pow(a.x-result.x,2)+Math.pow(a.y-result.y,2)-Math.pow(b.x-result.x,2)-Math.pow(b.y-result.y,2)})
    return choices[0]
  }
  function free(point) {
    probe.x=point.x;probe.y=point.y
    return !occupied.some(function(rect) {
      return probe.x<rect.x+rect.width+8 && probe.x+probe.width+8>rect.x && probe.y<rect.y+rect.height+8 && probe.y+probe.height+8>rect.y
    })
  }
  preferred=bounded(preferred)
  if(free(preferred)) return preferred
  var choices=candidates.slice(),xs=[preferred.x,area.x,area.x+area.width-dimensions.width],ys=[preferred.y,area.y,area.y+area.height-dimensions.height]
  occupied.forEach(function(rect) {xs.push(rect.x-dimensions.width-8,rect.x+rect.width+8);ys.push(rect.y-dimensions.height-8,rect.y+rect.height+8)})
  xs.forEach(function(x) {ys.forEach(function(y) {choices.push(position({x:x,y:y,width:dimensions.width,height:dimensions.height},area))})})
  choices=choices.map(bounded)
  choices.sort(function(a,b) {return Math.pow(a.x-preferred.x,2)+Math.pow(a.y-preferred.y,2)-Math.pow(b.x-preferred.x,2)-Math.pow(b.y-preferred.y,2)})
  for(var i=0;i<choices.length;i++) if(free(choices[i])) return choices[i]
  return null
}
function slots(area, width, height, edges) {
  area=rectangle(area)
  var margin=Math.min(8,Math.max(0,(area.width-width)/2),Math.max(0,(area.height-height)/2)),gap=8
  var columns=Math.max(1,Math.floor((area.width-margin*2+gap)/(width+gap))),rows=Math.max(1,Math.floor((area.height-margin*2+gap)/(height+gap)))
  var left=area.x+margin,right=area.x+area.width-margin-width,top=area.y+margin,bottom=area.y+area.height-margin-height
  var ys=[];for(var row=0;row<rows;row++) ys.push(rows===1 ? (top+bottom)/2 : top+(bottom-top)*row/(rows-1))
  ys.sort(function(a,b) { return Math.abs(a-(top+bottom)/2)-Math.abs(b-(top+bottom)/2) })
  var result=[]
  for(var column=0;column<columns;column++) {
    if(edges && column>0 && column<columns-1) continue
    var x=columns===1 ? right : right-(right-left)*column/(columns-1)
    ys.forEach(function(y) { result.push({x:x,y:y}) })
  }
  if(edges && columns>2) for(var c=1;c<columns-1;c++) {
    var px=right-(right-left)*c/(columns-1)
    result.push({x:px,y:top});if(rows>1) result.push({x:px,y:bottom})
  }
  return result
}
function layout(groups, saved, drafts, area, options) {
  options=options || {};area=rectangle(area);saved=saved || {};drafts=drafts || {}
  var titles=options.titles===true,frame=options.frame===true,scale=finite(options.scale,100),sizes={},width=1,height=1
  groups.forEach(function(group) {
    var key="preview:"+group.key,value=drafts[key] || saved[key]
    var requested=options.sizing==="preset" ? 280*scale/100 : value && value.length>=3 ? finite(value[2],280) : 280
    var d=dimensions(requested,group.windows[0],area,titles,frame)
    sizes[key]=d;width=Math.max(width,d.width);height=Math.max(height,d.height)
  })
  var available=slots(area,width,height,options.edges!==false),capacity=Math.max(1,available.length),packed=[[]],result={}
  // Honour existing placements before assigning slots to new cards. An
  // arbitrarily placed saved card can consume several regular grid slots;
  // add an overflow page rather than overlap an inaccessible thumbnail.
  var order=groups.map(function(group,index) {var key="preview:"+group.key;return {group:group,index:index,saved:!!(drafts[key] || saved[key])}})
  order.sort(function(a,b) {return Number(b.saved)-Number(a.saved) || a.index-b.index})
  order.forEach(function(entry) {
    var group=entry.group,key="preview:"+group.key,d=sizes[key],value=drafts[key] || saved[key],slot=available[entry.index%capacity]
    var preferred=position({x:value && value.length>=2 ? value[0] : slot.x,y:value && value.length>=2 ? value[1] : slot.y,width:d.width,height:d.height},area),p=null,pageIndex=0
    for(;pageIndex<packed.length;pageIndex++) {
      if(packed[pageIndex].length>=capacity) continue
      p=placement(preferred,d,packed[pageIndex],area,available,options.edges!==false);if(p) break
    }
    if(!p) {packed.push([]);pageIndex=packed.length-1;p=placement(preferred,d,[],area,available,options.edges!==false)}
    var rect={x:p.x,y:p.y,width:d.width,height:d.height,page:pageIndex,index:entry.index}
    packed[pageIndex].push(rect);result[key]=rect
  })
  var pages=Math.max(1,packed.length),page=clamp(Math.floor(finite(options.page,0)),0,pages-1)
  Object.keys(result).forEach(function(key) {result[key].visible=result[key].page===page})
  return {cards:result,capacity:capacity,pages:pages,page:page}
}
function groupGrid(records, anchor, area, titles, frame, requestedWidth) {
  area=rectangle(area)
  var gap=8,width=Math.min(finite(requestedWidth,280),area.width),columns=Math.max(1,Math.min(records.length,Math.floor((area.width+gap)/(Math.min(width,160)+gap))))
  width=Math.min(width,(area.width-gap*(columns-1))/columns)
  var rowY=0,rowHeight=0,cells={}
  records.forEach(function(record,index) {
    if(index>0 && index%columns===0) {rowY+=rowHeight+gap;rowHeight=0}
    var d=dimensions(width,record,area,titles,frame)
    cells[record.id]={x:(index%columns)*(width+gap),y:rowY,width:d.width,height:d.height}
    rowHeight=Math.max(rowHeight,d.height)
  })
  var contentHeight=rowY+rowHeight,totalWidth=columns*width+Math.max(0,columns-1)*gap
  var height=Math.min(area.height,contentHeight),x=anchor.x-totalWidth-gap
  if(x<area.x) x=anchor.x+anchor.width+gap
  var p=position({x:x,y:anchor.y,width:totalWidth,height:height},area)
  return {x:p.x,y:p.y,width:totalWidth,height:height,contentHeight:contentHeight,columns:columns,cells:cells,overflow:contentHeight>height+.01}
}
