const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

// Run the production event route. Socket events express intent; only a known
// stashed record may enter the ordinary identity-checked restoration path.
const source = fs.readFileSync('Service.qml', 'utf8');
const begin = source.indexOf('  function restoreNativePreviewWindow(');
const end = source.indexOf('  function restorePreviewWindow(', begin);
assert(begin >= 0 && end > begin);
const id = 'a'.repeat(32);
const other = 'b'.repeat(32);
let calls;
const model = vm.createContext({});
vm.runInContext(source.slice(begin, end), model);
for (const [name, boundary] of [['focusedScreen', '  Timer {'], ['screenMonitor', '  function invocationWorkspace(']]) {
  const start = source.indexOf('  function ' + name + '(');
  const finish = source.indexOf(boundary, start);
  assert(start >= 0 && finish > start);
  vm.runInContext(source.slice(start, finish), model);
}
function reset() {
  calls = [];
  Object.assign(model, {
    lifecycleReady: true, stopping: false, pendingCloseIds: {},
    snapshot: {windows: [{id, phase: 'stashed'}], monitors: [{name: 'HEADLESS-1', focused: true}]}, queue: [],
    worker: {running: false}, runningArgs: [],
    restorePreviewWindow: (...args) => calls.push(args)
  });
}

reset();
assert.equal(model.restoreNativePreviewWindow(id), true);
assert.deepEqual(calls, [[id, 'HEADLESS-1']]);
for (const invalid of [null, 0, {}, '', id.toUpperCase(), id + '\n', id + ',restore-all', '<img src="https://example.invalid">', other]) {
  reset();
  assert.equal(model.restoreNativePreviewWindow(invalid), false);
  assert.equal(calls.length, 0);
}
for (const patch of [
  {lifecycleReady: false}, {stopping: true}, {pendingCloseIds: {[id]: true}},
  {snapshot: {windows: []}}, {snapshot: {windows: [{id, phase: 'restoring'}]}},
  {snapshot: {windows: [{id, phase: 'stashed'}], monitors: []}},
  {worker: {running: true}, runningArgs: ['restore', id, '--monitor', 'HEADLESS-1']},
  {queue: [['restore', id]]}
]) {
  reset();
  Object.assign(model, patch);
  assert.equal(model.restoreNativePreviewWindow(id), false);
  assert.equal(calls.length, 0);
}
reset();
model.queue = [['restore', other], ['position', 'HEADLESS-1', 'other', 10, 20]];
assert.equal(model.restoreNativePreviewWindow(id), true);
assert.deepEqual(calls, [[id, 'HEADLESS-1']]);
console.log('Preview activation: bounded owned-record intent, current monitor, duplicate/closing/stale rejection and normal restore routing passed');
