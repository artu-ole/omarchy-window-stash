const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('Service.qml', 'utf8');
const functions = ['enqueue', 'pump', 'previewGeometryCommand', 'previewFoldIds', 'foldPreviewWindows',
  'unfoldPreviewWindows', 'minimizeAt', 'restoreStage', 'previewFoldResult', 'finishWorker', 'recordPosition'];
function body(name) {
  const start = source.indexOf('  function '+name+'(');
  const end = source.indexOf('\n  }', start);
  assert.ok(start >= 0 && end > start, 'Production method missing: '+name);
  return source.slice(start, end+4);
}
const plain = value => JSON.parse(JSON.stringify(value));
const first = {id:'first', phase:'stashed', size:[1000,700], order:3, origin:{id:5}, previewResized:true};
const second = {id:'second', phase:'stashed', size:[800,600], order:2, origin:{id:5}};

function fixture() {
  const calls = [], deferred = [];
  const state = {
    stopping:false, lifecycleReady:true, bridgeReloadBusy:false, contextOpen:false, dialogKind:'',
    previewInteractionRequest:null, previewInteractionStopping:false,
    pendingCloseIds:{}, pendingPreviewFoldIds:{}, previewGeometryStates:{}, previewGeometryDrafts:{},
    snapshot:{settings:{presentation:'previews'}, windows:plain([first,second]), positions:{screen:{'preview:window:first':[120,180,360,1.8]}}},
    queue:[], runningArgs:[], worker:{running:false}, controllerCommand:['python3','stash.py'],
    pendingRefresh:false, runningGeometryReplied:false, closeNotified:false, resetting:false,
    previewGeometryResult(){throw new Error('Unexpected geometry result')},
    screenMonitor(name){return name==='screen' ? {name} : null},
    closeContext(){calls.push(['closeContext']);state.contextOpen=false},
    closeDialog(){calls.push(['closeDialog']);state.dialogKind=''},
    endPreviewInteraction(reason){calls.push(['end',reason]);state.previewInteractionStopping=true},
    applyDeferredSettings(){},
    Model:{staticDockMonitorKey:monitor=>'static:'+monitor.name, monitorKey:monitor=>'legacy:'+monitor.name},
    Qt:{callLater:callback=>deferred.push(callback)}
  };
  const surface = {screen:{name:'screen'}, target:null,
    foldPreviewAt(x,y){calls.push(['hit',x,y]);return this.target},
    preparePreviewFold(key,origin){calls.push(['origin',key,plain(origin)])}};
  state.surfaces=[surface];state.root=state;
  const context=vm.createContext(state);
  functions.forEach(name=>vm.runInContext(body(name), context));
  return {state:context, surface, calls, deferred};
}

let f=fixture(), s=f.state;
assert.equal(s.minimizeAt(400,500).action,'queued');
assert.deepEqual(plain(s.worker.command),['python3','stash.py','minimize'],'A hover miss must retain focused-window minimization');

for (const flag of ['stopping','bridgeReloadBusy','contextOpen']) {
  f=fixture();s=f.state;s[flag]=true;
  assert.equal(s.minimizeAt(10,20).action,'noop');
  assert.equal(s.worker.running,false,'A blocked UI must not minimize a window behind it');
}
f=fixture();s=f.state;s.lifecycleReady=false;
assert.equal(s.minimizeAt(10,20).action,'noop');
for (const point of [[NaN,10],[10,Infinity]]) {
  f=fixture();assert.equal(f.state.minimizeAt(...point).action,'noop');
}

f=fixture();s=f.state;
f.surface.target={handled:true, ids:[], screenName:'screen'};
assert.equal(s.minimizeAt(40,50).action,'noop');
assert.equal(s.worker.running,false,'The terminal icon stage cannot minimize its underlying window');

