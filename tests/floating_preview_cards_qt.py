#!/usr/bin/env python3
"""Exercise persistent card lifecycle and geometry on a private offscreen Qt.

Capture is stubbed here; native suites verify actual pixels and input routing.
No desktop session, compositor IPC or input device is used by this suite.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='stash-preview-cards-') as directory:
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
  function details() {return {captureActive:active,live:active && mode==="live",recordId:record ? record.id : ""}}
}
''')
    (folder/'shell.qml').write_text('''import QtQuick
import QtQuick.Window
import Quickshell
import "ui"

ShellRoot {
  id:root
  property int phase:0
  property int ticks:0
  property real freeWidth:0
  property var first:({id:"first",size:[640,420],title:"<img src='https://invalid.test/title'>",app:"test"})
  property var second:({id:"second",size:[640,420],title:"Second",app:"test"})
  property var third:({id:"third",size:[640,420],title:"Third",app:"test"})
  QtObject {
    id:fake
    property var pendingCloseIds:({})
    property var saved:({})
    property var writes:[]
    property string restored:""
    signal pointerClicked(real x,real y,int button)
    signal snapshotChanged()
    function groupClosing(group) {return false}
    function positionPending(key) {return false}
    function recordPreviewPosition(m,key,x,y,width) {
      var next=Object.assign({},saved);next[key]=[x,y,width];saved=next
      writes=writes.concat([{key:key,x:x,y:y,width:width}])
    }
    function restorePreviewWindow(id,screen) {restored=id}
    function openContext(group,screen,point) {}
    function closeGroup(group,screen) {}
    function closeWindows(windows,screen) {}
  }
  Window {
    id:window
    width:1280;height:800;visible:true
    StashFloatingPreviews {
      id:previews
      stash:fake
      config:({animations:"off",floatingPlacement:"free",dragMotion:"direct",floatingPreviewSizing:"free",floatingPreviewScale:"100",floatingPreviewUpdate:"hover",floatingPreviewTitles:"hidden",floatingPreviewFrame:"hidden",floatingPreviewLock:"unlocked"})
      area:({x:0,y:26,width:1280,height:774})
      coordinateRoot:window.contentItem;screenName:"test";monitor:({x:0,y:0})
      savedPositions:fake.saved
      groups:[{key:"window:first",windows:[root.first]}]
      active:true
    }
  }
  function check(value,message) {if(!value) throw new Error(message)}
  function near(actual,expected,message) {check(Math.abs(actual-expected)<.01,message+": "+actual+" != "+expected)}
  function setting(key,value) {var next=Object.assign({},previews.config);next[key]=value;previews.config=next}
  function one() {return previews.cardForKey("preview:window:first")}
  Timer {
    interval:30;repeat:true;running:true
    onTriggered: {
      try {
        check(++root.ticks<100,"Persistent cards failed to settle")
        if(root.phase===0) {
          check(previews.details().cards.length===1,"Initial card was not constructed")
          check(!one().titleVisible && !one().frameVisible,"Default card has added chrome")
          near(one().width,280,"Default preview width")
          near(one().width/one().height,640/420,"Borderless image changed source aspect")
          check(previews.inputRegions.length===1,"Initial input region missing")
          one().x=400;one().y=250;previews.save(one())
          one().resizing=true;one().resizePressed("bottom-right")
          one().resizeRequested(90,60,"bottom-right")
          one().resizing=false;one().resizeReleased()
          root.freeWidth=one().width
          check(root.freeWidth>360,"Native resize signal did not grow the card")
          near(one().width/one().height,640/420,"Resize distorted the source")
          check(fake.writes.length>0 && fake.writes[fake.writes.length-1].width===Math.round(root.freeWidth),"Resize did not persist its width")
          root.phase=1;return
        }
        if(root.phase===1) {
          near(one().width,Math.round(root.freeWidth),"Preference acknowledgement lost the resized width")
          setting("floatingPreviewSizing","preset");setting("floatingPreviewScale","150")
          root.phase=2;return
        }
        if(root.phase===2) {
          near(one().width,420,"Preset resize did not reach the actual card")
          one().x=450;previews.save(one())
          near(fake.saved[one().key][2],Math.round(root.freeWidth),"Moving a preset card overwrote free dimensions")
          setting("floatingPreviewSizing","free");root.phase=3;return
        }
        if(root.phase===3) {
          near(one().width,Math.round(root.freeWidth),"Free sizing did not recover its saved width")
          setting("floatingPreviewLock","locked");root.phase=4;return
        }
        if(root.phase===4) {
          check(!one().canMove && !one().canResize,"Locked card remained movable/resizable")
          setting("floatingPreviewLock","unlocked")
          previews.groups=[{key:"window:first",windows:[root.second,root.first]}]
          root.phase=5;return
        }
        if(root.phase===5) {
          previews.activate(one());root.phase=6;return
        }
        if(root.phase===6) {
          check(previews.expanded && previews.details().tiles.length===2,"Group did not show every window together")
          check(previews.details().tiles.every(function(tile) {return tile.image.captureActive}),"Group omitted visible capture streams")
          previews.selectTile(1);previews.restoreSelected()
          check(fake.restored==="first" && !previews.expanded,"Keyboard selection restored the wrong window or kept expansion open")
          previews.activate(one());previews.groups=[{key:"window:first",windows:[root.first]}]
          root.phase=7;return
        }
        if(root.phase===7) {
          check(!previews.expanded && previews.expandedKey==="","Single-window group kept a stale expansion key")
          previews.groups=[{key:"window:first",windows:[root.third,root.first]}]
          root.phase=8;return
        }
        if(root.phase===8) {
          check(!previews.expanded,"A new grouped window reopened a dismissed expansion")
          previews.captureAllowed=false;root.phase=9;return
        }
        if(root.phase===9) {
          check(!previews.visible && previews.inputRegions.length===0,"Capture suspension left an invisible input region")
          check(previews.cardList().every(function(card) {return !card.details().image.captureActive}),"Suspension retained capture streams")
          previews.active=false;root.phase=10;return
        }
        if(root.phase===10) {
          check(!previews.present && previews.details().world.bodies.length===0,"Leaving preview mode retained delegates or simulation")
          console.log("FLOATING_PREVIEW_CARDS_QT_PASS");Qt.quit()
        }
      } catch(error) {console.error("FLOATING_PREVIEW_CARDS_QT_FAIL: "+error);Qt.exit(1)}
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
                            capture_output=True, text=True, timeout=12)
    output = result.stdout+result.stderr
    assert result.returncode == 0 and 'FLOATING_PREVIEW_CARDS_QT_PASS' in output, output
    assert not any(message in output for message in ('Binding loop', 'ReferenceError', 'TypeError', 'Cannot assign', 'Cannot read')), output
    print('Qt floating previews: card construction, borderless aspect, resize acknowledgement, independent sizing, lock, grouped exact selection and capture/mode cleanup passed')
