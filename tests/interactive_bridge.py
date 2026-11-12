#!/usr/bin/env python3
"""Native input proof on an explicitly isolated desktop; no UI dependency.

The owned GTK source logs actual delivered input. The bridge routes physical-seat
events through a scaled logical image rectangle while a second visible window
detects accidental click leakage. No source data is written into this repository.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid

from desktop_test import desktop_test
from live import ROOT, command, configure, h, wait
from interaction import InteractionBridge
from native_session import NativeSession
from preview import API, PreviewBridge, preview_records
from stash import SPECIAL, lua


def events(path, kind=None):
    try:
        values = [json.loads(line) for line in path.read_text().splitlines() if line]
    except FileNotFoundError:
        return []
    return [item for item in values if kind is None or item['event'] == kind]


def native_status(owner):
    return InteractionBridge(h).interaction_status(owner)


def begin(owner, record, monitor, rect, excludes=None, keyboard=False):
    identity = preview_records([record], h.read('clients'), [record['id']])[0]
    fields = ['owner='+lua(owner), 'window={'+','.join(key+'='+lua(value) for key, value in identity.items())+'}',
              'monitor='+lua(monitor), 'rect={'+','.join(key+'='+lua(value) for key, value in rect.items())+'}',
              'keyboard='+lua(keyboard), 'fps=60']
    if excludes:
        fields.append('excludeRects={'+','.join('{'+','.join(key+'='+lua(value) for key, value in item.items())+'}' for item in excludes)+'}')
    h.eval('local result,err='+API+'.interaction_update({'+','.join(fields)+'});assert(result,err);assert(result.active,result.reason)')


def end(owner):
    h.eval('if hl.plugin and '+API+' and '+API+'.interaction_release then '+API+'.interaction_release('+lua(owner)+') end')


def spawn_fixture(session, log):
    title = 'Stash interaction '+str(os.getpid())+' '+str(len(session.addresses))
    with log.with_suffix('.stderr').open('w') as errors:
        process = subprocess.Popen(['/usr/bin/python3', str(ROOT/'tests/interactive-window.py'), title, str(log)],
                                   env=dict(os.environ, GDK_BACKEND='wayland'), stdout=subprocess.DEVNULL, stderr=errors)
    session.processes.append(process)
    client = wait(lambda: next((item for item in h.read('clients') if item['title'] == title), None), 'Interactive fixture did not open')
    session.addresses.append(client['address'])
    wait(lambda: events(log, 'ready'), 'Interactive fixture did not initialize')
    h.dispatch('window.float', window='address:'+client['address'], action='on')
    h.dispatch('window.resize', window='address:'+client['address'], x=1000, y=700, relative=False)
    return client['address']


def scroll(pointer, delta=15):
    # wlr virtual pointer v1 axis + axis_source + frame. Native input must keep
    # the same units and event ordering instead of fabricating wheel keypresses.
    import struct
    stamp = int(time.monotonic()*1000) & 0xffffffff
    pointer.send(5, 5, pointer.uint(0))
    pointer.send(5, 7, struct.pack('IIii', stamp, 0, int(delta*256), 1 if delta > 0 else -1))
    pointer.send(5, 4)
    pointer.sync()


def local_point(session, rect, x, y):
    return rect['x']-session.monitor['x']+rect['width']*x, rect['y']-session.monitor['y']+rect['height']*y


@desktop_test('Isolated interactive-preview native pointer proof')
def main():
    assert os.environ.get('WINDOW_STASH_ISOLATED_TEST') == '1' and (Path.home()/'.window-stash-isolated').is_file(), \
        'Run only in the explicit disposable compositor'
    assert not command('list')['windows'], 'Native input proof requires an empty disposable stash'
    bridge = PreviewBridge(h)
    bridge.ensure()
    with tempfile.TemporaryDirectory(prefix='stash-interaction-') as temporary, NativeSession() as session:
        configure('presentation', 'dock')
        configure('hoverPreview', 'off')
        log = Path(temporary)/'source.jsonl'
        address = spawn_fixture(session, log)
        visible = h.client(address)
        h.dispatch('focus', window='address:'+address)
        session.move(visible['at'][0]-session.monitor['x']+visible['size'][0]*.75,
                     visible['at'][1]-session.monitor['y']+visible['size'][1]*.75)
        wait(lambda: events(log, 'motion'), 'Visible input fixture did not receive pointer motion')
        scroll(session.pointer)
        wait(lambda: events(log, 'scroll'), 'Ordinary visible fixture did not receive baseline scrolling')
        control, control_title = session.spawn(app='org.windowstash.InteractionControl')
        h.dispatch('window.float', window='address:'+control, action='on')
        h.dispatch('window.resize', window='address:'+control, x=1100, y=700, relative=False)
        h.dispatch('window.move', window='address:'+control, x=session.monitor['x']+50, y=session.monitor['y']+50, relative=False)
        record = session.park(address)
        h.dispatch('focus', window='address:'+control)
        source = h.client(address)
        source_state = (source['workspace'], source['at'], source['size'])
        owner = uuid.uuid4().hex
        rect = dict(x=session.monitor['x']+400, y=session.monitor['y']+300, width=400, height=280)
        try:
            begin(owner, record, session.monitor['name'], rect)
            assert native_status(owner)['active'], 'Native interaction did not become active'
            for button in (272, 273, 274):
                before = len(events(log, 'press'))
                x, y = local_point(session, rect, .75, .75)
                session.move(x-1, y)
                session.pointer.click(*session.point(x, y), button=button)
                press = wait(lambda: len(values := events(log, 'press')) > before and values[-1], 'Source did not receive native button '+str(button))
                assert press['button'] == {272:1, 273:3, 274:2}[button], ('Button mapping changed', press)
                assert abs(press['x']-source['size'][0]*.75) <= 3 and abs(press['y']-source['size'][1]*.75) <= 3, \
                    ('Scaled click missed its source coordinates', press, source['size'])
                wait(lambda: len(events(log, 'release')) >= before+1, 'Source did not receive matching button release')
                assert h.client(control)['title'] == control_title, 'Forwarded click leaked to the visible window'
                begin(owner, record, session.monitor['name'], rect)
            count = len(events(log, 'scroll'))
            scroll(session.pointer)
            try:
                wait(lambda: len(events(log, 'scroll')) > count, 'Source did not receive native scrolling', timeout=1.2)
            except AssertionError:
                print('Native scroll diagnostics:', native_status(owner), events(log)[-8:], log.with_suffix('.stderr').read_text()[-2000:], flush=True)
                raise
            begin(owner, record, session.monitor['name'], rect)
            start = local_point(session, rect, .25, .6)
            session.move(*start)
            session.pointer.button(True)
            for fraction in (.35, .5, .8, 1.1):
                session.move(*local_point(session, rect, fraction, .6))
                time.sleep(.025)
            session.pointer.button(False)
            wait(lambda: any(item.get('dragging') and item['x'] > source['size'][0] for item in events(log, 'motion')),
                 'Implicit source drag stopped at the miniature boundary')
            assert native_status(owner)['active'], 'Dragging outside the miniature incorrectly ended interaction'
            now = h.client(address)
            assert (now['workspace'], now['at'], now['size']) == source_state and now['workspace']['name'] == SPECIAL, \
                'Input forwarding restored, moved or resized the source'
            assert h.read('activeworkspace')['id'] == session.workspace, 'Input forwarding switched the visible workspace'
            print('PASS scaled left/right/middle clicks, real scrolling, implicit drag, no input leakage and unchanged source/workspace', flush=True)

            session.pointer.click(*session.point(200, 250))
            wait(lambda: not native_status(owner)['active'], 'Outside click did not end interaction')
            wait(lambda: h.client(control)['title'] == control_title+' clicked', 'Outside click did not reach its normal visible destination')
            identity = preview_records([record], h.read('clients'), [record['id']])[0]
            # Repeating the exact lease owner after native outside-click exit
            # must not reopen it on the next periodic renewal.
            fields = ','.join(key+'='+lua(value) for key, value in identity.items())
            script = ('local result,err='+API+'.interaction_update({owner='+lua(owner)+',window={'+fields+'},monitor='
                      +lua(session.monitor['name'])+',rect={'+','.join(key+'='+lua(value) for key,value in rect.items())
                      +'},keyboard=false,fps=60});assert(result,err);assert(not result.active,"Ended owner restarted")')
            h.eval(script)
            print('PASS outside click reaches its destination once and renewal cannot resurrect the ended owner', flush=True)
            owner = uuid.uuid4().hex
            begin(owner, record, session.monitor['name'], rect)
            wait(lambda: not native_status(owner)['active'], 'Abandoned input lease did not expire', timeout=5)
            print('PASS abandoned session expiry releases native input ownership', flush=True)
        finally:
            end(owner)


if __name__ == '__main__':
    main()
