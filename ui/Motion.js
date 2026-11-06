.pragma library

function full(mode) { return mode !== "reduced" && mode !== "off" }
function duration(mode, normal, reduced) {
  return mode === "off" ? 0 : mode === "reduced" ? (reduced || 0) : normal
}
function enter(mode) { return duration(mode, 200, 120) }
function exit(mode) { return duration(mode, 140, 100) }
function move(mode) { return duration(mode, 200, 0) }


// Full-motion profiles; Reduced/Off override these through duration()/full().
function fanProfile(style) {
  if (style === "glide") return {name:style,open:260,close:220,stagger:0,limit:0,easing:"cubic",overshoot:0}
  if (style === "cascade") return {name:style,open:340,close:260,stagger:48,limit:192,easing:"quint",overshoot:0}
  if (style === "spring") return {name:style,open:460,close:340,stagger:18,limit:90,easing:"back",overshoot:1.5}
  if (style === "swing") return {name:style,open:390,close:310,stagger:22,limit:110,easing:"cubic",overshoot:0}
  return {name:"arc",open:330,close:280,stagger:14,limit:72,easing:"back",overshoot:.45}
}
function fanDelay(profile, ordinal, opening, capacity) {
  var index=Math.max(0,ordinal)
  if (profile.name === "cascade" && !opening) index=Math.max(0,capacity-1-index)
  return Math.min(profile.limit,index*profile.stagger)
}
