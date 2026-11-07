.pragma library

function sizeScale(preset) {
  return ["50","75","100","125","150","175","200","250","300"].indexOf(preset)>=0 ? Number(preset)/100 : 1
}

function iconSize(preset, bubble, area) {
  var desired=Math.round((bubble ? 48 : 44)*sizeScale(preset))
  if (!area) return desired
  if (Math.floor(area.width)<=0 || Math.floor(area.height)<=0) return 0
  // Leave room for chrome, edge margins and the floating stack's scaled tail.
  var available=bubble ? Math.min(area.width-32,(area.height-32)/(7/6)) : Math.min(area.width,area.height)-40
  return Math.max(1,Math.min(desired,Math.floor(available),Math.floor(area.width),Math.floor(area.height)))
}

function iconRadius(shape, size, bubble, themeRadius) {
  if (shape === "circle") return size / 2
  if (shape === "square") return 0
  if (shape === "rounded") return size * 0.2
  if (shape === "squircle") return size * 0.25
  return bubble ? size / 2 : themeRadius
}

// Match StashIconRegion, including its integer superellipse scanlines.
function iconContains(x, y, size, shape, radius) {
  if (size<=0 || x<0 || y<0 || x>=size || y>=size) return false
  if (shape==="squircle") {
    return squircleBands(size,size).some(function(band) {
      return y>=band.y && y<band.y+band.height && x>=band.x && x<band.x+band.width
    })
  }
  radius=Math.max(0,Math.min(size/2,radius || 0))
  var dx=Math.max(radius-x,0,x-size+radius),dy=Math.max(radius-y,0,y-size+radius)
  return dx*dx+dy*dy<=radius*radius
}

function alignedIconSize(frame, desired, scale) {
  scale = Math.max(1, Number(scale) || 1)
  var framePixels = Math.round(frame * scale)
  var pixels = Math.min(framePixels, Math.max(1, Math.round(desired * scale)))
  if ((framePixels - pixels) % 2 !== 0) pixels = Math.max(1, pixels - 1)
  return pixels / scale
}

function artworkSize(frame, desired, radius, shape, inset, scale, frameless, sizeScale) {
  if (frameless) return alignedIconSize(frame,frame-4*(sizeScale===undefined ? 1 : sizeScale),scale)
  scale = Math.max(1, Number(scale) || 1)
  var half = Math.max(0, frame / 2 - inset)
  var r = Math.max(0, Math.min(half, radius - inset))
  var limit = shape === "squircle" ? half * 2 * Math.pow(0.5, 0.25)
    : 2 * (half - r + r / Math.sqrt(2))
  // Fit the outermost pixel centers inside the frame while keeping crisp,
  // centered artwork. Circular shapes need more corner clearance than squares.
  return alignedIconSize(frame, Math.min(desired, limit + 1 / scale), scale)
}

// The fourth-order superellipse has continuously changing curvature rather
// than the straight sides and circular corner arcs of a rounded square.
function squirclePath(width, height, left, top, right, bottom, reverse) {
  var rx = (width - left - right) / 2, ry = (height - top - bottom) / 2
  if (rx <= 0 || ry <= 0) return ""
  var cx = left + rx, cy = top + ry, path = []
  for (var i = 0; i < 128; i++) {
    var angle = (reverse ? -1 : 1) * i * Math.PI / 64
    var c = Math.cos(angle), s = Math.sin(angle)
    var x = cx + Math.sign(c) * Math.sqrt(Math.abs(c)) * rx
    var y = cy + Math.sign(s) * Math.sqrt(Math.abs(s)) * ry
    path.push((i === 0 ? "M " : "L ") + x.toFixed(4) + " " + y.toFixed(4))
  }
  return path.join(" ") + " Z"
}

// Integer scanlines use the same superellipse as the visible shape. Adjacent
// identical rows are merged to keep the compositor's input region small.
function squircleBands(width, height) {
  var result = [], cx = width / 2, cy = height / 2
  for (var y = 0; y < height; y++) {
    var half = cx * Math.pow(Math.max(0, 1 - Math.pow((y + 0.5 - cy) / cy, 4)), 0.25)
    var left = Math.max(0, Math.ceil(cx - half - 0.5))
    var right = Math.min(width, Math.floor(cx + half - 0.5) + 1)
    var last = result.length ? result[result.length - 1] : null
    if (last && last.x === left && last.width === right - left) last.height++
    else result.push({x:left, y:y, width:right-left, height:1})
  }
  return result
}

