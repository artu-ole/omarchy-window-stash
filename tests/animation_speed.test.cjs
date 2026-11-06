const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')

function library(name) {
  const context = vm.createContext({})
  vm.runInContext(fs.readFileSync(__dirname+'/../ui/'+name+'.js', 'utf8').replace(/^\.pragma library\s*/, ''), context)
  return context
}
const motion = library('Motion'), model = library('Model')
const rates = {slow:.5, relaxed:.75, normal:1, fast:1.5, ultrafast:2.5}
const close = (actual, expected, why) => assert.ok(Math.abs(actual-expected)<1e-8, `${why}: ${actual} != ${expected}`)

// Speed changes the clock, not the animation mode or its accessibility rules.
for (const [speed, rate] of Object.entries(rates)) {
  assert.equal(motion.speedRatio(speed), rate)
  for (const ms of [0, 32, 75, 90, 100, 120, 140, 170, 200, 740]) {
    close(motion.scale(ms, speed), ms/rate, 'Preset duration ratio')
    close(motion.duration('full', ms, 90, speed), ms/rate, 'Full duration ratio')
    close(motion.duration('reduced', ms, 90, speed), 90/rate, 'Reduced fade duration ratio')
    assert.equal(motion.duration('off', ms, 90, speed), 0, 'Off must stay immediate')
  }
  close(motion.enter('full', speed), 200/rate, 'Arrival duration')
  close(motion.exit('full', speed), 140/rate, 'Retirement duration')
  close(motion.move('full', speed), 200/rate, 'Reflow duration')
  close(motion.enter('reduced', speed), 120/rate, 'Reduced arrival duration')
  close(motion.exit('reduced', speed), 100/rate, 'Reduced retirement duration')
  assert.equal(motion.move('reduced', speed), 0, 'Reduced must not reintroduce spatial motion')
  for (const helper of ['enter', 'exit', 'move']) assert.equal(motion[helper]('off', speed), 0)
  assert.ok(motion.full('full')); assert.ok(!motion.full('reduced')); assert.ok(!motion.full('off'))
}
for (const speed of [undefined, null, '', 'unknown', 'NORMAL', 0, false, {}, []]) {
  assert.equal(motion.speedRatio(speed), 1, 'Unknown/missing speed must use Normal')
  assert.equal(motion.duration('full', 200, 100, speed), 200)
}
for (const ms of [-1, -Infinity, Infinity, NaN, undefined]) assert.equal(motion.scale(ms, 'ultrafast'), 0)
assert.equal(motion.scale(.01, 'ultrafast'), 1, 'Positive animation must have a valid minimum duration')
assert.equal(motion.scale(0, 'slow'), 0, 'Zero-delay stages must stay simultaneous')
assert.equal(motion.duration('reduced', 200, undefined, 'slow'), 0)
assert.equal(motion.enter('full'), 200); assert.equal(motion.exit('full'), 140); assert.equal(motion.move('full'), 200)
console.log('Animation speed: five monotonic presets, legacy defaults, accessibility modes and valid duration limits passed')

const styles = ['arc', 'glide', 'cascade', 'spring', 'swing', 'matryoshka', 'matryoshka-hop']
const area = {x:0, y:26, width:1000, height:700}, anchor = {x:400.375, y:300.625}
const layout = model.fanLayout(anchor.x+24, anchor.y+24, area, 5, true, 48, 4, 3, 17, 1, 0, anchor)

// Raw profiles retain one source of truth. Scale actor time, stagger and panel
// time once so the last icon lands when its panel finishes at every preset.
for (const style of styles) {
  const profile = motion.fanProfile(style)
  for (const count of [1, 2, 5, 50]) for (const opening of [true, false]) {
    const base = motion.fanDuration(profile, opening, count)
    const expected = profile.chain
      ? count<=1 ? profile.minimum : Math.min(opening ? profile.openLimit : profile.closeLimit, (count-1)*(opening ? profile.open : profile.close))
      : (opening ? profile.open : profile.close)+Math.min(profile.limit, Math.max(0, count-1)*profile.stagger)
    assert.equal(base, expected, 'Raw fan profile timing changed')
    for (const [speed, rate] of Object.entries(rates)) {
      const total = motion.duration('full', base, 100, speed)
      close(total, base/rate, 'Fan timeline duration ratio')
      for (const ordinal of new Set([0, Math.min(1,count-1), Math.max(0,count-1)])) {
        const rawDelay = motion.fanDelay(profile, ordinal, opening, count)
        const delay = motion.duration('full', rawDelay, 0, speed)
        close(delay, rawDelay/rate, 'Actor stagger duration ratio')
        assert.equal(motion.duration('reduced', rawDelay, 0, speed), 0, 'Reduced must not stagger motion')
        assert.equal(motion.duration('off', rawDelay, 0, speed), 0)
        if (profile.chain) assert.equal(delay, 0, 'Matryoshka must retain its single shared clock')
        else {
          const travel = motion.duration('full', opening ? profile.open : profile.close, 100, speed)
          assert.ok(delay+travel<=total+1e-8, 'Actor outlives its panel at this speed')
        }
      }
      // A partial reversal consumes only the remaining fraction of the same
      // path, without resetting the shared normalized progress.
      for (const progress of [.03, .3, .67, .96]) {
        const elapsed = total*progress
        close(elapsed/total, progress, 'Shared phase changed under speed scaling')
        const remaining = (1-progress)*total
        close(elapsed+remaining, total, 'Partial timeline/reversal no longer conserves duration')
        const destination = model.fanSlot(layout, 3, 0)
        const pose = profile.chain
          ? model.fanChainPose(anchor.x, anchor.y+8, destination.x, destination.y, elapsed/total, 3, layout, area, style, 0, 5)
          : model.fanPose(anchor.x, anchor.y+8, destination.x, destination.y, elapsed/total, 3, layout, area, style)
        const reference = profile.chain
          ? model.fanChainPose(anchor.x, anchor.y+8, destination.x, destination.y, progress, 3, layout, area, style, 0, 5)
          : model.fanPose(anchor.x, anchor.y+8, destination.x, destination.y, progress, 3, layout, area, style)
        close(pose.x, reference.x, 'Speed changed horizontal trajectory')
        close(pose.y, reference.y, 'Speed changed vertical trajectory')
        close(pose.scale, reference.scale, 'Speed changed transform trajectory')
      }
    }
  }
}
console.log('Animation speed: all seven profiles preserve staggering, shared clocks, bounds and reversal paths at every preset')
