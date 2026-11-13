#!/usr/bin/env python3
"""Super-click activation with stock compositor mouse bindings, in isolation.

The source and visible witness are owned GTK clients. Genuine virtual-keyboard
modifiers plus virtual-pointer buttons exercise the compositor path before Qt;
calling a QML method alone cannot prove compatibility with Super+left-drag.
"""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile
import time

from desktop_test import desktop_test
from floating_previews import card, drain, park, previews, ready, seed
from interactive_bridge import events, native_status, spawn_fixture
from interactive_groups import ready_tile
from interactive_keyboard import key_count
from interactive_previews import active, assert_source, source_click, start, stopped
from live import command, configure, h, shell, wait
from bridge import BridgeManager
from native_session import NativeSession
from preview import API, PreviewBridge


def stop():
    shell('dismiss')
    wait(stopped, 'Super-click acceptance retained native input', timeout=8)


def pause_captures(session):
    stop()
    configure('presentation', 'dock')
    wait(lambda: not previews(session)['present'], 'Test captures did not hide before source cleanup')
    wait(lambda: not any(item.get('image', {}).get('captureActive') for surface in shell('status')['surfaces']
                         for item in surface['floatingPreviews']['cards']),
         'Test capture was still active before terminating its source')
    drain()


def super_gesture(session, rect, dx=0, dy=0, button=272, return_to_start=False, release_modifier_first=False, physical_super=False):
    """Keep a real seat modifier down for the entire pointer sequence."""
    x, y = rect['x']+rect['width']*.45, rect['y']+rect['height']*.7
    session.move(x-1, y)
    session.move(x, y)
    keys = ['wtype', '-s', '100']
    if physical_super:
        keys += ['-P', 'Super_L']
    keys += ['-M', 'logo', '-s', '2000', '-m', 'logo']
    if physical_super:
        keys += ['-p', 'Super_L']
    keys += ['-s', '100']
    held = subprocess.Popen(keys, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(.3)
        session.pointer.button(True, button)
        try:
            time.sleep(.1)
            if dx or dy:
                for step in range(1, 7):
                    session.move(x+dx*step/6, y+dy*step/6)
                    time.sleep(.03)
                if return_to_start:
                    session.move(x, y)
                    time.sleep(.05)
            if release_modifier_first:
                held.wait(timeout=4)
        finally:
            session.pointer.button(False, button)
    finally:
        held.wait(timeout=4)


def geometry(address):
    value = h.client(address)
    return value['workspace'], value['at'], value['size'], value['floating']


@desktop_test('Isolated Super-click preview activation')
def main(fresh_support=False):
    assert os.environ.get('WINDOW_STASH_ISOLATED_TEST') == '1' and (Path.home()/'.window-stash-isolated').is_file(), \
        'Run only in the explicit disposable compositor'
    assert not command('list')['windows'], 'Super-click proof requires an empty disposable stash'
    manager = BridgeManager(h)
    expected = manager.build(manager.commit())
    if fresh_support:
        assert not any(item.get('image', {}).get('captureActive') for surface in shell('status')['surfaces']
                       for item in surface['floatingPreviews']['cards']), 'Fresh-support proof requires captures already stopped'
        native = manager.native()
        assert native['available'] and native['owners'] == 0 and not native['inputActive'], native
        assert native['fingerprint'] == expected['fingerprint'], ('Only the exact owned current build may be replaced', native, expected)
        path = manager.loaded_path(native, manager.commit())
        h.eval('assert('+API+'.prepare_reload())')
        wait(lambda: manager.native().get('reloadReady'), 'Owned native support did not drain before fresh-start proof')
        h.call('plugin', 'unload', str(path))
        wait(lambda: not manager.native()['available'], 'Owned native support remained loaded')
        print('PASS fresh-support fixture starts with native support absent; no explicit ensure follows', flush=True)
    else:
        PreviewBridge(h).ensure()
        native = manager.native()
        assert native['fingerprint'] == expected['fingerprint'], ('Super-click proof requires the current native source', native, expected)
    binding = '__window_stash_super_click_proof_'+str(os.getpid())
    try:
        with tempfile.TemporaryDirectory(prefix='stash-super-click-') as temporary, NativeSession() as session:
            try:
                for key, value in dict(presentation='previews', scope='workspace', grouping='window',
                                       floatingPreviewInteraction='on', floatingPreviewActivation='explicit',
                                       floatingPreviewKeyboard='mouse', floatingPreviewInteractionFps='60',
                                       floatingPreviewControls='hover', floatingPreviewUpdate='still',
                                       livePreviewCompatibility='standard', hoverPreview='off',
                                       floatingPreviewSizing='free', floatingPreviewTitles='hidden', floatingPreviewFrame='hidden',
                                       floatingPreviewLock='unlocked', floatingPlacement='free', dragMotion='direct', animations='off').items():
                    configure(key, value)
                log = Path(temporary)/'source.jsonl'
                address = spawn_fixture(session, log)
                control, title = session.spawn(app='org.windowstash.SuperClickVisibleControl')
                h.dispatch('window.float', window='address:'+control, action='on')
                h.dispatch('window.resize', window='address:'+control, x=1100, y=760, relative=False)
                h.dispatch('window.move', window='address:'+control, x=session.monitor['x']+40, y=session.monitor['y']+50, relative=False)
                record = park(session, address)
                seed(session, record, 200, 180, 380)
                wait(lambda: shell('status').get('previewShortcut', {}).get('status', {}).get('state') == 'ready',
                     'Native Super-click preparation did not become ready', timeout=15)
                native = manager.native()
                assert native['available'] and native['fingerprint'] == expected['fingerprint'], ('Automatic shortcut preparation loaded unexpected native support', native)
                if fresh_support:
                    print('PASS Standard/Still stashed source automatically loads current native support before Super-click', native['version'], native['fingerprint'], flush=True)
                wait(lambda: shell('status')['lifecycle']['ready'], 'Lifecycle did not settle after automatic preparation')
                h.eval('_G.'+binding+'={hl.bind("SUPER + mouse:272",hl.dsp.window.drag(),'
                       '{mouse=true,description="Window Stash isolated stock move proof"}),'
                       'hl.bind("SUPER + mouse:273",hl.dsp.window.resize(),'
                       '{mouse=true,description="Window Stash isolated stock resize proof"})}')
                assert sum(item.get('description', '').startswith('Window Stash isolated stock ') for item in h.read('binds')) == 2, 'Owned stock mouse bindings were not registered'
                layers = h.read('layers')
                namespaces = [(monitor, item.get('namespace')) for monitor, detail in layers.items()
                              for level in detail.get('levels', {}).values() for item in level]
                assert (session.monitor['name'], 'omarchy-window-stash-interactive-previews') in namespaces, ('Interactive layer namespace was not published', namespaces)
                print('PASS actual scoped layer namespace', namespaces, flush=True)
                original = geometry(address)
                control_before = geometry(control)
                h.dispatch('focus', window='address:'+control)
            except BaseException:
                pause_captures(session)
                raise
            try:
                value = ready(session, record)
                before = len(events(log, 'press'))
                super_gesture(session, value['imageRect'])
                result = wait(lambda: active(record), 'Super+left click did not activate the exact preview', timeout=15)
                assert len(events(log, 'press')) == before, 'Activation click reached the hidden application'
                assert not events(log, 'release'), 'Activation leaked an unmatched button release to the application'
                assert_source(record, original)
                assert geometry(control) == control_before and h.client(control)['title'] == title, 'Super-click moved or clicked the underlying witness'
                after = card(session, record)
                assert abs(after['x']-value['x']) < 1 and abs(after['y']-value['y']) < 1, 'Activation moved the preview'
                assert not after['held'] and not after['resizing'], 'Activation retained miniature drag or resize state'
                before = len(events(log, 'press'))
                source_click(session, record)
                wait(lambda: len(events(log, 'press')) == before+1, 'Next ordinary click did not reach the active application')
                print('PASS stock Super+left binding reaches exact preview activation without source/witness clicks, movement or orphan release; next ordinary click works', flush=True)

                stop()
                value = ready(session, record)
                counts = len(events(log, 'press')), len(events(log, 'release'))
                super_gesture(session, value['imageRect'], release_modifier_first=True)
                wait(lambda: active(record), 'Releasing Super before the button lost the paired activation', timeout=12)
                assert (len(events(log, 'press')), len(events(log, 'release'))) == counts, 'Early modifier release leaked an activation event'
                assert_source(record, original)
                stop()
                value = ready(session, record)
                before_control = geometry(control)
                super_gesture(session, value['imageRect'], dx=25, return_to_start=True)
                time.sleep(.15)
                assert stopped(), 'Dragging away and back was incorrectly treated as Super-click activation'
                assert (len(events(log, 'press')), len(events(log, 'release'))) == counts, 'Cancelled Super drag reached the source'
                assert geometry(control) == before_control, 'Cancelled Super drag moved the underlying public window'
                after = ready(session, record)
                assert abs(after['x']-value['x']) < 1 and abs(after['y']-value['y']) < 1, 'Cancelled Super drag moved the miniature'
                assert_source(record, original)
                print('PASS early modifier release retains the complete pair; drag-away-and-back cancels without forwarding input or moving any window', flush=True)

                configure('floatingPreviewLock', 'locked')
                value = ready(session, record)
                super_gesture(session, value['imageRect'])
                wait(lambda: active(record), 'Locked placement prevented Super-click interaction', timeout=12)
                assert_source(record, original)
                stop()
                configure('floatingPreviewLock', 'unlocked')
                print('PASS locked miniature placement still permits Super-click interaction', flush=True)

                # The current interaction policies retain their ordinary paths.
                start(session, record)
                stop()
                configure('floatingPreviewActivation', 'click')
                value = ready(session, record)
                session.click({'x':value['imageRect']['x']+40, 'y':value['imageRect']['y']+100, 'width':8, 'height':8})
                wait(lambda: active(record), 'Adding Super-click broke optional first-click activation', timeout=12)
                stop()
                configure('floatingPreviewActivation', 'explicit')
                print('PASS explicit control and optional first-click activation remain available', flush=True)

                # A genuine stock move on a public window remains untouched.
                before = geometry(control)
                super_gesture(session, {'x':760, 'y':650, 'width':40, 'height':40}, dx=55, dy=30)
                wait(lambda: h.client(control)['at'] != before[1], 'Super+left drag outside the miniature stopped moving public windows')
                assert stopped(), 'Outside stock movement activated a preview'
                assert_source(record, original)
                print('PASS stock Super+left drag still moves a public window outside preview bounds', flush=True)

                # Group covers are ambiguous; select a concrete expanded tile.
                second_log = Path(temporary)/'second.jsonl'
                second_address = spawn_fixture(session, second_log)
                second_record = park(session, second_address)
                second_original = geometry(second_address)
                configure('grouping', 'app')
                cover = wait(lambda: (value := ready(session)) and value['groupCount'] == 2 and value,
                             'Same-app windows did not form one cover')
                super_gesture(session, cover['imageRect'])
                wait(lambda: previews(session)['expanded'] and len(previews(session)['tiles']) == 2,
                     'Super-click on an ambiguous group did not expand its exact windows')
                assert stopped(), 'Ambiguous app-group cover activated an arbitrary source'
                configure('floatingPreviewKeyboard', 'click')
                value = ready_tile(session, second_record)
                counts = [len(events(item, 'press')) for item in (log, second_log)]
                super_gesture(session, value['imageRect'])
                wait(lambda: active(second_record), 'Super-click on an exact expanded tile did not select its source', timeout=12)
                assert [len(events(item, 'press')) for item in (log, second_log)] == counts, 'Grouped activation clicked a source'
                assert_source(record, original)
                assert_source(second_record, second_original)
                print('PASS Super-click selects one exact app-group tile and leaves its sibling private', flush=True)
                rect = ready_tile(session, second_record)['imageRect']
                session.click({'x':rect['x']+rect['width']*.75-2, 'y':rect['y']+rect['height']*.75-2, 'width':4, 'height':4})
                wait(lambda: active(second_record)['status']['status']['keyboardFocused'],
                     'Grouped source did not acquire real keyboard focus before replacement')
                counts = [len(events(item, 'press')) for item in (log, second_log)]
                super_presses, super_releases = key_count(second_log, 'Super_L'), key_count(second_log, 'Super_L', 'key-release')
                value = ready_tile(session, record)
                previous = shell('status')['previewInteraction']['request']['serial']
                previous_owner = active(second_record)['status']['status']['owner']
                super_gesture(session, value['imageRect'], physical_super=True)
                switched = wait(lambda: active(record), 'Super-click did not replace interaction with another exact tile', timeout=12)
                assert switched['request']['serial'] > previous, 'Replacement reused the previous interaction request'
                assert [len(events(item, 'press')) for item in (log, second_log)] == counts, 'Replacement activation clicked a source'
                assert_source(record, original)
                assert_source(second_record, second_original)
                ended = native_status(previous_owner)
                assert not ended['active'] and ended['heldKeys'] == 0 and ended['heldButtons'] == 0, ('Replacement retained old native input', ended)
                print('Keyboard replacement key events:', [item for item in events(second_log) if item['event'] in ('root-key', 'key-press', 'key-release')][-12:], flush=True)
                wait(lambda: key_count(second_log, 'Super_L') == super_presses+1
                     and key_count(second_log, 'Super_L', 'key-release') == super_releases+1,
                     'Replacing keyboard-focused interaction did not release the consumed Super key exactly once')
                print('PASS Super-click switches exact grouped targets without leaking the activating gesture or leaving Super held', flush=True)
                stop()
            except BaseException:
                state = shell('status')
                print('Super-click diagnostics:', dict(interaction=state['previewInteraction'],
                      lifecycle=state['lifecycle'], card=card(session, record),
                      source=h.client(address), witness=h.client(control),
                      sourceEvents=events(log)[-12:],
                      secondEvents=events(second_log)[-16:] if 'second_log' in locals() else [], pointer=state['pointer'],
                      pressedPointerButtons=state['pressedPointerButtons']), flush=True)
                raise
            finally:
                pause_captures(session)
    finally:
        h.eval('local b=_G.'+binding+';if b then for _,v in ipairs(b) do v:set_enabled(false) end;_G.'+binding+'=nil end')
    assert not command('list')['windows'], 'Super-click proof retained owned stash records'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fresh-support', action='store_true', help='safely unload the exact private module, then prove automatic preparation without calling ensure')
    args = parser.parse_args()
    main(args.fresh_support)
