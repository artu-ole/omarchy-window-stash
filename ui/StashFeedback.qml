import QtQuick
import "Motion.js" as Motion
import qs.Commons as Commons

Item {
  id: feedback
  property string animations:"full"
  property real presence:1
  property real idleOpacity:1
  property bool hot: false
  property bool down: false
  property real pressDepth: 0.06
  property real hoverProgress: hot ? 1 : 0
  property real pressProgress: down ? 1 : 0
  property real opacityProgress:hot || down ? 1 : Math.max(0,Math.min(1,idleOpacity))
  readonly property real visualOpacity:presence*opacityProgress
  property int opacityFrames:0
  onOpacityProgressChanged:if (opacityProgress>idleOpacity && opacityProgress<1) opacityFrames++
  readonly property color accent: Commons.Color.accent
  readonly property real tint: hoverProgress * 0.33 + pressProgress * 0.12
  readonly property real lightness: hoverProgress * 0.045 - pressProgress * 0.07
  readonly property real visualScale: Motion.full(animations) ? (0.86+presence*0.14)*(1-pressProgress*pressDepth) : 1
  property int hoverFrames: 0
  property int pressFrames: 0
  onHotChanged: { hoverFrames=0; opacityFrames=0 }
  onDownChanged: pressFrames = 0
  onHoverProgressChanged: if (hoverProgress > 0 && hoverProgress < 1) hoverFrames++
  onPressProgressChanged: if (pressProgress > 0 && pressProgress < 1) pressFrames++
  Behavior on hoverProgress {
    NumberAnimation { id:hoverAnimation; duration:Motion.duration(feedback.animations,feedback.hot ? 130 : 180,90); easing.type:Easing.OutCubic }
  }
  Behavior on pressProgress {
    NumberAnimation { id:pressAnimation; duration:Motion.duration(feedback.animations,feedback.down ? 75 : 170,90); easing.type:Easing.OutCubic }
  }
  Behavior on opacityProgress {
    NumberAnimation { id:opacityAnimation; duration:Motion.duration(feedback.animations,feedback.hot || feedback.down ? 140 : 200,90); easing.type:Easing.OutCubic }
  }
  onAnimationsChanged:if (animations==="off") { hoverAnimation.complete(); pressAnimation.complete(); opacityAnimation.complete() }
  function details() {
    return {hot:hot,down:down,presence:presence,idleOpacity:idleOpacity,opacity:visualOpacity,opacityProgress:opacityProgress,opacityFrames:opacityFrames,hover:hoverProgress,press:pressProgress,tint:tint,
      scale:visualScale,accent:String(accent),hoverFrames:hoverFrames,pressFrames:pressFrames}
  }
  function mouseArea(item) {
    // Observe the native control's handler instead of adding a competing grab.
    for (var i=0;i<item.children.length;i++) {
      var area=item.children[i] as MouseArea
      if (area) return area
    }
    return null
  }
}
