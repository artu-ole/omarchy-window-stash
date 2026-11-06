pragma ComponentBehavior: Bound
import QtQuick
import "Motion.js" as Motion

Item {
  id: artwork
  property url source
  property size sourceSize:Qt.size(width,height)
  property string animations:"full"
  property string animationSpeed:"normal"
  readonly property int status:incoming.status
  readonly property bool animating:blend.running
  property url previous
  property url lastSource
  property bool initialized:false
  property bool resetting:false
  property real mix:1
  property int crossfadeSerial:0
  property int frames:0
  Behavior on mix { enabled:!artwork.resetting; NumberAnimation { id:blend; duration:Motion.duration(artwork.animations,160,100,artwork.animationSpeed); easing.type:Easing.OutCubic } }
  onMixChanged: {
    if (mix>0 && mix<1) frames++
    if (mix===1) previous=""
  }
  onSourceChanged: {
    if (!initialized) { lastSource=source; return }
    if (source===lastSource) return
    crossfadeSerial++; frames=0
    blend.stop(); previous=lastSource; lastSource=source
    if (animations==="off") { mix=1; previous="" }
    else { resetting=true; mix=0; resetting=false; ready.restart() }
  }
  onAnimationsChanged:if (animations==="off") { blend.complete(); mix=1; previous="" }
  Timer { id:ready; interval:1; onTriggered:if (incoming.status!==Image.Loading) artwork.mix=1 }
  Image {
    anchors.fill:parent
    source:artwork.previous
    sourceSize:artwork.sourceSize
    fillMode:Image.PreserveAspectFit
    opacity:1-artwork.mix
    visible:artwork.previous!==""
  }
  Image {
    id:incoming
    anchors.fill:parent
    source:artwork.source
    sourceSize:artwork.sourceSize
    fillMode:Image.PreserveAspectFit
    opacity:artwork.mix
    onStatusChanged:if (status!==Image.Loading && artwork.mix<1) ready.restart()
  }
  Component.onCompleted: { lastSource=source; initialized=true }
}
