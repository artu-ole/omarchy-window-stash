"""Run the production Lua guard against owned windows and an explicit event loop."""
from pathlib import Path
import shutil
import subprocess
import unittest


SOURCE = Path(__file__).resolve().parents[1]/"controller/focus.lua"
PRELUDE = r'''
local callbacks,timers,windows={},{},{}
local active,clears=nil,0
local monitor={name="HEADLESS-1",id=1,active_workspace={id=10}}
function monitor:set_special_workspace(args)
 assert(next(args)==nil,"Guard changed something other than the overlay")
 self.active_special_workspace=nil;clears=clears+1
end
hl={}
function hl.get_window(selector) return windows[selector:gsub("^address:","")] end
function hl.get_active_window() return active end
function hl.get_active_monitor() return monitor end
function hl.on(event,fn)
 local row={fn=fn,enabled=true};callbacks[event]=callbacks[event] or {};table.insert(callbacks[event],row)
 return {remove=function() row.enabled=false end}
end
function hl.timer(fn,opts)
 assert(opts.type=="oneshot" and opts.timeout==1)
 local timer={fn=fn,enabled=true,fired=false};table.insert(timers,timer)
 function timer:set_enabled(value)
  assert(not (value and self.fired),"An expired one-shot cannot be rescheduled")
  self.enabled=value
 end
 return timer
end
local function emit(event,...)
 for _,row in ipairs(callbacks[event] or {}) do if row.enabled then row.fn(...) end end
end
local function fire(timer)
 if timer.enabled then timer.enabled=false;timer.fired=true;timer.fn() end
end
local function create(n)
 local window={address="0x"..n,pid=100+n,stable_id=1000+n,mapped=true,
  tags={"window-stash-owned-"..n},workspace={name="special:window-stash",id=-98},monitor=monitor,
  size={x=640,y=400},floating=true}
 windows[window.address]=window
 local record={address=window.address,pid=window.pid,stable_id=window.stable_id,tag=window.tags[1]}
 return window,record
end
local function closing(window)
 active=window;emit("window.close",window);window.mapped=false;windows[window.address]=nil
end
local function focused(window,reason)
 active=window;monitor.active_special_workspace=window and window.workspace or nil
 emit("window.active",window,reason or 12)
end
local g=dofile(arg[1])
'''


