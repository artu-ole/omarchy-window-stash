.pragma library

function full(mode) { return mode !== "reduced" && mode !== "off" }
function speedRatio(speed) {
  if (speed === "slow") return .5
  if (speed === "relaxed") return .75
  if (speed === "fast") return 1.5
  if (speed === "ultrafast") return 2.5
  return 1
}
function scale(milliseconds, speed) {
  if (!isFinite(milliseconds) || milliseconds <= 0) return 0
  // Leave rounding to QML so staggering and shared clocks use the same ratio.
  return Math.max(1, milliseconds / speedRatio(speed))
}
function duration(mode, normal, reduced, speed) {
  return mode === "off" ? 0 : scale(mode === "reduced" ? (reduced || 0) : normal, speed)
}
function enter(mode, speed) { return duration(mode, 200, 120, speed) }
function exit(mode, speed) { return duration(mode, 140, 100, speed) }
function move(mode, speed) { return duration(mode, 200, 0, speed) }


// Full-motion profiles; Reduced/Off override these through duration()/full().
function fanProfile(style) {
  if (style === "matryoshka") return {name:style,open:170,close:150,stagger:0,limit:0,easing:"linear",overshoot:0,chain:true,openLimit:680,closeLimit:600,minimum:180}
  if (style === "matryoshka-hop") return {name:style,open:210,close:190,stagger:0,limit:0,easing:"linear",overshoot:0,chain:true,openLimit:740,closeLimit:680,minimum:210}
  if (style === "glide") return {name:style,open:260,close:220,stagger:0,limit:0,easing:"cubic",overshoot:0}
  if (style === "cascade") return {name:style,open:340,close:260,stagger:48,limit:192,easing:"quint",overshoot:0}
  if (style === "spring") return {name:style,open:460,close:340,stagger:18,limit:90,easing:"back",overshoot:1.5}
  if (style === "swing") return {name:style,open:390,close:310,stagger:22,limit:110,easing:"cubic",overshoot:0}
  return {name:"arc",open:330,close:280,stagger:14,limit:72,easing:"back",overshoot:.45}
}
function chain(style) { return style === "matryoshka" || style === "matryoshka-hop" }
function fanDuration(profile, opening, count) {
  var base=opening ? profile.open : profile.close
  if (profile.chain) return count<=1 ? profile.minimum : Math.min(opening ? profile.openLimit : profile.closeLimit,(count-1)*base)
  return base+Math.min(profile.limit,Math.max(0,count-1)*profile.stagger)
}
function fanDelay(profile, ordinal, opening, capacity) {
  if (profile.chain) return 0
  var index=Math.max(0,ordinal)
  if (profile.name === "cascade" && !opening) index=Math.max(0,capacity-1-index)
  return Math.min(profile.limit,index*profile.stagger)
}
