#!/usr/bin/env python3
"""Exercise acknowledged interactive resizing and fresh-frame resumption offscreen."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='stash-interactive-resize-') as directory:
    folder = Path(directory)
    shutil.copytree(ROOT/'ui', folder/'ui')
    for name in ('Commons', 'Ui'):
        (folder/name).symlink_to('/usr/share/omarchy/shell/'+name, target_is_directory=True)
    for name in ('runtime', 'cache', 'config'):
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
  function details() {return {hasContent:hasContent,live:mode==="live",sourceSize:sourceSize}}
}
''')
    (folder/'shell.qml').write_text('''pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Window
import Quickshell
import "ui"
import "ui/PreviewInteraction.js" as Interaction
ShellRoot {
  id:root
  property int phase:0
  property int ticks:0
  property real initialWidth:0
  property real initialHeight:0
  property int shapeCount:0
  property var first:({id:"first",phase:"stashed",size:[640,420],title:"First",app:"test"})
  property var second:({id:"second",phase:"stashed",size:[640,420],title:"Second",app:"test"})
  QtObject {
    id:fake
    property var pendingCloseIds:({})
    property var saved:({"preview:window:first":[200,200,280]})
    property var states:({})
    property var shapes:[]
    property int geometrySerial:0
    property int previewInteractionIntentEpoch:0
    property bool previewInteractiveResizeReady:true
    property var previewInteractionRequest:null
    property var previewInteractionPendingRequest:null
    property bool previewInteractionStopping:false
    property var previewInteractionStatus:({state:"idle"})
    property string previewInteractionError:""
    property bool lifecycleReady:true
    property bool pointerKnown:false
    property point pointerPosition:Qt.point(0,0)
    property int begun:0
    signal pointerClicked(real x,real y,int button)
    signal snapshotChanged()
    function groupClosing(group) {return false}
    function positionPending(key) {return false}
    function recordPreviewPosition(m,key,x,y,width,aspect) {
      var next=Object.assign({},saved);next[key]=[x,y,width,aspect];saved=next
    }
    function restorePreviewWindow() {throw new Error("Pending resize restored the application")}
    function openContext() {}
    function closeGroup() {}
    function closeWindows() {}
    function screenMonitor(screen) {return {name:screen,x:0,y:0}}
    function previewInteractionMatches(id,monitor,key) {return Interaction.matches(previewInteractionRequest,id,monitor,key)}
    function beginPreviewInteraction(record,monitor,key,rect,excludeRects) {
      if(previewInteractionRequest) throw new Error("Input resumed before the old owner acknowledged release")
      previewInteractionIntentEpoch++;begun++
      previewInteractionRequest={id:record.id,monitor:monitor,viewKey:key,rect:rect,excludeRects:excludeRects}
      previewInteractionStatus={state:"active",id:record.id};return true
    }
    function beginPreviewResize() {return ++previewInteractionIntentEpoch}
    function updatePreviewInteraction(id,monitor,key,rect,excludeRects) {
      if(previewInteractionStopping) return
      if(previewInteractionMatches(id,monitor,key)) previewInteractionRequest={id:id,monitor:monitor,viewKey:key,rect:rect,excludeRects:excludeRects}
    }
    function endPreviewInteraction(reason) {
      if(reason!=="preview-resize") previewInteractionIntentEpoch++
      if(!previewInteractionRequest) return
      previewInteractionStopping=true;previewInteractionStatus={state:"stopping",reason:reason}
    }
    function acknowledge() {previewInteractionRequest=null;previewInteractionStopping=false;previewInteractionStatus={state:"ended"}}
    function previewGeometryState(id) {return states[id] || null}
    function requestPreviewAspect(id,aspect,axis,settle) {
      if(previewInteractionRequest || previewInteractionStopping) throw new Error("Source resized before native release acknowledgement")
      shapes=shapes.concat([{id:id,aspect:aspect,axis:axis,settle:settle}])
      var next=Object.assign({},states);next[id]={id:id,epoch:++geometrySerial,requestedAspect:aspect,axis:axis,pending:true,ready:false};states=next;return true
    }
    function ready() {
      var next=Object.assign({},states),state=Object.assign({},next.first)
      state.aspect=state.requestedAspect;state.size=[1000,Math.round(1000/state.aspect)]
      state.ready=true;state.pending=false;state.captureRevision=state.epoch;next.first=state;states=next
    }
  }
  Window {
    id:window;width:1280;height:800;visible:true
    StashFloatingPreviews {
      id:previews;stash:fake
      config:({presentation:"previews",animations:"off",floatingPlacement:"free",dragMotion:"physics",floatingPreviewSizing:"free",floatingPreviewUpdate:"still",floatingPreviewTitles:"hidden",floatingPreviewFrame:"hidden",floatingPreviewLock:"unlocked",floatingPreviewInteraction:"on",floatingPreviewInteractionResize:"on",floatingPreviewActivation:"explicit",floatingPreviewControls:"always"})
      area:({x:0,y:26,width:1280,height:774});coordinateRoot:window.contentItem;screenName:"test";monitor:({x:0,y:0})
      savedPositions:fake.saved;groups:[{key:"window:first",windows:[root.first]}];active:true
    }
  }
  function one() {return previews.cardList()[0]}
  function image() {return one().children.find(function(item) {return item.objectName==="floating-preview-source"})}
  function check(value,message) {if(!value) throw new Error(message)}
  function stopButton() {return window.contentItem.children.find(function(item) {return item.objectName==="floating-preview-interact"})}
  function find(item,name) {
    if(item.objectName===name) return item
    for(var i=0;i<item.children.length;i++) {var found=find(item.children[i],name);if(found) return found}
    return null
  }
  function frame() {var size=fake.states.first.size;image().sourceSize=Qt.size(size[0],size[1]);image().hasFrame=true}
  Timer {
    interval:35;repeat:true;running:true
    onTriggered: {
      try {
        if(root.phase===0) {
          check(one().beginNativeInteraction(),"Initial interaction failed")
          check(one().canResize && one().nativeExcludeRects().length===9,"Active interaction did not reserve all eight resize handles")
          root.initialWidth=one().width
          check(one().beginResizeGesture("right",false),"An active side handle did not start resizing")
          one().updateResizeGesture(50,0,"right");one().updateResizeGesture(140,0,"right")
          one().endResizeGesture()
          check(one().resizing && one().resizeResumePending && fake.previewInteractionStopping,"Early release lost the pending resize")
          check(one().width===root.initialWidth && !fake.shapes.length,"Pointer motion changed geometry before release acknowledgement")
          var stop=find(window.contentItem,"floating-preview-interact")
          check(stop.enabled && stop.iconText==="■","Pending resize did not expose a working Stop control")
          one().activatePrimary()
          fake.acknowledge()
        } else if(root.phase===1) {
          check(!one().resizing && one().resizeResumePending && one().width>root.initialWidth+130,"Acknowledged early release did not apply its final buffered target")
          check(fake.shapes.length===2 && fake.shapes[1].settle && fake.begun===1,"Final target was not settled exactly once without input")
          check(!one().geometryReady && image().mode==="live","Awaiting input resumption lost live capture or geometry gating")
          fake.ready()
        } else if(root.phase===2) {
          check(one().resizeResumePending && fake.begun===1 && !one().geometryReady,"Native size acknowledgement resumed before a fresh image")
          frame()
        } else if(root.phase===3) {
          check(one().interactionActive && !one().resizeResumePending && fake.begun===2,"Fresh matching frame did not resume the same interaction")
          root.shapeCount=fake.shapes.length;root.initialWidth=one().width
          check(one().beginResizeGesture("bottom-right",false),"An active proportional corner did not start resizing")
          one().updateResizeGesture(10,5,"bottom-right");fake.acknowledge()
          // A newer move can beat the zero-delay acknowledgment callback.
          one().updateResizeGesture(50,20,"bottom-right");one().endResizeGesture()
        } else if(root.phase===4) {
          check(one().interactionActive && fake.begun===3 && fake.shapes.length===root.shapeCount,"Proportional corner resize did not resume without changing the source allocation")
          check(Math.abs(one().width-root.initialWidth-50)<1,"A stale pre-ack move rewound the newer pointer position")
          root.initialHeight=one().height
          check(one().beginResizeGesture("bottom",false),"Second side resize did not begin")
          one().updateResizeGesture(0,60,"bottom");fake.acknowledge()
          // Mouse-up can also arrive before that callback, with no newer move.
          one().endResizeGesture()
        } else if(root.phase===5) {
          check(one().resizeResumePending && !one().geometryReady,"Stop fixture did not wait for its source frame")
          check(Math.abs(one().height-root.initialHeight-60)<1,"Mouse-up before the ack callback lost the buffered target")
          var stop=find(window.contentItem,"floating-preview-interact")
          stop.pressed();stop.clicked()
          check(!one().resizeResumePending,"Stop did not cancel pending resumption")
          fake.ready();root.ticks=0
        } else if(root.phase===6) {
          frame()
        } else if(root.phase===7) {
          check(fake.begun===3 && !fake.previewInteractionRequest,"A cancelled resize resumed when its delayed frame arrived")
          check(one().beginNativeInteraction(),"Re-entry after explicit Stop failed")
          root.shapeCount=fake.shapes.length
          check(one().beginResizeGesture("left",false),"Unacknowledged Stop fixture did not begin")
          one().updateResizeGesture(-40,0,"left");one().endResizeGesture()
          var stop=find(window.contentItem,"floating-preview-interact")
          stop.pressed();stop.clicked()
          check(!one().resizing && !one().resizeResumePending && fake.shapes.length===root.shapeCount,"Stop before acknowledgement finalized geometry against the still-owned source")
          fake.acknowledge()
          check(one().beginNativeInteraction(),"Re-entry after unacknowledged Stop failed")
          check(one().beginResizeGesture("left",false),"Option cancellation fixture did not begin")
          one().updateResizeGesture(-35,0,"left");one().endResizeGesture()
          var disabled=Object.assign({},previews.config);disabled.floatingPreviewInteractionResize="off";previews.config=disabled
          check(!one().resizing && !one().resizeResumePending && fake.shapes.length===root.shapeCount,
            "Disabling interaction resizing retained pending input or resized before acknowledgment")
          fake.acknowledge()
          var enabled=Object.assign({},previews.config);enabled.floatingPreviewInteractionResize="on";previews.config=enabled
          check(one().beginNativeInteraction(),"Re-entry after option cancellation failed")
          check(one().beginResizeGesture("left",false),"Replacement fixture did not begin")
          one().updateResizeGesture(-80,0,"left");one().endResizeGesture()
          previews.groups=[{key:"window:first",windows:[root.second]}]
        } else if(root.phase===8) {
          check(!one().resizeResumePending && !one().resizing && fake.shapes.length===root.shapeCount,"Source replacement mutated or retained the old resize")
          fake.acknowledge()
        } else if(root.phase===9) {
          check(one().record.id==="second" && fake.begun===6 && !fake.previewInteractionRequest,"Source replacement automatically acquired another window")
          console.log("PREVIEW_INTERACTIVE_RESIZE_QT_PASS");Qt.quit()
        }
        root.phase++
      } catch(error) {console.error("PREVIEW_INTERACTIVE_RESIZE_QT_FAIL: "+error);Qt.exit(1)}
    }
  }
}
''')
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen', QT_QPA_PLATFORMTHEME='generic',
               QT_QUICK_CONTROLS_STYLE='Basic', QSG_RHI_BACKEND='software',
               XDG_RUNTIME_DIR=str(folder/'runtime'), XDG_CACHE_HOME=str(folder/'cache'),
               XDG_CONFIG_HOME=str(folder/'config'), DBUS_SESSION_BUS_ADDRESS='unix:path=/dev/null')
    for key in ('WAYLAND_DISPLAY', 'DISPLAY', 'HYPRLAND_INSTANCE_SIGNATURE'):
        env.pop(key, None)
    result = subprocess.run(['qs', '-p', str(folder/'shell.qml')], env=env,
                            capture_output=True, text=True, timeout=10)
    output = result.stdout+result.stderr
    assert result.returncode == 0 and 'PREVIEW_INTERACTIVE_RESIZE_QT_PASS' in output, output
    assert not any(value in output for value in ('Binding loop', 'ReferenceError', 'TypeError', 'Cannot assign', 'Cannot read')), output
    print('Qt interactive resize: protected handles, acknowledged latest-target buffering, early release, fresh-frame resume, proportional corners, Stop and exact-source cancellation passed')
