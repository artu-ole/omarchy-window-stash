#!/usr/bin/env python3
"""Three-output floating preview placement, scope, motion and unplug checks.

Run in a disposable desktop with one output and an empty stash. NativeSession
preserves settings, positions and focus; only owned fixtures/outputs are removed.
The shared desktop_test wrapper announces input automation five seconds ahead.
"""
import json
import time

from desktop_test import desktop_test
from floating_previews import bounded, card, drain, drag, ids, key, park, preview_owner, previews, ready, seed, touch
from hover_previews import spawn_color
from live import command, configure, h, shell, wait
from native_session import NativeSession
from stash import SPECIAL


def output(name):
    return next(monitor for monitor in h.read('monitors') if monitor['name'] == name)


def surface(name):
    return next(value for value in shell('status')['surfaces'] if value['screen'] == name)


def visible_ids(name):
    return {value['recordId'] for value in surface(name)['floatingPreviews']['cards']}


def rect(value):
    return tuple(value[field] for field in ('x', 'y', 'width'))


def same(actual, expected):
    return all(abs(a-b) < 1 for a, b in zip(actual, expected))


def settled(session):
    return wait(lambda: previews(session) if not previews(session)['held']
                and not previews(session)['world']['active'] else None,
                'Floating preview motion did not settle', timeout=7)


def create_output(session, x):
    before = {monitor['name'] for monitor in h.read('monitors')}
    h.call('output', 'create', 'headless')
    monitor = wait(lambda: next((value for value in h.read('monitors') if value['name'] not in before), None),
                   'Owned headless output did not appear')
    session.outputs.append(monitor['name'])
    h.eval('hl.monitor({output=%s,mode="640x480@60",position=%s,scale=1})'
           % (json.dumps(monitor['name']), json.dumps('%dx0' % x)))
    wait(lambda: monitor['name'] in shell('status')['screens'], 'Owned output has no plugin surface')
    return output(monitor['name'])


def assign_workspace(session, monitor, workspace):
    session.monitor = output(monitor['name'])
    h.dispatch('focus', monitor=monitor['name'])
    h.dispatch('focus', workspace=str(workspace))
    wait(lambda: surface(monitor['name'])['workspaceId'] == workspace, 'Output workspace did not activate')


def save_all_cards(session, monitors, records):
    expected = {}
    for index, monitor in enumerate(monitors):
        session.monitor = output(monitor['name'])
        area = session.surface()['usableArea']
        expected[monitor['name']] = {}
        for ordinal, record in enumerate(records):
            touch(session, record)
            width = 210+ordinal*10 if index == 0 else 150+index*15+ordinal*5
            x = area['x']+(330 if ordinal == 1 else 40)
            y = area['y']+(270 if ordinal == 2 else 50)
            value = seed(session, record, x=x, y=y, width=width)
            bounded(session, value)
            expected[monitor['name']][record['id']] = rect(value)
    drain()
    snapshot = command('list')['positions']
    for monitor in monitors:
        session.monitor = output(monitor['name'])
        owner = preview_owner(session)
        for record in records:
            assert same(snapshot[owner][key(record)], expected[monitor['name']][record['id']]), \
                'A monitor did not retain its own preview geometry'
    for record in records:
        assert len({round(expected[monitor['name']][record['id']][2]) for monitor in monitors}) == 3, \
            'Independent output widths collapsed onto one shared setting'
    print('PASS three global surfaces show the same stash with independent per-output positions and widths', flush=True)
    return expected


def filtered_visibility(session, monitors, records):
    configure('scope', 'workspace')
    for monitor, record in zip(monitors, records):
        wait(lambda name=monitor['name'], ident=record['id']: visible_ids(name) == {ident},
             'Workspace filtering leaked windows between output workspace banks')
    primary = monitors[0]
    assign_workspace(session, primary, session.workspace+4)
    wait(lambda: not visible_ids(primary['name']), 'An unrelated workspace retained preview cards')
    for monitor, record in zip(monitors[1:], records[1:]):
        assert visible_ids(monitor['name']) == {record['id']}, 'Changing one output changed another output stash'
    assert all(h.client(record['address'])['workspace']['name'] == SPECIAL for record in records), \
        'Workspace filtering restored a source window'
    assign_workspace(session, primary, session.workspace)
    configure('scope', 'global')
    wanted = {record['id'] for record in records}
    wait(lambda: all(visible_ids(monitor['name']) == wanted for monitor in monitors),
         'Global scope did not restore all three independent surfaces')
    print('PASS distinct origin workspaces filter per output without restoring or moving source windows', flush=True)


