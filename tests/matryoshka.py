#!/usr/bin/env python3
"""Native nested-stack motion, interruption, input, and accessibility regression.

Run from an unlocked Hyprland session after installing this checkout. The suite
uses disposable windows and NativeSession restores the existing desktop state.
Pass --small-output to also exercise overflow on a temporary 320x240 output.
"""
import argparse
import json
import math
import time

from desktop_test import desktop_test
from live import command, configure, h, shell, wait
from native_session import KEYBOARD_SETTLE_SECONDS, NativeSession


STYLES = ('matryoshka', 'matryoshka-hop')
ALL_STYLES = ('arc', 'glide', 'cascade', 'spring', 'swing', *STYLES, 'jumping')
EPSILON = .08


def ordered(dock):
    return sorted(dock['actors'], key=lambda actor: actor['ordinal'])


def close_to(actual, expected, message, tolerance=EPSILON):
    assert abs(actual-expected) <= tolerance, (message, actual, expected)


class Cycle:
    """Observe actual actors throughout a shared-clock unfold or inverse fold."""

    def __init__(self, session):
        self.t = session
        dock = session.dock()
        self.created = dock['createdIcons']
        self.keys = tuple(a['key'] for a in ordered(dock))
        self.first_index = dock['firstIndex']
        self.full = shell('status')['settings']['animations'] == 'full'
        self.front = ordered(dock)[0]
        self.anchor = (self.front['x'], self.front['y'])
        self.samples = []
        self.group_stages = set()
        self.deposited_stages = set()
        self.actual_bend = 0

    def inspect(self, dock):
        actors = ordered(dock)
        assert dock['createdIcons'] == self.created, 'An unfold/fold recreated delegates'
        assert tuple(a['key'] for a in actors) == self.keys, 'Actor identity/order changed during a cycle'
        assert len(set(self.keys)) == len(self.keys), 'An actor was duplicated'
        close_to(actors[0]['x'], self.anchor[0], 'The original front moved horizontally', .001)
        close_to(actors[0]['y'], self.anchor[1], 'The original front moved vertically', .001)
        close_to(dock['handle']['x'], self.anchor[0], 'Opening changed the stored horizontal anchor', .001)
        close_to(dock['handle']['y'], self.anchor[1], 'Opening changed the stored vertical anchor', .001)
        if dock['style'] not in STYLES:
            return dock

        chain = dock['chain']
        if chain['moving'] or dock['expanded']:
            assert dock['firstIndex'] == self.first_index, 'The visible page changed during a shared-clock cycle'
        count = chain['count']
        progress = chain['progress']
        assert 0 <= progress <= 1, chain
        assert 1 <= count <= len(actors), chain
        stage = min(count-1, math.floor(progress*max(0, count-1)))
        assert chain['stage'] == stage, ('Shared clock reported the wrong stage', chain)
        visible = actors[self.first_index:self.first_index+count]
        horizontal = dock['orientation'] == 'horizontal'
        sign = dock['fan']['sign']
        for index, actor in enumerate(visible):
            assert actor['ordinal'] == self.first_index+index, ('Actor lost its original ordinal', actor)
            assert actor['poseStage'] == stage, ('Actors used different chain stages', actor, chain)
            if self.full:
                close_to(actor['progress'], progress, 'Actors did not share one clock', .0001)
            assert -.001 <= actor['groupOffset'] <= 8.001, actor
            if index <= stage:
                assert actor['poseSettled'], ('A deposited actor was still moving', actor, chain)
                close_to(actor['x'], self.anchor[0]+(index*sign*52 if horizontal else 0), 'Deposited icon shifted horizontally')
                close_to(actor['y']-actor['groupOffset'], self.anchor[1]+(0 if horizontal else index*sign*52), 'Deposited icon shifted vertically')
                close_to(actor['chainSlot'], index, 'Deposited icon lost its slot')
            else:
                assert stage-.001 <= actor['chainSlot'] <= stage+1.001, ('Remaining stack skipped a cell', actor, chain)

        if 0 < progress < 1:
            self.samples.append(progress)
            moving = visible[stage+1:]
            if len(moving) >= 2:
                # Preview offsets stay vertical even for a vertical fan. Remove
                # them to compare the actual common position of the group.
                base_x = moving[0]['x']
                base_y = moving[0]['y']-moving[0]['groupOffset']
                for actor in moving[1:]:
                    close_to(actor['x'], base_x, 'The remaining group split horizontally')
                    close_to(actor['y']-actor['groupOffset'], base_y, 'The remaining group split vertically')
                    close_to(actor['chainSlot'], moving[0]['chainSlot'], 'Remaining icons used separate travel phases')
                bend = abs(base_y-self.anchor[1]) if horizontal else abs(base_x-self.anchor[0])
                self.actual_bend = max(self.actual_bend, bend)
                if dock['style'] == 'matryoshka':
                    close_to(bend, 0, 'The straight nested stack curved')
                self.group_stages.add(stage)
                if stage:
                    self.deposited_stages.add(stage)
        return dock

    def watch(self, opened, timeout=4):
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline:
            dock = self.inspect(self.t.dock())
            if dock['expanded'] == opened and not dock['animating'] and not dock['snapping']:
                assert not dock.get('chain', {}).get('moving', False), 'Chain kept running after settling'
                return dock
            time.sleep(.002)
        raise AssertionError(('Nested-stack cycle did not settle', opened, self.t.dock()))

    def assert_motion(self, dock):
        assert len(self.samples) >= 2, 'No intermediate shared-clock frames were observed'
        assert len(self.group_stages) >= 2 and self.deposited_stages, (
            'Did not observe a group depositing an icon and carrying the remainder onward',
            sorted(self.group_stages), len(self.samples))
        if dock['style'] == 'matryoshka-hop':
            assert self.actual_bend > 1, 'The nested stack did not make a visible arch'
            assert any(a['maxBend'] > 1 for a in dock['actors'][1:]), 'Hop was absent from actor frame metrics'
        else:
            assert all(a['maxBend'] == 0 for a in dock['actors']), 'The straight style recorded a curved frame'


