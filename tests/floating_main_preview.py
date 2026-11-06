#!/usr/bin/env python3
"""Stationary front-icon previews after floating-dock unfolding.

Install this checkout first. The suite uses only owned color fixtures and
NativeSession restores the existing desktop after the five-second warning.
"""
import time

from desktop_test import desktop_test
from hover_previews import captured, captured_tiles, hidden, hover, preview, spawn_color
from live import configure, h, shell, wait
from native_session import NativeSession
from stash import SPECIAL


def actor(session, ordinal):
    return next(a for a in session.dock()['icons'] if a['ordinal'] == ordinal)


def check_source(session, source, records, live=False):
    # Capture/status polling injects no pointer motion. In particular, do not
    # use hover() here: its missed-enter retry would hide the original bug.
    try:
        wait(lambda: preview(session)['opened'] and preview(session)['recordId'] == records[0]['id'],
             'The hovered floating icon did not open its preview', timeout=3)
    except AssertionError:
        value = preview(session)
        print('Floating preview diagnostics:', {'expected': records[0]['id'], 'source': source,
              'preview': {k: value[k] for k in ('opened', 'pending', 'recordId', 'sourceHovered', 'hovered', 'rect', 'sourceRect')},
              'expanded': session.dock()['expanded'], 'icons': [
                  {k: a[k] for k in ('key', 'x', 'y', 'width', 'height')} for a in session.dock()['icons']]}, flush=True)
        raise
    value = captured_tiles(session, records) if len(records) > 1 else captured(session, records[0])
    for key in ('x', 'y', 'width', 'height'):
        assert abs(value['sourceRect'][key]-source[key]) < .1, \
            ('Expanded preview used the collapsed input handle instead of its icon', key, value['sourceRect'], source)
    images = [tile['image'] for tile in value['tiles'] if tile['visible']]
    assert images and all(image['live'] == live for image in images), 'The selected capture mode was not applied'
    assert session.dock()['expanded'], 'Previewing the main icon collapsed its dock'
    return value


def move_to(session, source):
    x, y = source['x']+source['width']/2, source['y']+source['height']/2
    session.move(x-1, y)
    session.move(x, y)


def cycle(session, horizontal, sign, records, older_records, live=False, delay_check=False):
    hidden(session)
    configure('hoverPreview', 'off')
    configure('floatingDirection', 'horizontal' if horizontal else 'vertical')
    session.resting()
    area = session.surface()['usableArea']
    x = area['x']+24 if sign > 0 else area['x']+area['width']-80
    y = area['y']+area['height']*.4
    if not horizontal:
        x = area['x']+area['width']*.45
        y = area['y']+24
    session.position('dock:floating', round(x), round(y))
    configure('hoverPreview', 'live' if live else 'still')
    handle = session.dock()['handle']
    session.click(handle)
    wait(lambda: session.dock()['expanded'] and not session.dock()['animating'], 'Floating dock did not finish unfolding')
    assert session.dock()['fan']['sign'] == sign, 'Fixture unfolded in the wrong direction'
    main = actor(session, 0)
    assert abs(main['x']-handle['x']) < .1 and abs(main['y']-handle['y']) < .1, 'Unfold moved the front icon'
    check_source(session, main, records, live)

    older = actor(session, 1)
    # Use the established missed-enter handling for this control icon; the
    # main icon above and below must work without any retry or pointer nudge.
    hover(session, older, older_records[0])
    check_source(session, older, older_records, live)
    entered = time.monotonic()
    move_to(session, main)
    if delay_check:
        wait(lambda: preview(session)['pending'] and preview(session)['recordId'] == records[0]['id'],
             'Re-entering the main icon did not start its preview delay')
        time.sleep(.08)
        assert not preview(session)['opened'], 'Main-icon preview bypassed the configured 400 ms delay'
    check_source(session, main, records, live)
    if delay_check:
        assert time.monotonic()-entered >= .30, 'Main-icon preview opening delay was shortened'
    print('PASS '+('horizontal right' if horizontal and sign > 0 else 'horizontal left' if horizontal else 'vertical')+
          ': stationary front preview, older-to-front retargeting and '+('grouped Live' if live else 'Still')+' captures', flush=True)
    return main


@desktop_test('Unfolded floating dock front preview test')
def main():
    with NativeSession() as session:
        for key, value in dict(scope='workspace', presentation='floating', grouping='window', sizePreset='100',
                               floatingPlacement='free', dragMotion='direct', floatingAnimation='cascade',
                               animations='full', animationSpeed='normal', iconFrame='hidden', dockFrame='hidden',
                               hoverPreview='still', previewDelay=400, previewHideDelay=200, restoreDestination='current').items():
            configure(key, value)
        red = spawn_color(session, 'red', app='org.windowstash.MainPreviewOther')
        old = session.park(red)
        green = spawn_color(session, 'green', app='org.windowstash.MainPreviewFront')
        second = session.park(green)
        blue = spawn_color(session, 'blue', app='org.windowstash.MainPreviewFront')
        front = session.park(blue)
        session.resting()
        geometry = {address: (h.client(address)['at'], h.client(address)['size']) for address in (red, green, blue)}

        # The collapsed overlay remains a valid preview source while visible.
        hover(session, session.dock()['handle'], front)
        captured(session, front)
        assert not session.dock()['expanded'], 'Collapsed preview unexpectedly unfolded the stack'
        hidden(session)

        for sign in (1, -1):
            cycle(session, True, sign, [front], [second], delay_check=sign > 0)
            session.keys('-k', 'Escape')
            wait(lambda: not session.dock()['expanded'] and not session.dock()['animating'], 'Floating dock did not fold')
            hidden(session)
        configure('grouping', 'app')
        configure('animationSpeed', 'fast')
        session.resting()
        main_icon = cycle(session, False, 1, [front, second], [old], live=True)
        assert all((h.client(address)['at'], h.client(address)['size']) == before for address, before in geometry.items()), \
            'Previewing moved or resized a parked fixture'

        # The same front actor must retain its left-click action: an app group
        # opens its chooser, then restores just the selected owned window.
        session.click(main_icon)
        wait(lambda: shell('status')['dialog'] == 'picker' and session.surface()['dialog']['visible'], 'Front-icon click did not open its app chooser')
        session.keys('-k', 'Return')
        wait(lambda: h.client(blue)['workspace']['id'] == session.workspace, 'Front chooser did not restore its selected fixture')
        assert h.client(red)['workspace']['name'] == SPECIAL and h.client(green)['workspace']['name'] == SPECIAL, \
            'Front chooser restored an unrelated stashed window'
        hidden(session)
        print('PASS collapsed preview and front left-click chooser/restore remain available', flush=True)
    wait(lambda: not shell('status')['controllerBusy'] and not shell('status')['queueLength'], 'Preview-test cleanup did not finish')


if __name__ == '__main__':
    main()
