const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const path = require('node:path')
const root = path.resolve(__dirname, '..')
const source = fs.readFileSync(path.join(root, 'ui/StashContextMenu.qml'), 'utf8')
const contains = source.match(/function containsPoint\(px,py\) \{([\s\S]*?)\n  \}/)
const clicked = source.match(/function onPointerClicked\(px,py,button\) \{([\s\S]*?)\n    \}/)
assert.ok(contains && clicked, 'The actual context-menu input functions must be exercised')
function fixture() {
  let closes = 0
  const menu = {opened: true, openingRightClickPending: true, x: 44, y: 84, width: 350, height: 225, radius: 12,
    host: {monitor: {x: 1000, y: 200}}, stash: {contextPoint: {x: 44, y: 84}, closeContext() { closes++; menu.opened=false }}}
  const context = vm.createContext({menu,x:menu.x,y:menu.y,width:menu.width,height:menu.height,radius:menu.radius})
  menu.containsPoint = vm.runInContext('(function(px,py) {'+contains[1]+'})', context).bind(menu)
  const click = vm.runInContext('(function(px,py,button) {'+clicked[1]+'})', context)
  return {menu, click: (x,y,button) => click(x+1000,y+200,button), closes: () => closes}
}
let f = fixture()
assert.equal(f.menu.containsPoint(44,84), false, 'The opening point is deliberately in a transparent rounded corner')
f.click(44,84,273)
assert.equal(f.closes(),0)
assert.equal(f.menu.openingRightClickPending,false)
f.click(44,84,273)
assert.equal(f.closes(),1,'A second right press at the anchor must dismiss normally')
for (const [x,y,button] of [[44,84,272],[44,84,274],[40,84,273],[44,80,273],[47,84,273]]) {
  f=fixture(); f.click(x,y,button)
  assert.equal(f.closes(),1,'Only the opening right press within two pixels may be exempted')
}
f=fixture(); f.click(45.5,85.5,273); assert.equal(f.closes(),0)
f=fixture(); f.click(100,120,272); assert.equal(f.closes(),0)
f.click(44,84,273); assert.equal(f.closes(),1,'An earlier observed inside click consumes the opening exemption')
f=fixture(); f.menu.opened=false; f.click(0,0,272); assert.equal(f.closes(),0)
console.log('Context clicks: exact opening right-press exemption, rounded corners, monitor offsets and immediate outside dismissal passed')

const observer = fs.readFileSync(path.join(root, 'ui/StashClickObserver.qml'), 'utf8')
const scriptBody = observer.match(/function script\(enabled,reset,tracking\) \{([\s\S]*?)\n  \}/)
assert.ok(scriptBody)
const context = vm.createContext({owner:'test-owner'})
const makeScript = vm.runInContext('(function(enabled,reset,tracking) {'+scriptBody[1]+'})', context)

