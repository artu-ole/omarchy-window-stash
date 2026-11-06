#!/usr/bin/env python3
"""Native speed presets, shared-clock interruption and unchanged input delays.

Run after installing this checkout in an unlocked Hyprland session. Only owned
fixtures are parked; NativeSession restores settings, positions and focus.
"""
import time

from desktop_test import desktop_test
from live import configure, shell, wait
from native_session import NativeSession


PRESETS = ('slow', 'relaxed', 'normal', 'fast', 'ultrafast')
RATES = dict(zip(PRESETS, (.5, .75, 1, 1.5, 2.5)))


def near(actual, expected, message, tolerance=1.1):
    assert abs(actual-expected) <= tolerance, (message, actual, expected)


def native_select(session, speed):
    from settings_fit import reveal

    shell('settings')
    wait(lambda: session.surface()['dialog']['visible'], 'Speed settings did not open')

    def control():
        return next(c for c in session.surface()['settingControls'] if c['key'] == 'animationSpeed')

    session.click(reveal(session, lambda: control()['rect']))
    wait(lambda: control()['open'], 'Animation speed dropdown did not open')
    session.keys(*(['-k', 'Up']*len(PRESETS)),
                 *(['-k', 'Down']*PRESETS.index(speed)), '-k', 'Return')
    wait(lambda: shell('status')['settings']['animationSpeed'] == speed, 'Native speed selection did not save')
    assert session.surface()['motion']['speed'] == speed
    shell('dismiss')
    wait(lambda: not session.surface()['dialog']['rendered'], 'Speed settings did not finish fading')
    session.resting()


class Cycle:
    def __init__(self, session):
        self.session = session
        dock = session.dock()
        self.created = dock['createdIcons']
        self.keys = tuple(a['key'] for a in dock['actors'])
        self.anchor = (dock['handle']['x'], dock['handle']['y'])
        self.samples = 0

    def inspect(self):
        dock = self.session.dock()
        assert dock['createdIcons'] == self.created, 'Changing speed recreated fan actors'
        assert tuple(a['key'] for a in dock['actors']) == self.keys, 'Changing speed reordered actors'
        front = next(a for a in dock['actors'] if a['ordinal'] == 0)
        for x, expected in ((front['x'], self.anchor[0]), (front['y'], self.anchor[1]),
                            (dock['handle']['x'], self.anchor[0]), (dock['handle']['y'], self.anchor[1])):
            near(x, expected, 'Original floating icon moved', .001)
        if dock['animating']:
            self.samples += 1
        return dock

    def finish(self, opened):
        deadline = time.monotonic()+5
        while time.monotonic() < deadline:
            dock = self.inspect()
            if dock['expanded'] == opened and not dock['animating'] and not dock['snapping']:
                return dock
            time.sleep(.002)
        raise AssertionError(('Speed cycle did not settle', opened, self.session.dock()))


def begin(session):
    cycle = Cycle(session)
    handle = session.dock()['handle']
    session.move(handle['x']+23, handle['y']+24)
    session.move(handle['x']+24, handle['y']+24)
    started = time.monotonic()
    session.pointer.button(True)
    session.pointer.button(False)
    return cycle, started


def timing(session, style, speed):
    cycle, started = begin(session)
    opened = cycle.finish(True)
    elapsed_open = time.monotonic()-started
    assert cycle.samples, 'Unfold did not expose any intermediate frames'
    assert opened['style'] == style and opened['capacity'] == 4
    opening = 372 if style == 'arc' else 630/1.5
    closing = 322 if style == 'arc' else 570/1.5
    assert opened['animation']['speed'] == speed
    near(opened['animation']['duration'], opening/RATES[speed], 'Actual unfold duration binding')
    started = time.monotonic()
    session.keys('-k', 'Escape')
    closed = cycle.finish(False)
    elapsed_close = time.monotonic()-started
    near(closed['animation']['duration'], closing/RATES[speed], 'Actual fold duration binding')
    # Status IPC adds a little polling overhead, but the animation cannot take
    # an unrelated amount of time while merely reporting a scaled duration.
    for actual, expected in ((elapsed_open, opening/RATES[speed]/1000),
                             (elapsed_close, closing/RATES[speed]/1000)):
        assert expected*.65 <= actual <= expected+.35, ('Native playback did not follow the preset', style, speed, actual, expected)
    return elapsed_open, elapsed_close


