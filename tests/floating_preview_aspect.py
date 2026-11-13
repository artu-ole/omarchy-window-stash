#!/usr/bin/env python3
"""Actual side resizing, client reflow and restoration in a disposable desktop.

Four edges change content proportions; corners retain the selected proportions.
The responsive GTK fixture and captured circle distinguish real reflow from
stretching an old buffer. --restart-shell also checks a new shell instance;
--apps chromium brave adds actual video picture-in-picture coverage. All input
is restricted to an explicitly isolated compositor. Profiles and pixels use /tmp.
"""
import argparse
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time

from desktop_test import desktop_test
from floating_previews import away, bounded, card, drain, drag, key, park, preview_owner, previews, seed
from floating_preview_layouts import active_layout, ledger
from interactive_apps import page_state, spawn as spawn_app
from interactive_bridge import events
from interactive_fullscreen import browser_page, modes, pixel_colors
from interactive_handoff import Events, monitor_records
from interactive_previews import active, show_controls, source_click, stopped
from live import ROOT, command, configure, h, shell, wait
from bridge import BridgeManager
from native_session import NativeSession
from preview import PreviewBridge
from stash import SPECIAL


def require_isolated():
    assert os.environ.get('WINDOW_STASH_ISOLATED_TEST') == '1' and (Path.home()/'.window-stash-isolated').is_file(), \
        'Refusing aspect input tests outside an explicitly disposable desktop'
    assert not command('list')['windows'], 'Use an empty disposable stash'


def spawn(session, log, workspace=None, app='org.windowstash.AspectFixture'):
    wanted = session.workspace if workspace is None else workspace
    h.dispatch('focus', workspace=str(wanted))
    title = 'Stash aspect '+str(os.getpid())+' '+str(len(session.addresses))
    with log.with_suffix('.stderr').open('w') as errors:
        process = subprocess.Popen(['/usr/bin/python3', str(ROOT/'tests/preview-aspect-window.py'), title, str(log), app],
                                   env=dict(os.environ, GDK_BACKEND='wayland'),
                                   stdout=subprocess.DEVNULL, stderr=errors)
    session.processes.append(process)
    client = wait(lambda: next((value for value in h.read('clients') if value['title'] == title), None),
                  'Responsive fixture did not open')
    address = client['address']
    session.addresses.append(address)
    wait(lambda: events(log, 'allocation'), 'Responsive fixture did not paint')
    h.dispatch('window.float', window='address:'+address, action='on')
    h.dispatch('window.resize', window='address:'+address, x=800, y=600, relative=False)
    h.dispatch('window.move', window='address:'+address,
               x=session.monitor['x']+120, y=session.monitor['y']+110, relative=False)
    wait(lambda: h.client(address)['size'] == [800, 600]
         and (values := events(log, 'allocation')) and [values[-1]['width'], values[-1]['height']] == [800, 600],
         'Responsive fixture did not commit its original allocation')
    return address


def source_geometry(record):
    value = h.client(record['address'])
    assert value, 'The responsive source disappeared'
    return value['workspace'], value['at'], value['size'], value['floating']


def private(session, record, saved, observer, witness=None):
    value = h.client(record['address'])
    assert value and value['workspace']['name'] == SPECIAL and value['floating'], \
        ('Aspect resizing restored or retiled the source', value)
    assert value['pid'] == record['pid'] and value['stableId'] == record['stableId'] and record['tag'] in value['tags'], \
        'Aspect resizing changed the exact parked identity'
    assert ledger(record) == saved, ('Aspect resizing rewrote original restoration metadata', saved, ledger(record))
    assert h.read('activeworkspace')['id'] == session.surface()['workspaceId'] == record['origin']['id'] > 0, \
        'Aspect resizing switched the visible workspace'
    observer.check()
    if witness:
        monitor_records(witness)


