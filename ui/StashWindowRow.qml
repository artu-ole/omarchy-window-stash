pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import Quickshell
import qs.Commons
import qs.Commons as Commons
import qs.Ui as Ui

Ui.CursorSurface {
  id: row
  readonly property var popupColors: Commons.Color.popups
  readonly property var fonts: Style.font
  readonly property var metrics: Style.spacing
  required property var windowData
  signal activated()
  signal contextRequested()
  signal pointed()
  implicitHeight: Math.max(Style.space(48), labels.implicitHeight + row.metrics.controlPaddingY * 2)
  foreground: row.popupColors.text
  layer.enabled: true
  layer.smooth: true
  layer.effect: StashHoverEffect { feedback:interaction }
  StashFeedback { id:interaction; hot:row.hasCursor || row.current; down:pointer.pressed; pressDepth:0.02 }

  RowLayout {
    anchors.fill: parent
    anchors.leftMargin: row.metrics.rowPaddingX
    anchors.rightMargin: row.metrics.rowPaddingX
    spacing: row.metrics.controlGap
    Image {
      readonly property var desktop: DesktopEntries.heuristicLookup(String(row.windowData.app || ""))
      Layout.preferredWidth: Style.space(26)
      Layout.preferredHeight: Style.space(26)
      source: Quickshell.iconPath(desktop && desktop.icon ? String(desktop.icon) : "application-x-executable", true)
      sourceSize.width: width * Screen.devicePixelRatio
      sourceSize.height: height * Screen.devicePixelRatio
      fillMode: Image.PreserveAspectFit
    }
    ColumnLayout {
      id: labels
      Layout.fillWidth: true
      spacing: row.metrics.labelGap
      Text {
        text: row.windowData.title
        textFormat: Text.PlainText
        color: row.foreground
        font.family: row.fonts.family
        font.pixelSize: row.fonts.body
        elide: Text.ElideRight
        Layout.fillWidth: true
      }
      Text {
        text: row.windowData.app + " · workspace " + row.windowData.origin.name
        textFormat: Text.PlainText
        color: Qt.darker(row.foreground, 1.4)
        font.family: row.fonts.family
        font.pixelSize: row.fonts.caption
        elide: Text.ElideRight
        Layout.fillWidth: true
      }
    }
  }
  MouseArea {
    id: pointer
    anchors.fill: parent
    hoverEnabled: true
    cursorShape: Qt.PointingHandCursor
    acceptedButtons: Qt.LeftButton | Qt.RightButton
    onPositionChanged: row.pointed()
    onClicked: function(mouse) {
      if (mouse.button === Qt.RightButton) row.contextRequested()
      else row.activated()
    }
    onPressAndHold: row.contextRequested()
  }
  Ui.PanelToolTip { visible: pointer.containsMouse; text: row.windowData.title }
}
