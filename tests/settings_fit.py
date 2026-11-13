#!/usr/bin/env python3
"""Native settings reachability on small, scaled and reserved work areas.

Run after installing this checkout. NativeSession restores preferences, stash,
focus and display geometry; only a temporary output and bar are created.
No application windows are needed.
"""
from contextlib import contextmanager
import importlib.util
import json
import math
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import time

from desktop_test import desktop_test
from live import ROOT, command, configure, h, shell, wait
from native_session import NativeSession
from stash import CHOICES, DEFAULTS


spec = importlib.util.spec_from_file_location('fit_shortcut_helpers', ROOT/'tests/shortcuts.py')
shortcut_helpers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shortcut_helpers)
SECTIONS = ('general', 'placement', 'appearance', 'motion', 'previews', 'interaction', 'shortcuts')
INTERACTION_CHOICES = ('floatingPreviewInteraction', 'floatingPreviewActivation', 'floatingPreviewKeyboard',
                       'floatingPreviewInteractionFps', 'floatingPreviewControls', 'floatingPreviewFullscreen')
EXIT_SHORTCUT = 'floatingPreviewExitShortcut'


def contained(rect, area, tolerance=1):
    return rect and rect['width'] > 0 and rect['height'] > 0 \
        and rect['x'] >= area['x']-tolerance and rect['y'] >= area['y']-tolerance \
        and rect['x']+rect['width'] <= area['x']+area['width']+tolerance \
        and rect['y']+rect['height'] <= area['y']+area['height']+tolerance


def choice(session, key):
    return next(c for c in session.surface()['settingControls'] if c['key'] == key)


def number(session, key):
    return next(c for c in session.surface()['numberControls'] if c['key'] == key)


def wheel(session, steps):
    viewport = session.surface()['settingsScroll']['rect']
    session.move(viewport['x']+3, viewport['y']+viewport['height']/2)
    pointer = session.pointer
    pointer.send(5, 5, pointer.uint(0))
    pointer.send(5, 7, pointer.uint(int(time.monotonic()*1000) & 0xffffffff)
                 + pointer.uint(0) + struct.pack('ii', steps*15*256, steps))
    pointer.send(5, 4)
    pointer.sync()


def drag_page(session, down):
    viewport = session.surface()['settingsScroll']['rect']
    x = viewport['x']+3
    start = viewport['y']+viewport['height']*(.8 if down else .2)
    end = viewport['y']+viewport['height']*(.2 if down else .8)
    session.move(x, start)
    session.pointer.button(True)
    for step in range(1, 7):
        session.move(x, start+(end-start)*step/6)
        time.sleep(.02)
    session.pointer.button(False)
    time.sleep(.1)


def reveal(session, rect_for):
    previous_down = None
    fine = False
    for attempt in range(60):
        surface = session.surface()
        viewport = surface['settingsScroll']['rect']
        rect = rect_for()
        assert contained(viewport, surface['usableArea']), ('Settings viewport escaped reserved bounds', viewport, surface['usableArea'])
        assert rect['width'] <= viewport['width']+1 and rect['height'] <= viewport['height']+1, \
            ('A control cannot fit inside its settings viewport', rect, viewport)
        if contained(rect, viewport):
            # Native wheel/drag scrolling can coast after a field first enters
            # view. Click only once it stops, using the final coordinates.
            stable_since = time.monotonic()
            settle_deadline = stable_since+2
            previous_y = surface['settingsScroll']['contentY']
            while time.monotonic() < settle_deadline:
                time.sleep(.04)
                surface = session.surface()
                viewport = surface['settingsScroll']['rect']
                rect = rect_for()
                if not contained(rect, viewport):
                    break
                current_y = surface['settingsScroll']['contentY']
                if abs(current_y-previous_y) > .1:
                    stable_since = time.monotonic()
                # Flickable can still consume a click to end wheel scrolling
                # after the content has reached its bounds and stopped moving.
                elif time.monotonic()-stable_since >= .5:
                    return rect
                previous_y = current_y
            if contained(rect, viewport):
                continue
        down = rect['y']+rect['height'] > viewport['y']+viewport['height']
        distance = rect['y']+rect['height']-viewport['y']-viewport['height'] if down else viewport['y']-rect['y']
        if previous_down is not None and down != previous_down:
            fine = True
        previous_down = down
        if attempt and attempt % 12 == 0:
            drag_page(session, down)
        else:
            steps = 1 if fine or distance <= viewport['height']/2 else min(20, math.ceil(distance/15))
            wheel(session, steps*(1 if down else -1))
        time.sleep(.035)
    raise AssertionError(('Control could not be revealed by native scrolling', rect_for(), session.surface()['settingsScroll']))