function gradientLine(width, height, angle) {
  var radians = Number(angle || 0) * Math.PI / 180
  var dx = Math.cos(radians), dy = Math.sin(radians)
  var extent = (Math.abs(width * dx) + Math.abs(height * dy)) / 2
  return {x1:width/2-dx*extent, y1:height/2-dy*extent,
    x2:width/2+dx*extent, y2:height/2+dy*extent}
}

function visibleWindows(windows, workspace, scope) {
  return windows.filter(function(w) { return scope === "global" || Number(w.origin.id) === Number(workspace) })
    .sort(function(a, b) { return b.order - a.order })
}

function groups(windows, grouping) {
  if (grouping === "window") return windows.map(function(w) {
    return { key: "window:" + (w.stableId || w.id), app: w.app, title: w.title, windows: [w] }
  })
  var result = [], byApp = {}
  windows.forEach(function(w) {
    var key = "app:" + String(w.app || "unknown").toLowerCase()
    if (!byApp[key]) {
      byApp[key] = { key: key, app: w.app, title: w.app || "Application", windows: [] }
      result.push(byApp[key])
    }
    byApp[key].windows.push(w)
  })
  return result
}

function monitorKey(monitor) {
  return [monitor.make || "", monitor.model || "", monitor.serial || "", monitor.description || ""].join("|")
}

// Keep existing floating/bubble keys unchanged. Static docks need distinct
// output names when a display supplies no identifying metadata at all.
function staticDockMonitorKey(monitor) {
  monitor=monitor || {}
  var identity=monitorKey(monitor)
  return identity.split("|").some(function(part) { return part.trim().length>0 })
    ? identity : "output:"+String(monitor.name || "")
}

function bubblePosition(saved, index, width, height, count, itemSize) {
  var size=itemSize===undefined ? 48 : itemSize,scale=size/48,step=size+16*scale
  var rowsPerColumn = Math.max(1, Math.floor((height - 32 - 58*scale) / Math.max(1,step)))
  var column = Math.floor(index / rowsPerColumn)
  var rows = Math.min(rowsPerColumn, Math.max(index + 1, count || 1) - column * rowsPerColumn)
  var top = (height - size - (rows - 1) * step) / 2
  var fallback = [width - size - 20*scale - step * column, top + step * (index % rowsPerColumn)]
  var pos = saved || fallback
  var minX=Math.min(8,Math.max(0,width-size)),minY=Math.min(32,Math.max(0,height-size))
  return [Math.max(minX, Math.min(width-size-8, pos[0])), Math.max(minY, Math.min(height-size-8, pos[1]))]
}

function floatingAnchor(saved, width, height, itemSize, itemHeight) {
  var size=itemSize===undefined ? 48 : itemSize,scale=size/48
  var bodyHeight=itemHeight===undefined ? size+8*scale : itemHeight
  var x = saved ? saved[0] : width-size-20*scale
  var y = saved ? saved[1] : (height-size)/2
  var minX=Math.min(8,Math.max(0,width-size)),minY=Math.min(32,Math.max(0,height-bodyHeight))
  return [Math.max(minX, Math.min(width-size-8, x)), Math.max(minY, Math.min(height-Math.max(size+16*scale,bodyHeight+8), y))]
}

function dockLength(count, size, gap) {
  return count > 0 ? count * size + (count - 1) * gap : 0
}

// Hyprland reserved edges are logical pixels in left/top/right/bottom order.
function usableArea(width, height, reserved) {
  reserved = reserved || []
  var left = Math.max(0, Number(reserved[0]) || 0)
  var top = Math.max(0, Number(reserved[1]) || 0)
  var right = Math.max(0, Number(reserved[2]) || 0)
  var bottom = Math.max(0, Number(reserved[3]) || 0)
  return {x:left, y:top, width:Math.max(0, width-left-right), height:Math.max(0, height-top-bottom)}
}

function staticDockNumber(value, fallback) {
  // Keep geometry arithmetic finite even for malformed, enormous inputs.
  var limit=Number.MAX_SAFE_INTEGER/4
  return typeof value==="number" && isFinite(value) ? Math.max(-limit,Math.min(limit,value)) : fallback
}

function staticDockFraction(value) {
  return typeof value==="number" && isFinite(value) ? Math.max(0,Math.min(1,value)) : .5
}

