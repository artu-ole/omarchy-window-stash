#!/usr/bin/env python3
"""Exercise actual static-dock drag state and acknowledgement races offscreen."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='stash-static-position-') as directory:
    folder = Path(directory)
    ui = folder/'ui'
    ui.mkdir()
    for name in ('StashStaticDockPosition.qml', 'Model.js'):
        shutil.copy2(ROOT/'ui'/name, ui/name)
    for name in ('runtime', 'cache', 'config'):
        (folder/name).mkdir(mode=0o700)
    (folder/'shell.qml').write_text('''import QtQuick
import Quickshell
import "ui"
import "ui/Model.js" as Model

ShellRoot {
  id:root
  property int phase:0
  property int ticks:0
  property int expectedResize:0
  property int expectedLocked:0
  property int expectedBottom:0
  property int expectedLeft:0
  property int expectedLayout:0
  property int expectedAnonymous:0
  component Fixture:Item {
    id:fixture
    property bool unlocked:true
    property string side:"bottom"
    property int layoutEpoch:0
    property real requestedLength:180
    property var area:({x:12,y:26,width:640,height:454})
    property var saved:({})
    property var output:({name:"DISPLAY-A",make:"A",model:"panel",serial:"001",description:"A"})
    property string outputKey:Model.staticDockMonitorKey(output)
    property var events:[]
    property int cancellations:0
    property alias placement:positioner
    readonly property bool vertical:side==="left" || side==="right"
    readonly property var geometry:Model.staticDockRect(area,side,vertical ? 50 : requestedLength,
      vertical ? requestedLength : 50,8,16)
    Item {
      id:dock
      width:fixture.geometry.width; height:fixture.geometry.height
      x:Model.staticDockRect(fixture.area,fixture.side,width,height,8,16,positioner.position).x
      y:Model.staticDockRect(fixture.area,fixture.side,width,height,8,16,positioner.position).y
    }
    StashStaticDockPosition {
      id:positioner
      dock:dock; area:fixture.area; monitor:fixture.output; monitorKey:fixture.outputKey
      side:fixture.side; savedPositions:fixture.saved; gap:8; longMargin:16
      enabled:fixture.unlocked
      layoutKey:JSON.stringify([fixture.side,fixture.outputKey,fixture.layoutEpoch])
      onCanceled:fixture.cancellations++
      onCommitted:function(owner,key,point) {
        fixture.events=fixture.events.concat([{monitor:owner.name,key:key,point:point}])
      }
    }
  }
  Fixture { id:resizeCase }
  Fixture { id:ackCase }
  Fixture { id:lockCase }
  Fixture { id:ownerCase }
  Fixture { id:anonymousCase; output:({name:"HEADLESS-1",make:"",model:"",serial:"",description:""}) }
  function check(value,message) { if (!value) throw new Error(message) }
  function near(actual,expected,message) {
    check(Math.abs(actual-expected)<.000001,message+": "+actual+" != "+expected)
  }
  function saved(key,point) { var value={}; value[key]=[point,0]; return value }
  Timer {
    interval:20; repeat:true; running:true
    onTriggered: {
      try {
        root.ticks++
        check(root.ticks<40,"Static dock state did not settle")
        if (root.phase===0) {
          check(resizeCase.placement.movable,"Initial dock was not movable")
          resizeCase.placement.press(); resizeCase.placement.move(80,0)
          check(resizeCase.placement.held && resizeCase.placement.changed,"Resize case did not start a drag")
          root.expectedResize=Math.round(resizeCase.placement.position*10000)
          resizeCase.requestedLength=10000
          root.phase=1; return
        }
        if (root.phase===1) {
          check(!resizeCase.placement.movable,"Overflow retained long-axis travel")
          check(!resizeCase.placement.held && !resizeCase.placement.dragging,"Filling the edge stranded a held drag")
          check(resizeCase.cancellations===1 && resizeCase.events.length===1,"Resize did not cancel and save exactly once")
          check(resizeCase.events[0].point===root.expectedResize,"Resize changed the saved normalized position")
          resizeCase.placement.release(); resizeCase.placement.cancel()
          check(resizeCase.events.length===1,"A late release duplicated a canceled save")

          ackCase.placement.press(); ackCase.placement.move(70,0); ackCase.placement.release()
          check(ackCase.events.length===1,"First acknowledged drag did not save")
          var point=ackCase.events[0].point,key=ackCase.events[0].key
          ackCase.placement.press()
          ackCase.saved=root.saved(key,point)
          check(ackCase.placement.held && ackCase.placement.drafts[key]!==undefined,"An acknowledgement discarded a held draft")
          ackCase.placement.release()
          root.phase=2; return
        }
        if (root.phase===2) {
          check(ackCase.events.length===1,"A second press without movement saved again")
          check(Object.keys(ackCase.placement.drafts).length===0,"An acknowledgement received while held stayed latched after release")
          ackCase.saved=root.saved("dock:static:bottom",2000)
          root.phase=3; return
        }
        if (root.phase===3) {
          near(ackCase.placement.position,.2,"A stale draft masked a later external saved position")
          lockCase.placement.press(); lockCase.placement.move(-80,0)
          root.expectedLocked=Math.round(lockCase.placement.position*10000)
          lockCase.unlocked=false
          root.phase=4; return
        }
        if (root.phase===4) {
          check(!lockCase.placement.held && lockCase.cancellations===1 && lockCase.events.length===1,"Locking did not end its drag exactly once")
          check(lockCase.events[0].key==="dock:static:bottom" && lockCase.events[0].monitor==="DISPLAY-A"
            && lockCase.events[0].point===root.expectedLocked,"Lock cancellation saved the wrong owner, edge or fraction")
          lockCase.placement.move(500,0); lockCase.placement.press(); lockCase.placement.release()
          check(!lockCase.placement.held && lockCase.events.length===1,"A locked dock accepted another drag")

          ownerCase.placement.press(); ownerCase.placement.move(60,0)
          root.expectedBottom=Math.round(ownerCase.placement.position*10000)
          ownerCase.side="left"
          root.phase=5; return
        }
        if (root.phase===5) {
          check(ownerCase.events.length===1 && ownerCase.events[0].key==="dock:static:bottom"
            && ownerCase.events[0].point===root.expectedBottom,"Changing sides saved against the new edge")
          ownerCase.saved=root.saved("dock:static:bottom",root.expectedBottom)
          ownerCase.placement.press(); ownerCase.placement.move(0,50)
          root.expectedLeft=Math.round(ownerCase.placement.position*10000)
          ownerCase.output=({name:"DISPLAY-B",make:"B",model:"panel",serial:"002",description:"B"})
          root.phase=6; return
        }
        if (root.phase===6) {
          check(!ownerCase.placement.held && ownerCase.events.length===2 && ownerCase.cancellations===2,"Changing monitors did not end one held gesture")
          var event=ownerCase.events[1]
          check(event.monitor==="DISPLAY-A" && event.key==="dock:static:left" && event.point===root.expectedLeft,
            "Changing monitors saved against the new monitor instead of the press snapshot")
          check(Object.keys(ownerCase.placement.drafts).length===0,"Monitor change retained another monitor's draft")
          ownerCase.saved=root.saved("dock:static:left",8000)
          root.phase=7; return
        }
        if (root.phase===7) {
          near(ownerCase.placement.position,.8,"New monitor did not apply its own saved position")
          ownerCase.placement.press(); ownerCase.placement.move(0,-40)
          root.expectedLayout=Math.round(ownerCase.placement.position*10000)
          ownerCase.layoutEpoch++
          root.phase=8; return
        }
        if (root.phase===8) {
          check(!ownerCase.placement.held && ownerCase.events.length===3 && ownerCase.cancellations===3,"Layout change did not cancel exactly once")
          check(ownerCase.events[2].monitor==="DISPLAY-B" && ownerCase.events[2].key==="dock:static:left"
            && ownerCase.events[2].point===root.expectedLayout,"Layout cancellation lost the current owner snapshot")
          check(anonymousCase.outputKey==="output:HEADLESS-1","Anonymous output did not use its named static key")
          anonymousCase.placement.press(); anonymousCase.placement.move(60,0)
          root.expectedAnonymous=Math.round(anonymousCase.placement.position*10000)
          anonymousCase.output=({name:"HEADLESS-2",make:"",model:"",serial:"",description:""})
          root.phase=9; return
        }
        check(anonymousCase.outputKey==="output:HEADLESS-2","Anonymous monitor switch retained its previous static key")
        check(!anonymousCase.placement.held && anonymousCase.events.length===1 && anonymousCase.cancellations===1,
          "Switching anonymous outputs did not cancel one held gesture")
        check(anonymousCase.events[0].monitor==="HEADLESS-1" && anonymousCase.events[0].key==="dock:static:bottom"
          && anonymousCase.events[0].point===root.expectedAnonymous,"Anonymous output switch saved to the wrong owner")
        check(Object.keys(anonymousCase.placement.drafts).length===0,"Anonymous output switch retained the previous output's draft")
        console.log("STATIC_DOCK_POSITION_PASS")
        Qt.quit()
      } catch (error) { console.error("STATIC_DOCK_POSITION_FAIL: "+error); Qt.exit(1) }
    }
  }
}
''')
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen', QT_QPA_PLATFORMTHEME='generic',
               QT_QUICK_CONTROLS_STYLE='Basic', QSG_RHI_BACKEND='software',
               XDG_RUNTIME_DIR=str(folder/'runtime'), XDG_CACHE_HOME=str(folder/'cache'),
               XDG_CONFIG_HOME=str(folder/'config'), DBUS_SESSION_BUS_ADDRESS='unix:path=/dev/null')
    env.pop('WAYLAND_DISPLAY', None)
    env.pop('DISPLAY', None)
    result = subprocess.run(['qs', '-p', str(folder/'shell.qml')], env=env,
                            capture_output=True, text=True, timeout=8)
    output = result.stdout+result.stderr
    assert result.returncode == 0 and 'STATIC_DOCK_POSITION_PASS' in output, output
    assert 'TypeError' not in output and 'Binding loop' not in output, output
    print('Qt static dock position: resize/overflow cancellation, held acknowledgements, lock/layout cancellation and real/anonymous monitor ownership passed')