def select_native(session, style):
    from settings_fit import reveal

    shell('settings')
    wait(lambda: session.surface()['dialog']['visible'], 'Settings did not open')

    def control():
        return next(c for c in session.surface()['settingControls'] if c['key'] == 'floatingAnimation')

    session.click(reveal(session, lambda: control()['rect']))
    wait(lambda: control()['open'], 'Unfold animation dropdown did not open')
    # Omarchy's dropdown handles arrows rather than Home/End.
    session.keys(*(['-k', 'Up']*len(ALL_STYLES)),
                 *(['-k', 'Down']*ALL_STYLES.index(style)), '-k', 'Return')
    try:
        wait(lambda: shell('status')['settings']['floatingAnimation'] == style,
             'Native dropdown did not save '+style)
    except AssertionError as exc:
        status = shell('status')
        raise AssertionError(('Native unfold selection was not saved', style,
                              {'control': control(), 'saved': status['settings'].get('floatingAnimation'),
                               'error': status.get('error', '')})) from exc
    shell('dismiss')
    session.resting()


def begin(session, offset=0):
    cycle = Cycle(session)
    handle = session.dock()['handle']
    x = handle['x']+24+offset
    y = handle['y']+24-offset
    session.move(x-1, y)
    session.pointer.click(*session.point(x, y))
    return cycle, (x, y)


def expand(session, offset=0, motion=True):
    cycle, pointer = begin(session, offset)
    dock = cycle.watch(True)
    front = ordered(dock)[0]
    assert front['x'] <= pointer[0] <= front['x']+front['width']
    assert front['y'] <= pointer[1] <= front['y']+front['height']
    assert dock['currentIndex'] == 0, 'Newest actor was not immediately selected'
    if motion:
        cycle.assert_motion(dock)
    return dock


def collapse(session, motion=True):
    cycle = Cycle(session)
    session.keys('-k', 'Escape')
    dock = cycle.watch(False)
    for index, actor in enumerate(ordered(dock)):
        close_to(actor['x'], dock['handle']['x'], 'Actor did not return to the stack')
        close_to(actor['y'], dock['handle']['y']+min(index, 2)*4, 'Actor lost its collapsed preview offset')
    if motion:
        cycle.assert_motion(dock)
    return dock


