#!/usr/bin/env python3
"""Native size presets, scaled artwork/input, safe resizing and overflow.

Install this checkout before running in an unlocked Hyprland session. Owned
fixtures and a temporary output are removed by NativeSession on completion.
"""
import json
import time

from desktop_test import desktop_test
from live import command, configure, h, shell, wait
from native_session import NativeSession


PRESETS = ('50', '75', '100', '125', '150', '175', '200', '250', '300')


def near(actual, expected, message, tolerance=.1):
    assert abs(actual-expected) <= tolerance, (message, actual, expected)


def bounded(rect, area):
    assert rect['x'] >= area['x']-.1 and rect['y'] >= area['y']-.1, ('Left/top bounds', rect, area)
    assert rect['x']+rect['width'] <= area['x']+area['width']+.1, ('Right bounds', rect, area)
    assert rect['y']+rect['height'] <= area['y']+area['height']+.1, ('Bottom bounds', rect, area)


def appearance(value, size):
    near(value['width'], size, 'Icon width did not follow the size preset')
    near(value['height'], size, 'Icon height did not follow the size preset')
    art = value['artwork']
    assert 0 < art['width'] <= size and art['width'] == art['height'], ('Artwork dimensions', art, size)
    near(art['x']+art['width']/2, size/2, 'Artwork was not centered horizontally')
    near(art['y']+art['height']/2, size/2, 'Artwork was not centered vertically')
    bounded(art, {'x': 0, 'y': 0, 'width': size, 'height': size})
    badge = value['badge']
    if badge['visible']:
        bounded(badge, {'x': 0, 'y': 0, 'width': size, 'height': size})
        assert badge['width'] > 0 and badge['height'] > 0, 'Grouped count badge disappeared'
    return art['width']


def native_select(session, preset):
    from settings_fit import reveal

    shell('settings')
    wait(lambda: session.surface()['dialog']['visible'], 'Size settings did not open')

    def control():
        return next(c for c in session.surface()['settingControls'] if c['key'] == 'sizePreset')

    session.click(reveal(session, lambda: control()['rect']))
    wait(lambda: control()['open'], 'Size dropdown did not open')
    session.keys(*(['-k', 'Up']*len(PRESETS)), *(['-k', 'Down']*PRESETS.index(preset)), '-k', 'Return')
    wait(lambda: shell('status')['settings'].get('sizePreset') == preset, 'Native size selection did not save '+preset)
    shell('dismiss')
    session.resting()


def collapse(session):
    if session.dock()['expanded']:
        session.keys('-k', 'Escape')
    session.resting()
    wait(lambda: not session.dock()['size']['pending'], 'Deferred size did not apply after folding')


def expand(session):
    session.click(session.dock()['handle'])
    return wait(lambda: (d if (d := session.dock())['expanded'] and not d['animating'] and not d['snapping'] else None),
                'Sized floating dock did not finish opening')


def fan_bounds(session, dock):
    area = session.surface()['usableArea']
    bounded(dock['panel'], area)
    size = dock['handle']['width']
    for actor in dock['actors']:
        if actor['slotVisible']:
            bounded(actor, area)
            appearance(actor['appearance'], size)
    near(dock['size']['tailStep'], size/12, 'Stack tail did not scale with the icon')
    return size


def resizing(session):
    configure('grouping', 'window')
    configure('presentation', 'floating')
    configure('floatingDirection', 'horizontal')
    configure('animations', 'full')
    configure('animationSpeed', 'slow')
    configure('floatingAnimation', 'jumping')
    configure('sizePreset', '100')
    session.resting()
    area = session.surface()['usableArea']
    session.position('dock:floating', round(area['x']+80), round(area['y']+area['height']*.4))
    dock = expand(session)
    before = tuple(a['key'] for a in dock['actors'])
    origin = (dock['handle']['x'], dock['handle']['y'])
    configure('sizePreset', '300')
    dock = session.dock()
    assert tuple(a['key'] for a in dock['actors']) == before, 'Open resize recreated the icons'
    if dock['size']['pending']:
        near(dock['handle']['width'], 48, 'Folding fan resized before completing its path')
        near(dock['handle']['x'], origin[0], 'Resize moved the folding anchor horizontally')
        near(dock['handle']['y'], origin[1], 'Resize moved the folding anchor vertically')
    else:
        assert not dock['expanded'] and not dock['animating'], 'Size applied before the fan finished folding'
    wait(lambda: not session.dock()['expanded'] and not session.dock()['size']['pending'], 'Size change did not fold and resize the fan')
    session.resting()
    near(session.dock()['handle']['width'], 144, 'Folded fan did not apply the requested size')
    configure('sizePreset', '100')
    session.resting()
    handle = session.dock()['handle']
    session.move(handle['x']+24, handle['y']+24)
    session.pointer.button(True)
    wait(lambda: session.dock()['handle']['held'], 'Sized stack did not receive the drag press')
    for step in range(1, 5):
        session.move(handle['x']+24+step*10, handle['y']+24+step*5)
        time.sleep(.02)
    configure('sizePreset', '300')
    dock = session.dock()
    assert dock['handle']['held'] and dock['size']['pending'], 'Held stack did not defer its size change'
    near(dock['handle']['width'], 48, 'Held stack changed dimensions under the pointer')
    session.pointer.button(False)
    session.resting()
    wait(lambda: not session.dock()['size']['pending'], 'Released drag retained a pending size')
    near(session.dock()['handle']['width'], 144, 'Released stack did not apply its requested size')
    assert session.surface()['groups'] == 4, 'Resizing a held stack restored a window'
    assert not any(b['held'] for b in session.surface()['motion']['dragWorld']['bodies']), 'Size change left a ghost drag grab'
    fan_bounds(session, expand(session))
    collapse(session)
    print('PASS automatic folding and held size changes preserve identity and input, then resize safely', flush=True)


