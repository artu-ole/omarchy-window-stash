#!/usr/bin/env python3
"""Private-workspace protection and exact restoration of unsupported app UI flows."""
import argparse
import os
from pathlib import Path
import socket
import tempfile
import time

from desktop_test import desktop_test
from floating_previews import card, park, ready, seed
from interactive_bridge import events, spawn_fixture
from interactive_previews import active, assert_source, interaction, source_click, start, stopped
from live import command, configure, h, shell, wait
from native_session import NativeSession
from stash import SPECIAL


class Events:
    def __init__(self):
        self.socket = socket.socket(socket.AF_UNIX)
        self.socket.connect(str(Path(os.environ['XDG_RUNTIME_DIR'])/'hypr'/os.environ['HYPRLAND_INSTANCE_SIGNATURE']/'.socket2.sock'))
        self.socket.setblocking(False)
        self.buffer = ''

    def check(self):
        while True:
            try:
                data = self.socket.recv(65536)
                if not data:
                    break
                self.buffer += data.decode(errors='replace')
            except BlockingIOError:
                break
        assert not any(line.startswith(('activespecial>>', 'activespecialv2>>')) and SPECIAL in line
                       for line in self.buffer.splitlines()), 'An application request exposed the private stash workspace'
        assert all(monitor.get('specialWorkspace', {}).get('name') != SPECIAL for monitor in h.read('monitors')), \
            'An application request left the private stash workspace visible'

    def close(self):
        self.check()
        self.socket.close()


def source_point(session, record, x, y):
    size = h.client(record['address'])['size']
    source_click(session, record, x/size[0], y/size[1])


def monitor_records(witness):
    assert h.client(witness['address'])['workspace']['name'] == SPECIAL, 'An unrelated stashed window was restored or exposed'
    records = command('list')['windows']
    assert any(record['id'] == witness['id'] for record in records), 'An unrelated stash record disappeared'