def place(session, placement, x, y):
    # Free placement permits an exact seed; edge mode then uses the actual
    # settled physics-world anchor rather than assuming a particular edge.
    configure('floatingPlacement', 'free')
    session.resting()
    session.position('dock:floating', round(x), round(y))
    if placement == 'edges':
        configure('floatingPlacement', 'edges')
        session.resting()


def interruption(session):
    cycle, _ = begin(session, 11)
    deadline = time.monotonic()+2
    before = None
    while time.monotonic() < deadline:
        dock = cycle.inspect(session.dock())
        if .56 <= dock['chain']['progress'] < .85 and dock['chain']['moving']:
            before = dock
            break
    assert before, 'Could not sample a nested stack before reversing it'
    started = time.monotonic()
    session.keys('-k', 'Escape')
    after = cycle.inspect(session.dock())
    elapsed = time.monotonic()-started
    # The shared keyboard driver deliberately waits before and after injection.
    # Keep the IPC budget separate from those fixed waits; pose continuity below
    # still uses the full wall time during which the animation really advanced.
    ipc_elapsed = elapsed-2*KEYBOARD_SETTLE_SECONDS
    assert ipc_elapsed < .2, ('IPC was too slow to inspect an interrupted frame', ipc_elapsed, elapsed)
    assert after['chain']['progress'] > .1, 'Escape reset the shared clock instead of reversing it'
    assert after['chain']['progress'] <= before['chain']['progress']+.12, 'Escape advanced or reset the fold phase'
    for old, new in zip(ordered(before), ordered(after)):
        assert math.hypot(new['x']-old['x'], new['y']-old['y']) <= 1200*elapsed+10, (
            'Escape teleported an icon instead of preserving the current pose', old, new, elapsed)
    # Reopen while the inverse chain is still running. A new click must keep
    # the front fixed and continue using the same actors and shared phase.
    handle = after['handle']
    session.move(handle['x']+24, handle['y']+24)
    session.pointer.button(True)
    session.pointer.button(False)
    reopened = cycle.inspect(session.dock())
    assert reopened['expanded'], 'Click during inverse folding did not reopen the stack'
    assert reopened['chain']['progress'] > 0, 'Reopening restarted the nested stack from zero'
    cycle.watch(True)
    collapse(session)


def source_removal(session, address):
    record = next(w for w in command('list')['windows'] if w['address'] == address)
    removed_key = 'window:'+str(record.get('stableId') or record['id'])
    cycle, _ = begin(session)
    assert cycle.keys[-1] == removed_key and cycle.keys[0] != removed_key, 'Removal fixture was not the oldest actor'
    deadline = time.monotonic()+2
    while time.monotonic() < deadline:
        dock = cycle.inspect(session.dock())
        if .16 <= dock['chain']['progress'] < .4 and dock['chain']['moving']:
            break
    else:
        raise AssertionError('Could not catch the nested stack before source removal')

    # This address belongs to a fixture created by this NativeSession. Closing
    # it changes the source model while the presentation must keep its actors.
    assert address in session.addresses, 'Refusing to close an unowned fixture'
    h.dispatch('window.close', window='address:'+address)
    shell('refresh')
    source_samples = 0
    deadline = time.monotonic()+3
    while time.monotonic() < deadline:
        dock = session.dock()
        if not dock['chain']['moving']:
            break
        cycle.inspect(dock)
        if dock['groups'] == len(cycle.keys)-1:
            source_samples += 1
            assert removed_key in {a['key'] for a in dock['actors']}, 'Source removal retired a held actor early'
        time.sleep(.002)
    else:
        raise AssertionError('Source removal prevented the shared timeline from completing')
    assert source_samples, 'No running frame showed the changed source with the original held presentation'

    # Reconciliation can now retire/reflow actors. Do not apply the old-cycle
    # front/ordinal assertions after that boundary. Check final client/ledger
    # removal here so those separate IPC reads do not consume the running-frame
    # observation interval above.
    wait(lambda: not h.client(address), 'The disposable removal fixture did not close')
    assert all(w['address'] != address for w in command('list')['windows']), 'Closed source record was not reconciled'
    session.resting()
    final = session.dock()
    assert final['groups'] == len(cycle.keys)-1
    assert tuple(a['key'] for a in ordered(final)) == cycle.keys[:-1], 'Completed chain did not reconcile the removed source'
    assert final['createdIcons'] == cycle.created, 'Removing a source recreated surviving actors'
    collapse(session)


