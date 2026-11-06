#!/usr/bin/env python3
"""Native Physics stack followers, catch-up, interruption and input bounds.

Install this checkout before running in an unlocked Hyprland session. The
notified suite uses only owned fixtures; NativeSession restores desktop state.
"""
import math
import time

from desktop_test import desktop_test
from live import configure, h, shell, wait
from native_session import NativeSession


def snapshot(session):
    surface = session.surface()
    dock = surface['floatingDock']
    body = next(b for b in surface['motion']['dragWorld']['bodies'] if b['key'] == 'dock:floating')
    return dock, body, surface['usableArea']


def actors(dock):
    return sorted(dock['actors'], key=lambda actor: actor['ordinal'])


def distance(dock, ordinal=1):
    actor = actors(dock)[ordinal]
    handle = dock['handle']
    return math.hypot(actor['x']-handle['x'], actor['y']-handle['y']-min(ordinal, 2)*4)


def near(actual, expected, message, tolerance=.1):
    assert abs(actual-expected) <= tolerance, (message, actual, expected)


def frame(session, expected=None):
    dock, body, area = snapshot(session)
    front = actors(dock)[0]
    near(front['x'], body['x'], 'Followers moved the front away from its physics body', .001)
    near(front['y'], body['y'], 'Followers moved the front away from its physics body', .001)
    if expected is not None:
        near(body['x'], expected[0], 'Lead icon lagged behind the pointer', 2)
        near(body['y'], expected[1], 'Lead icon lagged behind the pointer', 2)
    for actor in actors(dock)[:3]:
        assert area['x']-.001 <= actor['x'] <= area['x']+area['width']-actor['width']+.001, actor
        assert area['y']-.001 <= actor['y'] <= area['y']+area['height']-actor['height']+.001, actor
    return dock, body


def rest(session):
    session.resting()
    dock, body = frame(session)
    assert not dock['followers']['active'] and not dock['followers']['tracking'], dock['followers']
    for actor in actors(dock)[:3]:
        near(actor['x'], body['x'], 'Settled trailer did not reach the stack')
        near(actor['y'], body['y']+min(actor['ordinal'], 2)*4, 'Settled trailer lost its preview offset')
    return dock


def place(session, x, y):
    rest(session)
    session.position('dock:floating', round(x), round(y))
    return rest(session)


def press(session):
    dock = session.dock()
    origin = (dock['handle']['x'], dock['handle']['y'])
    session.move(origin[0]+24, origin[1]+24)
    session.pointer.button(True)
    wait(lambda: snapshot(session)[1]['held'], 'Floating dock did not acquire the pointer')
    return origin


def move(session, x, y):
    session.move(x+24, y+24)


def release(session, pause=0):
    if pause:
        time.sleep(pause)
    session.pointer.button(False)


def make_lag(session, start, dx=140):
    place(session, *start)
    origin = press(session)
    for i in range(1, 5):
        move(session, origin[0]+dx*i/4, origin[1])
        time.sleep(.015)
    dock, body = frame(session, (origin[0]+dx, origin[1]))
    assert dock['followers']['active'] and distance(dock) > 3, 'The underlying icons followed rigidly'
    assert not body['frozen'], 'Follower animation froze the lead body'
    return dock, body


def close_fan(session):
    wait(lambda: session.dock()['grabActive'], 'Unfolded dock did not receive keyboard focus')
    session.keys('-k', 'Escape')
    wait(lambda: not session.dock()['expanded'], 'Escape did not fold the dock')
    return rest(session)


