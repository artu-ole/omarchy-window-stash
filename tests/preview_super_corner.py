#!/usr/bin/env python3
"""Real Super+corner resizing with source reflow in a disposable compositor.

Run against an installed checkout with HEADLESS-1 focused. Both the isolation
environment flag and private-home marker are required before input is injected.
"""
import copy
from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import tempfile
import time

from live import command, configure, h, shell, wait
from bridge import BridgeManager
from desktop_test import desktop_test
from floating_preview_aspect import allocation, handle, pause_captures, shaped, spawn
from floating_preview_layouts import ledger
from floating_previews import card, drain, drag, park, seed
from interactive_bridge import events
from interactive_previews import active, stopped
from interactive_super_click import super_gesture
from native_session import NativeSession
from preview import API, PreviewBridge
from stash import SPECIAL


@contextmanager
def stock_move_binding():
    name = '__window_stash_super_corner_proof_'+str(os.getpid())
    h.eval('_G.'+name+'=hl.bind("SUPER + mouse:272",hl.dsp.window.drag(),'
           '{mouse=true,description="Window Stash isolated Super corner proof"})')
    try:
        yield
    finally:
        h.eval('local b=_G.'+name+';if b then b:set_enabled(false);_G.'+name+'=nil end')


def assert_private(session, record, saved, clicks, log):
    value = h.client(record['address'])
    assert value and value['workspace']['name'] == SPECIAL and value['floating'], \
        'Super+corner resize restored or retiled its source'
    assert value['pid'] == record['pid'] and value['stableId'] == record['stableId'] and record['tag'] in value['tags'], \
        'Super+corner resize lost the exact stashed source'
    assert ledger(record) == saved, 'Super+corner resize rewrote original restoration metadata'
    assert (len(events(log, 'press')), len(events(log, 'release'))) == clicks, \
        'Super+corner management forwarded pointer buttons to the application'
    assert stopped(), 'Super+corner management acquired native application input'
    assert h.read('activeworkspace')['id'] == session.surface()['workspaceId'] == record['origin']['id'], \
        'Super+corner resize switched the visible workspace'