function staticDockMetrics(area, side, desiredWidth, desiredHeight, gap, longMargin) {
  area=area || {}
  area={x:staticDockNumber(area.x,0),y:staticDockNumber(area.y,0),
    width:Math.max(0,staticDockNumber(area.width,0)),height:Math.max(0,staticDockNumber(area.height,0))}
  gap=Math.max(0,staticDockNumber(gap,0)); longMargin=Math.max(0,staticDockNumber(longMargin,0))
  desiredWidth=Math.max(0,staticDockNumber(desiredWidth,0)); desiredHeight=Math.max(0,staticDockNumber(desiredHeight,0))
  var vertical = side === "left" || side === "right"
  var marginX = Math.min(vertical ? gap : longMargin, area.width / 2)
  var marginY = Math.min(vertical ? longMargin : gap, area.height / 2)
  var width = Math.max(0, Math.min(desiredWidth, area.width - marginX * 2))
  var height = Math.max(0, Math.min(desiredHeight, area.height - marginY * 2))
  return {area:area,vertical:vertical,width:width,height:height,marginX:marginX,marginY:marginY,
    start:vertical ? area.y+marginY : area.x+marginX,
    travel:Math.max(0,vertical ? area.height-height-marginY*2 : area.width-width-marginX*2)}
}

// Position is the fraction of available long-axis travel between edge margins.
// The default retains the original pixel-rounded center exactly.
function staticDockRect(area, side, desiredWidth, desiredHeight, gap, longMargin, position) {
  var metrics=staticDockMetrics(area,side,desiredWidth,desiredHeight,gap,longMargin)
  area=metrics.area
  var vertical=metrics.vertical,width=metrics.width,height=metrics.height
  var marginX=metrics.marginX,marginY=metrics.marginY
  position=staticDockFraction(position)
  var x = area.x + Math.round((area.width-width)/2)
  var y = area.y + Math.round((area.height-height)/2)
  if (position!==.5) {
    if (vertical) y=area.y+Math.round(marginY+metrics.travel*position)
    else x=area.x+Math.round(marginX+metrics.travel*position)
  }
  if (side === "left") x = area.x + marginX
  else if (side === "right") x = area.x + area.width - marginX - width
  else if (side === "top") y = area.y + marginY
  else y = area.y + area.height - marginY - height
  x=Math.max(area.x,Math.min(area.x+area.width-width,x))
  y=Math.max(area.y,Math.min(area.y+area.height-height,y))
  return {x:x, y:y, width:width, height:height}
}

// Coordinate is the desired leading x (horizontal) or y (vertical), not the
// pointer center. Keep the saved fraction when overflow leaves no travel.
function staticDockPosition(area, side, desiredWidth, desiredHeight, gap, longMargin, coordinate, fallback) {
  fallback=staticDockFraction(fallback)
  var metrics=staticDockMetrics(area,side,desiredWidth,desiredHeight,gap,longMargin)
  if (!metrics.travel || typeof coordinate!=="number" || !isFinite(coordinate)) return fallback
  return Math.max(0,Math.min(1,(coordinate-metrics.start)/metrics.travel))
}

// Stored with the other position tuples as [basis points, 0], independently
// for each static side. Decimal basis points preserve drag precision.
function staticDockSavedPosition(saved) {
  return Array.isArray(saved) && saved.length===2 && typeof saved[0]==="number" && isFinite(saved[0])
    && saved[0]>=0 && saved[0]<=10000 && saved[1]===0 ? saved[0]/10000 : .5
}

function edgeTargets(point, area, width, height) {
  var minX=area.x+Math.min(8,area.width/2), minY=area.y+Math.min(8,area.height/2)
  var maxX=Math.max(minX,area.x+area.width-8-width), maxY=Math.max(minY,area.y+area.height-8-height)
  var x=Math.max(minX,Math.min(maxX,point[0])), y=Math.max(minY,Math.min(maxY,point[1]))
  return [{point:[minX,y],vertical:true}, {point:[maxX,y],vertical:true},
    {point:[x,minY],vertical:false}, {point:[x,maxY],vertical:false}]
    .sort(function(a,b) {
      function distance(p) { return Math.pow(p[0]-point[0],2)+Math.pow(p[1]-point[1],2) }
      return distance(a.point)-distance(b.point)
    })
}

