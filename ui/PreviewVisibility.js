.pragma library

// Capture is optional UI work. Unknown or stale output state must suspend it,
// especially while an ext-session-lock may be acquiring or restoring its lock.
function allowed(state, screenName, now) {
  if (!state || state.known!==true || !Array.isArray(state.monitors) || !state.monitors.length
      || !isFinite(state.checkedAt) || !isFinite(now) || now<state.checkedAt || now-state.checkedAt>2000) return false
  var monitors=state.monitors
  for (var i=0;i<monitors.length;i++) {
    var monitor=monitors[i]
    if (!monitor || typeof monitor!=="object") return false
    if (monitor.solitaryBlockedBy!==undefined && !Array.isArray(monitor.solitaryBlockedBy)) return false
    if (monitor.solitaryBlockedBy && monitor.solitaryBlockedBy.indexOf("LOCK")>=0) return false
  }
  var targets=monitors.filter(function(monitor) { return monitor.name===screenName })
  if (targets.length!==1) return false
  var target=targets[0]
  if (target.disabled===true || target.dpmsStatus===false || !(target.width>0) || !(target.height>0)) return false
  if (Array.isArray(target.solitaryBlockedBy)) return target.solitaryBlockedBy.indexOf("WORKSPACE")<0
  // Omarchy 4's older compositor does not expose solitaryBlockedBy. A mapped
  // monitor with a real active workspace is the compatible readable fallback.
  return !!target.activeWorkspace && Number(target.activeWorkspace.id)>0
}
