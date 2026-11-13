#!/usr/bin/env python3
"""Actual old-to-new native bridge upgrades in a disposable compositor only.

Supply an exported historical checkout with --old-root. Run once with the
render-only 1.24.0 source and once with 1.29.1 to check its explicit refusal.
A current checkout with only native/version.txt changed exercises cooperative
upgrades, including held mouse and keyboard input. No Git/network operations or
real desktop sessions are accessed by this suite.
"""
import argparse
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import tempfile
import time
import uuid

from desktop_test import desktop_test
from interactive_bridge import begin, events, local_point, spawn_fixture
from interactive_keyboard import content_click, key_count, source_geometry
from live import ROOT, command, configure, h, shell, wait
from bridge import BridgeManager
from native_session import NativeSession
from preview import API
from preview_bridge_native import accepted, geometry, identity, spawn, suspended
from stash import SPECIAL, lua


def require_isolated():
    assert os.environ.get('WINDOW_STASH_ISOLATED_TEST') == '1' \
        and (Path.home()/'.window-stash-isolated').is_file(), \
        'Refusing bridge replacement outside the explicit disposable desktop'
    assert not command('list')['windows'], 'Use an empty disposable stash'


def native():
    script = '''if not (hl.plugin and %s and %s.status) then return '{}' end
local s=%s.status(); local i=s.interaction or {}
return string.format('{"version":"%%s","hash":"%%s","fingerprint":"%%s",'
 ..'"owners":%%d,"windows":%%d,"frames":%%d,"interaction":%%s,'
 ..'"owner":"%%s","heldButtons":%%d,"heldKeys":%%d,"pendingButtons":%%d,'
 ..'"pendingKeys":%%d,"reloadProtocol":%%d,"reloadPending":%%s,"reloadReady":%%s}',
 s.version or '',s.hyprlandHash or '',s.fingerprint or '',s.owners or 0,
 s.windows or 0,s.frames or 0,tostring(i.active==true),i.owner or '',
 i.heldButtons or 0,i.heldKeys or 0,s.pendingButtons or 0,s.pendingKeys or 0,
 s.reloadProtocol or 0,tostring(s.reloadPending==true),tostring(s.reloadReady==true))
''' % (API, API, API)
    value = json.loads(h.call('repl', script))
    return json.loads(value) if isinstance(value, str) else value


def cli(action, *, env=None, expected_ok=True):
    result = subprocess.run(['/usr/bin/python3', str(ROOT/'controller/bridge.py'), action],
                            env=dict(os.environ, **(env or {})), capture_output=True,
                            text=True, timeout=150)
    values = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    assert values, ('Bridge command emitted no status', action, result.returncode, result.stderr)
    assert bool(values[-1].get('ok')) is expected_ok, (action, values, result.stderr)
    if expected_ok:
        assert result.returncode == 0, (action, values, result.stderr)
    return values


def build(root, directory, *, modern=False):
    argv = ['/usr/bin/python3', str(root/'tools/build-preview-bridge.py')]
    argv += ['--cache-dir', str(directory)] if modern else ['--output', str(directory/'window-stash-preview.so')]
    argv += ['--expected-hash', h.read('version')['commit']]
    result = subprocess.run(argv, capture_output=True, text=True, timeout=150, check=True)
    return json.loads(result.stdout)


def loaded_paths():
    plugins = json.loads(h.call('-j','plugin','list'))
    if not any(item.get('name') == 'window-stash-preview' for item in plugins):
        return []
    manager = BridgeManager(h)
    return [str(manager.loaded_path(manager.native(),manager.commit()))]


def unload_owned(path=None):
    state = native()
    assert not state.get('owners') and not state.get('interaction'), \
        ('Test cleanup refuses to unload live owners', state)
    for owned_path in [str(path)] if path else loaded_paths():
        h.call('plugin', 'unload', owned_path)
    wait(lambda: not native(), 'Owned native API survived cleanup unload')


def wait_line(process, wanted, timeout=15):
    deadline = time.monotonic()+timeout
    values = []
    while time.monotonic() < deadline:
        if not select.select([process.stdout], [], [], .1)[0]:
            if process.poll() is not None:
                break
            continue
        line = process.stdout.readline()
        if not line:
            break
        value = json.loads(line)
        values.append(value)
        if value.get('state') in wanted:
            return value, values
    raise AssertionError(('Bridge command never reached stage', wanted, values, process.poll()))