def pointer_motion(session, primary, records):
    session.monitor = output(primary['name'])
    assign_workspace(session, primary, session.workspace)
    wanted = ids()
    source_geometry = {record['id']: (h.client(record['address'])['at'], h.client(record['address'])['size'])
                       for record in records}
    configure('dragMotion', 'direct')
    first = ready(session, records[0])
    drag(session, first['imageRect'], 50, 20)
    settled(session)
    moved = ready(session, records[0])
    assert moved['x'] > first['x']+25, 'Direct preview drag did not follow pointer movement'
    bounded(session, moved)

    target = seed(session, records[2], x=140, y=session.surface()['usableArea']['y']+340, width=190)
    configure('animations', 'full')
    configure('animationSpeed', 'fast')
    configure('dragMotion', 'physics')
    settled(session)
    target = ready(session, records[2])
    x = target['imageRect']['x']+target['imageRect']['width']/2
    y = target['imageRect']['y']+target['imageRect']['height']/2
    session.move(x-1, y)
    session.move(x, y)
    time.sleep(.06)
    session.pointer.button(True)
    try:
        wait(lambda: card(session, records[2])['held'], 'Physics card did not acquire its drag')
        for step in range(1, 6):
            session.move(x+step*18, y)
            time.sleep(.012)
        held = card(session, records[2])
        assert held['held'] and held['x'] > target['x']+50, 'Physics drag did not follow the pointer'
    finally:
        session.pointer.button(False)
    wait(lambda: card(session, records[2])['x'] > held['x']+10, 'Flick released without carrying momentum', timeout=3)
    settled(session)
    value = ready(session, records[2])
    bounded(session, value)
    body = next(body for body in previews(session)['world']['bodies'] if body['key'] == key(records[2]))
    assert body['frames'] >= 3 and not body['held'] and not body['moving'], 'Physics flick did not advance and settle'
    drain()
    saved = command('list')['positions'][preview_owner(session)][key(records[2])]
    assert same(saved, rect(value)), 'Settled momentum did not persist preview geometry'
    assert ids() == wanted, 'Moving a preview restored or closed a stashed source'
    assert all((h.client(record['address'])['at'], h.client(record['address'])['size']) == source_geometry[record['id']]
               for record in records), 'Card movement changed actual window geometry'
    configure('animations', 'off')
    configure('dragMotion', 'direct')
    settled(session)
    print('PASS direct pointer drag and physics flick move only the miniature, retain momentum, settle bounded and save geometry', flush=True)


def disconnect(session, monitors, records):
    wanted = {record['id'] for record in records}
    saved = command('list')['positions']
    expected = {monitor['name']: {record['id']: rect(next(value for value in surface(monitor['name'])['floatingPreviews']['cards']
                                                       if value['recordId'] == record['id']))
                                  for record in records} for monitor in monitors[:-1]}
    removed = monitors[-1]['name']
    session.monitor = output(monitors[0]['name'])
    h.call('output', 'remove', removed)
    session.outputs.remove(removed)
    wait(lambda: removed not in shell('status')['screens'] and removed not in {value['name'] for value in h.read('monitors')},
         'Disconnected output retained a shell surface')
    wait(lambda: all(visible_ids(monitor['name']) == wanted for monitor in monitors[:-1]),
         'Disconnect lost preview cards on a remaining output')
    assert ids() == wanted, 'Disconnect lost a ledger entry'
    assert all(h.client(record['address'])['workspace']['name'] == SPECIAL for record in records), \
        'Disconnect restored or closed a hidden source window'
    drain()
    current = command('list')['positions']
    for monitor in monitors[:-1]:
        session.monitor = output(monitor['name'])
        owner = preview_owner(session)
        for record in records:
            value = ready(session, record)
            bounded(session, value)
            assert same(rect(value), expected[monitor['name']][record['id']]), 'Disconnect moved a remaining output card'
            assert current[owner][key(record)] == saved[owner][key(record)], 'Disconnect rewrote remaining output geometry'
    print('PASS removing an origin output keeps every source stashed and preserves all remaining output cards and saved geometry', flush=True)


@desktop_test('Floating previews three-monitor and momentum tests')
def main():
    initial_outputs = h.read('monitors')
    assert len(initial_outputs) == 1 and not command('list')['windows'], \
        'Run this focused three-output suite in a disposable single-output desktop with an empty stash'
    with NativeSession() as session:
        primary = dict(session.monitor)
        for name, value in dict(presentation='previews', scope='global', grouping='window', hoverPreview='off',
                                livePreviewCompatibility='standard', floatingPreviewUpdate='still',
                                floatingPreviewSizing='free', floatingPreviewScale='100', floatingPreviewTitles='hidden',
                                floatingPreviewFrame='hidden', floatingPreviewLock='unlocked',
                                floatingPlacement='free', dragMotion='direct', animations='off', iconOpacity=100).items():
            configure(name, value)
        right = max(monitor['x']+round(monitor['width']/monitor['scale']) for monitor in initial_outputs)
        monitors = [primary, create_output(session, right), create_output(session, right+640)]
        assert len(h.read('monitors')) == 3, 'The test did not create exactly three outputs'
        records = []
        for index, monitor in enumerate(monitors):
            assign_workspace(session, monitor, session.workspace+index)
            address = spawn_color(session, ('red', 'green', 'blue')[index],
                                  app='org.windowstash.FloatingMonitor'+str(index), workspace=session.workspace+index)
            records.append(park(session, address))
        wanted = {record['id'] for record in records}
        wait(lambda: all(visible_ids(monitor['name']) == wanted for monitor in monitors),
             'The shared stash did not appear on all three outputs')
        save_all_cards(session, monitors, records)
        filtered_visibility(session, monitors, records)
        pointer_motion(session, primary, records)
        disconnect(session, monitors, records)
        drain()
        assert not shell('status')['error'], shell('status')['error']
    drain()
    assert len(h.read('monitors')) == 1 and not command('list')['windows'], \
        'Preserving cleanup retained a test output or stashed fixture'
    print('PASS three-monitor cleanup restores settings, positions, focus and the original output set', flush=True)


if __name__ == '__main__':
    main()
