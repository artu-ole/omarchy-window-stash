#!/usr/bin/env python3
"""Fast popup teardown must leave every parked window private.

Use an explicitly disposable compositor: ninety actual Settings, context and
app-picker cycles keep the pointer over the icon layer, including dismissals
inside its keyboard-focus prime. Explicit external activation still restores.
Real application key events verify hover, drag and dismissal focus; a clicked
preview also acquires and releases input without any public window present.
"""
import os
from pathlib import Path
import tempfile

from desktop_test import desktop_test
from floating_previews import drag, park, ready, seed
from floating_preview_aspect import pause_captures
from interactive_bridge import events, spawn_fixture
from interactive_previews import source_click, start, stopped
from live import command, configure, h, shell, wait
from native_session import NativeSession
from stash import SPECIAL


@desktop_test('Rapid icon popup focus and external activation safety')
def main():
    assert os.environ.get('WINDOW_STASH_ISOLATED_TEST') == '1' and (Path.home()/'.window-stash-isolated').is_file(), \
        'Run only in the explicit disposable desktop'
    assert not command('list')['windows'], 'Use an empty disposable stash'
    with tempfile.TemporaryDirectory(prefix='stash-focus-safety-') as temporary, NativeSession() as session:
        for name, value in dict(scope='workspace', animations='off', hoverPreview='off',
                                floatingPlacement='free', dragMotion='direct', iconOpacity=100).items():
            configure(name, value)
        addresses = [session.spawn(app='org.windowstash.FocusSafety')[0] for _ in range(3)]
        records = [session.park(address) for address in addresses]
        baseline = {record['id'] for record in records}

        def unchanged():
            assert {record['id'] for record in command('list')['windows']} == baseline, \
                'Closing a plugin popup restored a window without activation'
            assert all(h.client(address)['workspace']['name'] == SPECIAL for address in addresses), \
                'Popup focus exposed a parked window'
            assert all((monitor.get('specialWorkspace') or {}).get('name') != SPECIAL for monitor in h.read('monitors')), \
                'Popup teardown opened the private stash workspace'

        def dismissed():
            shell('dismiss')
            wait(lambda: not session.surface()['keyboardOpen'] and shell('status')['dialog'] == '',
                 'Popup did not close')
            unchanged()

        for mode in ('dock', 'bubbles', 'floating'):
            configure('presentation', mode)
            configure('grouping', 'window')
            wait(lambda: session.surface()['groups'] == 3, 'Icon model did not settle')
            for _ in range(10):
                icon = wait(session.icon, 'Icon target missing')
                session.move(icon['x']+icon['width']/2, icon['y']+icon['height']/2)
                shell('settings')
                wait(lambda: session.surface()['dialog']['visible'], 'Settings did not open')
                dismissed()
            for _ in range(10):
                session.click(wait(session.icon, 'Context target missing'), 273)
                try:
                    wait(lambda: shell('status')['dialog'] == 'menu', 'Icon context menu did not open')
                except AssertionError:
                    print('Rapid context diagnostics:', mode, session.surface()['groups'], shell('status')['dialog'],
                          command('list')['windows'], h.read('activewindow'), flush=True)
                    raise
                dismissed()
            configure('grouping', 'app')
            wait(lambda: session.surface()['groups'] == 1, 'App grouping did not settle')
            for _ in range(10):
                if mode == 'floating':
                    session.click(session.dock()['handle'])
                    wait(lambda: session.dock()['expanded'] and not session.dock()['animating'], 'App fan did not unfold')
                session.click(wait(session.icon, 'App icon missing'))
                wait(lambda: shell('status')['dialog'] == 'picker', 'Grouped picker did not open')
                dismissed()
            print('PASS '+mode+':30 rapid Settings/context/group-picker dismissals preserve all exact private records', flush=True)
        configure('grouping', 'window')
        h.dispatch('focus', window='address:'+addresses[0])
        wait(lambda: h.client(addresses[0])['workspace']['id'] == session.workspace
             and all(record['id'] != records[0]['id'] for record in command('list')['windows']),
             'Explicit external activation no longer restores its intended window')
        assert {record['id'] for record in command('list')['windows']} == baseline-{records[0]['id']}
        assert all(h.client(address)['workspace']['name'] == SPECIAL for address in addresses[1:])
        print('PASS 90 rapid popup cycles and intentional external activation without affecting neighboring stashed windows', flush=True)

        configure('presentation', 'bubbles')
        log = Path(temporary)/'public.jsonl'
        control = spawn_fixture(session, log)
        client = h.client(control)
        session.click(dict(x=client['at'][0]-session.monitor['x']+180,
                           y=client['at'][1]-session.monitor['y']+180, width=8, height=8))
        wait(lambda: events(log, 'press'), 'Public application did not receive its initial content click')

        def keys_after(label, operation):
            before = len(events(log, 'root-key'))
            operation()
            session.keys('x')
            wait(lambda: len(events(log, 'root-key')) == before+1,
                 'Icon '+label+' kept keyboard input away from the public application')
            assert h.read('activewindow').get('address') == control, 'Icon '+label+' changed the public focused window'

        def hover():
            icon = session.icon()
            session.move(icon['x']+icon['width']/2, icon['y']+icon['height']/2)

        def menu():
            session.click(session.icon(), 273)
            wait(lambda: shell('status')['dialog'] == 'menu', 'Public-focus context menu did not open')
            shell('dismiss')
            wait(lambda: shell('status')['dialog'] == '', 'Public-focus context menu did not close')

        def settings():
            shell('settings')
            wait(lambda: session.surface()['dialog']['visible'], 'Public-focus Settings did not open')
            shell('dismiss')
            wait(lambda: shell('status')['dialog'] == '', 'Public-focus Settings did not close')

        keys_after('baseline', lambda: None)
        keys_after('hover', hover)
        keys_after('drag', lambda: drag(session, session.icon(), -120, 40))
        keys_after('menu dismissal', menu)
        keys_after('Settings dismissal', settings)
        print('PASS actual public application key delivery survives icon hover, dragging and rapid menu/Settings dismissal without refocusing or pointer warps', flush=True)

    with tempfile.TemporaryDirectory(prefix='stash-empty-preview-focus-') as temporary, NativeSession() as session:
        try:
            for name, value in dict(presentation='previews', scope='workspace', grouping='window',
                                   floatingPreviewInteraction='on', floatingPreviewKeyboard='click',
                                   floatingPreviewActivation='explicit', floatingPreviewSizing='free',
                                   floatingPreviewLock='unlocked', floatingPreviewUpdate='still',
                                   livePreviewCompatibility='standard', floatingPlacement='free',
                                   dragMotion='direct', animations='off', hoverPreview='off').items():
                configure(name, value)
            log = Path(temporary)/'source.jsonl'
            address = spawn_fixture(session, log)
            record = park(session, address)
            seed(session, record, 220, 180, 400)
            drag(session, ready(session, record)['imageRect'], 70, 30)
            start(session, record)
            source_click(session, record)
            session.keys('x')
            wait(lambda: events(log, 'root-key'), 'Empty-workspace preview did not receive actual app keys')
            shell('dismiss')
            wait(stopped, 'Empty-workspace preview interaction did not stop')
            assert any(window['id'] == record['id'] for window in command('list')['windows'])
            assert h.client(address)['workspace']['name'] == SPECIAL
            print('PASS clicked/dragged preview on an empty public workspace acquires real app keyboard input and stays stashed after Stop', flush=True)
        finally:
            pause_captures(session)


if __name__ == '__main__':
    main()
