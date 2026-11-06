pragma ComponentBehavior: Bound
import QtQuick
import "Motion.js" as Motion

StashIcon {
  id: icon
  signal exited(int frames)
  property int exitFrames:0
  property bool exitReported:false
  presence:0
  function settle() { presence=retiring ? 0 : 1 }
  Connections {
    target:icon
    function onRetiringChanged() { icon.exitFrames=0; icon.exitReported=false; icon.settle() }
    function onPresenceChanged() {
      if (icon.retiring && icon.presence>0 && icon.presence<1) icon.exitFrames++
      if (icon.retiring && icon.presence===0 && !icon.exitReported) { icon.exitReported=true; icon.exited(icon.exitFrames) }
    }
    function onAnimationsChanged() {
      if (icon.animations==="off") arrival.complete()
      icon.settle()
    }
  }
  Behavior on presence {
    NumberAnimation { id:arrival; duration:icon.retiring ? Motion.exit(icon.animations,icon.animationSpeed) : Motion.enter(icon.animations,icon.animationSpeed); easing.type:Easing.OutCubic }
  }
  Timer { interval:1; running:true; onTriggered:icon.settle() }
}