def open_settings(session):
    # Resizing the temporary output can leave the pointer outside it, causing
    # focus-follows-mouse to undo the earlier monitor-focus dispatch.
    area = session.surface()['usableArea']
    session.move(area['x']+area['width']/2, area['y']+area['height']/2)
    h.dispatch('focus', monitor=session.monitor['name'])
    shell('refresh')
    time.sleep(.1)  # Allow the service's 70 ms refresh debounce to fire.
    wait(lambda: not shell('status')['controllerBusy'] and not shell('status')['queueLength'],
         'Settings monitor refresh did not finish')
    shell('settings')
    try:
        wait(lambda: session.surface()['dialog']['visible'], 'Small-output settings did not open')
    except AssertionError:
        print('Settings target diagnostics:', shell('status')['dialog'],
              [{k: s[k] for k in ('screen', 'dialog', 'usableArea')} for s in shell('status')['surfaces']],
              [{k: m[k] for k in ('name', 'focused', 'width', 'height', 'scale')} for m in h.read('monitors')], flush=True)
        raise
    surface = session.surface()
    assert contained(surface['dialog'], surface['usableArea']), ('Settings card overlaps reserved edges', surface['dialog'], surface['usableArea'])
    assert surface['settingsScroll']['contentHeight'] > surface['settingsScroll']['rect']['height'], 'Small output did not exercise scrolling'


def dropdown(session, key, value=None, click_option=False):
    saved = shell('status')['settings'][key]
    rect = reveal(session, lambda: choice(session, key)['rect'])
    session.click(rect)
    try:
        wait(lambda: choice(session, key)['open'], 'Dropdown did not open: '+key)
    except AssertionError:
        print('Dropdown diagnostics:', key, rect, choice(session, key), session.surface()['settingsScroll'],
              h.read('cursorpos'), flush=True)
        raise
    popup = wait(lambda: choice(session, key)['popupRect'], 'Dropdown has no visible popup rectangle: '+key)
    assert contained(popup, session.surface()['usableArea']), ('Dropdown popup escaped the work area', key, popup)
    if value is None:
        session.keys('-k', 'Escape')
    else:
        values = list(CHOICES[key])
        # A bounded popup can overlap its trigger on a tiny display. Keep the
        # test pointer outside it while navigating so hover cannot reselect a
        # row that scrolls beneath the stationary cursor.
        area = session.surface()['usableArea']
        session.move(area['x']+1, area['y']+1)
        session.keys(*(['-k', 'Up']*len(values)), *(['-k', 'Down']*values.index(value)))
        if click_option:
            # The native ListView animates the selected row into view. Wait
            # for its actual geometry before clicking the first/ninth option.
            wait(lambda: contained(choice(session, key)['popupCurrentRect'], choice(session, key)['popupRect']),
                 'Selected dropdown row did not scroll into view: '+key)
            time.sleep(.25)
            row = choice(session, key)['popupCurrentRect']
            assert contained(row, choice(session, key)['popupRect']), 'Selected dropdown row left the visible popup'
            session.click(row)
        else:
            session.keys('-k', 'Return')
        try:
            wait(lambda: shell('status')['settings'][key] == value, 'Visible dropdown did not save '+key+'='+value)
        except AssertionError:
            print('Dropdown selection diagnostics:', key, value, choice(session, key), shell('status')['settings'][key], flush=True)
            raise
    wait(lambda: not choice(session, key)['open'], 'Dropdown did not close: '+key)
    assert shell('status')['settings'][key] == (saved if value is None else value), 'Closing a dropdown changed its value'


