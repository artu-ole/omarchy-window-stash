#!/usr/bin/env python3
"""Preserving native tests for resizable floating preview cards.

Install the checkout in an unlocked Hyprland session first. All clients, output
profiles, preferences and saved card geometry created here belong to the test.
--small-output exercises pagination and settings on a disposable 320x240 output;
--enhanced also checks the optional native rendering lease lifecycle.
"""
import argparse
import json
import struct
import time

from desktop_test import desktop_test
from hover_previews import assert_pixels, change_color, current_focus, spawn_color
from live import command, configure, h, shell, wait
from native_session import NativeSession
from settings_fit import choice, dropdown
from stash import SPECIAL, monitor_identity


def previews(session):
    return session.surface()['floatingPreviews']


def key(record):
    return 'preview:window:'+str(record.get('stableId') or record['id'])


def preview_owner(session):
    identity = monitor_identity(session.monitor)
    return identity if any(part.strip() for part in identity.split('|')) else 'output:'+session.monitor['name']


def touch(session, record):
    touched = session.touched.setdefault(preview_owner(session), set())
    touched.add(key(record))
    touched.add('preview:app:'+record['app'].lower())


def park(session, address):
    drain()
    result = command('minimize', '--address', address)
    if not result.get('id'):
        status = shell('status')
        client = h.client(address)
        raise AssertionError(('Owned fixture was not stashed', {
            'result': result, 'address': address,
            'client': {field: client.get(field) for field in ('workspace', 'pid', 'stableId', 'tags')} if client else None,
            'ledger': [{field: item.get(field) for field in ('id', 'address', 'phase', 'lastError')}
                       for item in command('list')['windows'] if item['address'] == address],
            'controllerBusy': status['controllerBusy'], 'queueLength': status['queueLength'], 'error': status['error']}))
    ident = result['id']
    record = wait(lambda: next((item for item in command('list')['windows'] if item['id'] == ident), None),
                  'Owned preview fixture did not reach the stash ledger')
    wait(lambda: ident in shell('status')['windowIds'], 'Owned preview fixture did not reach the UI snapshot')
    session.touch('window:'+str(record.get('stableId') or ident))
    session.touch('app:'+record['app'].lower())
    session.touch('dock:floating')
    touch(session, record)
    return record


def card(session, record=None):
    return next((item for item in previews(session)['cards']
                 if record is None or item['recordId'] == record['id']), None)


def ready(session, record=None, content=True):
    return wait(lambda: (value := card(session, record)) and not value['held']
                and not value['resizing'] and (not content or value['image']['hasContent']) and value,
                'Floating preview card did not become ready')


def bounded(session, item):
    area = session.surface()['usableArea']
    assert item['width'] > 0 and item['height'] > 0, ('Empty preview card', item)
    assert item['x'] >= area['x']-.6 and item['y'] >= area['y']-.6, ('Card crossed reserved origin', item, area)
    assert item['x']+item['width'] <= area['x']+area['width']+.6, ('Card crossed right bound', item, area)
    assert item['y']+item['height'] <= area['y']+area['height']+.6, ('Card crossed bottom bound', item, area)


def ids():
    return {record['id'] for record in command('list')['windows']}


def drain():
    def idle():
        value = shell('status')
        return not value['controllerBusy'] and not value['queueLength']
    wait(idle, 'Preview geometry/action queue did not drain')


def seed(session, record, x=110, y=150, width=280):
    touch(session, record)
    drain()
    command('preview-position', preview_owner(session), key(record), x, y, width)
    shell('refresh')
    return wait(lambda: (value := card(session, record)) and abs(value['x']-x) < 1
                and abs(value['y']-y) < 1 and abs(value['width']-width) < 1 and value,
                'Saved floating preview geometry did not load')


def drag(session, rect, dx, dy, during=None):
    x, y = rect['x']+rect['width']/2, rect['y']+rect['height']/2
    area = session.surface()
    def move(px, py):
        session.move(max(0, min(area['width']-1, px)), max(0, min(area['height']-1, py)))
    move(x-1, y)
    move(x, y)
    time.sleep(.07)
    session.pointer.button(True)
    time.sleep(.05)
    try:
        for step in range(1, 11):
            move(x+dx*step/10, y+dy*step/10)
            time.sleep(.02)
            if step == 5 and during:
                during()
    finally:
        session.pointer.button(False)