def pressed_icon_resizing(session):
    for mode, old_size, new_size in (('dock', 44, 66), ('bubbles', 48, 72)):
        configure('presentation', mode)
        configure('sizePreset', '100')
        session.resting()
        icon = session.icon()
        key = icon['key']
        before = {w['id'] for w in command('list')['windows']}
        session.move(icon['x']+icon['width']/2, icon['y']+icon['height']/2)
        session.pointer.button(True)
        wait(lambda: session.icon(key)['appearance']['feedback']['down'], 'Icon did not receive the size-test press')
        configure('sizePreset', '150')
        current = session.icon(key)
        near(current['width'], new_size if mode == 'dock' else old_size, 'Pressed icon used an unsafe resize policy')
        if mode == 'bubbles':
            assert current['held'], 'Bubble lost its held state before release'
        session.pointer.button(False)
        wait(lambda: session.icon(key) and abs(session.icon(key)['width']-new_size)<.1, 'Released icon did not apply its size')
        session.resting()
        wait(lambda: not shell('status')['controllerBusy'] and not shell('status')['queueLength'], 'Press resize left an action pending')
        assert {w['id'] for w in command('list')['windows']} == before, 'Resizing a pressed icon restored or closed a window'
        assert session.surface()['groups'] == 4, 'A pressed resize removed an icon'
        assert not any(b['held'] for b in session.surface()['motion']['dragWorld']['bodies']), 'Pressed resize retained a ghost grab'
    print('PASS static pressed-resize suppression and deferred bubble resize prevent accidental restoration', flush=True)


def static_reflow(session):
    for key, value in dict(presentation='dock', grouping='window', scope='workspace', dockSide='bottom',
                           animations='full', animationSpeed='slow', sizePreset='100').items():
        configure(key, value)
    wait(lambda: len(session.surface()['shelf']['icons']) == 4, 'Static reflow needs four owned fixture icons')
    session.resting()
    # Finish the initial arrival and any movement inherited from another mode;
    # subsequent preset changes are sampled immediately, without a settle wait.
    time.sleep(.5)
    initial = session.surface()['shelf']['icons']
    keys = tuple(i['key'] for i in initial)
    base_gap = initial[1]['x']-initial[0]['x']-initial[0]['width']
    for preset in ('100', '300', '50', '200'):
        configure('sizePreset', preset)
        size = 44*int(preset)/100
        samples = 0
        deadline = time.monotonic()+(.5 if preset == '200' else .18)
        while time.monotonic() < deadline or samples < 3:
            surface = session.surface()
            shelf = surface['shelf']
            icons = shelf['icons']
            assert tuple(i['key'] for i in icons) == keys, 'Static sizing changed icon identity or ordering'
            assert surface['groups'] == 4, 'Static reflow removed a stashed window'
            bounded(shelf, surface['usableArea'])
            for icon in icons:
                near(icon['width'], size, 'Static icon width lagged behind its size preset')
                near(icon['height'], size, 'Static icon height lagged behind its size preset')
                bounded(icon, shelf)
            for before, after in zip(icons, icons[1:]):
                assert after['x'] >= before['x']+before['width']-.1, ('Static size reflow overlapped adjacent icons', preset, before, after)
            target_width = len(icons)*size+(len(icons)-1)*base_gap*int(preset)/100 \
                + shelf['insets']['left']+shelf['insets']['right']
            near(shelf['width'], target_width, 'Static dock width did not immediately fit its new row', 1.1)
            samples += 1
            time.sleep(.005)
    print('PASS Full/Slow static size changes keep every frame ordered, bounded and free of overlap', flush=True)


