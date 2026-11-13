#!/usr/bin/env python3
"""Keyboard/focus proof for hidden interactive previews in a disposable desktop.

The owned GTK sources log real entry text, keys and close requests. An exact
temporary runtime binding exercises the same unqualified window.close dispatcher
as Omarchy's Super+Q/Super+W, without touching the user's shortcuts. No execution
or input occurs at import time.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import time
import uuid

from desktop_test import desktop_test
from interactive_bridge import begin, end, events, local_point, native_status, spawn_fixture
from live import command, configure, h, wait
from native_session import NativeSession
from preview import PreviewBridge
from stash import SPECIAL, lua


def content_click(session, rect, size, x, y):
    point = local_point(session,rect,x/size[0],y/size[1])
    session.move(point[0]-1,point[1])
    session.pointer.click(*session.point(*point))


def text(log):
    values = events(log,'text')
    return values[-1]['text'] if values else ''


def key_count(log, name, kind='key-press'):
    return sum(value.get('name') == name for value in events(log,kind))


def source_geometry(address):
    current = h.client(address)
    return current['workspace'],current['at'],current['size'],current['floating']


@desktop_test('Isolated interactive-preview native keyboard proof')
def main():
    assert os.environ.get('WINDOW_STASH_ISOLATED_TEST') == '1' and (Path.home()/'.window-stash-isolated').is_file(), \
        'Run only in the explicit disposable compositor'
    assert not command('list')['windows'], 'Keyboard proof requires an empty disposable stash'
    PreviewBridge(h).ensure()
    binding = '__window_stash_keyboard_proof_'+str(os.getpid())
    occupied = {str(value.get('key','')).lower() for value in h.read('binds') if value.get('modmask') == 76}
    proof_key = next(('F'+str(number) for number in range(24, 12, -1) if 'f'+str(number) not in occupied), None)
    assert proof_key, 'No unused high function chord is available for the owned close proof'
    chord = 'SUPER + CTRL + ALT + '+proof_key
    matching = h.call('repl', 'return hl.get_config("input.resolve_binds_by_sym")')
    assert matching in ('true', 'false')
    with tempfile.TemporaryDirectory(prefix='stash-keyboard-') as temporary, NativeSession() as session:
        configure('presentation','dock')
        configure('hoverPreview','off')
        log, control_log = Path(temporary)/'source.jsonl',Path(temporary)/'control.jsonl'
        address = spawn_fixture(session,log)
        control = spawn_fixture(session,control_log)
        h.dispatch('window.move',window='address:'+control,x=session.monitor['x']+50,y=session.monitor['y']+50,relative=False)
        record = session.park(address)
        original = source_geometry(address)
        size = original[2]
        h.dispatch('focus',window='address:'+control)
        rect = dict(x=session.monitor['x']+400,y=session.monitor['y']+300,width=400,height=280)
        owner = uuid.uuid4().hex
        held = None
        try:
            begin(owner,record,session.monitor['name'],rect,keyboard=True)
            state = native_status(owner)
            assert state['active'] and state['keyboard'], ('Native keyboard mode is unavailable',state)
            assert not state['keyboardFocused'], 'Beginning interaction stole keyboard focus before a click'
            session.move(*local_point(session,rect,.75,.75))
            assert not native_status(owner)['keyboardFocused'], 'Hovering a miniature stole keyboard focus'
            assert h.read('activewindow').get('address') == control, 'Hover changed the ordinary focused window'

            content_click(session,rect,size,120,46)
            wait(lambda:native_status(owner)['keyboardFocused'],'Clicking the source did not acquire keyboard focus')
            control_keys = len(events(control_log,'key-press'))
            phrase = 'Hello preview 123'
            session.keys(phrase)
            wait(lambda:text(log) == phrase,'Typing did not reach the hidden source entry')
            assert len(events(control_log,'key-press')) == control_keys, 'Typing leaked to the visible control'
            begin(owner,record,session.monitor['name'],rect,keyboard=True)
            session.keys('-M','ctrl','-k','a','-m','ctrl','replacement')
            wait(lambda:text(log) == 'replacement','Ctrl+A and replacement did not use native application selection')
            begin(owner,record,session.monitor['name'],rect,keyboard=True)
            session.keys('-M','ctrl','-k','a','-k','c','-m','ctrl','temporary')
            wait(lambda:text(log) == 'temporary','Selected source text did not replace after copy')
            begin(owner,record,session.monitor['name'],rect,keyboard=True)
            session.keys('-M','ctrl','-k','a','-k','v','-m','ctrl')
            wait(lambda:text(log) == 'replacement','Native Ctrl+C/Ctrl+V clipboard failed on the hidden entry')
            assert source_geometry(address) == original and original[0]['name'] == SPECIAL, \
                'Keyboard input restored, moved or resized the stashed source'
            assert h.read('activeworkspace')['id'] == session.workspace, 'Keyboard input changed the visible workspace'
            print('PASS click-only keyboard focus, actual entry typing, Ctrl+A replacement, native copy/paste and unchanged hidden geometry/workspace',flush=True)

            begin(owner,record,session.monitor['name'],rect,keyboard=True)
            content_click(session,rect,size,size[0]*.75,size[1]*.75)
            escapes = key_count(log,'Escape')
            session.keys('-k','Escape')
            wait(lambda:key_count(log,'Escape') == escapes+1,'Plain Escape did not reach the application')
            assert native_status(owner)['active'], 'Plain Escape unexpectedly exited interactive mode'
            print('PASS plain Escape remains an application key',flush=True)

            end(owner)
            for keyboard, key, modifiers, exit_keys in (
                    (False, 'Escape', 12, ('-M','ctrl','-M','alt','-k','Escape','-m','alt','-m','ctrl')),
                    (True, 'Escape', 12, ('-M','ctrl','-M','alt','-k','Escape','-m','alt','-m','ctrl')),
                    (True, 'F8', 4, ('-M','ctrl','-k','F8','-m','ctrl'))):
                owner = uuid.uuid4().hex
                begin(owner,record,session.monitor['name'],rect,keyboard=keyboard,
                      exit_shortcut=dict(modmask=modifiers,key=key))
                content_click(session,rect,size,size[0]*.75,size[1]*.75)
                source_escapes = key_count(log,key)
                control_escapes = key_count(control_log,key)
                source_releases = key_count(log,key,'key-release')
                control_releases = key_count(control_log,key,'key-release')
                session.keys(*exit_keys)
                wait(lambda:not native_status(owner)['active'],'Configured exit chord did not end the session')
                assert native_status(owner)['reason'] == 'shortcut', native_status(owner)
                assert key_count(log,key) == source_escapes and key_count(control_log,key) == control_escapes, \
                    'Consumed exit shortcut leaked its press to an application'
                assert key_count(log,key,'key-release') == source_releases and key_count(control_log,key,'key-release') == control_releases, \
                    'Consumed exit shortcut leaked an orphan release'
            print('PASS configurable exit chord works in mouse and keyboard modes without leaked key presses/releases',flush=True)

            owner = uuid.uuid4().hex
            begin(owner,record,session.monitor['name'],rect,keyboard=True)
            content_click(session,rect,size,size[0]*.75,size[1]*.75)
            pressed, released = key_count(log,'F8'),key_count(log,'F8','key-release')
            held = subprocess.Popen(['wtype','-s','100','-P','F8','-s','1000','-p','F8','-s','100'],
                                    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            wait(lambda:key_count(log,'F8') > pressed,'Held keyboard fixture did not reach the application')
            wait(lambda:native_status(owner)['heldKeys'] > 0,'Native bridge did not track the held application key')
            end(owner)
            wait(lambda:key_count(log,'F8','key-release') > released,'Exiting did not release the held application key')
            assert not native_status(owner)['active'] and native_status(owner)['heldKeys'] == 0, \
                'Native keyboard ownership survived explicit exit'
            held.wait(timeout=4);held = None
            time.sleep(.1)
            assert key_count(log,'F8','key-release') == released+1, 'Physical release was delivered twice after exit'
            print('PASS explicit exit releases held keys exactly once and restores ordinary routing',flush=True)

            owner = uuid.uuid4().hex
            begin(owner,record,session.monitor['name'],rect,keyboard=True)
            content_click(session,rect,size,size[0]*.75,size[1]*.75)
            control_presses = len(events(control_log,'press'))
            control_letters = key_count(control_log,'g')
            source_letters = key_count(log,'g')
            session.pointer.click(*session.point(200,250))
            wait(lambda:not native_status(owner)['active'],'Outside click did not end keyboard interaction')
            wait(lambda:len(events(control_log,'press')) == control_presses+1,'Outside click did not reach its visible destination once')
            session.keys('g')
            wait(lambda:key_count(control_log,'g') == control_letters+1,'Outside click did not restore visible keyboard focus')
            assert key_count(log,'g') == source_letters, 'Keys continued reaching the source after outside exit'
            assert h.client(control), 'Outside focus restoration closed the visible control'
            print('PASS outside click reaches its destination once and subsequent typing reaches that visible application',flush=True)

            # Bind only an unoccupied high function chord, disable the exact
            # returned handle in finally, and use the stock close dispatcher.
            h.call('repl','_G.'+binding+'=assert(hl.bind('+lua(chord)+',hl.dsp.window.close(),{description="Window Stash isolated keyboard close proof"}));return true')
            h.eval('hl.config({input={resolve_binds_by_sym=true}})')
            owner = uuid.uuid4().hex
            begin(owner,record,session.monitor['name'],rect,keyboard=True)
            content_click(session,rect,size,size[0]*.75,size[1]*.75)
            session.keys('-M','logo','-M','ctrl','-M','alt','-s','60','-k',proof_key,'-s','60','-m','alt','-m','ctrl','-m','logo')
            wait(lambda:not h.client(address),'Default-focus WM close did not target the hidden interactive window')
            assert events(log,'close'), 'The hidden source did not receive its normal close request'
            assert h.client(control) and not events(control_log,'close'), 'WM close incorrectly targeted the visible underlying control'
            assert h.read('activeworkspace')['id'] == session.workspace, 'WM close changed the visible workspace'
            wait(lambda:not native_status(owner)['active'],'Closing the source did not release native interaction')
            assert not any(value['id'] == record['id'] for value in command('list')['windows']), 'Closed source retained a stash record'
            print('PASS unqualified Omarchy-style WM close targets the hidden source, preserves the visible control and cleans up the stash',flush=True)
        except BaseException:
            print('Keyboard proof diagnostics:',native_status(owner),events(log)[-20:],events(control_log)[-12:],flush=True)
            raise
        finally:
            end(owner)
            if held is not None:
                try:held.wait(timeout=4)
                except subprocess.TimeoutExpired:held.terminate();held.wait(timeout=3)
            h.call('repl','if _G.'+binding+' then _G.'+binding+':set_enabled(false);_G.'+binding+'=nil end;return true')
            h.eval('hl.config({input={resolve_binds_by_sym='+matching+'}})')


if __name__ == '__main__':
    main()
