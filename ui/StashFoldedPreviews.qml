pragma ComponentBehavior: Bound
import QtQuick
import Quickshell
import qs.Commons
import "Model.js" as Model
import "FloatingPreviewModel.js" as Geometry
import "Motion.js" as Motion

// A second visual stage of the same ledger records. Icons own no capture or
// input lease, and their positions never overwrite the remembered preview tuple.
Item {
  id:folded
  required property var stash
  required property var config
  required property var groups
  required property var savedPositions
  required property var area
  required property var monitor
  required property Item coordinateRoot
  required property string screenName
  property var origins:({})
  property var recordIds:[]
  property bool active:false
  property bool blocked:false
  property var drafts:({})
  property var lastRects:({})
  property var inputRegions:[]
  readonly property string animations:config.animations || "full"
  readonly property string animationSpeed:config.animationSpeed || "normal"
  readonly property real iconSize:Model.iconSize(config.sizePreset,true,area)
  readonly property bool sizingReady:iconSize>0 && width>0 && height>0 && area.width>0 && area.height>0
    && width>=area.x+area.width-.5 && height>=area.y+area.height-.5
  readonly property bool present:collection.count>0
  readonly property bool held:iconList().some(function(icon) {return icon.positionHeld})
  signal inputChanged()
  width:coordinateRoot.width;height:coordinateRoot.height
  visible:active && present && sizingReady
  z:60
  function iconList() {var result=[];for(var i=0;i<icons.count;i++) {var icon=icons.itemAt(i);if(icon) result.push(icon)}return result}
  function iconForKey(key) {return iconList().find(function(icon) {return icon.groupKey===key}) || null}
  function remember(icon) {
    if(!icon || !icon.group) return
    var next=Object.assign({},lastRects),rect={x:icon.x,y:icon.y,width:icon.width,height:icon.height}
    icon.group.windows.forEach(function(record) {next[record.id]=rect})
    if(JSON.stringify(next)!==JSON.stringify(lastRects)) lastRects=next
  }
  function originFor(records) {
    for(var i=0;i<records.length;i++) if(lastRects[records[i].id]) return lastRects[records[i].id]
    return null
  }
  function save(icon) {
    if(!icon || icon.retiring || !active || !sizingReady || !monitor || typeof stash.recordPosition!=="function") return
    var point=[Math.round(icon.x),Math.round(icon.y)],next=Object.assign({},drafts)
    if(JSON.stringify(drafts[icon.groupKey] || savedPositions[icon.groupKey])===JSON.stringify(point)) return
    next[icon.groupKey]=point;drafts=next
    stash.recordPosition(monitor,icon.groupKey,point[0],point[1])
  }
  function initial(icon,index) {
    var stored=drafts[icon.groupKey] || savedPositions[icon.groupKey]
    if(Array.isArray(stored) && stored.length>=2) return Model.floatingPosition(stored,width,height,area,config.floatingPlacement!=="free",iconSize,iconSize)
    var origin=origins[icon.groupKey]
    if(!origin) {
      var preview=savedPositions["preview:"+icon.groupKey.slice("folded-preview:".length)]
      if(preview && preview.length>=3 && icon.group.windows.length) {
        var size=Geometry.dimensions(preview[2],icon.group.windows[0],area,config.floatingPreviewTitles==="shown",config.floatingPreviewFrame==="shown",Geometry.savedAspect(preview))
        origin={x:preview[0],y:preview[1],width:size.width,height:size.height}
      }
    }
    if(origin) return Model.floatingPosition([origin.x+(origin.width-iconSize)/2,origin.y+(origin.height-iconSize)/2],width,height,area,false,iconSize,iconSize)
    return Model.floatingPosition(Model.bubblePosition(null,index,width,height,collection.activeKeys.length,iconSize),width,height,area,config.floatingPlacement!=="free",iconSize,iconSize)
  }
  function updateRegions() {
    inputRegions=active && sizingReady && !blocked ? iconList().filter(function(icon) {return !icon.retiring}).map(function(icon) {return icon.hitRegion}) : []
    inputChanged()
  }
  function hit(globalX,globalY) {
    if(!active || !sizingReady || !monitor) return false
    var x=globalX-monitor.x,y=globalY-monitor.y
    return iconList().some(function(icon) {return !icon.retiring && Model.iconContains(x-icon.x,y-icon.y,icon.width,icon.inputShape,icon.hitRadius)})
  }
  function arrange() {
    iconList().forEach(function(icon,index) {
      if(!active || !sizingReady || icon.retiring) {icon.unregisterBody();return}
      var frozen=blocked || stash.groupClosing(icon.group) || config.floatingPreviewLock==="locked"
      if(icon.registered) world.freeze(icon.groupKey,frozen)
      if(icon.positionHeld || icon.positionAnimating) return
      if(icon.registered && Math.abs(icon.width-iconSize)>.1) icon.unregisterBody()
      icon.width=iconSize
      if(!icon.registered) {
        var point=initial(icon,index);icon.x=point[0];icon.y=point[1]
        world.add(icon.groupKey,icon.x,icon.y,icon.width,icon.height);icon.registered=true
        remember(icon);save(icon);icon.settleDelay.restart()
      } else {
        var saved=drafts[icon.groupKey] || savedPositions[icon.groupKey]
        var body=world.body(icon.groupKey)
        if(saved && body && !body.frozen && !(typeof stash.positionPending==="function" && stash.positionPending(icon.groupKey))) {
          var next=Model.floatingPosition(saved,width,height,area,config.floatingPlacement!=="free",icon.width,icon.height)
          world.sync(icon.groupKey,next[0],next[1],icon.width,icon.height)
        }
      }
      world.freeze(icon.groupKey,frozen)
    })
    updateRegions()
  }
  function details() {
    return {present:present,held:held,sizingReady:sizingReady,icons:iconList().filter(function(icon) {return !icon.retiring}).map(function(icon) {
      return {key:icon.groupKey,recordIds:icon.group.windows.map(function(record) {return record.id}),
        rect:{x:icon.x,y:icon.y,width:icon.width,height:icon.height},x:icon.x,y:icon.y,width:icon.width,height:icon.height,
        held:icon.positionHeld,moving:icon.positionAnimating,retiring:icon.retiring,appearance:icon.appearance()}
    }),world:world.details()}
  }
  onActiveChanged:placement.restart()
  onSizingReadyChanged:placement.restart()
  onWidthChanged:placement.restart()
  onHeightChanged:placement.restart()
  onBlockedChanged:placement.restart()
  onConfigChanged:placement.restart()
  onAreaChanged:placement.restart()
  onIconSizeChanged:placement.restart()
  onRecordIdsChanged: {
    var next=Object.assign({},lastRects)
    Object.keys(next).forEach(function(id) {if(recordIds.indexOf(id)<0) delete next[id]})
    if(JSON.stringify(next)!==JSON.stringify(lastRects)) lastRects=next
  }
  onSavedPositionsChanged: {
    var next=Object.assign({},drafts)
    Object.keys(next).forEach(function(key) {if(JSON.stringify(next[key])===JSON.stringify(savedPositions[key])) delete next[key]})
    if(JSON.stringify(next)!==JSON.stringify(drafts)) drafts=next
    placement.restart()
  }
  Connections {
    target:folded.stash
    ignoreUnknownSignals:true
    function onSnapshotChanged() {placement.restart()}
    function onPendingCloseIdsChanged() {placement.restart()}
  }
  Timer {id:placement;interval:0;onTriggered:folded.arrange()}
  Timer {id:regionsUpdate;interval:0;onTriggered:folded.updateRegions()}
  StashCollection {
    id:collection
    sourceGroups:folded.active ? folded.groups : []
    animations:folded.animations;animationSpeed:folded.animationSpeed
    onReconciled:placement.restart()
  }
  StashDragWorld {
    id:world
    area:folded.area;snapEdges:folded.config.floatingPlacement!=="free";physicsEnabled:folded.config.dragMotion!=="direct"
    animations:folded.animations;animationSpeed:folded.animationSpeed
    onMoved:function(key,x,y) {var icon=folded.iconForKey(key);if(icon && !icon.retiring) {icon.x=x;icon.y=y;folded.remember(icon)}}
    onActivityChanged:function(key,held,moving) {var icon=folded.iconForKey(key);if(icon) {icon.positionHeld=held;icon.positionAnimating=moving};if(!held && !moving) placement.restart();regionsUpdate.restart()}
    onSettled:function(key,x,y) {var icon=folded.iconForKey(key);if(icon && !icon.retiring) {icon.x=x;icon.y=y;folded.remember(icon);folded.save(icon)}}
  }
  Repeater {
    id:icons
    model:collection
    delegate:StashAnimatedIcon {
      id:icon
      required property string groupKey
      required retiring
      property bool registered:false
      property Timer settleDelay:Timer {
        interval:Motion.enter(folded.animations,folded.animationSpeed)
        onTriggered:if(icon.registered && !icon.retiring && !icon.positionHeld && !folded.blocked) world.cancel(icon.groupKey,true)
      }
      group:collection.dataByKey[groupKey] || ({key:groupKey,app:"",title:"",windows:[]})
      animations:folded.animations;animationSpeed:folded.animationSpeed
      idleOpacity:(folded.config.iconOpacity===undefined ? 100 : folded.config.iconOpacity)/100
      bubble:true;width:folded.iconSize;sizeScale:width/48
      frameVisible:folded.config.iconFrame==="shown";iconShape:folded.config.iconShape || "auto"
      draggable:folded.config.floatingPreviewLock!=="locked";enabled:folded.active && !folded.blocked && !retiring && !folded.stash.groupClosing(group)
      previewEnabled:false
      property Region hitRegion:StashIconRegion {originX:icon.x;originY:icon.y;size:icon.retiring ? 0 : icon.width;cornerRadius:icon.hitRadius;iconShape:icon.inputShape;onChanged:regionsUpdate.restart()}
      z:positionHeld ? 20 : hot ? 10 : 0
      function unregisterBody() {if(registered) world.remove(groupKey);registered=false;positionHeld=false;positionAnimating=false;settleDelay.stop();regionsUpdate.restart()}
      onRetiringChanged: {if(retiring) unregisterBody();else placement.restart();regionsUpdate.restart()}
      onXChanged:regionsUpdate.restart()
      onYChanged:regionsUpdate.restart()
      onWidthChanged:regionsUpdate.restart()
      onFrameVisibleChanged:regionsUpdate.restart()
      onPointerPressed:function(button) {if(registered && button!==Qt.LeftButton) world.cancel(groupKey,false)}
      onDragHeld:function(pressed) {if(!registered) return;if(pressed) world.press(groupKey);else positionHeld=false}
      onMoved:function(dx,dy) {if(registered) world.drag(groupKey,x+dx,y+dy)}
      onDragFinished:if(registered) world.release(groupKey)
      onActivated: {if(registered) world.cancel(groupKey,false);if(typeof folded.stash.unfoldPreviewWindows==="function") folded.stash.unfoldPreviewWindows(group.windows,folded.screenName)}
      onCloseRequested: {if(registered) world.cancel(groupKey,false);folded.stash.closeGroup(group,folded.screenName)}
      onContextRequested:function(x,y) {if(registered) world.cancel(groupKey,false);folded.stash.openContext(group,folded.screenName,mapToItem(folded.coordinateRoot,x,y))}
      Component.onCompleted:placement.restart()
      Component.onDestruction:unregisterBody()
    }
  }
  Component.onCompleted:placement.restart()
}