def pixel_value(item):
    return dict(image=item['image'], imageRect=item['imageRect'], rect=item['rect'])


def color(session, record, expected, timeout=3):
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        value = card(session, record)
        if value and value['image']['hasContent']:
            try:
                assert_pixels(session, pixel_value(value), expected)
                return value
            except AssertionError:
                pass
        time.sleep(.04)
    raise AssertionError(('Floating preview never displayed '+expected, card(session, record)))


def away(session):
    area = session.surface()['usableArea']
    for x, y in ((area['x']+2, area['y']+2), (area['x']+area['width']-2, area['y']+2),
                 (area['x']+2, area['y']+area['height']-2)):
        if not any(item['x'] <= x <= item['x']+item['width'] and item['y'] <= y <= item['y']+item['height']
                   for item in previews(session)['cards']+previews(session)['tiles']):
            session.move(x, y)
            return
    raise AssertionError('No empty point was available outside the preview cards')


def settings_controls(session):
    shell('settings')
    wait(lambda: session.surface()['dialog']['visible'], 'Floating preview settings did not open')
    assert choice(session, 'sizePreset')['visible'], 'Folded icon size is unreachable in preview mode'
    assert choice(session, 'iconFrame')['visible'], 'Folded icon border/background is unreachable in preview mode'
    assert not choice(session, 'floatingPreviewScale')['visible'], 'Free resize exposes a competing scale dropdown'
    assert choice(session, 'floatingPreviewSizing')['visible'], 'Preview sizing selector is unreachable'
    dropdown(session, 'floatingPreviewSizing', 'preset')
    wait(lambda: choice(session, 'floatingPreviewScale')['visible'], 'Preset sizing did not expose scale choices')
    dropdown(session, 'floatingPreviewScale', '150')
    dropdown(session, 'floatingPreviewSizing', 'free')
    assert not choice(session, 'floatingPreviewScale')['visible'], 'Returning to free resize retained the scale dropdown'
    for name in ('floatingPreviewUpdate', 'floatingPreviewTitles', 'floatingPreviewFrame', 'floatingPreviewLock'):
        assert choice(session, name)['visible'], 'Floating preview setting is hidden: '+name
        dropdown(session, name)
    shell('dismiss')
    wait(lambda: not session.surface()['dialog']['rendered'], 'Settings did not dismiss')
    print('PASS native sizing controls hide irrelevant scale fields and all floating-preview options are reachable', flush=True)