def front_reflow(session, address):
    record = next(w for w in command('list')['windows'] if w['address'] == address)
    removed_key = 'window:'+str(record.get('stableId') or record['id'])
    dock = expand(session)
    actors = ordered(dock)
    keys = tuple(a['key'] for a in actors)
    assert keys[0] == removed_key, 'Front-removal fixture was not the newest actor'
    assert address in session.addresses, 'Refusing to close an unowned fixture'
    successor_key = keys[1]
    anchor = (dock['handle']['x'], dock['handle']['y'])
    old_slot = (actors[1]['x'], actors[1]['y'])
    dx, dy = old_slot[0]-anchor[0], old_slot[1]-anchor[1]
    distance_squared = dx*dx+dy*dy
    assert distance_squared > 1, 'Successor already occupied the front anchor'
    created = dock['createdIcons']
    h.dispatch('window.close', window='address:'+address)
    shell('refresh')
    deadline = time.monotonic()+3
    became_front = None
    intermediate = False
    while time.monotonic() < deadline:
        dock = session.dock()
        assert dock['createdIcons'] == created, 'Removing the front recreated surviving actors'
        close_to(dock['handle']['x'], anchor[0], 'Front removal changed the stored horizontal anchor', .001)
        close_to(dock['handle']['y'], anchor[1], 'Front removal changed the stored vertical anchor', .001)
        successor = next(a for a in dock['actors'] if a['key'] == successor_key)
        if successor['ordinal'] == 0:
            if became_front is None:
                became_front = time.monotonic()
            fraction = ((successor['x']-anchor[0])*dx+(successor['y']-anchor[1])*dy)/distance_squared
            assert -.002 <= fraction <= 1.002, ('Successor overshot its reflow path', successor, fraction)
            close_to(successor['x'], anchor[0]+fraction*dx, 'Successor left its reflow path')
            close_to(successor['y'], anchor[1]+fraction*dy, 'Successor left its reflow path')
            if .02 < fraction < .98 and time.monotonic()-became_front <= .2:
                intermediate = True
        if dock['groups'] == len(keys)-1 and not dock['animating'] and not dock['snapping']:
            break
        time.sleep(.002)
    else:
        raise AssertionError('Removing the fully unfolded front did not settle')
    assert intermediate, 'New front snapped from its old slot instead of reflowing through an intermediate pose'
    session.resting()
    final = session.dock()
    assert tuple(a['key'] for a in ordered(final)) == keys[1:], 'Front removal changed the surviving actor order'
    assert final['createdIcons'] == created
    front = ordered(final)[0]
    close_to(front['x'], anchor[0], 'Replacement front did not reach the horizontal anchor')
    close_to(front['y'], anchor[1], 'Replacement front did not reach the vertical anchor')
    assert not h.client(address), 'The disposable front fixture did not close'
    # Closing an external client can clear layer keyboard focus in Hyprland.
    # An outside click also verifies the dock remains usable after reflow.
    cycle = Cycle(session)
    area = session.surface()['usableArea']
    x = area['x']+8 if anchor[0] > area['x']+area['width']/2 else area['x']+area['width']-8
    y = area['y']+8 if anchor[1] > area['y']+area['height']/2 else area['y']+area['height']-8
    session.move(x-1, y)
    session.pointer.click(*session.point(x, y))
    cycle.watch(False)


