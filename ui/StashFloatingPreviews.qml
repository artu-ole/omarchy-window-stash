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
  property bool active:false
  property bool blocked:false
  property bool captureAllowed:true
  property var drafts:({})
  property int page:0
  property string expandedKey:""
  property int selectedIndex:0
  property bool keyboardSelection:false
  property int regionRevision:0
  property var inputRegions:[]
  readonly property string animations:config.animations || "full"
  readonly property string animationSpeed:config.animationSpeed || "normal"
  readonly property var popupColors:Commons.Color.popups
  readonly property var fonts:Style.font
  readonly property var layoutOptions:({titles:config.floatingPreviewTitles==="shown",frame:config.floatingPreviewFrame==="shown",
    sizing:config.floatingPreviewSizing || "free",scale:Number(config.floatingPreviewScale || "100"),edges:config.floatingPlacement!=="free",page:page})
  readonly property var preliminary:Geometry.layout(collection.entries,savedPositions,drafts,area,layoutOptions)
  readonly property bool overflow:preliminary.pages>1
  readonly property var layoutArea:({x:area.x,y:area.y,width:area.width,height:Math.max(1,area.height-(overflow ? 34 : 0))})
  readonly property var layout:Geometry.layout(collection.entries,savedPositions,drafts,layoutArea,layoutOptions)
  readonly property var expandedGroup:expandedKey ? groups.find(function(group) {return group.key===expandedKey}) || null : null
  readonly property var expandedRecords:expandedGroup ? expandedGroup.windows : []
  readonly property var expandedAnchor:expandedKey ? cardForKey("preview:"+expandedKey) : null
  readonly property var expandedLayout:Geometry.groupGrid(expandedRecords,expandedAnchor ? {x:expandedAnchor.x,y:expandedAnchor.y,width:expandedAnchor.width,height:expandedAnchor.height} : area,
    area,config.floatingPreviewTitles==="shown",config.floatingPreviewFrame==="shown",config.floatingPreviewSizing==="preset" ? 280*Number(config.floatingPreviewScale || "100")/100 : expandedAnchor ? expandedAnchor.width : 280)
  readonly property bool present:collection.count>0
  readonly property bool held:cardList().some(function(card) {return card.held || card.resizing})
  readonly property bool expanded:!!expandedGroup && expandedRecords.length>1
  signal inputChanged()
  width:coordinateRoot.width;height:coordinateRoot.height
  visible:present && captureAllowed
  Shortcut {sequence:"Escape";context:Qt.WindowShortcut;enabled:previews.expanded;onActivated:previews.closeExpansion()}
  Shortcut {sequence:"Left";context:Qt.WindowShortcut;enabled:previews.expanded;onActivated:previews.selectTile(-1)}
  Shortcut {sequence:"Right";context:Qt.WindowShortcut;enabled:previews.expanded;onActivated:previews.selectTile(1)}
  Shortcut {sequence:"Up";context:Qt.WindowShortcut;enabled:previews.expanded;onActivated:previews.selectTile(-previews.expandedLayout.columns)}
  Shortcut {sequence:"Down";context:Qt.WindowShortcut;enabled:previews.expanded;onActivated:previews.selectTile(previews.expandedLayout.columns)}
  Shortcut {sequence:"Return";context:Qt.WindowShortcut;enabled:previews.expanded;onActivated:previews.restoreSelected()}

  function cardList() {var result=[];for(var i=0;i<cards.count;i++) {var card=cards.itemAt(i);if(card) result.push(card)}return result}
  function tileList() {var result=[];for(var i=0;i<tiles.count;i++) {var tile=tiles.itemAt(i);if(tile) result.push(tile)}return result}
  function cardForKey(key) {return cardList().find(function(card) {return card.key===key}) || null}
  function updateRegions() {
    var next=[]
    if(active && captureAllowed && !blocked) {
      cardList().forEach(function(card) {if(card.visible && !card.retiring) next.push(card.inputRegion)})
      if(expanded) tileList().forEach(function(tile) {if(tile.inViewport) next.push(tile.clippedRegion)})
      if(layout.pages>1) next.push(navigationRegion)
    }
    inputRegions=next;inputChanged()
  }
  function scheduleRegions() {regionDelay.restart()}
  function scheduleLayout() {placementDelay.restart()}
  function save(card) {
    if(!card || card.retiring || !active || !captureAllowed || !monitor) return
    var prior=drafts[card.key] || savedPositions[card.key],savedWidth=config.floatingPreviewSizing==="preset" ? prior && prior.length>=3 ? prior[2] : 280 : card.width
    var point=[Math.round(card.x),Math.round(card.y),Math.round(savedWidth)]
    if(prior && JSON.stringify(prior)===JSON.stringify(point)) return
    var next=Object.assign({},drafts)
    next[card.key]=point
    drafts=next
    stash.recordPreviewPosition(monitor,card.key,point[0],point[1],point[2])
  }
  function closeExpansion() {expandedKey="";selectedIndex=0;keyboardSelection=false;strip.contentY=0;scheduleRegions()}
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
      expandedKey=expandedKey===card.group.key ? "" : card.group.key
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
      if(body && body.moving) return
      var changed=!body || Math.abs(body.width-target.width)>.05 || Math.abs(body.height-target.height)>.05
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
    })
    scheduleRegions()
  }
  function details() {
    return {present:present,held:held,expanded:expanded,expandedKey:expandedKey,
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
  onCaptureAllowedChanged: {if(!captureAllowed) closeExpansion();scheduleLayout()}
  onBlockedChanged: {if(blocked) {closeExpansion();cardList().forEach(function(card) {card.cancelInteraction()})};scheduleLayout()}
  onExpandedChanged: {expansionValidation.restart();scheduleRegions();scheduleLayout()}
  onExpandedRecordsChanged: {expansionValidation.restart();scheduleRegions()}
  onSavedPositionsChanged: {
    var next=Object.assign({},drafts)
    Object.keys(next).forEach(function(key) {if(JSON.stringify(next[key])===JSON.stringify(savedPositions[key])) delete next[key]})
    if(JSON.stringify(next)!==JSON.stringify(drafts)) drafts=next
    scheduleLayout()
  }
  Connections {
    target:previews.stash
    function onPointerClicked(x,y,button) {
      if(!previews.expanded || !previews.monitor) return
      var px=x-previews.monitor.x,py=y-previews.monitor.y
      if(previews.expandedAnchor && Geometry.contains(previews.expandedAnchor,px,py)) return
      if(Geometry.contains({x:strip.x,y:strip.y,width:strip.width,height:strip.height},px,py)) return
      previews.closeExpansion()
    }
    function onSnapshotChanged() {previews.scheduleLayout()}
  }
  Timer {id:regionDelay;interval:0;onTriggered:previews.updateRegions()}
  Timer {id:placementDelay;interval:0;onTriggered:previews.arrange()}
  Timer {
    id:expansionValidation;interval:0
    onTriggered: {
      if(previews.expandedKey && previews.expandedRecords.length<=1) previews.closeExpansion()
      else previews.selectedIndex=Math.max(0,Math.min(previews.selectedIndex,previews.expandedRecords.length-1))
    }
  }
  StashCollection {
    id:collection
    sourceGroups:previews.active ? previews.groups : []
    animations:previews.animations;animationSpeed:previews.animationSpeed
    onReconciled:previews.scheduleLayout()
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
      required property bool retiring
      readonly property var target:previews.layout.cards[key] || null
      property bool registered:false
      property var resizeOrigin:null
      stash:previews.stash;config:previews.config;group:collection.dataByKey[groupKey] || ({key:groupKey,windows:[]})
      coordinateRoot:previews.coordinateRoot;screenName:previews.screenName
      captureAllowed:previews.captureAllowed && previews.active && !!target && target.visible
      interactive:previews.active && previews.captureAllowed && !previews.blocked && !previews.stash.groupClosing(group)
      visible:!!target && target.visible && previews.captureAllowed
      maximumHeight:previews.layoutArea.height
      width:280
      onInputChanged:previews.scheduleRegions()
      onMovePressed: {previews.closeExpansion();world.press(key)}
      onMoveRequested:function(x,y) {world.drag(key,x,y)}
      onMoveReleased:world.release(key)
      onMoveCanceled:world.cancel(key,false)
      onResizePressed:function(corner) {
        previews.closeExpansion();world.remove(key);registered=false
        resizeOrigin={x:x,y:y,width:width,height:height}
      }
      onResizeRequested:function(dx,dy,corner) {
        if(!resizeOrigin) return
        var rect=Geometry.resize(resizeOrigin,record,previews.layoutArea,dx,dy,corner,titleVisible,frameVisible)
        width=rect.width;x=rect.x;y=rect.y
      }
      onResizeReleased: {
        if(!resizeOrigin) return
        resizeOrigin=null
        world.add(key,x,y,width,height);registered=true
        world.freeze(key,previews.blocked || previews.config.floatingPreviewLock==="locked")
        previews.save(card)
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
  // Groups unfold as a wrapping grid, never a one-window carousel. The grid
  // scrolls only when its complete set cannot fit on this monitor.
  Flickable {
    id:strip
    x:previews.expandedLayout.x;y:previews.expandedLayout.y
    width:previews.expandedLayout.width;height:previews.expandedLayout.height
    contentWidth:width;contentHeight:previews.expandedLayout.contentHeight
    clip:true;visible:previews.expanded && previews.active && previews.captureAllowed
    interactive:previews.expandedLayout.overflow
    flickableDirection:Flickable.VerticalFlick;boundsBehavior:Flickable.StopAtBounds
    z:40
    onContentYChanged:previews.scheduleRegions()
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
        coordinateRoot:previews.coordinateRoot;screenName:previews.screenName
        x:cell.x;y:cell.y;width:cell.width
        captureAllowed:previews.captureAllowed && inViewport
        interactive:previews.expanded && !previews.blocked && !previews.stash.pendingCloseIds[modelData.id]
        movable:false;resizable:false;expandedTile:true
        maximumHeight:previews.area.height
        keyboardSelected:!!(previews.keyboardSelection && previews.expandedRecords[previews.selectedIndex] && previews.expandedRecords[previews.selectedIndex].id===modelData.id)
        onInputChanged:previews.scheduleRegions()
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
