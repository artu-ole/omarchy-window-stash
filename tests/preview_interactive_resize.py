#!/usr/bin/env python3
"""Resize active miniature handles in an explicitly disposable compositor.

Physical pointer gestures prove the native exclusions, release acknowledgement,
fresh-frame resumption and ordinary application implicit grabs together.
"""
from contextlib import contextmanager
import copy
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time

from live import command, configure, h, shell, wait
from bridge import BridgeManager
from desktop_test import desktop_test
from floating_preview_aspect import allocation, pause_captures, shaped, spawn
from floating_preview_layouts import ledger
from floating_previews import card, drain, park, seed
from interactive_bridge import events, native_status
from interactive_previews import active, source_click, start, stopped
from native_session import NativeSession
from preview import PreviewBridge
from preview_super_corner import stock_move_binding
from stash import SPECIAL


def counts(log):
    return len(events(log, 'press')), len(events(log, 'release'))


def contains(rect, x, y):
    return rect['x'] <= x <= rect['x']+rect['width'] and rect['y'] <= y <= rect['y']+rect['height']


def assert_handles(session, value, enabled=True):
    handles = value['resizeRects']
    assert len(handles) == 8 and all(item['enabled'] is enabled for item in handles), \
        ('Active miniature has incorrect resize handles', enabled, handles)
    if not enabled:
        return
    exclusions = value['interaction']['excludeRects']
    assert len(exclusions) <= 16, 'Handle exclusions exceeded the native input limit'
    for item in handles:
        rect = item['rect']
        x = session.monitor['x']+rect['x']+rect['width']/2
        y = session.monitor['y']+rect['y']+rect['height']/2
        assert any(contains(excluded, x, y) for excluded in exclusions), \
            ('A resize handle remains application input', item['corner'], exclusions)


def handle_point(value, edge):
    item = next(item for item in value['resizeRects'] if item['corner'] == edge)
    assert item['enabled'], ('Resize handle is disabled', edge, value)
    rect = item['rect']
    if '-' in edge:
        # Corner centers can sit beneath higher-priority hover controls.
        return (rect['x']+(1 if 'left' in edge else rect['width']-1),
                rect['y']+(1 if 'top' in edge else rect['height']-1))
    return rect['x']+rect['width']/2, rect['y']+rect['height']/2


