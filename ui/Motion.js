.pragma library

function full(mode) { return mode !== "reduced" && mode !== "off" }
function duration(mode, normal, reduced) {
  return mode === "off" ? 0 : mode === "reduced" ? (reduced || 0) : normal
}
function enter(mode) { return duration(mode, 200, 120) }
function exit(mode) { return duration(mode, 140, 100) }
function move(mode) { return duration(mode, 200, 0) }
