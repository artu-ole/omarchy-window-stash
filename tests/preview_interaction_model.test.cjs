const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const model = vm.createContext({});
vm.runInContext(fs.readFileSync('ui/PreviewInteraction.js', 'utf8').replace(/^\.pragma.*$/m, ''), model);
const plain = value => JSON.parse(JSON.stringify(value));
const settings = {presentation:'previews', floatingPreviewInteraction:'on', floatingPreviewKeyboard:'mouse', floatingPreviewInteractionFps:'60'};

// Negative monitor origins and fractional logical coordinates remain logical;
// registering an overlay never crops or shifts the actual image transform.
const image = {x:-1450.5,y:63.25,width:280.5,height:180.75};
const original = JSON.stringify(image);
const overlay = {x:-1320,y:65,width:120,height:28};
const excluded = plain(model.exclusions(image, [overlay], {x:-1600,y:80,width:1600,height:700}));
assert.equal(JSON.stringify(image), original);
assert.deepEqual(excluded[0], {x:-1320,y:65,width:120,height:28});
assert.deepEqual(excluded[1], {x:-1450.5,y:63.25,width:280.5,height:16.75});
assert.deepEqual(plain(model.exclusions(image, [], {x:0,y:0,width:100,height:100})), [image]);
assert.deepEqual(plain(model.exclusions(image, [{x:-1500,y:50,width:100,height:30}], null)),
  [{x:-1450.5,y:63.25,width:50.5,height:16.75}]);

const request = plain(model.request(7, 'exact-window', 'DP-2', 'preview:window:1', image, excluded, settings));
assert.equal(request.fps, 60);
assert.equal(request.keyboard, false);
assert.deepEqual(request.rect, image);
assert(model.matches(request, 'exact-window', 'DP-2', 'preview:window:1'));
assert(!model.matches(request, 'exact-window', 'DP-1', 'preview:window:1'));
assert(!model.matches(request, 'exact-window', 'DP-2', 'preview:window:2'));
assert.deepEqual(Object.keys(plain(model.wire(request))).sort(), ['excludeRects','fps','id','keyboard','monitor','rect','serial']);

for (const invalid of [{...image,width:0}, {...image,height:-1}, {...image,x:NaN}, {...image,y:Infinity}]) {
  assert.equal(model.request(8, 'exact-window', 'DP-2', 'card', invalid, [], settings), null);
}
for (const serial of [0,-1,1.5,'1',2147483648]) assert.equal(model.request(serial,'window','DP-2','card',image,[],settings),null);
assert.equal(model.request(1,'window','DP-2','card',image,[],{...settings,floatingPreviewInteraction:'off'}),null);
assert.equal(model.request(1,'window','DP-2','card',image,[],{...settings,presentation:'dock'}),null);
const keyboard = plain(model.request(8,'window','DP-2','card',image,[],{...settings,floatingPreviewKeyboard:'click',floatingPreviewInteractionFps:'30'}));
assert.equal(keyboard.keyboard,true);assert.equal(keyboard.fps,30);
assert.equal(plain(model.request(9,'window','DP-2','card',image,Array(25).fill(image),settings)).excludeRects.length,16);
for(const imageRect of [{x:200,y:200,width:280,height:180},{x:0,y:0,width:280,height:180},
  {x:0,y:600,width:280,height:200},{x:0,y:26,width:280,height:774}]) {
  const bounds={x:0,y:26,width:1280,height:774};
  const controls=plain(model.controlsPlacement(imageRect,bounds,76,28));
  assert(controls && !model.intersection(imageRect,controls));
  assert(controls.x>=bounds.x && controls.y>=bounds.y && controls.x+controls.width<=bounds.x+bounds.width && controls.y+controls.height<=bounds.y+bounds.height);
}
assert.equal(model.controlsPlacement({x:0,y:26,width:1280,height:774},{x:0,y:26,width:1280,height:774},76,28),null);
console.log('Preview interaction: exact global logical image mapping, clipped controls, owner selection, bounded requests and optional activation passed');
