pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Shapes
import QtQml.Models
import qs.Commons
import "Model.js" as Model

Shape {
  id: squircle
  required property color backgroundColor
  required property var borderSpec
  property var gradientStops: []
  readonly property var gradient: borderSpec.gradient || ({enabled:false})
  readonly property var colors: gradient.enabled ? gradient.colors : [Border.color(borderSpec), Border.color(borderSpec)]
  readonly property var line: Model.gradientLine(width, height, gradient.angle)
  readonly property string outerPath: Model.squirclePath(width, height, 0, 0, 0, 0, false)
  readonly property string innerPath: Model.squirclePath(width, height, Border.left(borderSpec),
    Border.top(borderSpec), Border.right(borderSpec), Border.bottom(borderSpec), true)
  preferredRendererType: Shape.CurveRenderer
  ShapePath {
    strokeWidth: 0
    fillColor: squircle.backgroundColor
    PathSvg { path: squircle.outerPath }
  }
  ShapePath {
    strokeWidth: 0
    fillRule: ShapePath.WindingFill
    fillColor: "transparent"
    fillGradient: LinearGradient {
      x1: squircle.line.x1; y1: squircle.line.y1
      x2: squircle.line.x2; y2: squircle.line.y2
      stops: squircle.gradientStops
    }
    PathSvg { path: Border.isNone(squircle.borderSpec) ? "" : squircle.outerPath + " " + squircle.innerPath }
  }
  Instantiator {
    model: squircle.colors
    delegate: GradientStop {
      required property int index
      required property var modelData
      position: squircle.colors.length <= 1 ? 0 : index / (squircle.colors.length - 1)
      color: modelData
    }
    onObjectAdded: function(index, object) {
      var stops = squircle.gradientStops.slice(); stops.splice(index, 0, object); squircle.gradientStops = stops
    }
    onObjectRemoved: function(index, object) {
      squircle.gradientStops = squircle.gradientStops.filter(function(stop) { return stop !== object })
    }
  }
}