const service = fs.readFileSync(path.join(root,'Service.qml'),'utf8')
const surfaceSource = fs.readFileSync(path.join(root,'ui/StashSurface.qml'),'utf8')
const pressBody = service.match(/onClicked:function\(x,y,button\) \{([\s\S]*?)\n    \}/)
const releaseBody = service.match(/onReleased:function\(x,y,button\) \{([\s\S]*?)\n    \}/)
const holdBody = surfaceSource.match(/function beginPointerFocusHold\(\) \{([^\n]*)\}/)
const clearBody = surfaceSource.match(/function onPointerButtonHeldChanged\(\) \{([^\n]*)\}/)
const focusExpression = surfaceSource.match(/WlrLayershell.keyboardFocus:([\s\S]*?)\n  visible:/)
const resetBody = service.match(/function resetPointerHold\(\) \{([^\n]*)\}/)
const recoveryShortcut = surfaceSource.match(/Shortcut \{([\s\S]*?)\n    \}/)
const recoveryEnabled = recoveryShortcut && recoveryShortcut[1].match(/enabled:([^\n]*)/)
const recoveryAction = recoveryShortcut && recoveryShortcut[1].match(/onActivated:([^\n]*)/)
assert.ok(pressBody && releaseBody && holdBody && clearBody && focusExpression && resetBody && recoveryEnabled && recoveryAction)
assert.match(recoveryShortcut[1],/context:Qt.WindowShortcut/)
let resets=0,presses=0
const state={surfaces:[],_pressed:{},get pointerButtonHeld(){return Object.keys(this._pressed).length>0}}
const focusModes={None:0,OnDemand:1,Exclusive:2}
for (const initiallyOpen of [true,false]) {
  const surface={stash:state,keyboardOpen:initiallyOpen,pointerFocusHeld:false,focusPrimed:true,
    get retainingPointerFocus(){return this.pointerFocusHeld && state.pointerButtonHeld}}
  const scope=vm.createContext({surface,WlrKeyboardFocus:focusModes})
  for (const key of ['keyboardOpen','pointerFocusHeld','focusPrimed','retainingPointerFocus'])
    Object.defineProperty(scope,key,{get:()=>surface[key],set:value=>{surface[key]=value}})
  surface.beginPointerFocusHold=vm.runInContext('(function(){'+holdBody[1]+'})',scope)
  surface.notifyHeld=vm.runInContext('(function(){'+clearBody[1]+'})',scope)
  surface.keyboardFocus=vm.runInContext('(function(){return ('+focusExpression[1]+')})',scope)
  surface.recoveryEnabled=vm.runInContext('(function(){return ('+recoveryEnabled[1]+')})',scope)
  surface.recover=vm.runInContext('(function(){'+recoveryAction[1]+'})',scope)
  state.surfaces.push(surface)
}
Object.defineProperty(state,'pressedPointerButtons',{get(){return this._pressed},set(value){
  const previous=this.pointerButtonHeld; this._pressed=value
  if(previous!==this.pointerButtonHeld) this.surfaces.forEach(surface=>surface.notifyHeld())
}})
state.pointerClicked=()=>{
  presses++
  assert.equal(state.pointerButtonHeld,true,'Held state must exist before popup dismissal sees the press')
  assert.equal(state.surfaces[0].pointerFocusHeld,true)
  assert.equal(state.surfaces[1].pointerFocusHeld,false,'A surface which owned no keyboard focus must not acquire it')
  state.surfaces.forEach(surface=>{surface.keyboardOpen=false})
}
const scope=vm.createContext({root:state,clickObserver:{resetHeld(){resets++}}})
state.resetPointerHold=vm.runInContext('(function(){'+resetBody[1]+'})',scope)
const press=vm.runInContext('(function(x,y,button){'+pressBody[1]+'})',scope)
const release=vm.runInContext('(function(x,y,button){'+releaseBody[1]+'})',scope)
assert.equal(state.surfaces[0].recoveryEnabled(),false,'Visible menus keep ordinary Escape navigation')
press(10,20,272)
assert.equal(state.surfaces[0].recoveryEnabled(),true)
assert.equal(state.surfaces[1].recoveryEnabled(),false)
assert.equal(state.surfaces[0].keyboardFocus(),focusModes.OnDemand)
assert.equal(state.surfaces[1].keyboardFocus(),focusModes.None)
press(10,20,273)
release(10,20,272)
assert.equal(state.surfaces[0].keyboardFocus(),focusModes.OnDemand,'Another held button must keep the original focus alive')
assert.equal(resets,0)
release(10,20,273)
assert.equal(state.surfaces[0].keyboardFocus(),focusModes.None)
assert.equal(state.surfaces[0].pointerFocusHeld,false)
assert.equal(presses,2,'Release events must not re-run press consumers')
assert.equal(resets,0)
assert.equal(state.surfaces[0].recoveryEnabled(),false)
state.surfaces[0].keyboardOpen=true
press(10,20,272)
assert.equal(state.surfaces[0].recoveryEnabled(),true)
state.surfaces[0].recover()
assert.equal(state.pointerButtonHeld,false)
assert.equal(state.surfaces[0].keyboardFocus(),focusModes.None)
assert.equal(resets,1,'Explicit Escape recovery must reset native held state too')
assert.equal(state.surfaces[0].recoveryEnabled(),false)
console.log('Pointer holds: press-before-dismiss ordering, prior focus only, multi-button release and explicit WindowShortcut Escape recovery passed')

