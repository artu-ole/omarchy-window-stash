#!/usr/bin/env python3
"""Actual Ghostty/btop pixels in persistent floating previews.

Run in a disposable desktop with an empty stash and no active native rendering
leases. Uses a new Ghostty instance and temporary btop configuration; captures
are sampled in memory and never include the surrounding desktop. NativeSession
restores settings, positions, focus and fixtures after the five-second notice.
"""
import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

from desktop_test import desktop_test
from floating_previews import away, card, drain, previews, ready, touch
from hover_previews import current_focus
from live import command, configure, h, shell, wait
from live_compatibility import bridge_status, ready as enhanced_ready, spawn
from native_session import NativeSession
from stash import SPECIAL


def bridge_empty():
    value = bridge_status()
    return value.get('windows', 0) == 0 and value.get('owners', 0) == 0


def scoped(record):
    value = shell('status')['previewCompatibility']
    native = bridge_status()
    return set(value['requestedIds']) == {record['id']} and enhanced_ready(record) \
        and native.get('windows') == 1 and native.get('owners') == 1


def frame_samples(session, record, count):
    hashes = []
    for _ in range(count):
        value = ready(session, record)
        rect = value['imageRect']
        # The central 80% excludes borders, resize handles, app/title strips,
        # pointer feedback and all neighboring windows from the pixel hash.
        x = round(session.monitor['x']+rect['x']+rect['width']*.1)
        y = round(session.monitor['y']+rect['y']+rect['height']*.1)
        width, height = max(1, round(rect['width']*.8)), max(1, round(rect['height']*.8))
        pixels = subprocess.check_output(['grim', '-s', '1', '-t', 'ppm', '-g',
                                         f'{x},{y} {width}x{height}', '-'],
                                        stderr=subprocess.DEVNULL)
        assert pixels.startswith(b'P6\n'), 'Persistent preview sample was not a PPM capture'
        hashes.append(hashlib.sha256(pixels).hexdigest())
        time.sleep(.45)
    return hashes


def assert_unchanged(record, focus, geometry):
    assert current_focus() == focus, 'Floating preview changed focus or workspace'
    client = h.client(record['address'])
    assert client and client['workspace']['name'] == SPECIAL, 'Floating preview restored its Ghostty source'
    assert (client['at'], client['size']) == geometry, 'Floating preview moved or resized its real Ghostty source'


@desktop_test('Persistent Ghostty/btop live preview rendering test')
def main():
    assert shutil.which('ghostty') and shutil.which('btop'), 'This test requires Ghostty and btop'
    assert not command('list')['windows'], 'Run this focused rendering test in an isolated desktop with an empty stash'
    assert bridge_empty(), 'Refusing to interfere with pre-existing native preview leases'
    with tempfile.TemporaryDirectory(prefix='stash-floating-live-') as temporary, NativeSession() as session:
        for key, value in dict(presentation='previews', scope='workspace', grouping='window',
                               hoverPreview='off', livePreviewCompatibility='standard',
                               floatingPreviewUpdate='live', floatingPreviewSizing='free', floatingPreviewScale='100',
                               floatingPreviewTitles='hidden', floatingPreviewFrame='hidden', floatingPreviewLock='unlocked',
                               floatingPlacement='free', dragMotion='direct', animations='off', iconOpacity=100).items():
            configure(key, value)
        control, _ = session.spawn(app='org.windowstash.FloatingLiveControl', workspace=session.workspace)
        address = spawn(session, 'ghostty', Path(temporary))
        h.dispatch('window.float', window='address:'+address, action='on')
        h.dispatch('window.resize', window='address:'+address, x=900, y=600, relative=False)
        h.dispatch('window.move', window='address:'+address,
                   x=session.monitor['x']+100, y=session.monitor['y']+100, relative=False)
        time.sleep(.2)
        record = session.park(address)
        touch(session, record)
        h.dispatch('focus', window='address:'+control)
        ready(session, record)
        away(session)
        focus = current_focus()
        client = h.client(address)
        geometry = (client['at'], client['size'])
        assert card(session, record)['image']['live'], 'Always-live card requires pointer hover'
        assert shell('status')['settings']['hoverPreview'] == 'off', 'Persistent mode enabled ordinary hover previews'
        assert bridge_empty(), 'Standard preview acquired native rendering support'
        time.sleep(.3)
        standard = frame_samples(session, record, 7)
        assert_unchanged(record, focus, geometry)

        configure('livePreviewCompatibility', 'enhanced')
        wait(lambda: scoped(record), 'Enhanced persistent preview did not acquire exactly its Ghostty source', timeout=150)
        initial_frames = bridge_status()['frames']
        enhanced = frame_samples(session, record, 9)
        assert len(set(enhanced)) >= 3, ('Persistent Ghostty/btop pixels stayed frozen with Enhanced support',
                                        len(set(standard)), len(set(enhanced)), bridge_status())
        assert bridge_status()['frames'] > initial_frames+2, 'Native renderer sent no new frame feedback'
        assert_unchanged(record, focus, geometry)
        print('PASS persistent Ghostty/btop: '+str(len(set(standard)))+' distinct Standard frames, '
              +str(len(set(enhanced)))+' Enhanced frames; exact scoped lease, unchanged source geometry/focus', flush=True)

        configure('floatingPreviewUpdate', 'hover')
        away(session)
        wait(lambda: not card(session, record)['image']['live'] and bridge_empty()
             and not shell('status')['previewCompatibility']['requestedIds'],
             'Live-on-hover kept rendering after the pointer left the card', timeout=5)
        value = ready(session, record)
        session.move(value['x']+value['width']/2-1, value['y']+value['height']/2)
        session.move(value['x']+value['width']/2, value['y']+value['height']/2)
        wait(lambda: card(session, record)['image']['live'] and scoped(record),
             'Re-entering the card did not resume its scoped live render', timeout=10)
        resumed = frame_samples(session, record, 5)
        assert len(set(resumed)) >= 2, 'Re-entering the card resumed a frozen Ghostty/btop frame'
        assert_unchanged(record, focus, geometry)
        configure('presentation', 'dock')
        wait(lambda: not previews(session)['present'] and bridge_empty()
             and not shell('status')['previewCompatibility']['requestedIds'],
             'Changing presentation retained a persistent preview rendering lease', timeout=5)
        idle_frames = bridge_status()['frames']
        time.sleep(.3)
        assert bridge_status()['frames'] == idle_frames, 'Idle native bridge kept issuing preview frame callbacks'
        assert_unchanged(record, focus, geometry)
        print('PASS live-on-hover leave/re-enter updates real terminal pixels; leaving preview mode releases all owners/windows and idles rendering', flush=True)
        drain()
        assert not shell('status')['error'], shell('status')['error']
    drain()
    wait(bridge_empty, 'Preserving cleanup left native preview owners/windows behind', timeout=5)
    assert not command('list')['windows'], 'Live preview cleanup retained its disposable stashed terminal'
    print('PASS live preview cleanup restores preferences/focus/positions and leaves zero native owners/windows', flush=True)


if __name__ == '__main__':
    main()
