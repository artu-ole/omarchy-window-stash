#!/usr/bin/env python3
"""Use the production layer-focus bindings without compositor IPC or input."""
import os
from pathlib import Path
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
source = (ROOT/'ui/StashSurface.qml').read_text()
bindings = '\n'.join(next(line for line in source.splitlines() if line.strip().startswith(prefix))
                     for prefix in ('readonly property bool previewInteractionOwnsScreen:', 'readonly property bool keyboardOpen:'))
begin = source.index('  onKeyboardOpenChanged:')
handler = source[begin:source.index('  onDialogOpenChanged:', begin)]
timer = next(line for line in source.splitlines() if 'id: primeFocus;' in line)
begin = source.index('  WlrLayershell.keyboardFocus:')
focus = source[begin:source.index('  visible: retainingPointerFocus', begin)]
focus = focus.replace('  WlrLayershell.keyboardFocus:', '  readonly property int requestedKeyboardFocus:')

with tempfile.TemporaryDirectory(prefix='stash-preview-keyboard-focus-') as directory:
    folder = Path(directory)
    for name in ('runtime', 'config', 'cache'):
        (folder/name).mkdir(mode=0o700)
    (folder/'shell.qml').write_text('''import QtQuick
import Quickshell
import Quickshell.Wayland
ShellRoot {
  id:surface
  property int phase:0
  property int ticks:0
  property bool dialogOpen:false
  property bool floatingPreviewsExpanded:false
  property bool contextMenuOpen:false
  property bool retainingPointerFocus:false
  property bool focusPrimed:false
  property QtObject screen:QtObject {property string name:"test"}
  QtObject {id:floatingDock;property bool open:false}
  QtObject {
    id:stash
    property var previewInteractionRequest:null
    property var previewInteractionPendingRequest:null
    property bool previewInteractionStopping:false
  }
''' + bindings + '\n' + handler + timer + '\n' + focus + '''
  function check(value,message) {if(!value) throw new Error(message)}
  Timer {
    interval:20;repeat:true;running:true
    onTriggered: {
      try {
        if(surface.phase===0) {
          surface.floatingPreviewsExpanded=true
          check(surface.requestedKeyboardFocus===WlrKeyboardFocus.Exclusive,"Ordinary chooser lost initial keyboard priming")
        } else if(surface.phase===1) {
          stash.previewInteractionPendingRequest={id:"first",monitor:"test"}
          check(!surface.keyboardOpen && surface.requestedKeyboardFocus===WlrKeyboardFocus.None,"Queued input competed with chooser keyboard priming")
        } else if(surface.phase===2) {
          stash.previewInteractionRequest={id:"first",monitor:"test"}
          stash.previewInteractionPendingRequest=null
          check(surface.requestedKeyboardFocus===WlrKeyboardFocus.None,"Activating input briefly reopened chooser keyboard demand")
          stash.previewInteractionStopping=true
          surface.ticks=0
        } else if(surface.phase===3) {
          check(surface.requestedKeyboardFocus===WlrKeyboardFocus.None,"Stopping restored chooser focus before native release acknowledgement")
          if(++surface.ticks<6) return
          check(surface.requestedKeyboardFocus===WlrKeyboardFocus.None,"A stale priming timer stole the interactive app's keyboard")
          stash.previewInteractionRequest=null
          stash.previewInteractionStopping=false
          check(surface.keyboardOpen && surface.requestedKeyboardFocus===WlrKeyboardFocus.Exclusive,"Acknowledged release did not restore chooser priming")
        } else if(surface.phase===4) {
          if(!surface.focusPrimed) return
          check(surface.requestedKeyboardFocus===WlrKeyboardFocus.OnDemand,"Chooser did not return to on-demand keyboard focus")
          stash.previewInteractionRequest={id:"other",monitor:"DP-other"}
          check(surface.requestedKeyboardFocus===WlrKeyboardFocus.OnDemand,"A different monitor's input incorrectly suppressed this chooser")
        } else if(surface.phase===5) {
          stash.previewInteractionPendingRequest={id:"replacement",monitor:"test"}
          check(surface.requestedKeyboardFocus===WlrKeyboardFocus.None,"Pending replacement did not suppress chooser demand")
          surface.dialogOpen=true
          check(surface.requestedKeyboardFocus===WlrKeyboardFocus.Exclusive,"An explicit dialog could not take keyboard precedence")
        } else if(surface.phase===6) {
          surface.dialogOpen=false
          check(surface.requestedKeyboardFocus===WlrKeyboardFocus.None,"Closing a dialog stole pending input's keyboard")
          surface.contextMenuOpen=true
          check(surface.requestedKeyboardFocus===WlrKeyboardFocus.Exclusive,"The explicit plugin context menu lost keyboard precedence")
        } else if(surface.phase===7) {
          surface.contextMenuOpen=false
          stash.previewInteractionPendingRequest=null;stash.previewInteractionRequest=null
          surface.floatingPreviewsExpanded=false
          check(surface.requestedKeyboardFocus===WlrKeyboardFocus.None,"Closing the chooser retained keyboard demand")
          surface.retainingPointerFocus=true
          check(surface.requestedKeyboardFocus===WlrKeyboardFocus.OnDemand,"Pointer-release focus retention regressed")
        } else if(surface.phase===8) {
          surface.retainingPointerFocus=false;floatingDock.open=true
          check(surface.requestedKeyboardFocus===WlrKeyboardFocus.Exclusive,"Ordinary dock keyboard priming regressed")
          floatingDock.open=false
          check(surface.requestedKeyboardFocus===WlrKeyboardFocus.None,"Closing the dock retained keyboard demand")
          console.log("PREVIEW_KEYBOARD_FOCUS_QT_PASS");Qt.quit()
        }
        surface.phase++
      } catch(error) {console.error("PREVIEW_KEYBOARD_FOCUS_QT_FAIL: "+error);Qt.exit(1)}
    }
  }
}
''')
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen', QT_QPA_PLATFORMTHEME='generic',
               QSG_RHI_BACKEND='software', XDG_RUNTIME_DIR=str(folder/'runtime'),
               XDG_CACHE_HOME=str(folder/'cache'), XDG_CONFIG_HOME=str(folder/'config'),
               DBUS_SESSION_BUS_ADDRESS='unix:path=/dev/null')
    for key in ('WAYLAND_DISPLAY', 'DISPLAY', 'HYPRLAND_INSTANCE_SIGNATURE'):
        env.pop(key, None)
    result = subprocess.run(['qs', '-p', str(folder/'shell.qml')], env=env,
                            capture_output=True, text=True, timeout=8)
    output = result.stdout+result.stderr
    assert result.returncode == 0 and 'PREVIEW_KEYBOARD_FOCUS_QT_PASS' in output, output
    assert not any(message in output for message in ('Binding loop', 'ReferenceError', 'TypeError', 'Cannot assign', 'Cannot read')), output
    print('Qt preview keyboard focus: queued/active/stopping owners, delayed priming, release acknowledgement, monitor ownership and explicit overlay precedence passed')