const canResetBody = surfaceSource.match(/function canResetPreviewProportions\(group\) \{([\s\S]*?)\n  \}/)
const resetProportionsBody = service.match(/function resetPreviewProportionsContext\(\) \{([\s\S]*?)\n  \}/)
const resetActionIds = source.match(/readonly property var actionIds:([\s\S]*?)\n  property int currentIndex/)
assert.ok(canResetBody && resetProportionsBody && resetActionIds)
const geometryConfig={presentation:'previews',floatingPreviewSizing:'free',floatingPreviewLock:'unlocked'}
const cover={visible:true,retiring:false,aspectOverride:2,displayRecord:{id:'first'},canResize:false}
const group={key:'app:browser',windows:[{id:'first'},{id:'second'}]}
const geometryScope=vm.createContext({config:geometryConfig,floatingPreviews:{cardForKey:key=>key==='preview:app:browser' ? cover : null}})
const canReset=vm.runInContext('(function(group){'+canResetBody[1]+'})',geometryScope)
assert.equal(canReset(group),true,'Opening the menu blocks gestures without hiding the reset action')
cover.aspectOverride=0;assert.equal(canReset(group),false,'Natural triples have no reset action');cover.aspectOverride=2
geometryConfig.floatingPreviewLock='locked';assert.equal(canReset(group),false);geometryConfig.floatingPreviewLock='unlocked'
geometryConfig.floatingPreviewSizing='preset';assert.equal(canReset(group),false);geometryConfig.floatingPreviewSizing='free'
cover.displayRecord={id:'second'};assert.equal(canReset(group),false,'A stale cover lead cannot reset another source');cover.displayRecord={id:'first'}
assert.equal(canReset({key:'window:first',windows:[{id:'first'}]}),false,'An expanded tile cannot reset its grouped cover')
const ids=vm.runInNewContext(resetActionIds[1],{interactionAvailable:true,proportionsResetAvailable:true,unfoldAvailable:false})
assert.ok(ids.indexOf('reset-preview-proportions')>=0 && ids.indexOf('reset-preview-proportions')<ids.indexOf('close'))
const foldedIds=vm.runInNewContext(resetActionIds[1],{interactionAvailable:false,proportionsResetAvailable:false,unfoldAvailable:true})
assert.equal(foldedIds[0],'unfold-preview','A folded icon offers its preview before full restoration')
assert.ok(foldedIds.includes('here') && foldedIds.includes('original') && !foldedIds.includes('interact'),'Explicit full restores remain available; folded sources cannot interact')
let menuClosed=false,proportionsReset=0
const deferred=[]
const resetSurface={screen:{name:'test'},canResetPreviewProportions:canReset,resetPreviewProportions(id){
  assert.equal(menuClosed,true,'The context menu must release its gesture block before reset')
  assert.equal(id,'first');proportionsReset++
}}
const resetScope=vm.createContext({contextGroup:group,contextScreen:'test',surfaces:[resetSurface],
  closeContext(){menuClosed=true},Qt:{callLater:callback=>deferred.push(callback)}})
vm.runInContext('(function(){'+resetProportionsBody[1]+'})',resetScope)()
assert.equal(menuClosed,true);assert.equal(proportionsReset,0)
deferred[0]();assert.equal(proportionsReset,1)
console.log('Preview proportions context: exact custom cover, unlocked/free sizing, grouped lead identity and close-before-reset routing passed')
const cleanupArray = observer.match(/Component.onDestruction:Quickshell.execDetached\((\[[\s\S]*?\])\)/)
assert.ok(cleanupArray)
const cleanup = vm.runInContext(cleanupArray[1],context)[2]
if (process.argv.includes('--observer-scripts')) console.log(JSON.stringify({enabled:makeScript(true),disabled:makeScript(false),reset:makeScript(false,true),tracking:makeScript(false,false,true),stopTracking:makeScript(false,false,false),resetTracking:makeScript(false,true,true),cleanup}))