@desktop_test('Isolated interactive-preview popup and restoration handoff acceptance')
def main(handoff_only=False):
    assert os.environ.get('WINDOW_STASH_ISOLATED_TEST') == '1' and (Path.home()/'.window-stash-isolated').is_file()
    assert not command('list')['windows']
    following = h.call('repl', 'return hl.get_config("input.follow_mouse")')
    assert following in ('0', '1', '2', '3')
    with tempfile.TemporaryDirectory(prefix='stash-handoff-') as temporary, NativeSession() as session:
        for key, value in dict(presentation='previews', scope='global', grouping='window',
                               floatingPreviewInteraction='on', floatingPreviewActivation='explicit', floatingPreviewKeyboard='click',
                               floatingPreviewInteractionFps='60', floatingPreviewControls='always', floatingPreviewUpdate='still',
                               livePreviewCompatibility='standard', hoverPreview='off', floatingPreviewSizing='free',
                               floatingPreviewTitles='hidden', floatingPreviewFrame='hidden', floatingPreviewLock='unlocked',
                               floatingPlacement='free', dragMotion='direct', animations='off').items():
            configure(key, value)
        directory = Path(temporary)
        witness_address = spawn_fixture(session, directory/'witness.jsonl')
        witness = park(session, witness_address)
        seed(session, witness, 800, 180, 280)
        control, _ = session.spawn(app='org.windowstash.HandoffVisibleControl')
        log = directory/'source.jsonl'
        address = spawn_fixture(session, log)
        source = h.client(address)
        session.pointer.click(*session.point(source['at'][0]-session.monitor['x']+740,
                                             source['at'][1]-session.monitor['y']+106))
        existing = wait(lambda: next((client for client in h.read('clients')
                                     if client['title'] == h.client(address)['title']+' existing'), None),
                        'Pre-existing transient fixture did not map')
        session.addresses.append(existing['address'])
        h.dispatch('window.move', window='address:'+existing['address'], workspace=str(session.workspace+2), follow=False)
        record = park(session, address)
        seed(session, record, 180, 180, 440)
        monitor = Events()
        try:
            for follow in () if handoff_only else (0, 1, 2, 3):
                h.eval('hl.config({input={follow_mouse='+str(follow)+'}})')
                h.dispatch('focus', window='address:'+control)
                start(session, record)
                opened = len(events(log, 'popup-open'))
                chosen = len(events(log, 'popup-choice'))
                closed_before = len(events(log, 'popup-closed'))
                source_point(session, record, 400, 46)
                wait(lambda: len(events(log, 'popup-open')) > opened, 'Popup did not open with follow_mouse='+str(follow))
                popup = wait(lambda: (values := events(log, 'popup-layout')) and values[-1], 'Popup geometry unavailable')
                source_point(session, record, popup['x']+popup['width']/2, popup['y']+popup['height']/2)
                wait(lambda: len(events(log, 'popup-choice')) > chosen, 'Popup item input failed with follow_mouse='+str(follow))
                wait(lambda: len(events(log, 'popup-closed')) > closed_before, 'Choosing an item did not close its popup')
                monitor.check();monitor_records(witness)
                assert active(record), 'An in-bounds menu unexpectedly restored or ended its source'
                source_point(session, record, 400, 46)
                wait(lambda: len(events(log, 'popup-open')) >= opened+2, 'Popup did not reopen before application Escape')
                closed = len(events(log, 'popup-closed'))
                session.keys('-k', 'Escape')
                wait(lambda: len(events(log, 'popup-closed')) > closed, 'Application Escape did not close its popup')
                monitor.check();monitor_records(witness)
                source_point(session, record, 400, 46)
                wait(lambda: len(events(log, 'popup-open')) >= opened+3, 'Popup did not reopen before exit')
                shell('dismiss')
                wait(stopped, 'Stopping with an open popup retained native ownership')
                wait(lambda: len(events(log, 'popup-closed')) >= closed+2, 'Exit did not dismiss the exact owned popup')
                monitor.check();monitor_records(witness)
            if not handoff_only:
                print('PASS popup choice, application Escape and stopping an open grab across all four focus-follow modes without exposing the stash', flush=True)

            h.eval('hl.config({input={follow_mouse=1}})')
            for destination in ('current', 'original'):
                configure('restoreDestination', destination)
                h.dispatch('focus', workspace=str(session.workspace+1))
                start(session, record)
                source_point(session, record, 555, 46)
                dialog = wait(lambda: next((client for client in h.read('clients') if client['title'] == h.client(address)['title']+' dialog'), None),
                              'Owned modal dialog did not map')
                if dialog['address'] not in session.addresses:
                    session.addresses.append(dialog['address'])
                wanted = session.workspace+1 if destination == 'current' else session.workspace
                try:
                    wait(lambda: h.client(address)['workspace']['id'] == wanted and h.client(dialog['address'])['workspace']['id'] == wanted,
                         'Modal fallback did not restore parent and exact child to '+destination, timeout=12)
                except AssertionError:
                    print('Modal handoff diagnostics:', {'destination':destination, 'wanted':wanted, 'origin':record['origin'],
                          'parent':h.client(address)['workspace'], 'child':h.client(dialog['address'])['workspace'],
                          'interaction':shell('status')['previewInteraction'],
                          'savedDestination':command('list')['settings']['restoreDestination']}, flush=True)
                    raise
                wait(stopped, 'Modal fallback retained native input')
                monitor.check();monitor_records(witness)
                assert h.client(existing['address'])['workspace']['id'] == session.workspace+2, \
                    'Modal handoff moved a pre-existing public transient'
                assert not any(item['id'] == record['id'] for item in command('list')['windows']), 'Restored modal parent retained its stash record'
                h.dispatch('window.close', window='address:'+dialog['address'])
                wait(lambda: not h.client(dialog['address']), 'Owned modal dialog did not close')
                h.dispatch('window.move', window='address:'+address, workspace=str(session.workspace), follow=True)
                record = park(session, address)
                ready(session, record)
            print('PASS modal fallback restores only the exact source and transient to current/original destinations, preserving unrelated stashes', flush=True)

            configure('restoreDestination', 'current')
            configure('floatingPreviewFullscreen', 'desktop')
            start(session, record)
            source_point(session, record, 900, 46)
            wait(lambda: h.client(address)['workspace']['name'] != SPECIAL and h.client(address)['fullscreen'] == 2,
                 'Application fullscreen request did not restore to its normal visible window', timeout=12)
            wait(stopped, 'Fullscreen handoff retained native input')
            monitor.check();monitor_records(witness)
            wait(lambda: not any(item['id'] == record['id'] for item in command('list')['windows']),
                 'Fullscreen fallback retained a partially restored ledger record')
            configure('floatingPreviewFullscreen', 'preview')
            h.dispatch('window.fullscreen_state', window='address:'+address, internal=0, client=0, action='set')
            record = park(session, address)
            ready(session, record)
            start(session, record)
            source_point(session, record, 720, 46)
            sibling = wait(lambda: next((client for client in h.read('clients') if client['title'] == h.client(address)['title']+' sibling'), None),
                           'Application-created unparented window did not map')
            session.addresses.append(sibling['address'])
            wait(lambda: h.client(sibling['address'])['workspace']['name'] != SPECIAL,
                 'New unparented window was stranded in the private stash')
            wait(stopped, 'New-window handoff retained old input ownership')
            assert h.client(address)['workspace']['name'] == SPECIAL, 'Independent new window unnecessarily restored its parent'
            assert all(item['address'] != sibling['address'] for item in command('list')['windows']), 'New unparented window was adopted as a stash record'
            monitor.check();monitor_records(witness)
            print('PASS fullscreen restores normally; an independent new window appears on the visible workspace without being adopted or exposing other stashes', flush=True)
            start(session, record)
            source_point(session, record, 890, 622)
            wait(lambda: events(log, 'edge-popup-open'), 'Oversized popup did not open')
            wait(lambda: h.client(address)['workspace']['name'] != SPECIAL,
                 'Popup outside the source capture did not restore the source', timeout=12)
            wait(stopped, 'Out-of-bounds popup fallback retained input ownership')
            wait(lambda: not any(item['id'] == record['id'] for item in command('list')['windows']),
                 'Out-of-bounds popup retained its restored ledger record')
            monitor.check();monitor_records(witness)
            assert h.client(existing['address'])['workspace']['id'] == session.workspace+2
            print('PASS out-of-bounds popup restores its source; pre-existing public transients never move', flush=True)
            record = park(session, address)
            ready(session, record)
            start(session, record)
            h.dispatch('focus', window='address:'+address)
            wait(lambda: h.client(address)['workspace']['name'] != SPECIAL,
                 'Explicit application activation did not restore its source', timeout=12)
            wait(stopped, 'Application activation retained miniature input')
            monitor.check();monitor_records(witness)
            record = park(session, address)
            ready(session, record)
            start(session, record)
            source_point(session, record, 555, 106)
            wait(lambda: events(log, 'move-request'), 'Application move request was not emitted')
            wait(lambda: h.client(address)['workspace']['name'] != SPECIAL,
                 'Application-owned move request did not restore its source', timeout=12)
            wait(stopped, 'Application move request retained miniature input')
            wait(lambda: not any(item['id'] == record['id'] for item in command('list')['windows']),
                 'Move-request fallback retained its restored ledger record')
            monitor.check();monitor_records(witness)
            print('PASS explicit application activation and native move requests restore normally without exposing the private stash', flush=True)
            record = park(session, address)
            ready(session, record)
            start(session, record)
            client = h.client(address)
            before = client['workspace'], client['at'], client['size'], client['floating']
            acknowledgements = interaction()['status'].get('status', {}).get('keyboardActivationAcknowledgements', 0)
            source_point(session, record, 890, 106)
            wait(lambda: events(log, 'activate-request'), 'Application activation request was not emitted')
            wait(lambda: interaction()['status'].get('status', {}).get('keyboardActivationAcknowledgements', 0) > acknowledgements,
                 'A redundant activation of the keyboard-focused source was not acknowledged')
            assert active(record), 'A redundant source activation ended miniature input'
            assert_source(record, before)
            monitor.check();monitor_records(witness)
            print('PASS a genuine redundant application activation preserves its already keyboard-focused preview and geometry', flush=True)

            h.dispatch('focus', window='address:'+address)
            wait(lambda: h.client(address)['workspace']['name'] != SPECIAL,
                 'Explicit WM activation was ignored while the source owned keyboard focus')
            wait(stopped, 'Explicit WM activation retained miniature input')
            record = park(session, address)
            ready(session, record)
            start(session, record)
            source_point(session, record, 890, 166)
            wait(lambda: events(log, 'activate-delayed-scheduled'), 'Delayed application activation was not scheduled')
            h.dispatch('focus', window='address:'+control)
            wait(lambda: active(record) and not interaction()['status'].get('status', {}).get('keyboardFocused'),
                 'The public control did not take keyboard focus while the input lease remained active')
            wait(lambda: events(log, 'activate-delayed-request'), 'Delayed application activation request was not emitted')
            wait(lambda: h.client(address)['workspace']['name'] != SPECIAL,
                 'A real application activation did not restore the source after external keyboard focus', timeout=12)
            wait(stopped, 'Client activation retained miniature input after external focus')
            monitor.check();monitor_records(witness)
            print('PASS explicit WM activation and genuine application activation after external keyboard focus still restore normally', flush=True)
        finally:
            shell('dismiss')
            h.eval('hl.config({input={follow_mouse='+following+'}})')
            monitor.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--handoff-only', action='store_true', help='Skip the independent four-mode popup cleanup proof')
    main(parser.parse_args().handoff_only)
