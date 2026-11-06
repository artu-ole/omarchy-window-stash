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
  property bool tracking:false
  property bool trackingApplied:false
  property bool applied:false
  property bool initialized:false
  property bool ready:false
  property int clicks:0
  readonly property string owner:String(Date.now())+"-"+String(Math.random())
  property bool resetRequested:false
  signal clicked(real x,real y,int button)
  signal released(real x,real y,int button)
  signal moved(real x,real y)
  function script(enabled,reset,tracking) {
    return "local s=_community_window_stash_clicks; "
      + "if s and s.version~=4 then for _,b in ipairs(s.binds) do b:set_enabled(false) end; if s.timer then s.timer:set_enabled(false) end; s=nil end; "
      + "if not s then s={version=4,binds={},held={}}; _community_window_stash_clicks=s; "
      + "for button=272,279 do local watchedButton=button; "
      + "local function emit(phase) local p=hl.get_cursor_pos(); hl.dispatch(hl.dsp.event('window-stash:click,'..p.x..','..p.y..','..watchedButton..','..phase)) end; "
      + "local press=hl.bind('mouse:'..button,function() s.held[watchedButton]=true; emit('press') end,"
      + "{non_consuming=true,transparent=true,ignore_mods=true,description='Window Stash click observer'}); "
      + "local release=hl.bind('mouse:'..button,function() if not s.held[watchedButton] then return end; s.held[watchedButton]=nil; "
      // Run after the compositor finishes delivering the physical release.
      + "hl.timer(function() emit('release'); if not s.watching and not next(s.held) then for _,b in ipairs(s.binds) do b:set_enabled(false) end end end,"
      + "{type='oneshot',timeout=1}) end,{release=true,non_consuming=true,transparent=true,ignore_mods=true,description='Window Stash click observer'}); "
      + "press:set_enabled(false); release:set_enabled(false); table.insert(s.binds,press); table.insert(s.binds,release); end; "
      + "s.poll=function() if not s.tracking then return end; local p=hl.get_cursor_pos(); if p.x~=s.x or p.y~=s.y then s.x=p.x; s.y=p.y; "
      + "hl.dispatch(hl.dsp.event('window-stash:pointer,'..p.x..','..p.y)) end end; "
      + "s.timer=hl.timer(s.poll,{type='repeat',timeout=32}); s.timer:set_enabled(false); end; "
      + (reset ? "s.held={}; " : "")
      + "local beginTracking="+(tracking ? "true" : "false")+" and ("+(reset ? "true" : "false")+" or not s.tracking or s.owner~="+JSON.stringify(owner)+"); "
      + "s.owner="+JSON.stringify(owner)+"; s.tracking="+(tracking ? "true" : "false")+"; "
      + "s.timer:set_enabled(s.tracking); if beginTracking then s.x=nil; s.y=nil; s.poll() end; "
      + "s.watching="+(enabled ? "true" : "false")+"; "
      + "local active=s.watching or next(s.held)~=nil; for _,b in ipairs(s.binds) do b:set_enabled(active) end"
  }
  function resetHeld() { resetRequested=true; initialized=false; sync() }
  function sync() {
    if (worker.running || (initialized && applied===watching && trackingApplied===tracking)) return
    initialized=true; applied=watching; trackingApplied=tracking; ready=false
    worker.command=["hyprctl","eval",script(applied,resetRequested,trackingApplied)]; resetRequested=false; worker.running=true
  }
  onWatchingChanged:sync()
  onTrackingChanged:sync()
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
      if (event.name!=="custom") return
      var parts=String(event.data || "").split(",")
      if (parts.length===3 && parts[0]==="window-stash:pointer" && observer.tracking
          && Number.isFinite(Number(parts[1])) && Number.isFinite(Number(parts[2]))) {
        observer.moved(Number(parts[1]),Number(parts[2])); return
      }
      var button=parts.length===5 ? Number(parts[3]) : 0
      if (parts[0]==="window-stash:click" && Number.isInteger(button) && button>=272 && button<=279
          && Number.isFinite(Number(parts[1])) && Number.isFinite(Number(parts[2]))) {
        if (parts[4]==="press") { observer.clicks++; observer.clicked(Number(parts[1]),Number(parts[2]),button) }
        else if (parts[4]==="release") observer.released(Number(parts[1]),Number(parts[2]),button)
      }
    }
  }
  Component.onCompleted:sync()
  // Disable exact handles. Hyprland 0.56's handle.remove() also removes other
  // bindings for the same button, so retain/reuse these disabled handles until
  // the next compositor config reload instead of removing user bindings.
  Component.onDestruction:Quickshell.execDetached(["hyprctl","eval",
    "local s=_community_window_stash_clicks; if s and s.owner=="+JSON.stringify(owner)
    +" then s.tracking=false; s.watching=false; s.held={}; if s.timer then s.timer:set_enabled(false) end; for _,b in ipairs(s.binds) do b:set_enabled(false) end end"])
}
