#!/usr/bin/env python3
"""End-to-end interactive miniature controls on an isolated Omarchy desktop."""
import os
from pathlib import Path
import tempfile
import time

from desktop_test import desktop_test
from floating_previews import away, card, drain, drag, park, previews, ready, seed
from interactive_bridge import events, scroll, spawn_fixture
from live import command, configure, h, shell, wait
from native_session import NativeSession
from stash import SPECIAL


def interaction():
    return shell('status')['previewInteraction']


def stopped():
    value = interaction()
    return not value['request'] and not value['running']


def active(record):
    value = interaction()
    if value['error']:
        raise AssertionError(('Interactive preview failed', value))
    return value if value['request'] and value['request']['id'] == record['id'] and value['status']['state'] == 'active' else None


def show_controls(session, record):
    value = ready(session, record)
    session.move(value['imageRect']['x']+value['imageRect']['width']*.5,
                 value['imageRect']['y']+value['imageRect']['height']*.7)
    return wait(lambda: (value := card(session, record)) and value['interaction']['controlsVisible'] and value,
                'Interactive miniature controls did not appear')


def start(session, record):
    value = show_controls(session, record)
    session.click(value['interaction']['interactRect'])
    result = wait(lambda: active(record), 'Explicit Interact did not start the native session', timeout=150)
    wait(lambda: card(session, record)['image']['live'] and card(session, record)['interaction']['active'],
         'Active miniature did not show live capture and its active state')
    return result


def source_click(session, record, x=.75, y=.75, button=272):
    value = ready(session, record)
    rect = value['imageRect']
    px, py = rect['x']+rect['width']*x, rect['y']+rect['height']*y
    session.move(px-1, py)
    session.pointer.click(*session.point(px, py), button=button)


def assert_source(record, original):
    client = h.client(record['address'])
    assert client and client['workspace']['name'] == SPECIAL, 'Interacting restored or lost the source'
    assert (client['workspace'], client['at'], client['size'], client['floating']) == original, \
        'Miniature interaction changed the real source geometry'