def geometry_and_resize(session, record):
    before_ids = ids()
    source = h.client(record['address'])
    original_geometry = (source['at'], source['size'])
    initial = seed(session, record)
    assert not initial['titleVisible'] and not initial['frameVisible'], 'Default card adds permanent chrome'
    ratio = record['size'][0]/record['size'][1]
    image = initial['imageRect']
    assert abs(image['width']/image['height']-ratio) < .015, ('Preview distorts source aspect', initial, record['size'])

    def resizing():
        assert card(session, record)['resizing'], 'Corner gesture did not acquire resizing'
    drag(session, initial['resizeRect'], 90, 60, resizing)
    resized = ready(session, record)
    assert resized['width'] > initial['width']+35, ('Corner drag did not resize the miniature', initial, resized)
    assert abs(resized['imageRect']['width']/resized['imageRect']['height']-ratio) < .015, 'Direct resize changed source aspect ratio'
    assert ids() == before_ids, 'Resizing a thumbnail restored/closed a client'
    assert (h.client(record['address'])['at'], h.client(record['address'])['size']) == original_geometry, 'Card resize mutated the real window'
    bounded(session, resized)
    drain()
    saved = command('list')['positions'][preview_owner(session)][key(record)]
    assert len(saved) == 3 and abs(saved[2]-resized['width']) < 1, 'Direct width was not persisted separately from icon positions'
    configure('presentation', 'bubbles')
    configure('presentation', 'previews')
    retained = ready(session, record)
    assert all(abs(retained[name]-resized[name]) < 1 for name in ('x', 'y', 'width')), 'Changing modes lost card geometry'

    configure('floatingPreviewSizing', 'preset')
    widths = []
    for scale in ('50', '75', '100', '125', '150', '175', '200', '250', '300'):
        configure('floatingPreviewScale', scale)
        area = session.surface()['usableArea']
        expected = min(280*int(scale)/100, area['width'], area['height']*ratio)
        value = wait(lambda: (item := card(session, record)) and abs(item['width']-expected) < 1 and item,
                     'Thumbnail did not apply its scale preset: '+scale)
        bounded(session, value)
        assert not value['resizable'], 'Preset sizing retained active direct-resize handles'
        widths.append(value['width'])
    assert all(a < b for a, b in zip(widths, widths[1:])), ('Scale presets did not grow the thumbnail', widths)
    configure('floatingPreviewScale', '150')
    preset = wait(lambda: (item := card(session, record)) and abs(item['width']-420) < 1 and item,
                  'Preset drag fixture did not apply 150 percent scale')
    drag(session, preset['imageRect'], 40, 15)
    wait(lambda: card(session, record)['x'] > preset['x']+15, 'Preset-mode card did not remain draggable')
    drain()
    saved = command('list')['positions'][preview_owner(session)][key(record)]
    assert abs(saved[2]-resized['width']) < 1, 'Dragging a preset-sized card destroyed the remembered free-resize width'
    configure('floatingPreviewSizing', 'free')
    retained = wait(lambda: (item := card(session, record)) and abs(item['width']-resized['width']) < 1 and item,
                    'Preset sizing overwrote the remembered free-resize width')
    assert abs(retained['width']-resized['width']) < 1, 'Preset sizing overwrote the remembered free-resize width'

    configure('floatingPreviewLock', 'locked')
    locked = ready(session, record)
    drag(session, locked['imageRect'], 80, 35)
    drain()
    after = ready(session, record)
    assert all(abs(after[name]-locked[name]) < 1 for name in ('x', 'y', 'width')), 'Locked card moved or resized'
    assert ids() == before_ids, 'Dragging a locked card accidentally restored a window'
    configure('floatingPreviewLock', 'unlocked')
    drag(session, after['imageRect'], 65, 25)
    moved = ready(session, record)
    assert moved['x'] > after['x']+30 and moved['y'] > after['y']+10, 'Unlocked card did not follow pointer movement'
    assert abs(moved['width']-after['width']) < 1 and ids() == before_ids, 'Moving resized/activated the miniature'
    bounded(session, moved)
    print('PASS borderless aspect-correct cards, direct corner resize, source geometry, saved dimensions, placement lock and movement', flush=True)


def visibility_and_stability(session, first, second, previous):
    current = ready(session, first)
    assert all(abs(current[name]-previous[name]) < 1 for name in ('x', 'y', 'width')), \
        'Adding another stashed window moved the existing card'
    configure('scope', 'workspace')
    h.dispatch('focus', workspace=str(session.workspace+1))
    wait(lambda: session.surface()['workspaceId'] == session.workspace+1 and not previews(session)['present'],
         'Workspace scope left another workspace\'s cards/captures visible')
    assert all(h.client(item['address'])['workspace']['name'] == SPECIAL for item in (first, second)), 'Workspace filtering restored a hidden client'
    configure('scope', 'global')
    wait(lambda: len(previews(session)['cards']) == 2, 'Global scope did not reveal the shared stash on another workspace')
    configure('scope', 'workspace')
    wait(lambda: not previews(session)['present'], 'Returning to workspace scope retained global cards')
    h.dispatch('focus', workspace=str(session.workspace))
    wait(lambda: len(previews(session)['cards']) == 2, 'Returning to the original workspace lost its cards')
    print('PASS new-card placement remains stable and workspace/global visibility filters without restoring clients', flush=True)


