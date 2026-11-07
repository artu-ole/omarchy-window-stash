pragma ComponentBehavior: Bound
import QtQuick
import "Model.js" as Model

Item {
  id: placement
  required property var dock
  required property var area
  required property var monitor
  required property string monitorKey
  required property string side
  required property var savedPositions
  required property real gap
  required property real longMargin
  property string layoutKey:""
  readonly property string layoutStamp:JSON.stringify([layoutKey,dock.width,dock.height])
  readonly property string positionKey:"dock:static:"+side
  readonly property bool vertical:side==="left" || side==="right"
  readonly property real position:drafts[positionKey]===undefined
    ? Model.staticDockSavedPosition(savedPositions[positionKey]) : drafts[positionKey]
  readonly property var startRect:Model.staticDockRect(area,side,dock.width,dock.height,gap,longMargin,0)
  readonly property var endRect:Model.staticDockRect(area,side,dock.width,dock.height,gap,longMargin,1)
  readonly property bool movable:enabled && Math.abs(vertical ? endRect.y-startRect.y : endRect.x-startRect.x)>0.5
  property var drafts:({})
  property bool held:false
  property bool dragging:false
  property bool changed:false
  property bool ready:false
  property string heldKey:""
  property var heldMonitor:null
  signal started()
  signal canceled()
  signal committed(var monitor,string key,int position)

  function press() {
    if (!movable || held) return
    heldKey=positionKey; heldMonitor=monitor
    dragging=false; changed=false; held=true
    started()
  }
  function move(dx,dy) {
    if (!held || !enabled || !movable) return
    dragging=true
    var coordinate=(vertical ? dock.y+dy : dock.x+dx)
    var next=Model.staticDockPosition(area,side,dock.width,dock.height,gap,longMargin,coordinate,position)
    next=Math.round(next*10000)/10000
    if (next===position) return
    var updated=Object.assign({},drafts)
    updated[heldKey]=next; drafts=updated; changed=true
  }
  function release() {
    if (!held) return
    var key=heldKey, owner=heldMonitor, moved=changed, point=drafts[key]
    held=false; dragging=false; changed=false; heldKey=""; heldMonitor=null
    if (moved && point!==undefined) committed(owner,key,Math.round(point*10000))
    reconcileSavedPositions()
  }
  function cancel() {
    if (!held) return
    release()
    canceled()
  }
  onEnabledChanged:if (ready && !enabled) cancel()
  onMovableChanged:if (ready && !movable) cancel()
  onLayoutStampChanged:if (ready) cancel()
  onMonitorKeyChanged:if (ready) { cancel();drafts=({}) }
  function reconcileSavedPositions() {
    var next=Object.assign({},drafts)
    Object.keys(next).forEach(function(key) {
      if (placement.held && key===placement.heldKey) return
      var saved=placement.savedPositions[key]
      if (Array.isArray(saved) && saved.length===2 && saved[0]===Math.round(next[key]*10000) && saved[1]===0) delete next[key]
    })
    if (JSON.stringify(next)!==JSON.stringify(drafts)) drafts=next
  }
  onSavedPositionsChanged:reconcileSavedPositions()
  Component.onCompleted:ready=true
  Component.onDestruction:release()
}
