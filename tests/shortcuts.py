#!/usr/bin/env python3
"""Native shortcut editing, conflict rejection and FIFO/LIFO keyboard actions.

Run after installing this checkout in an unlocked Hyprland session. Only owned
fixtures are stashed; NativeSession restores settings, positions and focus.
"""
from collections import Counter
import json
import time

from desktop_test import desktop_test
from live import command, configure, h, shell, wait
from native_session import NativeSession
from shortcuts import normalize
from stash import SPECIAL


KEYS = ('minimizeShortcut', 'restoreLastShortcut', 'restoreOldestShortcut')
MODIFIERS = (('SUPER', 64, 'logo'), ('CTRL', 4, 'ctrl'), ('ALT', 8, 'alt'), ('SHIFT', 1, 'shift'))
OLDEST_DESCRIPTION = 'Window Stash: restore oldest minimized'


def owned():
    # Inspect the installed manager without loading or replacing its methods.
    return json.loads(h.call('repl', 'local m=_community_window_stash_shortcuts; return m and m.inspect() or "[]"'))


def identity(binding):
    return tuple(binding.get(k, '') for k in ('dispatcher', 'arg', 'description', 'modmask')) + \
        (str(binding.get('key', '')).lower(), binding.get('submap', ''))


def foreign_bindings():
    registered = Counter(identity(b) for b in owned())
    result = []
    for binding in h.read('binds'):
        key = identity(binding)
        if registered[key]:
            registered[key] -= 1
        else:
            result.append(binding)
    return result


def active_signature():
    return sorted(identity(b) for b in owned() if b.get('enabled') is True)


def free_chords(settings):
    foreign = foreign_bindings()
    occupied = {(b.get('modmask'), str(b.get('key', '')).upper()) for b in foreign}
    current = {settings.get(key) for key in KEYS}
    result = ['SUPER + CTRL + ALT + F'+str(n) for n in range(24, 0, -1)
              if (76, 'F'+str(n)) not in occupied and 'SUPER + CTRL + ALT + F'+str(n) not in current]
    assert len(result) >= 4, 'Four unused test chords were not available'
    return result[:4]


def foreign_chord():
    for binding in foreign_bindings():
        mask = binding.get('modmask', 0)
        if not isinstance(mask, int) or mask & ~77 or binding.get('submap', '') not in ('', 'reset'):
            continue
        chord = ' + '.join([name for name, bit, _ in MODIFIERS if mask & bit] + [str(binding.get('key', ''))])
        try:
            return normalize(chord)
        except ValueError:
            continue
    raise AssertionError('No existing keyboard shortcut was available for the conflict test')


def control(session, key):
    return next(c for c in session.surface()['shortcutControls'] if c['key'] == key)


def contained(rect, viewport):
    return rect['width'] > 0 and rect['height'] > 0 and rect['x'] >= viewport['x']-.1 \
        and rect['x']+rect['width'] <= viewport['x']+viewport['width']+.1 \
        and rect['y'] >= viewport['y']+.1 and rect['y']+rect['height'] <= viewport['y']+viewport['height']-.1


def reveal(session, key, part='fieldRect'):
    from settings_fit import reveal as reveal_rect

    return reveal_rect(session, lambda: control(session, key)[part])


def open_settings(session):
    shell('settings')
    wait(lambda: session.surface()['dialog']['visible'], 'Shortcut settings did not open')
    wait(lambda: len(session.surface()['shortcutControls']) == 3, 'Shortcut controls were not created')


def edit(session, key, value, enter=False):
    session.click(reveal(session, key))
    session.keys('-M', 'ctrl', '-k', 'a', '-m', 'ctrl')
    if value:
        session.keys(value)
    else:
        session.keys('-k', 'BackSpace')
    wait(lambda: control(session, key)['text'] == value, 'Shortcut draft did not accept text')
    if enter:
        session.keys('-k', 'Return')
    else:
        session.click(reveal(session, key, 'applyRect'))


def saved(session, key, value):
    expected = normalize(value)
    wait(lambda: shell('status')['settings'].get(key) == expected
         and not control(session, key)['pending'] and not control(session, key)['dirty'],
         'Shortcut was not saved and acknowledged: '+key)
    wait(lambda: not shell('status')['controllerBusy'] and not shell('status')['queueLength'],
         'Shortcut controller did not finish')
    assert control(session, key)['text'] == expected, 'Saved shortcut text was not normalized'
    assert not shell('status')['error'], shell('status')['error']


def rejected(session, key, value):
    previous = dict(shell('status')['settings'])
    bindings = active_signature()
    edit(session, key, value)
    wait(lambda: shell('status')['error'] and not control(session, key)['pending'], 'Conflicting shortcut was not rejected')
    assert shell('status')['settings'] == previous, 'Rejected shortcut changed persisted settings'
    assert active_signature() == bindings, 'Rejected shortcut changed active bindings'
    assert control(session, key)['text'] == value and control(session, key)['dirty'], 'Rejected edit lost its draft'


def trigger(session, chord):
    parts = chord.split(' + ')
    names = {name: native for name, _, native in MODIFIERS}
    modifiers = [names[name] for name in parts[:-1]]
    args = [value for modifier in modifiers for value in ('-M', modifier)]
    args += ['-s', '30', '-k', parts[-1], '-s', '30']
    args += [value for modifier in reversed(modifiers) for value in ('-m', modifier)]
    session.keys(*args)


def record_for(address):
    return next((w for w in command('list')['windows'] if w['address'] == address), None)


