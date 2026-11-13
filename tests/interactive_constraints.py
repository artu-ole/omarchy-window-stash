#!/usr/bin/env python3
"""Real Wayland pointer-lock/confinement safety proof in a disposable compositor."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import uuid

from desktop_test import desktop_test
from interactive_bridge import begin, end, events, local_point, native_status, spawn_fixture
from interactive_handoff import Events
from live import ROOT, command, configure, h, wait
from native_session import NativeSession
from preview import API, PreviewBridge, preview_records
from stash import SPECIAL, lua


class ConstraintFixture:
    def __init__(self, session, log):
        self.log, self.serial = log, 0
        title = 'Stash constraint '+str(os.getpid())+' '+str(len(session.addresses))
        with log.with_suffix('.stderr').open('w') as errors:
            self.process = subprocess.Popen([str(Path(os.sys.executable)), str(ROOT/'tests/constraint-window.py'), title, str(log)],
                                            stdin=subprocess.PIPE, text=True, stdout=subprocess.DEVNULL, stderr=errors)
        session.processes.append(self.process)
        try:
            client = wait(lambda: next((item for item in h.read('clients') if item['title'] == title), None),
                          'Raw Wayland constraint fixture did not map')
            wait(lambda: events(log, 'ready'), 'Raw Wayland constraint fixture did not initialize')
        except BaseException:
            print('Constraint fixture startup diagnostics:', dict(title=title, status=self.process.poll()),
                  log.with_suffix('.stderr').read_text()[-4000:], events(log)[-12:], flush=True)
            raise
        self.address = client['address']
        session.addresses.append(self.address)
        h.dispatch('window.float', window='address:'+self.address, action='on')

    def send(self, action):
        self.serial += 1
        assert self.process.poll() is None, self.log.with_suffix('.stderr').read_text()
        self.process.stdin.write(json.dumps(dict(action=action, serial=self.serial))+'\n')
        self.process.stdin.flush()
        wait(lambda: any(item.get('serial') == self.serial for item in events(self.log, 'command')),
             'Constraint command did not complete a compositor roundtrip: '+action)

    def activations(self):
        return sum(item['active'] for item in events(self.log, 'constraint-state'))


def cursor():
    value = h.read('cursorpos')
    return value['x'], value['y']


def unchanged_cursor(before):
    now = cursor()
    assert max(abs(a-b) for a, b in zip(now, before)) <= 1, ('A hidden constraint warped the physical cursor', before, now)


def rejected(owner, record, monitor, rect):
    identity = preview_records([record], h.read('clients'), [record['id']])[0]
    fields = ','.join(key+'='+lua(value) for key, value in identity.items())
    geometry = ','.join(key+'='+lua(value) for key, value in rect.items())
    h.eval('local result,err='+API+'.interaction_update({owner='+lua(owner)+',window={'+fields+'},monitor='+lua(monitor)
           +',rect={'+geometry+'},keyboard=true,fps=60});assert(result==nil and type(err)=="string" '
           'and err:find("Pointer-locked",1,true),"Dormant constraint was not refused: "..tostring(err))')


@desktop_test('Isolated interactive-preview pointer constraint safety proof')
def main():
    assert os.environ.get('WINDOW_STASH_ISOLATED_TEST') == '1' and (Path.home()/'.window-stash-isolated').is_file(), \
        'Run only in the explicit disposable compositor'
    assert not command('list')['windows'], 'Constraint proof requires an empty disposable stash'
    PreviewBridge(h).ensure()
    with tempfile.TemporaryDirectory(prefix='stash-constraints-') as temporary, NativeSession() as session:
        configure('presentation', 'dock')
        configure('hoverPreview', 'off')
        directory = Path(temporary)
        source = ConstraintFixture(session, directory/'source.jsonl')
        control = spawn_fixture(session, directory/'control.jsonl')
        record = session.park(source.address)
        original = h.client(source.address)
        geometry = original['workspace'], original['at'], original['size']
        h.dispatch('focus', window='address:'+control)
        rect = dict(x=session.monitor['x']+380, y=session.monitor['y']+260, width=400, height=280)
        owner = uuid.uuid4().hex
        monitor = Events()
        try:
            for kind in ('lock', 'confine'):
                session.move(*local_point(session, rect, .5, .5))
                source.send(kind)
                assert source.activations() == 0, 'An unfocused hidden constraint unexpectedly activated'
                before = cursor()
                keyboard_enters = len(events(source.log, 'keyboard-enter'))
                owner = uuid.uuid4().hex
                rejected(owner, record, session.monitor['name'], rect)
                assert not native_status(owner)['active'], 'Refused source retained an input session'
                unchanged_cursor(before)
                assert len(events(source.log, 'keyboard-enter')) == keyboard_enters, 'A refused source received keyboard focus'
                assert source.activations() == 0, 'A refused source constraint activated'
                source.send('destroy')
                end(owner)
            print('PASS dormant lock and confinement are refused before keyboard focus or physical cursor changes', flush=True)

            for kind in ('lock', 'confine'):
                owner = uuid.uuid4().hex
                h.dispatch('focus', window='address:'+control)
                begin(owner, record, session.monitor['name'], rect, keyboard=True)
                session.move(*local_point(session, rect, .5, .5))
                session.pointer.button(True)
                session.pointer.button(False)
                wait(lambda: native_status(owner).get('keyboardFocused'), 'Source did not acquire click-only keyboard focus')
                before = cursor()
                activations = source.activations()
                source.send(kind)
                state = wait(lambda: (value := native_status(owner)) and not value['active'] and value,
                             'A new source constraint did not end native routing')
                assert state['reason'] == 'pointer-constrained', state
                unchanged_cursor(before)
                assert source.activations() == activations, 'A hidden source constraint activated before cleanup'
                source.send('destroy')
                assert h.read('activewindow').get('address') == control, 'Constraint cleanup did not return ordinary focus'
            print('PASS new lock and confinement requests end routing before activation or cursor warp', flush=True)

            unrelated = ConstraintFixture(session, directory/'unrelated.jsonl')
            unrelated_record = session.park(unrelated.address)
            h.dispatch('focus', window='address:'+control)
            unrelated.send('lock')
            assert unrelated.activations() == 0, 'Unrelated dormant lock unexpectedly activated'
            owner = uuid.uuid4().hex
            begin(owner, record, session.monitor['name'], rect, keyboard=True)
            session.move(*local_point(session, rect, .5, .5))
            session.pointer.button(True)
            session.pointer.button(False)
            wait(lambda: native_status(owner).get('keyboardFocused'), 'An unrelated dormant constraint blocked the source')
            assert native_status(owner)['active'], 'An unrelated dormant constraint ended the source session'
            assert unrelated.activations() == 0, 'Miniature input activated another application constraint'
            end(owner)
            command('restore', unrelated_record['id'], '--to', 'original')
            h.dispatch('focus', window='address:'+unrelated.address)
            public = h.client(unrelated.address)
            session.move(public['at'][0]-session.monitor['x']+20, public['at'][1]-session.monitor['y']+20)
            wait(lambda: unrelated.activations() == 1, 'The native guard broke normal constraint activation in another application')
            unrelated.send('destroy')
            now = h.client(source.address)
            assert (now['workspace'], now['at'], now['size']) == geometry and now['workspace']['name'] == SPECIAL, \
                'Constraint handling changed the source placement'
            assert h.read('activeworkspace')['id'] == session.workspace, 'Constraint handling switched workspaces'
            monitor.check()
            print('PASS unrelated constraints neither block miniature input nor lose normal activation outside it; stash remains private', flush=True)
        except BaseException:
            print('Constraint proof diagnostics:', native_status(owner), events(source.log)[-20:],
                  source.log.with_suffix('.stderr').read_text()[-2000:], flush=True)
            raise
        finally:
            end(owner)
            monitor.close()


if __name__ == '__main__':
    main()