function floatingPosition(saved, width, height, area, snap, itemHeight, itemSize) {
  var size=itemSize===undefined ? 48 : itemSize
  var point=itemSize===undefined ? floatingAnchor(saved,width,height) : floatingAnchor(saved,width,height,size,itemHeight)
  if (snap) return edgeTargets(point,area,size,itemHeight)[0].point
  return itemSize===undefined ? point : [Math.max(area.x,Math.min(area.x+Math.max(0,area.width-size),point[0])),
    Math.max(area.y,Math.min(area.y+Math.max(0,area.height-itemHeight),point[1]))]
}

function bubbleLayout(keys, saved, drafts, width, height, area, snap, compact, itemSize, itemGap) {
  var placed=[], size=itemSize===undefined ? 48 : itemSize, gap=itemGap===undefined ? 4 : itemGap, crowded=false
  keys.forEach(function(key,index) {
    var point=bubblePosition(drafts[key] || saved[key],index,width,height,keys.length,size)
    if (itemSize!==undefined) point=[Math.max(area.x,Math.min(area.x+Math.max(0,area.width-size),point[0])),
      Math.max(area.y,Math.min(area.y+Math.max(0,area.height-size),point[1]))]
    if (!snap) { placed.push(point); return }
    var edges=edgeTargets(point,area,size,size), chosen=null
    for (var i=0;i<edges.length && !chosen;i++) {
      var edge=edges[i], axis=edge.vertical ? 1 : 0
      var low=axis ? area.y+8 : area.x+8
      var high=Math.max(low,(axis ? area.y+area.height : area.x+area.width)-8-size)
      var slots=[edge.point[axis],low,high]
      placed.forEach(function(p) { slots.push(p[axis]-size-gap,p[axis]+size+gap) })
      if (compact) {
        slots=[]
        for (var slot=low;slot<=high;slot+=size+gap) slots.push(slot)
      }
      slots=slots.map(function(value) { return Math.max(low,Math.min(high,value)) })
        .sort(function(a,b) { return Math.abs(a-point[axis])-Math.abs(b-point[axis]) })
      for (var j=0;j<slots.length;j++) {
        var candidate=edge.point.slice(); candidate[axis]=slots[j]
        if (placed.every(function(p) { return candidate[0]>=p[0]+size+gap || candidate[0]+size+gap<=p[0]
          || candidate[1]>=p[1]+size+gap || candidate[1]+size+gap<=p[1] })) { chosen=candidate; break }
      }
    }
    if (!chosen) crowded=true
    placed.push(chosen || edges[0].point)
  })
  // Repack fragmented gaps before treating a perimeter as full. With more
  // icons than fit on every edge, retain all icons at their nearest edge.
  if (crowded && !compact) return bubbleLayout(keys,saved,drafts,width,height,area,snap,true,itemSize,itemGap)
  return placed
}

function dockRadius(mode, custom, theme, width, height) {
  var radius=mode === "custom" && typeof custom === "number" && isFinite(custom) && custom >= 0 && custom <= 64
    ? custom : theme
  return Math.max(0,Math.min(radius,width/2,height/2))
}

// Distance along a rounded end at the content's nearest cross-axis edge.
// Keep the entire rectangular icon/button inside the border's inner arc.
function dockEndInset(radius, crossInset, border) {
  var inner=Math.max(0,radius-border)
  var offset=Math.max(0,Math.min(inner,radius-crossInset))
  return Math.ceil(border+inner-Math.sqrt(Math.max(0,inner*inner-offset*offset)))
}

// Preserve retiring slots while merging new keys and ordering the active ones.
function reconcileKeys(previous, desired) {
  var result=previous.slice()
  desired.forEach(function(key,index) {
    if (result.indexOf(key)>=0) return
    var slots=[]
    result.forEach(function(old,i) { if (desired.indexOf(old)>=0) slots.push(i) })
    result.splice(index<slots.length ? slots[index] : slots.length ? result.length : 0,0,key)
  })
  var active=[]
  result.forEach(function(key,i) { if (desired.indexOf(key)>=0) active.push(i) })
  active.forEach(function(at,i) { result[at]=desired[i] })
  return result
}

