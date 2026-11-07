#!/usr/bin/env python3
"""Native edge-constrained static dock dragging and position persistence.

Install this checkout in an unlocked Hyprland session first. Disposable windows,
preferences, positions and focus are restored by NativeSession. --small-output
adds an owned 320x240 logical output to exercise overflow and reserved space.
"""
import argparse
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import time

from desktop_test import desktop_test
from live import command, configure, h, shell, wait
from native_session import NativeSession
from stash import monitor_identity


SIDES = ('top', 'bottom', 'left', 'right')


def shelf(session):
    return session.surface()['shelf']


def settled(session, side=None):
    def ready():
        surface = session.surface()
        value = surface['shelf']
        return value if value['width'] > 0 and value['height'] > 0 and not value['animating'] \
            and not value['held'] and not value['dragging'] and not surface['motion']['shelfBusy'] \
            and (side is None or value['side'] == side) else None
    return wait(ready, 'Static dock did not settle on '+str(side))


def bounded(session, value=None):
    value = value or settled(session)
    area = session.surface()['usableArea']
    assert value['x'] >= area['x']-.5 and value['y'] >= area['y']-.5, ('Dock crossed reserved origin', value, area)
    assert value['x']+value['width'] <= area['x']+area['width']+.5, ('Dock crossed right bound', value, area)
    assert value['y']+value['height'] <= area['y']+area['height']+.5, ('Dock crossed bottom bound', value, area)
    assert value['positionKey'] == 'dock:static:'+value['side'], 'Dock saved under another edge key'
    assert type(value['position']) is int and 0 <= value['position'] <= 10000, value
    return value


def ids():
    return {window['id'] for window in command('list')['windows']}


def monitor_key(session):
    identity = monitor_identity(session.monitor)
    return 'output:'+session.monitor['name'] if identity == '|||' else identity


def touch_static(session, side):
    session.touched.setdefault(monitor_key(session), set()).add('dock:static:'+side)


def saved(session, side):
    return command('list')['positions'].get(monitor_key(session), {}).get('dock:static:'+side)


def persisted(session, side, position=None):
    position = settled(session, side)['position'] if position is None else position
    wait(lambda: saved(session, side) == [position, 0], 'Normalized '+side+' dock position was not saved')
    return position


def seed(session, side, position):
    key = 'dock:static:'+side
    touch_static(session, side)
    configure('dockSide', side)
    wait(lambda: not shell('status')['controllerBusy'] and not shell('status')['queueLength'],
         'Controller did not drain before setting a fixture dock position')
    command('position', monitor_key(session), key, position, 0)
    shell('refresh')
    wait(lambda: shelf(session)['side'] == side and shelf(session)['position'] == position,
         'Saved static dock position was not applied')
    bounded(session, settled(session, side))


def select_lock(session, value):
    from settings_fit import reveal

    shell('settings')
    wait(lambda: session.surface()['dialog']['visible'], 'Static dock settings did not open')

    def control():
        return next(row for row in session.surface()['settingControls'] if row['key'] == 'staticDockLock')

    assert control()['visible'] and control()['section'] == 'placement', 'Static dock position selector is not in Placement'
    session.click(reveal(session, lambda: control()['rect']))
    wait(lambda: control()['open'], 'Static dock position dropdown did not open')
    area = session.surface()['usableArea']
    session.move(area['x']+1, area['y']+1)
    session.keys('-k', 'Up', '-k', 'Up', *(['-k', 'Down'] if value == 'unlocked' else []), '-k', 'Return')
    wait(lambda: shell('status')['settings']['staticDockLock'] == value,
         'Native static dock position selection did not save '+value)
    shell('dismiss')
    wait(lambda: not session.surface()['dialog']['rendered'], 'Static dock settings did not close')
    h.dispatch('focus', workspace=str(session.workspace))
    wait(lambda: shelf(session)['locked'] is (value == 'locked'), 'Dock did not apply the native lock setting')
    settled(session)


