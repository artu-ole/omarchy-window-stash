pragma ComponentBehavior: Bound
import QtQuick
import qs.Commons
import qs.Ui as Ui

// Keep dock chrome on its own opacity layer so icons never inherit its alpha.
Item {
  id:surface
  property color color:"transparent"
  property real radius:0
  property var borderSpec:Border.none()
  property real frameOpacity:1
  readonly property real borderLeft:Border.left(borderSpec)
  readonly property real borderRight:Border.right(borderSpec)
  readonly property real borderTop:Border.top(borderSpec)
  readonly property real borderBottom:Border.bottom(borderSpec)
  Ui.BorderSurface {
    anchors.fill:parent
    color:surface.color
    radius:surface.radius
    borderSpec:surface.borderSpec
    opacity:surface.frameOpacity
  }
}
