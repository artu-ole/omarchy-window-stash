#!/usr/bin/env python3
"""Actual independent Still frames for floating covers and expanded app tiles.

Run in an isolated desktop with an empty stash. An explicitly owned rendering
keeper lets only the disposable source redraw while the UI retains its old Still
frame. NativeSession restores preferences, positions and fixtures after cleanup.
"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from desktop_test import desktop_test
from floating_preview_layouts import assert_borderless_fit, ledger
from floating_previews import card, drain, park, pixel_value, previews, ready
from hover_previews import assert_pixels, change_color, spawn_color
from live import ROOT, command, configure, h, shell, wait
from live_compatibility import bridge_status
from native_session import NativeSession
from stash import SPECIAL


def bridge_empty():
    value = bridge_status()
    return value.get('owners', 0) == 0 and value.get('windows', 0) == 0


def pixels(session, item_for, expected):
    deadline = time.monotonic()+3
    while time.monotonic() < deadline:
        item = item_for()
        if item and item['image']['hasContent']:
            try:
                assert_pixels(session, pixel_value(item), expected)
                return item
            except AssertionError:
                pass
        time.sleep(.04)
    raise AssertionError(('Still snapshot did not display '+expected, item_for()))


@desktop_test('Independent floating cover and app-group Still snapshots')
def main():
    assert not command('list')['windows'], 'Run snapshot-context tests in an isolated desktop with an empty stash'
    assert bridge_empty(), 'Refusing to interfere with an existing native rendering lease'
    with tempfile.TemporaryDirectory(prefix='stash-independent-snapshots-') as temporary, NativeSession() as session:
        for key, value in dict(presentation='previews', scope='workspace', grouping='app', hoverPreview='off',
                               floatingPreviewUpdate='still', floatingPreviewSizing='free', floatingPreviewScale='100',
                               floatingPreviewTitles='hidden', floatingPreviewFrame='hidden', floatingPreviewLock='unlocked',
                               floatingPlacement='free', dragMotion='direct', animations='off', iconOpacity=100,
                               livePreviewCompatibility='standard').items():
            configure(key, value)
        red = park(session, spawn_color(session, 'red', app='org.windowstash.SnapshotContext'))
        green = park(session, spawn_color(session, 'green', app='org.windowstash.SnapshotContext'))
        cover = ready(session, green)
        assert cover['groupCount'] == 2, 'Snapshot fixtures did not form one app group'
        pixels(session, lambda: card(session, green), 'green')
        old_size = cover['image']['sourceSize']
        assert old_size == {'width': 640, 'height': 420}, ('Unexpected original snapshot dimensions', old_size)
        original = {record['id']: ledger(record) for record in (red, green)}
        assert all(value['size'] == [640, 420] for value in original.values()), 'Snapshot fixtures did not retain original floating geometry'
        helper = None
        log_path = Path(temporary)/'keeper.log'
        with log_path.open('w') as log:
            try:
                # The direct helper alone owns the rendering lease. Persistent
                # cards stay in Still; their UI capture requests must stay empty.
                configure('hoverPreview', 'live')
                configure('livePreviewCompatibility', 'enhanced')
                helper = subprocess.Popen([sys.executable, str(ROOT/'controller/preview.py')],
                                          stdin=subprocess.PIPE, stdout=log, stderr=log, text=True)
                session.processes.append(helper)
                helper.stdin.write(json.dumps([green['id']])+'\n')
                helper.stdin.flush()
                try:
                    wait(lambda: helper.poll() is None and bridge_status().get('windows') == 1
                         and bridge_status().get('owners') == 1,
                         'Owned rendering helper did not acquire its single source', timeout=150)
                except AssertionError:
                    print('Snapshot keeper diagnostics:', log_path.read_text()[-2000:], flush=True)
                    raise
                assert not shell('status')['previewCompatibility']['requestedIds'], 'Still UI unexpectedly acquired native rendering support'
                start_frames = bridge_status()['frames']
                h.dispatch('window.resize', window='address:'+green['address'], x=420, y=640, relative=False)
                change_color(session, green['address'])  # green -> blue
                wait(lambda: h.client(green['address'])['size'] == [420, 640]
                     and bridge_status()['frames'] >= start_frames+8, 'Owned portrait source did not redraw after resizing')
                before_expand = pixels(session, lambda: card(session, green), 'green')
                assert before_expand['image']['sourceSize'] == old_size, 'Resizing the live source rewrote the retained Still frame dimensions'

                def expand(expected):
                    session.click(ready(session, green)['imageRect'])
                    wait(lambda: previews(session)['expanded'] and len(previews(session)['tiles']) == 2,
                         'Still app group did not expand both thumbnails')
                    tile_for = lambda: next((tile for tile in previews(session)['tiles'] if tile['recordId'] == green['id']), None)
                    tile = pixels(session, tile_for, expected)
                    assert tile['image']['sourceSize'] == {'width': 420, 'height': 640}, ('Fresh group snapshot retained the old landscape source', tile)
                    assert_borderless_fit(tile)
                    retained = pixels(session, lambda: card(session, green), 'green')
                    assert retained['image']['sourceSize'] == old_size, 'Expanded tile replaced the cover\'s independent Still dimensions'
                    assert_borderless_fit(retained)
                    assert ledger(green) == original[green['id']], 'Snapshot aspect propagation changed original restore geometry'
                expand('blue')
                print('PASS actual landscape cover remains green while its independently captured portrait group tile is blue', flush=True)
                session.keys('-k', 'Escape')
                wait(lambda: not previews(session)['expanded'], 'Still group did not close')
                start_frames = bridge_status()['frames']
                change_color(session, green['address'])  # blue -> red
                wait(lambda: bridge_status()['frames'] >= start_frames+8, 'Owned source did not redraw before reopening the group')
                expand('red')
                session.keys('-k', 'Escape')
                wait(lambda: not previews(session)['expanded'], 'Reopened Still group did not close')
                assert all(ledger(record) == original[record['id']] for record in (red, green)), 'Snapshot contexts modified saved restoration metadata'
                assert all(h.client(record['address'])['workspace']['name'] == SPECIAL for record in (red, green)), 'Capturing an independent snapshot restored a source'
                assert not shell('status')['previewCompatibility']['requestedIds'], 'Still snapshots requested UI live leases'
                print('PASS reopening refreshes only group snapshots while the cover and original 640x420 restoration metadata remain unchanged', flush=True)
            finally:
                if helper is not None:
                    if helper.stdin and not helper.stdin.closed:
                        try:
                            helper.stdin.close()
                        except (OSError, ValueError):
                            pass
                    try:
                        helper.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        helper.kill()
                        helper.wait(timeout=3)
                    wait(bridge_empty, 'Snapshot helper cleanup retained native owners/windows', timeout=5)
        drain()
        assert not shell('status')['error'], shell('status')['error']
    drain()
    wait(bridge_empty, 'Snapshot test cleanup retained native owners/windows', timeout=5)
    assert not command('list')['windows'], 'Snapshot test cleanup retained disposable clients in the stash'
    print('PASS direct keeper EOF releases all native leases and preserving cleanup restores the desktop', flush=True)


if __name__ == '__main__':
    main()