def background(value):
    # Use the middle of a long edge: it is outside every icon and outside the
    # large rounded end caps, including when the frame is transparent.
    if value['side'] in ('left', 'right'):
        x = value['x']+max(1, min(3, value['insets']['left']/2))
        y = value['y']+value['height']/2
    else:
        x = value['x']+value['width']/2
        y = value['y']+max(1, min(3, value['insets']['top']/2))
    assert not any(icon['x'] <= x < icon['x']+icon['width'] and icon['y'] <= y < icon['y']+icon['height']
                   for icon in value['icons']), 'The background fixture overlaps an icon'
    return dict(x=x-.5, y=y-.5, width=1, height=1)


def move_pointer(session, rect, dx, dy, during=None, button=272):
    x, y = rect['x']+rect['width']/2, rect['y']+rect['height']/2
    area = session.surface()
    def move(px, py):
        # The virtual-pointer protocol uses unsigned absolute coordinates.
        # Real cursors stop at the desktop boundary during outward gestures.
        session.move(max(0, min(area['width']-1, px)), max(0, min(area['height']-1, py)))
    move(x-1, y)
    move(x, y)
    # Let the mapped edge region and hover delivery settle before pressing,
    # as Pointer.click does after changing the physical cursor position.
    time.sleep(.06)
    session.pointer.button(True, button)
    # Match Pointer.click's press delivery interval before injecting motion;
    # thin gutters otherwise leave the region before Qt can acquire the grab.
    time.sleep(.05)
    try:
        for step in range(1, 13):
            move(x+dx*step/12, y+dy*step/12)
            time.sleep(.018)
            if step == 5 and during:
                during()
    finally:
        session.pointer.button(False, button)


def drag(session, target, along, cross, movable=True):
    before = bounded(session, settled(session))
    before_ids = ids()
    vertical = before['side'] in ('left', 'right')
    rect = background(before) if target == 'background' else before['icons'][0 if target == 'first' else -1]
    dx, dy = (cross, along) if vertical else (along, cross)

    def held():
        if movable and along:
            value = shelf(session)
            assert value['held'] and value['dragging'], ('Unlocked dock did not acquire an edge drag', target, value)

    move_pointer(session, rect, dx, dy, held)
    after = bounded(session, settled(session, before['side']))
    axis, orthogonal = ('y', 'x') if vertical else ('x', 'y')
    assert abs(after[orthogonal]-before[orthogonal]) <= .5, ('Dock left its configured edge', before, after)
    if movable and along:
        assert (after[axis]-before[axis])*along > 0 and abs(after[axis]-before[axis]) > 15, \
            ('Dock did not follow the along-edge component', target, before, after)
        assert after['position'] != before['position'], 'A completed drag did not update normalized placement'
        persisted(session, before['side'], after['position'])
    else:
        assert abs(after[axis]-before[axis]) <= .5 and after['position'] == before['position'], \
            ('Locked or orthogonal drag moved the dock', before, after)
    assert ids() == before_ids, 'Dragging restored or closed a stashed window'
    return after


def restore_click(session, records, locked):
    configure('staticDockLock', 'locked' if locked else 'unlocked')
    value = settled(session)
    record = records[-1]
    key = 'window:'+str(record.get('stableId') or record['id'])
    icon = next(icon for icon in value['icons'] if icon['key'] == key)
    before_ids = ids()
    session.click(icon)
    wait(lambda: record['id'] not in ids(), 'An ordinary icon click did not restore with locked='+str(locked))
    client = h.client(record['address'])
    assert client and client['workspace']['id'] == session.workspace, 'Icon click restored to another workspace'
    assert ids() == before_ids-{record['id']}, 'An ordinary click changed a neighboring stashed window'
    records[-1] = session.park(record['address'])
    settled(session)