def update_policies(session, record, enhanced):
    configure('floatingPreviewUpdate', 'still')
    configure('livePreviewCompatibility', 'enhanced' if enhanced else 'standard')
    seed(session, record)
    away(session)
    color(session, record, 'red')
    focus = current_focus()
    geometry = (h.client(record['address'])['at'], h.client(record['address'])['size'])
    assert not card(session, record)['image']['live'], 'Snapshot card kept continuous capture active'
    change_color(session, record['address'])  # red -> green
    time.sleep(.2)
    color(session, record, 'red', timeout=.4)
    configure('floatingPreviewUpdate', 'hover')
    value = ready(session, record)
    session.move(value['x']+value['width']/2, value['y']+value['height']/2)
    wait(lambda: card(session, record)['image']['live'], 'Live-on-hover did not start for the card')
    color(session, record, 'green')
    if enhanced:
        wait(lambda: record['id'] in shell('status')['previewCompatibility']['requestedIds'],
             'A hovered card did not acquire Enhanced support with hoverPreview disabled')
    away(session)
    wait(lambda: not card(session, record)['image']['live'], 'Leaving a card retained its live stream')
    if enhanced:
        wait(lambda: not shell('status')['previewCompatibility']['requestedIds'], 'Leaving the last live card retained Enhanced leases')
    configure('floatingPreviewUpdate', 'live')
    wait(lambda: card(session, record)['image']['live'], 'Always-live depends on pointer hover')
    change_color(session, record['address'])  # green -> blue
    color(session, record, 'blue')
    assert current_focus() == focus, 'Persistent preview updates changed focus/workspace'
    assert (h.client(record['address'])['at'], h.client(record['address'])['size']) == geometry, 'Live rendering moved/resized the real client'
    assert h.client(record['address'])['workspace']['name'] == SPECIAL, 'Live rendering restored a parked client'
    configure('presentation', 'dock')
    wait(lambda: not previews(session)['present'] and not shell('status')['previewCompatibility']['requestedIds'],
         'Leaving floating previews retained captures or rendering leases')
    configure('presentation', 'previews')
    configure('floatingPreviewUpdate', 'still')
    ready(session, record)
    assert shell('status')['settings']['hoverPreview'] == 'off', 'Card live updating changed ordinary hover previews'
    print('PASS Snapshot/Live-on-hover/Always-live pixels, independent hover settings, unchanged focus/geometry and capture lease release', flush=True)


