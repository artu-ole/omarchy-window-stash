.pragma library

function iconRadius(shape, size, bubble, themeRadius) {
  if (shape === "circle") return size / 2
  if (shape === "square") return 0
  if (shape === "rounded") return size * 0.2
  if (shape === "squircle") return size * 0.25
  return bubble ? size / 2 : themeRadius
}

function alignedIconSize(frame, desired, scale) {
  scale = Math.max(1, Number(scale) || 1)
  var framePixels = Math.round(frame * scale)
  var pixels = Math.min(framePixels, Math.max(1, Math.round(desired * scale)))
  if ((framePixels - pixels) % 2 !== 0) pixels = Math.max(1, pixels - 1)
  return pixels / scale
}

function artworkSize(frame, desired, radius, shape, inset, scale, frameless) {
  if (frameless) return alignedIconSize(frame,frame-4,scale)
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

function bubblePosition(saved, index, width, height, count) {
  var rowsPerColumn = Math.max(1, Math.floor((height - 90) / 64))
  var column = Math.floor(index / rowsPerColumn)
  var rows = Math.min(rowsPerColumn, Math.max(index + 1, count || 1) - column * rowsPerColumn)
  var top = (height - 48 - (rows - 1) * 64) / 2
  var fallback = [width - 68 - 64 * column, top + 64 * (index % rowsPerColumn)]
  var pos = saved || fallback
  return [Math.max(8, Math.min(width - 56, pos[0])), Math.max(32, Math.min(height - 56, pos[1]))]
}

function floatingAnchor(saved, width, height) {
  var x = saved ? saved[0] : width - 68
  var y = saved ? saved[1] : (height - 48) / 2
  return [Math.max(8, Math.min(width - 56, x)), Math.max(32, Math.min(height - 64, y))]
}

function dockLength(count, size, gap) {
  return count > 0 ? count * size + (count - 1) * gap : 0
}

function floatingPanel(x, y, handleHeight, width, height, count, padding, gap, rowHeight, preferredDown, horizontal, endPadding) {
  var margin = 8, panelWidth = rowHeight + padding * 2
  var ends = typeof endPadding === "number" ? Math.max(padding,endPadding) : padding
  var desired = dockLength(count,rowHeight,gap) + ends * 2
  if (horizontal) {
    var right = Math.max(0, width - margin - x - 48 - gap)
    var left = Math.max(0, x - gap - margin)
    var forward = typeof preferredDown === "boolean" ? preferredDown : right >= desired || right >= left
    var extent = Math.min(desired, forward ? right : left)
    return {x:forward ? x + 48 + gap : x - gap - extent,
      y:Math.max(margin, Math.min(height - margin - panelWidth, y + (48 - panelWidth) / 2)),
      width:extent,height:panelWidth,forward:forward,right:forward,down:false,horizontal:true}
  }
  var below = Math.max(0, height - margin - y - handleHeight - gap)
  var above = Math.max(0, y - gap - margin)
  var down = typeof preferredDown === "boolean" ? preferredDown : below >= desired || below >= above
  var panelHeight = Math.min(desired, down ? below : above)
  return {x:Math.max(margin, Math.min(width - margin - panelWidth, x + (48 - panelWidth) / 2)),
    y:down ? y + handleHeight + gap : y - gap - panelHeight,
    width:panelWidth, height:panelHeight, down:down,forward:down,right:false,horizontal:false}
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

function staticDockRect(area, side, desiredWidth, desiredHeight, gap, longMargin) {
  var vertical = side === "left" || side === "right"
  var marginX = Math.min(vertical ? gap : longMargin, area.width / 2)
  var marginY = Math.min(vertical ? longMargin : gap, area.height / 2)
  var width = Math.max(0, Math.min(desiredWidth, area.width - marginX * 2))
  var height = Math.max(0, Math.min(desiredHeight, area.height - marginY * 2))
  var x = area.x + Math.round((area.width-width)/2)
  var y = area.y + Math.round((area.height-height)/2)
  if (side === "left") x = area.x + marginX
  else if (side === "right") x = area.x + area.width - marginX - width
  else if (side === "top") y = area.y + marginY
  else y = area.y + area.height - marginY - height
  return {x:x, y:y, width:width, height:height}
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

function floatingPosition(saved, width, height, area, snap, itemHeight) {
  var point=floatingAnchor(saved,width,height)
  return snap ? edgeTargets(point,area,48,itemHeight)[0].point : point
}

function bubbleLayout(keys, saved, drafts, width, height, area, snap, compact) {
  var placed=[], size=48, gap=4, crowded=false
  keys.forEach(function(key,index) {
    var point=bubblePosition(drafts[key] || saved[key],index,width,height,keys.length)
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
  if (crowded && !compact) return bubbleLayout(keys,saved,drafts,width,height,area,snap,true)
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