@desktop_test('Isolated floating-preview interaction acceptance')
def main():
    assert os.environ.get('WINDOW_STASH_ISOLATED_TEST') == '1' and (Path.home()/'.window-stash-isolated').is_file(), \
        'Run only in the explicit disposable compositor'
    assert not command('list')['windows'], 'Interactive acceptance requires an empty disposable stash'
    with tempfile.TemporaryDirectory(prefix='stash-interactive-ui-') as temporary, NativeSession() as session:
        for key, value in dict(presentation='previews', scope='workspace', grouping='window',
                               floatingPreviewInteraction='on', floatingPreviewInteractionResize='on', floatingPreviewActivation='explicit',
                               floatingPreviewKeyboard='mouse', floatingPreviewInteractionFps='60', floatingPreviewControls='hover',
                               floatingPreviewUpdate='still', livePreviewCompatibility='standard', hoverPreview='off',
                               floatingPreviewSizing='free', floatingPreviewTitles='hidden', floatingPreviewFrame='hidden',
                               floatingPreviewLock='unlocked', floatingPlacement='free', dragMotion='direct', animations='off').items():
            configure(key, value)
        log = Path(temporary)/'first.jsonl'
        address = spawn_fixture(session, log)
        control, title = session.spawn(app='org.windowstash.InteractiveVisibleControl')
        h.dispatch('window.float', window='address:'+control, action='on')
        h.dispatch('window.resize', window='address:'+control, x=1100, y=700, relative=False)
        h.dispatch('window.move', window='address:'+control, x=session.monitor['x']+40, y=session.monitor['y']+50, relative=False)
        record = park(session, address)
        seed(session, record, 180, 160, 360)
        client = h.client(address)
        original = (client['workspace'], client['at'], client['size'], client['floating'])
        h.dispatch('focus', window='address:'+control)
        value = ready(session, record)
        assert not value['image']['live'] and not value['titleVisible'] and not value['frameVisible']
        before = len(events(log, 'press'))
        start(session, record)
        assert len(events(log, 'press')) == before, 'Interact control also clicked the hidden application'
        assert card(session, record)['resizable'], 'Active miniature lost its management resize handles'
        for button in (272, 273, 274):
            before = len(events(log, 'press'))
            source_click(session, record, button=button)
            event = wait(lambda: len(values := events(log, 'press')) > before and values[-1], 'Miniature did not deliver application button '+str(button))
            assert abs(event['x']-client['size'][0]*.75) <= 5 and abs(event['y']-client['size'][1]*.75) <= 5, \
                ('Miniature input did not use actual image geometry', event, card(session, record))
            assert not session.menu()['opened'], 'Native right click opened the plugin context menu'
            assert_source(record, original)
        count = len(events(log, 'scroll'))
        scroll(session.pointer)
        wait(lambda: len(events(log, 'scroll')) > count, 'Interactive miniature did not forward wheel input')
        settings = shell('status')['settings']
        assert settings['floatingPreviewUpdate'] == 'still' and settings['livePreviewCompatibility'] == 'standard', \
            'Interacting overwrote the ordinary capture preferences'
        assert h.client(control)['title'] == title, 'Interactive content clicks leaked through the miniature'
        print('PASS explicit controls, live override without preference writes, mapped native mouse buttons/scroll and unchanged borderless source', flush=True)

        value = show_controls(session, record)
        session.click(value['interaction']['manageRect'])
        wait(stopped, 'Manage did not release native interaction')
        wait(lambda: card(session, record)['resizable'], 'Manage did not re-enable miniature sizing')
        value = ready(session, record)
        drag(session, {'x':value['x']+40, 'y':value['y']+value['height']*.6, 'width':30, 'height':20}, 45, 25)
        try:
            wait(lambda: abs(card(session, record)['x']-value['x']-45) <= 2, 'Inactive miniature did not retain ordinary drag movement')
        except AssertionError:
            print('Post-interaction drag diagnostics:', {'before':value, 'after':card(session, record),
                  'world':previews(session)['world'], 'interaction':interaction(),
                  'pointer':shell('status')['pointer'], 'buttons':shell('status')['pressedPointerButtons']}, flush=True)
            raise
        assert_source(record, original)
        start(session, record)
        session.pointer.click(*session.point(80, 350))
        wait(stopped, 'Outside click did not release the input worker')
        wait(lambda: h.client(control)['title'] == title+' clicked', 'Outside click did not reach the visible control')
        time.sleep(.65)
        assert stopped(), 'Finished native interaction restarted on a later lease renewal'
        print('PASS Manage restores card movement and outside click exits without rearming or eating the click', flush=True)

        configure('floatingPreviewActivation', 'click')
        before = len(events(log, 'press'))
        value = ready(session, record)
        session.click({'x':value['imageRect']['x']+30, 'y':value['imageRect']['y']+value['imageRect']['height']*.6, 'width':10, 'height':10})
        wait(lambda: active(record), 'First-click activation did not start interaction')
        assert len(events(log, 'press')) == before, 'Activating click was forwarded into the application'
        assert_source(record, original)
        configure('floatingPreviewInteraction', 'off')
        wait(stopped, 'Disabling interactivity retained an input owner')
        assert_source(record, original)
        print('PASS optional first-click activation consumes the click; disabling interactivity releases input without restoring the source', flush=True)

        configure('floatingPreviewInteraction', 'on')
        configure('floatingPreviewActivation', 'explicit')
        start(session, record)
        value = show_controls(session, record)
        session.click(value['interaction']['restoreRect'])
        wait(stopped, 'Restore control retained the interaction worker')
        wait(lambda: h.client(address)['workspace']['id'] == session.workspace, 'Restore control did not restore its own source')
        assert h.client(address)['floating'] and h.client(address)['size'] == original[2], 'Restoring after interaction lost original floating size'
        record = park(session, address)
        ready(session, record)
        source_click(session, record, button=273)
        wait(lambda: session.menu()['opened'], 'Inactive preview did not retain its plugin context menu')
        session.click(session.action('interact')['rect'])
        wait(lambda: active(record), 'Context Interact action did not start its exact target')
        shell('dismiss')
        wait(stopped, 'Dismiss did not release the active interaction')
        drain()
        assert not shell('status')['error'], shell('status')['error']
        print('PASS explicit restore keeps saved geometry, context Interact targets its exact window, and dismissal cleans up ownership', flush=True)
    wait(stopped, 'Preserving cleanup retained an interaction process')
    assert not command('list')['windows'], 'Interactive acceptance retained fixture stash records'


if __name__ == '__main__':
    main()