def all_controls(session):
    reached = set()
    for section in SECTIONS:
        if not next(s for s in session.surface()['settingSections'] if s['key'] == section).get('visible', True):
            continue
        reveal(session, lambda: next(s for s in session.surface()['settingSections'] if s['key'] == section)['rect'])
    for entry in session.surface()['settingControls']:
        if entry['visible']:
            dropdown(session, entry['key'])
            reached.add(entry['key'])
    for entry in session.surface()['numberControls']:
        if not entry['visible']:
            continue
        key = entry['key']
        session.click(reveal(session, lambda: number(session, key)['rect']))
        session.keys('-M', 'ctrl', '-k', 'a', '-m', 'ctrl', str(entry['value']), '-k', 'Return')
        wait(lambda: shell('status')['settings'][key] == entry['value'], 'Editing an unchanged numeric field changed it: '+key)
        reached.add(key)
    for entry in session.surface()['shortcutControls']:
        if not entry.get('visible', True):
            continue
        key = entry['key']
        for part in ('fieldRect', 'applyRect', 'clearRect', 'defaultRect'):
            reveal(session, lambda: shortcut_helpers.control(session, key)[part])
        session.click(reveal(session, lambda: shortcut_helpers.control(session, key)['fieldRect']))
        assert session.surface()['settingsScroll']['focusedKey'] == key, 'Shortcut field could not receive focus'
        reached.add(key)
    reveal(session, lambda: session.surface()['reset']['requestRect'])
    return reached


def tab_focus(session):
    expected = {c['key'] for c in session.surface()['settingControls'] if c['visible']}
    expected |= {c['key'] for c in session.surface()['numberControls'] if c['visible']}
    expected |= {c['key'] for c in session.surface()['shortcutControls'] if c.get('visible', True)}
    dropdown(session, 'presentation')
    seen = {'presentation'}
    for _ in range(140):
        session.keys('-k', 'Tab')
        value = session.surface()['settingsScroll']
        key = value['focusedKey']
        if key in expected:
            wait(lambda: contained(session.surface()['settingsScroll']['focusedRect'], session.surface()['settingsScroll']['rect']),
                 'Tab focus remained behind the settings clip: '+key, timeout=2)
            seen.add(key)
        if expected <= seen:
            return
    raise AssertionError(('Tab navigation could not reach every visible setting', sorted(expected-seen)))


def scrolling_inputs(session):
    reveal(session, lambda: choice(session, 'presentation')['rect'])
    before = session.surface()['settingsScroll']['contentY']
    wheel(session, 3)
    wait(lambda: session.surface()['settingsScroll']['contentY'] > before+1, 'Mouse wheel did not scroll settings')
    before = session.surface()['settingsScroll']['contentY']
    drag_page(session, True)
    wait(lambda: session.surface()['settingsScroll']['contentY'] > before+1, 'Pointer drag did not scroll settings')
    scroll = session.surface()['settingsScroll']
    before = scroll['contentY']
    thumb = scroll['thumbRect']
    track = scroll['scrollbarRect']
    assert contained(thumb, track), ('Scrollbar thumb is outside its track', thumb, track)
    session.move(thumb['x']+thumb['width']/2, thumb['y']+thumb['height']/2)
    session.pointer.button(True)
    for step in range(1, 7):
        session.move(thumb['x']+thumb['width']/2,
                     thumb['y']+thumb['height']/2+(track['y']+track['height']-thumb['height']/2-thumb['y']-thumb['height']/2)*step/6)
        time.sleep(.02)
    session.pointer.button(False)
    wait(lambda: session.surface()['settingsScroll']['contentY'] > before+1, 'Scrollbar thumb could not reveal later settings')


