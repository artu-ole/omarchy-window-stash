pragma ComponentBehavior: Bound
import QtQuick
import Quickshell
import qs.Commons
import qs.Commons as Commons
import qs.Ui as Ui
import "Model.js" as Model

Ui.BorderSurface {
  id: icon
  readonly property var popupColors: Commons.Color.popups
  readonly property var fonts: Style.font
  readonly property var metrics: Style.spacing
  required property var group
  property bool bubble: false
  property string iconShape: "auto"
  readonly property real hitRadius: Model.iconRadius(iconShape, width, bubble, Style.cornerRadius)
  signal activated()
  signal contextRequested()
  signal moved(real dx, real dy)
  signal dragFinished()
  width: bubble ? 48 : 44
  height: width
  radius: hitRadius
  property color frameColor: pointer.pressed ? Style.pressedFillFor(icon.popupColors.text, Commons.Color.accent)
    : pointer.containsMouse ? Style.hoverFillFor(icon.popupColors.text, Commons.Color.accent)
    : bubble || iconShape !== "auto" ? icon.popupColors.background : "transparent"
  readonly property var frameBorder: pointer.containsMouse || pointer.pressed
    ? Border.controlSpec("hover-cursor", icon.popupColors.text, Commons.Color.accent)
    : bubble || iconShape !== "auto" ? Border.surfaceSpec("popups", "border", icon.popupColors.border, Style.normalBorderWidth)
    : Border.none()
  color: iconShape === "squircle" ? "transparent" : frameColor
  borderSpec: iconShape === "squircle" ? Border.none() : frameBorder
  Behavior on frameColor { ColorAnimation { duration: 120 } }
  Loader {
    anchors.fill: parent
    active: icon.iconShape === "squircle"
    sourceComponent: StashSquircle {
      backgroundColor: icon.frameColor
      borderSpec: icon.frameBorder
    }
  }
  readonly property var desktop: DesktopEntries.heuristicLookup(String(group.app || ""))
  readonly property string appIcon: desktop && desktop.icon ? String(desktop.icon) : "application-x-executable"
  Image {
    id: image
    anchors.centerIn: parent
    width: Math.min(icon.width - icon.metrics.sm * 2, Style.space(29)); height: width
    source: Quickshell.iconPath(icon.appIcon, true)
    sourceSize.width: width * Screen.devicePixelRatio
    sourceSize.height: height * Screen.devicePixelRatio
    fillMode: Image.PreserveAspectFit
  }
  Text {
    anchors.centerIn: parent
    visible: image.status === Image.Error || image.status === Image.Null
    text: String(icon.group.app || "?").slice(0, 1).toUpperCase()
    color: icon.popupColors.text
    font.family: icon.fonts.family
    font.pixelSize: icon.fonts.display
  }
  Rectangle {
    visible: icon.group.windows.length > 1
    width: Math.max(Style.space(18), countText.implicitWidth + icon.metrics.sm * 2)
    height: Math.max(Style.space(18), countText.implicitHeight + icon.metrics.xxs * 2)
    radius: icon.bubble ? height / 2 : Style.cornerRadius
    anchors.right: parent.right; anchors.bottom: parent.bottom
    color: Commons.Color.accent
    Text {
      id: countText
      anchors.centerIn: parent
      text: icon.group.windows.length
      textFormat: Text.PlainText
      color: Commons.Color.background
      font.family: icon.fonts.family
      font.pixelSize: icon.fonts.caption
      font.bold: true
    }
  }
  Ui.PanelToolTip {
    visible: pointer.containsMouse && !pointer.pressed
    text: icon.group.title + (icon.group.windows.length > 1 ? " · " + icon.group.windows.length + " windows" : "")
  }
  MouseArea {
    id: pointer
    anchors.fill: parent
    hoverEnabled: true
    acceptedButtons: Qt.LeftButton | Qt.RightButton
    cursorShape: Qt.PointingHandCursor
    property point start
    property bool dragging: false
    onPressed: function(mouse) { start = Qt.point(mouse.x, mouse.y); dragging = false }
    onPositionChanged: function(mouse) {
      if (!icon.bubble || !pressed || pressedButtons !== Qt.LeftButton) return
      var dx = mouse.x - start.x, dy = mouse.y - start.y
      if (dragging || Math.abs(dx) + Math.abs(dy) > 6) { dragging = true; icon.moved(dx, dy) }
    }
    onReleased: function(mouse) {
      if (dragging) { icon.dragFinished(); return }
      if (mouse.button === Qt.RightButton) icon.contextRequested()
      else icon.activated()
    }
  }
}
