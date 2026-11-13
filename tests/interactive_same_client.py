#!/usr/bin/env python3
"""Existing sibling windows sharing one Wayland client must not share input ownership."""
import os
from pathlib import Path
import tempfile
import uuid

from desktop_test import desktop_test
from interactive_bridge import begin, end, events, native_status, spawn_fixture
from interactive_keyboard import content_click, key_count
from live import command, configure, h, wait
from native_session import NativeSession
from preview import PreviewBridge
from stash import SPECIAL


@desktop_test('Isolated same-client preview keyboard focus regression')
def main():
    assert os.environ.get('WINDOW_STASH_ISOLATED_TEST') == '1' and (Path.home()/'.window-stash-isolated').is_file()
    assert not command('list')['windows']
    PreviewBridge(h).ensure()
    with tempfile.TemporaryDirectory(prefix='stash-same-client-') as temporary, NativeSession() as session:
        configure('presentation', 'dock');configure('hoverPreview', 'off')
        log = Path(temporary)/'source.jsonl'
        address = spawn_fixture(session, log)
        source = h.client(address)
        title = source['title']+' sibling'
        session.move(source['at'][0]-session.monitor['x']+720, source['at'][1]-session.monitor['y']+46)
        session.pointer.click(*session.point(source['at'][0]-session.monitor['x']+720,
                                            source['at'][1]-session.monitor['y']+46))
        sibling = wait(lambda: next((client for client in h.read('clients') if client['title'] == title), None),
                       'Same-client public sibling did not open')
        session.addresses.append(sibling['address'])
        assert sibling['pid'] == source['pid'], 'Sibling fixture did not share its GTK application process'
        record = session.park(address)
        h.dispatch('focus', window='address:'+sibling['address'])
        rect = dict(x=session.monitor['x']+400, y=session.monitor['y']+300, width=400, height=280)
        owner = uuid.uuid4().hex
        try:
            begin(owner, record, session.monitor['name'], rect, keyboard=True)
            content_click(session, rect, source['size'], 750, 525)
            wait(lambda: native_status(owner)['keyboardFocused'], 'Hidden source did not acquire keyboard focus')
            session.keys('h')
            wait(lambda: key_count(log, 'h') == 1, 'Hidden source did not receive its own key')
            begin(owner, record, session.monitor['name'], rect, keyboard=True)
            h.dispatch('focus', window='address:'+sibling['address'])
            wait(lambda: not native_status(owner)['keyboardFocused'],
                 'Another window sharing the Wayland client retained hidden-source keyboard ownership')
            assert h.read('activewindow').get('address') == sibling['address'], 'Focus getter kept identifying the hidden source'
            before = key_count(log, 'j')
            session.keys('j')
            wait(lambda: any(item.get('text') == 'j' for item in events(log, 'sibling-text')),
                 'Typing did not reach the same-client public sibling')
            assert key_count(log, 'j') == before, 'Typing in the public sibling leaked into the hidden source'
            assert h.client(address)['workspace']['name'] == SPECIAL, 'Sibling focus exposed or restored the hidden source'
            assert h.read('activeworkspace')['id'] == session.workspace, 'Sibling focus changed the visible workspace'
            begin(owner, record, session.monitor['name'], rect, keyboard=True)
            content_click(session, rect, source['size'], 750, 525)
            wait(lambda: native_status(owner)['keyboardFocused'], 'Explicit source click did not reacquire keyboard focus')
            end(owner)
            wait(lambda: h.read('activewindow').get('address') == sibling['address'], 'Exiting did not restore the exact same-client sibling focus')
            print('PASS same-client sibling focus releases hidden keyboard ownership, preserves correct window commands, routes typing once and restores exact focus on exit', flush=True)
        finally:
            end(owner)


if __name__ == '__main__':
    main()