def confirmation(session):
    serial = session.surface()['reset']['serial']
    for key in ('Escape', 'Return'):
        session.click(reveal(session, lambda: session.surface()['reset']['requestRect']))
        wait(lambda: session.surface()['reset']['confirming'], 'Reset confirmation did not open')
        wait(lambda: contained(session.surface()['reset']['cancelRect'], session.surface()['settingsScroll']['rect']),
             'Default Cancel focus was not scrolled into the tiny confirmation')
        if key == 'Escape':
            reveal(session, lambda: session.surface()['reset']['confirmRect'])
        session.keys('-k', key)
        wait(lambda: not session.surface()['reset']['confirming'], 'Tiny reset confirmation did not cancel with '+key)
        assert session.surface()['dialog']['visible'], 'Confirmation cancellation closed the settings panel'
        assert session.surface()['reset']['serial'] == serial, 'Default confirmation input unexpectedly reset preferences'


def critical_bottom(session):
    for entry in session.surface()['shortcutControls']:
        if not entry.get('visible', True):
            continue
        key = entry['key']
        for part in ('fieldRect', 'applyRect', 'clearRect', 'defaultRect'):
            reveal(session, lambda: shortcut_helpers.control(session, key)[part])
    reveal(session, lambda: number(session, 'previewHideDelay')['rect'])
    reveal(session, lambda: session.surface()['reset']['requestRect'])


def interaction_controls(session):
    """Visit the conditional section and exercise the real local-shortcut field."""
    original = dict(shell('status')['settings'])
    global_shortcuts = dict(shell('status')['activeShortcuts'])
    reached = set()
    assert choice(session, 'floatingPreviewInteraction')['visible'], 'Interaction enable control is hidden in preview mode'
    dropdown(session, 'floatingPreviewInteraction', 'on')
    reached.add('floatingPreviewInteraction')
    section = next(item for item in session.surface()['settingSections'] if item['key'] == 'interaction')
    assert section['visible'], 'The seventh settings section is hidden in preview mode'
    reveal(session, lambda: next(item for item in session.surface()['settingSections'] if item['key'] == 'interaction')['rect'])
    for key in INTERACTION_CHOICES[1:]:
        assert choice(session, key)['visible'], 'Enabled interaction option is unreachable: '+key
        dropdown(session, key)
        reached.add(key)
    field = shortcut_helpers.control(session, EXIT_SHORTCUT)
    assert field['visible'] and field['section'] == 'interaction', 'The local exit shortcut is outside the interaction section'
    authoritative = command('list')['shortcutDefaults'][EXIT_SHORTCUT]
    assert field['defaultBinding'] == authoritative, 'Exit-field reset does not use the controller default'
    for part in ('fieldRect', 'applyRect', 'clearRect', 'defaultRect'):
        reveal(session, lambda: shortcut_helpers.control(session, EXIT_SHORTCUT)[part])
    candidates = shortcut_helpers.free_chords(shell('status')['settings'])
    custom = next(value for value in candidates if value not in (original[EXIT_SHORTCUT], authoritative))
    shortcut_helpers.edit(session, EXIT_SHORTCUT, custom)
    shortcut_helpers.saved(session, EXIT_SHORTCUT, custom)
    session.click(reveal(session, lambda: shortcut_helpers.control(session, EXIT_SHORTCUT)['defaultRect']))
    shortcut_helpers.saved(session, EXIT_SHORTCUT, authoritative)
    session.click(reveal(session, lambda: shortcut_helpers.control(session, EXIT_SHORTCUT)['clearRect']))
    shortcut_helpers.saved(session, EXIT_SHORTCUT, '')
    shortcut_helpers.edit(session, EXIT_SHORTCUT, original[EXIT_SHORTCUT], enter=True)
    shortcut_helpers.saved(session, EXIT_SHORTCUT, original[EXIT_SHORTCUT])
    assert shell('status')['activeShortcuts'] == global_shortcuts, 'Editing the local exit chord changed the three global actions'
    reached.add(EXIT_SHORTCUT)
    tab_focus(session)
    configure('floatingPreviewInteraction', original['floatingPreviewInteraction'])
    assert shell('status')['settings'] == original, 'Interaction reachability checks changed saved preferences'
    return reached