def away(session):
    area = session.surface()['usableArea']
    session.move(area['x']+8, area['y']+8)


def feedback(appearance, speed, mode='full'):
    state = appearance['feedback']
    assert state['animationSpeed'] == speed
    hot, down = state['hot'], state['down']
    raw = {'hover': 130 if hot else 180, 'press': 75 if down else 170,
           'opacity': 140 if hot or down else 200}
    for name, value in raw.items():
        expected = 0 if mode == 'off' else (90 if mode == 'reduced' else value)/RATES[speed]
        near(state['durations'][name], expected, 'Actual '+name+' feedback duration')


@desktop_test('Animation speed presets test')
def main():
    with NativeSession() as session:
        for key, value in dict(presentation='floating', grouping='window', scope='workspace',
                               sizePreset='100', animationSpeed='normal',
                               animations='full', hoverPreview='off', floatingPlacement='free',
                               floatingDirection='horizontal', floatingAnimation='arc',
                               iconShape='square').items():
            configure(key, value)
        records = [session.park(session.spawn(workspace=session.workspace)[0]) for _ in range(4)]
        session.resting()
        area = session.surface()['usableArea']
        session.position('dock:floating', round(area['x']+area['width']*.45), round(area['y']+area['height']*.45))
        for speed in PRESETS:
            native_select(session, speed)
        print('PASS all five speed presets save through the native settings dropdown', flush=True)

        for style in ('arc', 'matryoshka-hop'):
            configure('floatingAnimation', style)
            measured = []
            for speed in PRESETS:
                configure('animationSpeed', speed)
                session.resting()
                measured.append(timing(session, style, speed))
            for index, name in enumerate(('unfold', 'fold')):
                values = [entry[index] for entry in measured]
                assert all(a > b for a, b in zip(values, values[1:])), (style, name, 'Preset ordering failed', values)
                assert values[0] > values[-1]*2.5, (style, name, 'Slow and Ultrafast playback were indistinguishable', values)
            print('PASS '+style+' real unfold/fold ordering, scaled bindings, fixed origin and persistent actors', flush=True)

        configure('animationSpeed', 'slow')
        cycle, _ = begin(session)
        wait(lambda: session.dock()['expanded'], 'Slow nested stack did not open')
        away(session)
        state = wait(lambda: (d if .5 <= (d := cycle.inspect())['chain']['progress'] < .85 else None),
                     'Could not observe leave grace during the slow shared unfold')
        assert state['expanded'] and state['chain']['progress'] < 1, 'Leave timer folded a slow opening before it completed'
        assert state['dismissal']['timeout'] == 800, 'Animation speed changed the interaction grace period'
        assert not state['dismissal']['pending'], 'Leave grace started while icons were still unfolding'
        started = time.monotonic()
        session.pointer.button(True)
        session.pointer.button(False)
        wait(lambda: not session.dock()['expanded'], 'Outside click did not dismiss slow unfold immediately', timeout=.5)
        assert time.monotonic()-started < .5
        cycle.finish(False)
        print('PASS Slow opening completes before leave grace starts; outside click still dismisses immediately', flush=True)

        cycle, _ = begin(session)
        before = wait(lambda: (d if .12 <= (d := cycle.inspect())['chain']['progress'] < .35 else None),
                      'Could not catch a shared timeline before changing speed')
        configure('animationSpeed', 'ultrafast')
        after = cycle.inspect()
        assert after['chain']['progress'] >= before['chain']['progress']-.015 and after['chain']['progress'] > .05, \
            'Changing speed reset the shared unfold phase'
        cycle.finish(True)
        session.keys('-k', 'Escape')
        cycle.finish(False)
        print('PASS changing Slow to Ultrafast during shared unfolding preserves progress, actors and anchor', flush=True)

        for mode in ('reduced', 'off'):
            configure('animations', mode)
            for speed in ('slow', 'ultrafast'):
                configure('animationSpeed', speed)
                session.resting()
                cycle, _ = begin(session)
                state = cycle.finish(True)
                expected = 0 if mode == 'off' else 100/RATES[speed]
                near(state['animation']['duration'], expected, 'Actual accessible-mode reveal duration')
                assert all(a['rotation'] == 0 and a['scale'] == 1 and a['maxBend'] == 0 and a['maxTilt'] == 0
                           for a in state['actors']), 'Reduced/Off retained spatial transforms'
                wait(lambda: session.dock()['grabActive'], 'Accessible-mode fan did not receive keyboard focus')
                session.keys('-k', 'Escape')
                cycle.finish(False)
        configure('animations', 'full')
        print('PASS Reduced keeps motion-free fades and Off stays immediate at both speed extremes', flush=True)

        for speed in ('slow', 'ultrafast'):
            configure('animationSpeed', speed)
            for presentation in ('dock', 'bubbles', 'floating'):
                away(session)
                configure('presentation', presentation)
                session.resting()
                surface = session.surface()
                assert surface['motion']['speed'] == speed
                appearances = [i['appearance'] for i in surface['shelf']['icons']] if presentation == 'dock' else \
                    [i['appearance'] for i in surface['bubbles']] if presentation == 'bubbles' else \
                    [surface['floatingDock']['handle']['appearance']]
                assert appearances
                for appearance in appearances:
                    feedback(appearance, speed)
        print('PASS actual hover/press/opacity durations inherit the preset in all three presentations', flush=True)

        configure('presentation', 'dock')
        configure('animationSpeed', 'slow')
        configure('previewDelay', 250)
        configure('previewHideDelay', 200)
        away(session)
        configure('hoverPreview', 'still')
        session.resting()
        wait(lambda: not session.surface()['shelf']['animating'] and session.surface()['shelf']['progress'] == 1
             and all(i['appearance']['presence'] > .999 for i in session.surface()['shelf']['icons']),
             'Static preview sources did not finish appearing')
        record = records[-1]
        key = 'window:'+str(record.get('stableId') or record['id'])
        icon = wait(lambda: session.icon(key), 'Still preview source was missing')
        started = time.monotonic()
        session.move(icon['x']+icon['width']/2, icon['y']+icon['height']/2)
        time.sleep(.1)
        assert not session.surface()['preview']['opened'], 'Speed changed the configured hover delay'
        wait(lambda: session.surface()['preview']['opened'], 'Slow preview did not open')
        assert time.monotonic()-started >= .20
        value = wait(lambda: (p if (p := session.surface()['preview'])['image']['hasContent'] else None),
                     'Still preview capture did not become ready')
        near(value['fadeDuration'], 300, 'Slow preview fade duration')
        near(value['image']['fadeDuration'], 280, 'Slow thumbnail fade duration')
        assert value['animationSpeed'] == value['image']['animationSpeed'] == 'slow'
        assert shell('status')['settings']['previewDelay'] == 250 and shell('status')['settings']['previewHideDelay'] == 200
        configure('animationSpeed', 'ultrafast')
        value = session.surface()['preview']
        near(value['fadeDuration'], 60, 'Ultrafast preview fade duration')
        near(value['image']['fadeDuration'], 56, 'Ultrafast thumbnail fade duration')
        assert value['animationSpeed'] == value['image']['animationSpeed'] == 'ultrafast'
        configure('hoverPreview', 'off')
        wait(lambda: not session.surface()['preview']['rendered'] and not session.surface()['preview']['image']['captureActive'],
             'Disabled preview retained its capture')
        print('PASS preview/thumbnail fade presets and unchanged configured hover/hide delays', flush=True)
        assert not shell('status')['error'], shell('status')['error']


if __name__ == '__main__':
    main()