def actions(session, first, second):
    configure('grouping', 'app')
    group = wait(lambda: (value := card(session)) and value['groupCount'] == 2 and value,
                 'Two app windows did not form one preview card')
    def expand():
        session.click(ready(session)['imageRect'])
        wait(lambda: previews(session)['expanded'] and len(previews(session)['tiles']) == 2,
             'Grouped preview did not expand all windows together')
    expand()
    session.keys('-k', 'Escape')
    wait(lambda: not previews(session)['expanded'], 'Escape did not collapse grouped floating previews')
    expand()
    away(session)
    session.pointer.button(True)
    time.sleep(.05)
    session.pointer.button(False)
    wait(lambda: not previews(session)['expanded'], 'Outside click did not collapse grouped floating previews')
    expand()
    h.dispatch('focus', workspace=str(session.workspace+1))
    wait(lambda: not previews(session)['expanded'], 'Workspace switch retained expanded group previews')
    h.dispatch('focus', workspace=str(session.workspace))
    ready(session)
    assert not previews(session)['expanded'], 'Returning to the workspace reopened its dismissed group'
    configure('scope', 'global')
    h.dispatch('focus', workspace=str(session.workspace+1))
    wait(lambda: session.surface()['workspaceId'] == session.workspace+1, 'Current-restore invocation workspace did not reach the UI')
    expand()
    wait(lambda: all(tile['image']['hasContent'] for tile in previews(session)['tiles']),
         'Expanded app group did not capture both visible windows')
    tiles = previews(session)['tiles']
    assert {tile['recordId'] for tile in tiles} == {first['id'], second['id']}, 'Group expansion replaced windows with a carousel'
    assert all(tile['image']['captureActive'] for tile in tiles), 'Expanded visible group did not capture both windows'
    for tile in tiles:
        bounded(session, tile['rect'])
    configure('restoreDestination', 'current')
    selected = next(tile for tile in tiles if tile['recordId'] == second['id'])
    session.click(selected['imageRect'])
    wait(lambda: h.client(second['address'])['workspace']['id'] == session.workspace+1, 'Expanded thumbnail did not restore to the invoking workspace')
    # The move precedes geometry/tag/ledger cleanup inside one queued restore.
    # External fixture mutations must wait for that transaction to finish.
    drain()
    wait(lambda: second['id'] not in ids() and second['id'] not in shell('status')['windowIds'],
         'Expanded thumbnail restore did not finish ledger/UI cleanup')
    assert h.client(second['address'])['floating'] and h.client(second['address'])['size'] == second['size'], 'Miniature sizing changed restored floating geometry'
    assert h.client(first['address'])['workspace']['name'] == SPECIAL, 'Selecting one group thumbnail restored its neighbor'
    h.dispatch('window.move', window='address:'+second['address'], workspace=str(session.workspace), follow=False)
    second = park(session, second['address'])
    assert not previews(session)['expanded'], 'Restashing a restored group member reopened a dismissed expansion'
    configure('grouping', 'window')
    configure('scope', 'global')
    h.dispatch('focus', workspace=str(session.workspace+1))
    wait(lambda: session.surface()['workspaceId'] == session.workspace+1, 'Restore destination workspace did not reach the UI')
    value = ready(session, first)
    session.click(value['imageRect'], 273)
    wait(lambda: session.menu()['opened'], 'Preview context menu did not open at the pointer')
    assert session.menu()['targetIds'] == [first['id']], 'Preview context menu targeted another client'
    session.click(session.action('original')['rect'])
    wait(lambda: h.client(first['address'])['workspace']['id'] == session.workspace, 'Original-workspace preview action ignored the saved origin')
    drain()
    wait(lambda: first['id'] not in ids() and first['id'] not in shell('status')['windowIds'],
         'Original-workspace restore did not finish ledger/UI cleanup')
    assert h.client(first['address'])['floating'] and h.client(first['address'])['size'] == first['size'], 'Original restoration used thumbnail dimensions for the real window'
    h.dispatch('focus', workspace=str(session.workspace))
    first = park(session, first['address'])
    configure('scope', 'workspace')
    configure('grouping', 'app')
    expand()
    selected = next(tile for tile in previews(session)['tiles'] if tile['recordId'] == second['id'])
    session.click(selected['imageRect'], 274)
    wait(lambda: not h.client(second['address']) and not previews(session)['expanded'], 'Middle-click did not close the represented group tile')
    drain()
    replacement = park(session, spawn_color(session, 'green'))
    ready(session, replacement)
    assert not previews(session)['expanded'], 'A 2→1 group retained an expansion that reopened on the next stashed instance'
    configure('grouping', 'window')
    second = replacement
    value = ready(session, second)
    session.click(value['imageRect'], 274)
    wait(lambda: not h.client(second['address']), 'Middle-click did not wait for represented window closure')
    drain()
    assert h.client(first['address']) and h.client(first['address'])['workspace']['name'] == SPECIAL, 'Middle-close escaped its represented window'
    configure('floatingPreviewTitles', 'shown')
    configure('floatingPreviewFrame', 'shown')
    value = ready(session, first)
    assert value['titleVisible'] and value['frameVisible'], 'Optional title/frame did not appear'
    assert value['closeRect']['width'] > 0, 'Titled preview has no close button'
    session.click(value['closeRect'])
    wait(lambda: not h.client(first['address']), 'Preview title close button did not close its own window')
    drain()
    print('PASS grouped simultaneous previews, exact-window restoration, current/original destinations, context targeting, middle close and optional title close', flush=True)