// Fan toward available space. An existing stack supplies its exact tile origin;
// pointer-centered placement remains available for callers without an anchor.
function fanLayout(px, py, area, count, horizontal, size, gap, inset, endInset, preferredSign, preferredCurve, anchor) {
  var padX=horizontal ? endInset : inset, padY=horizontal ? inset : endInset
  var x=Math.max(area.x+padX,Math.min(area.x+area.width-size-padX,px-size/2))
  var y=Math.max(area.y+padY,Math.min(area.y+area.height-size-padY,py-size/2))
  // Near an edge, cursor coverage takes precedence over symmetric padding.
  x=Math.max(area.x,Math.min(area.x+Math.max(0,area.width-size),Math.min(px,Math.max(px-size+1,x))))
  y=Math.max(area.y,Math.min(area.y+Math.max(0,area.height-size),Math.min(py,Math.max(py-size+1,y))))
  if (anchor) { x=anchor.x; y=anchor.y }
  var step=size+gap
  var ahead=horizontal ? area.x+area.width-padX-x-size : area.y+area.height-padY-y-size
  var behind=horizontal ? x-area.x-padX : y-area.y-padY
  var sign=preferredSign===1 || preferredSign===-1 ? preferredSign
    : ahead >= dockLength(count,size,gap)-size || ahead >= behind ? 1 : -1
  var capacity=count ? Math.min(count,Math.max(1,1+Math.floor(Math.max(0,sign>0 ? ahead : behind)/step))) : 0
  var crossBefore=horizontal ? y-area.y : x-area.x
  var crossAfter=horizontal ? area.y+area.height-y-size : area.x+area.width-x-size
  // Horizontal curves always lift above the row, in either travel direction.
  // Near the top, reduce the arch rather than flipping it below the icons.
  // Vertical curves keep their preferred side or use the available space.
  var curveSign=horizontal ? -1
    : preferredCurve===1 || preferredCurve===-1 ? preferredCurve : crossBefore>=crossAfter ? -1 : 1
  var curveRoom=horizontal ? crossBefore : Math.max(crossBefore,crossAfter)
  var hopSign=curveSign
  var hopRoom=hopSign<0 ? crossBefore : crossAfter
  return {x:anchor ? x : Math.round(x),y:anchor ? y : Math.round(y),horizontal:horizontal,sign:sign,forward:sign>0,
    capacity:capacity,step:step,size:size,tailStep:4*size/48,span:dockLength(capacity,size,gap),
    curveSign:curveSign,curveLimit:Math.max(0,Math.min(18*size/48,curveRoom-inset)),
    hopSign:hopSign,hopLimit:Math.max(0,Math.min(28*size/48,hopRoom-inset))}
}

function fanSlot(layout, index, first) {
  var slot=Math.max(0,Math.min(Math.max(0,layout.capacity-1),index-first))
  return {x:layout.x+(layout.horizontal ? layout.sign*slot*layout.step : 0),
    y:layout.y+(layout.horizontal ? 0 : layout.sign*slot*layout.step),
    shown:index>=first && index<first+layout.capacity}
}

// A linear clock stages anticipation, flight and two damped landing rebounds.
// Keep deformation inside the tile so frames, artwork and input stay bounded.
function fanJumpPose(sx, sy, tx, ty, progress, ordinal, layout, area) {
  var p=Math.max(0,Math.min(1,progress))
  var result={x:sx,y:sy,bend:0,tilt:0,scale:1,stretchX:1,stretchY:1,jumpPhase:"stacked"}
  if (p===1) { result.x=tx; result.y=ty; result.jumpPhase="settled"; return result }
  if (p===0 || (ordinal===0 && sx===tx && sy===ty)) return result
  var travel=0,bend=0,compression=0
  var limit=layout.hopLimit===undefined ? layout.curveLimit : layout.hopLimit
  var sign=layout.horizontal ? -1 : layout.hopSign===1 || layout.hopSign===-1 ? layout.hopSign : layout.curveSign
  if (p<=.12) {
    result.jumpPhase="launch"
    compression=.12*Math.sin(Math.PI*p/.12)
  } else if (p<.68) {
    result.jumpPhase="flight"
    var f=(p-.12)/.56
    travel=f*f*(3-2*f)
    bend=Math.sin(Math.PI*f)*limit
    var impact=Math.max(0,Math.min(1,(f-.85)/.15))
    compression=-.09*Math.sin(Math.PI*f)+.13*impact*impact*(3-2*impact)
  } else {
    result.jumpPhase="landing"
    var q=(p-.68)/.32,wave=Math.sin(2*Math.PI*q)
    travel=1
    bend=limit*.32*Math.pow(1-q,1.3)*wave*wave
    compression=.13*(1-q)*(1-q)*Math.cos(4*Math.PI*q)
  }
  var wide=1+compression*.4,tall=1-compression,fit=Math.max(1,wide,tall)
  result.stretchX=(layout.horizontal ? wide : tall)/fit
  result.stretchY=(layout.horizontal ? tall : wide)/fit
  result.x=Math.max(area.x,Math.min(area.x+area.width-layout.size,sx+(tx-sx)*travel+(layout.horizontal ? 0 : bend*sign)))
  result.y=Math.max(area.y,Math.min(area.y+area.height-layout.size,sy+(ty-sy)*travel+(layout.horizontal ? bend*sign : 0)))
  result.bend=bend
  return result
}

