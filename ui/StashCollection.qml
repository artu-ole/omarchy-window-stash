import QtQuick
import "Model.js" as Model
import "Motion.js" as Motion

// Keys survive ordinary refreshes. Removed entries stay only for their exit,
// can be revived in place, and lose input as soon as they start retiring.
ListModel {
  id: collection
  signal reconciled()
  property var sourceGroups: []
  property string animations: "full"
  property string animationSpeed:"normal"
  property bool hold: false
  readonly property var activeKeys:sourceGroups.map(function(g) { return g.key })
  property var keys: []
  property var entries: []
  property var dataByKey: ({})
  property var retireAt: ({})
  property real settleUntil: 0
  property bool busy: false
  property Timer clock: Timer {
    interval:16; repeat:true; running:collection.busy
    onTriggered:collection.prune()
  }
  function publish() {
    var next=[]
    for (var i=0;i<count;i++) next.push(get(i).groupKey)
    if (JSON.stringify(next)!==JSON.stringify(keys)) keys=next
    entries=next.map(function(key) { return dataByKey[key] })
  }
  function reconcile() {
    if (hold) return
    var wanted=sourceGroups.map(function(g) { return g.key })
    var order=Model.reconcileKeys(keys,wanted), cache=Object.assign({},dataByKey)
    var expires=Object.assign({},retireAt), now=Date.now(), changed=false
    sourceGroups.forEach(function(g) { cache[g.key]=g; delete expires[g.key] })
    dataByKey=cache
    for (var i=0;i<order.length;i++) {
      var at=-1
      for (var j=i;j<count;j++) if (get(j).groupKey===order[i]) { at=j; break }
      if (at<0) { insert(i,{groupKey:order[i],retiring:false}); changed=true }
      else if (at!==i) { move(at,i,1); changed=true }
      var retiring=wanted.indexOf(order[i])<0
      if (get(i).retiring!==retiring) { setProperty(i,"retiring",retiring); changed=true }
      if (retiring && expires[order[i]]===undefined) expires[order[i]]=now+Motion.exit(animations,collection.animationSpeed)+(animations==="off" ? 0 : 32)
    }
    retireAt=expires
    if (changed) settleUntil=now+Math.max(Motion.enter(animations,collection.animationSpeed),Motion.move(animations,collection.animationSpeed),Motion.exit(animations,collection.animationSpeed))
    publish()
    prune()
    reconciled()
  }
  function prune() {
    var now=Date.now(), expires=Object.assign({},retireAt), cache=Object.assign({},dataByKey), removed=false
    for (var i=count-1;i>=0;i--) {
      var row=get(i), key=row.groupKey
      if (row.retiring && (animations==="off" || expires[key]<=now)) {
        remove(i); delete expires[key]; delete cache[key]; removed=true
      }
    }
    if (removed) {
      dataByKey=cache; retireAt=expires; publish(); reconciled()
      settleUntil=Math.max(settleUntil,now+Motion.move(animations,collection.animationSpeed))
    }
    busy=animations!=="off" && (Object.keys(expires).length>0 || now<settleUntil)
  }
  onSourceGroupsChanged:reconcile()
  onHoldChanged:if (!hold) reconcile()
  onAnimationsChanged: { if (animations==="off") settleUntil=0; reconcile() }
  onAnimationSpeedChanged: {
    // Running QML transitions can retain their original timing. Keep both
    // their old deadline and enough room for a newly selected slower fade.
    var now=Date.now(),expires=Object.assign({},retireAt)
    Object.keys(expires).forEach(function(key) { expires[key]=Math.max(expires[key],now+Motion.exit(animations,collection.animationSpeed)+32) })
    retireAt=expires
    if (busy) settleUntil=Math.max(settleUntil,now+Math.max(Motion.enter(animations,collection.animationSpeed),Motion.move(animations,collection.animationSpeed),Motion.exit(animations,collection.animationSpeed)))
    prune()
  }
  Component.onCompleted:reconcile()
}
