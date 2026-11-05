pragma ComponentBehavior: Bound
import QtQuick
import QtQml.Models
import Quickshell
import "Model.js" as Model

Region {
  id: region
  property real originX: 0
  property real originY: 0
  property real size: 48
  property real cornerRadius: size / 2
  property string iconShape: "auto"
  property var scanlines: []
  x: iconShape === "squircle" ? 0 : originX
  y: iconShape === "squircle" ? 0 : originY
  width: iconShape === "squircle" ? 0 : size
  height: width
  radius: cornerRadius
  regions: scanlines
  property Instantiator generator: Instantiator {
    model: region.iconShape === "squircle" ? Model.squircleBands(region.size, region.size) : []
    delegate: Region {
      required property var modelData
      x: region.originX + modelData.x; y: region.originY + modelData.y
      width: modelData.width; height: modelData.height
    }
    onObjectAdded: function(index, object) {
      var parts = region.scanlines.slice(); parts.push(object); region.scanlines = parts
    }
    onObjectRemoved: function(index, object) {
      region.scanlines = region.scanlines.filter(function(part) { return part !== object })
    }
  }
}
