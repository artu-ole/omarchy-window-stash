#!/usr/bin/env python3
"""Grouped interactive miniatures, keyboard routing and small-output clipping.

Requires the explicit disposable profile. All input, source windows, log files,
positions and the additional 320x240 output belong to this preserving test.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile

from desktop_test import desktop_test
from floating_previews import drain, park, preview_owner, previews, ready, touch
from interactive_bridge import events, native_status, scroll, spawn_fixture
from interactive_keyboard import content_click, key_count, text
from interactive_previews import active, assert_source, interaction, stopped
from live import command, configure, h, shell, wait
from native_session import NativeSession
from settings_fit import contained


def tile(session, record):
    return next((value for value in previews(session)['tiles'] if value['recordId'] == record['id']), None)


def ready_tile(session, record, fully_visible=True):
    return wait(lambda: (value := tile(session, record)) and value['image']['hasContent']
                and (not fully_visible or value['interaction']['fullyVisible']) and value,
                'The exact grouped preview did not become ready')


def cover(session):
    return wait(lambda: (value := ready(session)) and value['groupCount'] == 2 and value,
                'Two same-app windows did not form one cover')


def expand(session):
    clicked = None
    if not previews(session)['expanded']:
        clicked = cover(session)
        session.click(clicked['imageRect'])
    try:
        return wait(lambda: previews(session)['expanded'] and len(previews(session)['tiles']) == 2 and previews(session),
                    'The app cover did not expand into both exact windows')
    except AssertionError:
        artifacts = Path(tempfile.mkdtemp(prefix='stash-group-failure-'))
        status = shell('status')
        diagnostic = dict(clicked=clicked, previews=previews(session), pointer=status['pointer'],
                          buttons=status['pressedPointerButtons'], interaction=status['previewInteraction'],
                          grouping=status['settings']['grouping'], workspace=session.surface()['workspaceId'],
                          screen=session.monitor['name'], context=session.menu()['opened'], error=status['error'])
        (artifacts/'status.json').write_text(json.dumps(diagnostic, indent=2)+'\n')
        try:
            subprocess.run(['grim', '-o', session.monitor['name'], str(artifacts/'screen.png')],
                           check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass
        print('Group expansion diagnostics:', json.dumps(diagnostic), 'private artifacts:', str(artifacts), flush=True)
        raise


def start_tile(session, record):
    value = ready_tile(session, record)
    rect = value['imageRect']
    session.move(rect['x']+rect['width']*.4, rect['y']+rect['height']*.7)
    value = wait(lambda: (value := tile(session, record)) and value['interaction']['controlsVisible'] and value,
                 'Exact grouped-window interaction controls did not appear')
    session.click(value['interaction']['interactRect'])
    result = wait(lambda: active(record), 'Grouped-window Interact did not acquire its exact source', timeout=150)
    wait(lambda: (value := tile(session, record)) and value['image']['live'] and value['interaction']['active'],
         'Grouped interaction did not show a live active miniature')
    return result


def click_source(session, record, x=.75, y=.75):
    rect = ready_tile(session, record)['imageRect']
    point = rect['x']+rect['width']*x, rect['y']+rect['height']*y
    session.move(point[0]-1, point[1])
    session.pointer.click(*session.point(*point))


def close_expansion(session):
    area = session.surface()['usableArea']
    session.pointer.click(*session.point(area['x']+3, area['y']+3))
    wait(lambda: not previews(session)['expanded'], 'Outside click did not collapse the grouped previews')
    wait(stopped, 'Collapsing the group retained native input ownership')


def native_owner(result):
    return result['status']['status']['owner']


def assert_controls_bounded(session, record):
    value = ready_tile(session, record)
    controls = value['interaction']
    area = session.surface()['usableArea']
    assert controls['controlsVisible'] and contained(controls['controlsRect'], area), \
        ('Grouped management controls escaped the small work area', controls, area)
    for field in ('interactRect', 'restoreRect', 'manageRect'):
        assert contained(controls[field], controls['controlsRect']), ('A management button overflowed its control bar', field, controls)
    if controls['controlsOutside']:
        image, bar = value['imageRect'], controls['controlsRect']
        overlap = min(image['x']+image['width'], bar['x']+bar['width']) > max(image['x'], bar['x']) \
            and min(image['y']+image['height'], bar['y']+bar['height']) > max(image['y'], bar['y'])
        assert not overlap, 'A detached grouped toolbar obstructed the interactive image'


def keyboard_and_replacement(session, records, logs, originals):
    expand(session)
    before = [len(events(log, 'press')) for log in logs]
    first = start_tile(session, records[0])
    assert [len(events(log, 'press')) for log in logs] == before, 'Entering group interaction clicked an app'
    request = first['request']
    content_click(session, request['rect'], originals[0][2], 120, 46)
    session.keys('group-first')
    wait(lambda: text(logs[0]) == 'group-first', 'Typing did not reach the selected grouped window entry')
    assert text(logs[1]) == '', 'Grouped typing reached the other stashed window'
    click_source(session, records[0])
    escaped, arrows = key_count(logs[0], 'Escape'), key_count(logs[0], 'Right')
    session.keys('-k', 'Escape', '-k', 'Right')
    wait(lambda: key_count(logs[0], 'Escape') == escaped+1 and key_count(logs[0], 'Right') == arrows+1,
         'Expanded-group shortcuts stole application Escape or arrow keys')
    assert previews(session)['expanded'] and active(records[0]), 'Application keys collapsed the chooser or ended interaction'
    assert_source(records[0], originals[0]);assert_source(records[1], originals[1])
    print('PASS an exact grouped window receives real entry typing, Escape and arrows while its sibling remains untouched and the chooser stays expanded', flush=True)

    old_owner, old_serial = native_owner(first), request['serial']
    before = [len(events(log, 'press')) for log in logs]
    second = start_tile(session, records[1])
    assert second['request']['serial'] > old_serial and native_owner(second) != old_owner, 'Replacing a group target reused its input owner'
    old = native_status(old_owner)
    assert not old['active'] and not old['heldButtons'] and not old['heldKeys'], 'The replaced group member retained native input'
    assert not tile(session, records[0])['interaction']['busy'], 'The previous grouped tile retained UI ownership'
    assert [len(events(log, 'press')) for log in logs] == before, 'Replacement activation leaked a button into either app'
    content_click(session, second['request']['rect'], originals[1][2], 120, 46)
    session.keys('group-second')
    wait(lambda: text(logs[1]) == 'group-second', 'The replacement grouped entry did not receive typing')
    assert text(logs[0]) == 'group-first', 'Replacement typing continued reaching the previous source'
    close_expansion(session)
    assert not native_status(native_owner(second))['active'], 'Collapsed group retained its native owner'
    assert_source(records[0], originals[0]);assert_source(records[1], originals[1])
    print('PASS replacing the exact grouped target releases the old owner, routes keyboard input once and ends ownership when the group collapses', flush=True)


def small_output(session):
    existing = h.read('monitors')
    h.call('output', 'create', 'headless')
    output = wait(lambda: next((monitor for monitor in h.read('monitors') if monitor['name'] not in {item['name'] for item in existing}), None),
                  'Small grouped-preview output was not created')
    session.outputs.append(output['name'])
    right = max(monitor['x']+round(monitor['width']/monitor['scale']) for monitor in existing)
    h.eval('hl.monitor({output=%s,mode="320x240@60",position=%s,scale=1})' %
           (json.dumps(output['name']), json.dumps(str(right)+'x0')))
    h.dispatch('focus', monitor=output['name'])
    h.dispatch('focus', workspace=str(session.workspace+1))
    session.monitor = wait(lambda: next((monitor for monitor in h.read('monitors') if monitor['name'] == output['name'] and monitor['width'] == 320), None),
                           'Small grouped output geometry did not settle')
    session.move(160, 120)
    h.dispatch('focus', monitor=output['name'])
    h.dispatch('focus', workspace=str(session.workspace+1))
    wait(lambda: output['name'] in shell('status')['screens'], 'The small output has no plugin surface')


def visible_part(session, value):
    image, viewport = value['imageRect'], previews(session)['viewportRect']
    left, top = max(image['x'], viewport['x']), max(image['y'], viewport['y'])
    right = min(image['x']+image['width'], viewport['x']+viewport['width'])
    bottom = min(image['y']+image['height'], viewport['y']+viewport['height'])
    assert right > left and bottom > top, 'A supposedly visible grouped tile is completely clipped'
    return {'x': left, 'y': top, 'width': right-left, 'height': bottom-top}


def small_group(session, records, logs, originals):
    small_output(session)
    for record in records:
        touch(session, record)
    for key, value in dict(scope='global', floatingPreviewKeyboard='mouse', floatingPreviewSizing='preset').items():
        configure(key, value)
    wait(lambda: session.surface()['width'] == 320 and session.surface()['height'] == 240,
         'The small grouped-preview surface did not adopt the requested size')
    by_id = {record['id']: index for index, record in enumerate(records)}
    for scale in ('50', '75'):
        configure('floatingPreviewScale', scale)
        expand(session)
        values = wait(lambda: (values := previews(session)['tiles']) and all(item['image']['hasContent'] for item in values) and values,
                      'Small grouped captures did not become ready')
        full = next(value for value in values if value['interaction']['fullyVisible'])
        index = by_id[full['recordId']]
        result = start_tile(session, records[index])
        assert_controls_bounded(session, records[index])
        click_source(session, records[index])
        scrolling = [len(events(log, 'scroll')) for log in logs]
        grid_y = previews(session)['groupOverflow']['contentY']
        scroll(session.pointer)
        wait(lambda: len(events(logs[index], 'scroll')) > scrolling[index], 'Small grouped app did not receive its own scrolling')
        assert abs(previews(session)['groupOverflow']['contentY']-grid_y) <= .1, 'Application scrolling moved the grouped chooser'
        assert len(events(logs[1-index], 'scroll')) == scrolling[1-index], 'Scrolling reached an unrelated stashed group member'
        assert_source(records[0], originals[0]);assert_source(records[1], originals[1])
        if scale == '50':
            close_expansion(session)
            print('PASS 320x240 at 50%: grouped controls remain bounded, app scrolling reaches only its selected window, and the grid stays fixed', flush=True)
            continue
        group = previews(session)
        assert group['groupOverflow']['enabled'], 'The 75% small-output case did not exercise grouped overflow'
        partial = max(group['tiles'], key=lambda value: value['imageRect']['y'])
        assert partial['recordId'] != records[index]['id'] and not partial['interaction']['fullyVisible'], \
            'The overflow fixture has no inactive partially clipped group member'
        area = visible_part(session, partial)
        session.move(area['x']+area['width']*.2, area['y']+area['height']*.8)
        assert native_status(native_owner(result))['active'], 'Moving to an inactive tile ended interaction before any click or clipping'
        scrolling = [len(events(log, 'scroll')) for log in logs]
        scroll(session.pointer, delta=60)
        wait(lambda: previews(session)['groupOverflow']['contentY'] > grid_y+1, 'Scrolling an inactive tile did not move its overflowing grid')
        wait(stopped, 'Clipping the active grouped image did not release native input')
        assert [len(events(log, 'scroll')) for log in logs] == scrolling, 'Chooser scrolling leaked to a hidden application'
        assert not native_status(native_owner(result))['active'], 'A clipped grouped image retained native ownership'

        # Closing for a context menu resets the grid scroll. Its action must
        # reopen the last exact member and reveal it fully before acquiring input.
        target = next(record for record in records if record['id'] == partial['recordId'])
        target_value = ready_tile(session, target, fully_visible=False)
        area = visible_part(session, target_value)
        point = area['x']+area['width']*.2, area['y']+area['height']*.8
        session.pointer.click(*session.point(*point), button=273)
        wait(lambda: session.menu()['opened'], 'An exact clipped group tile could not open its context menu')
        session.click(session.action('interact')['rect'])
        wait(lambda: active(target), 'Context Interact did not reveal and activate its exact grouped member', timeout=150)
        assert ready_tile(session, target)['interaction']['fullyVisible'], 'Context interaction acquired a partially hidden tile'
        assert previews(session)['groupOverflow']['contentY'] > 0, 'Context interaction did not scroll the target row fully into view'
        assert_controls_bounded(session, target)
        assert_source(records[0], originals[0]);assert_source(records[1], originals[1])
        close_expansion(session)
        print('PASS 320x240 at 75%: inactive-tile grid scrolling releases a clipped active target, and context Interact reveals the exact row before reacquiring input', flush=True)


@desktop_test('Isolated grouped interactive-preview acceptance')
def main():
    assert os.environ.get('WINDOW_STASH_ISOLATED_TEST') == '1' and (Path.home()/'.window-stash-isolated').is_file(), \
        'Run grouped input tests only in the disposable profile'
    assert not command('list')['windows'], 'Grouped interaction requires an empty disposable stash'
    with tempfile.TemporaryDirectory(prefix='stash-interactive-groups-') as temporary, NativeSession() as session:
        for key, value in dict(presentation='previews', scope='workspace', grouping='app',
                               floatingPreviewInteraction='on', floatingPreviewActivation='explicit', floatingPreviewKeyboard='click',
                               floatingPreviewInteractionFps='60', floatingPreviewControls='hover', floatingPreviewUpdate='still',
                               livePreviewCompatibility='standard', hoverPreview='off', floatingPreviewSizing='free',
                               floatingPreviewTitles='hidden', floatingPreviewFrame='hidden', floatingPreviewLock='unlocked',
                               floatingPlacement='free', dragMotion='direct', animations='off').items():
            configure(key, value)
        logs = [Path(temporary)/('member-'+str(index)+'.jsonl') for index in range(2)]
        addresses = [spawn_fixture(session, log) for log in logs]
        records = [park(session, address) for address in addresses]
        assert records[0]['app'] == records[1]['app'], 'The grouped fixtures did not share their application identity'
        originals = []
        for record in records:
            client = h.client(record['address'])
            originals.append((client['workspace'], client['at'], client['size'], client['floating']))
        key = 'preview:app:'+records[0]['app'].lower()
        drain()
        area = session.surface()['usableArea']
        x, y = round(area['x']+area['width']-320), round(area['y']+150)
        command('preview-position', preview_owner(session), key, x, y, 280)
        shell('refresh')
        wait(lambda: (value := cover(session)) and abs(value['x']-x)<1 and abs(value['y']-y)<1
             and abs(value['width']-280)<1 and not value['moving'], 'Saved grouped cover geometry was not acknowledged')
        presses = [len(events(log, 'press')) for log in logs]
        expand(session)
        assert [len(events(log, 'press')) for log in logs] == presses and stopped(), 'Opening an app cover restored or interacted with a member'
        keyboard_and_replacement(session, records, logs, originals)
        small_group(session, records, logs, originals)
        shell('dismiss')
        wait(stopped, 'Grouped acceptance retained a native input worker')
        drain()
        assert not shell('status')['error'], shell('status')['error']
    assert stopped() and not command('list')['windows'], 'Grouped preserving cleanup retained an input owner or stash record'


if __name__ == '__main__':
    main()
