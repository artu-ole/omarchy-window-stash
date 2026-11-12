#!/usr/bin/env python3
"""Native lease safety, Wayland suspension, expiry and bridge lifecycle.

Run in an unlocked Hyprland session with the checkout installed. Only disposable
windows and random test-owned leases are changed. A pre-existing bridge is
preserved; unload/reload checks run only when this suite loaded the bridge.
The raw client observes protocol state directly; GTK can defer its corresponding
property until another frame and cannot reliably report hidden-window suspension.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import uuid

from desktop_test import desktop_test
from live import command, configure, h, wait
from native_session import NativeSession
from preview import API, PROBE, PreviewBridge
from stash import PREFIX, SPECIAL, lua


def spawn(session, directory, label):
    title = 'Stash native lease %s %s' % (os.getpid(), label)
    path = directory / (label+'.json')
    h.dispatch('focus', workspace=str(session.workspace))
    process = subprocess.Popen(['/usr/bin/python3', str(Path(__file__).with_name('constraint-window.py')),
                                title, str(directory/(label+'.jsonl')), str(path)],
                               env=dict(os.environ, GDK_BACKEND='wayland', PYTHONDONTWRITEBYTECODE='1'),
                               stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    session.processes.append(process)
    client = wait(lambda: next((c for c in h.read('clients') if c['title'] == title), None),
                  'Native lease fixture did not map: '+label)
    session.addresses.append(client['address'])
    h.dispatch('window.float', window='address:'+client['address'], action='on')
    wait(lambda: path.is_file(), 'Wayland suspension state was not published: '+label)
    return client['address'], path


def suspended(path, expected):
    def check():
        try:
            return json.loads(path.read_text())['suspended'] is expected
        except (FileNotFoundError, ValueError):
            return False
    wait(check, 'Wayland suspension did not become '+str(expected), timeout=4)


def available():
    try:
        h.eval(PROBE)
        return True
    except RuntimeError:
        return False


def status():
    # repl prints tables as addresses. Serialize only bounded native counters
    # and validated hexadecimal record IDs into a JSON string inside Lua.
    code = '''local s=%s.status()
local ids={}; for _,id in ipairs(s.windowIds) do ids[#ids+1]='"'..id..'"' end
table.sort(ids)
return string.format('{"owners":%%d,"windows":%%d,"frames":%%d,"ids":[%%s]}',
  s.owners,s.windows,s.frames,table.concat(ids,','))''' % API
    value = json.loads(h.call('repl', code))
    return json.loads(value) if isinstance(value, str) else value


def identity(record):
    return dict(id=record['id'], tag=record['tag'], address=record['address'],
                pid=record['pid'], stable_id=record['stableId'])


def payload(owner, windows):
    return '{owner='+lua(owner)+',windows={'+','.join(
        '{'+','.join(key+'='+lua(value) for key, value in window.items())+'}' for window in windows)+'}}'


def accepted(owner, windows, count):
    h.eval('local r,e='+API+'.update('+payload(owner, windows)+'); assert(r,e); '
           +'assert(r.accepted=='+str(count)+', "Unexpected accepted preview count")')


def rejected(owner, windows):
    h.eval('local r,e='+API+'.update('+payload(owner, windows)+'); '
           +'assert(r==nil and type(e)=="string", "Malformed preview identity was accepted")')


def expect(records, owner_count):
    wanted = sorted(record['id'] for record in records)

    def matches():
        value = status()
        return value if value['ids'] == wanted and value['windows'] == len(wanted) \
            and value['owners'] == owner_count else None

    return wait(matches, 'Native lease set did not match '+str(wanted), timeout=4)


def geometry(address):
    client = h.client(address)
    return {key: client.get(key) for key in ('at', 'size', 'workspace', 'floating', 'pinned',
                                            'fullscreen', 'pid', 'stableId', 'tags')}


@desktop_test('Native live preview bridge safety test')
def main():
    loaded_by_test = False
    bridge = PreviewBridge(h)
    tokens = [uuid.uuid4().hex for _ in range(3)]
    first_owner, second_owner, invalid_owner = tokens
    loaded_path = None
    try:
        with NativeSession() as session, tempfile.TemporaryDirectory(prefix='stash-native-preview-') as temporary:
            # Persistent floating captures can keep a hovered source awake
            # independently of rendering leases. Measure the bridge in isolation.
            configure('presentation', 'dock')
            configure('hoverPreview', 'off')
            existed = available()
            if not existed:
                commit = h.read('version')['commit']
                loaded_path = Path(os.environ.get('XDG_CACHE_HOME', Path.home()/'.cache')) \
                    / 'omarchy/window-stash/preview-bridge' / commit / 'window-stash-preview.so'
                # ensure builds against matching headers and loads only the
                # cache path it produced; the shared desktop guard is active.
                bridge.ensure()
                loaded_by_test = True
            else:
                bridge.ensure()
            wait(available, 'Native preview API did not attach after loading')
            expect([], 0)  # Never clear or unload another owner's live lease.
            directory = Path(temporary)
            first_address, first_state = spawn(session, directory, 'first')
            first = session.park(first_address)
            second_address, second_state = spawn(session, directory, 'second')
            second = session.park(second_address)
            foreign_address, foreign_state = spawn(session, directory, 'unstashed')
            h.dispatch('focus', window='address:'+foreign_address)
            try:
                suspended(first_state, True)
                suspended(second_state, True)
            except AssertionError:
                print('Natural suspension diagnostics:', {'native': status(),
                      'first': json.loads(first_state.read_text()), 'second': json.loads(second_state.read_text()),
                      'clients': [geometry(address) for address in session.addresses],
                      'active': h.read('activewindow').get('address'), 'monitors': h.read('monitors')}, flush=True)
                raise
            suspended(foreign_state, False)
            baseline = {address: geometry(address) for address in session.addresses}
            focus = h.read('activewindow')['address'], h.read('activeworkspace')['id']
            one, two = identity(first), identity(second)

            accepted(first_owner, [one, two], 2)
            before = expect([first, second], 1)['frames']
            suspended(first_state, False)
            suspended(second_state, False)
            wait(lambda: status()['frames'] >= before+2, 'Leased windows received no frame feedback')
            suspended(foreign_state, False)

            # Schema failures are transactional: the owner's previous valid
            # lease must survive each rejected update.
            rejected('not-an-owner', [one])
            for patch in (dict(id='bad'), dict(pid=0), dict(pid='1'),
                          dict(stable_id='not-hex'), dict(tag='another-plugin')):
                accepted(first_owner, [one, two], 2)
                rejected(first_owner, [dict(one, **patch)])
                expect([first, second], 1)

            # Well-formed but stale/foreign identities are dropped, including
            # correct-looking ownership on an unstashed window.
            for patch in (dict(pid=one['pid']+1), dict(stable_id=format(int(one['stable_id'], 16)+1, 'x')),
                          dict(id=invalid_owner, tag=PREFIX+invalid_owner)):
                accepted(first_owner, [one, two], 2)
                accepted(invalid_owner, [dict(one, **patch)], 0)
                expect([first, second], 1)
            foreign = h.client(foreign_address)
            foreign_tag = PREFIX+invalid_owner
            h.dispatch('window.tag', window='address:'+foreign_address, tag='+'+foreign_tag)
            try:
                candidate = dict(id=invalid_owner, tag=foreign_tag, address=foreign_address,
                                 pid=foreign['pid'], stable_id=foreign['stableId'])
                accepted(first_owner, [one, two], 2)
                accepted(invalid_owner, [candidate], 0)
                expect([first, second], 1)
                suspended(foreign_state, False)
            finally:
                h.dispatch('window.tag', window='address:'+foreign_address, tag='-'+foreign_tag)
            assert {address: geometry(address) for address in session.addresses} == baseline
            assert (h.read('activewindow')['address'], h.read('activeworkspace')['id']) == focus
            print('PASS malformed and mismatched identities, exact ownership/workspace checks, unchanged foreign window and focus', flush=True)

            accepted(second_owner, [two], 1)
            expect([first, second], 2)
            accepted(first_owner, [one], 1)
            expect([first, second], 2)
            bridge.release(first_owner)
            expect([second], 1)
            suspended(first_state, True)
            suspended(second_state, False)
            # Overlapping owners retain one window until its last lease ends.
            accepted(first_owner, [two], 1)
            expect([second], 2)
            bridge.release(second_owner)
            expect([second], 1)
            suspended(second_state, False)
            bridge.release(first_owner)
            bridge.release(first_owner)
            expect([], 0)
            suspended(second_state, True)
            print('PASS independent owner union, replacement/subsets, overlapping release and idempotent cleanup', flush=True)

            for _ in range(7):
                accepted(first_owner, [one], 1)
                suspended(first_state, False)
                time.sleep(.5)
            renewed = time.monotonic()
            expect([first], 1)
            suspended(first_state, True)
            elapsed = time.monotonic()-renewed
            assert 1.6 <= elapsed < 3.6, ('Lease expiry ignored its 2.5 second deadline', elapsed)
            expect([], 0)
            print('PASS 500 ms renewals survive beyond a lease period and abandoned leases expire and resuspend', flush=True)

            # A previously valid client must lose eligibility after either
            # restoration or closure, without touching a surviving neighbor.
            accepted(first_owner, [one, two], 2)
            command('restore', first['id'], '--to', 'current', '--monitor', session.monitor['name'],
                    '--workspace', str(session.workspace))
            wait(lambda: h.client(first_address)['workspace']['name'] != SPECIAL, 'Owned fixture did not restore')
            accepted(first_owner, [one, two], 1)
            expect([second], 1)
            suspended(first_state, False)
            h.dispatch('window.close', window='address:'+second_address)
            wait(lambda: not h.client(second_address), 'Owned fixture did not close')
            accepted(first_owner, [two], 0)
            expect([], 0)
            assert h.client(first_address) and h.client(foreign_address)
            print('PASS restored and closed window identities are rejected while surviving windows remain intact', flush=True)

            if loaded_by_test:
                first = session.park(first_address)
                accepted(first_owner, [identity(first)], 1)
                suspended(first_state, False)
                assert status()['owners'] == 1
                h.call('plugin', 'unload', str(loaded_path))
                loaded_by_test = False
                wait(lambda: not available(), 'Bridge API survived unloading')
                suspended(first_state, True)
                assert h.read('monitors') and h.client(first_address), 'Unloading hung or destroyed compositor state'
                bridge.ready = False
                bridge.ensure()
                loaded_by_test = True
                accepted(first_owner, [identity(first)], 1)
                suspended(first_state, False)
                bridge.release(first_owner)
                expect([], 0)
                suspended(first_state, True)
                print('PASS active unload restores suspension, compositor stays responsive and reloading reacquires safely', flush=True)
            else:
                print('NOTE pre-existing native bridge preserved; unload/reload branch requires a fresh isolated compositor', flush=True)
    finally:
        if available():
            for token in tokens:
                bridge.release(token)
            if loaded_by_test:
                assert status()['owners'] == 0, 'Refusing to unload a bridge with another owner'
                h.call('plugin', 'unload', str(loaded_path))
                wait(lambda: not available(), 'Test-owned bridge did not unload during cleanup')


if __name__ == '__main__':
    main()