def group_overflow(session, records):
    configure('grouping', 'app')
    group = wait(lambda: (value := card(session)) and value['groupCount'] == len(records) and value,
                 'Small-output fixtures did not form one app group')
    session.click(group['imageRect'])
    wait(lambda: previews(session)['expanded'] and previews(session)['groupOverflow']['enabled'],
         'Small-output app group did not expose its bounded scrolling grid')
    seen = set()
    direction = 1
    for step in range(40):
        value = previews(session)
        seen.update(tile['recordId'] for tile in value['tiles'])
        if {record['id'] for record in records} <= seen:
            break
        viewport = value['viewportRect']
        session.move(viewport['x']+viewport['width']/2, viewport['y']+viewport['height']/2)
        pointer = session.pointer
        pointer.send(5, 5, pointer.uint(0))
        pointer.send(5, 7, pointer.uint(int(time.monotonic()*1000) & 0xffffffff)
                     + pointer.uint(0) + struct.pack('ii', direction*120*256, direction*8))
        pointer.send(5, 4)
        pointer.sync()
        time.sleep(.06)
        if step == 2 and previews(session)['groupOverflow']['contentY'] <= .1:
            direction = -1
    assert {record['id'] for record in records} <= seen, 'Scrolling the grouped grid never exposed every window'
    assert all(h.client(record['address'])['workspace']['name'] == SPECIAL for record in records), 'Scrolling a group restored a window'
    session.keys('-k', 'Escape')
    wait(lambda: not previews(session)['expanded'], 'Escape did not close the scrolled app group')
    print('PASS small-output app groups keep all windows in a scrollable grid with no carousel or accidental restoration', flush=True)


def dpms_capture(session, records, enhanced, diagnostics=False):
    drain()
    name = session.monitor['name']
    assert name in session.outputs, 'Refusing DPMS changes on an output not owned by this test'
    baseline = {monitor['name']: monitor.get('dpmsStatus') for monitor in h.read('monitors')}
    geometry_fields = ('at', 'size', 'workspace', 'floating', 'monitor', 'pid', 'stableId', 'tags')
    restoration_fields = ('size', 'relativePosition', 'floating', 'origin', 'monitor', 'monitorName', 'slot',
                          'pinned', 'fullscreen', 'fullscreenClient')
    wanted = {record['id'] for record in records}
    history = []
    def snapshot(label):
        clients = {record['id']: {field: client.get(field) for field in geometry_fields} if (client := h.client(record['address'])) else None
                   for record in records}
        ledger = {record['id']: {field: record.get(field) for field in restoration_fields}
                  for record in command('list')['windows'] if record['id'] in wanted}
        value = dict(phase=label, clients=clients, restoration=ledger,
                     monitors=[{field: monitor.get(field) for field in ('name', 'id', 'x', 'y', 'width', 'height', 'scale', 'dpmsStatus', 'activeWorkspace', 'specialWorkspace')}
                               for monitor in h.read('monitors')],
                     visibility=shell('status')['captureVisibility'],
                     compatibility=shell('status')['previewCompatibility'])
        history.append(value)
        if diagnostics:
            print('DPMS diagnostic '+json.dumps(value, sort_keys=True), flush=True)
        return value
    before = snapshot('before-live')
    configure('floatingPreviewUpdate', 'live')
    value = ready(session)
    wait(lambda: card(session)['image']['live'], 'DPMS fixture did not start live capture')
    if enhanced:
        wait(lambda: value['recordId'] in shell('status')['previewCompatibility']['requestedIds'], 'DPMS fixture did not acquire its rendering lease')
    snapshot('live-before-dpms')
    def allowed():
        return next((item['allowed'] for item in shell('status')['captureVisibility']['screens'] if item['name'] == name), None)
    try:
        h.dispatch('dpms', monitor=name, action='off')
        wait(lambda: next(m for m in h.read('monitors') if m['name'] == name)['dpmsStatus'] is False,
             'The owned output did not enter DPMS sleep')
        wait(lambda: allowed() is False and not previews(session)['cards'], 'Sleeping output retained visible capture cards')
        wait(lambda: not wanted.intersection(shell('status')['previewCompatibility']['requestedIds']),
             'Sleeping output retained its Enhanced rendering leases')
        snapshot('dpms-off')
        assert all(m.get('dpmsStatus') == baseline[m['name']] for m in h.read('monitors') if m['name'] != name), 'Targeted DPMS changed another output'
    finally:
        h.dispatch('dpms', monitor=name, action='on')
        wait(lambda: next(m for m in h.read('monitors') if m['name'] == name)['dpmsStatus'] is True,
             'The owned output did not resume after DPMS sleep')
    wait(lambda: allowed() is True, 'Resumed output did not regain capture permission')
    value = ready(session)
    if enhanced:
        wait(lambda: value['recordId'] in shell('status')['previewCompatibility']['requestedIds'], 'Resumed card did not reacquire its rendering lease')
    after = snapshot('resumed-live')
    assert after['restoration'] == before['restoration'], ('DPMS changed saved restoration metadata',
                                                          {'expected': before['restoration'], 'actual': after['restoration'], 'history': history})
    for record in records:
        expected, actual = before['clients'][record['id']], after['clients'][record['id']]
        assert actual and actual['workspace']['name'] == SPECIAL and (actual['at'], actual['size']) == (expected['at'], expected['size']), \
            ('DPMS capture suspension changed a real stashed window',
             {'id': record['id'], 'expected': expected, 'actual': actual, 'history': history})
    configure('floatingPreviewUpdate', 'still')
    wait(lambda: not wanted.intersection(shell('status')['previewCompatibility']['requestedIds']), 'Snapshot policy retained resumed live leases')
    print('PASS targeted disposable-output DPMS releases/resumes captures and Enhanced leases without changing source geometry or other outputs', flush=True)


