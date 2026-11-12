#!/usr/bin/env python3
"""Exercise the actual preview controls/mapping with capture and input stubbed."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='stash-interactive-cards-') as directory:
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
  readonly property bool eligible:active
  readonly property bool hasContent:active
  function contentRect() {return {x:2,y:3,width:width-4,height:height-6}}
  function details() {return {captureActive:active,live:active && mode==="live",hasContent:hasContent,sourceSize:sourceSize}}
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
  property var first:({id:"first",phase:"stashed",size:[640,420],title:"First",app:"test"})
  property var second:({id:"second",phase:"stashed",size:[640,420],title:"Second",app:"test"})
  QtObject {
    id:fake
    property var pendingCloseIds:({})
    property var saved:({})
    property var previewInteractionRequest:null
    property var previewInteractionPendingRequest:null
    property bool previewInteractionStopping:false
    property bool deferStop:false
    property var previewInteractionStatus:({state:"idle"})
    property string previewInteractionError:""
    property bool pointerKnown:true
    property point pointerPosition:Qt.point(-1500,200)
    property int begun:0
    property string ended:""
    property string restored:""
    property int contextOpened:0
    signal pointerClicked(real x,real y,int button)
    signal snapshotChanged()
    function groupClosing(group) {return false}
    function positionPending(key) {return false}
    function recordPreviewPosition(m,key,x,y,width) {}
    function restorePreviewWindow(id,screen) {restored=id}
    function openContext(group,screen,point) {contextOpened++}
    function closeGroup(group,screen) {}
    function closeWindows(windows,screen) {}
    function screenMonitor(screen) {return {name:screen,x:-1600,y:50}}
    function previewInteractionMatches(id,monitor,key) {return Interaction.matches(previewInteractionRequest,id,monitor,key)}
    function beginPreviewInteraction(record,monitor,key,rect,excludeRects) {
      begun++;ended=""
      previewInteractionRequest={id:record.id,monitor:monitor,viewKey:key,rect:rect,excludeRects:excludeRects}
      previewInteractionStatus={state:"active",id:record.id}
      pointerPosition=Qt.point(rect.x+rect.width/2,rect.y+rect.height/2)
      return true
    }
    function updatePreviewInteraction(id,monitor,key,rect,excludeRects) {
      if(previewInteractionMatches(id,monitor,key)) previewInteractionRequest={id:id,monitor:monitor,viewKey:key,rect:rect,excludeRects:excludeRects}
    }
    function endPreviewInteraction(reason) {
      ended=reason
      if(deferStop && previewInteractionRequest) {previewInteractionStopping=true;previewInteractionStatus={state:"stopping",reason:reason}}
      else acknowledgeStop()
    }
    function acknowledgeStop() {previewInteractionRequest=null;previewInteractionStopping=false;previewInteractionStatus={state:"ended",reason:ended}}
  }
  Window {
    id:window;width:1280;height:800;visible:true
    StashFloatingPreviews {
      id:previews;stash:fake
      config:({presentation:"previews",animations:"off",floatingPlacement:"free",dragMotion:"physics",floatingPreviewSizing:"free",floatingPreviewScale:"100",floatingPreviewUpdate:"still",floatingPreviewTitles:"hidden",floatingPreviewFrame:"hidden",floatingPreviewLock:"unlocked",floatingPreviewInteraction:"on",floatingPreviewActivation:"explicit",floatingPreviewKeyboard:"mouse",floatingPreviewInteractionFps:"60",floatingPreviewControls:"always"})
      area:({x:0,y:26,width:1280,height:774})
      coordinateRoot:window.contentItem;screenName:"test";monitor:({x:-1600,y:50})
      savedPositions:fake.saved;groups:[{key:"window:first",windows:[root.first]}];active:true
    }
  }
  function check(value,message) {if(!value) throw new Error(message)}
  function near(actual,expected,message) {check(Math.abs(actual-expected)<.1,message+": "+actual+" vs "+expected)}
  function one() {return previews.cardList()[0]}
  function image(card) {return card.children.find(function(item) {return item.objectName==="floating-preview-source"})}
  function find(item,name) {
    if(item.objectName===name) return item
    for(var index=0;index<item.children.length;index++) {var child=find(item.children[index],name);if(child) return child}
    return null
  }
  function setting(key,value) {var next=Object.assign({},previews.config);next[key]=value;previews.config=next}
  Timer {
    interval:35;repeat:true;running:true
    onTriggered: {
      try {
        if(root.phase===0) {
          check(one() && one().interactionEnabled,"Interactive card was not constructed")
          check(!one().titleVisible && !one().frameVisible,"Interaction added permanent title/frame chrome")
          one().activatePrimary()
          check(fake.restored==="first" && fake.begun===0,"Explicit default stopped ordinary click-to-restore")
          fake.restored="";setting("floatingPreviewActivation","click")
          one().activatePrimary()
          check(fake.restored==="" && fake.begun===1,"First-click activation was forwarded as restore")
        } else if(root.phase===1) {
          check(one().interactionActive && !one().canMove && !one().canResize,"Active application content remained a miniature drag/resize target")
          check(image(one()).mode==="live" && previews.config.floatingPreviewUpdate==="still","Active interaction did not force live capture independently")
          check(previews.details().world.bodies[0].frozen,"Active miniature physics was not frozen")
          var request=fake.previewInteractionRequest,details=one().details()
          near(request.rect.x,-1600+one().x+2,"Source mapping ignored negative monitor origin or actual captured inset")
          near(request.rect.y,50+one().y+3,"Source mapping ignored actual captured content origin")
          near(request.rect.width,one().width-4,"Source mapping used card width instead of actual image width")
          check(details.interaction.controlsVisible && request.excludeRects.length===1,"Active controls were not excluded from application input")
          check(details.interaction.controlsOutside && previews.inputRegions.length===2,"Active controls did not detach into their own bounded input region")
          check(!Interaction.intersection(request.rect,request.excludeRects[0]),"Detached controls still obstruct the interactive application image")
          check(request.excludeRects[0].x>=request.rect.x && request.excludeRects[0].width>0,"Control exclusion escaped the full image transform")
          var count=fake.begun;one().activatePrimary();check(fake.begun===count,"Clicking active content rearmed the native owner")
          image(one()).sourceSize=Qt.size(1200,600)
        } else if(root.phase===2) {
          near(one().width/one().height,640/420,"A source aspect update moved the active miniature beneath the pointer")
          var manage=find(window.contentItem,"floating-preview-manage")
          manage.pressed();fake.endPreviewInteraction("outside-click");manage.clicked()
          check(fake.contextOpened===0,"Manage changed into Menu after native input ended before the Qt click")
        } else if(root.phase===3) {
          check(!one().interactionRequested && one().canMove && one().canResize,"Leaving interaction did not recover miniature management")
          check(!previews.details().world.bodies[0].frozen,"Leaving interaction retained frozen physics")
          near(one().width/one().height,2,"Leaving interaction did not apply deferred source proportions")
          check(image(one()).mode==="still","Leaving interaction did not resume the saved capture policy")
          check(root.first.size.join(",")==="640,420","Interaction rewrote the original window dimensions")
          check(one().beginNativeInteraction(),"Explicit re-entry failed")
          var stop=find(window.contentItem,"floating-preview-interact"),begun=fake.begun
          stop.pressed();fake.endPreviewInteraction("outside-click");stop.clicked()
          check(fake.begun===begun && !fake.previewInteractionRequest,"Stop rearmed interaction after native teardown raced the Qt click")
          check(one().beginNativeInteraction(),"Explicit activation after a stopped click failed")
          fake.deferStop=true;one().endNativeInteraction("manage")
          check(one().interactionBusy && !one().canMove && !one().canResize,"Manage enabled miniature gestures before native release acknowledgement")
          previews.groups=[{key:"window:first",windows:[root.second]}]
        } else if(root.phase===4) {
          check(fake.previewInteractionRequest && one().interactionBusy && !one().canMove,"Source replacement unlocked a view with native input still attached")
          check(one().displayRecord.id==="first" && image(one()).record.id==="first","Source replacement displayed another app before releasing the old app's input")
          check(previews.details().world.bodies[0].frozen,"Stopping let the active image move beneath the native hit rectangle")
          fake.acknowledgeStop();fake.deferStop=false
        } else if(root.phase===5) {
          check(!fake.previewInteractionRequest && one().displayRecord.id==="second","Native acknowledgement did not release the old displayed source")
          previews.groups=[{key:"app:test",windows:[root.first,root.second]}]
        } else if(root.phase===6) {
          check(!one().beginNativeInteraction(),"A multi-window cover accepted ambiguous application input")
          one().activatePrimary()
        } else if(root.phase===7) {
          check(previews.expanded && previews.tileList().length===2,"Interactive app group did not expand to exact windows")
          var tile=previews.tileList().find(function(item) {return item.record.id==="second"})
          check(tile.beginNativeInteraction(),"An exact grouped window could not enter interaction")
          check(fake.previewInteractionRequest.id==="second","Grouped interaction selected the wrong source")
          tile.interactionClipRect={x:0,y:0,width:1,height:1}
        } else if(root.phase===8) {
          check(!fake.previewInteractionRequest,"Clipping an active grouped window retained off-viewport input routing")
          var tile=previews.tileList().find(function(item) {return item.record.id==="second"})
          check(!tile.interactionFullyVisible && !tile.beginNativeInteraction(),"A clipped grouped window could acquire hidden input")
          previews.closeExpansion();setting("floatingPreviewInteraction","off")
        } else if(root.phase===9) {
          check(!one().interactionEnabled && !one().details().interaction.controlsVisible,"Disabled interaction left controls on ordinary previews")
          console.log("PREVIEW_INTERACTION_CARDS_QT_PASS");Qt.quit()
        }
        root.phase++
      } catch(error) {console.error("PREVIEW_INTERACTION_CARDS_QT_FAIL: "+error);Qt.exit(1)}
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
    assert result.returncode == 0 and 'PREVIEW_INTERACTION_CARDS_QT_PASS' in output, output
    assert not any(message in output for message in ('Binding loop', 'ReferenceError', 'TypeError', 'Cannot assign', 'Cannot read')), output
    print('Qt interactive cards: explicit/click activation, real image mapping, controls, source identity, independent live capture, frozen physics, grouped input and viewport cleanup passed')
