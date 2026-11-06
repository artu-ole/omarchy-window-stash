#!/usr/bin/env python3
"""Verify stack followers on an isolated offscreen Qt frame clock."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='stash-stack-follow-') as directory:
    folder = Path(directory)
    ui = folder/'ui'
    ui.mkdir()
    for name in ('StackFollow.js', 'Motion.js', 'StashStackFollow.qml'):
        shutil.copy2(ROOT/'ui'/name, ui/name)
    for name in ('runtime', 'cache', 'config'):
        (folder/name).mkdir(mode=0o700)
    (folder/'shell.qml').write_text('''import QtQuick
import QtQuick.Window
import Quickshell
import "ui"

ShellRoot {
  id:root
  property int phase:0
  property int ticks:0
  property int step:0
  property int updates:0
  property int savedFrames:0
  property real releasedDistance:0
  property real releaseTime:0
  property var savedPositions:[]
  Window {
    width:640; height:480; visible:true
    StashStackFollow {
      id:follow
      leadX:100; leadY:140; count:3
      area:({x:0,y:26,width:640,height:454})
      eligible:true
      identity:"initial-stack"
      onUpdated:root.updates++
    }
  }
  function check(value,message) { if (!value) throw new Error(message) }
  function near(actual,expected,message) {
    check(Math.abs(actual-expected)<.000001,message+": "+actual+" != "+expected)
  }
  function front() {
    near(follow.pose(0).x,follow.leadX,"Lead horizontal position lagged")
    near(follow.pose(0).y,follow.leadY,"Lead vertical position lagged")
  }
  function distance() {
    var tail=follow.pose(2)
    return Math.hypot(tail.x-follow.leadX,tail.y-follow.leadY-8)
  }
  function rest() {
    front()
    for (var i=1;i<3;i++) {
      near(follow.pose(i).x,follow.leadX,"Follower did not settle horizontally")
      near(follow.pose(i).y,follow.leadY+i*4,"Follower lost its resting preview offset")
    }
    check(!follow.active && !follow.tracking,"Resting follower kept tracking or animation alive")
  }
  function start(identity,speed) {
    follow.driving=false; follow.eligible=true; follow.count=3
    follow.leadX=100; follow.leadY=140
    follow.identity=identity; follow.animationSpeed=speed
    rest()
    follow.driving=true
    check(follow.tracking && !follow.active,"Driving did not arm the follower before movement")
    root.step=0
  }
  Timer {
    interval:20; repeat:true; running:true
    onTriggered: {
      try {
        root.ticks++
        if (root.ticks>350) throw new Error("Stack follower frame clock failed to settle")
        front()
        if (root.phase===0) {
          // Construction starts eligible/count3 to exercise initialization
          // handlers before any external call can mask an undefined state.
          rest(); check(follow.frames===0,"Initial stack started an idle frame clock")
          root.start("normal-drag","normal"); root.phase=1; return
        }
        if (root.phase===1) {
          root.step++
          follow.leadX=100+root.step*18; follow.leadY=140+root.step*7
          front()
          if (root.step<6) return
          check(follow.active && follow.tracking,"Dragging did not activate the spring")
          check(follow.pose(1).x<follow.leadX-4,"First follower had no horizontal lag")
          check(follow.pose(2).x<follow.pose(1).x-2,"Second follower did not trail the first")
          check(follow.pose(2).y<follow.leadY+8,"Vertical movement did not affect the spring")
          root.releasedDistance=distance(); root.savedFrames=follow.frames
          follow.driving=false
          check(follow.active && follow.tracking,"Releasing the lead discarded its catching followers")
          root.step=0; root.phase=2; return
        }
        if (root.phase===2) {
          root.step++
          if (root.step<5) return
          check(follow.frames>root.savedFrames+2,"Released followers had no native frame updates")
          check(distance()<root.releasedDistance-2,"Released followers did not catch the lead")
          root.phase=3; return
        }
        if (root.phase===3) {
          if (follow.active || follow.tracking) return
          rest(); root.savedFrames=follow.frames; root.step=0; root.phase=4; return
        }
        if (root.phase===4) {
          root.step++
          check(follow.frames===root.savedFrames,"Settled followers kept an idle frame clock running")
          if (root.step<4) return
          root.start("speed-change","slow"); root.phase=5; return
        }
        if (root.phase===5) {
          root.step++
          follow.leadX=100+root.step*22; follow.leadY=140+root.step*5
          front()
          if (root.step<6) return
          root.phase=6; return
        }
        if (root.phase===6) {
          root.savedPositions=[follow.pose(1),follow.pose(2)]
          check(follow.active,"Slow movement did not produce follower motion")
          follow.animationSpeed="ultrafast"
          for (var i=1;i<3;i++) {
            near(follow.pose(i).x,root.savedPositions[i-1].x,"Speed change jumped a follower horizontally")
            near(follow.pose(i).y,root.savedPositions[i-1].y,"Speed change jumped a follower vertically")
          }
          check(follow.details().speed==="ultrafast","Speed did not reach the native wrapper")
          follow.driving=false; root.releaseTime=Date.now(); root.phase=7; return
        }
        if (root.phase===7) {
          check(Date.now()-root.releaseTime<1500,"Ultrafast catch-up failed to settle")
          if (follow.active || follow.tracking) return
          rest(); root.start("disable-case","normal")
          follow.leadX+=90; follow.leadY+=30
          root.step=0; root.phase=8; return
        }
        if (root.phase===8) {
          root.step++
          if (root.step<3) return
          check(follow.active,"Disable case had no motion to cancel")
          follow.eligible=false
          rest(); follow.driving=false
          root.savedFrames=follow.frames; root.step=0; root.phase=9; return
        }
        if (root.phase===9) {
          root.step++
          check(follow.frames===root.savedFrames,"Disabled follower frame clock kept running")
          if (root.step<3) return
          follow.eligible=true
          follow.leadX+=55; follow.leadY+=25
          // Inactive programmatic placement should snap immediately, without
          // being mistaken for a new physical drag after mode re-enablement.
          rest(); root.phase=10; return
        }
        if (root.phase===10) {
          rest(); follow.driving=true
          follow.leadX+=75; follow.leadY-=20
          root.step=0; root.phase=11; return
        }
        if (root.phase===11) {
          root.step++
          if (root.step<3) return
          check(follow.active,"Identity reset case had no trailing motion")
          follow.identity="replacement-stack"
          front()
          for (var i=1;i<3;i++) {
            near(follow.pose(i).x,follow.leadX,"New stack inherited an old horizontal trail")
            near(follow.pose(i).y,follow.leadY+i*4,"New stack inherited an old vertical trail")
          }
          follow.driving=false; rest()
          follow.count=1; follow.driving=true
          check(!follow.active && !follow.tracking,"A single icon armed decorative followers")
          root.savedFrames=follow.frames; root.step=0; root.phase=12; return
        }
        if (root.phase===12) {
          root.step++
          check(follow.frames===root.savedFrames,"A single dragged icon wasted follower frame updates")
          if (root.step<3) return
          follow.count=0
          check(!follow.active && !follow.tracking,"An empty stack kept old followers")
          follow.driving=false; follow.count=3
          rest()
          check(root.updates>10,"Wrapper did not publish native intermediate poses")
          console.log("STACK_FOLLOW_QT_PASS")
          Qt.quit()
        }
      } catch (error) { console.error("STACK_FOLLOW_QT_FAIL: "+error);Qt.exit(1) }
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
                            capture_output=True, text=True, timeout=12)
    output = result.stdout+result.stderr
    assert result.returncode == 0 and 'STACK_FOLLOW_QT_PASS' in output, output
    assert not any(message in output for message in ('Binding loop', 'ReferenceError', 'TypeError')), output
    print('Qt stack follow: native lag, release catch-up, speed changes, exact sleep, identity and mode/count resets passed')
