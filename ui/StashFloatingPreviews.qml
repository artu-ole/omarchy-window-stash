pragma ComponentBehavior: Bound
import QtQuick
import Quickshell
import qs.Commons
import qs.Commons as Commons
import "FloatingPreviewModel.js" as Geometry

Item {
  id:previews
  required property var stash
  required property var config
  required property var area
  required property Item coordinateRoot
  required property string screenName
  required property var monitor
  required property var savedPositions
  property var groups:[]
  readonly property var previewGroups:groups.map(function(group) {
    return Object.assign({},group,{windows:group.windows.filter(function(record) {return record.previewFolded!==true})})
  }).filter(function(group) {return group.windows.length>0})
  readonly property var foldedGroups:groups.map(function(group) {
    return Object.assign({},group,{key:"folded-preview:"+group.key,windows:group.windows.filter(function(record) {return record.previewFolded===true})})
  }).filter(function(group) {return group.windows.length>0})
  property var foldOrigins:({})
  property var previousFoldedIds:({})
  property var unfoldArrivals:({})
  property bool active:false
  property bool blocked:false
  property bool captureAllowed:true
  property var drafts:({})
  property var observedSizes:({})
  property var pendingSizes:({})
  property var expandedObservedSizes:({})
  property var expandedPendingSizes:({})
  property int page:0
  property string expandedKey:""
  property int selectedIndex:0
  property bool keyboardSelection:false
  property string pendingInteractionId:""
  property int interactionAttempts:0
  property var activationShortcut:null
  readonly property bool interacting:typeof stash.endPreviewInteraction==="function" && (!!stash.previewInteractionRequest || !!stash.previewInteractionPendingRequest)
  property int regionRevision:0
  property var inputRegions:[]
  readonly property string animations:config.animations || "full"
  readonly property string animationSpeed:config.animationSpeed || "normal"
  readonly property var popupColors:Commons.Color.popups
  readonly property var fonts:Style.font
  readonly property var layoutOptions:({titles:config.floatingPreviewTitles==="shown",frame:config.floatingPreviewFrame==="shown",
    sizing:config.floatingPreviewSizing || "free",scale:Number(config.floatingPreviewScale || "100"),edges:config.floatingPlacement!=="free",page:page})
  readonly property var geometryGroups:Geometry.geometryGroups(collection.entries,observedSizes)
  readonly property var preliminary:Geometry.layout(geometryGroups,savedPositions,drafts,area,layoutOptions)
  readonly property bool overflow:preliminary.pages>1
  readonly property var layoutArea:({x:area.x,y:area.y,width:area.width,height:Math.max(1,area.height-(overflow ? 34 : 0))})
  readonly property var layout:Geometry.layout(geometryGroups,savedPositions,drafts,layoutArea,layoutOptions)
  readonly property var expandedGroup:expandedKey ? previewGroups.find(function(group) {return group.key===expandedKey}) || null : null
  readonly property var expandedRecords:expandedGroup ? expandedGroup.windows : []
  readonly property var expandedSourceSizes:Object.assign({},observedSizes,expandedObservedSizes)
  readonly property var expandedGeometryRecords:expandedRecords.map(function(record) {return Geometry.geometryRecord(record,previews.expandedSourceSizes)})
  readonly property var expandedAnchor:expandedKey ? cardForKey("preview:"+expandedKey) : null
  readonly property var expandedLayout:Geometry.groupGrid(expandedGeometryRecords,expandedAnchor ? {x:expandedAnchor.x,y:expandedAnchor.y,width:expandedAnchor.width,height:expandedAnchor.height} : area,
    area,config.floatingPreviewTitles==="shown",config.floatingPreviewFrame==="shown",config.floatingPreviewSizing==="preset" ? 280*Number(config.floatingPreviewScale || "100")/100 : expandedAnchor ? expandedAnchor.width : 280)
  readonly property bool present:collection.count>0 || folded.present
  readonly property bool held:folded.held || cardList().some(function(card) {return card.held || card.resizing})
  readonly property bool expanded:!!expandedGroup && expandedRecords.length>1
  readonly property string shortcutViewStamp:JSON.stringify([active,captureAllowed,blocked,layout.page,expandedKey,
    config.presentation,config.scope,config.grouping,config.floatingPreviewInteraction,screenName,monitor ? [monitor.x,monitor.y] : null])
  onShortcutViewStampChanged:activationShortcut=null
  signal inputChanged()
  width:coordinateRoot.width;height:coordinateRoot.height
  visible:present && captureAllowed
  Shortcut {sequence:"Escape";context:Qt.WindowShortcut;enabled:previews.expanded && !previews.interacting;onActivated:previews.closeExpansion()}
  Shortcut {sequence:"Left";context:Qt.WindowShortcut;enabled:previews.expanded && !previews.interacting;onActivated:previews.selectTile(-1)}
  Shortcut {sequence:"Right";context:Qt.WindowShortcut;enabled:previews.expanded && !previews.interacting;onActivated:previews.selectTile(1)}
  Shortcut {sequence:"Up";context:Qt.WindowShortcut;enabled:previews.expanded && !previews.interacting;onActivated:previews.selectTile(-previews.expandedLayout.columns)}
  Shortcut {sequence:"Down";context:Qt.WindowShortcut;enabled:previews.expanded && !previews.interacting;onActivated:previews.selectTile(previews.expandedLayout.columns)}
  Shortcut {sequence:"Return";context:Qt.WindowShortcut;enabled:previews.expanded && !previews.interacting;onActivated:previews.restoreSelected()}

  function cardList() {var result=[];for(var i=0;i<cards.count;i++) {var card=cards.itemAt(i);if(card) result.push(card)}return result}
  function tileList() {var result=[];for(var i=0;i<tiles.count;i++) {var tile=tiles.itemAt(i);if(tile) result.push(tile)}return result}
  function cardForKey(key) {return cardList().find(function(card) {return card.key===key}) || null}
  function foldedIconList() {return folded.iconList()}
  function prepareFold(key,origin) {
    if(typeof key!=="string" || key.indexOf("folded-preview:")!==0 || !origin) return
    var next=Object.assign({},foldOrigins);next[key]=Geometry.rectangle(origin);foldOrigins=next
  }
  function isFoldedGroup(group) {
    var records=[];groups.forEach(function(current) {records=records.concat(current.windows)})
    return !!group && group.windows.length>0 && group.windows.every(function(record) {
      return records.some(function(current) {return current.id===record.id && current.previewFolded===true})
    })
  }
  function unfoldArrival(group) {return group.windows.some(function(record) {return !!previousFoldedIds[record.id] || !!unfoldArrivals[record.id]})}
  function stageChanges() {
    var next={},arrivals=Object.assign({},unfoldArrivals),now=Date.now(),owned={},origins=Object.assign({},foldOrigins),keys={}
    groups.forEach(function(group) {group.windows.forEach(function(record) {
      owned[record.id]=true
      if(record.previewFolded===true) next[record.id]=true
      else if(previousFoldedIds[record.id]) arrivals[record.id]=now
    });keys["folded-preview:"+group.key]=true})
    Object.keys(arrivals).forEach(function(id) {if(!owned[id] || now-arrivals[id]>5000) delete arrivals[id]})
    Object.keys(origins).forEach(function(key) {if(!keys[key]) delete origins[key]})
    if(JSON.stringify(origins)!==JSON.stringify(foldOrigins)) foldOrigins=origins
    unfoldArrivals=arrivals;previousFoldedIds=next
  }
  function foldAt(x,y) {
    if(!active || !visible || !captureAllowed || blocked) return null
    if(folded.hit(x,y)) return {handled:true,ids:[]}
    var candidates=cardList().filter(function(card) {return card.visible && !card.retiring})
      .sort(function(first,second) {return first.z-second.z})
    if(expanded) candidates=candidates.concat(tileList().filter(function(tile) {return tile.inViewport}))
    for(var index=candidates.length-1;index>=0;index--) {
      var card=candidates[index]
      if(card.shortcutControlHit(x,y)) return {handled:true,ids:[]}
      if(!card.shortcutSurfaceHit(x,y)) continue
      if(!card.interactive || card.retiring || card.held || card.moving || card.resizing
          || (typeof stash.lifecycleReady==="boolean" && !stash.lifecycleReady)
          || card.group.windows.some(function(record) {return record.previewFolded===true || record.phase && record.phase!=="stashed"
            || stash.pendingCloseIds[record.id] || (stash.pendingPreviewFoldIds && stash.pendingPreviewFoldIds[record.id])})) return {handled:true,ids:[]}
      var groupKey=card.expandedTile ? expandedKey : card.group.key
      return {handled:true,ids:card.group.windows.map(function(record) {return record.id}),screenName:screenName,
        key:"folded-preview:"+groupKey,origin:card.visualRectOf(card)}
    }
    return null
  }
  function updateNativeInteractions() {cardList().concat(tileList()).forEach(function(card) {if(card.interactionBusy) card.syncNativeInteraction()})}
  function shortcutAvailable() {return active && visible && captureAllowed && !blocked && config.floatingPreviewInteraction==="on"}
  function shortcutCardAt(x,y) {
    if(!shortcutAvailable()) return null
    if(folded.hit(x,y)) return null
    var candidates=cardList().filter(function(card) {return card.visible && !card.retiring})
      .sort(function(first,second) {return first.z-second.z})
    if(expanded) candidates=candidates.concat(tileList().filter(function(tile) {return tile.inViewport}))
    // Resolve the frontmost image before checking readiness. An unavailable
    // image must not allow a shortcut to reach a different window behind it.
    for(var index=candidates.length-1;index>=0;index--) {
      var card=candidates[index]
      if(card.shortcutSurfaceHit(x,y)) return card.shortcutHit(x,y) ? card : null
      if(card.shortcutControlHit(x,y)) return null
    }
    return null
  }
  function handleActivationShortcut(serial,phase,x,y) {
    if(phase==="cancel") {activationShortcut=null;return false}
    if(phase==="press") {
      activationShortcut=null
      var candidate=shortcutCardAt(x,y)
      if(!candidate || !candidate.interactionReady(true)) return false
      activationShortcut={serial:serial,key:candidate.key,tile:candidate.expandedTile,identity:candidate.shortcutIdentity(),
        revision:candidate.interactionGeometryRevision,rect:JSON.stringify(candidate.nativeImageRect())}
      return true
    }
    var pending=activationShortcut;activationShortcut=null
    if(phase!=="release" || !pending || pending.serial!==serial || !shortcutAvailable()) return false
    var target=shortcutCardAt(x,y)
    if(!target || target.key!==pending.key || target.expandedTile!==pending.tile || target.shortcutIdentity()!==pending.identity
        || target.interactionGeometryRevision!==pending.revision || JSON.stringify(target.nativeImageRect())!==pending.rect
        || !target.interactionReady(true)) return false
    if(target.group.windows.length>1) {
      if(expandedKey!==target.group.key) activate(target)
      return true
    }
    return target.beginNativeInteraction()
  }
  function activateInteraction(id) {
    if(config.floatingPreviewInteraction!=="on" || !active || blocked) return false
    var cover=cardList().find(function(card) {return !card.retiring && card.group.windows.some(function(window) {return window.id===id})})
    if(!cover) return false
    pendingInteractionId=id;interactionAttempts=0
    var target=layout.cards[cover.key]
    if(target && target.page!==layout.page) {page=target.page;scheduleLayout()}
    if(cover.group.windows.length>1 && expandedKey!==cover.group.key) {
      clearExpandedGeometry();expandedKey=cover.group.key;keyboardSelection=false;strip.contentY=0
    }
    interactionStart.restart()
    return true
  }
  function startPendingInteraction() {
    if(!pendingInteractionId || !active || blocked || config.floatingPreviewInteraction!=="on") {pendingInteractionId="";return}
    if(++interactionAttempts>100) {
      pendingInteractionId="";stash.previewInteractionError="The preview is not ready or cannot fit completely on this screen";return
    }
    var id=pendingInteractionId
    var card=cardList().find(function(item) {return item.visible && !item.retiring && item.group.windows.length===1 && item.record && item.record.id===id})
    if(!card) {
      card=tileList().find(function(item) {return item.record && item.record.id===id})
      if(card) {
        var cell=expandedLayout.cells[id]
        if(cell && (cell.y<strip.contentY || cell.y+cell.height>strip.contentY+strip.height)) {
          strip.contentY=Geometry.clamp(cell.y,0,Math.max(0,strip.contentHeight-strip.height))
          interactionStart.restart();return
        }
      }
    }
    if(card && card.beginNativeInteraction()) {pendingInteractionId="";return}
    interactionStart.restart()
  }
  function updateRegions() {
    var next=[]
    if(active && captureAllowed && !blocked) {
      cardList().forEach(function(card) {
        if(card.visible && !card.retiring) {next.push(card.inputRegion);if(card.controlsOutside) next.push(card.managementRegion)}
      })
      if(expanded) tileList().forEach(function(tile) {
        if(tile.inViewport) {next.push(tile.clippedRegion);if(tile.controlsOutside) next.push(tile.managementRegion)}
      })
      if(layout.pages>1) next.push(navigationRegion)
      next=next.concat(folded.inputRegions)
    }
    inputRegions=next;inputChanged()
  }
  function scheduleRegions() {regionDelay.restart()}
  function scheduleLayout() {placementDelay.restart()}
  function observeSource(recordId,width,height) {
    var size=[width,height],previous=pendingSizes[recordId] || observedSizes[recordId]
    if(!Geometry.validSourceSize(size) || Geometry.sameAspect(previous,size)) return
    var next=Object.assign({},pendingSizes);next[recordId]=size;pendingSizes=next
    sourceGeometryDelay.restart()
  }
  function observeExpandedSource(recordId,width,height) {
    var size=[width,height],previous=expandedPendingSizes[recordId] || expandedObservedSizes[recordId]
    if(!expanded || !Geometry.validSourceSize(size) || Geometry.sameAspect(previous,size)) return
    var next=Object.assign({},expandedPendingSizes);next[recordId]=size;expandedPendingSizes=next
    sourceGeometryDelay.restart()
  }
  function applySourceGeometry() {
    var next=Object.assign({},observedSizes),pending=Object.assign({},pendingSizes),changed=false
    var owned={}
    collection.entries.forEach(function(group) {group.windows.forEach(function(record) {owned[record.id]=true})})
    Object.keys(pending).forEach(function(id) {
      if(!owned[id]) {delete pending[id];return}
      if(cardList().some(function(card) {return card.displayRecord && card.displayRecord.id===id && (card.held || card.resizing || card.moving || card.interactionBusy)})) return
      if(!Geometry.sameAspect(next[id],pending[id])) {next[id]=pending[id];changed=true}
      delete pending[id]
    })
    Object.keys(next).forEach(function(id) {if(!owned[id]) {delete next[id];changed=true}})
    if(changed) observedSizes=next
    if(JSON.stringify(pending)!==JSON.stringify(pendingSizes)) pendingSizes=pending
    // A Still cover and its newly opened group tile can represent different
    // captures of the same client. Their frame aspects must remain independent.
    var expandedOwned={},expandedNext=Object.assign({},expandedObservedSizes),expandedPending=Object.assign({},expandedPendingSizes),expandedChanged=false
    if(expanded) expandedRecords.forEach(function(record) {expandedOwned[record.id]=true})
    Object.keys(expandedPending).forEach(function(id) {
      if(tileList().some(function(tile) {return tile.displayRecord && tile.displayRecord.id===id && tile.interactionBusy})) return
      if(expandedOwned[id] && !Geometry.sameAspect(expandedNext[id],expandedPending[id])) {expandedNext[id]=expandedPending[id];expandedChanged=true}
      delete expandedPending[id]
    })
    Object.keys(expandedNext).forEach(function(id) {if(!expandedOwned[id]) {delete expandedNext[id];expandedChanged=true}})
    if(expandedChanged) expandedObservedSizes=expandedNext
    if(JSON.stringify(expandedPending)!==JSON.stringify(expandedPendingSizes)) expandedPendingSizes=expandedPending
  }
  function save(card) {
    if(!card || card.retiring || !active || !captureAllowed || !monitor) return
    var prior=drafts[card.key] || savedPositions[card.key],savedWidth=config.floatingPreviewSizing==="preset" ? prior && prior.length>=3 ? prior[2] : 280 : card.width
    var point=[Math.round(card.x),Math.round(card.y),Math.round(savedWidth)]
    if(card.aspectOverride>0) point.push(card.aspectOverride)
    if(prior && JSON.stringify(prior)===JSON.stringify(point)) return
    var next=Object.assign({},drafts)
    next[card.key]=point
    drafts=next
    stash.recordPreviewPosition(monitor,card.key,point[0],point[1],point[2],point.length>3 ? point[3] : 0)
  }
  function requestShape(card,aspect,axis,settle) {
    if(!card || !card.displayRecord || card.expandedTile || typeof stash.requestPreviewAspect!=="function") return false
    return stash.requestPreviewAspect(card.record.id,aspect,axis,settle)
  }
  function applySavedShape(card) {
    if(!card || !card.visible || card.retiring || card.resizing || card.interactionBusy || card.expandedTile
        || !card.record || !card.imageReadyForShape()) return
    var size=card.capturedSourceSize(),state=typeof stash.previewGeometryState==="function" ? stash.previewGeometryState(card.record.id) : null
    if(state && state.ready && Math.abs(Number(state.aspect)-card.aspectOverride)<=Math.max(Number(state.aspect),card.aspectOverride)*.0001 && card.frameMatchesGeometry()) return
    if(card.aspectOverride>0 && !Geometry.sameAspect([card.aspectOverride,1],[size.width,size.height])) {
      if(state && Math.abs(Number(state.requestedAspect)-card.aspectOverride)<=card.aspectOverride*.0001) return
      requestShape(card,card.aspectOverride,"width",true);return
    }
    if(card.record.previewResized && !state && typeof stash.verifyPreviewGeometry==="function") stash.verifyPreviewGeometry(card.record.id)
  }
  function acceptShape(card,state) {
    if(!card || !card.record || !state || state.id && state.id!==card.record.id || !Geometry.customAspect(state.aspect)) return
    if(card.resizing) return
    var anchor=card.shapeAnchor,ratio=Number(state.aspect),natural=Geometry.aspect(card.record)
    var verifying=!Number.isFinite(state.requestedAspect) && !anchor
    var naturalTolerance=state.size && state.size[1]>0 ? 2/state.size[1] : natural*.0001
    var custom=(verifying && card.aspectOverride<=0) || (anchor && anchor.reset && Math.abs(ratio-natural)<=naturalTolerance) ? 0 : ratio
    card.aspectOverride=custom
    if(anchor && anchor.recordId===card.record.id) {
      var c=Geometry.chrome(card.titleVisible,card.frameVisible)
      var wanted=anchor.axis==="width" ? Math.max(1,anchor.height-c.header-c.inset*2)*ratio+c.inset*2 : anchor.width
      var d=Geometry.dimensions(wanted,card.geometryRecord,previews.layoutArea,card.titleVisible,card.frameVisible,ratio)
      card.width=d.width
      card.x=anchor.edge==="left" ? anchor.x+anchor.width-d.width : anchor.x
      card.y=anchor.edge==="top" ? anchor.y+anchor.height-d.height : anchor.y
      var p=Geometry.position({x:card.x,y:card.y,width:card.width,height:card.height},previews.layoutArea)
      card.x=p.x;card.y=p.y
      card.shapeAnchor=null
    }
    world.remove(card.key);world.add(card.key,card.x,card.y,card.width,card.height);card.registered=true
    world.freeze(card.key,blocked || config.floatingPreviewLock==="locked")
    save(card);scheduleLayout()
  }
  function resetShape(card) {
    if(!card || !card.canResize || !card.record || card.expandedTile) return
    card.shapeAnchor={x:card.x,y:card.y,width:card.width,height:card.height,axis:"height",edge:"bottom",recordId:card.record.id,reset:true}
    card.aspectOverride=0
    save(card);requestShape(card,Geometry.aspect(card.record),"height",true);scheduleLayout()
  }
  function resetPreviewProportions(id) {
    var card=cardList().find(function(item) {return item.visible && !item.retiring && item.displayRecord && item.displayRecord.id===id})
    if(!card || !card.canResize) return false
    resetShape(card);return true
  }
  function clearExpandedGeometry() {expandedObservedSizes={};expandedPendingSizes={}}
  function closeExpansion() {activationShortcut=null;pendingInteractionId="";expandedKey="";clearExpandedGeometry();selectedIndex=0;keyboardSelection=false;strip.contentY=0;scheduleRegions()}
  function selectTile(delta) {
    if(!expandedRecords.length) return
    selectedIndex=Geometry.clamp(selectedIndex+delta,0,expandedRecords.length-1);keyboardSelection=true
    var cell=expandedLayout.cells[expandedRecords[selectedIndex].id]
    if(cell) strip.contentY=Geometry.clamp(cell.y<strip.contentY ? cell.y : cell.y+cell.height>strip.contentY+strip.height ? cell.y+cell.height-strip.height : strip.contentY,0,Math.max(0,strip.contentHeight-strip.height))
  }
  function restoreSelected() {
    var record=expandedRecords[selectedIndex]
    if(!record) return
    var id=record.id;closeExpansion();stash.restorePreviewWindow(id,screenName)
  }
  function activate(card) {
    if(stash.groupClosing(card.group)) return
    if(card.group.windows.length>1) {
      if(expandedKey===card.group.key) {closeExpansion();return}
      clearExpandedGeometry();expandedKey=card.group.key
      selectedIndex=0;keyboardSelection=false;strip.contentY=0;scheduleRegions()
    } else {closeExpansion();stash.restorePreviewWindow(card.record.id,screenName)}
  }
  function stepPage(direction) {
    if(held || layout.pages<=1) return
    closeExpansion();page=Geometry.clamp(layout.page+direction,0,layout.pages-1)
    scheduleLayout()
  }
  function arrange() {
    if(!active || !captureAllowed) {
      cardList().forEach(function(card) {world.remove(card.key);card.registered=false})
      scheduleRegions();return
    }
    cardList().forEach(function(card) {
      var target=layout.cards[card.key]
      if(!target || !target.visible || card.retiring) {world.remove(card.key);card.registered=false;return}
      if(card.held || card.resizing) return
      var body=world.body(card.key)
      if(card.interactionBusy) {world.freeze(card.key,true);card.syncNativeInteraction();return}
      if(body && body.moving) return
      var changed=!body || Math.abs(body.width-target.width)>.05 || Math.abs(body.height-target.height)>.05
      card.aspectOverride=target.aspectOverride || 0
      card.width=target.width
      if(!card.registered) {
        card.x=target.x;card.y=target.y
        world.add(card.key,card.x,card.y,card.width,card.height)
        card.registered=true
      } else if(changed || !stash.positionPending(card.key)) {
        var x=target.x,y=target.y
        if(!body || Math.abs(body.x-x)>.05 || Math.abs(body.y-y)>.05 || changed) {
          world.remove(card.key)
          world.add(card.key,x,y,card.width,card.height)
        }
      }
      world.freeze(card.key,blocked || config.floatingPreviewLock==="locked" || expanded)
      applySavedShape(card)
    })
    scheduleRegions()
  }
  function details() {
    return {present:present,held:held,expanded:expanded,expandedKey:expandedKey,folded:folded.details(),
      cards:cardList().filter(function(card) {return card.visible && !card.retiring}).map(function(card) {return card.details()}),
      tiles:tileList().filter(function(tile) {return tile.inViewport}).map(function(tile) {return tile.details()}),
      viewportRect:{x:strip.x,y:strip.y,width:strip.width,height:strip.height},
      overflow:{enabled:layout.pages>1,page:layout.page,pages:layout.pages,capacity:layout.capacity,previousRect:rectOf(previous),nextRect:rectOf(next)},
      groupOverflow:{enabled:expandedLayout.overflow,contentHeight:strip.contentHeight,contentY:strip.contentY},
      world:world.details()}
  }
  function rectOf(item) {var p=item.mapToItem(coordinateRoot,0,0);return {x:p.x,y:p.y,width:item.width,height:item.height}}
  onLayoutChanged: {
    if(expandedKey && (!layout.cards["preview:"+expandedKey] || !layout.cards["preview:"+expandedKey].visible)) closeExpansion()
    scheduleLayout()
  }
  onActiveChanged: {if(!active) closeExpansion();scheduleLayout()}
  onGroupsChanged: {stageChanges();scheduleLayout()}
  onCaptureAllowedChanged: {if(!captureAllowed) closeExpansion();scheduleLayout()}
  onBlockedChanged: {if(blocked) {closeExpansion();cardList().forEach(function(card) {card.cancelInteraction()})};scheduleLayout()}
  onExpandedChanged: {expansionValidation.restart();scheduleRegions();scheduleLayout()}
  onInteractingChanged: {activationShortcut=null;scheduleLayout();sourceGeometryDelay.restart();scheduleRegions()}
  onExpandedRecordsChanged: {expansionValidation.restart();sourceGeometryDelay.restart();scheduleRegions()}
  onSavedPositionsChanged: {
    var next=Object.assign({},drafts)
    Object.keys(next).forEach(function(key) {if(JSON.stringify(next[key])===JSON.stringify(savedPositions[key])) delete next[key]})
    if(JSON.stringify(next)!==JSON.stringify(drafts)) drafts=next
    scheduleLayout()
  }
  Connections {
    target:previews.stash
    ignoreUnknownSignals:true
    function onPointerClicked(x,y,button) {
      if(!previews.expanded || !previews.monitor) return
      var px=x-previews.monitor.x,py=y-previews.monitor.y
      if(previews.expandedAnchor && Geometry.contains(previews.expandedAnchor,px,py)) return
      if(Geometry.contains({x:strip.x,y:strip.y,width:strip.width,height:strip.height},px,py)) return
      previews.closeExpansion()
    }
    function onSnapshotChanged() {previews.scheduleLayout()}
    function onPreviewInteractionRequestChanged() {previews.scheduleLayout()}
    function onPreviewInteractionPendingRequestChanged() {previews.scheduleLayout()}
  }
  Timer {id:interactionStart;interval:50;onTriggered:previews.startPendingInteraction()}
  Timer {id:regionDelay;interval:0;onTriggered:previews.updateRegions()}
  Timer {id:placementDelay;interval:0;onTriggered:previews.arrange()}
  Timer {id:sourceGeometryDelay;interval:0;onTriggered:previews.applySourceGeometry()}
  Timer {
    id:expansionValidation;interval:0
    onTriggered: {
      if(previews.expandedKey && previews.expandedRecords.length<=1) previews.closeExpansion()
      else previews.selectedIndex=Math.max(0,Math.min(previews.selectedIndex,previews.expandedRecords.length-1))
    }
  }
  StashCollection {
    id:collection
    sourceGroups:previews.active ? previews.previewGroups : []
    animations:previews.animations;animationSpeed:previews.animationSpeed
    onReconciled: {previews.scheduleLayout();sourceGeometryDelay.restart()}
  }
  StashDragWorld {
    id:world
    area:previews.layoutArea
    snapEdges:previews.config.floatingPlacement!=="free"
    physicsEnabled:previews.config.dragMotion!=="direct"
    animations:previews.animations;animationSpeed:previews.animationSpeed
    onMoved:function(key,x,y) {var card=previews.cardForKey(key);if(card && !card.retiring) {card.x=x;card.y=y}}
    onActivityChanged:function(key,held,moving) {
      var card=previews.cardForKey(key)
      if(card) {card.held=held;card.moving=moving}
      if(!held && !moving) previews.scheduleLayout()
      previews.scheduleRegions()
    }
    onSettled:function(key,x,y) {
      var card=previews.cardForKey(key)
      if(card && !card.resizing && !card.retiring) {card.x=x;card.y=y;previews.save(card)}
    }
  }
  Repeater {
    id:cards
    model:collection
    delegate:StashPreviewCard {
      id:card
      required property string groupKey
      required retiring
      readonly property var target:previews.layout.cards[key] || null
      property bool registered:false
      property var resizeOrigin:null
      sourceResizeActive:resizing && !!resizeOrigin && ["left","right","top","bottom"].indexOf(resizeOrigin.edge)>=0
      property var shapeAnchor:null
      stash:previews.stash;config:previews.config;group:collection.dataByKey[groupKey] || ({key:groupKey,windows:[]})
      sourceSizes:previews.observedSizes
      coordinateRoot:previews.coordinateRoot;screenName:previews.screenName
      managementArea:previews.area
      captureAllowed:previews.captureAllowed && previews.active && !!target && target.visible
      interactive:previews.active && previews.captureAllowed && !previews.blocked && !previews.stash.groupClosing(group)
      visible:!!target && target.visible && previews.captureAllowed
      maximumHeight:previews.layoutArea.height
      folding:retiring && previews.isFoldedGroup(group)
      unfolding:previews.unfoldArrival(group)
      stageIconSize:folded.iconSize
      stageOrigin:unfolding ? folded.originFor(group.windows) : null
      width:280
      aspectOverride:target ? target.aspectOverride || 0 : 0
      onInputChanged:previews.scheduleRegions()
      onSourceAspectObserved:function(recordId,width,height) {previews.observeSource(recordId,width,height);previews.applySavedShape(card)}
      onSourceGeometryAccepted:function(state) {previews.acceptShape(card,state)}
      onProportionsResetRequested:previews.resetShape(card)
      onGeometryReleased:sourceGeometryDelay.restart()
      onMovePressed: {previews.closeExpansion();world.press(key)}
      onMoveRequested:function(x,y) {world.drag(key,x,y)}
      onMoveReleased:world.release(key)
      onMoveCanceled:world.cancel(key,false)
      onResizePressed:function(corner) {
        previews.closeExpansion();world.remove(key);registered=false
        resizeOrigin={x:x,y:y,width:width,height:height,aspect:dimensions.aspect,custom:aspectOverride,edge:corner,
          axis:corner==="left" || corner==="right" ? "width" : "height",recordId:record ? record.id : ""}
        shapeAnchor=Object.assign({},resizeOrigin)
      }
      onResizeRequested:function(dx,dy,corner) {
        if(!resizeOrigin) return
        var side=["left","right","top","bottom"].indexOf(corner)>=0
        var rect=Geometry.resize(resizeOrigin,geometryRecord,previews.layoutArea,dx,dy,corner,titleVisible,frameVisible,resizeOrigin.aspect)
        aspectOverride=side ? rect.aspect : resizeOrigin.custom
        width=rect.width;x=rect.x;y=rect.y
        if(side) previews.requestShape(card,rect.aspect,resizeOrigin.axis,false)
      }
      onResizeReleased: {
        if(!resizeOrigin) return
        var origin=resizeOrigin,side=["left","right","top","bottom"].indexOf(origin.edge)>=0
        resizeOrigin=null
        if(!record || origin.recordId!==record.id) {shapeAnchor=null;previews.scheduleLayout();return}
        world.add(key,x,y,width,height);registered=true
        world.freeze(key,previews.blocked || previews.config.floatingPreviewLock==="locked")
        previews.save(card)
        if(side) previews.requestShape(card,aspectOverride,origin.axis,true)
        else shapeAnchor=null
        previews.scheduleLayout()
      }
      onActivated:previews.activate(card)
      onContextRequested:function(x,y) {previews.closeExpansion();previews.stash.openContext(group,previews.screenName,Qt.point(x,y))}
      onCloseRequested: {previews.closeExpansion();previews.stash.closeGroup(group,previews.screenName)}
      onScrolled:function(delta) {if(delta) previews.stepPage(delta<0 ? 1 : -1)}
      Component.onCompleted:previews.scheduleLayout()
      Component.onDestruction: {world.remove(key);previews.scheduleRegions()}
    }
  }
  StashFoldedPreviews {
    id:folded
    stash:previews.stash;config:previews.config;groups:previews.foldedGroups
    savedPositions:previews.savedPositions;area:previews.area;monitor:previews.monitor
    coordinateRoot:previews.coordinateRoot;screenName:previews.screenName;origins:previews.foldOrigins
    recordIds:previews.groups.reduce(function(ids,group) {return ids.concat(group.windows.map(function(record) {return record.id}))},[])
    active:previews.active && previews.captureAllowed;blocked:previews.blocked
    onInputChanged:previews.scheduleRegions()
  }
  // Groups unfold as a wrapping grid, never a one-window carousel. The grid
  // scrolls only when its complete set cannot fit on this monitor.
  Flickable {
    id:strip
    x:previews.expandedLayout.x;y:previews.expandedLayout.y
    width:previews.expandedLayout.width;height:previews.expandedLayout.height
    contentWidth:width;contentHeight:previews.expandedLayout.contentHeight
    clip:true;visible:previews.expanded && previews.active && previews.captureAllowed
    interactive:previews.expandedLayout.overflow && !previews.interacting
    flickableDirection:Flickable.VerticalFlick;boundsBehavior:Flickable.StopAtBounds
    z:40
    onContentYChanged: {previews.scheduleRegions();previews.updateNativeInteractions()}
    Repeater {
      id:tiles
      model:previews.expanded ? previews.expandedRecords : []
      delegate:StashPreviewCard {
        id:tile
        required property var modelData
        readonly property var cell:previews.expandedLayout.cells[modelData.id] || ({x:0,y:0,width:1,height:1})
        readonly property bool inViewport:strip.visible && y+height>strip.contentY && y<strip.contentY+strip.height
        readonly property Region clippedRegion:Region {
          x:strip.x+tile.x;y:Math.max(strip.y,strip.y+tile.y-strip.contentY)
          width:tile.width;height:Math.max(0,Math.min(strip.y+strip.height,strip.y+tile.y-strip.contentY+tile.height)-y)
          onChanged:previews.scheduleRegions()
        }
        stash:previews.stash;config:previews.config;group:({key:"window:"+modelData.id,windows:[modelData]})
        sourceSizes:previews.expandedSourceSizes
        coordinateRoot:previews.coordinateRoot;screenName:previews.screenName
        managementArea:previews.area
        x:cell.x;y:cell.y;width:cell.width
        captureAllowed:previews.captureAllowed && inViewport
        interactive:previews.expanded && !previews.blocked && !previews.stash.pendingCloseIds[modelData.id]
        movable:false;resizable:false;expandedTile:true
        maximumHeight:previews.area.height
        interactionClipRect:({x:strip.x,y:strip.y,width:strip.width,height:strip.height,offset:strip.contentY})
        keyboardSelected:!!(previews.keyboardSelection && previews.expandedRecords[previews.selectedIndex] && previews.expandedRecords[previews.selectedIndex].id===modelData.id)
        onInputChanged:previews.scheduleRegions()
        onSourceAspectObserved:function(recordId,width,height) {previews.observeExpandedSource(recordId,width,height)}
        onGeometryReleased:sourceGeometryDelay.restart()
        onActivated: {var id=modelData.id;previews.closeExpansion();previews.stash.restorePreviewWindow(id,previews.screenName)}
        onContextRequested:function(x,y) {previews.closeExpansion();previews.stash.openContext(group,previews.screenName,Qt.point(x,y))}
        onCloseRequested:previews.stash.closeWindows([modelData],previews.screenName)
        onScrolled:function(delta) {strip.contentY=Geometry.clamp(strip.contentY-delta/3,0,Math.max(0,strip.contentHeight-strip.height))}
      }
    }
  }
  Item {
    id:navigation
    x:previews.area.x+previews.area.width-width-8;y:previews.area.y+previews.area.height-height-2
    width:112;height:28
    visible:previews.active && previews.captureAllowed && previews.layout.pages>1
    enabled:!previews.blocked
    StashActionButton {
      id:previous
      size:28;iconText:"‹";tooltipText:"Previous previews";foreground:previews.popupColors.text
      enabled:previews.layout.page>0
      animations:previews.animations;animationSpeed:previews.animationSpeed
      onClicked:previews.stepPage(-1)
    }
    Text {
      x:32;width:48;height:parent.height
      text:(previews.layout.page+1)+" / "+previews.layout.pages;textFormat:Text.PlainText
      color:previews.popupColors.text;font.family:previews.fonts.family;font.pixelSize:previews.fonts.caption
      horizontalAlignment:Text.AlignHCenter;verticalAlignment:Text.AlignVCenter
    }
    StashActionButton {
      id:next
      x:84;size:28;iconText:"›";tooltipText:"Next previews";foreground:previews.popupColors.text
      enabled:previews.layout.page<previews.layout.pages-1
      animations:previews.animations;animationSpeed:previews.animationSpeed
      onClicked:previews.stepPage(1)
    }
  }
  Region {id:navigationRegion;item:navigation;onChanged:previews.scheduleRegions()}
  Component.onCompleted:scheduleLayout()
}