def shaped(session, record, timeout=12):
    """Wait for an acknowledged source and a newly captured matching buffer."""
    def matches():
        value = card(session, record)
        if not value or value['held'] or value['resizing'] or not value.get('geometryReady') or not value['image']['hasContent']:
            return None
        state = command('preview-geometry', record['id'])
        source = value['image']['sourceSize']
        if not state['ready'] or state['nativeRequired'] or min(source['width'], source['height']) <= 1:
            return None
        actual = state['size'][0]/state['size'][1]
        image = value['imageRect']
        if abs(source['width']/source['height']-actual) > max(.004, actual*.004):
            return None
        if abs(image['width']/image['height']-actual) > max(.008, actual*.008):
            return None
        return value
    try:
        value = wait(matches, 'Aspect resize did not reach a committed, freshly captured geometry', timeout=timeout)
    except AssertionError:
        print('Aspect readiness diagnostics:', {'card': card(session, record),
              'native': command('preview-geometry', record['id']),
              'geometryStates': shell('status').get('previewGeometry'),
              'layout': {name: previews(session).get(name) for name in ('page', 'pages', 'pageCount', 'count')},
              'visibleIds': [item['recordId'] for item in previews(session)['cards']],
              'source': source_geometry(record)}, flush=True)
        raise
    bounded(session, value)
    return value


def handle(value, edge):
    result = next((item for item in value['resizeRects'] if item['corner'] == edge), None)
    assert result and result['enabled'], ('The requested resize handle is unavailable', edge, value['resizeRects'])
    return result['rect']


def side(session, record, edge, dx, dy):
    before = shaped(session, record)
    def during():
        current = card(session, record)
        assert current['resizing'] and not current['geometryReady'], ('Side drag did not own geometry readiness', current)
        assert not current['interaction'].get('interactEnabled', False), 'Interact remained enabled during a side drag'
    drag(session, handle(before, edge), dx, dy, during)
    result = shaped(session, record)
    drain()
    assert abs(result['aspectOverride']-before['imageRect']['width']/before['imageRect']['height']) > .025, \
        ('Side drag did not change content proportions', edge, before['rect'], result['rect'])
    unchanged = ('y', 'height') if edge in ('left', 'right') else ('x', 'width')
    assert all(abs(result[name]-before[name]) <= 2 for name in unchanged), \
        ('An edge changed the orthogonal card dimension', edge, before['rect'], result['rect'])
    if edge in ('left', 'top'):
        origin, length = ('x', 'width') if edge == 'left' else ('y', 'height')
        assert abs(result[origin]+result[length]-before[origin]-before[length]) <= 2, \
            ('An edge moved its opposite anchor', edge, before['rect'], result['rect'])
    else:
        assert abs(result['x']-before['x']) <= 2 and abs(result['y']-before['y']) <= 2, \
            ('An edge moved its fixed origin', edge, before['rect'], result['rect'])
    return result


def allocation(log, record):
    size = h.client(record['address'])['size']
    value = wait(lambda: (values := events(log, 'allocation'))
                 and abs(values[-1]['width']-size[0]) <= 1 and abs(values[-1]['height']-size[1]) <= 1 and values[-1],
                 'Actual GTK content did not reflow to the new source allocation')
    assert value['wide'] == (size[0] >= size[1]), 'Responsive orientation does not match the source'
    return value