def build_failures(directory, version, address):
    before = native()
    cli('reload', env={'CXX': '/nonexistent-window-stash-test-compiler'}, expected_ok=False)
    assert native()['version'] == version and h.client(address), \
        'Failed build unloaded the existing bridge or closed the source'
    assert native().get('reloadPending') is not True, 'Failed build left native acquisition disabled'
    print('PASS failed build preserves the loaded bridge and application', flush=True)

    # The compiler remains in a separate owned process group. SIGTERM must
    # cancel it before any compositor change; the current bridge stays usable.
    compiler = directory/'slow-cxx'
    compiler.write_text('#!/usr/bin/python3\nimport os,sys,time\n'
                        'if "--version" in sys.argv: print("Window Stash cancellation fixture");sys.exit(0)\n'
                        'time.sleep(60)\n')
    compiler.chmod(0o700)
    process = subprocess.Popen(['/usr/bin/python3', str(ROOT/'controller/bridge.py'), 'reload'],
                               env=dict(os.environ, CXX=str(compiler)), stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        wait_line(process, {'building'})
        conflict=cli('reload',expected_ok=False)[-1]
        assert conflict['state']=='busy',('Concurrent replacement was not serialized',conflict)
        process.send_signal(signal.SIGTERM)
        process.communicate(timeout=8)
        assert native()['version'] == version and h.client(address), \
            'Cancelled build changed the loaded bridge or closed the source'
        assert native().get('reloadPending') is not True, 'Cancelled build left acquisition disabled'
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate(timeout=3)
    assert before['hash'] == native()['hash']
    print('PASS concurrent replacement is rejected; cancelled preparation preserves the bridge and compositor responsiveness', flush=True)


def load_failure(directory, version, address):
    """Fail just the new module's load; let the real rollback load execute."""
    wrapper = directory/'bin'
    wrapper.mkdir()
    executable = wrapper/'hyprctl'
    token = directory/'load-failed'
    current_version = (ROOT/'native/version.txt').read_text().strip()
    executable.write_text('#!/usr/bin/python3\nimport os,sys\nfrom pathlib import Path\n'
        +'token=Path('+repr(str(token))+')\n'
        +'if sys.argv[1:3]==["plugin","load"] and '+repr('/'+current_version+'-')
        +' in sys.argv[3] and not token.exists():\n'
        +' token.touch();print("Owned synthetic new-bridge load failure",file=sys.stderr);sys.exit(1)\n'
        +'os.execv("/usr/bin/hyprctl",["/usr/bin/hyprctl",*sys.argv[1:]])\n')
    executable.chmod(0o700)
    result = cli('reload',env={'PATH':str(wrapper)+':'+os.environ['PATH']},expected_ok=False)
    assert token.exists(), ('Synthetic failure did not reach the new load', result)
    state = native()
    assert state['version']==version and not state.get('reloadPending') and h.client(address), \
        ('Failed load did not restore the previous usable bridge',state,result)
    assert cli('status')[-1]['state']=='update-required'
    print('PASS failed replacement load rolls back the exact previous bridge and remains retryable',flush=True)


@desktop_test('Isolated bridge upgrade session-lock rejection')
def locked_acceptance():
    require_isolated()
    assert os.environ.get('WINDOW_STASH_SESSION_LOCK_TEST')=='1', 'Explicit session-lock test opt-in is required'
    from interactive_lifecycle import SessionLock
    before=native()
    lock=SessionLock()
    try:
        lock.acquire()
        wait(lambda:h.read('locked').get('locked') is True,'Owned session lock did not engage')
        result=cli('reload',expected_ok=False)[-1]
        assert 'unlock' in result.get('error','').lower(),result
        assert native()==before,'A locked session reload changed native support'
    finally:
        lock.unlock()
    wait(lambda:h.read('locked').get('locked') is False,'Owned session lock did not release')
    print('PASS actual ext-session-lock rejects reload without changing the bridge and unlocks cleanly',flush=True)


@desktop_test('Isolated native bridge old-to-new upgrade acceptance')
def acceptance(old_root, expect_refusal=False, skip_failures=False):
    require_isolated()
    assert not loaded_paths() and not native(), 'Start a fresh disposable compositor with no native bridge'
    current_version = (ROOT/'native/version.txt').read_text().strip()
    old_version = (old_root/'native/version.txt').read_text().strip()
    assert current_version != old_version, 'Use a historical source or a changed-version fixture'
    with tempfile.TemporaryDirectory(prefix='stash-bridge-upgrade-') as temporary, NativeSession() as session:
        directory = Path(temporary)
        configure('presentation', 'dock'); configure('hoverPreview', 'off')
        cache = Path(os.environ.get('XDG_CACHE_HOME', Path.home()/'.cache'))
        legacy = build(old_root, cache/'omarchy/window-stash/preview-bridge'/h.read('version')['commit']/('legacy-fixture-'+old_version))
        h.call('plugin', 'load', legacy['path'])
        wait(lambda: native().get('version') == old_version, 'Historical bridge did not load its actual version')
        state = cli('status')[-1]
        assert state['state'] == 'update-required' and state['loadedVersion'] == old_version, state
        address, state_path = spawn(session, directory, 'suspension')
        record = session.park(address)
        control, _ = session.spawn(app='org.windowstash.BridgeUpgradeControl')
        h.dispatch('focus', window='address:'+control)
        suspended(state_path, True)
        baseline = geometry(address)
        saved = command('list')
        owner = uuid.uuid4().hex
        accepted(owner, [identity(record)], 1)
        suspended(state_path, False)
        if not skip_failures:
            build_failures(directory, old_version, address)

        if expect_refusal:
            #1.29.1 hides physical-release tombstones from status. Even when
            #idle it must not be guessed safe merely from owners==0.
            result = cli('reload', expected_ok=False)[-1]
            assert native()['version'] == old_version and h.client(address), result
            assert 'log' in result.get('error', '').lower() or 'restart' in result.get('error', '').lower(), result
            print('PASS unsupported historical input bridge fails closed without touching applications', flush=True)
            h.eval(API+'.release('+lua(owner)+')')
            wait(lambda:not native()['owners'], 'Historical bridge owner survived explicit release')
            unload_owned(legacy['path'])
            return

        # Cache compilation before holding input, so input is still active
        # when replacement starts instead of naturally expiring during C++.
        expected = build(ROOT, cache/'omarchy/window-stash/preview-bridge', modern=True)
        if not skip_failures:
            load_failure(directory,old_version,address)
        helper = None
        input_address = None
        input_owner = None
        source_log = directory/'input.jsonl'
        try:
            supports_input = native().get('reloadProtocol', 0) == 1
            if supports_input:
                input_address = spawn_fixture(session, source_log)
                input_record = session.park(input_address)
                source = h.client(input_address)
                original_input = source_geometry(input_address)
                h.dispatch('focus', window='address:'+control)
                rect = dict(x=session.monitor['x']+400,y=session.monitor['y']+300,width=400,height=280)
                if not skip_failures:
                    timeout_owner=uuid.uuid4().hex
                    begin(timeout_owner,input_record,session.monitor['name'],rect,keyboard=True)
                    content_click(session,rect,source['size'],source['size'][0]*.75,source['size'][1]*.75)
                    session.move(*local_point(session,rect,.75,.75))
                    session.pointer.button(True)
                    try:
                        wait(lambda:native()['heldButtons']>0,'Timeout fixture did not hold its button')
                        result=cli('reload',expected_ok=False)[-1]
                        state=native()
                        assert state['version']==old_version and not state['reloadPending'] \
                            and state['pendingButtons']>0 and not state['interaction'],(state,result)
                        assert 'held' in result['error'].lower() or 'release' in result['error'].lower(),result
                    finally:
                        session.pointer.button(False)
                    wait(lambda:native()['pendingButtons']==0,'Cancelled reload lost its physical-release cleanup')
                    assert source_geometry(input_address)==original_input
                    print('PASS unreleased physical input times out safely, cancels acquisition barrier and drains after release',flush=True)
                input_owner = uuid.uuid4().hex
                begin(input_owner,input_record,session.monitor['name'],rect,keyboard=True)
                content_click(session,rect,source['size'],source['size'][0]*.75,source['size'][1]*.75)
                session.move(*local_point(session,rect,.75,.75))
                session.pointer.button(True)
                helper = subprocess.Popen(['wtype','-s','100','-P','F8','-s','1500','-p','F8','-s','100'],
                                          stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                wait(lambda:native()['heldButtons'] > 0 and native()['heldKeys'] > 0,
                     'Owned application inputs were not held before reload')
                press_count = len(events(source_log,'press'))
                key_releases = key_count(source_log,'F8','key-release')
                process = subprocess.Popen(['/usr/bin/python3',str(ROOT/'controller/bridge.py'),'reload'],
                                           stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                try:
                    wait(lambda: native().get('reloadPending') is True,
                         'Reload never quiesced the current bridge',timeout=10)
                    state = native()
                    assert not state['interaction'] and not state['owners'], state
                    assert state['pendingButtons'] > 0, ('Held physical button was not retained', state)
                    assert process.poll() is None, 'Bridge unloaded before the held physical button released'
                    session.pointer.button(False)
                    output, errors = process.communicate(timeout=20)
                    values = [json.loads(line) for line in output.splitlines() if line]
                    assert process.returncode == 0 and values[-1].get('ok'), (values, errors)
                finally:
                    session.pointer.button(False)
                    if process.poll() is None:process.terminate();process.communicate(timeout=5)
                helper.wait(timeout=5);helper=None
                assert len(events(source_log,'release')) == press_count, 'Held mouse press was not released exactly once'
                assert key_count(source_log,'F8','key-release') == key_releases+1, 'Held key release was missing or duplicated'
                assert source_geometry(input_address) == original_input, 'Reload changed the hidden input source geometry'
                print('PASS active pointer/keyboard cleanup waits for physical releases and preserves hidden source geometry',flush=True)
            else:
                accepted(owner,[identity(record)],1)
                suspended(state_path,False)
                values=cli('reload')
            status=cli('status')[-1]
            actual=native()
            assert status['state']=='current' and actual['version']==current_version, (status,actual)
            assert actual['hash']==h.read('version')['commit'] and actual['fingerprint']==expected['fingerprint'],actual
            assert actual['owners']==0 and not actual['interaction'],actual
            assert len(loaded_paths())==1 and loaded_paths()[0]!=legacy['path'],loaded_paths()
            suspended(state_path,True)
            assert geometry(address)==baseline, 'Reload moved/resized/restored the hidden application'
            after=command('list')
            assert after['settings']==saved['settings'] and after['positions']==saved['positions'], \
                'Reload changed preferences or positions'
            assert any(value['id']==record['id'] for value in after['windows']), 'Reload lost an owned stash record'
            assert h.read('activeworkspace')['id']==session.workspace, 'Reload exposed a private workspace'
            accepted(uuid.uuid4().hex,[identity(record)],1)
            suspended(state_path,False)
            wait(lambda:native()['owners']==0,'Post-upgrade rendering lease did not expire',timeout=5)
            suspended(state_path,True)
            path=loaded_paths()[0]
            assert cli('reload')[-1]['ok'] and loaded_paths()==[path], 'Repeated reload unnecessarily replaced the current bridge'
            print('PASS exact new binary/hash/fingerprint, resumed rendering, repeat no-op, unchanged stash/preferences/geometry/workspace',flush=True)
        finally:
            try:session.pointer.button(False)
            except (OSError,RuntimeError):pass
            if helper is not None and helper.poll() is None:helper.terminate();helper.wait(timeout=3)
            if native():
                h.eval('if '+API+'.interaction_release then '+API+'.interaction_release('+lua(input_owner or uuid.uuid4().hex)+') end;'+API+'.release('+lua(owner)+')')
                wait(lambda:not native().get('owners') and not native().get('interaction'), 'Native owners survived test cleanup',timeout=5)
                unload_owned()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--old-root',type=Path)
    mode.add_argument('--session-lock-only',action='store_true')
    parser.add_argument('--expect-refusal',action='store_true')
    parser.add_argument('--skip-failures',action='store_true')
    args=parser.parse_args()
    if args.session_lock_only:
        locked_acceptance()
    else:
        acceptance(args.old_root.resolve(),args.expect_refusal,args.skip_failures)