function fanPose(sx, sy, tx, ty, progress, ordinal, layout, area, style) {
  if (style==="jumping") return fanJumpPose(sx,sy,tx,ty,progress,ordinal,layout,area)
  var unit=Math.max(0,Math.min(1,progress)),phase=unit>0 && unit<1 ? Math.sin(Math.PI*unit) : 0
  var amplitude=8+Math.max(0,ordinal)*3, tilt=0, shrink=.035
  if (style === "glide") { amplitude=0; shrink=0 }
  else if (style === "cascade") { amplitude=0; shrink=.07 }
  else if (style === "spring") { amplitude=4; shrink=.055 }
  else if (style === "swing") {
    amplitude=16+Math.max(0,ordinal)*2; shrink=.025
    tilt=phase*layout.curveSign*Math.min(9,4+Math.max(0,ordinal)*2)
  }
  var fixed=ordinal===0 && sx===tx && sy===ty
  if (fixed) {
    amplitude=0
    shrink=style==="glide" ? 0 : style==="spring" ? .02 : style==="cascade" ? .012 : .008
    tilt=style==="swing" ? phase*layout.curveSign : 0
  }
  var bend=phase*Math.min(layout.curveLimit,amplitude*layout.size/48)
  // Keep rotated corners within the same square input/work-area envelope.
  var radians=tilt*Math.PI/180,fit=1/(Math.abs(Math.cos(radians))+Math.abs(Math.sin(radians)))
  return {x:fixed ? sx : Math.max(area.x,Math.min(area.x+area.width-layout.size,sx+(tx-sx)*progress+(layout.horizontal ? 0 : bend*layout.curveSign))),
    y:fixed ? sy : Math.max(area.y,Math.min(area.y+area.height-layout.size,sy+(ty-sy)*progress+(layout.horizontal ? bend*layout.curveSign : 0))),
    bend:bend,tilt:tilt,scale:Math.min(1-shrink*phase,fit)}
}

