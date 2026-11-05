pragma ComponentBehavior: Bound
import QtQuick

Item {
  id:row
  required property var group
  property bool frameVisible:true
  property string iconShape:"auto"
  property bool hasCursor:false
  readonly property alias icon:graphic
  implicitHeight:44
  height:implicitHeight
  signal activated()
  signal contextRequested()
  signal hovered(bool isHovered)
  StashIcon {
    id:graphic
    anchors.horizontalCenter:parent.horizontalCenter
    anchors.verticalCenter:parent.verticalCenter
    group:row.group
    frameVisible:row.frameVisible
    iconShape:row.iconShape
    hasCursor:row.hasCursor
    cursorManaged:true
    onActivated:row.activated()
    onContextRequested:row.contextRequested()
    onHovered:function(isHovered) { row.hovered(isHovered) }
  }
}