def long_error(session):
    before = dict(shell('status')['settings'])
    # A rejected oversized chord exercises wrapping without creating any
    # additional compositor binding or modifying a real shortcut.
    invalid = 'SUPER + '+'A'*128
    session.click(reveal(session, lambda: shortcut_helpers.control(session, 'restoreOldestShortcut')['fieldRect']))
    session.keys('-M', 'ctrl', '-k', 'a', '-m', 'ctrl', invalid, '-k', 'Return')
    wait(lambda: session.surface()['settingsError']['visible'] and not shortcut_helpers.control(session, 'restoreOldestShortcut')['pending'],
         'Rejected-shortcut error did not appear')
    error = session.surface()['settingsError']
    viewport = session.surface()['settingsScroll']['rect']
    assert error['text'] and error['lineCount'] > 1, 'Validation error was not wrapped'
    assert error['rect']['width'] <= viewport['width']+1, 'Error expanded the settings horizontally'
    reveal(session, lambda: session.surface()['reset']['requestRect'])
    reveal(session, lambda: shortcut_helpers.control(session, 'restoreOldestShortcut')['fieldRect'])
    session.click(shortcut_helpers.control(session, 'restoreOldestShortcut')['fieldRect'])
    session.keys('-k', 'Escape')
    configure('hoverPreview', before['hoverPreview'])
    assert shell('status')['settings'] == before, 'Rejected error changed saved settings'


