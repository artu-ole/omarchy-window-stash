pragma ComponentBehavior: Bound
import QtQuick
import Quickshell
import Quickshell.Hyprland
import Quickshell.Io

// Non-consuming compositor bindings observe clicks without a fullscreen input
// surface or focus grab, so the same click still reaches the underlying app.
Item {
  id:observer
  property bool watching:false
  property bool applied:false
  property bool initialized:false
  property bool ready:false
  property int clicks:0
  readonly property string owner:String(Date.now())+"-"+String(Math.random())
  signal clicked(real x,real y)
  function script(enabled) {
    return "local s=_community_window_stash_clicks; "
      + "if s and s.version~=1 then for _,b in ipairs(s.binds) do b:set_enabled(false) end; s=nil end; "
      + "if not s then s={version=1,binds={}}; _community_window_stash_clicks=s; "
      + "for button=272,279 do local b=hl.bind('mouse:'..button,function() "
      + "local p=hl.get_cursor_pos(); hl.dispatch(hl.dsp.event('window-stash:click,'..p.x..','..p.y)) "
      + "end,{non_consuming=true,transparent=true,ignore_mods=true,description='Window Stash click observer'}); "
      + "b:set_enabled(false); table.insert(s.binds,b); end end; "
      + "s.owner="+JSON.stringify(owner)+"; for _,b in ipairs(s.binds) do b:set_enabled("+(enabled ? "true" : "false")+") end"
  }
  function sync() {
    if (worker.running || (initialized && applied===watching)) return
    initialized=true; applied=watching; ready=false
    worker.command=["hyprctl","eval",script(applied)]; worker.running=true
  }
  onWatchingChanged:sync()
  Process {
    id:worker
    stdout:StdioCollector {}
    stderr:StdioCollector {}
    onExited:function(code) {
      observer.ready=code===0 && observer.applied
      if (code!==0) console.warn("Window Stash click observer could not update")
      Qt.callLater(observer.sync)
    }
  }
  Connections {
    target:Hyprland
    function onRawEvent(event) {
      if (event.name==="configreloaded") { observer.initialized=false; observer.sync() }
      if (!observer.watching || event.name!=="custom") return
      var parts=String(event.data || "").split(",")
      if (parts.length===3 && parts[0]==="window-stash:click") { observer.clicks++; observer.clicked(Number(parts[1]),Number(parts[2])) }
    }
  }
  Component.onCompleted:sync()
  // Disable exact handles. Hyprland 0.56's handle.remove() also removes other
  // bindings for the same button, so retain/reuse these disabled handles until
  // the next compositor config reload instead of removing user bindings.
  Component.onDestruction:Quickshell.execDetached(["hyprctl","eval",
    "local s=_community_window_stash_clicks; if s and s.owner=="+JSON.stringify(owner)
    +" then for _,b in ipairs(s.binds) do b:set_enabled(false) end end"])
}