def overflow_reversal(session):
    previous_speed = shell('status')['settings']['animationSpeed']
    configure('animationSpeed', 'slow')
    try:
        session.resting()
        # Position the pointer before starting the short inverse timeline.
        # Reopening then needs only the two native button events, without a
        # monitor query or pointer move consuming the remaining fold budget.
        handle = session.dock()['handle']
        session.move(handle['x']+handle['width']/2, handle['y']+handle['width']/2)
        cycle = Cycle(session)
        page = cycle.first_index
        assert page > 0, 'Overflow reversal requires a nonzero page'
        session.keys('-k', 'Escape')
        deadline = time.monotonic()+2
        before = None
        sample_elapsed = 0
        while time.monotonic() < deadline:
            sampled = time.monotonic()
            dock = cycle.inspect(session.dock())
            sample_elapsed = time.monotonic()-sampled
            if 0 < dock['chain']['progress'] < .95 and dock['chain']['moving']:
                before = dock
                break
        assert before, 'Could not observe a partial nonzero-page fold at Slow speed'
        closing_seconds = before['animation']['duration']/1000
        assert closing_seconds > 0, 'Partial inverse chain reported no animation budget'
        started = time.monotonic()
        session.pointer.button(True)
        session.pointer.button(False)
        after = cycle.inspect(session.dock())
        elapsed = time.monotonic()-started
        assert after['expanded'] and after['firstIndex'] == page, 'Interrupted reopening reset the overflow page'
        assert after['chain']['progress'] > 0, 'Interrupted overflow reopening reset the shared clock'
        opening_seconds = after['animation']['duration']/1000
        phase_budget = (elapsed+sample_elapsed)/min(closing_seconds, opening_seconds)+.06
        assert abs(after['chain']['progress']-before['chain']['progress']) <= phase_budget, \
            ('Overflow reversal jumped to a new animation phase', before['chain'], after['chain'], phase_budget)
        area = session.surface()['usableArea']
        for old, new in zip(ordered(before), ordered(after)):
            assert math.hypot(new['x']-old['x'], new['y']-old['y']) <= 1200*elapsed+10, (
                'Reopening the overflow page teleported an actor', old, new, elapsed)
            assert new['x'] >= area['x']-.01 and new['y'] >= area['y']-.01 \
                and new['x']+new['width'] <= area['x']+area['width']+.01 \
                and new['y']+new['height'] <= area['y']+area['height']+.01, 'Interrupted actor escaped the work area'
        reopened = cycle.watch(True)
        assert reopened['firstIndex'] == page, 'The overflow page changed after reopening settled'
        session.keys('-k', 'Escape')
        session.resting()
    finally:
        configure('animationSpeed', previous_speed)


def interaction(session, under, title):
    dock = expand(session)
    wait(lambda: shell('status')['clickObserverActive'], 'Outside-click observer did not arm')
    client = h.client(under)
    left = client['at'][0]-session.monitor['x']
    top = client['at'][1]-session.monitor['y']
    panel = dock['panel']
    candidates = [(left+client['size'][0]*u, top+client['size'][1]*v)
                  for u, v in ((.25, .25), (.75, .25), (.25, .75), (.75, .75))]
    point = next(((x, y) for x, y in candidates
                  if not (panel['x']-8 <= x <= panel['x']+panel['width']+8
                          and panel['y']-8 <= y <= panel['y']+panel['height']+8)), None)
    assert point, 'The fixture has no unobstructed point outside the expanded stack'
    x, y = point
    session.move(x, y)
    wait(lambda: session.dock()['dismissal']['pending'], 'Pointer leave did not arm the grace timer')
    time.sleep(.15)
    assert session.dock()['expanded'], 'Pointer leave folded the stack before the grace period'
    front = ordered(session.dock())[0]
    session.move(front['x']+24, front['y']+24)
    wait(lambda: not session.dock()['dismissal']['pending'], 'Re-entry did not cancel the grace timer')
    time.sleep(.85)
    assert session.dock()['expanded'], 'A cancelled grace timer still folded the stack'
    session.move(x, y)
    started = time.monotonic()
    session.pointer.button(True)
    time.sleep(.02)
    session.pointer.button(False)
    wait(lambda: not session.dock()['expanded'], 'Outside click did not fold immediately', timeout=.5)
    assert time.monotonic()-started < .5
    assert session.dock()['lastDismissal'] == 'outside-click'
    wait(lambda: h.client(under)['title'] == title+' clicked', 'The outside click did not reach the application')
    session.resting()
    expand(session)
    h.dispatch('focus', workspace=str(session.workspace+1))
    wait(lambda: not session.dock()['expanded'], 'Workspace interaction did not dismiss the stack')
    h.dispatch('focus', workspace=str(session.workspace))
    session.resting()


