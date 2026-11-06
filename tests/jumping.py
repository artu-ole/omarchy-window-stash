#!/usr/bin/env python3
"""Native Jumping fan choreography, reversal and accessibility checks.

Install this checkout first and run in an unlocked Hyprland session. The test
announces its five-second countdown and restores existing desktop state.
"""
import time

from desktop_test import desktop_test
from floating_panel import Cycle, begin, near, place
from live import configure, shell, wait
from matryoshka import select_native
from native_session import NativeSession


class JumpCycle(Cycle):
    def __init__(self, session):
        super().__init__(session)
        self.phases = set()
        self.deformed = set()
        self.lift = 0

    def inspect(self, dock, monotonic=None):
        super().inspect(dock, monotonic)
        assert dock['style'] == 'jumping', 'The selected profile was not applied'
        horizontal = dock['orientation'] == 'horizontal'
        sign = dock['fan']['sign']
        if horizontal:
            assert dock['fan']['curveSign'] == -1, 'Horizontal jump chose the bottom side'
        for actor in dock['actors']:
            stretch = actor['stretch']
            assert 0 < stretch['x'] <= 1 and 0 < stretch['y'] <= 1, ('Deformation escaped its tile', actor)
            assert actor['x'] >= self.area['x']-.01 and actor['y'] >= self.area['y']-.01
            assert actor['x']+actor['width'] <= self.area['x']+self.area['width']+.01
            assert actor['y']+actor['height'] <= self.area['y']+self.area['height']+.01
            if actor['ordinal'] == 0:
                near(stretch['x'], 1, 'The fixed front squashed horizontally')
                near(stretch['y'], 1, 'The fixed front squashed vertically')
                continue
            phase = actor['jumpPhase']
            self.phases.add(phase)
            if abs(stretch['x']-stretch['y']) > .025:
                self.deformed.add(phase)
            start_y = self.anchor[1]+min(actor['ordinal'], 2)*4
            # Recover travel from its longitudinal coordinate rather than
            # duplicating the staged easing equations used by the renderer.
            if horizontal:
                travel = (actor['x']-self.anchor[0])/(sign*actor['ordinal']*52)
                baseline = start_y+(self.anchor[1]-start_y)*travel
                lift = baseline-actor['y']
                assert lift >= -.02, ('Horizontal jump passed below its straight baseline', actor)
                limit = min(28, max(0, self.anchor[1]-self.area['y']-dock['panel']['inset']))
                assert lift <= limit+.02, ('Near-top jump exceeded its available lift', lift, limit)
            else:
                lift = abs(actor['x']-self.anchor[0])
            self.lift = max(self.lift, lift)
        return dock


def endpoint(session, expanded):
    dock = session.dock()
    horizontal = dock['orientation'] == 'horizontal'
    sign = dock['fan']['sign']
    for actor in dock['actors']:
        offset = actor['ordinal']*52 if expanded else 0
        near(actor['x'], dock['handle']['x']+(sign*offset if horizontal else 0), 'Jump missed its exact horizontal endpoint')
        near(actor['y'], dock['handle']['y']+(0 if horizontal else sign*offset)+
             (0 if expanded else min(actor['ordinal'], 2)*4), 'Jump missed its exact vertical endpoint')
        near(actor['stretch']['x'], 1, 'Horizontal deformation survived settling')
        near(actor['stretch']['y'], 1, 'Vertical deformation survived settling')


def full_cycle(session, sign, choreography=True):
    cycle = JumpCycle(session)
    begin(session)
    dock = cycle.watch(True, 1)
    assert dock['fan']['sign'] == sign, 'Fixture expanded in the wrong direction'
    endpoint(session, True)
    session.keys('-k', 'Escape')
    cycle.watch(False, -1)
    endpoint(session, False)
    if choreography:
        assert {'launch', 'flight', 'landing'} <= cycle.phases, ('Native frames skipped a jump stage', cycle.phases)
        assert {'launch', 'flight', 'landing'} <= cycle.deformed, ('Squash/stretch was absent from a stage', cycle.deformed)
        assert cycle.lift > 1, 'Jumping did not leave its straight path'
    return cycle