@unittest.skipUnless(shutil.which("lua"), "Standalone Lua interpreter unavailable")
class FocusGuardTests(unittest.TestCase):
    def run_lua(self, body):
        result = subprocess.run(["lua", "-", str(SOURCE)], input=PRELUDE+body,
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_closure_only_hides_the_exact_automatic_private_overlay(self):
        self.run_lua('''
local a,ra=create(1);local b,rb=create(2)
assert(g.register(ra) and g.register(rb))
closing(a);focused(b);fire(timers[1])
assert(clears==1 and g.cleared==1 and not monitor.active_special_workspace)
assert(b.mapped and b.workspace.name=="special:window-stash" and b.floating)
assert(b.tags[1]==rb.tag and b.size.x==640 and b.size.y==400)
''')

    def test_multiple_closures_use_fresh_one_shots(self):
        self.run_lua('''
local a,ra=create(1);local b,rb=create(2);local c,rc=create(3)
g.sync({ra,rb,rc})
closing(a);focused(b);fire(timers[1]);assert(clears==1)
closing(b);focused(c);assert(#timers==2);fire(timers[2])
assert(clears==2 and g.cleared==2)
''')

    def test_close_uses_the_actual_focused_output_instead_of_the_source_monitor(self):
        self.run_lua('''
local a,ra=create(1);local b,rb=create(2)
local source_monitor={name="SOURCE",id=9,active_workspace={id=90}}
a.monitor=source_monitor;g.sync({ra,rb})
closing(a);focused(b);fire(timers[1])
assert(clears==1 and source_monitor.active_special_workspace==nil)
''')

    def test_external_activation_without_a_close_witness_is_untouched(self):
        self.run_lua('''
local a,ra=create(1);g.register(ra)
for _,reason in ipairs({12,2,3,6,14}) do focused(a,reason) end
assert(#timers==0 and clears==0 and monitor.active_special_workspace==a.workspace)
''')

    def test_unregistered_inactive_public_and_already_visible_closures_do_not_arm(self):
        self.run_lua('''
local a,ra=create(1);local b,rb=create(2);g.register(ra);g.register(rb)
active=b;emit("window.close",a);assert(#timers==0)
local c=create(3);closing(c);assert(#timers==0)
active=a;monitor.active_special_workspace=a.workspace;emit("window.close",a);assert(#timers==0)
monitor.active_special_workspace=nil;a.workspace={name="10",id=10}
active=a;emit("window.close",a);assert(#timers==0 and clears==0)
''')

    def test_identity_scope_and_overlay_changes_cancel_the_pending_action(self):
        mutations = (
            "b.pid=999", "b.stable_id=999", "b.tags={}", "b.mapped=false",
            'b.workspace={name="11",id=11}', "monitor.id=99", 'monitor.name="OTHER"',
            "monitor.active_workspace={id=20}", "monitor.active_special_workspace=nil",
            "monitor.active_special_workspace={id=-99,name='special:window-stash'}",
            "windows[a.address]={pid=999,stable_id=999,mapped=true}",
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.run_lua('''
local a,ra=create(1);local b,rb=create(2);g.sync({ra,rb})
closing(a);focused(b)
'''+mutation+'''
fire(timers[1]);assert(clears==0)
''')

    def test_newer_focus_and_authoritative_resync_cancel_pending_cleanup(self):
        for interruption in ("focused(b,3)", "focused(nil,6)",
                             "local c,rc=create(3);g.register(rc);focused(c,12)",
                             "g.sync({rb})", "g.unregister(rb)"):
            with self.subTest(interruption=interruption):
                self.run_lua('''
local a,ra=create(1);local b,rb=create(2);g.sync({ra,rb})
closing(a);focused(b)
'''+interruption+'''
fire(timers[1]);assert(clears==0)
''')

    def test_stale_timer_does_not_apply_to_a_newer_close(self):
        self.run_lua('''
local a,ra=create(1);local b,rb=create(2);local c,rc=create(3);g.sync({ra,rb,rc})
closing(a);focused(b)
monitor.active_special_workspace=nil;closing(b);focused(c)
timers[1].fn();assert(clears==0)
fire(timers[2]);assert(clears==1)
''')

    def test_registration_is_exact_and_prunes_old_public_records(self):
        self.run_lua('''
local a,ra=create(1);local b,rb=create(2)
local wrong={address=ra.address,pid=999,stable_id=ra.stable_id,tag=ra.tag}
assert(not g.register(wrong));assert(g.register(ra))
a.workspace={name="10",id=10};assert(g.register(rb))
assert(g.records[a.address]==nil and g.records[b.address])
g.unregister({address=rb.address,pid=999,stable_id=rb.stable_id,tag=rb.tag})
assert(g.records[b.address]);g.unregister(rb);assert(not g.records[b.address])
ra.stable_id=nil;a.workspace={name="special:window-stash",id=-98}
assert(g.register(ra) and g.records[a.address].stable_id==a.stable_id)
''')

    def test_stop_removes_only_its_observers_and_cancels_pending_timers(self):
        self.run_lua('''
local foreign=0;hl.on("window.active",function() foreign=foreign+1 end)
local a,ra=create(1);local b,rb=create(2);g.sync({ra,rb})
assert(dofile(arg[1])==g and #callbacks["window.close"]==1)
closing(a);focused(b);g.stop();fire(timers[1])
assert(clears==0 and _community_window_stash_focus==nil and next(g.records)==nil)
focused(b,3);assert(foreign==2)
local replacement=dofile(arg[1]);assert(replacement~=g)
''')


if __name__ == "__main__":
    unittest.main()
