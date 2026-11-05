pragma ComponentBehavior: Bound
import QtQuick
import Quickshell
import qs.Commons
import qs.Commons as Commons
import qs.Ui as Ui
import "Model.js" as Model
import "Motion.js" as Motion

Ui.BorderSurface {
  id: icon
  readonly property var popupColors: Commons.Color.popups
  readonly property var fonts: Style.font
  readonly property var metrics: Style.spacing
  required property var group
  property string animations:"full"
  property real presence:1
  property real idleOpacity:1
  property bool retiring:false
  property int presenceFrames:0
  readonly property bool artworkAnimating:image.animating
  readonly property real visualOpacity:interaction.visualOpacity
  opacity:visualOpacity
  onPresenceChanged:if (presence>0 && presence<1) presenceFrames++
  onAnimationsChanged:if (animations==="off") {
    frameColorAnimation.complete(); artworkScaleAnimation.complete(); badgeRevealAnimation.complete()
  }
  property bool frameVisible: true
  readonly property string inputShape: frameVisible ? iconShape : "square"
  property bool bubble: false
  property string iconShape: "auto"
  property bool hasCursor: false
  property bool cursorManaged: false
  property bool externalPressed: false
  property bool positionAnimating: false
  property bool positionHeld: false
  readonly property bool hot: hasCursor || (!cursorManaged && pointer.containsMouse)
  readonly property bool down: pointer.pressed || externalPressed
  readonly property real hitRadius: frameVisible ? Model.iconRadius(iconShape, width, bubble, Style.cornerRadius) : 0
  signal activated()
  signal contextRequested()
  signal moved(real dx, real dy)
  signal dragHeld(bool held)
  signal dragFinished()
  signal hovered(bool isHovered)
  width: bubble ? 48 : 44
  height: width
  clip: true
  radius: hitRadius
  layer.enabled: true
  layer.smooth: true
  layer.effect: StashHoverEffect { feedback:interaction }
  StashFeedback { id:interaction; hot:icon.hot; down:icon.down; presence:icon.presence; animations:icon.animations; idleOpacity:icon.idleOpacity }
  property color frameColor: !frameVisible ? "transparent" : down ? Style.pressedFillFor(icon.popupColors.text, Commons.Color.accent)
    : hot ? Style.hoverFillFor(icon.popupColors.text, Commons.Color.accent)
    : bubble || iconShape !== "auto" ? icon.popupColors.background : "transparent"
  readonly property var hoverBorder: Border.controlSpec("hover-cursor", icon.popupColors.text, Commons.Color.accent)
  readonly property var normalBorder: bubble || iconShape !== "auto"
    ? Border.surfaceSpec("popups", "border", icon.popupColors.border, Style.normalBorderWidth) : Border.none()
  readonly property var frameBorder: !frameVisible ? Border.none() : hot || down ? hoverBorder : normalBorder
  // Reserve both border states so the artwork never jumps in size on hover.
  readonly property real artworkInset: Math.max(1, 0.5 + Math.max(Border.left(normalBorder),
    Border.right(normalBorder), Border.top(normalBorder), Border.bottom(normalBorder),
    Border.left(hoverBorder), Border.right(hoverBorder), Border.top(hoverBorder), Border.bottom(hoverBorder)))
  function appearance() {
    return {width:width,height:height,frameVisible:frameVisible,enabled:enabled,background:String(frameColor),presence:presence,retiring:retiring,presenceFrames:presenceFrames,feedback:interaction.details(),
      borderWidth:Math.max(Border.left(frameBorder),Border.right(frameBorder),Border.top(frameBorder),Border.bottom(frameBorder)),
      artwork:{x:image.x,y:image.y,width:image.width,height:image.height,scale:image.scale,animating:image.animating,blend:image.mix,transitions:image.crossfadeSerial,frames:image.frames},
      badge:{visible:badge.visible,x:badge.x,y:badge.y,width:badge.width,height:badge.height}}
  }
  color: iconShape === "squircle" ? "transparent" : frameColor
  borderSpec: iconShape === "squircle" ? Border.none() : frameBorder
  Behavior on frameColor { ColorAnimation { id:frameColorAnimation; duration: Motion.duration(icon.animations,120,90) } }
  Loader {
    anchors.fill: parent
    active: icon.frameVisible && icon.iconShape === "squircle"
    sourceComponent: StashSquircle {
      backgroundColor: icon.frameColor
      borderSpec: icon.frameBorder
    }
  }
  readonly property var desktop: DesktopEntries.heuristicLookup(String(group.app || ""))
  readonly property string appIcon: desktop && desktop.icon ? String(desktop.icon) : "application-x-executable"
  StashArtwork {
    id: image
    animations:icon.animations
    anchors.centerIn: parent
    width: Model.artworkSize(icon.width, Style.space(36), icon.hitRadius, icon.iconShape, icon.artworkInset, Screen.devicePixelRatio, !icon.frameVisible)
    height: width
    scale: Motion.full(icon.animations) && !icon.frameVisible && icon.hot ? 1.04 : 1
    Behavior on scale { NumberAnimation { id:artworkScaleAnimation; duration:Motion.move(icon.animations); easing.type:Easing.OutCubic } }
    source: Quickshell.iconPath(icon.appIcon, true)
    sourceSize.width: Math.round(width * Screen.devicePixelRatio)
    sourceSize.height: Math.round(height * Screen.devicePixelRatio)
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
    id:badge
    readonly property int actualCount:icon.group.windows.length
    property int shownCount:actualCount>1 ? actualCount : 2
    onActualCountChanged:if (actualCount>1) shownCount=actualCount
    property real reveal:actualCount>1 ? 1 : 0
    visible:reveal>0
    opacity:reveal
    scale:Motion.full(icon.animations) ? 0.8+reveal*0.2 : 1
    Behavior on reveal { NumberAnimation { id:badgeRevealAnimation; duration:Motion.duration(icon.animations,160,100); easing.type:Easing.OutCubic } }
    width: Math.min(icon.width - inset * 2, Math.max(Style.space(18), countText.implicitWidth + icon.metrics.sm * 2))
    height: Math.min(icon.height - inset * 2, Math.max(Style.space(18), icon.fonts.caption + icon.metrics.xxs * 2))
    readonly property real inset: icon.hitRadius >= icon.width / 2 ? Math.ceil(icon.width * 0.12) : 2
    radius: icon.hitRadius > 0 ? height / 2 : Style.cornerRadius
    anchors.right: parent.right; anchors.bottom: parent.bottom
    anchors.rightMargin: inset; anchors.bottomMargin: inset
    color: Commons.Color.accent
    Text {
      id: countText
      anchors.centerIn: parent
      width:parent.width-icon.metrics.xxs*2
      height:parent.height-icon.metrics.xxs*2
      horizontalAlignment:Text.AlignHCenter
      verticalAlignment:Text.AlignVCenter
      fontSizeMode:Text.Fit
      minimumPixelSize:5
      text: badge.shownCount > 99 ? "99+" : badge.shownCount
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
    preventStealing: icon.bubble
    acceptedButtons: Qt.LeftButton | Qt.RightButton
    cursorShape: Qt.PointingHandCursor
    property point start
    property bool dragging: false
    onContainsMouseChanged: icon.hovered(containsMouse)
    onPressed: function(mouse) { start = Qt.point(mouse.x, mouse.y); dragging = false; if (icon.bubble && mouse.button === Qt.LeftButton) icon.dragHeld(true) }
    onPositionChanged: function(mouse) {
      if (!icon.bubble || !pressed || pressedButtons !== Qt.LeftButton) return
      var dx = mouse.x - start.x, dy = mouse.y - start.y
      if (dragging || Math.abs(dx) + Math.abs(dy) > 6) { dragging = true; icon.moved(dx, dy) }
    }
    onCanceled: { if (icon.bubble) { icon.dragHeld(false); icon.dragFinished() } }
    onReleased: function(mouse) {
      if (icon.bubble && mouse.button === Qt.LeftButton) icon.dragHeld(false)
      if (dragging) { icon.dragFinished(); return }
      if (mouse.button === Qt.RightButton) icon.contextRequested()
      else icon.activated()
    }
  }
}
