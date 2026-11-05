import QtQuick.Effects

// Tint the composed pixels, including artwork, glyphs and badges. Scaling the
// effect leaves the source item's layout and pointer coordinates unchanged.
MultiEffect {
  required property var feedback
  autoPaddingEnabled: false
  colorizationColor: feedback.accent
  colorization: feedback.tint
  brightness: feedback.lightness
  scale: feedback.visualScale
  opacity: feedback.presence
}
