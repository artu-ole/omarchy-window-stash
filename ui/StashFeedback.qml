import QtQuick
import qs.Commons as Commons

Item {
  id: feedback
  property bool hot: false
  property bool down: false
  property real pressDepth: 0.06
  property real hoverProgress: hot ? 1 : 0
  property real pressProgress: down ? 1 : 0
  readonly property color accent: Commons.Color.accent
  readonly property real tint: hoverProgress * 0.33 + pressProgress * 0.12
  readonly property real lightness: hoverProgress * 0.045 - pressProgress * 0.07
  readonly property real visualScale: 1 - pressProgress * pressDepth
  property int hoverFrames: 0
  property int pressFrames: 0
  onHotChanged: hoverFrames = 0
  onDownChanged: pressFrames = 0
  onHoverProgressChanged: if (hoverProgress > 0 && hoverProgress < 1) hoverFrames++
  onPressProgressChanged: if (pressProgress > 0 && pressProgress < 1) pressFrames++
  Behavior on hoverProgress {
    NumberAnimation { duration:feedback.hot ? 130 : 180; easing.type:Easing.OutCubic }
  }
  Behavior on pressProgress {
    NumberAnimation { duration:feedback.down ? 75 : 170; easing.type:Easing.OutCubic }
  }
  function details() {
    return {hot:hot,down:down,hover:hoverProgress,press:pressProgress,tint:tint,
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