@desktop_test('Floating stack follower physics test')
def main():
    with NativeSession() as session:
        for key, value in dict(presentation='floating', grouping='window', scope='workspace',
                               animations='full', animationSpeed='slow', hoverPreview='off',
                               dragMotion='physics', floatingPlacement='free', floatingDirection='horizontal',
                               floatingAnimation='arc', iconShape='square').items():
            configure(key, value)
        for _ in range(4):
            session.park(session.spawn(workspace=session.workspace)[0])
        session.resting()
        area = session.surface()['usableArea']
        start = (area['x']+area['width']*.32, area['y']+area['height']*.42)

        control, title = session.spawn(app='org.windowstash.StackFollowInput', workspace=session.workspace)
        h.dispatch('window.float', window='address:'+control, action='on')
        h.dispatch('window.resize', window='address:'+control, x=700, y=500, relative=False)
        h.dispatch('window.move', window='address:'+control,
                   x=round(session.monitor['x']+start[0]-100), y=round(session.monitor['y']+start[1]-80), relative=False)

        dock = place(session, *start)
        created = dock['createdIcons']
        keys = tuple(a['key'] for a in actors(dock))
        origin = press(session)
        for i in range(1, 7):
            move(session, origin[0]+180*i/6, origin[1])
            time.sleep(.015)
        dock, _ = frame(session, (origin[0]+180, origin[1]))
        ordered = actors(dock)
        assert ordered[2]['x'] < ordered[1]['x'] < ordered[0]['x']-2, ('Trailers did not form a following chain',dock['followers'],[(a['ordinal'],a['x'],a['y'],a['stackLag']) for a in ordered])
        for i in range(1, 7):
            move(session, origin[0]+180, origin[1]+100*i/6)
            time.sleep(.015)
        dock, _ = frame(session, (origin[0]+180, origin[1]+100))
        assert actors(dock)[1]['y'] < actors(dock)[0]['y']+2, 'Trailers did not lag after changing direction'
        release(session, .18)
        wait(lambda: not snapshot(session)[1]['moving'], 'Paused lead did not settle')
        dock, body = frame(session)
        assert dock['followers']['active'] and dock['animating'], 'Trailers stopped with the main body'
        assert not any(a['moving'] for a in actors(dock)), 'Follower motion was mixed into actor/body freezing'
        assert dock['handle']['height'] == 48, 'Lag left invisible trailing input strips on the handle'
        old_lag = distance(dock, 2)
        time.sleep(.1)
        assert distance(session.dock(), 2) < old_lag, 'Released trailers did not catch up'
        rest(session)
        print('PASS direct lead tracking, cascaded trailing motion through turns and independent exact catch-up', flush=True)

        configure('animationSpeed', 'normal')
        place(session, *start)
        origin = press(session)
        for i in range(1, 7):
            move(session, origin[0]+180*i/6, origin[1])
            time.sleep(.012)
        release(session)
        dock = wait(lambda: (d if (d := session.dock())['followers']['active'] else None), 'Flick lost its trailer motion')
        moving = wait(lambda: (b if (b := snapshot(session)[1])['moving'] and b['vx'] > 100 else None), 'Follower motion cancelled the lead momentum')
        assert not moving['frozen']
        assert dock['createdIcons'] == created and tuple(a['key'] for a in actors(dock)) == keys
        rest(session)
        print('PASS flick momentum remains live while the decorative followers catch up', flush=True)

        configure('animationSpeed', 'slow')
        make_lag(session, start, 170)
        release(session, .18)
        wait(lambda: not snapshot(session)[1]['moving'], 'Click-through lead did not settle')
        dock = session.dock()
        trailer = actors(dock)[2]
        point = (trailer['x']+2, trailer['y']+24)
        assert point[0] < dock['handle']['x']-1, 'No exposed trailing corner remained for the input-region check'
        session.pointer.click(*session.point(*point))
        wait(lambda: h.client(control)['title'] == title+' clicked', 'A decorative trailer swallowed the underlying application click')
        assert not session.dock()['expanded'], 'A trailing icon acted as the floating handle'
        rest(session)
        print('PASS exposed trailing artwork stays click-through instead of leaving an extra input target', flush=True)

        lag = {}
        for speed in ('slow', 'relaxed', 'normal', 'fast', 'ultrafast'):
            configure('animationSpeed', speed)
            place(session, *start)
            origin = press(session)
            move(session, origin[0]+120, origin[1])
            time.sleep(.1)
            dock, _ = frame(session, (origin[0]+120, origin[1]))
            assert dock['followers']['speed'] == speed
            lag[speed] = distance(dock)
            release(session, .18)
            rest(session)
        assert lag['slow'] > lag['ultrafast']+5, ('Animation speed did not change catch-up', lag)
        assert lag['normal'] < lag['slow'] and lag['normal'] > lag['ultrafast'], lag
        print('PASS all five speed presets propagate; slower springs trail farther and Ultrafast catches up sooner', flush=True)

        configure('animationSpeed', 'slow')
        for style in ('arc', 'matryoshka-hop'):
            configure('floatingAnimation', style)
            make_lag(session, start, 170)
            release(session, .18)
            before = session.dock()
            assert before['followers']['active'], 'No lag remained for the unfold handoff'
            anchor = (before['handle']['x'], before['handle']['y'])
            timestamp = time.monotonic()
            session.pointer.button(True)
            session.pointer.button(False)
            opened = wait(lambda: (d if (d := session.dock())['expanded'] else None), 'Lagging stack did not unfold')
            elapsed = time.monotonic()-timestamp
            near(opened['handle']['x'], anchor[0], 'Opening moved the lead anchor', .001)
            near(opened['handle']['y'], anchor[1], 'Opening moved the lead anchor', .001)
            assert opened['createdIcons'] == created and tuple(a['key'] for a in actors(opened)) == keys
            if elapsed < .08:
                assert opened['followers']['active'], 'Unfolding reset the spring state'
                assert any(abs(a['stackLag']['x'])+abs(a['stackLag']['y']) > 1 for a in actors(opened)[1:3]), 'Opening discarded current trailer offsets'
                for old, new in zip(actors(before)[1:3], actors(opened)[1:3]):
                    assert math.hypot(new['x']-old['x'], new['y']-old['y']) < 1200*elapsed+10, 'Opening teleported a trailing icon'
            wait(lambda: session.dock()['grabActive'], 'Opening did not acquire keyboard focus')
            session.keys('-k', 'Escape')
            wait(lambda: not session.dock()['expanded'], 'Interrupted opening did not fold')
            rest(session)
        print('PASS moving-to-unfold handoff keeps the anchor/actors and folds without resurrecting old lag', flush=True)

        for mode, motion in (('full', 'direct'), ('reduced', 'physics'), ('off', 'physics')):
            configure('animations', 'full'); configure('dragMotion', 'physics')
            make_lag(session, start)
            configure('animations', mode); configure('dragMotion', motion)
            wait(lambda: not session.dock()['followers']['active'] and not session.dock()['followers']['eligible'], 'A disabled mode kept follower motion alive')
            dock, body = frame(session)
            for actor in actors(dock)[:3]:
                near(actor['x'], body['x'], 'Disabled follower retained horizontal lag')
                near(actor['y'], body['y']+min(actor['ordinal'], 2)*4, 'Disabled follower retained vertical lag')
            release(session, .18)
            rest(session)
            configure('animations', 'full'); configure('dragMotion', 'physics')
            rest(session)
            assert not session.dock()['followers']['active'], 'Re-enabling physics resurrected old lag'
        print('PASS Direct, Reduced and Off clear spring state, including changes during a held drag', flush=True)

        make_lag(session, start)
        configure('grouping', 'app')
        wait(lambda: session.dock()['groups'] == 1 and not session.dock()['followers']['active'], 'Single app group retained old followers')
        assert not session.dock()['followers']['eligible']
        release(session, .18)
        rest(session)
        configure('grouping', 'window')
        wait(lambda: session.dock()['groups'] == 4, 'Window grouping did not return')
        rest(session)
        assert not session.dock()['followers']['active']
        print('PASS grouping/count changes reset decorative followers without leaving a stale drag state', flush=True)

        configure('animationSpeed', 'normal')
        place(session, area['x']+70, area['y']+70)
        origin = press(session)
        for x, y in ((area['x']+8, area['y']+70), (area['x']+8, area['y']+8),
                     (area['x']+100, area['y']+8), (area['x']+100, area['y']+100)):
            move(session, x, y); time.sleep(.04); frame(session)
        release(session, .18)
        rest(session)
        assert not shell('status')['error'], shell('status')['error']
        print('PASS dragging near work-area edges keeps every visible follower bounded and returns to idle', flush=True)


if __name__ == '__main__':
    main()
