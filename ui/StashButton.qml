pragma ComponentBehavior: Bound
import QtQuick
import qs.Ui as Ui

Ui.Button {
  id: button
  property string animations:"full"
  property string animationSpeed:"normal"
  property real idleOpacity:1
  opacity:interaction.visualOpacity
  property MouseArea pressArea: null
  layer.enabled: true
  layer.smooth: true
  layer.effect: StashHoverEffect { feedback:interaction }
  StashFeedback {
    id: interaction
    animations:button.animations; animationSpeed:button.animationSpeed
    idleOpacity:button.idleOpacity
    hot: button.enabled && (button.hot || button.activeFocus)
    down: button.pressArea ? button.pressArea.pressed : false
    pressDepth: 0.025
  }
  Component.onCompleted: pressArea = interaction.mouseArea(button)
  function feedbackDetails() { return interaction.details() }
}
