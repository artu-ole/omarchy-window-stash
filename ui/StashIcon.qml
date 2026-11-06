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
  property string animationSpeed:"normal"
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
  property real sizeScale:1
  property bool draggable:bubble
  property string iconShape: "auto"
  property bool hasCursor: false
  property bool cursorManaged: false
  property bool externalPressed: false
  property bool positionAnimating: false
  property bool positionHeld: false
  property bool previewEnabled:false
  property bool previewSuppressed:false
  readonly property bool previewReady:enabled && !retiring && !positionAnimating && !positionHeld && !down && !previewSuppressed
  readonly property bool pointerHovered:iconHover.hovered
  onPreviewReadyChanged:if (previewEnabled && pointerHovered) hovered(previewReady)
  onPreviewEnabledChanged:if (previewEnabled && pointerHovered) hovered(previewReady)
  readonly property bool hot: hasCursor || (!cursorManaged && pointerHovered)
  readonly property bool down: pointer.pressed || externalPressed
  readonly property real hitRadius: frameVisible ? Model.iconRadius(iconShape, width, bubble, Style.cornerRadius) : 0
  signal activated()
  signal closeRequested()
  signal pointerPressed(int button)
  signal contextRequested(real x,real y)
  signal moved(real dx, real dy)
  signal dragHeld(bool held)
  signal dragFinished()
  signal hovered(bool isHovered)
  width: Math.round((bubble ? 48 : 44)*sizeScale)
  height: width
  clip: true
  radius: hitRadius
  layer.enabled: true
  layer.smooth: true
  layer.effect: StashHoverEffect { feedback:interaction }
  StashFeedback { id:interaction; hot:icon.hot; down:icon.down; presence:icon.presence; animations:icon.animations; animationSpeed:icon.animationSpeed; idleOpacity:icon.idleOpacity }
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
      pointer:{hover:iconHover.hovered,mouseAreaHover:pointer.containsMouse,pressed:pointer.pressed},
      borderWidth:Math.max(Border.left(frameBorder),Border.right(frameBorder),Border.top(frameBorder),Border.bottom(frameBorder)),
      artwork:{x:image.x,y:image.y,width:image.width,height:image.height,scale:image.scale,animating:image.animating,blend:image.mix,transitions:image.crossfadeSerial,frames:image.frames},
      badge:{visible:badge.visible,x:badge.x,y:badge.y,width:badge.width,height:badge.height}}
  }
  color: iconShape === "squircle" ? "transparent" : frameColor
  borderSpec: iconShape === "squircle" ? Border.none() : frameBorder
  Behavior on frameColor { ColorAnimation { id:frameColorAnimation; duration: Motion.duration(icon.animations,120,90,icon.animationSpeed) } }
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
    animations:icon.animations; animationSpeed:icon.animationSpeed
    anchors.centerIn: parent
    width: Model.artworkSize(icon.width, Style.space(36)*icon.sizeScale, icon.hitRadius, icon.iconShape, icon.artworkInset, Screen.devicePixelRatio, !icon.frameVisible,icon.sizeScale)
    height: width
    scale: Motion.full(icon.animations) && !icon.frameVisible && icon.hot ? 1.04 : 1
    Behavior on scale { NumberAnimation { id:artworkScaleAnimation; duration:Motion.move(icon.animations,icon.animationSpeed); easing.type:Easing.OutCubic } }
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
    font.pixelSize: Math.max(1,Math.min(icon.width-icon.artworkInset*2,icon.fonts.display*icon.sizeScale))
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
    Behavior on reveal { NumberAnimation { id:badgeRevealAnimation; duration:Motion.duration(icon.animations,160,100,icon.animationSpeed); easing.type:Easing.OutCubic } }
    width: Math.max(0,Math.min(icon.width - inset * 2, Math.max(Style.space(18)*icon.sizeScale, countText.implicitWidth + icon.metrics.sm*icon.sizeScale*2)))
    height: Math.max(0,Math.min(icon.height - inset * 2, Math.max(Style.space(18)*icon.sizeScale, icon.fonts.caption*icon.sizeScale + icon.metrics.xxs*icon.sizeScale*2)))
    readonly property real inset: Math.min(icon.width/4,icon.hitRadius >= icon.width / 2 ? Math.ceil(icon.width * 0.12) : 2*icon.sizeScale)
    radius: icon.hitRadius > 0 ? height / 2 : Style.cornerRadius
    anchors.right: parent.right; anchors.bottom: parent.bottom
    anchors.rightMargin: inset; anchors.bottomMargin: inset
    color: Commons.Color.accent
    Text {
      id: countText
      anchors.centerIn: parent
      width:Math.max(0,parent.width-icon.metrics.xxs*icon.sizeScale*2)
      height:Math.max(0,parent.height-icon.metrics.xxs*icon.sizeScale*2)
      horizontalAlignment:Text.AlignHCenter
      verticalAlignment:Text.AlignVCenter
      fontSizeMode:Text.Fit
      minimumPixelSize:Math.min(5,Math.max(1,height))
      text: badge.shownCount > 99 ? "99+" : badge.shownCount
      textFormat: Text.PlainText
      color: Commons.Color.background
      font.family: icon.fonts.family
      font.pixelSize: Math.max(1,icon.fonts.caption*icon.sizeScale)
      font.bold: true
    }
  }
  Ui.PanelToolTip {
    visible: !icon.previewEnabled && icon.pointerHovered && !pointer.pressed
    text: icon.group.title + (icon.group.windows.length > 1 ? " · " + icon.group.windows.length + " windows" : "")
  }
  // Keep hover independent of MouseArea's press/drag state. Its containsMouse
  // can remain latched across delegate reflow and native focus transitions.
  HoverHandler {
    id:iconHover
    enabled:icon.enabled && !icon.retiring
    blocking:false
    cursorShape:Qt.PointingHandCursor
    onHoveredChanged: { if (!hovered) icon.previewSuppressed=false; icon.hovered(hovered && !icon.previewSuppressed) }
  }
  MouseArea {
    id: pointer
    anchors.fill: parent
    preventStealing: icon.draggable
    acceptedButtons: Qt.LeftButton | Qt.RightButton | Qt.MiddleButton
    cursorShape: Qt.PointingHandCursor
    property point start
    property real pressedWidth:0
    property real pressedHeight:0
    property bool dragging: false
    onPressed: function(mouse) { pressedWidth=icon.width;pressedHeight=icon.height;icon.previewSuppressed=true; icon.pointerPressed(mouse.button); start = Qt.point(mouse.x, mouse.y); dragging = false; if (icon.draggable && mouse.button === Qt.LeftButton) icon.dragHeld(true) }
    onPositionChanged: function(mouse) {
      if (!icon.draggable || !pressed || pressedButtons !== Qt.LeftButton) return
      var dx = mouse.x - start.x, dy = mouse.y - start.y
      if (dragging || Math.abs(dx) + Math.abs(dy) > 6) { dragging = true; icon.moved(dx, dy) }
    }
    onCanceled: { if (icon.draggable) { icon.dragHeld(false); icon.dragFinished() } }
    onReleased: function(mouse) {
      if (icon.draggable && mouse.button === Qt.LeftButton) icon.dragHeld(false)
      if (pressedWidth!==icon.width || pressedHeight!==icon.height) { if (icon.draggable) icon.dragFinished();return }
      if (dragging) { icon.dragFinished(); return }
      if (mouse.button === Qt.MiddleButton) { if (icon.pointerHovered) icon.closeRequested() }
      else if (mouse.button === Qt.RightButton) icon.contextRequested(mouse.x,mouse.y)
      else icon.activated()
    }
  }
}