def restored(address, before):
    client = h.client(address)
    assert client and client['workspace']['name'] != SPECIAL and client['floating'], 'Shortcut did not restore the floating client'
    assert client['at'] == before['at'] and client['size'] == before['size'], 'Shortcut restore lost floating geometry'


@desktop_test('Configurable shortcuts and FIFO restore test')
def main():
    with NativeSession() as session:
        configure('sizePreset', '100')
        configure('animationSpeed', 'normal')
        assert not any(w['origin']['id'] in range(session.workspace, session.workspace+5)
                       for w in session.snapshot['windows']), 'Test workspace overlaps an existing stash origin'
        configure('presentation', 'dock')
        configure('animations', 'off')
        configure('hoverPreview', 'off')
        configure('restoreDestination', 'current')
        minimize, newest, oldest, replacement = free_chords(shell('status')['settings'])
        foreign = foreign_chord()
        open_settings(session)
        edit(session, KEYS[0], minimize.lower().replace(' + ', '+'))
        saved(session, KEYS[0], minimize)
        edit(session, KEYS[1], newest, enter=True)
        saved(session, KEYS[1], newest)
        edit(session, KEYS[2], oldest)
        saved(session, KEYS[2], oldest)
        rejected(session, KEYS[2], newest)
        rejected(session, KEYS[2], foreign)
        edit(session, KEYS[2], oldest, enter=True)
        saved(session, KEYS[2], oldest)
        session.click(reveal(session, KEYS[2], 'defaultRect'))
        saved(session, KEYS[2], '')
        assert not any(b.get('enabled') and b.get('description') == OLDEST_DESCRIPTION for b in owned())
        edit(session, KEYS[2], oldest)
        saved(session, KEYS[2], oldest)
        session.click(reveal(session, KEYS[2], 'clearRect'))
        saved(session, KEYS[2], '')
        edit(session, KEYS[2], oldest, enter=True)
        saved(session, KEYS[2], oldest)
        assert len(active_signature()) == 3, 'Shortcut edits left duplicate enabled handles'
        shell('dismiss')
        wait(lambda: not session.surface()['dialog']['rendered'], 'Settings did not dismiss')
        print('PASS native shortcut edits, normalization, Return/Apply, clear/default and non-destructive conflict rejection', flush=True)

        matching = h.call('repl', 'return hl.get_config("input.resolve_binds_by_sym")')
        assert matching in ('true','false'), 'Could not read the original shortcut-matching option'
        try:
            h.eval('hl.config({input={resolve_binds_by_sym=true}})')
            addresses, geometry = [], {}
            for index in range(3):
                address, _ = session.spawn(workspace=session.workspace)
                addresses.append(address)
                h.dispatch('window.float', window='address:'+address, action='on')
                h.dispatch('window.resize', window='address:'+address, x=420+index*70, y=300+index*35, relative=False)
                h.dispatch('window.move', window='address:'+address,
                           x=session.monitor['x']+120+index*35, y=session.monitor['y']+140+index*25, relative=False)
                h.dispatch('focus', window='address:'+address)
                wait(lambda: h.read('activewindow').get('address') == address, 'Owned minimize target did not focus')
                geometry[address] = h.client(address)
                trigger(session, minimize)
                record = wait(lambda: record_for(address), 'Configured minimize shortcut did not stash its target')
                wait(lambda: h.client(address)['workspace']['name'] == SPECIAL, 'Minimize did not finish')
                session.touch('window:'+str(record.get('stableId') or record['id']))
                session.touch('app:'+record['app'].lower()); session.touch('dock:floating')
            trigger(session, oldest)
            wait(lambda: record_for(addresses[0]) is None, 'FIFO shortcut did not restore the oldest window')
            restored(addresses[0], geometry[addresses[0]])
            assert all(h.client(a)['workspace']['name'] == SPECIAL for a in addresses[1:]), 'FIFO restored another window'
            trigger(session, newest)
            wait(lambda: record_for(addresses[2]) is None, 'LIFO shortcut did not restore the newest window')
            restored(addresses[2], geometry[addresses[2]])
            assert h.client(addresses[1])['workspace']['name'] == SPECIAL, 'LIFO restored the middle window'
            trigger(session, oldest)
            wait(lambda: record_for(addresses[1]) is None, 'FIFO did not restore the remaining window')
            restored(addresses[1], geometry[addresses[1]])
            print('PASS configured keyboard minimize, FIFO/LIFO order and exact floating geometry', flush=True)

            configure(KEYS[0], replacement)
            h.dispatch('focus', window='address:'+addresses[0])
            wait(lambda: h.read('activewindow').get('address') == addresses[0], 'Rebind target did not focus')
            trigger(session, minimize); time.sleep(.2)
            assert record_for(addresses[0]) is None, 'The old minimize chord stayed enabled after rebinding'
            trigger(session, replacement)
            wait(lambda: record_for(addresses[0]), 'Replacement minimize chord did not activate')
            configure(KEYS[2], '')
            trigger(session, oldest); time.sleep(.2)
            assert record_for(addresses[0]), 'A disabled FIFO shortcut still restored a window'
            trigger(session, newest)
            wait(lambda: record_for(addresses[0]) is None, 'Newest shortcut did not recover the final fixture')
            restored(addresses[0], geometry[addresses[0]])
            assert len(active_signature()) == 2, 'Disabled FIFO left an enabled historical handle'
            print('PASS rebind disables only the previous chord and blank FIFO disables its action', flush=True)
        finally:
            h.eval('hl.config({input={resolve_binds_by_sym='+matching+'}})')


if __name__ == '__main__':
    main()
