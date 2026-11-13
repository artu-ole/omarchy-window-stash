#!/usr/bin/env python3
"""Real tabbed Chromium/Brave navigation in a disposable compositor only."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

from desktop_test import desktop_test
from floating_previews import drain, park, seed
from interactive_apps import page_state, spawn
from interactive_bridge import spawn_fixture
from interactive_fullscreen import GeometryProbe, original, require_isolated
from interactive_handoff import Events, monitor_records, source_point
from interactive_previews import active, assert_source, interaction, start, stopped
from live import command, configure, h, shell, wait
from bridge import BridgeManager
from native_session import NativeSession
from preview import PreviewBridge
from stash import SPECIAL


def status():
    return interaction().get('status', {}).get('status', {})


def plus_button(address):
    """Locate the real plus glyph in the one-tab browser chrome, without app mode."""
    client = h.client(address)
    width, height = client['size'][0], min(60, client['size'][1])
    geometry = '%d,%d %dx%d' % (*client['at'], width, height)
    raw = subprocess.check_output(['grim', '-s', '1', '-t', 'ppm', '-g', geometry, '-'], timeout=5)
    pixels = raw.split(b'\n', 3)[3]
    def light(x, y):
        offset = 3*(y*width+x)
        return sum(pixels[offset:offset+3])/3
    candidates = []
    for y in range(8, min(43, height-7)):
        for x in range(245, min(450, width-7)):
            background = sum(light(x+dx, y+dy) for dx, dy in ((-6,-6),(-6,6),(6,-6),(6,6)))/4
            center = light(x, y)
            sign = 1 if center > background else -1
            arms = [sign*(light(x+dx, y+dy)-background)
                    for distance in (1,2,3) for dx,dy in ((distance,0),(-distance,0),(0,distance),(0,-distance))]
            diagonals = [abs(light(x+dx, y+dy)-background) for dx,dy in ((-4,-4),(-4,4),(4,-4),(4,4))]
            if min(arms) > 35 and max(diagonals) < 30:
                candidates.append((sum(arms)/len(arms)-sum(diagonals)/4, x, y))
    assert candidates, 'Could not locate the real browser New tab plus button'
    _, x, y = max(candidates)
    return x, y


def write_pages(directory, title):
    target = directory/'target.html'
    target.write_text('<!doctype html><title>'+title+' target</title><body style="margin:0;background:#e57722;color:white;font:32px sans-serif">Second local tab</body>')
    page = directory/'initial.html'
    page.write_text('''<!doctype html><meta charset="utf-8"><style>
body{margin:0;background:#2053d8;color:white;font:24px sans-serif}a{display:inline-block;width:240px;height:80px;margin:30px;padding:20px;background:white;color:black}
</style><h1>Normal browser tabs</h1><a id="blank" target="_blank" href="target.html">Target blank</a><a id="middle" href="target.html">Middle-click tab</a><script>
const title='''+json.dumps(title)+''';function publish(){const b=document.querySelector('#blank').getBoundingClientRect(),m=document.querySelector('#middle').getBoundingClientRect();
document.title=title+'|'+encodeURIComponent(JSON.stringify({width:innerWidth,height:innerHeight,blank:[b.x+b.width/2,b.y+b.height/2],middle:[m.x+m.width/2,m.y+m.height/2]}));}
addEventListener('resize',publish);setInterval(publish,250);publish();</script>''')
    return page


def private(record, before, witness, observer):
    assert active(record), ('Tab navigation ended miniature interaction', interaction())
    assert_source(record, before)
    monitor_records(witness)
    observer.check()


def initial(address, title):
    return page_state(address, title)


def close_tab(session, address, title):
    session.keys('-M', 'ctrl', '-k', 'w', '-m', 'ctrl')
    wait(lambda: initial(address, title), 'Closing the new tab did not return to the original local page')


def browser(session, directory, executable, witness, observer):
    title = 'Window Stash normal tab navigation '+executable+' '+str(os.getpid())
    page = write_pages(directory, title)
    stderr = directory/(executable+'.stderr')
    argv = [executable, '--user-data-dir='+str(directory/(executable+'-profile')), '--no-first-run',
            '--no-default-browser-check', '--disable-background-networking', '--disable-component-update',
            '--disable-sync', '--password-store=basic', '--ozone-platform=wayland', '--no-sandbox',
            '--new-window', page.as_uri()]
    address = spawn(session, argv, title, stderr)
    h.dispatch('window.move', window='address:'+address, x=session.monitor['x']+200, y=session.monitor['y']+100, relative=False)
    wait(lambda: h.client(address)['at'] == [session.monitor['x']+200, session.monitor['y']+100],
         'The owned browser did not settle inside the independent test output')
    wait(lambda: (value := initial(address, title)) and value['width'] == h.client(address)['size'][0],
         'Normal browser did not resize its original tab')
    # Chrome positions this control independently of the page. Read its actual
    # pixels before parking, then forward a real pointer click to the same place.
    plus = plus_button(address)
    record = park(session, address)
    seed(session, record, 180, 150, 440)
    before = original(record)
    control, _ = session.spawn(app='org.windowstash.BrowserTabsControl')
    h.dispatch('focus', window='address:'+control)
    start(session, record)
    with GeometryProbe(session, record):
        source_point(session, record, *plus)
        wait(lambda: 'new tab' in h.client(address)['title'].lower(), 'Mouse plus did not open a genuine browser tab')
        private(record, before, witness, observer)
        assert status().get('keyboardFocused'), 'Clicking the browser plus did not acquire permitted keyboard focus'
        close_tab(session, address, title)
        private(record, before, witness, observer)
        print('PASS '+executable+' normal-browser mouse plus and Ctrl+W preserve the same interactive preview', flush=True)

        acknowledged = status().get('keyboardActivationAcknowledgements', 0)
        session.keys('-M', 'ctrl', '-k', 't', '-m', 'ctrl')
        wait(lambda: 'new tab' in h.client(address)['title'].lower(), 'Ctrl+T did not open a genuine browser tab')
        wait(lambda: status().get('keyboardActivationAcknowledgements', 0) > acknowledged,
             'The real keyboard-owned tab activation did not reach the native acknowledgement path')
        private(record, before, witness, observer)
        session.keys('-M', 'ctrl', '-M', 'shift', '-k', 'Tab', '-m', 'shift', '-m', 'ctrl')
        wait(lambda: initial(address, title), 'Ctrl+Shift+Tab did not select the original tab')
        private(record, before, witness, observer)
        session.keys('-M', 'ctrl', '-k', 'Tab', '-m', 'ctrl')
        wait(lambda: 'new tab' in h.client(address)['title'].lower(), 'Ctrl+Tab did not select the newly opened tab')
        private(record, before, witness, observer)
        close_tab(session, address, title)
        print('PASS '+executable+' Ctrl+T and tab switching acknowledge redundant focus without restoring the source', flush=True)

        for name, button in (('blank', 272), ('middle', 274)):
            state = wait(lambda: initial(address, title), 'The original tab was not available for local link input')
            inset_x = max(0, (before[2][0]-state['width'])/2)
            inset_y = max(0, before[2][1]-state['height'])
            x, y = state[name]
            if button == 272:
                source_point(session, record, inset_x+x, inset_y+y)
            else:
                source_middle(session, record, inset_x+x, inset_y+y)
            if button == 274:
                time.sleep(.2)
                private(record, before, witness, observer)
                session.keys('-M', 'ctrl', '-k', 'Tab', '-m', 'ctrl')
            wait(lambda: title+' target' in h.client(address)['title'], name+' did not create/select the real local target tab')
            private(record, before, witness, observer)
            close_tab(session, address, title)
            private(record, before, witness, observer)
        print('PASS '+executable+' target-blank and middle-click background tabs remain contained with unchanged source geometry', flush=True)

    # A genuine WM action must retain its explicit restoration meaning even
    # immediately after the browser has acknowledged an ordinary tab action.
    h.dispatch('focus', window='address:'+address)
    wait(lambda: h.client(address)['workspace']['name'] != SPECIAL, 'Explicit WM focus was swallowed by keyboard-owned activation handling')
    wait(stopped, 'Explicit WM focus retained hidden browser input')
    assert not any(value['id'] == record['id'] for value in command('list')['windows'])
    monitor_records(witness);observer.check()
    h.dispatch('window.close', window='address:'+address)
    wait(lambda: not h.client(address), 'Owned normal browser did not close')
    print('PASS '+executable+' explicit WM focus still restores the exact source after tab interactions', flush=True)


def source_middle(session, record, x, y):
    size = h.client(record['address'])['size']
    from interactive_previews import source_click
    source_click(session, record, x/size[0], y/size[1], button=274)


@desktop_test('Isolated normal-browser tab activation regression')
def main(apps):
    require_isolated()
    PreviewBridge(h).ensure()
    manager = BridgeManager(h)
    assert manager.native().get('fingerprint') == manager.build(manager.commit())['fingerprint'], 'Refresh the owned native test module before running this checkout'
    with tempfile.TemporaryDirectory(prefix='stash-browser-tabs-') as temporary, NativeSession() as session:
        for key, value in dict(presentation='previews', scope='global', grouping='window', restoreDestination='original',
                               floatingPreviewInteraction='on', floatingPreviewActivation='explicit', floatingPreviewKeyboard='click',
                               floatingPreviewFullscreen='preview', floatingPreviewInteractionFps='60', floatingPreviewControls='always',
                               floatingPreviewUpdate='live', livePreviewCompatibility='enhanced', hoverPreview='off',
                               floatingPreviewSizing='free', floatingPreviewTitles='hidden', floatingPreviewFrame='hidden',
                               floatingPreviewLock='unlocked', floatingPlacement='free', dragMotion='direct', animations='off').items():
            configure(key, value)
        directory = Path(temporary)
        witness = park(session, spawn_fixture(session, directory/'witness.jsonl'))
        seed(session, witness, 850, 150, 280)
        observer = Events()
        try:
            for executable in apps:
                assert shutil.which(executable), 'Requested browser is unavailable: '+executable
                browser(session, directory, executable, witness, observer)
        finally:
            shell('dismiss')
            configure('presentation', 'dock')
            drain()
            wait(lambda: not any(card.get('image', {}).get('captureActive') for surface in shell('status')['surfaces']
                                 for card in surface['floatingPreviews']['cards']) and manager.native().get('owners') == 0, 'Owned captures did not stop before fixture termination')
            observer.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apps', nargs='+', choices=('brave', 'chromium'), default=['brave', 'chromium'])
    main(parser.parse_args().apps)
