#!/usr/bin/env python3
"""Native fixed-thickness floating panels, moving icons and input regression.

Install this checkout before running in an unlocked Hyprland session. Only
owned fixtures are used; NativeSession restores settings, stash and focus.
Pass --small-output to also check overflow on a temporary 320x240 output.
"""
import argparse
import json
import time

from desktop_test import desktop_test
from live import command, configure, h, shell, wait
from native_session import NativeSession


STYLES = ('arc', 'glide', 'cascade', 'spring', 'swing', 'matryoshka', 'matryoshka-hop', 'jumping')
CURVED = ('arc', 'spring', 'swing', 'matryoshka-hop')


def near(actual, expected, message, tolerance=.01):
    assert abs(actual-expected) <= tolerance, (message, actual, expected)


class Cycle:
    def __init__(self, session, identity=True):
        self.session = session
        dock = session.dock()
        self.area = session.surface()['usableArea']
        self.identity = identity
        self.anchor = (dock['handle']['x'], dock['handle']['y'])
        self.created = dock['createdIcons']
        self.keys = tuple(a['key'] for a in dock['actors'])
        self.cross = None
        self.radius = None
        self.samples = []
        self.escaped = False

    def inspect(self, dock, monotonic=None):
        assert dock['createdIcons'] == self.created, 'Panel motion recreated the icons'
        if self.identity:
            assert tuple(a['key'] for a in dock['actors']) == self.keys, 'Panel motion changed actor identity'
        front = next(a for a in dock['actors'] if a['ordinal'] == 0)
        near(front['x'], self.anchor[0], 'Panel motion shifted the front horizontally')
        near(front['y'], self.anchor[1], 'Panel motion shifted the front vertically')
        p = dock['panel']
        area = self.area
        assert p['x'] >= area['x']-.01 and p['y'] >= area['y']-.01, ('Panel escaped reserved edges', p, area)
        assert p['x']+p['width'] <= area['x']+area['width']+.01, ('Panel escaped right edge', p, area)
        assert p['y']+p['height'] <= area['y']+area['height']+.01, ('Panel escaped bottom edge', p, area)
        if not p['visible']:
            return dock
        horizontal = dock['orientation'] == 'horizontal'
        cross = (p['y'], p['height']) if horizontal else (p['x'], p['width'])
        target = p['targetHeight'] if horizontal else p['targetWidth']
        near(cross[1], target, 'Jumping icons changed the panel thickness')
        if self.cross is None:
            self.cross = cross
            self.radius = p['radius']
        near(cross[0], self.cross[0], 'Jumping icons moved the panel across its axis')
        near(cross[1], self.cross[1], 'Panel thickness pulsed during the cycle')
        near(p['radius'], self.radius, 'Jumping icons changed the panel corner radius', 1.01)
        length = p['width'] if horizontal else p['height']
        full = p['targetWidth'] if horizontal else p['targetHeight']
        assert 0 < length <= full+1.01, ('Panel length followed an icon overshoot', length, full)
        if self.samples and monotonic is not None:
            previous = self.samples[-1]
            assert monotonic*(length-previous) >= -1.01, ('Panel length rebounded', monotonic, previous, length, dock['style'])
        self.samples.append(length)
        if dock['animating']:
            for a in dock['actors']:
                if a['ordinal'] and .1 < a['progress'] < .9:
                    outside = a['y'] < p['y']-2 or a['y']+a['height'] > p['y']+p['height']+2 if horizontal else a['x'] < p['x']-2 or a['x']+a['width'] > p['x']+p['width']+2
                    self.escaped = self.escaped or outside
        return dock

    def watch(self, opened, monotonic=None, timeout=4):
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline:
            dock = self.inspect(self.session.dock(), monotonic)
            if dock['expanded'] == opened and not dock['animating'] and not dock['snapping']:
                return dock
            time.sleep(.002)
        raise AssertionError(('Floating panel did not settle', opened, self.session.dock()))