def reduced_motion(session):
    for mode in ('reduced', 'off'):
        configure('animations', mode)
        for style in ALL_STYLES:
            configure('floatingAnimation', style)
            session.resting()
            cycle, _ = begin(session, 7)
            immediate = cycle.inspect(session.dock())
            if style in STYLES:
                assert immediate['chain']['progress'] == 1 and not immediate['chain']['moving'], (
                    'Reduced/Off interpolated the spatial chain', mode, style, immediate['chain'])
            dock = cycle.watch(True)
            horizontal = dock['orientation'] == 'horizontal'
            for index, actor in enumerate(ordered(dock)):
                close_to(actor['x'], dock['handle']['x']+(index*dock['fan']['sign']*52 if horizontal else 0), 'Reduced/Off icon missed its slot')
                close_to(actor['y'], dock['handle']['y']+(0 if horizontal else index*dock['fan']['sign']*52), 'Reduced/Off icon missed its slot')
                assert actor['maxBend'] == 0 and actor['maxTilt'] == 0 and actor['rotation'] == 0 and actor['scale'] == 1, (
                    'Reduced/Off retained a spatial transform', mode, style, actor)
            cycle = Cycle(session)
            session.keys('-k', 'Escape')
            immediate = cycle.inspect(session.dock())
            if style in STYLES:
                assert immediate['chain']['progress'] == 0 and not immediate['chain']['moving'], (
                    'Reduced/Off interpolated the inverse chain', mode, style, immediate['chain'])
            cycle.watch(False)
    print('PASS Reduced/Off use immediate spatial endpoints for all seven profiles', flush=True)


def small_output(session):
    outputs = {m['name'] for m in h.read('monitors')}
    h.call('output', 'create', 'headless')
    monitor = wait(lambda: next((m for m in h.read('monitors') if m['name'] not in outputs), None), 'Temporary output did not appear')
    session.outputs.append(monitor['name'])
    right = max(m['x']+round(m['width']/m['scale']) for m in h.read('monitors') if m['name'] != monitor['name'])
    h.eval('hl.monitor({output=%s,mode="320x240@60",position=%s,scale=1})' % (
        json.dumps(monitor['name']), json.dumps('%dx0' % right)))
    session.monitor = next(m for m in h.read('monitors') if m['name'] == monitor['name'])
    h.dispatch('focus', monitor=monitor['name'])
    workspace = session.workspace+3
    h.dispatch('focus', workspace=str(workspace))
    wait(lambda: session.monitor['name'] in shell('status')['screens'], 'Temporary output has no surface')
    for _ in range(7):
        session.park(session.spawn(workspace=workspace)[0])
    h.dispatch('focus', monitor=monitor['name'])
    h.dispatch('focus', workspace=str(workspace))
    configure('animations', 'full')
    for style in STYLES:
        configure('floatingAnimation', style)
        for direction in ('horizontal', 'vertical'):
            configure('floatingDirection', direction)
            session.resting()
            area = session.surface()['usableArea']
            place(session, 'free', area['x']+10, area['y']+10)
            h.dispatch('focus', monitor=monitor['name'])
            cycle, _ = begin(session)
            dock = cycle.watch(True)
            assert 1 < dock['capacity'] < 7, ('Small output did not exercise overflow', dock['capacity'])
            panel = dock['panel']
            assert panel['x'] >= 0 and panel['y'] >= 0
            assert panel['x']+panel['width'] <= session.surface()['width']+.1
            assert panel['y']+panel['height'] <= session.surface()['height']+.1
            key = ('Right' if dock['fan']['sign'] > 0 else 'Left') if direction == 'horizontal' else ('Down' if dock['fan']['sign'] > 0 else 'Up')
            wait(lambda: session.dock()['grabActive'], 'Temporary output did not receive keyboard focus: '+style+' '+direction)
            session.keys(*(['-k', key]*6))
            try:
                wait(lambda: session.dock()['firstIndex'] > 0, 'Overflow icons were not keyboard-accessible')
            except AssertionError:
                state = session.dock()
                print('Overflow keyboard diagnostics:', style, direction,
                      {k: state[k] for k in ('expanded', 'grabActive', 'currentIndex', 'firstIndex', 'capacity', 'fan', 'lastDismissal')}, flush=True)
                raise
            overflow_reversal(session)
            close_to(ordered(session.dock())[0]['x'], cycle.anchor[0], 'Overflow moved the original icon')
            close_to(ordered(session.dock())[0]['y'], cycle.anchor[1], 'Overflow moved the original icon')
    print('PASS nested stacks stay bounded, expose overflow and preserve a nonzero page through interrupted folding on a 320x240 output', flush=True)


