#!/usr/bin/env python3
"""Contained application/video fullscreen in a disposable compositor only.

Uses actual GTK fullscreen requests, Omarchy's normal Super+F dispatcher and
local browser video Fullscreen API requests. Runtime profiles, pixels and logs
stay outside the checkout; no input reaches the real desktop.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
import uuid

from desktop_test import desktop_test
from floating_previews import card, drag, park, ready, seed
from interactive_apps import page_state, spawn as spawn_app
from interactive_bridge import begin as native_begin, events, local_point, native_status, spawn_fixture
from interactive_handoff import Events, monitor_records, source_point
from interactive_previews import active, assert_source, interaction, source_click, start, stopped
from live import command, configure, h, shell, wait
from bridge import BridgeManager
from native_session import NativeSession
from preview import API, PreviewBridge
from stash import DEFAULTS


def require_isolated():
    assert os.environ.get('WINDOW_STASH_ISOLATED_TEST') == '1' and (Path.home()/'.window-stash-isolated').is_file(), \
        'Refusing input outside an explicitly disposable desktop'
    assert not command('list')['windows'], 'Use an empty disposable stash'


def modes(address):
    value = h.client(address)
    return value and (value.get('fullscreen'), value.get('fullscreenClient'))


def original(record):
    value = h.client(record['address'])
    return value['workspace'], value['at'], value['size'], value['floating']



class GeometryProbe:
    """Sample source and preview independently so shell IPC cannot stall source checks."""
    def __init__(self, session, record):
        self.session, self.record = session, record
        self.source = original(record)
        self.preview = self.preview_geometry()
        self.finished = threading.Event()
        self.failures = []
        self.samples = {'source': 0, 'preview': 0}
        self.gaps = {'source': [], 'preview': []}

    def preview_geometry(self):
        value = card(self.session, self.record)
        assert value, 'The contained preview disappeared during geometry sampling'
        return tuple(value[key] for key in ('x', 'y', 'width', 'height'))+tuple(
            value['imageRect'][key] for key in ('x', 'y', 'width', 'height'))

    def sample(self, kind):
        previous = time.monotonic()
        deadline = previous
        while not self.finished.is_set():
            now = time.monotonic()
            self.gaps[kind].append(now-previous)
            previous = now
            try:
                if kind == 'source':
                    observed = original(self.record)
                    assert observed == self.source, ('Source geometry changed during fullscreen', self.source, observed)
                else:
                    observed = self.preview_geometry()
                    assert all(abs(a-b) < .05 for a, b in zip(observed, self.preview)), \
                        ('Preview geometry changed during fullscreen', self.preview, observed)
                self.samples[kind] += 1
            except Exception as error:
                self.failures.append(repr(error))
                return
            deadline += .01 if kind == 'source' else .02
            self.finished.wait(max(0, deadline-time.monotonic()))

    def __enter__(self):
        self.threads = [threading.Thread(target=self.sample, args=(kind,), daemon=True) for kind in self.samples]
        for thread in self.threads:
            thread.start()
        return self

    def __exit__(self, kind, value, traceback):
        self.finished.set()
        for thread in self.threads:
            thread.join(timeout=3)
            assert not thread.is_alive(), 'Geometry sampling did not stop'
        if kind is None:
            assert not self.failures, self.failures
        print('Fullscreen geometry samples:', self.samples, 'max intervals(ms):',
              {key: round(max(gaps, default=0)*1000, 1) for key, gaps in self.gaps.items()},
              'failures:', self.failures, flush=True)


def confined(record, before, witness, observer):
    assert_source(record, before)
    assert modes(record['address']) == (0, 2), ('Client fullscreen escaped its retained floating geometry', h.client(record['address']))
    assert active(record), 'Contained fullscreen ended interaction'
    monitor_records(witness)
    observer.check()


def wait_fullscreen(record, enabled=True):
    wanted = (0, 2 if enabled else 0)
    return wait(lambda: modes(record['address']) == wanted, 'Contained fullscreen modes did not become '+str(wanted))


def browser_exit_modes(record):
    return wait(lambda: (value := modes(record['address'])) and value[0] == 0 and value[1] in (0, 1),
                'Browser fullscreen exit did not retain an ordinary contained client mode')


def input_focus(session, record):
    source_click(session, record, .7, .7)
    wait(lambda: interaction()['status'].get('status', {}).get('keyboardFocused'),
         'Content click did not acquire keyboard focus')


def key_fullscreen(session):
    session.keys('-M', 'logo', '-k', 'f', '-m', 'logo')


def stop():
    shell('dismiss')
    wait(stopped, 'Stopping retained application input')


def install_fullscreen_binding():
    assert not any(value.get('modmask') == 64 and str(value.get('key', '')).lower() == 'f'
                   and value.get('enabled') is not False and value.get('disabled') is not True
                   and value.get('description') != 'Window Stash isolated stock fullscreen proof'
                   for value in h.read('binds')), 'Super+F is already bound in the disposable profile'
    name = '__window_stash_contained_fullscreen_'+str(os.getpid())
    h.call('repl', '_G.'+name+'=assert(hl.bind("SUPER + F",hl.dsp.window.fullscreen({mode="fullscreen"}),'
           '{description="Window Stash isolated stock fullscreen proof"}));return true')
    return name


def disable_binding(name):
    h.call('repl', 'if _G.'+name+' then _G.'+name+':set_enabled(false);_G.'+name+'=nil end;return true')


def gtk(session, directory, witness, observer):
    log = directory/'gtk.jsonl'
    address = spawn_fixture(session, log)
    public = h.client(address)
    control, title = session.spawn(app='org.windowstash.ContainedFullscreenControl')
    record = park(session, address)
    seed(session, record, 180, 150, 440)
    before = original(record)
    h.dispatch('focus', window='address:'+control)
    start(session, record)
    source_point(session, record, 900, 46)
    wait(lambda: events(log, 'fullscreen-request'), 'GTK fullscreen button was not activated')
    wait_fullscreen(record)
    confined(record, before, witness, observer)
    wait(lambda: (values := events(log, 'fullscreen-state')) and values[-1]['active'],
         'GTK did not receive a real fullscreen configure')
    session.keys('-k', 'Escape')
    wait_fullscreen(record, False)
    assert_source(record, before)
    assert active(record), 'Application Escape left interaction instead of fullscreen'
    print('PASS actual GTK fullscreen button receives fullscreen state inside the unchanged preview; Escape exits without desktop exposure', flush=True)

    source_click(session, record)
    session.keys('-k', 'F11')
    wait_fullscreen(record)
    confined(record, before, witness, observer)
    session.keys('-k', 'F11')
    wait_fullscreen(record, False)
    source_click(session, record)
    key_fullscreen(session)
    wait_fullscreen(record)
    confined(record, before, witness, observer)
    key_fullscreen(session)
    wait_fullscreen(record, False)
    assert_source(record, before)
    assert h.client(control)['title'] == title, 'Fullscreen interaction clicked the underlying visible application'
    print('PASS application F11 and actual stock Super+F toggle client fullscreen, preserving source/preview geometry and foreign windows', flush=True)

    key_fullscreen(session)
    wait_fullscreen(record)
    stop()
    assert modes(address) == (0, 2), 'Stopping collapsed passive picture-in-picture content'
    assert_source(record, before)
    initial = ready(session, record)
    drag(session, initial['resizeRect'], 90, 60)
    wait(lambda: ready(session, record)['width'] > initial['width']+35,
         'Passive fullscreen preview could not be resized')
    assert modes(address) == (0, 2)
    assert_source(record, before)
    monitor_records(witness);observer.check()
    start(session, record)
    input_focus(session, record)
    session.pointer.click(*session.point(60, 450))
    wait(stopped, 'Outside click did not end fullscreen interaction')
    assert modes(address) == (0, 2), 'Outside click collapsed passive fullscreen content'
    assert_source(record, before)
    print('PASS Stop, passive preview resizing and outside click retain fullscreen content and unchanged source geometry', flush=True)

    h.dispatch('focus', window='address:'+address)
    wait(lambda: h.client(address)['workspace']['id'] == session.workspace and modes(address) == (0, 0),
         'Activating passive picture-in-picture did not restore its exact window through the shell')
    observer.check()
    assert 'window-stash-restore>>'+record['id'] in observer.buffer, 'Passive fullscreen activation did not use the owned restoration event'
    assert not any(value['id'] == record['id'] for value in command('list')['windows']), 'Passive activation retained the restored record'
    restored = h.client(address)
    assert (restored['at'], restored['size'], restored['floating']) == (public['at'], public['size'], public['floating']), \
        ('Contained fullscreen changed saved floating restoration geometry', public, restored)
    monitor_records(witness);observer.check()
    print('PASS passive activation restores only its owned window, exits contained fullscreen and reinstates exact saved floating geometry', flush=True)

    record = park(session, address)
    seed(session, record, 180, 150, 440)
    before = original(record)
    h.dispatch('focus', window='address:'+control)
    image = ready(session, record)['imageRect']
    rect = dict(x=session.monitor['x']+image['x'], y=session.monitor['y']+image['y'],
                width=image['width'], height=image['height'])
    owner = uuid.uuid4().hex
    native_begin(owner, record, session.monitor['name'], rect, keyboard=True)
    point = local_point(session, rect, .7, .7)
    session.move(*point)
    session.pointer.click(*session.point(*point))
    session.keys('-k', 'F11')
    wait_fullscreen(record)
    wait(lambda: not native_status(owner)['active'], 'Abandoned fullscreen input lease did not expire', timeout=5)
    assert native_status(owner)['reason'] == 'expired'
    assert modes(address) == (0, 2), 'Lease expiry collapsed passive picture-in-picture content'
    assert_source(record, before)
    command('restore', record['id'], '--to', 'original')
    wait(lambda: modes(address) == (0, 0) and h.client(address)['workspace']['id'] == session.workspace,
         'Expired fullscreen lease could not be restored normally')
    print('PASS abandoned input expires without collapsing passive fullscreen; ordinary restoration still clears the temporary mode', flush=True)

    configure('floatingPreviewKeyboard', 'mouse')
    record = park(session, address)
    seed(session, record, 180, 150, 440)
    h.dispatch('focus', window='address:'+control)
    start(session, record)
    source_point(session, record, 900, 46)
    wait_fullscreen(record)
    h.dispatch('focus', window='address:'+address)
    wait(stopped, 'Explicit focus did not end mouse-only fullscreen interaction')
    wait(lambda: h.client(address)['workspace']['id'] == session.workspace and modes(address) == (0, 0),
         'Explicit window-manager focus was swallowed by a mouse-only input acknowledgement')
    monitor_records(witness);observer.check()
    configure('floatingPreviewKeyboard', 'click')
    print('PASS explicit window-manager focus restores mouse-only fullscreen immediately instead of consuming it as an input acknowledgement', flush=True)

    # An originally fullscreen application must still recover its own saved
    # fullscreen state; clearing the temporary mode must not rewrite the ledger.
    h.dispatch('window.fullscreen_state', window='address:'+address, internal=2, client=2, action='set')
    wait(lambda: modes(address) == (2, 2), 'Original fullscreen fixture did not enter normal fullscreen')
    record = park(session, address)
    seed(session, record, 180, 150, 440)
    assert record['fullscreen'] == 2 and record['fullscreenClient'] == 2
    h.dispatch('focus', window='address:'+control)
    start(session, record)
    source_click(session, record)
    key_fullscreen(session)
    wait_fullscreen(record)
    stop()
    command('restore', record['id'], '--to', 'original')
    wait(lambda: h.client(address)['workspace']['id'] == session.workspace and modes(address) == (2, 2),
         'Contained fullscreen cleanup lost the original pre-stash fullscreen snapshot')
    h.dispatch('window.fullscreen_state', window='address:'+address, internal=0, client=0, action='set')
    print('PASS original pre-stash fullscreen state survives temporary confined fullscreen and is reapplied on restore', flush=True)

    record = park(session, address)
    seed(session, record, 180, 150, 440)
    h.dispatch('focus', window='address:'+control)
    start(session, record)
    source_click(session, record)
    session.keys('-k', 'F11')
    wait_fullscreen(record)
    stop()
    h.dispatch('window.close', window='address:'+address)
    wait(lambda: not h.client(address), 'Owned passive fullscreen application did not close')
    wait(lambda: int(h.call('repl', 'return '+API+'.status().constrainedFullscreenWindows')) == 0,
         'Closed passive fullscreen source retained native ownership')
    monitor_records(witness);observer.check()
    print('PASS closing a passive fullscreen source clears its exact native ownership without disturbing other stashes', flush=True)


def image_pixels(session, record):
    value = ready(session, record)
    image = value['imageRect']
    geometry = '%d,%d %dx%d' % (round(session.monitor['x']+image['x']), round(session.monitor['y']+image['y']),
                               max(1, round(image['width'])), max(1, round(image['height'])))
    ppm = subprocess.check_output(['grim', '-s', '1', '-t', 'ppm', '-g', geometry, '-'],
                                  stderr=subprocess.DEVNULL, timeout=5)
    return ppm.split(b'\n', 3)[3]


def pixel_colors(session, record):
    pixels = image_pixels(session, record)
    count = max(1, len(pixels)//3)
    green = sum(pixels[index] < 100 and pixels[index+1] > 110 and pixels[index+2] < 150
                for index in range(0, len(pixels)-2, 3))/count
    blue = sum(pixels[index] < 100 and pixels[index+1] < 130 and pixels[index+2] > 150
               for index in range(0, len(pixels)-2, 3))/count
    return green, blue


def browser_page(path, title):
    path.write_text('''<!doctype html><meta charset="utf-8"><style>
*{box-sizing:border-box}body{margin:0;background:#20242a;color:white;font:24px sans-serif}
header{height:120px;background:#2053d8;padding:20px}button{font:20px sans-serif;height:64px;width:260px}#passive{width:180px}
main{padding:28px}video{width:640px;height:360px;background:#24ac60;object-fit:contain}
video:fullscreen{width:100%;height:100%;background:black}
</style><header>Website navigation <button>Fullscreen video</button><button id="ordinary">Ordinary control</button><button id="passive">Auto-exit video</button></header>
<main><video autoplay muted playsinline controls></video><p>Website controls outside the video</p></main>
<script>
const title='''+json.dumps(title)+''';const video=document.querySelector('video');
const canvas=document.createElement('canvas');canvas.width=640;canvas.height=360;
const context=canvas.getContext('2d');let frame=0,clicks=0;
function draw(){context.fillStyle='#24ac60';context.fillRect(0,0,640,360);
 context.fillStyle='#fff';context.fillRect((frame++*8)%640,150,24,60)}
draw();video.srcObject=canvas.captureStream(15);video.play();setInterval(draw,66);
function publish(){const r=video.getBoundingClientRect(),b=document.querySelector('button').getBoundingClientRect(),o=document.querySelector('#ordinary').getBoundingClientRect(),p=document.querySelector('#passive').getBoundingClientRect();
 document.title=title+'|'+encodeURIComponent(JSON.stringify({fullscreen:!!document.fullscreenElement,
 element:document.fullscreenElement?.tagName||'',width:innerWidth,height:innerHeight,
 video:[r.x,r.y,r.width,r.height],button:[b.x+b.width/2,b.y+b.height/2],ordinary:[o.x+o.width/2,o.y+o.height/2],passive:[p.x+p.width/2,p.y+p.height/2],clicks:clicks,ready:video.readyState,time:video.currentTime}));}
document.querySelector('button').onclick=()=>{video.play();video.requestFullscreen().then(publish)};
document.querySelector('#ordinary').onclick=()=>{clicks++;publish()};
document.querySelector('#passive').onclick=()=>{video.play();video.requestFullscreen().then(()=>{publish();setTimeout(()=>document.exitFullscreen().then(publish),4000)})};
document.addEventListener('fullscreenchange',publish);addEventListener('resize',publish);
video.addEventListener('loadeddata',publish);setInterval(publish,250);publish();
</script>''')


def browser(session, directory, executable, witness, observer, pointer_only=True, desktop_only=False, original_maximized=False):
    configure('floatingPreviewFullscreen', 'preview')
    title = 'Stash contained '+executable+' '+str(os.getpid())
    page = directory/(executable+'-fullscreen.html')
    browser_page(page, title)
    argv = [executable, '--user-data-dir='+str(directory/(executable+'-profile')), '--no-first-run',
            '--no-default-browser-check', '--disable-background-networking', '--disable-component-update',
            '--disable-sync', '--password-store=basic', '--disable-features=MediaRouter', '--ozone-platform=wayland', '--no-sandbox',
            '--app='+page.as_uri(), '--class=org.windowstash.ContainedBrowser']
    if os.environ.get('WINDOW_STASH_FULLSCREEN_TRACE') == '1':
        argv += ['--enable-logging=stderr', '--vmodule=wayland_toplevel_window=3,wayland_window=3']
    address = spawn_app(session, argv, title, directory/(executable+'.stderr'))
    state = wait(lambda: (value := page_state(address, title)) and value['ready'] >= 2
                 and value['width'] == h.client(address)['size'][0] and value,
                 'Local video did not start at its configured size in '+executable)
    if desktop_only:
        control, _ = session.spawn(app='org.windowstash.ContainedBrowserControl')
        if original_maximized:
            # Adding a tiled control can leave the old maximized layout. Apply
            # the precondition only after every visible fixture is mapped.
            h.dispatch('window.fullscreen_state', window='address:'+address, internal=1, client=1, action='set')
            wait(lambda: modes(address) == (1, 1), 'Original browser maximize did not settle')
        desktop_browser(session, address, title, control, executable, witness, observer,
                        expected_original=(1,1) if original_maximized else None)
        return
    record = park(session, address)
    seed(session, record, 180, 150, 440)
    before = original(record)
    with GeometryProbe(session, record):
        control, _ = session.spawn(app='org.windowstash.ContainedBrowserControl')
        h.dispatch('focus', window='address:'+control)
        configure('floatingPreviewKeyboard', 'mouse' if pointer_only else 'click')
        start(session, record)
        baseline = wait(lambda: (colors := pixel_colors(session, record))[1] > .05 and colors,
                        'Browser preview did not show the website navigation before fullscreen')
        state = page_state(address, title)
        inset_x = max(0, (before[2][0]-state['width'])/2)
        inset_y = max(0, before[2][1]-state['height'])
        if pointer_only:
            source_point(session, record, inset_x+state['ordinary'][0], inset_y+state['ordinary'][1])
            wait(lambda: page_state(address, title)['clicks'] == 1, 'Mouse-only ordinary browser control did not receive input')
            time.sleep(.65)
            assert active(record), 'A normal mouse-only browser click promoted the hidden application'
            assert_source(record, before)
            assert modes(address) == (0, 0)
            assert h.read('activewindow').get('address') == control, 'Mouse-only browser input stole the visible keyboard target'
            state = page_state(address, title)
        source_point(session, record, inset_x+state['button'][0], inset_y+state['button'][1])
        wait(lambda: (value := page_state(address, title)) and value['fullscreen'] and value['element'] == 'VIDEO',
             'Actual video Fullscreen API request did not complete in '+executable)
        wait_fullscreen(record)
        confined(record, before, witness, observer)
        colors = wait(lambda: (value := pixel_colors(session, record))[0] > max(.65, baseline[0]+.15)
                      and value[1] < .005 and value,
                      'Fullscreen video did not replace website UI throughout the preview in '+executable)
        frame = page_state(address, title)['time']
        wait(lambda: page_state(address, title)['time'] > frame+.2, 'Actual fullscreen video stopped playback in '+executable)
        assert_source(record, before)
        if pointer_only:
            assert not interaction()['status']['status']['keyboardFocused'], 'Mouse-only video fullscreen stole keyboard focus'
            assert h.read('activewindow').get('address') == control, 'Mouse-only fullscreen changed the real keyboard target'
            configure('floatingPreviewKeyboard', 'click')
            wait(stopped, 'Changing keyboard permission did not finish the previous interaction')
            assert page_state(address, title)['fullscreen'], 'Changing keyboard permission collapsed passive fullscreen'
            assert modes(address) == (0, 2), ('Keyboard permission change altered the contained client state', modes(address), page_state(address, title))
            start(session, record)
            assert modes(address) == (0, 2), ('Re-entering interaction altered the contained client state', modes(address), page_state(address, title))
            input_focus(session, record)
            assert modes(address) == (0, 2), ('Acquiring keyboard focus altered the contained client state', modes(address), page_state(address, title))
        if os.environ.get('WINDOW_STASH_FULLSCREEN_TRACE') == '1':
            print('Before browser Escape pending fullscreen:', h.call('repl', 'return '+API+'.status().pendingFullscreen'), flush=True)
        session.keys('-k', 'Escape')
        try:
            wait(lambda: not page_state(address, title)['fullscreen'], 'Escape did not exit real video fullscreen in '+executable)
        except AssertionError:
            registry = h.call('repl', 'local s='+API+'.status(); local out={};for _,v in ipairs(s.fullscreenWindows) do '
                             'out[#out+1]=string.format("%s:%d:%d",v.id,v.client,v.originalClient) end;return table.concat(out,",")')
            print('Video Escape diagnostics:', {'page':page_state(address,title),'modes':modes(address),
                  'pixels':pixel_colors(session,record),'registry':registry}, flush=True)
            raise
        browser_exit_modes(record)
        wait(lambda: pixel_colors(session, record)[1] > .05, 'Website UI did not return after exiting fullscreen')
        assert active(record)
        print('PASS '+executable+' video.requestFullscreen hides website UI, fills the preview with moving video and exits with Escape; pixels='+str(colors), flush=True)

        # Browser-level fullscreen and Omarchy's unmodified dispatcher use the same
        # retained source, independently of the page's element fullscreen mode.
        session.keys('-k', 'F11')
        wait_fullscreen(record)
        confined(record, before, witness, observer)
        assert not page_state(address, title)['fullscreen'], 'Browser F11 unexpectedly fullscreened a page element'
        session.keys('-k', 'F11')
        browser_exit_modes(record)
        key_fullscreen(session)
        wait_fullscreen(record)
        confined(record, before, witness, observer)
        assert not page_state(address, title)['fullscreen'], 'Stock Super+F unexpectedly fullscreened a page element'
        key_fullscreen(session)
        browser_exit_modes(record)
        assert_source(record, before)
        print('PASS '+executable+' F11 and actual stock Super+F toggle contained application fullscreen independently of video fullscreen', flush=True)

        # Re-enter through the browser's genuine fullscreen button, then leave
        # interaction: the video remains picture-in-picture while input is released.
        state = page_state(address, title)
        inset_x = max(0, (before[2][0]-state['width'])/2)
        inset_y = max(0, before[2][1]-state['height'])
        source_point(session, record, inset_x+state['button'][0], inset_y+state['button'][1])
        wait(lambda: page_state(address, title)['fullscreen'], 'Video did not re-enter fullscreen')
        stop()
        assert modes(address) == (0, 2) and page_state(address, title)['fullscreen']
        wait(lambda: pixel_colors(session, record)[0] > .65, 'Passive fullscreen video disappeared after Stop')
        frame = page_state(address, title)['time']
        wait(lambda: page_state(address, title)['time'] > frame+.2, 'Passive fullscreen video stopped playback after input release')
        time.sleep(2.5)  # Let native video controls fade before measuring motion.
        frames = set()
        for _ in range(9):
            frames.add(hashlib.sha256(image_pixels(session, record)).hexdigest())
            time.sleep(.12)
        assert len(frames) >= 4, ('Passive picture-in-picture pixels did not keep updating', executable, len(frames))
        h.eval('assert('+API+'.prepare_reload())')
        try:
            browser_exit_modes(record)
            wait(lambda: not page_state(address, title)['fullscreen'], 'Reload preparation did not exit DOM video fullscreen')
            assert_source(record, before)
            observer.check();monitor_records(witness)
        finally:
            h.eval('assert('+API+'.cancel_reload())')
        configure('floatingPreviewUpdate', 'still')
        configure('floatingPreviewUpdate', 'live')
        start(session, record)
        state = page_state(address, title)
        inset_x = max(0, (before[2][0]-state['width'])/2)
        inset_y = max(0, before[2][1]-state['height'])
        source_point(session, record, inset_x+state['button'][0], inset_y+state['button'][1])
        wait(lambda: page_state(address, title)['fullscreen'], 'Video could not re-enter fullscreen after cancelled reload preparation')
        wait_fullscreen(record)
        stop()
    command('restore', record['id'], '--to', 'original')
    restored_modes = record['fullscreen'], record['fullscreenClient']
    wait(lambda: h.client(address)['workspace']['id'] == session.workspace and modes(address) == restored_modes,
         'Browser restoration retained temporary fullscreen')
    wait(lambda: not page_state(address, title)['fullscreen'], 'Restored browser retained DOM video fullscreen')
    assert h.client(address)['size'] == before[2]
    monitor_records(witness);observer.check()
    # Simulate a video/app ending fullscreen itself after input is released.
    # The delayed DOM request has no active helper or forwarded input to guard it.
    record = park(session, address)
    seed(session, record, 180, 150, 440)
    before = original(record)
    with GeometryProbe(session, record):
        h.dispatch('focus', window='address:'+control)
        start(session, record)
        state = page_state(address, title)
        inset_x = max(0, (before[2][0]-state['width'])/2)
        inset_y = max(0, before[2][1]-state['height'])
        source_point(session, record, inset_x+state['passive'][0], inset_y+state['passive'][1])
        wait(lambda: page_state(address, title)['fullscreen'], 'Delayed-exit video did not enter actual fullscreen')
        wait_fullscreen(record)
        stop()
        assert page_state(address, title)['fullscreen'], 'Delayed exit happened before the input helper stopped'
        wait(lambda: not page_state(address, title)['fullscreen'], 'Passive app-origin fullscreen exit did not finish')
        browser_exit_modes(record)
        assert stopped(), 'Passive app fullscreen exit acquired input ownership'
        assert_source(record, before)
        wait(lambda: pixel_colors(session, record)[1] > .05, 'Passive fullscreen exit did not restore the website UI')
        frame = page_state(address, title)['time']
        wait(lambda: page_state(address, title)['time'] > frame+.2, 'Passive app-origin fullscreen exit stalled actual video')
        monitor_records(witness);observer.check()
    command('restore', record['id'], '--to', 'original')
    wait(lambda: h.client(address)['workspace']['id'] == session.workspace
         and modes(address) == (record['fullscreen'], record['fullscreenClient']),
         'Passive app exit polluted the original fullscreen restoration snapshot')
    assert h.client(address)['size'] == before[2]
    assert not page_state(address, title)['fullscreen']
    monitor_records(witness);observer.check()
    print('PASS '+executable+' app-origin fullscreen exit after Stop preserves passive geometry, video playback and exact original-mode restoration', flush=True)

    print('PASS '+executable+' retains '+str(len(frames))+' distinct passive video frames after Stop; reload preparation and restoration clear temporary fullscreen without exposing the stash', flush=True)
    desktop_browser(session, address, title, control, executable, witness, observer)


def desktop_browser(session, address, title, control, executable, witness, observer, expected_original=None):
    configure('floatingPreviewFullscreen', 'desktop')
    configure('floatingPreviewKeyboard', 'mouse')
    record = park(session, address)
    if expected_original is not None:
        assert (record['fullscreen'],record['fullscreenClient']) == expected_original, \
            ('Desktop fullscreen fixture lost its original-mode precondition',expected_original,record)
    seed(session, record, 180, 150, 440)
    before = original(record)
    h.dispatch('focus', window='address:'+control)
    start(session, record)
    state = wait(lambda: (value := page_state(address, title)) and value['width'] == before[2][0]
                 and value['height'] <= before[2][1] and value, 'Desktop preview client viewport did not settle')
    inset_x = max(0, (before[2][0]-state['width'])/2)
    inset_y = max(0, before[2][1]-state['height'])
    clicks = state['clicks']
    source_point(session, record, inset_x+state['ordinary'][0], inset_y+state['ordinary'][1])
    wait(lambda: page_state(address, title)['clicks'] == clicks+1, 'Desktop fullscreen policy broke ordinary mouse-only input')
    time.sleep(.65)
    assert active(record), 'Desktop fullscreen policy promoted an ordinary browser control click'
    assert_source(record, before)
    state = page_state(address, title)
    source_point(session, record, inset_x+state['button'][0], inset_y+state['button'][1])
    wait(lambda: h.client(address)['workspace']['id'] == session.workspace and modes(address) == (2, 2),
         'Explicit Desktop fullscreen did not restore the full application normally', timeout=12)
    wait(stopped, 'Desktop fullscreen fallback retained miniature input')
    try:
        wait(lambda: page_state(address, title)['fullscreen'], 'Desktop fullscreen lost the actual video Fullscreen API state')
    except AssertionError:
        print('Desktop video fullscreen diagnostics:', page_state(address, title), modes(address),
              'saved:', (record['fullscreen'], record['fullscreenClient']), 'native:', interaction(), flush=True)
        raise
    assert not any(value['id'] == record['id'] for value in command('list')['windows'])
    monitor_records(witness);observer.check()
    h.dispatch('window.fullscreen_state', window='address:'+address, internal=0, client=0, action='set')
    h.dispatch('window.close', window='address:'+address)
    wait(lambda: not h.client(address), 'Owned browser did not close')
    print('PASS '+executable+' Desktop fullscreen restores a real fullscreen video while ordinary mouse-only controls remain contained', flush=True)


@desktop_test('Isolated contained fullscreen and picture-in-picture acceptance')
def main(apps, gtk_enabled=True, pointer_only=True, desktop_only=False, original_maximized=False):
    require_isolated()
    assert DEFAULTS['floatingPreviewFullscreen'] == 'preview'
    PreviewBridge(h).ensure()
    manager = BridgeManager(h)
    expected = manager.build(manager.commit())
    assert manager.native().get('fingerprint') == expected['fingerprint'], \
        'The loaded development module does not match the current native source; refresh the owned test module first'
    binding = install_fullscreen_binding()
    matching = h.call('repl', 'return hl.get_config("input.resolve_binds_by_sym")')
    try:
        with tempfile.TemporaryDirectory(prefix='stash-contained-fullscreen-') as temporary, NativeSession() as session:
            for key, value in dict(presentation='previews', scope='global', grouping='window', restoreDestination='original',
                                   floatingPreviewInteraction='on', floatingPreviewActivation='explicit',
                                   floatingPreviewKeyboard='click', floatingPreviewFullscreen='preview',
                                   floatingPreviewInteractionFps='60', floatingPreviewControls='always',
                                   floatingPreviewUpdate='live', livePreviewCompatibility='enhanced', hoverPreview='off',
                                   floatingPreviewSizing='free', floatingPreviewTitles='hidden', floatingPreviewFrame='hidden',
                                   floatingPreviewLock='unlocked', floatingPlacement='free', dragMotion='direct', animations='off').items():
                configure(key, value)
            h.eval('hl.config({input={resolve_binds_by_sym=true}})')
            directory = Path(temporary)
            witness_address = spawn_fixture(session, directory/'witness.jsonl')
            witness = park(session, witness_address)
            seed(session, witness, 850, 150, 280)
            observer = Events()
            try:
                if gtk_enabled:
                    gtk(session, directory, witness, observer)
                for executable in apps:
                    assert shutil.which(executable), 'Requested browser is not installed: '+executable
                    browser(session, directory, executable, witness, observer, pointer_only, desktop_only, original_maximized)
            except BaseException:
                print('Fullscreen failure diagnostics:', {'interaction':interaction(),
                      'clients':[(value['address'], value['class'], value['workspace'], value['size'], value.get('fullscreen'), value.get('fullscreenClient'))
                                 for value in h.read('clients')]}, flush=True)
                if os.environ.get('WINDOW_STASH_FULLSCREEN_TRACE') == '1':
                    for path in directory.glob('*.stderr'):
                        trace = [line for line in path.read_text(errors='replace').splitlines()
                                 if any(value in line for value in ('HandleToplevelConfigure', 'wayland_window.cc', 'states=[', 'xdg_activation', 'set_fullscreen', 'unset_fullscreen', 'set_maximized', 'unset_maximized', '.configure(', '.button(', '.key('))]
                        print('Owned browser protocol trace:', path.name, '\n'.join(trace[-80:]), flush=True)
                raise
            finally:
                stop()
                observer.close()
    finally:
        if binding:
            disable_binding(binding)
        h.eval('hl.config({input={resolve_binds_by_sym='+matching+'}})')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apps', nargs='*', choices=('chromium', 'brave'), default=['chromium'])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--gtk-only', action='store_true', help='Only exercise actual GTK fullscreen and lifecycle cases')
    mode.add_argument('--skip-gtk', action='store_true')
    mode.add_argument('--desktop-only', action='store_true', help='Only exercise the optional Desktop fullscreen handoff')
    parser.add_argument('--original-maximized', action='store_true', help='Start Desktop-only browsers maximized before stashing')
    parser.add_argument('--keyboard-click', action='store_true', help='Test browser fullscreen with keyboard permission enabled from the start')
    arguments = parser.parse_args()
    if arguments.original_maximized and not arguments.desktop_only:
        parser.error('--original-maximized requires --desktop-only')
    main([] if arguments.gtk_only else arguments.apps, not (arguments.skip_gtk or arguments.desktop_only), not arguments.keyboard_click, arguments.desktop_only, arguments.original_maximized)