def begin(session):
    cycle = Cycle(session)
    r = session.dock()['handle']
    session.move(r['x']+23, r['y']+24)
    session.move(r['x']+24, r['y']+24)
    wait(lambda: session.dock()['handle']['appearance']['feedback']['hot'], 'Pointer did not reach the floating stack')
    session.pointer.button(True)
    wait(lambda: session.dock()['handle']['held'], 'Floating stack did not receive the press')
    session.pointer.button(False)
    wait(lambda: session.dock()['expanded'], 'Floating stack did not receive the release')
    return cycle


def collapse(session):
    cycle = Cycle(session)
    session.keys('-k', 'Escape')
    return cycle.watch(False, -1)


def place(session, x, y):
    session.resting()
    session.position('dock:floating', round(x), round(y))
    return session.dock()


class UpwardCycle(Cycle):
    """Compare horizontal artwork with its straight, tail-offset baseline."""

    def __init__(self, session):
        super().__init__(session)
        self.lift = 0

    def inspect(self, dock, monotonic=None):
        super().inspect(dock, monotonic)
        assert dock['fan']['curveSign'] == -1, 'Horizontal curve chose the bottom side'
        for actor in dock['actors']:
            if not actor['ordinal']:
                continue
            # Collapsed preview cards begin four/eight pixels below the front.
            # Test the bend independently of that existing stack silhouette.
            tail = actor['groupOffset'] if dock['style'] == 'matryoshka-hop' else min(actor['ordinal'], 2)*4*(1-actor['progress'])
            baseline = max(self.area['y'], min(self.area['y']+self.area['height']-actor['height'], self.anchor[1]+tail))
            lift = baseline-actor['y']
            assert lift >= -.01, ('Horizontal animation arched downward', dock['style'], dock['fan']['sign'], actor)
            limit = min(28 if dock['style'] == 'matryoshka-hop' else 18,
                        max(0, self.anchor[1]-self.area['y']-dock['panel']['inset']))
            assert lift <= limit+.01, ('Arch exceeded the space above the stack', lift, limit)
            self.lift = max(self.lift, lift)
        return dock


def horizontal_arcs(session):
    original = session.dock()['handle']
    configure('floatingDirection', 'horizontal')
    area = session.surface()['usableArea']
    for near_top in (False, True):
        y = area['y']+8 if near_top else area['y']+area['height']*.4
        for sign in (1, -1):
            x = area['x']+24 if sign > 0 else area['x']+area['width']-80
            for style in CURVED:
                configure('floatingAnimation', style)
                place(session, x, y)
                cycle = UpwardCycle(session)
                begin(session)
                dock = cycle.watch(True, 1)
                assert dock['fan']['sign'] == sign, 'Fixture expanded in the wrong direction'
                session.keys('-k', 'Escape')
                cycle.watch(False, -1)
                assert cycle.lift > 1, ('No upward arch was observed', style, sign, near_top)
                for actor in session.dock()['actors']:
                    near(actor['x'], cycle.anchor[0], 'Folding missed the stack horizontally')
                    near(actor['y'], cycle.anchor[1]+min(actor['ordinal'], 2)*4, 'Folding lost its stack offset')
        print('PASS all four horizontal curves arch upward left/right through unfold/fold '+
              ('near the reserved top edge' if near_top else 'with space above'), flush=True)
    place(session, original['x'], original['y'])


def reversal(session):
    cycle = begin(session)
    wait(lambda: cycle.inspect(session.dock())['chain']['progress'] > .3, 'No intermediate unfold frame')
    assert session.dock()['chain']['progress'] < .85, 'Missed the unfold reversal interval'
    session.keys('-k', 'Escape')
    inverse = cycle.inspect(session.dock())
    assert not inverse['expanded'] and inverse['chain']['progress'] > .05, 'Reversing snapped to the collapsed endpoint'
    session.move(cycle.anchor[0]+24, cycle.anchor[1]+24)
    session.pointer.button(True)
    session.pointer.button(False)
    reopened = cycle.inspect(session.dock())
    assert reopened['expanded'] and reopened['chain']['progress'] > .01, 'Reopening restarted the background'
    cycle.watch(True)
    collapse(session)