def small_output(session, records):
    previous = {m['name'] for m in h.read('monitors')}
    h.call('output', 'create', 'headless')
    monitor = wait(lambda: next((m for m in h.read('monitors') if m['name'] not in previous), None), 'Temporary size-test output missing')
    session.outputs.append(monitor['name'])
    right = max(m['x']+round(m['width']/m['scale']) for m in h.read('monitors') if m['name'] != monitor['name'])
    h.eval('hl.monitor({output=%s,mode="320x240@60",position=%s,scale=1})' % (json.dumps(monitor['name']), json.dumps('%dx0' % right)))
    session.monitor = next(m for m in h.read('monitors') if m['name'] == monitor['name'])
    h.dispatch('focus', monitor=monitor['name'])
    h.dispatch('focus', workspace=str(session.workspace+3))
    wait(lambda: monitor['name'] in shell('status')['screens'], 'Temporary output has no shell surface')
    # Reuse only owned fixtures; user stash entries remain on their workspaces.
    for record in records:
        assert record['address'] in session.addresses, 'Refusing to move an unowned fixture'
        command('restore', record['id'], '--to', 'current', '--workspace', session.workspace+3)
        session.park(record['address'])
    configure('presentation', 'floating')
    configure('sizePreset', '300')
    for direction in ('horizontal', 'vertical'):
        configure('floatingDirection', direction)
        configure('floatingPlacement', 'edges')
        session.resting()
        dock = expand(session)
        size = fan_bounds(session, dock)
        assert size <= 144 and 1 <= dock['capacity'] < 4, 'Large icons did not exercise bounded overflow'
        axis = ('Right' if dock['fan']['sign'] > 0 else 'Left') if direction == 'horizontal' else ('Down' if dock['fan']['sign'] > 0 else 'Up')
        session.keys(*(['-k', axis]*3))
        wait(lambda: session.dock()['firstIndex'] > 0, 'Sized overflow did not expose later icons')
        session.resting()
        fan_bounds(session, session.dock())
        collapse(session)
    print('PASS largest preset remains bounded at small-output edges and exposes overflow on both axes', flush=True)


@desktop_test('Window Stash size presets test')
def main():
    with NativeSession() as session:
        for key, value in dict(presentation='dock', grouping='app', scope='workspace', animations='off',
                               sizePreset='100', animationSpeed='normal',
                               hoverPreview='off', dragMotion='direct', floatingPlacement='free',
                               iconShape='square', iconFrame='shown', dockFrame='shown', dockSide='bottom').items():
            configure(key, value)
        records = [session.park(session.spawn(app=app, workspace=session.workspace)[0])
                   for app in ('org.chromium.Chromium', 'org.chromium.Chromium', 'org.gnome.Nautilus', 'org.gnome.Nautilus')]
        widths = {mode: [] for mode in ('dock', 'bubbles', 'floating')}
        for preset in PRESETS:
            native_select(session, preset)
            for mode in widths:
                configure('presentation', mode)
                session.resting()
                surface = session.surface()
                size = round((44 if mode == 'dock' else 48)*int(preset)/100)
                icons = surface['shelf']['icons'] if mode == 'dock' else surface['bubbles'] if mode == 'bubbles' else [session.dock()['handle']]
                assert icons and any(i['appearance']['badge']['visible'] for i in icons), 'Grouped badge fixture missing'
                for icon in icons:
                    bounded(icon, surface['usableArea'])
                    appearance(icon['appearance'], size)
                widths[mode].append(icons[0]['appearance']['artwork']['width'])
                if mode == 'bubbles':
                    configure('floatingPlacement', 'edges')
                    session.resting()
                    bubbles = session.surface()['bubbles']
                    for index, a in enumerate(bubbles):
                        bounded(a, surface['usableArea'])
                        for b in bubbles[:index]:
                            assert a['x'] >= b['x']+b['width']-.1 or a['x']+a['width'] <= b['x']+.1 \
                                or a['y'] >= b['y']+b['height']-.1 or a['y']+a['height'] <= b['y']+.1, \
                                ('Sized edge bubbles overlapped', preset, a, b)
                    configure('floatingPlacement', 'free')
                    session.resting()
                if mode == 'dock':
                    shelf = surface['shelf']
                    near(shelf['height'], size+shelf['insets']['top']+shelf['insets']['bottom'], 'Static dock thickness did not follow icon sizing', 1.1)
        assert all(all(a < b for a, b in zip(values, values[1:])) for values in widths.values()), 'Size presets changed padding without growing artwork'
        native_select(session, '100')
        assert shell('status')['settings']['sizePreset'] == '100', 'Default size could not be restored'
        print('PASS all nine native size choices grow centered artwork in all three modes with bounded badges/input', flush=True)
        resizing(session)
        pressed_icon_resizing(session)
        static_reflow(session)
        configure('presentation', 'dock')
        configure('sizePreset', '300')
        session.resting()
        icon = session.surface()['shelf']['icons'][0]
        record = next(r for r in records if 'window:'+str(r.get('stableId') or r['id']) == icon['key'])
        session.click(icon)
        wait(lambda: not any(w['id'] == record['id'] for w in command('list')['windows']), 'Large icon center did not restore its window')
        records[records.index(record)] = session.park(record['address'])
        print('PASS enlarged icon input restores only its owned fixture', flush=True)
        small_output(session, records)
        assert not shell('status')['error'], shell('status')['error']
    wait(lambda: not shell('status')['controllerBusy'] and not shell('status')['queueLength'], 'Size-test cleanup did not finish')


if __name__ == '__main__':
    main()
