#!/usr/bin/env python3
"""Exercise native shortcut handoff against real Qt preview cards offscreen."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='stash-super-click-qt-') as directory:
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
  property bool available:true
  readonly property bool eligible:active && available
  readonly property bool hasContent:active && available
  function contentRect() {return {x:2,y:3,width:width-4,height:height-6}}
  function refreshFrame() {return true}
  function details() {return {hasContent:hasContent,sourceSize:sourceSize}}
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
  property int serial:0
  property var point:null
  property var first:({id:"first",address:"0x1",pid:11,stableId:"a",tag:"owned-a",phase:"stashed",size:[640,420],title:"First",app:"test"})
  property var second:({id:"second",address:"0x2",pid:12,stableId:"b",tag:"owned-b",phase:"stashed",size:[640,420],title:"Second",app:"test"})
  QtObject {
    id:fake
    property var pendingCloseIds:({})
    property var states:({})
    property var previewInteractionRequest:null
    property var previewInteractionPendingRequest:null
    property var previewInteractionStatus:({state:"idle"})
    property bool lifecycleReady:true
    property string previewInteractionError:""
    property bool pointerKnown:false
    property point pointerPosition:Qt.point(0,0)
    property int begun:0
    property string restored:""
    signal pointerClicked(real x,real y,int button)
    signal snapshotChanged()
    function groupClosing(group) {return false}
    function positionPending(key) {return false}
    function recordPreviewPosition() {}
    function restorePreviewWindow(id,screen) {restored=id}
    function openContext() {}
    function closeGroup() {}
    function closeWindows() {}
    function screenMonitor(screen) {return {name:screen,x:-1600,y:50}}
    function previewGeometryState(id) {return states[id] || null}
    function previewInteractionMatches(id,monitor,key) {return Interaction.matches(previewInteractionRequest,id,monitor,key)}
    function beginPreviewInteraction(record,monitor,key,rect,excludeRects) {
      begun++;previewInteractionRequest={id:record.id,monitor:monitor,viewKey:key,rect:rect,excludeRects:excludeRects}
      previewInteractionStatus={state:"active",id:record.id};return true
    }
    function updatePreviewInteraction() {}
    function endPreviewInteraction() {previewInteractionRequest=null;previewInteractionStatus={state:"idle"}}
  }
  Window {
    id:window;width:1280;height:800;visible:true
    StashFloatingPreviews {
      id:previews;stash:fake
      config:({presentation:"previews",animations:"off",floatingPlacement:"free",dragMotion:"direct",floatingPreviewSizing:"free",floatingPreviewUpdate:"still",floatingPreviewTitles:"hidden",floatingPreviewFrame:"hidden",floatingPreviewLock:"unlocked",floatingPreviewInteraction:"on",floatingPreviewActivation:"explicit",floatingPreviewControls:"always"})
      area:({x:0,y:26,width:1280,height:774});coordinateRoot:window.contentItem;screenName:"test";monitor:({x:-1600,y:50})
      savedPositions:({});groups:[{key:"window:first",windows:[root.first]}];active:true
    }
  }
  function one() {return previews.cardList()[0]}
  function image(card) {return card.children.find(function(child) {return child.objectName==="floating-preview-source"})}
  function check(value,message) {if(!value) throw new Error(message)}
  function setting(key,value) {var next=Object.assign({},previews.config);next[key]=value;previews.config=next}
  function press(card) {
    var rect=card.nativeImageRect();point={x:rect.x+rect.width*.35,y:rect.y+rect.height*.7};serial++
    return previews.handleActivationShortcut(serial,"press",point.x,point.y)
  }
  function release() {return previews.handleActivationShortcut(serial,"release",point.x,point.y)}
  function endInput() {fake.endPreviewInteraction()}
  Timer {
    interval:35;repeat:true;running:true
    onTriggered: {
      try {
        if(root.phase===0) {
          check(one().interactionReady(false),"Initial preview is unavailable")
          check(press(one()) && fake.begun===0,"Shortcut press acquired application input before physical release")
          check(release() && fake.begun===1,"Completed shortcut did not acquire exact preview input")
          check(fake.previewInteractionRequest.id==="first" && !fake.restored,"Shortcut restored or selected another source")
          check(!one().held && !one().resizing,"Shortcut started a miniature gesture")
          check(!release() && fake.begun===1,"Duplicate release rearmed the input owner")
          endInput()
        } else if(root.phase===1) {
          fake.lifecycleReady=false
          check(!press(one()),"Unavailable lifecycle accepted a shortcut press")
          fake.lifecycleReady=true
          check(!release() && fake.begun===1 && !fake.restored,"Rejected press silently activated after lifecycle recovered")
          check(press(one()),"Ready lifecycle rejected shortcut")
          fake.lifecycleReady=false
          check(!release() && fake.begun===1,"Release bypassed newly unavailable lifecycle")
          fake.lifecycleReady=true
          fake.states={first:{ready:false,reason:"configure-pending"}}
          check(!press(one()) && !release(),"Unacknowledged geometry accepted native input")
          fake.states={}
          image(one()).available=false
          check(!press(one()) && !release(),"Missing capture accepted native input")
          image(one()).available=true
        } else if(root.phase===2) {
          check(press(one()),"Cancel fixture failed to arm")
          previews.handleActivationShortcut(serial,"cancel",point.x,point.y)
          check(!release() && fake.begun===1,"Cancelled native gesture activated on a later release")
          check(press(one()),"Wrong-serial fixture failed to arm")
          check(!previews.handleActivationShortcut(serial+1,"release",point.x,point.y),"Unmatched release activated a pending shortcut")
          check(press(one()),"Outside-release fixture failed to arm")
          check(!previews.handleActivationShortcut(serial,"release",-9999,-9999),"Outside release activated a preview")
          check(press(one()),"Transient-block fixture failed to arm")
          previews.blocked=true;previews.blocked=false
          check(!release(),"A temporarily blocked view replayed its old shortcut")
          check(press(one()),"Transient-capture fixture failed to arm")
          previews.captureAllowed=false;previews.captureAllowed=true
          check(!release(),"A temporarily hidden capture replayed its old shortcut")
          check(press(one()),"Policy-toggle fixture failed to arm")
          setting("floatingPreviewInteraction","off");setting("floatingPreviewInteraction","on")
          check(!release(),"A disabled/re-enabled view replayed its old shortcut")
          var exclusion=one().nativeExcludeRects()[0]
          check(!!exclusion,"Control-exclusion fixture has no visible overlay")
          check(!previews.handleActivationShortcut(++serial,"press",exclusion.x+exclusion.width/2,exclusion.y+exclusion.height/2),"Management controls were treated as application content")
          check(press(one()),"Moving-source fixture failed to arm")
          one().x+=10
          check(!release(),"A moved preview accepted an outdated shortcut target")
        } else if(root.phase===3) {
          check(press(one()),"Replacement fixture failed to arm")
          previews.groups=[{key:"window:first",windows:[root.second]}]
        } else if(root.phase===4) {
          check(!release() && fake.begun===1,"Source replacement activated the new source from an old press")
          check(press(one()),"Same-ID identity-change fixture failed to arm")
          previews.groups=[{key:"window:first",windows:[Object.assign({},root.second,{pid:99})]}]
        } else if(root.phase===5) {
          check(!release() && fake.begun===1,"Changed source identity reused a pending press")
          setting("floatingPreviewInteraction","off")
          check(!press(one()) && !release(),"Disabled interaction accepted shortcut input")
          setting("floatingPreviewInteraction","on");setting("floatingPreviewLock","locked")
          check(press(one()) && release() && fake.begun===2,"Locked placement prevented shortcut interaction")
          endInput();setting("floatingPreviewLock","unlocked")
          previews.groups=[{key:"app:test",windows:[root.first,root.second]}]
        } else if(root.phase===6) {
          check(press(one()) && release(),"Group-cover shortcut failed")
          check(fake.begun===2 && !fake.restored,"Group cover guessed a member or restored the group")
        } else if(root.phase===7) {
          check(previews.expanded && previews.tileList().length===2,"Group cover did not open exact-window selection")
          var tile=previews.tileList().find(function(item) {return item.record.id==="second"})
          check(press(tile) && release(),"Exact grouped tile could not use shortcut input")
          check(fake.previewInteractionRequest.id==="second" && fake.begun===3,"Grouped shortcut selected the wrong member")
        } else if(root.phase===8) {
          var replacement=previews.tileList().find(function(item) {return item.record.id==="first"})
          check(press(replacement) && release(),"An inactive exact tile could not replace another active miniature")
          check(fake.previewInteractionRequest.id==="first" && fake.begun===4,"Replacement shortcut selected the active or wrong source")
          endInput()
          var tile=previews.tileList().find(function(item) {return item.record.id==="second"})
          tile.interactionClipRect={x:0,y:0,width:1,height:1}
          check(!press(tile) && !release(),"Clipped group tile accepted invisible input")
          check(!fake.restored,"A rejected shortcut fell through to restore")
          console.log("PREVIEW_SUPER_CLICK_QT_PASS");Qt.quit()
        }
        root.phase++
      } catch(error) {console.error("PREVIEW_SUPER_CLICK_QT_FAIL: "+error);Qt.exit(1)}
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
    try:
        result = subprocess.run(['qs', '-p', str(folder/'shell.qml')], env=env,
                                capture_output=True, text=True, timeout=10)
    except subprocess.TimeoutExpired as error:
        raise AssertionError((error.stdout or b'')+(error.stderr or b'')) from error
    output = result.stdout+result.stderr
    assert result.returncode == 0 and 'PREVIEW_SUPER_CLICK_QT_PASS' in output, output
    assert not any(message in output for message in ('Binding loop', 'ReferenceError', 'TypeError', 'Cannot assign', 'Cannot read')), output
    print('Qt Super-click: exact content/identity/release routing, readiness, cancellation, controls, lock, app selection and clipped-tile guards passed')
