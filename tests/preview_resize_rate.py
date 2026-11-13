#!/usr/bin/env python3
"""Side-drag update cadence against an actual client in a disposable desktop.

Frequent physical pointer moves must not postpone source reflow until release.
The fixture logs actual GTK allocations, distinguishing committed app updates
from changes to the miniature's bounding rectangle alone.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

from desktop_test import desktop_test
from floating_previews import card, drain, park, seed
from floating_preview_aspect import allocation, handle, pause_captures, shaped, spawn
from floating_preview_layouts import ledger
from interactive_bridge import events
from live import command, configure, h, shell, wait
from native_session import NativeSession
from preview import PreviewBridge
from settings_fit import choice, dropdown, open_settings, reveal
from stash import SPECIAL


SETTING = 'floatingPreviewResizeRate'


def continuous_drag(session, record, log, edge='right', distance=160, duration=1.1):
    before = shaped(session, record)
    rect = handle(before, edge)
    x, y = rect['x']+rect['width']/2, rect['y']+rect['height']/2
    monitors = h.read('monitors')
    left, top = min(item['x'] for item in monitors), min(item['y'] for item in monitors)
    right = max(item['x']+round(item['width']/item['scale']) for item in monitors)
    bottom = max(item['y']+round(item['height']/item['scale']) for item in monitors)

    def move(px, py):
        session.pointer.move(session.monitor['x']+px-left, session.monitor['y']+py-top,
                             right-left, bottom-top)

    old_size = h.client(record['address'])['size']
    move(x-1, y)
    move(x, y)
    session.pointer.button(True)
    try:
        wait(lambda: card(session, record)['resizing'], 'The physical edge press did not acquire resize management')
        started = time.monotonic()
        steps = max(15, round(duration/.012))
        gaps = []
        previous = started
        for step in range(1, steps+1):
            offset = distance*step/steps
            move(x+offset if edge == 'right' else x, y+offset if edge == 'bottom' else y)
            moved_at = time.monotonic()
            gaps.append(moved_at-previous)
            previous = moved_at
            deadline = started+duration*step/steps
            if (remaining := deadline-time.monotonic()) > 0:
                time.sleep(remaining)
        last_move = previous
        # Read the actual client's allocation log before releasing. Filtering
        # by the move interval excludes any later quiet period or release work.
        allocations = [item for item in events(log, 'allocation') if started <= item['time'] <= last_move
                       and [item['width'], item['height']] != old_size]
        during = card(session, record)
        assert during['resizing'] and not during['geometryReady'], 'A held drag advertised ready application input'
    finally:
        released = time.monotonic()
        session.pointer.button(False)
    after = shaped(session, record)
    allocation(log, record)
    drain()
    return dict(before=before, during=during, after=after, allocations=allocations, started=started, lastMove=last_move,
                released=released, maximumMoveGap=max(gaps, default=0), oldSize=old_size)


def case(session, directory, rate, index, duration=1.1, edge='right'):
    configure(SETTING, rate)
    wait(lambda: command('list')['settings'][SETTING] == rate, 'Resize cadence was not persisted in the controller settings')
    log = directory/(rate+'-'+str(index)+'.jsonl')
    address = spawn(session, log, app='org.windowstash.ResizeCadence'+str(index))
    original = {field: copy.deepcopy(h.client(address)[field]) for field in ('workspace', 'at', 'size', 'floating')}
    record = park(session, address)
    seed(session, record, 260, 180, 340)
    saved = ledger(record)
    result = continuous_drag(session, record, log, edge=edge, duration=duration)
    assert ledger(record) == saved, 'Resize cadence changed original restoration metadata'
    client = h.client(address)
    assert client['workspace']['name'] == SPECIAL and client['floating'], 'Live resizing exposed or retiled the source'
    first = result['allocations'][0]['time']-result['started'] if result['allocations'] else None
    distinct = {(item['width'], item['height']) for item in result['allocations']}
    if rate == 'release':
        assert not distinct, ('On release reflowed the app during a held drag', distinct)
        assert not result['during']['image']['live'], 'Release-only resizing unnecessarily enabled continuous capture'
    elif duration >= .7:
        assert result['during']['image']['live'], 'Snapshot previews did not temporarily show live resize frames'
        assert len(distinct) >= 2, ('Continuous dragging postponed app reflow until release', rate, distinct, result)
        assert first < (result['lastMove']-result['started'])*.85, ('First app resize arrived only after pointer motion stopped', rate, first, result)
    assert result['after']['geometryReady'] and result['after']['image']['hasContent'], 'Release did not reach a fresh committed frame'
    assert not result['after']['image']['live'], 'Resizing did not restore the saved Snapshot capture policy'
    before, after = result['before'], result['after']
    assert abs(after['aspectOverride']-before['imageRect']['width']/before['imageRect']['height']) > .05
    assert abs(after['x']-before['x']) <= 2 and abs(after['y']-before['y']) <= 2, 'A cadence change moved the fixed resize anchor'
    expected_axis = 'width' if edge == 'right' else 'height'
    assert abs(after[expected_axis]-before[expected_axis]-160) <= 2, \
        ('A pending update replaced the pointer-release target', rate, edge, before['rect'], after['rect'])
    measured = dict(rate=rate, axis=expected_axis, moveDurationMs=round((result['lastMove']-result['started'])*1000),
                    maximumMoveGapMs=round(result['maximumMoveGap']*1000, 1),
                    committedUpdatesWhileHeld=len(distinct), firstCommittedUpdateMs=None if first is None else round(first*1000, 1),
                    finalSourceSize=client['size'], finalAspect=after['aspectOverride'])
    print('PASS actual resize cadence', json.dumps(measured), flush=True)

    command('restore', record['id'], '--to', 'original')
    wait(lambda: not any(item['id'] == record['id'] for item in command('list')['windows']), 'Cadence source did not restore fully')
    current = {field: h.client(address)[field] for field in original}
    assert current == original, ('Cadence resizing changed full-window restoration', original, current)
    return measured


def settings(session):
    open_settings(session)
    assert choice(session, SETTING)['visible'], 'Free sizing hid the resize-update setting'
    artifacts = os.environ.get('WINDOW_STASH_TEST_ARTIFACT_DIR')
    if artifacts:
        folder = Path(artifacts)
        folder.mkdir(parents=True, exist_ok=True)
        session.click(reveal(session, lambda: choice(session, SETTING)['rect']))
        popup = wait(lambda: choice(session, SETTING)['open'] and choice(session, SETTING)['popupRect'],
                     'Resize-update choices did not open for inspection')
        region = '%d,%d %dx%d' % (session.monitor['x']+popup['x'], session.monitor['y']+popup['y'], popup['width'], popup['height'])
        subprocess.run(['grim', '-g', region, str(folder/'resize-update-options.png')], check=True, timeout=5,
                       stderr=subprocess.DEVNULL)
        session.keys('-k', 'Escape')
        wait(lambda: not choice(session, SETTING)['open'], 'Inspection popup did not dismiss')
    for value in ('balanced', 'release', 'realtime'):
        dropdown(session, SETTING, value)
        wait(lambda: command('list')['settings'][SETTING] == value, 'The visible resize-update selector did not persist '+value)
    dropdown(session, 'floatingPreviewSizing', 'preset')
    assert not choice(session, SETTING)['visible'], 'Preset sizing exposed an irrelevant drag-update preference'
    dropdown(session, 'floatingPreviewSizing', 'free')
    assert choice(session, SETTING)['visible'], 'Returning to Free sizing did not restore its update preference'
    assert command('list')['settings'][SETTING] == 'realtime', 'Hiding the selector changed its saved value'
    shell('dismiss')
    print('PASS native resize-update selector saves all three presets, stays reachable through scrolling and follows Free/Preset visibility', flush=True)


@desktop_test('Isolated continuous preview-resize cadence')
def main(settings_only=False):
    assert os.environ.get('WINDOW_STASH_ISOLATED_TEST') == '1' and (Path.home()/'.window-stash-isolated').is_file(), \
        'Run resize cadence input only in an explicitly disposable compositor'
    assert not command('list')['windows'], 'Cadence proof requires an empty disposable stash'
    # Prepare before motion so module compilation/config reload is measured
    # independently of the side-drag update scheduler itself.
    PreviewBridge(h).ensure()
    h.dispatch('focus', monitor='HEADLESS-1')
    with tempfile.TemporaryDirectory(prefix='stash-resize-cadence-') as temporary, NativeSession() as session:
        directory = Path(temporary)
        try:
            for key, value in dict(presentation='previews', scope='workspace', grouping='window',
                                   floatingPreviewInteraction='on', floatingPreviewActivation='explicit',
                                   floatingPreviewKeyboard='mouse', floatingPreviewUpdate='still',
                                   floatingPreviewSizing='free', floatingPreviewTitles='hidden', floatingPreviewFrame='hidden',
                                   floatingPreviewLock='unlocked', floatingPlacement='free', dragMotion='direct',
                                   livePreviewCompatibility='enhanced', hoverPreview='off', animations='off').items():
                configure(key, value)
            if not settings_only:
                results = [case(session, directory, rate, index) for index, rate in enumerate(('realtime', 'balanced', 'release'))]
                # A quick vertical drag must still flush its last target on release,
                # even if the scheduler's next interval has not fired.
                results.append(case(session, directory, 'realtime', 3, duration=.09, edge='bottom'))
                print('PASS continuous pointer motion updates the app before release; release-only and rapid final flush preserve fresh frames and exact original geometry', flush=True)
                print('Resize cadence measurements:', json.dumps(results), flush=True)
            settings(session)
            assert not shell('status')['error'], shell('status')['error']
        finally:
            pause_captures(session)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--settings-only', action='store_true', help='Only exercise the actual preset selector and persistence')
    options = parser.parse_args()
    main(options.settings_only)
