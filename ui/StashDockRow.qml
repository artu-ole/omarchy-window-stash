pragma ComponentBehavior: Bound
import QtQuick

Item {
  id:row
  required property var group
  property string animations:"full"
  property bool retiring:false
  property bool frameVisible:true
  property string iconShape:"auto"
  property bool hasCursor:false
  readonly property alias icon:graphic
  implicitHeight:44
  height:implicitHeight
  signal exited(int frames)
  signal activated()
  signal contextRequested()
  signal hovered(bool isHovered)
  StashAnimatedIcon {
    id:graphic
    anchors.horizontalCenter:parent.horizontalCenter
    anchors.verticalCenter:parent.verticalCenter
    group:row.group
    animations:row.animations
    retiring:row.retiring
    frameVisible:row.frameVisible
    iconShape:row.iconShape
    hasCursor:row.hasCursor
    cursorManaged:true
    onExited:function(frames) { row.exited(frames) }
    onActivated:row.activated()
    onContextRequested:row.contextRequested()
    onHovered:function(isHovered) { row.hovered(isHovered) }
  }
}