def clamp_and_interrupt(session, position):
    configure('dockSide', 'bottom')
    configure('staticDockLock', 'unlocked')
    before_ids = ids()
    area = session.surface()['usableArea']
    for fraction, destination in ((10000, area['x']+area['width']-2), (0, area['x']+2)):
        rect = background(settled(session, 'bottom'))
        start_x = rect['x']+rect['width']/2
        move_pointer(session, rect, destination-start_x, -20)
        value = bounded(session, settled(session, 'bottom'))
        assert value['position'] == fraction, ('Dragging beyond available travel did not clamp at the edge', value, fraction)
        persisted(session, 'bottom', fraction)
        assert ids() == before_ids, 'A boundary drag activated an icon'

    for key, value, previous in (('staticDockLock', 'locked', 'unlocked'),
                                 ('dockSide', 'left', 'bottom'),
                                 ('presentation', 'bubbles', 'dock')):
        seed(session, 'bottom', 5000)
        rect = settled(session)['icons'][0]

        def interrupt():
            value_before = shelf(session)
            assert value_before['held'] and value_before['dragging'], 'Interruption fixture did not acquire an actual drag'
            configure(key, value)

        move_pointer(session, rect, 100, -30, interrupt)
        configure(key, previous)
        bounded(session, settled(session, 'bottom'))
        assert ids() == before_ids, 'Releasing after a '+key+' change restored or closed an icon'
    seed(session, 'bottom', position)
    print('PASS normalized end stops and safe release after lock, edge or presentation changes during an active drag', flush=True)


def restart(session, expected):
    subprocess.run(['omarchy', 'restart', 'shell'], check=True, timeout=100)

    def ready():
        result = subprocess.run(['omarchy-shell', 'window-stash', 'status'], capture_output=True, text=True)
        if result.returncode or not result.stdout.startswith('{'):
            return False
        value = json.loads(result.stdout)
        return value if value['settings']['staticDockLock'] == 'locked' \
            and session.monitor['name'] in value['screens'] and not value['error'] else None

    wait(ready, 'Static dock lock did not survive shell restart', timeout=20)
    h.dispatch('focus', workspace=str(session.workspace))
    for side, position in expected.items():
        configure('dockSide', side)
        value = bounded(session, settled(session, side))
        assert value['locked'] and value['position'] == position, ('Restart lost an edge position', side, value, position)
        assert saved(session, side) == [position, 0]


def wheel(session, steps):
    value = shelf(session)
    session.move(value['x']+value['width']/2, value['y']+value['height']/2)
    time.sleep(.05)
    pointer = session.pointer
    axis = 0 if value['side'] in ('left', 'right') else 1
    pointer.send(5, 5, pointer.uint(0))
    pointer.send(5, 7, pointer.uint(int(time.monotonic()*1000) & 0xffffffff)
                 + pointer.uint(axis) + struct.pack('ii', steps*15*256, steps))
    pointer.send(5, 4)
    pointer.sync()


