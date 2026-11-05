.pragma library

function iconRadius(shape, size, bubble, themeRadius) {
  if (shape === "circle") return size / 2
  if (shape === "square") return 0
  if (shape === "rounded") return size * 0.2
  if (shape === "squircle") return size * 0.25
  return bubble ? size / 2 : themeRadius
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
