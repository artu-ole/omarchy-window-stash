const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const capture = vm.createContext({})
vm.runInContext(fs.readFileSync(__dirname+'/../ui/PreviewCapture.js','utf8').replace(/^\.pragma library\s*/,''),capture)
const record={id:'owned',tag:'window-stash-owned',address:'0x000ab12',pid:42,stableId:'1800010a',phase:'stashed',app:'test'}
const client={address:'ab12',pid:42,stableId:'0x1800010A',mapped:true,workspace:{name:'special:window-stash'},tags:['other','window-stash-owned']}
const copy=value=>JSON.parse(JSON.stringify(value))

assert.equal(capture.matches(record,client),true)
assert.equal(capture.findClient(record,[{...client,address:'cafe'},client]),client)
assert.equal(capture.stableId(0x1800010a),'1800010a')
assert.equal(capture.address('0X000AB12'),'ab12')
for(const value of [null,undefined,'','0','0x0','xyz','0xabc;cat',' 0xabc',123]) assert.equal(capture.address(value),'')
for(const value of [null,undefined,'xyz',-1,NaN,Number.MAX_SAFE_INTEGER+1]) assert.equal(capture.stableId(value),'')

// Qt exposes a native QVariantList as an array-like V4Sequence. Its elements
// remain exact ownership tags even though Array.isArray(sequence) is false.
const nativeTags={0:'other',1:record.tag,length:2}
assert.equal(Array.isArray(nativeTags),false)
assert.equal(capture.matches(record,{...client,tags:nativeTags}),true)
for(const tags of [record.tag,'prefix-'+record.tag,{0:record.tag,length:'1'},
  {0:record.tag+'-suffix',length:1},{0:record.tag,length:-1},{0:record.tag,length:5000}])
  assert.equal(capture.matches(record,{...client,tags}),false)

for(const patch of [
  {address:'0xcafe'},{pid:43},{stableId:'1800010b'},{mapped:false},
  {workspace:{name:'1'}},{workspace:{name:'special:minimized'}},{workspace:null},{tags:[]},{tags:['window-stash-other']},{tags:null},
]) assert.equal(capture.matches(record,{...client,...patch}),false,JSON.stringify(patch))
for(const patch of [
  {id:''},{tag:'window-stash-other'},{address:''},{pid:0},{pid:'42'},
  {stableId:'not-a-window'},{phase:'restoring'},{phase:'stashing'},
]) assert.equal(capture.matches({...record,...patch},client),false,JSON.stringify(patch))

// Reusing the same address, PID, title and app must not reveal a replacement.
const reused={...client,title:'same',class:'test',stableId:'1800010b'}
assert.equal(capture.findClient(record,[reused]),null)
assert.equal(capture.findClient(record,[client,client]),null)
assert.equal(capture.findClient(record,{clients:[client]}),null)
assert.equal(capture.findClient(null,[client]),null)
assert.equal(capture.findClient(record,[null]),null)

// Legacy ledger entries can still prove ownership through a unique stash tag.
assert.equal(capture.matches({...record,stableId:null},client),true)
assert.equal(capture.matches({...record,stableId:null},{...client,tags:[]}),false)

// Metadata refreshes do not restart capture; an identity or phase change does.
const originalKey=capture.key(record)
assert.equal(capture.key({...record,title:'new title',app:'new app'}),originalKey)
for(const patch of [{id:'new',tag:'window-stash-new'},{pid:43},{stableId:'1800010b'},{phase:'restoring'}])
  assert.notEqual(capture.key({...record,...patch}),originalKey)
assert.equal(capture.key({...record,address:'AB12',stableId:0x1800010a}),originalKey)
assert.equal(capture.key(null),'')
assert.equal(capture.validRecord(copy(record)),true)
console.log('Preview capture: ownership, stable identity, address reuse, stale phase, exact source matching and metadata-only refresh passed')