def small_output(session, enhanced):
    names = {monitor['name'] for monitor in h.read('monitors')}
    h.call('output', 'create', 'headless')
    monitor = wait(lambda: next((m for m in h.read('monitors') if m['name'] not in names), None), 'Temporary preview output did not appear')
    session.outputs.append(monitor['name'])
    right = max(m['x']+round(m['width']/m['scale']) for m in h.read('monitors') if m['name'] != monitor['name'])
    h.eval('hl.monitor({output=%s,mode="320x240@60",position=%s,scale=1})' % (json.dumps(monitor['name']), json.dumps('%dx0' % right)))
    session.monitor = wait(lambda: next((m for m in h.read('monitors') if m['name'] == monitor['name'] and m['width'] == 320
                            and m['height'] == 240 and m['scale'] == 1), None), 'Temporary preview mode did not apply')
    session.move(160, 120)
    h.dispatch('focus', monitor=monitor['name'])
    wait(lambda: next(item for item in h.read('monitors') if item['name'] == monitor['name'])['focused'],
         'Temporary preview output did not receive monitor focus')
    h.dispatch('focus', workspace=str(session.workspace+3))
    try:
        wait(lambda: session.surface()['workspaceId'] == session.workspace+3
             and session.surface()['usableArea']['width'] == 320,
             'Temporary preview surface did not settle on the reserved workspace and output dimensions')
    except AssertionError:
        print('Small-output setup diagnostics:', {'wantedWorkspace': session.workspace+3,
              'activeWorkspace': h.read('activeworkspace'), 'monitors': h.read('monitors'),
              'surfaces': [{name: value.get(name) for name in ('screen', 'workspaceId', 'workspaceState', 'width', 'height', 'usableArea', 'groups')}
                           for value in shell('status')['surfaces']]}, flush=True)
        raise
    configure('floatingPreviewTitles', 'hidden')
    configure('floatingPreviewFrame', 'hidden')
    configure('floatingPreviewSizing', 'preset')
    configure('floatingPreviewScale', '300')
    configure('floatingPlacement', 'edges')
    records = [park(session, spawn_color(session, value, app='org.windowstash.FloatingSmall', workspace=session.workspace+3))
               for value in ('red', 'green', 'blue')]
    assert all(record['origin']['id'] == session.workspace+3 and record['monitorName'] == monitor['name']
               for record in records), 'Overflow fixtures were not stashed from their owned output/workspace'
    try:
        wait(lambda: previews(session)['overflow']['enabled'], 'Small output did not expose bounded overflow navigation')
    except AssertionError:
        status = shell('status')
        surface = next((item for item in status['surfaces'] if item['screen'] == session.monitor['name']), None)
        print('Small-output overflow diagnostics:', {
            'settings': status['settings'], 'wantedWorkspace': session.workspace+3,
            'activeWorkspace': h.read('activeworkspace'),
            'surface': {field: surface.get(field) for field in ('screen', 'workspaceId', 'groups', 'eligible', 'width', 'height', 'usableArea', 'floatingPreviews')} if surface else None,
            'records': [{field: record.get(field) for field in ('id', 'origin', 'monitorName', 'floating', 'size')}
                        | {'client': {field: client.get(field) for field in ('workspace', 'at', 'size', 'floating', 'monitor', 'pid', 'stableId')} if (client := h.client(record['address'])) else None}
                        for record in records],
            'monitors': h.read('monitors'), 'workspaces': h.read('workspaces')}, flush=True)
        raise
    seen = set()
    pages = previews(session)['overflow']['pages']
    assert pages > 1, 'Overflow silently discarded card records'
    for _ in range(pages):
        value = previews(session)
        for item in value['cards']:
            bounded(session, item)
            seen.add(item['recordId'])
        overflow = value['overflow']
        if overflow['page']+1 < overflow['pages']:
            page = overflow['page']
            session.click(overflow['nextRect'])
            wait(lambda: previews(session)['overflow']['page'] == page+1, 'Small-output Next did not expose the next card page')
    assert {record['id'] for record in records} <= seen, 'An overflowed card is unreachable'
    shell('settings')
    wait(lambda: session.surface()['dialog']['visible'], 'Small-output floating settings did not open')
    assert session.surface()['settingsScroll']['contentHeight'] > session.surface()['settingsScroll']['rect']['height'], 'Small-output settings did not scroll'
    for name in ('floatingPreviewSizing', 'floatingPreviewScale', 'floatingPreviewUpdate', 'floatingPreviewTitles', 'floatingPreviewFrame', 'floatingPreviewLock'):
        assert choice(session, name)['visible'], 'A floating preview option is missing on a small output: '+name
        dropdown(session, name)
    shell('dismiss')
    print('PASS 320x240 oversized cards remain bounded, overflow exposes every window, and all settings remain reachable', flush=True)
    group_overflow(session, records)
    dpms_capture(session, records, enhanced)


