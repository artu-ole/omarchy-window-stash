pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Commons as Commons
import qs.Ui as Ui

ColumnLayout {
  id:shortcut
  required property var stash
  required property string settingKey
  required property string label
  property string binding:""
  property string defaultBinding:""
  property string animations:"full"
  property string animationSpeed:"normal"
  property color foreground:Commons.Color.foreground
  property bool dirty:false
  property bool awaiting:false
  property string submittedText:""
  readonly property var metrics:Style.spacing
  readonly property var fonts:Style.font
  readonly property bool narrow:width<Style.space(360)
  readonly property alias field:input
  Layout.fillWidth:true
  Layout.minimumWidth:0
  spacing:shortcut.metrics.xxs

  function resetDraft() {
    input.text=binding; dirty=false; awaiting=false; submittedText=""
  }
  function submit(value) {
    if (stash.resetBusy || stash.resetConfirmation) return
    input.text=value
    dirty=value!==binding
    if (!dirty && !stash.lastError) { awaiting=false; submittedText=""; return }
    submittedText=value; awaiting=true
    stash.setting(settingKey,value)
  }
  function syncBinding() {
    if (!input) return
    if ((awaiting && input.text===submittedText) || !dirty) resetDraft()
    else dirty=input.text!==binding
  }
  function acknowledged(key,value) {
    if (key!==settingKey) return
    // An earlier save may complete while a newer draft is being typed.
    if (input.text===submittedText || !dirty) { input.text=value; dirty=false }
    awaiting=false; submittedText=""
  }
  function rectOf(item,coordinateRoot) {
    var point=item.mapToItem(coordinateRoot || shortcut,0,0)
    return {x:point.x,y:point.y,width:item.width,height:item.height}
  }
  function details(coordinateRoot) {
    return {key:settingKey,text:input.text,binding:binding,dirty:dirty,pending:awaiting,
      field:rectOf(input,coordinateRoot),fieldRect:rectOf(input,coordinateRoot),applyRect:rectOf(applyButton,coordinateRoot),
      clearRect:rectOf(clearButton,coordinateRoot),defaultRect:rectOf(defaultButton,coordinateRoot)}
  }
  onBindingChanged:syncBinding()
  Component.onCompleted:resetDraft()
  Connections {
    target:shortcut.stash
    ignoreUnknownSignals:true
    function onShortcutConfigured(key,value) { shortcut.acknowledged(key,value) }
    function onSettingsReset() { shortcut.resetDraft() }
    function onLastErrorChanged() {
      if (shortcut.stash.lastError!=="") { shortcut.awaiting=false; shortcut.submittedText="" }
    }
  }

  GridLayout {
    Layout.fillWidth:true
    Layout.minimumWidth:0
    columns:shortcut.narrow ? 1 : 2
    columnSpacing:shortcut.metrics.sm
    rowSpacing:shortcut.metrics.xxs
    Text {
      text:shortcut.label
      textFormat:Text.PlainText
      wrapMode:Text.Wrap
      Layout.minimumWidth:0; Layout.fillWidth:true
      Layout.maximumWidth:shortcut.width
      color:shortcut.foreground
      font.family:shortcut.fonts.family; font.pixelSize:shortcut.fonts.body
    }
    Text {
      visible:shortcut.dirty || shortcut.awaiting
      Layout.minimumWidth:0
      Layout.fillWidth:shortcut.narrow
      Layout.maximumWidth:shortcut.width
      text:shortcut.awaiting ? "Saving…" : "Not applied"
      textFormat:Text.PlainText
      wrapMode:Text.Wrap
      color:shortcut.foreground; opacity:.65
      font.family:shortcut.fonts.family; font.pixelSize:shortcut.fonts.caption
    }
  }
  GridLayout {
    Layout.fillWidth:true
    Layout.minimumWidth:0
    columns:shortcut.narrow ? 1 : 2
    columnSpacing:shortcut.metrics.sm
    rowSpacing:shortcut.metrics.xxs
    Ui.TextField {
      id:input
      Layout.minimumWidth:0; Layout.fillWidth:true
      placeholderText:"Not bound"
      foreground:shortcut.foreground
      selectByMouse:true
      inputMethodHints:Qt.ImhNoPredictiveText | Qt.ImhNoAutoUppercase
      onTextEdited:shortcut.dirty=text!==shortcut.binding
      onAccepted:if (!shortcut.awaiting) shortcut.submit(text)
      Keys.onEscapePressed:function(event) {
        if (shortcut.dirty || shortcut.awaiting) { shortcut.resetDraft(); event.accepted=true }
        else event.accepted=false
      }
      Ui.PanelToolTip {
        visible:input.hovered && !input.activeFocus
        text:"Example: SUPER + SHIFT + Z. Leave empty to disable."
      }
    }
    Item {
      Layout.minimumWidth:0
      Layout.fillWidth:shortcut.narrow
      Layout.maximumWidth:shortcut.width
      implicitWidth:applyButton.implicitWidth+clearButton.width+defaultButton.width+shortcut.metrics.sm*2
      implicitHeight:actionFlow.implicitHeight
      Flow {
        id:actionFlow
        width:parent.width
        spacing:shortcut.metrics.sm
        StashButton {
          id:applyButton
          width:implicitWidth; height:implicitHeight
          text:"Apply"; focusable:true
          enabled:(shortcut.dirty || !!shortcut.stash.lastError) && !shortcut.awaiting
          animations:shortcut.animations; animationSpeed:shortcut.animationSpeed
          foreground:shortcut.foreground
          onClicked:shortcut.submit(input.text)
        }
        StashActionButton {
          id:clearButton
          size:input.implicitHeight
          iconText:"×"; tooltipText:"Disable shortcut"
          focusable:true
          enabled:!shortcut.awaiting && (input.text!=="" || shortcut.binding!=="")
          animations:shortcut.animations; animationSpeed:shortcut.animationSpeed
          foreground:shortcut.foreground
          onClicked:shortcut.submit("")
        }
        StashActionButton {
          id:defaultButton
          size:input.implicitHeight
          iconText:"↺"; tooltipText:"Use default: "+(shortcut.defaultBinding || "Not bound")
          focusable:true
          enabled:!shortcut.awaiting && (shortcut.dirty || shortcut.binding!==shortcut.defaultBinding)
          animations:shortcut.animations; animationSpeed:shortcut.animationSpeed
          foreground:shortcut.foreground
          onClicked:shortcut.submit(shortcut.defaultBinding)
        }
      }
    }
  }
}