@contextmanager
def reserved_edges(session):
    initial = next(m for m in h.read('monitors') if m['name'] == session.monitor['name'])['reserved']
    with tempfile.TemporaryDirectory(prefix='stash-settings-fit-bar-') as directory:
        path = Path(directory)/'shell.qml'
        path.write_text('''import Quickshell
import QtQuick
ShellRoot {
  PanelWindow {
    screen: Quickshell.screens.find(s => s.name === Quickshell.env("STASH_SETTINGS_FIT_SCREEN"))
    anchors { top:true; left:true; right:true }
    implicitHeight:16; exclusiveZone:16; color:"#1a1b26"; mask:Region {}
  }
  PanelWindow {
    screen: Quickshell.screens.find(s => s.name === Quickshell.env("STASH_SETTINGS_FIT_SCREEN"))
    anchors { left:true; top:true; bottom:true }
    implicitWidth:12; exclusiveZone:12; color:"#1a1b26"; mask:Region {}
  }
}
''')
        bar = subprocess.Popen(['qs', '-p', str(path)], env=dict(os.environ, STASH_SETTINGS_FIT_SCREEN=session.monitor['name']),
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        session.processes.append(bar)
        try:
            wait(lambda: (m := next(m for m in h.read('monitors') if m['name'] == session.monitor['name']))['reserved'][0] >= initial[0]+12
                 and m['reserved'][1] >= initial[1]+16, 'Temporary top/left bar reservations did not appear')
            shell('refresh')
            yield
        finally:
            if bar.poll() is None:
                bar.terminate()
            bar.wait(timeout=5)


@desktop_test('Small-screen settings accessibility test')
def main():
    with NativeSession() as session:
        for key, value in dict(scope='workspace', animations='off', presentation='floating', iconFrame='shown', dockFrame='shown',
                               dockCorners='custom', hoverPreview='live', livePreviewCompatibility='standard', sizePreset='100').items():
            configure(key, value)
        before_outputs = {m['name'] for m in h.read('monitors')}
        h.call('output', 'create', 'headless')
        monitor = wait(lambda: next((m for m in h.read('monitors') if m['name'] not in before_outputs), None), 'Temporary settings output missing')
        session.outputs.append(monitor['name'])
        right = max(m['x']+round(m['width']/m['scale']) for m in h.read('monitors') if m['name'] != monitor['name'])
        for index, (width, height, scale) in enumerate(((640, 480, 1.25), (400, 300, 1.25))):
            shell('dismiss')
            h.eval('hl.monitor({output=%s,mode=%s,position=%s,scale=%s})' %
                   (json.dumps(monitor['name']), json.dumps('%dx%d@60' % (width, height)), json.dumps('%dx0' % right), scale))
            session.monitor = next(m for m in h.read('monitors') if m['name'] == monitor['name'])
            h.dispatch('focus', monitor=monitor['name'])
            h.dispatch('focus', workspace=str(session.workspace+1))
            wait(lambda: monitor['name'] in shell('status')['screens'], 'Temporary output has no settings surface')
            # No bottom/right bars are used on this owned output, so the work
            # area's far edges give the screen's logical size even unmapped.
            wait(lambda: (a := session.surface()['usableArea'])['x']+a['width'] == round(width/scale)
                 and a['y']+a['height'] == round(height/scale), 'Temporary screen geometry did not settle')
            with reserved_edges(session):
                shell('refresh')
                wait(lambda: not shell('status')['controllerBusy'] and not shell('status')['queueLength'], 'Monitor refresh did not finish')
                open_settings(session)
                # An unmapped layer surface retains its placeholder size until
                # settings open; inspect the actual mapped window here.
                wait(lambda: session.surface()['width'] == round(width/scale) and session.surface()['height'] == round(height/scale),
                     'Temporary surface did not adopt the requested logical dimensions')
                before = dict(shell('status')['settings'])
                if index == 1:
                    reached = all_controls(session)
                    dropdown(session, 'sizePreset', '300', click_option=True)
                    dropdown(session, 'sizePreset', '50', click_option=True)
                    dropdown(session, 'sizePreset', '100')
                    configure('presentation', 'dock')
                    dropdown(session, 'dockSide')
                    reached.add('dockSide')
                    dropdown(session, 'staticDockLock')
                    reached.add('staticDockLock')
                    configure('presentation', 'previews')
                    configure('floatingPreviewSizing', 'preset')
                    for key in ('floatingPreviewSizing', 'floatingPreviewScale', 'floatingPreviewUpdate',
                                'floatingPreviewTitles', 'floatingPreviewFrame', 'floatingPreviewLock'):
                        assert choice(session, key)['visible'], 'Floating preview control is hidden: '+key
                        dropdown(session, key)
                        reached.add(key)
                    reached |= interaction_controls(session)
                    configure('floatingPreviewSizing', before['floatingPreviewSizing'])
                    configure('presentation', before['presentation'])
                    assert reached == set(DEFAULTS), ('Settings were not all reachable', sorted(set(DEFAULTS)-reached))
                else:
                    critical_bottom(session)
                tab_focus(session)
                scrolling_inputs(session)
                confirmation(session)
                if index == 1:
                    long_error(session)
                assert shell('status')['settings'] == before, 'Accessibility checks changed preferences'
                assert {w['id'] for w in command('list')['windows']} == session.baseline, 'Accessibility checks changed the stash'
                print(('PASS %dx%d @ %.2f: '+(('seven sections/all%d controls, local exit apply/default/disable, bounded9-option popup and wrapped error; ' % len(DEFAULTS)) if index == 1 else 'bottom shortcuts/actions and preview controls; ')+
                       'reserved bounds, Tab/wheel/drag/scrollbar and tiny reset cancellation') %
                      (width, height, scale), flush=True)
                shell('dismiss')
    wait(lambda: not shell('status')['controllerBusy'] and not shell('status')['queueLength'], 'Settings-fit cleanup did not finish')


if __name__ == '__main__':
    main()
