#!/usr/bin/env python3
"""Exercise real dock timers when Qt hover disagrees with compositor coordinates."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='stash-floating-dismissal-') as directory:
    folder = Path(directory)
    shutil.copytree(ROOT/'ui', folder/'ui')
    for name in ('Commons', 'Ui'):
        (folder/name).symlink_to('/usr/share/omarchy/shell/'+name, target_is_directory=True)
    for name in ('runtime', 'cache', 'config'):
        (folder/name).mkdir(mode=0o700)
    (folder/'shell.qml').write_text('''import QtQuick
import QtQuick.Window
import QtTest
import Quickshell
import "ui"

ShellRoot {
  id:root
  property int phase:0
  property int ticks:0
  property real since:0
  property var records:[{id:"one",app:"test",title:"One"},{id:"two",app:"test",title:"Two"}]
  QtObject {
    id:fake
    property bool pointerKnown:true
    property point pointerPosition:Qt.point(-826,374)
    property bool contextOpen:false
    property string dialogKind:""
    signal pointerClicked(real x,real y,int button)
    function groupClosing(group) {return false}
    function recordPosition(m,key,x,y) {}
    function selectGroup(group,screen) {throw new Error("Pointer tracking restored a window")}
  }
  QtObject {
    id:preview
    property bool fromFloating:true
    property bool hovered:false
    property bool previewEnabled:false
    property bool shown:false
    function containsPoint(x,y) {return shown && x>=600 && x<=700 && y>=100 && y<=200}
    function request() {}
    function dismiss() {shown=false}
  }
  Window {
    id:window
    width:800; height:600; visible:true
    TestCase {id:mouse;name:"DockPointer";when:false}
    StashDragWorld {id:world;area:({x:0,y:0,width:800,height:600});physicsEnabled:false;snapEdges:false;animations:"off"}
    StashFloatingDock {
      id:dock
      anchors.fill:parent
      stash:fake;preview:preview;dragWorld:world;hostWindow:window
      monitor:({name:"test",x:-1200,y:100,width:800,height:600,scale:1,reserved:[0,0,0,0]})
      screenName:"test";active:true;savedPosition:[350,250]
      config:({animations:"off",floatingPlacement:"free",floatingDirection:"horizontal",sizePreset:"100",
               iconFrame:"shown",iconShape:"circle",dockFrame:"shown",dockCorners:"custom",dockCornerRadius:32})
      windows:root.records
      groups:root.records.map(function(r) {return {key:"window:"+r.id,title:r.title,app:r.app,windows:[r]}})
    }
  }
  function check(value,message) {if(!value) throw new Error(message)}
  function point(x,y) {fake.pointerPosition=Qt.point(dock.monitor.x+x,dock.monitor.y+y)}
  function inside() {point(dock.anchorX+24,dock.anchorY+24)}
  function open() {inside();dock.unfoldAt(dock.anchorX+24,dock.anchorY+24)}
  Timer {
    interval:20;repeat:true;running:true
    onTriggered: {
      try {
        root.ticks++
        check(root.ticks<240,"Dock pointer regression timed out")
        if(root.phase===0) {if(dock.animating) return;root.open();root.phase=1;return}
        if(root.phase===1) {
          if(dock.animating || !dock.open) return
          mouse.mouseMove(window.contentItem,10,10)
          root.point(10,10);root.phase=2;return
        }
        if(root.phase===2) {
          check(dock.details().dismissal.qtHovered,"Test did not create stale whole-canvas Qt hover")
          check(!dock.pointerInside && dock.details().dismissal.pending,"Physical leave did not arm grace despite stale Qt hover")
          root.since=Date.now();root.phase=3;return
        }
        if(root.phase===3) {
          if(Date.now()-root.since<180) return
          check(dock.open,"Physical leave folded before grace expired")
          root.inside();root.phase=4;root.since=Date.now();return
        }
        if(root.phase===4) {
          check(dock.open && !dock.details().dismissal.pending,"Re-entry failed to cancel pending fold")
          if(Date.now()-root.since<850) return
          preview.shown=true;root.point(650,150);root.phase=5;return
        }
        if(root.phase===5) {
          check(dock.pointerInside && !dock.details().dismissal.pending,"Physical preview transfer did not retain dock")
          preview.hovered=true;root.point(10,10);root.phase=6;return
        }
        if(root.phase===6) {
          check(!dock.pointerInside && dock.details().dismissal.pending,"Stale preview hover prevented physical leave")
          root.since=Date.now();root.phase=7;return
        }
        if(root.phase===7) {
          if(dock.open) {check(Date.now()-root.since<1100,"Grace failed to fold the dock");return}
          check(dock.lastDismissal==="pointer-leave","Fold used the wrong dismissal action")
          preview.shown=false;preview.hovered=false;root.open();root.phase=8;return
        }
        if(root.phase===8) {
          if(dock.animating) return
          var panel=dock.details().panel
          check(!dock.panelContains(panel.x+1,panel.y+1),"Rounded corner counted as visible dock")
          fake.pointerClicked(dock.monitor.x+10,dock.monitor.y+10,272)
          check(!dock.open && dock.lastDismissal==="outside-click","Outside click did not fold immediately")
          console.log("FLOATING_DISMISSAL_QT_PASS");Qt.quit()
        }
      } catch(error) {console.error("FLOATING_DISMISSAL_QT_FAIL: "+error);Qt.exit(1)}
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
    assert result.returncode == 0 and 'FLOATING_DISMISSAL_QT_PASS' in output, output
    assert not any(message in output for message in ('Binding loop', 'ReferenceError', 'TypeError', 'Cannot assign', 'Cannot read')), output
    print('Qt dock dismissal: stale Qt hover, physical preview transfer, negative monitor offsets, grace/re-entry and immediate outside click passed')
