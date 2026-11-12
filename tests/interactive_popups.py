#!/usr/bin/env python3
"""Actual hidden GTK popup pixels and input through the production miniature."""
import os
from pathlib import Path
import subprocess
import tempfile
import time

from desktop_test import desktop_test
from floating_previews import card, park, ready, seed
from interactive_bridge import events, spawn_fixture
from interactive_previews import active, assert_source, source_click, start, stopped
from live import command, configure, h, shell, wait
from native_session import NativeSession


def screenshot(session, record, popup):
    image = card(session, record)['imageRect']
    source = h.client(record['address'])['size']
    x = session.monitor['x']+image['x']+image['width']*(popup['x']+popup['width']*.15)/source[0]
    y = session.monitor['y']+image['y']+image['height']*(popup['y']+popup['height']*.3)/source[1]
    width = max(1, round(image['width']*popup['width']*.7/source[0]))
    height = max(1, round(image['height']*popup['height']*.5/source[1]))
    data = subprocess.check_output(['grim', '-s', '1', '-t', 'ppm', '-g', f'{round(x)},{round(y)} {width}x{height}', '-'],
                                   stderr=subprocess.DEVNULL)
    assert data.startswith(b'P6\n')
    pixels = data.split(b'\n', 3)[3]
    return sum(1 for index in range(0, len(pixels)-2, 3)
               if pixels[index] > 160 and pixels[index+1] < 130 and pixels[index+2] < 150)/max(1, len(pixels)//3)


@desktop_test('Isolated interactive-preview GTK popup rendering and input')
def main():
    assert os.environ.get('WINDOW_STASH_ISOLATED_TEST') == '1' and (Path.home()/'.window-stash-isolated').is_file()
    assert not command('list')['windows']
    with tempfile.TemporaryDirectory(prefix='stash-popup-') as temporary, NativeSession() as session:
        for key, value in dict(presentation='previews', scope='workspace', grouping='window',
                               floatingPreviewInteraction='on', floatingPreviewActivation='explicit',
                               floatingPreviewKeyboard='click', floatingPreviewInteractionFps='60', floatingPreviewControls='always',
                               floatingPreviewUpdate='still', livePreviewCompatibility='standard', hoverPreview='off',
                               floatingPreviewSizing='free', floatingPreviewTitles='hidden', floatingPreviewFrame='hidden',
                               floatingPreviewLock='unlocked', floatingPlacement='free', dragMotion='direct', animations='off').items():
            configure(key, value)
        log = Path(temporary)/'source.jsonl'
        address = spawn_fixture(session, log)
        control, _ = session.spawn(app='org.windowstash.PopupControl')
        record = park(session, address)
        seed(session, record, 180, 180, 440)
        client = h.client(address)
        original = (client['workspace'], client['at'], client['size'], client['floating'])
        h.dispatch('focus', window='address:'+control)
        ready(session, record)
        start(session, record)
        source_click(session, record, 400/client['size'][0], 46/client['size'][1])
        wait(lambda: events(log, 'popup-open'), 'Native popup button did not open its Gtk.Popover')
        popup = wait(lambda: (values := events(log, 'popup-layout')) and values[-1], 'GTK popup did not report its actual surface geometry')
        assert popup['x'] >= 0 and popup['y'] >= 0 and popup['x']+popup['width'] <= client['size'][0] \
            and popup['y']+popup['height'] <= client['size'][1], ('Fixture popup is outside the source capture', popup)
        assert_source(record, original)
        try:
            wait(lambda: screenshot(session, record, popup) > .15,
                 'Mapped hidden popup pixels were absent from the floating preview', timeout=5)
        except AssertionError:
            print('Popup pixel diagnostics:', popup, screenshot(session, record, popup), card(session, record), events(log)[-8:], flush=True)
            raise
        source_click(session, record, (popup['x']+popup['width']/2)/client['size'][0],
                     (popup['y']+popup['height']/2)/client['size'][1])
        wait(lambda: events(log, 'popup-choice'), 'Clicking the miniature popup did not reach its real GTK item')
        assert_source(record, original)
        assert h.read('activeworkspace')['id'] == session.workspace, 'Popup handling exposed the private workspace'
        assert active(record), 'An ordinary in-bounds popup ended the interaction'
        print('PASS actual hidden GTK popup renders in the miniature, receives exact item input, closes normally and keeps the source/workspace unchanged', flush=True)
        shell('dismiss')
        wait(stopped, 'Popup interaction did not release on dismissal')
        configure('floatingPreviewKeyboard', 'mouse')
        h.dispatch('focus', window='address:'+control)
        start(session, record)
        opened, chosen = len(events(log, 'popup-open')), len(events(log, 'popup-choice'))
        layouts = len(events(log, 'popup-layout'))
        source_click(session, record, 400/client['size'][0], 46/client['size'][1])
        wait(lambda: len(events(log, 'popup-open')) > opened, 'Mouse-only popup did not open')
        popup = wait(lambda: len(values := events(log, 'popup-layout')) > layouts and values[-1],
                     'Mouse-only popup did not report its actual geometry')
        wait(lambda: screenshot(session, record, popup) > .15, 'Mouse-only popup did not render')
        before_keys = len(events(log, 'root-key'))
        session.keys('p')
        assert len(events(log, 'root-key')) == before_keys, 'A mouse-only popup acquired application keyboard input'
        assert h.read('activewindow').get('address') == control, 'A mouse-only popup changed the focused window'
        source_click(session, record, (popup['x']+popup['width']/2)/client['size'][0],
                     (popup['y']+popup['height']/2)/client['size'][1])
        wait(lambda: len(events(log, 'popup-choice')) > chosen, 'Mouse-only popup item did not receive pointer input')
        assert active(record) and not active(record)['status']['status']['keyboardFocused']
        assert_source(record, original)
        shell('dismiss')
        wait(stopped, 'Mouse-only popup did not release on dismissal')
        print('PASS mouse-only popup rendering and item input preserve visible keyboard focus and do not silently enable typing', flush=True)
    assert not command('list')['windows']


if __name__ == '__main__':
    main()