// One clock moves the entire remaining stack one slot at a time. At each
// landing its leading icon stays behind, and the smaller stack moves onward.
// Reading this same pose function backwards gathers the icons on that path.
function fanChainPose(sx, sy, tx, ty, progress, ordinal, layout, area, style, firstIndex, chainCount) {
  var p=Math.max(0,Math.min(1,progress)), first=Math.max(0,firstIndex || 0)
  var count=Math.max(1,Math.floor(chainCount===undefined ? layout.capacity : chainCount))
  var hops=count-1,slot=Math.max(0,Math.min(hops,ordinal-first))
  var raw=p*hops,stage=Math.min(hops,Math.floor(raw)),fraction=raw-stage
  // A short landing dwell lets the next group visibly separate. Smoothstep's
  // zero velocity at both ends gives every departure and arrival some weight.
  var u=Math.min(1,fraction/.86),ease=u*u*(3-2*u)
  var phase=p>0 && p<1 ? Math.sin(Math.PI*p) : 0
  var result={x:sx,y:sy,bend:0,tilt:0,scale:1,stage:stage,slot:slot,targetSlot:slot,settled:slot<=stage,groupOffset:0}
  // At full unfold the destination can keep moving as paging or removal
  // reflows slots; even a new front icon must follow that animation.
  if (p===1) { result.x=tx; result.y=ty; return result }
  if (ordinal===0) { result.scale=1-.008*phase; return result }
  var tailStep=layout.tailStep===undefined ? 4*layout.size/48 : layout.tailStep
  if (p===0) { result.slot=0; result.groupOffset=Math.min(ordinal,2)*tailStep; return result }
  var originalOffset=Math.min(Math.max(0,ordinal),2)*tailStep
  var anchorY=sy-originalOffset
  if (!hops) {
    var single=p*p*(3-2*p)
    result.x=sx+(tx-sx)*single; result.y=sy+(ty-sy)*single
    result.groupOffset=originalOffset*(1-single)
    return result
  }
  // A fan closed from another page still ends at the original preview stack.
  // Peel off its global preview offset during the first shared hop.
  var pageOffset=Math.min(slot,2)*tailStep
  var pageCorrection=stage===0 ? (originalOffset-pageOffset)*(1-ease) : 0
  if (slot<=stage) {
    result.x=tx; result.y=ty+pageCorrection; result.groupOffset=pageCorrection
    return result
  }
  var before=Math.min(slot-stage,2)*tailStep,after=Math.min(slot-stage-1,2)*tailStep
  var tail=before+(after-before)*ease+pageCorrection
  var distance=(stage+ease)*layout.sign*layout.step
  var x=sx+(layout.horizontal ? distance : 0)
  var y=anchorY+(layout.horizontal ? 0 : distance)+tail
  var bend=0
  if (style==="matryoshka-hop") {
    var sign=layout.hopSign===1 || layout.hopSign===-1 ? layout.hopSign : layout.curveSign
    var limit=layout.hopLimit===undefined ? Math.min(28*layout.size/48,layout.curveLimit) : layout.hopLimit
    bend=u>0 && u<1 ? Math.sin(Math.PI*u)*limit : 0
    // The whole remainder uses one safe cross-axis excursion, preserving its
    // layered silhouette rather than clamping individual icons differently.
    if (layout.horizontal) y+=bend*sign
    else x+=bend*sign
  }
  result.x=Math.max(area.x,Math.min(area.x+area.width-layout.size,x))
  result.y=Math.max(area.y,Math.min(area.y+area.height-layout.size,y))
  result.bend=bend; result.groupOffset=tail; result.slot=stage+ease
  return result
}

// Chrome follows the straight row/column, independently of airborne artwork.
// Capping elastic travel at the last slot prevents a rebound in panel length.
function fanPanelRects(rects, layout) {
  if (!layout.capacity) return []
  var distance=layout.sign*Math.max(0,layout.capacity-1)*layout.step
  var minX=layout.x+(layout.horizontal ? Math.min(0,distance) : 0)
  var maxX=layout.x+(layout.horizontal ? Math.max(0,distance) : 0)
  var minY=layout.y+(layout.horizontal ? 0 : Math.min(0,distance))
  var maxY=layout.y+(layout.horizontal ? 0 : Math.max(0,distance))
  return rects.map(function(r) {
    return {x:Math.max(minX,Math.min(maxX,r.x)),y:Math.max(minY,Math.min(maxY,r.y)),width:layout.size,height:layout.size}
  })
}

function fanBounds(rects, inset, endInset, horizontal, area) {
  if (!rects.length) return {x:area.x,y:area.y,width:0,height:0}
  var left=Infinity,top=Infinity,right=-Infinity,bottom=-Infinity
  rects.forEach(function(r) { left=Math.min(left,r.x); top=Math.min(top,r.y); right=Math.max(right,r.x+r.width); bottom=Math.max(bottom,r.y+r.height) })
  left=Math.max(area.x,left-(horizontal ? endInset : inset)); top=Math.max(area.y,top-(horizontal ? inset : endInset))
  right=Math.min(area.x+area.width,right+(horizontal ? endInset : inset)); bottom=Math.min(area.y+area.height,bottom+(horizontal ? inset : endInset))
  return {x:Math.floor(left),y:Math.floor(top),width:Math.ceil(right)-Math.floor(left),height:Math.ceil(bottom)-Math.floor(top)}
}

function fanRadius(frame, rects, desired, border) {
  var radius=Math.min(desired,frame.width/2,frame.height/2)
  rects.forEach(function(r) {
    var xs=[r.x-frame.x,frame.x+frame.width-r.x-r.width],ys=[r.y-frame.y,frame.y+frame.height-r.y-r.height]
    xs.forEach(function(x) { ys.forEach(function(y) {
      var a=Math.max(0,x-border),b=Math.max(0,y-border)
      radius=Math.min(radius,Math.max(0,a+b+border+Math.sqrt(2*a*b)))
    }) })
  })
  return Math.max(0,radius)
}