def modifier_drag(session, record, corner, dx, dy, expected_resize=True, jump=False):
    before = shaped(session, record)
    rect = next(item['rect'] for item in before['resizeRects'] if item['corner'] == corner)
    # The top-right hover controls deliberately sit above the resize handle.
    # Its outer pixel remains a real corner target without covering a button.
    x = rect['x']+(1 if 'left' in corner else rect['width']-1)
    y = rect['y']+(1 if 'top' in corner else rect['height']-1)
    session.move(x-1, y)
    session.move(x, y)
    held = subprocess.Popen(['wtype', '-s', '100', '-M', 'logo', '-s', '2200', '-m', 'logo', '-s', '100'],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(.3)
        session.pointer.button(True)
        try:
            if expected_resize:
                wait(lambda: card(session, record)['resizing'],
                     'Super+corner press did not acquire preview resizing', timeout=1)
            else:
                time.sleep(.08)
            # One large first move leaves the original layer input mask. A
            # native gesture must retain the owned drag across that focus gap.
            steps = (1,) if jump else range(1, 9)
            for step in steps:
                fraction = 1 if jump else step/8
                session.move(x+dx*fraction, y+dy*fraction)
                time.sleep(.025)
            if expected_resize:
                current = wait(lambda: (value := card(session, record)) and value['resizing']
                               and abs(value['width']-before['width']) > 5
                               and abs(value['height']-before['height']) > 5 and value,
                               'Super+corner move did not independently resize both axes', timeout=1)
                assert not current['geometryReady'] and not current['interaction']['interactEnabled'], \
                    'Held free-aspect resize advertised ready source input'
        finally:
            session.pointer.button(False)
    finally:
        held.wait(timeout=4)
    after = shaped(session, record)
    drain()
    if expected_resize:
        old_ratio = before['imageRect']['width']/before['imageRect']['height']
        assert abs(after['aspectOverride']-old_ratio) > .025, \
            ('Super+corner drag retained the old aspect ratio', corner, before['rect'], after['rect'])
        expected_width = before['width']+(-dx if 'left' in corner else dx)
        expected_height = before['height']+(-dy if 'top' in corner else dy)
        assert abs(after['width']-expected_width) <= 2 and abs(after['height']-expected_height) <= 3, \
            ('Free corner did not follow independent pointer axes', corner, before['rect'], after['rect'])
        for origin, length, side in (('x', 'width', 'left'), ('y', 'height', 'top')):
            old_anchor = before[origin]+(before[length] if side in corner else 0)
            new_anchor = after[origin]+(after[length] if side in corner else 0)
            assert abs(old_anchor-new_anchor) <= 2, \
                ('Free corner moved its opposite anchor', corner, before['rect'], after['rect'])
    else:
        assert not after['resizing'] and all(abs(after[name]-before[name]) < 1 for name in ('x', 'y', 'width', 'height')), \
            ('Locked/preset preview accepted a free resize', before['rect'], after['rect'])
    return after


@desktop_test('Isolated Super+corner preview resizing')
def main():
    assert os.environ.get('WINDOW_STASH_ISOLATED_TEST') == '1' and (Path.home()/'.window-stash-isolated').is_file(), \
        'Run Super+corner input only in an explicitly disposable compositor'
    assert not command('list')['windows'], 'Super+corner proof requires an empty disposable stash'
    PreviewBridge(h).ensure()
    manager = BridgeManager(h)
    expected = manager.build(manager.commit())
    native = manager.native()
    assert native['fingerprint'] == expected['fingerprint'], \
        ('Super+corner proof requires the current native build', native, expected)
    h.eval('assert('+API+'.status().capabilities.superCornerResize==true)')
    h.dispatch('focus', monitor='HEADLESS-1')
    with tempfile.TemporaryDirectory(prefix='stash-super-corner-') as temporary, NativeSession() as session, stock_move_binding():
        try:
            for key, value in dict(presentation='previews', scope='workspace', grouping='window',
                                   floatingPreviewInteraction='off', floatingPreviewActivation='explicit',
                                   floatingPreviewKeyboard='mouse', floatingPreviewControls='hover',
                                   floatingPreviewUpdate='still', floatingPreviewResizeRate='realtime',
                                   floatingPreviewSizing='free', floatingPreviewTitles='hidden', floatingPreviewFrame='hidden',
                                   floatingPreviewLock='unlocked', floatingPlacement='free', dragMotion='direct',
                                   livePreviewCompatibility='standard', hoverPreview='off', animations='off',
                                   iconOpacity=100).items():
                configure(key, value)
            log = Path(temporary)/'responsive.jsonl'
            address = spawn(session, log, app='org.windowstash.SuperCornerFixture')
            original = {key: copy.deepcopy(h.client(address)[key]) for key in ('workspace', 'at', 'size', 'floating')}
            record = park(session, address)
            seed(session, record, 400, 320, 360)
            witness, _ = session.spawn(app='org.windowstash.SuperCornerWitness')
            h.dispatch('window.float', window='address:'+witness, action='on')
            h.dispatch('window.resize', window='address:'+witness, x=1100, y=800, relative=False)
            h.dispatch('window.move', window='address:'+witness,
                       x=session.monitor['x']+100, y=session.monitor['y']+80, relative=False)
            witness_geometry = {key: copy.deepcopy(h.client(witness)[key]) for key in ('workspace', 'at', 'size', 'floating')}
            saved = ledger(record)
            clicks = len(events(log, 'press')), len(events(log, 'release'))
            wait(lambda: shell('status')['previewShortcut']['status']['state'] == 'ready',
                 'View-only free previews did not prepare native corner support', timeout=15)

            cases = (('bottom-right', 100, 15), ('top-left', -75, -90),
                     ('top-right', 60, -15), ('bottom-left', -20, 65))
            for index, (corner, dx, dy) in enumerate(cases):
                if index == 2:
                    configure('floatingPreviewInteraction', 'on')
                after = modifier_drag(session, record, corner, dx, dy, jump=index == 0)
                allocation(log, record)
                assert_private(session, record, saved, clicks, log)
                assert {key: h.client(witness)[key] for key in witness_geometry} == witness_geometry, \
                    'Super+corner drag reached the underlying public window move binding'
                assert after['geometryReady'] and after['image']['hasContent'], 'Free resize did not capture a fresh committed frame'
                print('PASS real Super+corner', corner, 'interaction', 'off' if index < 2 else 'on',
                      'aspect', after['aspectOverride'], 'source', h.client(address)['size'], flush=True)

            before = shaped(session, record)
            size = h.client(address)['size']
            drag(session, handle(before, 'bottom-right'), 60, 5)
            after = shaped(session, record)
            assert abs(after['aspectOverride']-before['aspectOverride']) < .0001, 'Ordinary corner scaling changed custom proportions'
            assert h.client(address)['size'] == size, 'Ordinary corner scaling resized the source application'
            assert_private(session, record, saved, clicks, log)
            print('PASS ordinary corner dragging preserves the chosen ratio and source allocation', flush=True)

            for setting, value, restore in (('floatingPreviewLock', 'locked', 'unlocked'),
                                             ('floatingPreviewSizing', 'preset', 'free')):
                configure(setting, value)
                modifier_drag(session, record, 'bottom-right', 35, 10, expected_resize=False)
                assert_private(session, record, saved, clicks, log)
                configure(setting, restore)
            print('PASS locked and preset previews reject Super+corner resizing', flush=True)

            value = shaped(session, record)
            super_gesture(session, value['imageRect'])
            wait(lambda: active(record), 'Super+content click no longer activates interaction', timeout=12)
            assert (len(events(log, 'press')), len(events(log, 'release'))) == clicks, 'Super+click activation forwarded its pointer pair'
            shell('dismiss')
            wait(stopped, 'Super+click regression check retained source input')
            assert_private(session, record, saved, clicks, log)
            command('restore', record['id'], '--to', 'original')
            wait(lambda: all(item['id'] != record['id'] for item in command('list')['windows']), 'Super+corner source did not fully restore')
            assert {key: h.client(address)[key] for key in original} == original, 'Free corner resizing changed full-window restoration'
            print('PASS Super+content activation, fresh input gating, unchanged stash metadata and exact original restoration', flush=True)
            assert not shell('status')['error'], shell('status')['error']
        finally:
            pause_captures(session)


if __name__ == '__main__':
    main()