def airborne_restore(session, records):
    configure('floatingAnimation', 'arc')
    configure('floatingDirection', 'horizontal')
    configure('dockCornerRadius', 0)
    session.resting()
    cycle = begin(session)
    selected = None
    deadline = time.monotonic()+2
    while time.monotonic() < deadline:
        dock = cycle.inspect(session.dock())
        panel = dock['panel']
        for actor in reversed(dock['actors']):
            if not actor.get('interactive') or not .855 < actor['progress'] < .92:
                continue
            top = panel['y']-actor['y']
            bottom = actor['y']+actor['height']-panel['y']-panel['height']
            if max(top, bottom) < 3:
                continue
            x = actor['x']+actor['width']/2
            y = panel['y']-1.5 if top > bottom else panel['y']+panel['height']+1.5
            selected = actor['key']
            session.move(x, y)
            # Pointer.click deliberately waits 50 ms before pressing, which
            # would miss this short, already-interactive airborne interval.
            session.pointer.button(True)
            session.pointer.button(False)
            break
        if selected:
            break
        time.sleep(.001)
    assert selected, 'No interactive airborne icon extended outside the straight panel'
    record = next(r for r in records if 'window:'+str(r.get('stableId') or r['id']) == selected)
    wait(lambda: all(w['id'] != record['id'] for w in command('list')['windows']), 'Clicking an airborne icon was treated as an outside click')
    remaining = {w['id'] for w in command('list')['windows']}
    assert {r['id'] for r in records if r['id'] != record['id']} <= remaining, 'Airborne click restored another fixture'
    session.resting()
    replacement = session.park(record['address'])
    records[records.index(record)] = replacement
    session.resting()


def overflow(session):
    outputs = {m['name'] for m in h.read('monitors')}
    h.call('output', 'create', 'headless')
    monitor = wait(lambda: next((m for m in h.read('monitors') if m['name'] not in outputs), None), 'Temporary output missing')
    session.outputs.append(monitor['name'])
    right = max(m['x']+round(m['width']/m['scale']) for m in h.read('monitors') if m['name'] != monitor['name'])
    h.eval('hl.monitor({output=%s,mode="320x240@60",position=%s,scale=1})' % (json.dumps(monitor['name']), json.dumps('%dx0' % right)))
    session.monitor = next(m for m in h.read('monitors') if m['name'] == monitor['name'])
    h.dispatch('focus', monitor=monitor['name'])
    workspace = session.workspace+3
    h.dispatch('focus', workspace=str(workspace))
    wait(lambda: session.monitor['name'] in shell('status')['screens'], 'Temporary output has no shell surface')
    addresses = [session.spawn(workspace=workspace)[0] for _ in range(6)]
    for address in addresses:
        session.park(address)
    configure('animations', 'full')
    configure('floatingAnimation', 'matryoshka-hop')
    for direction in ('horizontal', 'vertical'):
        configure('floatingDirection', direction)
        area = session.surface()['usableArea']
        place(session, area['x']+12, area['y']+12)
        dock = begin(session).watch(True, 1)
        assert 1 < dock['capacity'] < len(addresses), 'Temporary output did not overflow'
        cycle = Cycle(session)
        axis = 'Right' if dock['fan']['sign'] > 0 else 'Left'
        if direction == 'vertical':
            axis = 'Down' if dock['fan']['sign'] > 0 else 'Up'
        session.keys(*(['-k', axis]*len(addresses)))
        paged = cycle.watch(True)
        assert paged['firstIndex'] > 0, 'Keyboard navigation did not advance the overflow page'
        collapse(session)
    # Removing an owned parked fixture may shrink the length but cannot alter
    # the rail's cross-axis geometry or recreate the remaining icons.
    configure('floatingDirection', 'horizontal')
    begin(session).watch(True, 1)
    cycle = Cycle(session, identity=False)
    h.dispatch('window.close', window='address:'+addresses[0])
    wait(lambda: not h.client(addresses[0]), 'Owned removal fixture did not close')
    shell('refresh')
    # Refresh queues the controller snapshot; wait for it before observing
    # retirement so the next collapse does not overlap this deliberate removal.
    wait(lambda: session.dock()['groups'] == len(addresses)-1, 'Owned removal did not reach the dock')
    cycle.watch(True)
    collapse(session)
    print('PASS small-output bounds, overflow paging and source removal retain the straight panel', flush=True)