@contextmanager
def super_held(enabled, physical=False):
    process = None
    if enabled:
        keys = ['wtype', '-s', '100']+(['-P', 'Super_L'] if physical else [])
        keys += ['-M', 'logo', '-s', '2600', '-m', 'logo']+(['-p', 'Super_L'] if physical else [])+['-s', '100']
        process = subprocess.Popen(keys,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(.3)
    try:
        yield
    finally:
        if process:
            process.wait(timeout=4)


def native_owner():
    value = native_status('')
    assert value['active'] and value.get('owner'), ('No active native owner', value)
    return value['owner']


def assert_source(session, record, saved):
    client = h.client(record['address'])
    assert client and client['workspace']['name'] == SPECIAL and client['floating'], \
        'Resizing active miniature restored or retiled the application'
    assert client['pid'] == record['pid'] and client['stableId'] == record['stableId'] and record['tag'] in client['tags'], \
        'Interactive resize changed the exact private source'
    assert ledger(record) == saved, 'Interactive resize changed original restoration metadata'
    assert session.surface()['workspaceId'] == record['origin']['id'], 'Resize changed the visible workspace'


def mapped_click(session, record, log):
    value = shaped(session, record)
    before = counts(log)
    source_click(session, record, x=.6, y=.65)
    event = wait(lambda: len(values := events(log, 'press')) == before[0]+1 and values[-1],
                 'Resumed miniature did not deliver application input')
    wait(lambda: len(events(log, 'release')) == before[1]+1,
         'Resumed miniature did not deliver its matching release')
    source = h.client(record['address'])['size']
    assert abs(event['x']-source[0]*.6) <= 5 and abs(event['y']-source[1]*.65) <= 5, \
        ('Resumed input retained the previous image mapping', event, source, value['imageRect'])
    assert active(record), 'Resumed application click ended interaction'


def resize(session, record, log, edge, dx, dy, super_key=False, resume=True, physical_super=False):
    before = shaped(session, record)
    request = active(record)
    assert request, 'The resize fixture is not interactive'
    old_owner = native_owner()
    old_serial = request['request']['serial']
    clicks = counts(log)
    x, y = handle_point(before, edge)
    session.move(x-1, y)
    session.move(x, y)
    with super_held(super_key, physical=physical_super):
        if physical_super:
            wait(lambda: native_status(old_owner)['heldKeys'] > 0, 'Focused application did not receive the physical Super press')
        session.pointer.button(True)
        try:
            wait(lambda: (value := card(session, record)) and value['resizing']
                 and value['interaction'].get('resizeResumePending'),
                 'Active handle did not claim the resize and remember interaction')
            wait(stopped, 'Handle resize did not acknowledge release before changing source geometry', timeout=6)
            assert not native_status(old_owner)['active'], 'Old native owner survived the resize barrier'
            if physical_super:
                assert BridgeManager(h).native()['pendingKeys'] > 0, 'Physical Super cleanup was not retained until its real release'
            for step in range(1, 9):
                session.move(x+dx*step/8, y+dy*step/8)
                time.sleep(.035)
            value = card(session, record)
            assert value['resizing'] and not value['geometryReady'], 'Held resize exposed ready application input'
            assert counts(log) == clicks, 'Handle press/motion leaked a pointer button into the application'
        finally:
            session.pointer.button(False)
    if not resume:
        return before
    wait(lambda: active(record), 'Resizing did not resume the exact interactive miniature', timeout=15)
    after = shaped(session, record)
    current = active(record)
    assert current['request']['serial'] > old_serial and native_owner() != old_owner, \
        'Resize reused an input owner from before its geometry change'
    assert current['request']['id'] == record['id'] and current['request']['viewKey'] == before['key'], \
        'Resize resumed a different source or preview'
    assert not after['interaction'].get('resizeResumePending') and after['geometryReady'], \
        'Resize resumed without a fresh matching frame or retained a pending continuation'
    actual, wanted = current['request']['rect'], after['interaction']['imageRect']
    assert all(abs(actual[name]-wanted[name]) < 1 for name in ('x', 'y', 'width', 'height')), \
        ('Resumed native image geometry is stale', actual, wanted)
    assert counts(log) == clicks, 'Resuming after a handle drag forwarded the management pointer pair'
    return before, after


def fast_inward_resize(session, record, log):
    before = shaped(session, record)
    request = active(record)
    assert request, 'Fast resize fixture is not interactive'
    clicks = counts(log)
    owner = native_owner()
    x, y = handle_point(before, 'right')
    session.move(x-1, y);session.move(x, y)
    time.sleep(.05)
    # Queue the move and release before the Qt press handler can await its
    # worker's stop acknowledgement. The endpoint is inside the old image.
    session.pointer.button(True)
    try:
        session.move(x-55, y)
    finally:
        session.pointer.button(False)
    wait(lambda: (current := active(record)) and current['request']['serial'] > request['request']['serial'],
         'Fast inward handle drag did not finish and resume after its release barrier', timeout=15)
    after = shaped(session, record)
    assert abs(after['width']-before['width']+55) <= 3 and abs(after['height']-before['height']) <= 3, \
        ('Fast handle motion or release was lost during native handoff', before['rect'], after['rect'])
    assert counts(log) == clicks, 'Fast management drag leaked its press or unmatched release into the application'
    assert native_owner() != owner and not native_status(owner)['active'], 'Fast drag retained the previous input owner'
    print('PASS same-frame inward handle motion/release stays with management until acknowledged input handoff', flush=True)


@desktop_test('Isolated resizing during preview interaction')
def main():
    assert os.environ.get('WINDOW_STASH_ISOLATED_TEST') == '1' and (Path.home()/'.window-stash-isolated').is_file(), \
        'Refusing input outside an explicitly disposable compositor'
    assert not command('list')['windows'], 'Interactive resize proof requires an empty disposable stash'
    PreviewBridge(h).ensure()
    manager = BridgeManager(h)
    assert manager.native()['fingerprint'] == manager.build(manager.commit())['fingerprint'], \
        'Interactive resize proof requires the tested current native build'
    h.dispatch('focus', monitor='HEADLESS-1')
    with tempfile.TemporaryDirectory(prefix='stash-interactive-resize-') as temporary, NativeSession() as session, stock_move_binding():
        try:
            for key, value in dict(presentation='previews', scope='workspace', grouping='window',
                                   floatingPreviewInteraction='on', floatingPreviewInteractionResize='on', floatingPreviewActivation='explicit',
                                   floatingPreviewKeyboard='mouse', floatingPreviewControls='hover',
                                   floatingPreviewUpdate='still', floatingPreviewResizeRate='realtime',
                                   floatingPreviewSizing='free', floatingPreviewTitles='hidden', floatingPreviewFrame='hidden',
                                   floatingPreviewLock='unlocked', floatingPlacement='free', dragMotion='direct',
                                   livePreviewCompatibility='standard', hoverPreview='off', animations='off', iconOpacity=100).items():
                configure(key, value)
            log = Path(temporary)/'source.jsonl'
            address = spawn(session, log, app='org.windowstash.InteractiveResizeFixture')
            original = {name: copy.deepcopy(h.client(address)[name]) for name in ('workspace', 'at', 'size', 'floating')}
            record = park(session, address)
            seed(session, record, 400, 300, 360)
            saved = ledger(record)
            start(session, record)
            assert_handles(session, shaped(session, record))

            before_size = h.client(address)['size']
            before, after = resize(session, record, log, 'bottom-right', 70, 12)
            assert abs(after['width']-before['width']-70) <= 3 and after['height'] > before['height']+10, \
                ('Ordinary active corner resize lost its pointer movement', before['rect'], after['rect'])
            assert abs(after['imageRect']['width']/after['imageRect']['height']
                       - before['imageRect']['width']/before['imageRect']['height']) < .005, \
                'Ordinary active corner resize changed proportions'
            assert h.client(address)['size'] == before_size, 'Proportional active corner resized the hidden application'
            mapped_click(session, record, log)
            assert_source(session, record, saved)
            print('PASS active corner handles, acknowledged pause, fresh-owner resume and remapped content clicks', flush=True)

            for edge, dx, dy, modifier in (('right', 70, 0, False), ('top-left', -45, -60, True)):
                before, after = resize(session, record, log, edge, dx, dy, super_key=modifier)
                state = shell('status')
                diagnostics = dict(edge=edge, modifier=modifier, delta=[dx, dy],
                    before={name: before.get(name) for name in ('rect', 'width', 'height', 'aspectOverride', 'imageRect', 'geometryReady')},
                    after={name: after.get(name) for name in ('rect', 'width', 'height', 'aspectOverride', 'imageRect', 'geometryReady')},
                    sourceSize=h.client(address)['size'], allocations=events(log, 'allocation')[-3:],
                    geometry=state.get('previewGeometry', {}).get(record['id']),
                    interaction=state.get('previewInteraction'), native=native_status(''))
                assert abs(after['aspectOverride']-before['imageRect']['width']/before['imageRect']['height']) > .025, \
                    ('Active reshape gesture retained its previous proportions', diagnostics)
                allocation(log, record)
                mapped_click(session, record, log)
                assert_source(session, record, saved)
                assert_handles(session, after)
            print('PASS side and Super-corner reflow resume only after fresh committed frames without management click leakage', flush=True)

            fast_inward_resize(session, record, log)
            allocation(log, record)
            mapped_click(session, record, log)
            assert_source(session, record, saved)

            configure('floatingPreviewKeyboard', 'click')
            wait(stopped, 'Keyboard policy change retained the previous input owner')
            start(session, record)
            mapped_click(session, record, log)
            wait(lambda: active(record)['status'].get('status', {}).get('keyboardFocused'), 'Content click did not acquire keyboard focus')
            resize(session, record, log, 'top-right', 30, -15, super_key=True, physical_super=True)
            wait(lambda: BridgeManager(h).native()['pendingKeys'] == 0, 'Physical Super release retained a stale keyboard cleanup filter')
            mapped_click(session, record, log)
            wait(lambda: active(record)['status'].get('status', {}).get('keyboardFocused'), 'Resized keyboard miniature did not reacquire focus on a fresh content click')
            assert_source(session, record, saved)
            configure('floatingPreviewKeyboard', 'mouse')
            wait(stopped, 'Restoring mouse-only input retained the keyboard owner')
            start(session, record)
            print('PASS focused keyboard Super-corner resizing releases held keys and resumes with fresh click-to-focus input', flush=True)

            # A drag that starts in application content retains its native
            # implicit grab when it crosses and exits a resize handle.
            value = shaped(session, record)
            owner = native_owner()
            image = value['imageRect']
            x, y = image['x']+image['width']*.6, image['y']+image['height']*.6
            edge_x, edge_y = handle_point(value, 'bottom-right')
            clicks = counts(log)
            session.move(x-1, y);session.move(x, y);session.pointer.button(True)
            try:
                wait(lambda: len(events(log, 'press')) == clicks[0]+1, 'Application grab fixture did not receive its press')
                for step in range(1, 9):
                    session.move(x+(edge_x+25-x)*step/8, y+(edge_y+25-y)*step/8)
                    time.sleep(.025)
                current = card(session, record)
                assert not current['resizing'] and not current['interaction'].get('resizeResumePending'), \
                    'Application drag became a handle resize while crossing the edge'
                assert native_owner() == owner and native_status(owner)['heldButtons'] == 1, \
                    'Crossing a handle lost the exact application implicit grab'
            finally:
                session.pointer.button(False)
            wait(lambda: native_status(owner)['heldButtons'] == 0, 'Application drag retained a physical button')
            wait(lambda: len(events(log, 'release')) == clicks[1]+1, 'Application implicit grab lost its matching release')
            assert all(abs(card(session, record)[name]-value[name]) < 1 for name in ('x', 'y', 'width', 'height')), \
                'Application content drag changed miniature geometry'
            print('PASS native application drags cross resize handles without changing miniature geometry', flush=True)

            # Ordinary content remains interactive even when resizing is
            # unavailable because of placement lock or preset sizing.
            for setting, value, restore in (('floatingPreviewLock', 'locked', 'unlocked'),
                                             ('floatingPreviewSizing', 'preset', 'free')):
                configure(setting, value)
                wait(stopped, 'Changing resize availability retained the previous input lease')
                start(session, record)
                assert_handles(session, shaped(session, record), enabled=False)
                mapped_click(session, record, log)
                configure(setting, restore)
                wait(stopped, 'Restoring resize availability retained the previous input lease')
            start(session, record)
            print('PASS locked and preset previews disable handles while preserving application interaction', flush=True)

            # Keep the owned client from acknowledging its new allocation, so
            # Stop is tested during a genuine pending fresh-frame continuation.
            configure('floatingPreviewResizeRate', 'release')
            wait(stopped, 'Resize cadence change retained input')
            start(session, record)
            pid = next(process.pid for process in session.processes if process.pid == record['pid'])
            os.kill(pid, signal.SIGSTOP)
            try:
                resize(session, record, log, 'bottom', 0, 45, resume=False)
                wait(lambda: (value := card(session, record)) and not value['resizing']
                     and not value['geometryReady'] and value['interaction'].get('resizeResumePending'),
                     'Paused source did not leave a pending fresh-frame continuation')
                session.click(card(session, record)['interaction']['interactRect'])
                wait(lambda: not card(session, record)['interaction'].get('resizeResumePending'),
                     'Explicit Stop did not cancel automatic interaction resumption')
            finally:
                os.kill(pid, signal.SIGCONT)
            shaped(session, record)
            time.sleep(.5)
            assert stopped() and not card(session, record)['interaction'].get('resizeResumePending'), \
                'Stopped pending resize rearmed after its fresh frame arrived'
            assert_source(session, record, saved)
            print('PASS release-only resize and explicit Stop cancel pending resume before a delayed client frame', flush=True)

            command('restore', record['id'], '--to', 'original')
            wait(lambda: all(item['id'] != record['id'] for item in command('list')['windows']), 'Interactive resize source did not restore')
            assert {name: h.client(address)[name] for name in original} == original, \
                'Interactive resizing changed the original full-window restoration geometry'
            assert not shell('status')['error'], shell('status')['error']
            print('PASS exact original restoration and unchanged stash metadata after active resizing', flush=True)
        finally:
            pause_captures(session)


if __name__ == '__main__':
    main()