def circle(session, record):
    away(session)
    value = shaped(session, record)
    image = value['imageRect']
    x, y = math.ceil(image['x']), math.ceil(image['y'])
    width, height = max(1, math.floor(image['width']-1)), max(1, math.floor(image['height']-1))
    geometry = '%d,%d %dx%d' % (session.monitor['x']+x, session.monitor['y']+y, width, height)
    time.sleep(.1)
    raw = subprocess.check_output(['grim', '-s', '1', '-t', 'ppm', '-g', geometry, '-'],
                                  stderr=subprocess.DEVNULL, timeout=5)
    magic, dimensions, maximum, pixels = raw.split(b'\n', 3)
    assert magic == b'P6' and maximum == b'255'
    width, height = map(int, dimensions.split())
    points = [(index//3 % width, index//3 // width) for index in range(0, len(pixels), 3)
              if min(pixels[index:index+3]) > 230
              and width*.15 < index//3 % width < width*.85
              and height*.15 < index//3 // width < height*.85]
    assert len(points) > 100, 'Captured client pixels do not contain the fixture circle'
    spans = [max(point[axis] for point in points)-min(point[axis] for point in points)+1 for axis in (0, 1)]
    assert min(spans) > 30 and abs(spans[0]-spans[1]) <= 3, \
        ('The preview stretched a real circle instead of reflowing the client', spans, image)
    return spans


def start(session, record):
    shaped(session, record)
    value = show_controls(session, record)
    assert value['geometryReady'], 'Interact was offered before a fresh resized buffer'
    session.click(value['interaction']['interactRect'])
    wait(lambda: active(record), 'Resized preview did not start native interaction', timeout=12)


def stop():
    shell('dismiss')
    wait(stopped, 'Preview interaction did not stop', timeout=6)


def pause_captures(session):
    stop()
    configure('presentation', 'dock')
    wait(lambda: not previews(session)['present'], 'Aspect cleanup retained visible preview captures')
    drain()
    wait(lambda: not any(item.get('image', {}).get('captureActive') for surface in shell('status')['surfaces']
                         for item in surface['floatingPreviews']['cards']) and BridgeManager(h).native().get('owners') == 0,
         'Owned aspect captures did not stop before fixture termination')


def shell_ready():
    # Quickshell briefly returns human-readable discovery messages with status0
    # while its IPC target is registering. They are not plugin JSON replies.
    result = subprocess.run(['omarchy-shell', 'window-stash', 'status'], capture_output=True, text=True, timeout=3)
    try:
        value = json.loads(result.stdout) if result.returncode == 0 else None
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) and value.get('lifecycle', {}).get('ready') else None


def floating(session, directory, witness, observer, proof_only=False):
    log = directory/'responsive.jsonl'
    address = spawn(session, log)
    original = source_geometry({'address': address})
    record = park(session, address)
    saved = ledger(record)
    seed(session, record, 210, 170, 360)
    shaped(session, record)
    assert len(command('list')['positions'][preview_owner(session)][key(record)]) == 3, 'A natural preview requires custom aspect metadata'
    edges = (('right', 80, 0), ('bottom', 0, 60)) if proof_only else (('right', 80, 0), ('left', -45, 0), ('bottom', 0, 60), ('top', 0, 35))
    for edge, dx, dy in edges:
        side(session, record, edge, dx, dy)
        allocation(log, record)
        circle(session, record)
        private(session, record, saved, observer, witness)
    if proof_only:
        print('PASS physical right/bottom drags in Standard/Still reflow actual GTK allocations and preserve round pixels/private restoration metadata', flush=True)
        return record, saved, original, log
    value = shaped(session, record)
    ratio = value['aspectOverride']
    state = source_geometry(record)
    for corner, dx, dy in (('bottom-right', 45, 25), ('top-left', -30, -20)):
        before = shaped(session, record)
        drag(session, handle(before, corner), dx, dy)
        after = shaped(session, record)
        assert abs(after['aspectOverride']-ratio) < .0001, 'Corner resizing overwrote the custom content ratio'
        assert abs(after['width']-before['width']) > 15, 'Corner resize did not change miniature scale'
        assert source_geometry(record) == state, 'Proportional corner resizing needlessly resized the real client'
        private(session, record, saved, observer, witness)
    print('PASS all four physical edge drags reflow committed GTK buffers; opposite anchors stay fixed, circles stay round and corners preserve custom proportions', flush=True)
    return record, saved, original, log


def persistence(session, record, saved, observer, witness, restart_shell, directory):
    before = shaped(session, record)
    custom = command('list')['positions'][preview_owner(session)][key(record)]
    assert len(custom) == 4 and abs(custom[3]-before['aspectOverride']) < .0001, ('The custom content ratio was not persisted', custom)
    for mode in ('dock', 'bubbles', 'previews'):
        configure('presentation', mode)
    for update in ('still', 'hover', 'live'):
        configure('floatingPreviewUpdate', update)
        value = shaped(session, record)
        assert abs(value['aspectOverride']-custom[3]) < .0001, 'Capture refresh snapped back to the original aspect'
    for setting, option in (('floatingPreviewLock', 'locked'), ('floatingPreviewSizing', 'preset')):
        configure(setting, option)
        value = shaped(session, record)
        assert not value['resizable'] and not any(item['enabled'] for item in value['resizeRects']), 'Lock/preset retained an edge handle'
        configure(setting, 'unlocked' if setting == 'floatingPreviewLock' else 'free')
        shaped(session, record)
    configure('floatingPreviewTitles', 'shown')
    configure('floatingPreviewFrame', 'shown')
    before_chrome = shaped(session, record)
    value = side(session, record, 'right', 50, 0)
    assert value['titleVisible'] and value['frameVisible'], 'Chrome fixture is missing title/frame'
    assert abs(value['height']-before_chrome['height']) <= 2, 'Horizontal resize included title height in its content aspect'
    circle(session, record)
    configure('floatingPreviewTitles', 'hidden')
    configure('floatingPreviewFrame', 'hidden')
    retained = shaped(session, record)
    if restart_shell:
        # Only private namespace processes can match this path. A replacement
        # must remain running for NativeSession to restore preferences later.
        config = Path(os.environ['OMARCHY_PATH'])/'shell'
        assert config.is_absolute() and (config/'shell.qml').is_file()
        with (directory/'restarted-shell.log').open('w') as output:
            subprocess.run(['quickshell', 'kill', '-p', str(config), '--any-display'], check=True, timeout=20,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.Popen(['qs', '-p', str(config/'shell.qml')], stdout=output, stderr=output)
        wait(shell_ready, 'Replacement private shell did not become ready', timeout=25)
        retained_after = shaped(session, record)
        assert all(abs(retained_after[name]-retained[name]) <= 1 for name in ('x', 'y', 'width', 'height', 'aspectOverride')), \
            ('A shell restart lost custom preview shape', retained['rect'], retained_after['rect'])
    private(session, record, saved, observer, witness)
    print('PASS custom proportions persist across presentation/capture policy changes, chrome, locks and presets'+(' and a new shell process' if restart_shell else ''), flush=True)


def delayed_commit(session, record, saved, log, observer, witness):
    process = next((value for value in session.processes if value.pid == record['pid'] and value.poll() is None), None)
    assert process, 'Refusing to suspend a source without its exact owned process'
    before = shaped(session, record)
    previous_size = h.client(record['address'])['size']
    process.send_signal(signal.SIGSTOP)
    try:
        drag(session, handle(before, 'right'), 55, 0)
        pending = wait(lambda: (value := card(session, record)) and not value['resizing']
                       and not value['geometryReady'] and value, 'Uncommitted client was incorrectly marked ready', timeout=3)
        assert not pending['interaction']['interactEnabled'], 'Interact accepted a configure without a committed source frame'
        wait(lambda: h.client(record['address'])['size'] != previous_size,
             'The coalesced source resize never reached the compositor', timeout=5)
        native = command('preview-geometry', record['id'])
        assert not native['ready'], ('Native readiness accepted an unacknowledged client resize', native)
        private(session, record, saved, observer, witness)
    finally:
        process.send_signal(signal.SIGCONT)
    shaped(session, record)
    allocation(log, record)
    circle(session, record)
    print('PASS an unresponsive owned client keeps native/UI input disabled until its real configure, draw and fresh capture complete', flush=True)


def input_and_fullscreen(session, record, saved, original, log, witness, observer):
    start(session, record)
    assert not card(session, record)['resizable'], 'Active input allowed source resizing'
    for x, y in ((.25, .7), (.8, .3)):
        count = len(events(log, 'press'))
        source_click(session, record, x, y)
        event = wait(lambda: len(values := events(log, 'press')) > count and values[-1], 'Resized content did not receive its mapped click')
        size = h.client(record['address'])['size']
        assert abs(event['x']-size[0]*x) <= 5 and abs(event['y']-size[1]*y) <= 5, \
            ('Resized miniature input used stale dimensions', event, size, x, y)
    session.keys('-k', 'F11')
    wait(lambda: modes(record['address']) == (0, 2), 'GTK fullscreen escaped the preview')
    wait(lambda: (values := events(log, 'fullscreen')) and values[-1]['active'], 'GTK did not receive a real fullscreen configure')
    stop()
    side(session, record, 'bottom', 0, 45)
    allocation(log, record)
    circle(session, record)
    assert modes(record['address']) == (0, 2) and events(log, 'fullscreen')[-1]['active'], \
        'Side reflow collapsed passive picture-in-picture fullscreen'
    private(session, record, saved, observer, witness)
    start(session, record)
    source_click(session, record)
    session.keys('-k', 'Escape')
    wait(lambda: modes(record['address']) == (0, 0), 'Application Escape did not exit resized contained fullscreen')
    stop()
    # Pause capture before closing/restoring owned buffers to avoid the
    # compositor's documented export-frame close race in fixture cleanup.
    custom = command('list')['positions'][preview_owner(session)][key(record)]
    pause_captures(session)
    command('restore', record['id'], '--to', 'original')
    wait(lambda: source_geometry(record) == original, 'Floating restore used the temporary preview source size or position')
    assert record['id'] not in {value['id'] for value in command('list')['windows']}, 'Exact floating restore retained its record'
    observer.check()
    configure('presentation', 'previews')
    print('PASS fresh resized input coordinates, application fullscreen retained through side reflow, and exact original floating geometry on restore', flush=True)
    return custom


def restash(session, previous, original, log, custom, witness, observer):
    record = park(session, previous['address'])
    saved = ledger(record)
    assert record['id'] != previous['id'] and record['stableId'] == previous['stableId'] and key(record) == key(previous), \
        'Re-stashing did not create a fresh record for the same stable preview key'
    assert record['size'] == original[2] and record['floating'], 'Re-stash saved temporary source geometry instead of the restored original'
    value = shaped(session, record)
    assert value['aspectOverride'] > 0 and abs(value['aspectOverride']-custom[3]) <= max(.001, custom[3]*.003), \
        ('Re-stash lost its saved custom proportions', value['aspectOverride'], custom)
    size = h.client(record['address'])['size']
    assert abs(size[0]/size[1]-custom[3]) <= max(.005, custom[3]*.005), \
        ('A new UUID displayed saved shape without reflowing its exact source', size, custom)
    allocation(log, record)
    circle(session, record)
    private(session, record, saved, observer, witness)
    start(session, record)
    count = len(events(log, 'press'))
    source_click(session, record, .75, .65)
    event = wait(lambda: len(values := events(log, 'press')) > count and values[-1], 'Re-stashed source did not accept fresh input')
    assert abs(event['x']-size[0]*.75) <= 5 and abs(event['y']-size[1]*.65) <= 5, ('Re-stash used stale input geometry', event, size)
    stop()
    private(session, record, saved, observer, witness)
    pause_captures(session)
    command('restore', record['id'], '--to', 'original')
    wait(lambda: source_geometry(record) == original, 'Re-stashed source lost exact original floating restoration geometry')
    configure('presentation', 'previews')
    print('PASS the same stable window re-stashes with a new UUID, reapplies saved custom source proportions, captures a fresh frame and maps input before exact restore', flush=True)


def reset_and_group(session, record, saved, directory, witness, observer):
    value = shaped(session, record)
    assert value['aspectOverride'] > 0, 'Reset fixture lacks custom proportions'
    session.click(value['imageRect'], 273)
    wait(lambda: session.menu()['opened'], 'Aspect context menu did not open')
    action = session.action('reset-preview-proportions')
    assert action['enabled'], 'Custom preview proportions cannot be reset'
    session.click(action['rect'])
    wait(lambda: not session.menu()['opened'], 'Reset action did not close its context menu')
    reset = shaped(session, record)
    persisted = command('list')['positions'][preview_owner(session)][key(record)]
    assert reset['aspectOverride'] == 0 and len(persisted) == 3, \
        ('Reset retained a custom proportion override', reset['aspectOverride'], persisted)
    assert abs(reset['imageRect']['width']/reset['imageRect']['height']-record['size'][0]/record['size'][1]) <= .01, \
        'Reset did not return the source to its natural content aspect'
    private(session, record, saved, observer, witness)
    side(session, record, 'bottom', 0, 45)

    sibling_log = directory/'group-lead.jsonl'
    sibling = park(session, spawn(session, sibling_log))
    sibling_saved = ledger(sibling)
    untouched = source_geometry(record)
    configure('grouping', 'app')
    group = wait(lambda: (item := card(session, sibling)) and item['groupCount'] == 2 and item,
                 'Owned sources did not form an app preview cover')
    assert group['recordId'] == sibling['id'], 'The newest grouped source is not the displayed cover'
    drain()
    command('preview-position', preview_owner(session), group['key'], 220, 170, 320)
    shell('refresh')
    wait(lambda: (item := card(session, sibling)) and abs(item['x']-220) < 1 and abs(item['y']-170) < 1,
         'Grouped cover did not load its centered interior fixture position')
    side(session, sibling, 'right', 60, 0)
    allocation(sibling_log, sibling)
    circle(session, sibling)
    assert source_geometry(record) == untouched, 'Grouped cover resizing changed a nondisplayed source'
    private(session, record, saved, observer, witness)
    private(session, sibling, sibling_saved, observer, witness)
    configure('grouping', 'window')
    shaped(session, record)
    # An additional free-positioned card may land on the next bounded page.
    # Its exact source/ledger were already verified while it was the cover.
    private(session, sibling, sibling_saved, observer, witness)
    print('PASS context reset restores natural proportions; grouped cover side dragging reflows only its exact displayed source', flush=True)


def proof_input(session, record, saved, original, log, witness, observer):
    start(session, record)
    before = len(events(log, 'press'))
    source_click(session, record, .8, .7)
    event = wait(lambda: len(values := events(log, 'press')) > before and values[-1], 'Freshly reflowed GTK source did not receive input')
    size = h.client(record['address'])['size']
    assert abs(event['x']-size[0]*.8) <= 5 and abs(event['y']-size[1]*.7) <= 5, ('Reflowed input used stale source geometry', event, size)
    stop()
    private(session, record, saved, observer, witness)
    pause_captures(session)
    command('restore', record['id'], '--to', 'original')
    wait(lambda: source_geometry(record) == original, 'Proof restore lost original floating geometry')
    print('PASS committed resized Still source starts fresh mapped input and restores exact original floating geometry', flush=True)


def scrolling(session, directory, witness, observer):
    workspace = session.workspace+2
    name = '__window_stash_aspect_scrolling_'+str(os.getpid())
    h.eval('_G.'+name+'=hl.workspace_rule({workspace='+json.dumps(str(workspace))+',layout="scrolling",layout_opts={direction="right"}})')
    try:
        h.dispatch('focus', workspace=str(workspace))
        active_layout(session, workspace, 'scrolling')
        addresses = []
        for index in range(3):
            address = spawn(session, directory/('scrolling-'+str(index)+'.jsonl'), workspace,
                            app='org.windowstash.AspectScrolling')
            h.dispatch('window.float', window='address:'+address, action='off')
            wait(lambda: not h.client(address)['floating'], 'Scrolling fixture did not tile')
            addresses.append(address)
        address = addresses[0]
        for fraction in (.31, .78):
            h.dispatch('focus', window='address:'+address)
            h.eval('hl.dispatch(hl.dsp.layout('+json.dumps('colresize '+str(fraction))+'))')
            width = h.client(address)['size'][0]
            record = park(session, address)
            saved = ledger(record)
            seed(session, record, 220, 180, 320)
            shaped(session, record)
            side(session, record, 'right', 80, 0)
            private(session, record, saved, observer, witness)
            assert not saved['floating'] and saved['size'][0] == width
            pause_captures(session)
            command('restore', record['id'], '--to', 'original')
            restored = wait(lambda: (value := h.client(address)) and value['workspace']['id'] == workspace and not value['floating'] and value,
                            'Aspect-resized scrolling source did not restore tiled')
            assert abs(restored['size'][0]-width) <= 1, ('Scrolling restore used preview width instead of original column pixels', width, restored['size'])
            h.eval('local w=hl.get_window('+json.dumps('address:'+address)+');for _,other in pairs(hl.get_workspace_windows(w.workspace)) do '
                   'if other.address~=w.address and not other.floating then assert(w.layout.column.index>other.layout.column.index,"Restored source is not last scrolling column") end end')
            configure('presentation', 'previews')
        print('PASS actual narrow/wide scrolling columns preserve original pixel widths and append correctly after source aspect reflow', flush=True)
    finally:
        h.eval('if _G.'+name+' then _G.'+name+':set_enabled(false);_G.'+name+'=nil end')
        h.dispatch('focus', workspace=str(session.workspace))


def browser(session, directory, executable, witness, observer):
    assert shutil.which(executable), 'Requested browser is unavailable: '+executable
    title = 'Stash aspect video '+executable+' '+str(os.getpid())
    page = directory/(executable+'-aspect.html')
    browser_page(page, title)
    text = page.read_text()
    needle = 'width:innerWidth,height:innerHeight,'
    assert text.count(needle) == 1, 'Browser fixture viewport publication changed'
    page.write_text(text.replace(needle, needle+'dpr:devicePixelRatio,outerWidth:outerWidth,outerHeight:outerHeight,'))
    address = spawn_app(session, [executable, '--user-data-dir='+str(directory/(executable+'-profile')),
                        '--no-first-run', '--no-default-browser-check', '--disable-background-networking',
                        '--disable-component-update', '--disable-sync', '--password-store=basic',
                        '--disable-features=MediaRouter', '--ozone-platform=wayland', '--no-sandbox',
                        '--app='+page.as_uri(), '--class=org.windowstash.AspectBrowser'],
                        title, directory/(executable+'.stderr'))
    h.dispatch('window.move', window='address:'+address, x=session.monitor['x']+200, y=session.monitor['y']+160, relative=False)
    wait(lambda: (value := page_state(address, title)) and value['ready'] >= 2, 'Browser fixture video did not start')
    original = source_geometry({'address': address})
    record = park(session, address)
    saved = ledger(record)
    seed(session, record, 210, 170, 440)
    start(session, record)
    state = page_state(address, title)
    size = h.client(address)['size']
    inset_x, inset_y = max(0, (size[0]-state['width'])/2), max(0, size[1]-state['height'])
    source_click(session, record, (state['button'][0]+inset_x)/size[0], (state['button'][1]+inset_y)/size[1])
    baseline = wait(lambda: (value := page_state(address, title)) and value['fullscreen'] and value['element'] == 'VIDEO' and value,
                    'Browser did not enter real video Fullscreen API mode')
    wait(lambda: modes(address) == (0, 2), 'Video fullscreen escaped the preview')
    source_before = h.client(address)['size']
    scales = [source_before[0]/baseline['outerWidth'], source_before[1]/baseline['outerHeight']]
    insets = [source_before[index]-baseline[name]*scales[index] for index, name in enumerate(('width', 'height'))]
    stop()
    for edge, dx, dy in (('right', 90, 0), ('bottom', 0, 90)):
        side(session, record, edge, dx, dy)
        private(session, record, saved, observer, witness)
        size = h.client(address)['size']
        try:
            state = wait(lambda: (value := page_state(address, title)) and value['fullscreen']
                         and abs(value['width']*scales[0]+insets[0]-size[0]) <= 2
                         and abs(value['height']*scales[1]+insets[1]-size[1]) <= 2 and value,
                         'Fullscreen browser viewport did not reflow to the source geometry')
        except AssertionError:
            print('Browser aspect diagnostics:', {'app': executable, 'edge': edge, 'source': source_geometry(record),
                  'modes': modes(address), 'page': page_state(address, title), 'before': baseline,
                  'sourceBefore': source_before, 'scales': scales, 'insets': insets,
                  'native': command('preview-geometry', record['id']), 'card': card(session, record)}, flush=True)
            raise
        assert modes(address) == (0, 2) and state['element'] == 'VIDEO', 'Resizing lost passive video fullscreen'
        assert state['dpr'] == baseline['dpr'], 'Browser CSS scale changed during source reflow'
        assert all(abs(actual-expected) <= 2 for actual, expected in zip(state['video'], (0, 0, state['width'], state['height']))), \
            ('Actual fullscreen video did not fill the reflowed website viewport', state)
        colors = pixel_colors(session, record)
        assert colors[0] > .35 and colors[1] < .01, ('Resized video exposed website UI', executable, colors)
        before = state['time']
        wait(lambda: page_state(address, title)['time'] > before+.2, 'Video stopped updating after aspect reflow')
    pause_captures(session)
    command('restore', record['id'], '--to', 'original')
    wait(lambda: source_geometry(record) == original and modes(address) == (0, 0), 'Browser restore lost original floating geometry')
    configure('presentation', 'previews')
    print('PASS '+executable+' actual video fullscreen survives horizontal/vertical reflow, keeps live playback and restores original geometry; '
          +'viewport '+str([baseline['width'], baseline['height']])+' → '+str([state['width'], state['height']])
          +', logical insets '+str(insets)+', DPR '+str(state['dpr']), flush=True)


@desktop_test('Isolated floating-preview aspect resizing acceptance')
def main(restart_shell=False, apps=(), proof_only=False, browser_only=False):
    require_isolated()
    PreviewBridge(h).ensure()
    manager = BridgeManager(h)
    assert manager.native().get('fingerprint') == manager.build(manager.commit())['fingerprint'], \
        'Refresh the owned native test module before running this checkout'
    with tempfile.TemporaryDirectory(prefix='stash-aspect-') as temporary, NativeSession() as session:
        directory = Path(temporary)
        observer = None
        try:
            for setting, value in dict(presentation='previews', scope='global', grouping='window', restoreDestination='original',
                                   floatingPreviewInteraction='on', floatingPreviewActivation='explicit', floatingPreviewKeyboard='click',
                                   floatingPreviewFullscreen='preview', floatingPreviewInteractionFps='60', floatingPreviewControls='hover',
                                   floatingPreviewUpdate='live', livePreviewCompatibility='enhanced', hoverPreview='off',
                                   floatingPreviewSizing='free', floatingPreviewTitles='hidden', floatingPreviewFrame='hidden',
                                   floatingPreviewLock='unlocked', floatingPlacement='free', dragMotion='direct', animations='off',
                                       iconOpacity=100).items():
                configure(setting, value)
            if proof_only:
                configure('floatingPreviewUpdate', 'still')
                configure('livePreviewCompatibility', 'standard')
            witness = park(session, spawn(session, directory/'witness.jsonl', app='org.windowstash.AspectWitness'))
            seed(session, witness, 1250, 170, 220)
            observer = Events()
            if not browser_only:
                record, saved, original, log = floating(session, directory, witness, observer, proof_only)
                if proof_only:
                    proof_input(session, record, saved, original, log, witness, observer)
                    return
                delayed_commit(session, record, saved, log, observer, witness)
                persistence(session, record, saved, observer, witness, restart_shell, directory)
                reset_and_group(session, record, saved, directory, witness, observer)
                custom = input_and_fullscreen(session, record, saved, original, log, witness, observer)
                restash(session, record, original, log, custom, witness, observer)
                scrolling(session, directory, witness, observer)
            for executable in apps:
                browser(session, directory, executable, witness, observer)
            drain()
            assert not shell('status')['error'], shell('status')['error']
        finally:
            pause_captures(session)
            if observer:
                observer.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--restart-shell', action='store_true', help='Also replace the isolated shell process to check persisted aspect')
    parser.add_argument('--proof-only', action='store_true', help='Only check right/bottom edges and fresh input under Standard/Still capture')
    parser.add_argument('--apps', nargs='*', choices=('chromium', 'brave'), default=[])
    parser.add_argument('--browser-only', action='store_true', help='Only exercise the browsers selected by --apps')
    options = parser.parse_args()
    if options.browser_only and (not options.apps or options.proof_only):
        parser.error('--browser-only requires --apps and cannot be combined with --proof-only')
    main(options.restart_shell, options.apps, options.proof_only, options.browser_only)
