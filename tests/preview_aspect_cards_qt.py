#!/usr/bin/env python3
"""Exercise actual free-aspect card gestures and fresh-frame input gating offscreen."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='stash-aspect-cards-') as directory:
    folder=Path(directory)
    shutil.copytree(ROOT/'ui',folder/'ui')
    for name in ('Commons','Ui'):
        (folder/name).symlink_to('/usr/share/omarchy/shell/'+name,target_is_directory=True)
    for name in ('runtime','cache','config'):
        (folder/name).mkdir(mode=0o700)
    (folder/'ui/StashPreviewImage.qml').write_text('''import QtQuick
Item {
  property var stash
  property var record
  property string mode:"still"
  property bool active:false
  property string animations:"off"
  property string animationSpeed:"normal"
  property size sourceSize:Qt.size(640,420)
  property bool hasFrame:true
  property int restarts:0
  readonly property bool eligible:active
  readonly property bool hasContent:active && hasFrame
  function contentRect() {return {x:0,y:0,width:width,height:height}}
  function refreshFrame() {return true}
  function restartCapture() {restarts++;hasFrame=false;return restarts}
  function details() {return {hasContent:hasContent,sourceSize:sourceSize,restarts:restarts}}
}
''')
    (folder/'shell.qml').write_text('''pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Window
import Quickshell
import "ui"
ShellRoot {
  id:root
  property int phase:0
  property real originalHeight:0
  property int requestsBeforeCorner:0
  property int requestsBeforeReplacement:0
  property int freeCornerIndex:0
  property var freeCornerOrigin:null
  property real freeCornerWidth:0
  property var first:({id:"first",phase:"stashed",size:[640,420],title:"First",app:"test"})
  property var second:({id:"second",phase:"stashed",size:[800,600],title:"Second",app:"test"})
  QtObject {
    id:fake
    property var saved:({})
    property var pendingCloseIds:({})
    property var states:({})
    property var requests:[]
    property int serial:0
    property int verifications:0
    property bool lifecycleReady:true
    property var previewInteractionRequest:null
    property var previewInteractionPendingRequest:null
    property var previewInteractionStatus:({state:"idle"})
    property string previewInteractionError:""
    property bool pointerKnown:false
    property point pointerPosition:Qt.point(0,0)
    signal pointerClicked(real x,real y,int button)
    signal snapshotChanged()
    function groupClosing(group) {return false}
    function positionPending(key) {return false}
    function recordPreviewPosition(m,key,x,y,width,aspect) {
      var next=Object.assign({},saved);next[key]=aspect>0 ? [x,y,width,aspect] : [x,y,width];saved=next
    }
    function restorePreviewWindow(id,screen) {}
    function openContext(group,screen,point) {}
    function closeGroup(group,screen) {}
    function closeWindows(windows,screen) {}
    function screenMonitor(screen) {return {name:screen,x:0,y:0}}
    function beginPreviewInteraction() {throw new Error("A blocked preview acquired input")}
    function endPreviewInteraction() {}
    function previewGeometryState(id) {return states[id] || null}
    function verifyPreviewGeometry(id) {
      if(states[id]) return
      verifications++
      var next=Object.assign({},states);next[id]={id:id,epoch:++serial,ready:false,pending:true};states=next
    }
    function requestPreviewAspect(id,aspect,axis,settle) {
      requests=requests.concat([{id:id,aspect:aspect,axis:axis,settle:settle}])
      var next=Object.assign({},states);next[id]={epoch:++serial,requestedAspect:aspect,axis:axis,pending:true,ready:false};states=next;return true
    }
    function ready(aspect,size) {
      readyFor("first",aspect,size)
    }
    function readyFor(id,aspect,size) {
      var next=Object.assign({},states),state=Object.assign({},next[id])
      state.ready=true;state.pending=false;state.aspect=aspect;state.size=size;state.captureRevision=state.epoch;next[id]=state;states=next
    }
  }
  Window {
    id:window;width:1280;height:800;visible:true
    StashFloatingPreviews {
      id:previews;stash:fake
      config:({presentation:"previews",animations:"off",floatingPlacement:"free",dragMotion:"direct",floatingPreviewSizing:"free",floatingPreviewUpdate:"still",floatingPreviewTitles:"hidden",floatingPreviewFrame:"hidden",floatingPreviewLock:"unlocked",floatingPreviewInteraction:"on",floatingPreviewActivation:"explicit",floatingPreviewControls:"always"})
      area:({x:0,y:26,width:1280,height:774});coordinateRoot:window.contentItem;screenName:"test";monitor:({x:0,y:0})
      savedPositions:fake.saved;groups:[{key:"window:first",windows:[root.first]}];active:true
    }
  }
  function one() {return previews.cardList()[0]}
  function image() {return one().children.find(function(item) {return item.objectName==="floating-preview-source"})}
  function check(value,message) {if(!value) throw new Error(message)}
  function near(actual,expected,message) {check(Math.abs(actual-expected)<1.1,message+": "+actual+" vs "+expected)}
  function find(item,name) {
    if(item.objectName===name) return item
    for(var i=0;i<item.children.length;i++) {var child=find(item.children[i],name);if(child) return child}
    return null
  }
  function separateHandles() {
    var handles=one().details().resizeRects,corners=handles.slice(0,4),edges=handles.slice(4)
    edges.forEach(function(edge) {corners.forEach(function(corner) {
      var a=edge.rect,b=corner.rect
      check(Math.min(a.x+a.width,b.x+b.width)-Math.max(a.x,b.x)<.001 || Math.min(a.y+a.height,b.y+b.height)-Math.max(a.y,b.y)<.001,
        "An edge handle overlaps a corner on an extreme shape: "+edge.corner+"/"+corner.corner)
    })})
  }
  Timer {
    interval:45;repeat:true;running:true
    onTriggered: {
      try {
        if(root.phase===0) {
          check(one().details().resizeRects.length===8,"Free previews did not expose all corners and sides")
          one().aspectOverride=50;separateHandles()
          one().aspectOverride=.02;one().width=10;separateHandles()
          one().aspectOverride=0;one().width=280
          var config=Object.assign({},previews.config);config.floatingPreviewTitles="shown";previews.config=config
          var close=find(one(),"floating-preview-close"),handles=find(one(),"floating-preview-resize-handles"),controls=find(window.contentItem,"floating-preview-interact").parent
          check(close.visible && close.z>handles.z && close.z<controls.z,"Title close is below resize handles or above interaction controls")
          var closePoint=close.mapToItem(window.contentItem,close.width-5,5)
          check(one().shortcutResizeCorner(closePoint.x,closePoint.y)==="","Super corner overrode the higher title close control")
          var controlPoint=controls.mapToItem(window.contentItem,controls.width/2,controls.height/2)
          check(one().shortcutResizeCorner(controlPoint.x,controlPoint.y)==="","Super corner overrode the interaction controls")
          config=Object.assign({},previews.config);config.floatingPreviewTitles="hidden";previews.config=config
          one().x=200;one().y=180;previews.save(one());originalHeight=one().height
          one().resizing=true;one().resizePressed("right");one().resizeRequested(140,0,"right")
          check(one().sourceResizeActive && image().mode==="live" && previews.config.floatingPreviewUpdate==="still","Responsive side drag did not temporarily update a Snapshot preview")
          near(one().height,originalHeight,"Horizontal edge changed the orthogonal dimension")
          check(one().aspectOverride>2 && fake.requests.length===1 && !fake.requests[0].settle,"Edge drag did not request live source reflow")
          one().resizing=false;one().resizeReleased()
          check(!one().sourceResizeActive && image().mode==="still","Side release did not restore the saved Snapshot capture policy")
          check(fake.requests.length===2 && fake.requests[1].settle,"Edge release did not flush final native readiness")
          check(fake.saved[one().key].length===4,"Custom proportions were not persisted")
        } else if(root.phase===1) {
          check(!one().geometryReady && one().canResize && !one().beginNativeInteraction(),"Pending resize acquired input or locked management")
          fake.ready(2.2,[924,420])
        } else if(root.phase===2) {
          near(one().aspectOverride,2.2,"Client-accepted aspect was ignored")
          near(one().x,200,"Accepted horizontal aspect moved the opposite edge")
          near(one().height,originalHeight,"Accepted horizontal aspect changed its fixed height")
          check(image().restarts===1 && !one().geometryReady,"Native readiness enabled input before a fresh capture")
          image().sourceSize=Qt.size(924,420);image().hasFrame=true
        } else if(root.phase===3) {
          check(one().geometryReady && image().restarts===1,"Matching fresh frame did not unlock input exactly once")
          requestsBeforeCorner=fake.requests.length
          one().resizing=true;one().resizePressed("bottom-right");one().resizeRequested(40,20,"bottom-right")
          check(!one().sourceResizeActive && image().mode==="still","Corner scaling unnecessarily enabled live source reflow")
          one().resizing=false;one().resizeReleased()
          near(one().width/one().height,2.2,"Corner scaling lost custom proportions")
          check(fake.requests.length===requestsBeforeCorner,"Corner scaling resized the underlying application")
          previews.groups=[{key:"window:first",windows:[Object.assign({},root.first,{title:"Refreshed metadata"})]}]
          root.phase=30;return
        } else if(root.phase===30) {
          check(one().geometryReady && image().restarts===1,"A same-identity metadata refresh recreated the committed capture")
          image().sourceSize=Qt.size(640,420)
          root.phase=4;return
        } else if(root.phase===4) {
          near(one().width/one().height,2.2,"Passive source observation overwrote selected proportions")
          check(!one().geometryReady,"A stale wrong-aspect frame enabled native input")
          one().resetProportions()
          check(one().aspectOverride===0 && fake.saved[one().key].length===3,"Reset did not clear custom proportions")
          check(fake.requests[fake.requests.length-1].settle,"Reset did not settle natural source proportions")
          fake.ready(641/421,[641,421])
        } else if(root.phase===5) {
          check(image().restarts===2,"Reset did not request one fresh capture")
          image().sourceSize=Qt.size(641,421);image().hasFrame=true
        } else if(root.phase===6) {
          check(one().geometryReady && one().aspectOverride===0,"Natural reset did not recover input readiness")
          check(root.first.size.join(",")==="640,420","Resize changed the original restore geometry")
          one().resizing=true;one().resizePressed("left");one().resizeRequested(20,0,"left")
          requestsBeforeReplacement=fake.requests.length
          previews.groups=[{key:"window:first",windows:[root.second]}]
        } else if(root.phase===7) {
          check(!one().resizing && one().record.id==="second","Lead replacement did not cancel the old resize gesture")
          check(fake.requests.length===requestsBeforeReplacement,"Old resize release mutated the replacement source")
          fake.ready(3,[1200,400])
        } else if(root.phase===8) {
          check(one().record.id==="second" && one().aspectOverride===0,"A stale source result reshaped the replacement cover")
          previews.groups=[{key:"window:first",windows:[root.first,Object.assign({},root.second,{previewResized:true})]}]
        } else if(root.phase===9) {
          previews.activate(one())
        } else if(root.phase===10) {
          var tile=previews.tileList().find(function(item) {return item.record.id==="second"})
          check(tile && fake.verifications===1 && !!tile.sourceGeometryState,"A resized non-lead tile did not verify native geometry")
          check(!tile.geometryReady && !tile.details().interaction.interactEnabled,"An unverified resized tile enabled input")
          previews.closeExpansion()
          previews.groups=[{key:"window:first",windows:[{id:"restashed",phase:"stashed",size:[800,600],title:"Restashed",app:"test"}]}]
        } else if(root.phase===11) {
          image().sourceSize=Qt.size(800,600);image().hasFrame=true
          one().aspectOverride=2
          check(!one().sourceGeometryState && !one().geometryReady && !one().beginNativeInteraction(),"A new UUID enabled input against the old natural frame before saved-aspect reflow")
          var next=Object.assign({},fake.saved);next[one().key]=[200,180,280,2];fake.saved=next
          previews.applySavedShape(one())
          check(fake.requests[fake.requests.length-1].id==="restashed" && fake.requests[fake.requests.length-1].aspect===2,"Saved custom proportions were not reapplied to the new exact UUID")
          fake.readyFor("restashed",2,[800,400])
        } else if(root.phase===12) {
          check(!one().geometryReady && !image().hasContent,"Re-stash enabled input before replacing its old capture")
          image().sourceSize=Qt.size(800,400);image().hasFrame=true
        } else if(root.phase===13) {
          check(one().record.id==="restashed" && one().geometryReady && one().aspectOverride===2,"Re-stash did not recover saved proportions and fresh-frame readiness")
          var releaseConfig=Object.assign({},previews.config);releaseConfig.floatingPreviewResizeRate="release";previews.config=releaseConfig
          one().resizing=true;one().resizePressed("right");one().resizeRequested(20,0,"right")
          check(one().sourceResizeActive && image().mode==="still","On release forced Snapshot previews into continuous capture")
          one().resizing=false;one().resizeReleased()
          fake.readyFor("restashed",2,[800,400])
        } else if(root.phase===14) {
          image().sourceSize=Qt.size(800,400);image().hasFrame=true
        } else if(root.phase===15) {
          check(one().geometryReady,"Free-corner fixture did not settle")
          var responsive=Object.assign({},previews.config);responsive.floatingPreviewResizeRate="realtime";previews.config=responsive
          one().x=400;one().y=300;one().width=280;one().aspectOverride=2;previews.save(one())
          root.freeCornerOrigin={x:one().x,y:one().y,width:one().width,height:one().height}
          var corner=["top-left","top-right","bottom-left","bottom-right"][root.freeCornerIndex]
          var bounds=one().details().resizeRects.find(function(handle) {return handle.corner===corner}).rect
          var hitX=corner.indexOf("left")>=0 ? bounds.x+1 : bounds.x+bounds.width-1
          var hitY=corner.indexOf("top")>=0 ? bounds.y+1 : bounds.y+bounds.height-1
          check(one().shortcutResizeCorner(hitX,hitY)===corner,"Shortcut corner hit did not match the uncovered resize handle")
          var before=fake.requests.length
          check(one().beginResizeGesture(corner,true),"Super corner did not begin")
          check(one().updateResizeGesture(corner.indexOf("left")>=0 ? -70 : 70,corner.indexOf("top")>=0 ? -20 : 20,corner),"Super corner did not update")
          near(one().width,350,"Super corner ignored horizontal drag")
          near(one().height,160,"Super corner ignored vertical drag")
          check(one().resizeFreeAspect && one().sourceResizeActive && image().mode==="live","Super corner did not use responsive source reflow")
          check(fake.requests.length===before+1 && !fake.requests[before].settle,"Super corner did not draft native shape")
          root.freeCornerWidth=one().width
          check(one().endResizeGesture(),"Super corner did not end")
          check(!one().resizeFreeAspect && !one().resizing && !one().sourceResizeActive && image().mode==="still","Free-corner release retained gesture or temporary capture state")
          check(fake.requests.length===before+2 && fake.requests[before+1].settle,"Free-corner release did not settle source geometry")
          check(!one().geometryReady && fake.saved[one().key].length===4,"Free-corner release enabled stale input or lost custom proportions")
          fake.readyFor("restashed",2.1,[840,400])
        } else if(root.phase===16) {
          var acceptedCorner=["top-left","top-right","bottom-left","bottom-right"][root.freeCornerIndex]
          var origin=root.freeCornerOrigin
          near(one().width,root.freeCornerWidth,"Accepted free-corner geometry lost the latest requested width")
          near(one().width/one().height,2.1,"Accepted free-corner aspect was ignored")
          near(acceptedCorner.indexOf("left")>=0 ? one().x+one().width : one().x,acceptedCorner.indexOf("left")>=0 ? origin.x+origin.width : origin.x,"Accepted free corner moved its opposite horizontal anchor")
          near(acceptedCorner.indexOf("top")>=0 ? one().y+one().height : one().y,acceptedCorner.indexOf("top")>=0 ? origin.y+origin.height : origin.y,"Accepted free corner moved its opposite vertical anchor")
          check(!one().geometryReady && !image().hasFrame,"Accepted free corner did not gate input on a new capture")
          image().sourceSize=Qt.size(840,400);image().hasFrame=true
        } else if(root.phase===17) {
          check(one().geometryReady,"Matching free-corner capture did not enable input")
          root.freeCornerIndex++
          if(root.freeCornerIndex<4) {root.phase=15;return}
          var locked=Object.assign({},previews.config);locked.floatingPreviewLock="locked";previews.config=locked
          check(!one().beginResizeGesture("bottom-right",true) && one().shortcutResizeCorner(0,0)==="","Locked preview accepted a corner gesture")
          console.log("PREVIEW_ASPECT_CARDS_QT_PASS");Qt.quit()
        }
        root.phase++
      } catch(error) {console.error("PREVIEW_ASPECT_CARDS_QT_FAIL: "+error);Qt.exit(1)}
    }
  }
}
''')
    env=dict(os.environ,QT_QPA_PLATFORM='offscreen',QT_QPA_PLATFORMTHEME='generic',QT_QUICK_CONTROLS_STYLE='Basic',QSG_RHI_BACKEND='software',XDG_RUNTIME_DIR=str(folder/'runtime'),XDG_CACHE_HOME=str(folder/'cache'),XDG_CONFIG_HOME=str(folder/'config'),DBUS_SESSION_BUS_ADDRESS='unix:path=/dev/null')
    for key in ('WAYLAND_DISPLAY','DISPLAY','HYPRLAND_INSTANCE_SIGNATURE'):
        env.pop(key,None)
    result=subprocess.run(['qs','-p',str(folder/'shell.qml')],env=env,capture_output=True,text=True,timeout=10)
    output=result.stdout+result.stderr
    assert result.returncode==0 and 'PREVIEW_ASPECT_CARDS_QT_PASS' in output,output
    assert not any(message in output for message in ('Binding loop','ReferenceError','TypeError','Cannot assign','Cannot read')),output
    print('Qt free-aspect previews: side and Super-corner gestures, source reflow, accepted constraints, opposite anchors, fresh capture gate, proportional scaling and reset passed')