def reverse(session):
    cycle = JumpCycle(session)
    begin(session)

    def airborne():
        dock = cycle.inspect(session.dock())
        actor = next(a for a in dock['actors'] if a['ordinal'] == 1)
        return dock if actor['jumpPhase'] == 'flight' and .28 < actor['progress'] < .52 else None

    before = wait(airborne, 'Could not catch an icon in flight')
    started = time.monotonic()
    session.keys('-k', 'Escape')
    inverse = cycle.inspect(session.dock())
    elapsed = time.monotonic()-started
    assert not inverse['expanded'], 'Escape did not reverse the jump'
    assert next(a for a in inverse['actors'] if a['ordinal'] == 1)['progress'] > 0, 'Reversing reset the icon to the stack'
    for old, new in zip(before['actors'], inverse['actors']):
        assert abs(old['x']-new['x'])+abs(old['y']-new['y']) <= elapsed*1200+10, 'Reversal teleported an icon'
    r = inverse['handle']
    session.move(r['x']+24, r['y']+24)
    session.pointer.button(True)
    session.pointer.button(False)
    wait(lambda: session.dock()['expanded'], 'Click during folding did not reopen the fan')
    reopened = cycle.inspect(session.dock())
    assert next(a for a in reopened['actors'] if a['ordinal'] == 1)['progress'] > 0, 'Reopening reset the animation'
    cycle.watch(True)
    endpoint(session, True)
    session.keys('-k', 'Escape')
    cycle.watch(False)
    endpoint(session, False)
    print('PASS Jumping reverses and reopens in flight without moving the front or recreating icons', flush=True)


@desktop_test('Jumping floating dock animation test')
def main():
    with NativeSession() as session:
        for key, value in dict(presentation='floating', grouping='window', scope='workspace',
                               animations='full', animationSpeed='slow', hoverPreview='off',
                               dragMotion='physics', floatingPlacement='free', iconShape='square',
                               iconFrame='shown', dockFrame='shown', dockCorners='custom',
                               dockCornerRadius=64, dockOpacity=100, iconOpacity=100).items():
            configure(key, value)
        for _ in range(4):
            session.park(session.spawn(workspace=session.workspace)[0])
        session.resting()
        select_native(session, 'jumping')
        area = session.surface()['usableArea']
        for horizontal in (True, False):
            configure('floatingDirection', 'horizontal' if horizontal else 'vertical')
            for sign in (1, -1):
                x = area['x']+24 if sign > 0 else area['x']+area['width']-80
                y = area['y']+area['height']*.4
                if not horizontal:
                    x = area['x']+area['width']*(.4 if sign > 0 else .6)
                    y = area['y']+24 if sign > 0 else area['y']+area['height']-80
                place(session, x, y)
                full_cycle(session, sign)
        print('PASS native dropdown, both axes/directions, launch/flight/landing deformation, bounded icons and fixed panel', flush=True)
        configure('floatingDirection', 'horizontal')
        for sign in (1, -1):
            place(session, area['x']+24 if sign > 0 else area['x']+area['width']-80, area['y']+8)
            full_cycle(session, sign)
        print('PASS horizontal jumps stay upward and flatten near the reserved top edge in both directions', flush=True)
        place(session, area['x']+24, area['y']+area['height']*.4)
        reverse(session)
        configure('animationSpeed', 'ultrafast')
        full_cycle(session, 1, choreography=False)
        print('PASS Ultrafast keeps the same bounded path and exact endpoints', flush=True)
        for mode in ('reduced', 'off'):
            configure('animations', mode)
            cycle = full_cycle(session, 1, choreography=False)
            near(cycle.lift, 0, 'Accessibility mode reintroduced jumping')
            assert not cycle.deformed, 'Accessibility mode reintroduced squash/stretch'
        print('PASS Reduced/Off suppress jumps and deformation at both endpoints', flush=True)
    wait(lambda: not shell('status')['controllerBusy'] and not shell('status')['queueLength'], 'Native cleanup did not finish')


if __name__ == '__main__':
    main()