def small_output(session):
    original_monitor, original_workspace = session.monitor, session.workspace
    original_key = monitor_key(session)
    original_positions = {key: value for key, value in command('list')['positions'].get(original_key, {}).items()
                          if key.startswith('dock:static:')}

    def original_unchanged():
        actual = {key: value for key, value in command('list')['positions'].get(original_key, {}).items()
                  if key.startswith('dock:static:')}
        assert actual == original_positions, 'Moving the second output dock changed the first output positions'

    before_outputs = {monitor['name'] for monitor in h.read('monitors')}
    h.call('output', 'create', 'headless')
    monitor = wait(lambda: next((m for m in h.read('monitors') if m['name'] not in before_outputs), None),
                   'Static drag overflow output did not appear')
    session.outputs.append(monitor['name'])
    end = max(m['x']+round(m['width']/m['scale']) for m in h.read('monitors') if m['name'] != monitor['name'])
    h.eval('hl.monitor({output='+json.dumps(monitor['name'])+',mode="400x300@60",position='
           +json.dumps(str(end)+'x0')+',scale=1.25})')
    session.monitor = next(m for m in h.read('monitors') if m['name'] == monitor['name'])
    assert monitor_key(session) != original_key, 'The static dock did not distinguish outputs without identifying metadata'
    session.workspace = original_workspace+2
    bar = None
    try:
        session.move(160, 120)
        h.dispatch('focus', monitor=session.monitor['name'])
        h.dispatch('focus', workspace=str(session.workspace))
        configure('scope', 'workspace')
        configure('sizePreset', '300')
        for _ in range(8):
            session.park(session.spawn(workspace=session.workspace)[0])
        wait(lambda: session.surface()['width'] == 320 and session.surface()['height'] == 240,
             'Mapped 1.25-scale static dock output did not settle')
        before_ids = ids()
        for lock in ('locked', 'unlocked'):
            configure('staticDockLock', lock)
            for side in SIDES:
                configure('dockSide', side)
                value = bounded(session, settled(session, side))
                axis = 'Y' if side in ('left', 'right') else 'X'
                content, viewport = ('contentHeight', 'viewportHeight') if axis == 'Y' else ('contentWidth', 'viewportWidth')
                assert value[content] > value[viewport]+20, ('Small output did not exercise overflow', value)
                start = value['content'+axis]
                wheel(session, 12)
                wait(lambda: shelf(session)['content'+axis] > start+10,
                     'Overflow wheel scrolling failed on '+side+' with '+lock)
                assert ids() == before_ids, 'Scrolling an overflowing dock restored or closed a window'
                assert not shelf(session)['held'] and not shelf(session)['dragging']
        print('PASS locked and unlocked overflow axis-wheel input on all four edges at 1.25 scale', flush=True)

        configure('sizePreset', '100')
        configure('grouping', 'app')
        wait(lambda: session.surface()['groups'] == 1, 'Grouped overflow fixtures did not leave room for an output-local drag')
        configure('staticDockLock', 'unlocked')
        seed(session, 'top', 2500)
        drag(session, 'background', 40, 20)
        original_unchanged()
        print('PASS dragging the second output dock leaves every saved first-output edge position unchanged', flush=True)
        seed(session, 'top', 7500)
        value = bounded(session, settled(session, 'top'))
        initial_y, reserved = value['y'], session.surface()['usableArea']['y']
        with tempfile.TemporaryDirectory(prefix='stash-static-drag-bar-') as directory:
            path = Path(directory)/'shell.qml'
            path.write_text('''import QtQuick
import Quickshell
ShellRoot {
  PanelWindow {
    screen: Quickshell.screens.find(s => s.name === Quickshell.env("STASH_STATIC_DRAG_SCREEN"))
    anchors { top:true; left:true; right:true }
    implicitHeight:40; exclusiveZone:40
    color:"#1a1b26"
    mask:Region {}
  }
}
''')
            bar = subprocess.Popen(['quickshell', '-p', str(path)],
                                   env=dict(os.environ, STASH_STATIC_DRAG_SCREEN=session.monitor['name']),
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            wait(lambda: session.surface()['usableArea']['y'] == reserved+40,
                 'Static dock did not observe the owned top reservation', timeout=10)
            moved = bounded(session, settled(session, 'top'))
            assert abs(moved['y']-initial_y-40) <= .5 and moved['position'] == 7500, moved
            assert saved(session, 'top') == [7500, 0], 'A bar reservation rewrote normalized placement'
            bar.terminate()
            bar.wait(timeout=5)
            bar = None
            wait(lambda: session.surface()['usableArea']['y'] == reserved, 'Static dock retained a removed bar reservation')
            assert abs(bounded(session, settled(session, 'top'))['y']-initial_y) <= .5
        original_unchanged()
        print('PASS small-output bounds and appearing/removing bar reservations preserve normalized placement', flush=True)
    finally:
        if bar is not None:
            bar.terminate()
            bar.wait(timeout=5)
        session.monitor, session.workspace = original_monitor, original_workspace
        h.dispatch('focus', monitor=original_monitor['name'])
        h.dispatch('focus', workspace=str(original_workspace))


@desktop_test('Static dock lock, edge dragging and persistence test')
def main(with_small_output=False):
    with NativeSession() as session:
        for key, value in dict(presentation='dock', scope='workspace', grouping='window', hoverPreview='off',
                               restoreDestination='current', dockSide='bottom', staticDockLock='locked',
                               animations='full', animationSpeed='normal', sizePreset='100',
                               dockFrame='shown', iconFrame='shown', iconShape='square',
                               dockCorners='custom', dockCornerRadius=12, dockOpacity=100, iconOpacity=100).items():
            configure(key, value)
        records = [session.park(session.spawn(workspace=session.workspace)[0]) for _ in range(3)]
        for side in SIDES:
            seed(session, side, 5000)
        select_lock(session, 'unlocked')
        positions = {}
        for side, amount in zip(SIDES, (180, -120, 140, -100)):
            configure('dockSide', side)
            cross = 65 if side in ('top', 'left') else -65
            value = drag(session, 'first', amount, cross)
            value = drag(session, 'last', -amount/3, 0)
            value = drag(session, 'background', amount/2, -cross/2)
            # A pure orthogonal gesture cannot turn a fixed edge into free placement.
            drag(session, 'background', 0, cross, movable=False)
            positions[side] = value['position']
        assert len(set(positions.values())) == 4, ('Fixture did not establish independent edge positions', positions)
        print('PASS every edge: first/last icon and background drag, one-axis constraint, no restore-on-drag, per-edge basis points', flush=True)
        clamp_and_interrupt(session, positions['bottom'])

        configure('dockSide', 'bottom')
        configure('dockFrame', 'hidden')
        configure('iconFrame', 'hidden')
        drag(session, 'first', 100, -65)
        value = drag(session, 'background', -65, 35)
        positions['bottom'] = value['position']
        print('PASS frameless icons and transparent dock gutter remain draggable without visible chrome', flush=True)

        select_lock(session, 'locked')
        drag(session, 'background', 170, -65, movable=False)
        drag(session, 'first', 170, -65, movable=False)
        assert saved(session, 'bottom') == [positions['bottom'], 0], 'Locking reset or rewrote the saved position'
        for side, position in positions.items():
            configure('dockSide', side)
            assert bounded(session, settled(session, side))['position'] == position
        print('PASS native relock refuses dock/icon movement and retains every edge position', flush=True)

        for preset in ('150', '250', '100'):
            configure('sizePreset', preset)
            for side, position in positions.items():
                configure('dockSide', side)
                value = bounded(session, settled(session, side))
                assert value['position'] == position and saved(session, side) == [position, 0]
        configure('scope', 'global')
        assert bounded(session)['position'] == positions[shelf(session)['side']]
        configure('scope', 'workspace')
        # Different workspaces show different icon sets while sharing one
        # monitor/edge placement, rather than storing per-workspace copies.
        address, _ = session.spawn(workspace=session.workspace+1)
        session.park(address)
        wait(lambda: session.surface()['workspaceId'] == session.workspace+1 and session.surface()['groups'] == 1,
             'Alternate workspace did not show its own stashed window')
        assert bounded(session)['position'] == positions[shelf(session)['side']]
        h.dispatch('focus', workspace=str(session.workspace))
        wait(lambda: session.surface()['workspaceId'] == session.workspace and session.surface()['groups'] == 3,
             'Original workspace did not regain its dock entries')
        print('PASS size reflow and global/workspace visibility retain monitor-wide normalized edge positions', flush=True)

        restart(session, positions)
        restore_click(session, records, True)
        restore_click(session, records, False)
        print('PASS lock and all edge positions survive restart; ordinary clicks restore correctly in both lock states', flush=True)
        configure('dockSide', 'bottom')
        configure('grouping', 'app')
        configure('staticDockLock', 'locked')
        wait(lambda: len(settled(session)['icons']) == 1, 'Compact locked dock did not group its fixtures')
        before_ids = ids()
        for preset in ('100', '50'):
            configure('sizePreset', preset)
            for button in (272, 274):
                for dx in (100, 0):
                    move_pointer(session, settled(session)['icons'][0], dx, -65, button=button)
                    assert ids() == before_ids, 'Dragging outside a compact locked dock activated or closed its icon'
        configure('sizePreset', '100')
        print('PASS compact single-icon locked docks reject left/middle drag gestures without restoring or closing', flush=True)
        configure('grouping', 'window')
        if with_small_output:
            small_output(session)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--small-output', action='store_true')
    args = parser.parse_args()
    main(args.small_output)
