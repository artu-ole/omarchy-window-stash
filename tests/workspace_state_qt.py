#!/usr/bin/env python3
"""Use the production workspace binding with stale native monitor objects."""
import os
from pathlib import Path
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
binding = next(line for line in (ROOT/'ui/StashSurface.qml').read_text().splitlines()
               if line.strip().startswith('readonly property int activeWorkspaceId:'))
with tempfile.TemporaryDirectory(prefix='stash-workspace-state-') as directory:
    folder = Path(directory)
    for name in ('runtime', 'config', 'cache'):
        (folder/name).mkdir(mode=0o700)
    (folder/'shell.qml').write_text('''import QtQuick
import Quickshell
ShellRoot {
  id:root
  property var monitor:null
  property var liveMonitor:null
  property int phase:0
''' + binding + '''
  function check(expected,message) {
    if(activeWorkspaceId!==expected) throw new Error(message+": "+activeWorkspaceId+" != "+expected)
  }
  Timer {
    interval:20;repeat:true;running:true
    onTriggered: {
      try {
        if(root.phase===0) {
          root.check(-1,"Unknown output must not select another workspace")
          root.liveMonitor={activeWorkspace:{id:1}}
        } else if(root.phase===1) {
          root.check(1,"Native state should provide an initial fallback")
          root.monitor={activeWorkspace:{id:1524843}}
        } else if(root.phase===2) {
          root.check(1524843,"A stale native workspace must not override the compositor snapshot")
          root.liveMonitor={activeWorkspace:{id:2}}
        } else if(root.phase===3) {
          root.check(1524843,"A later cached event must not undo the current snapshot")
          root.monitor={activeWorkspace:{id:1524844}}
        } else if(root.phase===4) {
          root.check(1524844,"Workspace changes must follow fresh compositor data")
          root.monitor=null
        } else if(root.phase===5) {
          root.check(2,"A removed snapshot should safely fall back during discovery")
          root.monitor={activeWorkspace:{id:-27}}
        } else if(root.phase===6) {
          root.check(-27,"Named workspace identities must remain valid")
          console.log("WORKSPACE_STATE_QT_PASS");Qt.quit()
        }
        root.phase++
      } catch(error) {console.error("WORKSPACE_STATE_QT_FAIL: "+error);Qt.exit(1)}
    }
  }
}
''')
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen', QT_QPA_PLATFORMTHEME='generic',
               QSG_RHI_BACKEND='software', XDG_RUNTIME_DIR=str(folder/'runtime'),
               XDG_CONFIG_HOME=str(folder/'config'), XDG_CACHE_HOME=str(folder/'cache'),
               DBUS_SESSION_BUS_ADDRESS='unix:path=/dev/null')
    for name in ('WAYLAND_DISPLAY', 'DISPLAY', 'HYPRLAND_INSTANCE_SIGNATURE'):
        env.pop(name, None)
    result = subprocess.run(['qs', '-p', str(folder/'shell.qml')], env=env,
                            capture_output=True, text=True, timeout=8)
    output = result.stdout+result.stderr
    assert result.returncode == 0 and 'WORKSPACE_STATE_QT_PASS' in output, output
    assert not any(value in output for value in ('Binding loop', 'TypeError', 'ReferenceError')), output
    print('Qt workspace state: compositor authority, stale native cache, hotplug fallback and named workspaces passed')
