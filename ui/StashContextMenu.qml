pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import qs.Commons
import qs.Commons as Commons
import qs.Ui as Ui
import "Motion.js" as Motion

Ui.BorderSurface {
  id:menu
  required property var stash
  required property var host
  required property string screenName
  required property var area
  property string animations:"full"
  property string animationSpeed:"normal"
  readonly property bool opened:stash.contextOpen && stash.contextScreen===screenName
  readonly property var targets:stash.contextWindows()
  readonly property var eligible:stash.scopeWindows(screenName,stash.contextWorkspace)
  readonly property bool targetBusy:targets.some(function(w) { return !!menu.stash.pendingCloseIds[w.id] })
  readonly property bool allBusy:eligible.length>0 && eligible.every(function(w) { return !!menu.stash.pendingCloseIds[w.id] })
  readonly property var palette:Commons.Color.popups
  readonly property var metrics:Style.spacing
  readonly property var fonts:Style.font
  readonly property real padding:metrics.sm
  readonly property real margin:Math.min(metrics.sm,area.width/2,area.height/2)
  readonly property bool interactionAvailable:stash.snapshot.settings.presentation==="previews"
    && stash.snapshot.settings.floatingPreviewInteraction==="on" && targets.length===1 && !targetBusy
  readonly property bool proportionsResetAvailable:!targetBusy && typeof host.canResetPreviewProportions==="function" && host.canResetPreviewProportions(stash.contextGroup)
  readonly property var buttons:[hereButton,originalButton].concat(interactionAvailable ? [interactButton] : [])
    .concat(proportionsResetAvailable ? [proportionsResetButton] : []).concat([closeButton,allButton,closeAllButton,settingsButton])
  readonly property var actionIds:["here","original"].concat(interactionAvailable ? ["interact"] : [])
    .concat(proportionsResetAvailable ? ["reset-preview-proportions"] : []).concat(["close","all","closeAll","settings"])
  property int currentIndex:0
  property int frames:0
  property bool openingRightClickPending:false
  property real reveal:opened ? 1 : 0
  visible:reveal>0
  enabled:opened
  focus:opened
  z:30000
  opacity:reveal
  width:Math.max(1,Math.min(Style.space(350),area.width-margin*2))
  height:Math.max(1,Math.min(content.implicitHeight+padding*2+borderTop+borderBottom,area.height-margin*2))
  x:Math.max(area.x+margin,Math.min(area.x+area.width-margin-width,
      stash.contextPoint.x+width<=area.x+area.width-margin ? stash.contextPoint.x : stash.contextPoint.x-width))
  y:Math.max(area.y+margin,Math.min(area.y+area.height-margin-height,
      stash.contextPoint.y+height<=area.y+area.height-margin ? stash.contextPoint.y : stash.contextPoint.y-height))
  radius:Style.cornerRadius
  color:palette.background
  borderSpec:Border.surfaceSpec("popups","border",palette.border,Style.normalBorderWidth)
  signal inputChanged()
  Behavior on reveal { NumberAnimation { duration:Motion.duration(menu.animations,menu.opened ? 120 : 90,90,menu.animationSpeed); easing.type:Easing.OutCubic } }
  onRevealChanged: { if (reveal>0 && reveal<1) frames++; inputChanged() }
  onXChanged:inputChanged()
  onYChanged:inputChanged()
  onWidthChanged:inputChanged()
  onHeightChanged:inputChanged()
  onOpenedChanged:if (opened) initialize()
  function initialize() {
    frames=0; currentIndex=0; viewport.contentY=0; openingRightClickPending=true
    repairSelection()
    Qt.callLater(function() { if (menu.opened) menu.forceActiveFocus() })
  }
  function repairSelection() {
    if (!buttons[currentIndex] || !buttons[currentIndex].enabled) navigate(1)
  }
  function navigate(direction) {
    for (var i=1;i<=buttons.length;i++) {
      var next=(currentIndex+direction*i+buttons.length*2)%buttons.length
      if (buttons[next] && buttons[next].enabled) { currentIndex=next; ensureSelected(); return }
    }
  }
  function extreme(last) {
    currentIndex=last ? 0 : buttons.length-1
    navigate(last ? -1 : 1)
  }
  function ensureSelected() {
    var button=buttons[currentIndex]
    if (!button) return
    var top=button.y,bottom=top+button.height
    if (top<viewport.contentY) viewport.contentY=top
    else if (bottom>viewport.contentY+viewport.height) viewport.contentY=bottom-viewport.height
  }
  function activate() { var button=buttons[currentIndex]; if (button && button.enabled) button.clicked() }
  function containsPoint(px,py) {
    var lx=px-x,ly=py-y,r=radius
    if (lx<0 || ly<0 || lx>width || ly>height) return false
    var dx=Math.max(r-lx,0,lx-width+r),dy=Math.max(r-ly,0,ly-height+r)
    return dx*dx+dy*dy<=r*r
  }
  function actionRect(id) {
    var at=actionIds.indexOf(id)
    if (at<0) return {x:0,y:0,width:0,height:0}
    var button=buttons[at],point=button.mapToItem(host.contentItem,0,0)
    return {x:point.x,y:point.y,width:button.width,height:button.height,feedback:button.feedbackDetails()}
  }
  function details() {
    var ids=actionIds
    return {visible:opened && reveal>.999,opened:opened,rendered:visible,progress:reveal,frames:frames,serial:stash.contextSerial,
      openingRightClickPending:openingRightClickPending,
      rect:{x:x,y:y,width:width,height:height},radius:radius,point:{x:stash.contextPoint.x,y:stash.contextPoint.y},
      screen:screenName,workspace:stash.contextWorkspace,caption:caption.text,targetIds:targets.map(function(w) { return w.id }),
      currentIndex:currentIndex,separatorY:separator.mapToItem(host.contentItem,0,0).y,
      actions:ids.map(function(id,index) { return {id:id,text:menu.buttons[index].text,enabled:menu.buttons[index].enabled,rect:menu.actionRect(id)} })}
  }
  Keys.priority:Keys.BeforeItem
  Keys.onPressed:function(event) {
    if (event.key===Qt.Key_Down) navigate(1)
    else if (event.key===Qt.Key_Up) navigate(-1)
    else if (event.key===Qt.Key_Home) extreme(false)
    else if (event.key===Qt.Key_End) extreme(true)
    else if (event.key===Qt.Key_Return || event.key===Qt.Key_Enter || event.key===Qt.Key_Space) activate()
    else if (event.key===Qt.Key_Escape) stash.closeContext()
    else { event.accepted=false; return }
    event.accepted=true
  }
  Connections {
    target:menu.stash
    function onContextSerialChanged() { if (menu.opened) menu.initialize() }
    function onPendingCloseIdsChanged() { menu.repairSelection() }
    function onSnapshotChanged() { menu.repairSelection() }
    function onPointerClicked(px,py,button) {
      if (!menu.opened || !menu.host.monitor) return
      var x=px-menu.host.monitor.x,y=py-menu.host.monitor.y
      // The compositor press can arrive after Qt opens the menu on release.
      // Its anchor may be in a transparent rounded corner of the new card.
      // Exempt only that first right press at this invocation's exact anchor.
      if (menu.openingRightClickPending) {
        menu.openingRightClickPending=false
        if (button===273 && Math.abs(x-menu.stash.contextPoint.x)<=2 && Math.abs(y-menu.stash.contextPoint.y)<=2) return
      }
      if (!menu.containsPoint(x,y)) menu.stash.closeContext()
    }
  }
  // Card padding is part of this menu; surrounding content keeps its normal mask.
  MouseArea { anchors.fill:parent; acceptedButtons:Qt.AllButtons }
  Flickable {
    id:viewport
    anchors.fill:parent
    anchors.leftMargin:menu.padding+menu.borderLeft
    anchors.rightMargin:menu.padding+menu.borderRight
    anchors.topMargin:menu.padding+menu.borderTop
    anchors.bottomMargin:menu.padding+menu.borderBottom
    contentWidth:width; contentHeight:content.implicitHeight
    clip:true
    boundsBehavior:Flickable.StopAtBounds
    Controls.ScrollBar.vertical:Controls.ScrollBar {}
    ColumnLayout {
      id:content
      width:viewport.width
      spacing:menu.metrics.xxs
      Text {
        id:caption
        text:menu.stash.contextGroup ? (menu.stash.contextGroup.title || menu.stash.contextGroup.app || "Stashed window") : "Stashed window"
        textFormat:Text.PlainText
        color:menu.palette.text
        font.family:menu.fonts.family
        font.pixelSize:menu.fonts.caption
        elide:Text.ElideRight
        Layout.fillWidth:true
        Layout.leftMargin:menu.metrics.controlPaddingX
        Layout.rightMargin:menu.metrics.controlPaddingX
        Layout.bottomMargin:menu.metrics.xxs
      }
      StashButton {
        id:hereButton
        text:"Restore here"; enabled:menu.targets.length>0 && !menu.targetBusy
        animations:menu.animations; animationSpeed:menu.animationSpeed; foreground:menu.palette.text
        Layout.fillWidth:true; leftAlign:true; hasCursor:menu.buttons[menu.currentIndex]===hereButton
        onHovered:function(value) { if (value && enabled) menu.currentIndex=menu.buttons.indexOf(hereButton) }
        onClicked:menu.stash.restoreContext("current")
      }
      StashButton {
        id:originalButton
        text:"Restore to original workspace"; enabled:menu.targets.length>0 && !menu.targetBusy
        animations:menu.animations; animationSpeed:menu.animationSpeed; foreground:menu.palette.text
        Layout.fillWidth:true; leftAlign:true; hasCursor:menu.buttons[menu.currentIndex]===originalButton
        onHovered:function(value) { if (value && enabled) menu.currentIndex=menu.buttons.indexOf(originalButton) }
        onClicked:menu.stash.restoreContext("original")
      }
      StashButton {
        id:interactButton
        visible:menu.interactionAvailable
        text:"Interact with window";enabled:menu.interactionAvailable
        animations:menu.animations;animationSpeed:menu.animationSpeed;foreground:menu.palette.text
        Layout.fillWidth:true;leftAlign:true;hasCursor:menu.buttons[menu.currentIndex]===interactButton
        onHovered:function(value) {if(value && enabled) menu.currentIndex=menu.buttons.indexOf(interactButton)}
        onClicked:menu.stash.interactContext()
      }
      StashButton {
        id:proportionsResetButton
        visible:menu.proportionsResetAvailable
        text:"Reset preview proportions";enabled:menu.proportionsResetAvailable
        animations:menu.animations;animationSpeed:menu.animationSpeed;foreground:menu.palette.text
        Layout.fillWidth:true;leftAlign:true;hasCursor:menu.buttons[menu.currentIndex]===proportionsResetButton
        onHovered:function(value) {if(value && enabled) menu.currentIndex=menu.buttons.indexOf(proportionsResetButton)}
        onClicked:menu.stash.resetPreviewProportionsContext()
      }
      StashButton {
        id:closeButton
        text:menu.targetBusy ? "Closing…" : menu.stash.contextIds.length>1 ? "Close stashed windows ("+menu.targets.length+")" : "Close window"
        enabled:menu.targets.length>0 && !menu.targetBusy
        animations:menu.animations; animationSpeed:menu.animationSpeed; foreground:menu.palette.text
        Layout.fillWidth:true; leftAlign:true; hasCursor:menu.buttons[menu.currentIndex]===closeButton
        onHovered:function(value) { if (value && enabled) menu.currentIndex=menu.buttons.indexOf(closeButton) }
        onClicked:menu.stash.closeContextWindows()
      }
      Ui.PanelSeparator { id:separator; foreground:menu.palette.text; Layout.fillWidth:true; Layout.topMargin:menu.metrics.xxs; Layout.bottomMargin:menu.metrics.xxs }
      StashButton {
        id:allButton
        text:"All stashed windows…"; enabled:menu.stash.snapshot.windows.length>0
        animations:menu.animations; animationSpeed:menu.animationSpeed; foreground:menu.palette.text
        Layout.fillWidth:true; leftAlign:true; hasCursor:menu.buttons[menu.currentIndex]===allButton
        onHovered:function(value) { if (value && enabled) menu.currentIndex=menu.buttons.indexOf(allButton) }
        onClicked:menu.stash.allWindows(menu.screenName)
      }
      StashButton {
        id:closeAllButton
        text:(menu.stash.snapshot.settings.scope==="workspace" ? "Close all in this workspace (" : "Close all stashed windows (")+menu.eligible.length+")"
        enabled:menu.eligible.length>0 && !menu.allBusy
        animations:menu.animations; animationSpeed:menu.animationSpeed; foreground:menu.palette.text
        Layout.fillWidth:true; leftAlign:true; hasCursor:menu.buttons[menu.currentIndex]===closeAllButton
        onHovered:function(value) { if (value && enabled) menu.currentIndex=menu.buttons.indexOf(closeAllButton) }
        onClicked:menu.stash.closeContextAll()
      }
      StashButton {
        id:settingsButton
        text:"Settings…"
        animations:menu.animations; animationSpeed:menu.animationSpeed; foreground:menu.palette.text
        Layout.fillWidth:true; leftAlign:true; hasCursor:menu.buttons[menu.currentIndex]===settingsButton
        onHovered:function(value) { if (value && enabled) menu.currentIndex=menu.buttons.indexOf(settingsButton) }
        onClicked:menu.stash.openDialog("settings",menu.screenName,[],null)
      }
    }
  }
}