@desktop_test('Matryoshka nested-stack animation test')
def main(with_small_output=False):
    with NativeSession() as session:
        configure('sizePreset', '100')
        # These functional checks observe shared intermediate frames across
        # controller, compositor and shell IPC. Timing/profile scaling is
        # covered separately; Slow keeps the real animation observable here.
        configure('animationSpeed', 'slow')
        configure('hoverPreview', 'off')
        configure('presentation', 'floating')
        configure('grouping', 'window')
        configure('scope', 'workspace')
        configure('floatingPlacement', 'free')
        configure('animations', 'full')
        configure('iconShape', 'square')
        configure('iconFrame', 'shown')
        configure('dockFrame', 'shown')
        configure('dockCorners', 'custom')
        configure('dockCornerRadius', 64)
        configure('iconOpacity', 100)
        configure('dockOpacity', 100)
        fixtures = []
        for _ in range(5):
            address = session.spawn(app='org.windowstash.MatryoshkaTest')[0]
            fixtures.append(address)
            session.park(address)
        session.resting()
        area = session.surface()['usableArea']
        center = (area['x']+area['width']*.48, area['y']+area['height']*.48)
        corner = (area['x']+area['width']-72, area['y']+area['height']-90)
        assert session.dock()['groups'] == 5, 'Disposable windows were not grouped individually'
        for style in STYLES:
            select_native(session, style)
            for direction in ('horizontal', 'vertical'):
                configure('floatingDirection', direction)
                for placement, position in (('free', center), ('edges', corner)):
                    place(session, placement, *position)
                    dock = expand(session, offset=15 if direction == 'horizontal' else -15)
                    assert dock['style'] == style and dock['chain']['count'] == 5
                    collapse(session)
                place(session, 'free', *center)
                interruption(session)
            configure('floatingDirection', 'horizontal')
            place(session, 'free', *center)
            source_removal(session, fixtures.pop(0))
            replacement = session.spawn(app='org.windowstash.MatryoshkaTest', workspace=session.workspace)[0]
            fixtures.append(replacement)
            session.park(replacement)
            session.resting()
            front_reflow(session, fixtures.pop())
            replacement = session.spawn(app='org.windowstash.MatryoshkaTest', workspace=session.workspace)[0]
            fixtures.append(replacement)
            session.park(replacement)
            session.resting()
            print('PASS native '+style+' selection, shared group stages, both axes, free/edge anchors, fixed front and reversible folding', flush=True)
        print('PASS source removal preserves actor identities, ordinals and group geometry until the shared timeline completes', flush=True)
        print('PASS fully unfolded front removal smoothly reflows its successor into the fixed stored anchor', flush=True)

        for style in STYLES:
            under, title = session.spawn(app='org.windowstash.MatryoshkaInputTest')
            h.dispatch('window.float', window='address:'+under, action='on')
            h.dispatch('window.resize', window='address:'+under, x=640, y=420, relative=False)
            h.dispatch('window.move', window='address:'+under,
                       x=session.monitor['x']+100, y=session.monitor['y']+100, relative=False)
            configure('floatingAnimation', style)
            configure('floatingDirection', 'horizontal')
            place(session, 'free', *center)
            interaction(session, under, title)
        print('PASS leave grace, re-entry cancellation, immediate outside click-through and workspace dismissal', flush=True)

        configure('grouping', 'app')
        wait(lambda: session.dock()['groups'] == 1, 'Same-application windows did not become one group')
        session.resting()
        for style in STYLES:
            configure('floatingAnimation', style)
            dock = expand(session, motion=False)
            assert len(dock['actors']) == 1 and dock['chain']['count'] == 1
            session.click(dock['icons'][0])
            wait(lambda: shell('status')['dialog'] == 'picker', 'Single app actor did not open the window chooser')
            shell('dismiss')
            session.resting()
        configure('grouping', 'window')
        session.resting()
        print('PASS app grouping keeps one persistent actor and opens its window chooser', flush=True)
        reduced_motion(session)
        if with_small_output:
            small_output(session)
        assert not shell('status')['error'], shell('status')['error']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--small-output', action='store_true', help='also create and remove a temporary 320x240 output')
    main(parser.parse_args().small_output)
