pragma ComponentBehavior: Bound
import QtQuick
import qs.Ui as Ui

Ui.PanelActionButton {
  id: button
  property string animations:"full"
  property string animationSpeed:"normal"
  opacity:interaction.visualOpacity
  property MouseArea pressArea: null
  layer.enabled: true
  layer.smooth: true
  layer.effect: StashHoverEffect { feedback:interaction }
  StashFeedback {
    id: interaction
    animations:button.animations; animationSpeed:button.animationSpeed
    hot: button.enabled && (hover.hovered || button.hasCursor || button.activeFocus)
    down: button.pressArea ? button.pressArea.pressed : false
  }
  HoverHandler { id:hover }
  Component.onCompleted: pressArea = interaction.mouseArea(button)
}