@desktop_test('Resizable floating preview integration test')
def main(with_small_output=False, enhanced=False, small_output_only=False):
    assert not command('list')['windows'], 'Run floating preview acceptance in an isolated desktop with an empty stash'
    with NativeSession() as session:
        for name, value in dict(presentation='previews', scope='workspace', grouping='window', animations='off',
                                floatingPlacement='free', dragMotion='direct', hoverPreview='off', iconOpacity=100,
                                floatingPreviewSizing='free', floatingPreviewScale='100', floatingPreviewUpdate='still',
                                floatingPreviewTitles='hidden', floatingPreviewFrame='hidden', floatingPreviewLock='unlocked',
                                livePreviewCompatibility='standard').items():
            configure(name, value)
        if not small_output_only:
            first = park(session, spawn_color(session, 'red'))
            session.spawn(app='org.windowstash.FloatingInput', workspace=session.workspace)
            ready(session, first)
            assert len(previews(session)['cards']) == 1 and not session.surface()['preview']['opened'], 'Fourth presentation did not show a persistent thumbnail card'
            settings_controls(session)
            geometry_and_resize(session, first)
            update_policies(session, first, enhanced)
            previous = ready(session, first)
            second = park(session, spawn_color(session, 'green'))
            ready(session, second)
            visibility_and_stability(session, first, second, previous)
            actions(session, first, second)
        elif enhanced:
            configure('livePreviewCompatibility', 'enhanced')
        if with_small_output or small_output_only:
            small_output(session, enhanced)
        drain()
        assert not shell('status')['error'], shell('status')['error']
    drain()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--small-output', action='store_true')
    parser.add_argument('--small-output-only', action='store_true', help='Run only small-output overflow, settings, grouped grid and DPMS checks')
    parser.add_argument('--enhanced', action='store_true')
    options = parser.parse_args()
    main(options.small_output, options.enhanced, options.small_output_only)
