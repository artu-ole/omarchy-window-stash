"""Execute the real observer's generated Lua without touching the compositor."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ClickObserverTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('lua') and shutil.which('node'), 'Standalone Lua and Node interpreters unavailable')
    def test_button_identity_non_consuming_bindings_and_legacy_handle_migration(self):
        output = subprocess.check_output(['node', str(ROOT/'tests/context_clicks.test.cjs'), '--observer-scripts'], text=True, timeout=10)
        scripts = json.loads(output.strip().splitlines()[-1])
        source = '''
local legacy={enabled=true,set_enabled=function(self,v) self.enabled=v end}
_community_window_stash_clicks={version=2,binds={legacy}}
local binds={}; local event; local timers={}; local repeatTimers={}; local events={}; local cursor={x=1044,y=284}
hl={bind=function(chord,fn,options)
  assert(options.non_consuming and options.transparent and options.ignore_mods)
  local b={chord=chord,fn=fn,options=options,set_enabled=function(self,v) self.enabled=v end}
  table.insert(binds,b); return b
end,get_cursor_pos=function() return cursor end,
timer=function(fn,options)
  if options.type=='oneshot' then assert(options.timeout==1); table.insert(timers,fn); return end
  assert(options.type=='repeat' and options.timeout==32)
  local timer={enabled=true,fn=fn,set_enabled=function(self,v) self.enabled=v end}
  table.insert(repeatTimers,timer); return timer
end,
dsp={event=function(v) return v end},dispatch=function(v) event=v; table.insert(events,v) end}
local function flush() local pending=timers; timers={}; for _,fn in ipairs(pending) do fn() end end
'''+scripts['enabled']+'''
assert(not legacy.enabled and #binds==16)
for i=1,8 do
  local press,release=binds[i*2-1],binds[i*2]
  assert(press.enabled and release.enabled and not press.options.release and release.options.release)
  press.fn(); assert(event=='window-stash:click,1044,284,'..(271+i)..',press')
  release.fn(); assert(event=='window-stash:click,1044,284,'..(271+i)..',press')
  flush(); assert(event=='window-stash:click,1044,284,'..(271+i)..',release')
end
binds[1].fn()
'''+scripts['disabled']+'''
assert(#binds==16 and _community_window_stash_clicks.version==4)
for _,b in ipairs(binds) do assert(b.enabled) end
binds[2].fn()
for _,b in ipairs(binds) do assert(b.enabled) end
flush()
for _,b in ipairs(binds) do assert(not b.enabled) end
'''+scripts['enabled']+'''
binds[1].fn(); binds[3].fn()
'''+scripts['disabled']+'''
binds[2].fn(); flush()
for _,b in ipairs(binds) do assert(b.enabled) end
binds[4].fn(); flush()
for _,b in ipairs(binds) do assert(not b.enabled) end
'''+scripts['enabled']+'''
binds[1].fn()
'''+scripts['reset']+'''
assert(next(_community_window_stash_clicks.held)==nil)
for _,b in ipairs(binds) do assert(not b.enabled) end
assert(#repeatTimers==1 and not repeatTimers[1].enabled)
'''+scripts['tracking']+'''
assert(#repeatTimers==1 and repeatTimers[1].enabled)
assert(event=='window-stash:pointer,1044,284')
local sent=#events
repeatTimers[1].fn(); assert(#events==sent)
cursor={x=2000,y=300}; repeatTimers[1].fn()
assert(#events==sent+1 and event=='window-stash:pointer,2000,300')
'''+scripts['tracking']+'''
assert(#events==sent+1 and #repeatTimers==1)
'''+scripts['stopTracking']+'''
assert(not repeatTimers[1].enabled)
repeatTimers[1].fn(); assert(#events==sent+1)
'''+scripts['tracking']+'''
assert(repeatTimers[1].enabled and #events==sent+2)
'''+scripts['resetTracking']+'''
assert(#events==sent+3 and #repeatTimers==1)
_community_window_stash_clicks.owner='other-owner'
'''+scripts['tracking']+'''
assert(#events==sent+4 and #repeatTimers==1)
_community_window_stash_clicks.owner='other-owner'; _community_window_stash_clicks.held[272]=true
'''+scripts['cleanup']+'''
assert(repeatTimers[1].enabled and _community_window_stash_clicks.held[272])
_community_window_stash_clicks.owner='test-owner'
'''+scripts['cleanup']+'''
assert(not repeatTimers[1].enabled and not _community_window_stash_clicks.tracking)
assert(not next(_community_window_stash_clicks.held))
for _,b in ipairs(binds) do assert(not b.enabled) end
'''
        result = subprocess.run(['lua', '-'], input=source, text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