f=fixture();s=f.state;
f.surface.target={handled:true, ids:['first','first','absent'], screenName:'screen', key:'folded-preview:window:first', origin:{x:120,y:180,width:360,height:200}};
s.previewInteractionRequest={id:'first'};
s.previewGeometryStates={first:{epoch:1}, second:{epoch:2}};
s.previewGeometryDrafts={first:['preview-aspect','first',2,'--axis','width']};
s.queue=[['preview-geometry','first'],['preview-geometry','second']];
const restoration=JSON.stringify(s.snapshot.windows);
const placements=JSON.stringify(s.snapshot.positions);
assert.equal(s.minimizeAt(250,300).action,'preview-fold-queued');
assert.equal(s.worker.running,false,'Folding ran before the active input owner acknowledged release');
assert.deepEqual(plain(s.queue),[['preview-geometry','second'],['preview-fold','first']]);
assert.equal(s.pendingPreviewFoldIds.first,true,'The queued fold must block new input acquisitions');
assert.equal(s.previewGeometryStates.first,undefined);
assert.equal(s.previewGeometryDrafts.first,undefined,'Stale geometry drafts could renew hidden rendering after folding');
assert.equal(JSON.stringify(s.snapshot.windows),restoration,'Queuing a fold must not mutate authoritative window metadata');
assert.equal(JSON.stringify(s.snapshot.positions),placements,'Folding must preserve the remembered preview shape');
assert.equal(f.calls.filter(call=>call[0]==='end').length,1);
assert.equal(f.calls.find(call=>call[0]==='origin')[1],'folded-preview:window:first');
assert.equal(s.minimizeAt(250,300).action,'noop','Repeated minimize must not enqueue another fold while one is pending');

// Native acknowledgement releases the existing pump gate. Unrelated requests
// retain their order and the fold then runs as an ordinary serialized action.
s.previewInteractionRequest=null;s.previewInteractionStopping=false;
s.pump();assert.equal(s.runningArgs[1],'second');
s.worker.running=false;s.pump();assert.deepEqual(plain(s.runningArgs),['preview-fold','first']);
s.previewFoldResult({ok:true,action:'preview-fold',ids:['first'],previewFolded:true});
assert.equal(s.snapshot.windows[0].previewFolded,true);
assert.deepEqual(plain(s.snapshot.windows[0]),{...first,previewFolded:true});
assert.deepEqual(plain(s.snapshot.windows[1]),second);
assert.equal(JSON.stringify(s.snapshot.positions),placements);
s.worker.running=false;s.finishWorker(0);
assert.equal(s.pendingPreviewFoldIds.first,undefined,'Completed folding retained a permanent input block');
assert.equal(s.pendingRefresh,true);

assert.equal(s.unfoldPreviewWindows([s.snapshot.windows[0]],'screen'),true);
assert.deepEqual(plain(s.runningArgs),['preview-unfold','first']);
s.previewFoldResult({ok:true,action:'preview-unfold',ids:['first'],previewFolded:false});
assert.equal(s.snapshot.windows[0].previewFolded,false);
assert.equal(s.snapshot.windows[0].order,3,'Unfolding must not reorder newest/FIFO selection');
assert.equal(JSON.stringify(s.snapshot.positions),placements);

for (const oldest of [false,true]) {
  f=fixture();s=f.state;s.restoreStage(oldest);
  assert.deepEqual(plain(s.runningArgs),[oldest ? 'restore-oldest' : 'restore-last','--stage']);
  f=fixture();s=f.state;s.snapshot.settings.presentation='dock';s.restoreStage(oldest);
  assert.deepEqual(plain(s.runningArgs),[oldest ? 'restore-oldest' : 'restore-last'],'Other display modes keep full restoration');
}

f=fixture();s=f.state;s.pendingCloseIds={first:true};
assert.equal(s.foldPreviewWindows(['first'],'screen',null,''),false);
assert.equal(s.foldPreviewWindows(['second'],'missing',null,''),false);
s.snapshot.settings.presentation='dock';
assert.equal(s.foldPreviewWindows(['second'],'screen',null,''),false);
assert.equal(s.unfoldPreviewWindows(['first'],'screen'),false);

for (const key of ['folded-preview:window:first','dock:static:bottom','window:first']) {
  f=fixture();s=f.state;s.recordPosition({name:'anonymous'},key,10.4,20.7);
  assert.deepEqual(plain(s.runningArgs),['position',key==='window:first' ? 'legacy:anonymous' : 'static:anonymous',key,'10','21']);
}
console.log('Staged preview actions: fresh hover selection, terminal icons, acknowledged release, stale geometry cleanup, immutable restoration data, newest/FIFO and independent positions passed');