@desktop_test('Floating dock background geometry test')
def main(small=False):
    with NativeSession() as session:
        for key, value in dict(presentation='floating', grouping='window', scope='workspace',
                               animations='full', animationSpeed='slow', hoverPreview='off',
                               dragMotion='physics', floatingPlacement='free', iconShape='square',
                               iconFrame='shown', dockFrame='shown', dockCorners='custom',
                               dockCornerRadius=64, dockOpacity=100, iconOpacity=100).items():
            configure(key, value)
        records = [session.park(session.spawn(workspace=session.workspace)[0]) for _ in range(4)]
        session.resting()
        area = session.surface()['usableArea']
        center = (area['x']+area['width']*.4, area['y']+area['height']*.4)
        place(session, *center)
        for style in STYLES:
            configure('floatingAnimation', style)
            for direction in ('horizontal', 'vertical'):
                configure('floatingDirection', direction)
                session.resting()
                cycle = begin(session)
                dock = cycle.watch(True, 1)
                assert len(set(cycle.samples)) >= 3, 'Background skipped gradual length growth'
                if style in CURVED:
                    bends = [a['maxBend'] for a in dock['actors']]
                    assert any(bend > 1 for bend in bends), ('Fixed panel suppressed curved icon motion', style, direction, cycle.escaped, bends)
                    # Spring's four-pixel bend may fit within normal panel
                    # padding. The larger curves must visibly leave the rail.
                    if style != 'spring':
                        assert cycle.escaped, ('Larger icon curve stayed inside the thin panel', style, direction, cycle.escaped, bends)
                collapse(session)
            print('PASS '+style+' fixed thickness, stable corners, gradual length and unclipped jumps in both axes', flush=True)

        configure('floatingAnimation', 'matryoshka-hop')
        for direction in ('horizontal', 'vertical'):
            configure('floatingDirection', direction)
            session.resting()
            reversal(session)
            place(session, area['x']+area['width']-72, area['y']+area['height']-80)
            dock = begin(session).watch(True, 1)
            assert dock['fan']['sign'] == -1, 'Edge placement did not exercise negative expansion'
            collapse(session)
            place(session, *center)
        print('PASS interrupted unfold/fold reversal, negative expansion and work-area bounds', flush=True)

        horizontal_arcs(session)
        airborne_restore(session, records)
        print('PASS an interactive jumping icon outside the thin background restores its own window', flush=True)
        configure('dockCornerRadius', 64)
        for mode in ('reduced', 'off'):
            configure('animations', mode)
            for direction in ('horizontal', 'vertical'):
                configure('floatingDirection', direction)
                session.resting()
                begin(session).watch(True, 1)
                collapse(session)
        configure('animations', 'full')
        configure('dockFrame', 'hidden')
        configure('floatingAnimation', 'matryoshka-hop')
        session.resting()
        dock = begin(session).watch(True, 1)
        assert not dock['panel']['frameVisible']
        collapse(session)
        configure('dockFrame', 'shown')
        print('PASS Reduced/Off and hidden background preserve geometry and input behavior', flush=True)
        if small:
            overflow(session)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--small-output', action='store_true')
    main(parser.parse_args().small_output)
