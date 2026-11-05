#!/usr/bin/env python3
"""Exercise Omarchy controls with disposable windows in an unlocked session."""
import subprocess
import time

from live import h, command, shell, configure, spawn, stash, wait, processes, addresses
from pointer import Pointer


def main():
    original = h.read('activewindow')
    workspace = h.read('activeworkspace')['id']
    settings = dict(shell('status')['settings'])
    baseline = {w['id'] for w in command('list')['windows']}
    pointer = Pointer()

    def surface():
        return next(s for s in shell('status')['surfaces'] if s['visible'])

    def click(rect, button=272):
        s = surface()
        pointer.click(rect['x'] + rect['width']/2, rect['y'] + rect['height']/2,
                      s['width'], s['height'], button)
        time.sleep(.15)

    def keys(*args):
        subprocess.run(['wtype', *args], check=True)
        time.sleep(.15)

    try:
        shell('settings')
        wait(lambda: shell('status')['dialog'] == 'settings', 'Settings did not open')
        time.sleep(.3)
        alternatives = {'presentation': ('dock', 'bubbles'), 'scope': ('global', 'workspace'),
                        'restoreDestination': ('current', 'original'), 'grouping': ('window', 'app')}
        for key, values in alternatives.items():
            control = next(c for c in surface()['settingControls'] if c['key'] == key)
            wanted = values[1] if settings[key] == values[0] else values[0]
            click(control['rect'])
            keys('-k', 'Down' if wanted == values[1] else 'Up', '-k', 'Return')
            wait(lambda: shell('status')['settings'][key] == wanted, 'Dropdown failed: ' + key)
            configure(key, settings[key])
            wait(lambda: next(c for c in surface()['settingControls'] if c['key'] == key)['value'] == settings[key],
                 'Dropdown did not follow external setting: ' + key)
        print('PASS four native dropdowns and saved-setting synchronization', flush=True)
        shell('dismiss')

        first = spawn('Stash themed UI alpha')
        second = spawn('Stash themed UI beta')
        one, two = stash(first), stash(second)
        configure('scope', 'global')
        configure('presentation', 'bubbles')
        configure('grouping', 'app')
        wait(lambda: any(s['bubbles'] for s in shell('status')['surfaces']), 'Bubbles missing')
        s = surface()
        # Both disposable GTK windows share an application; unrelated stash entries remain untouched.
        group_key = 'app:' + next(w['app'] for w in command('list')['windows'] if w['id'] == one).lower()
        bubble = next(b for b in s['bubbles'] if b['key'] == group_key)
        click(bubble)
        wait(lambda: shell('status')['dialog'] == 'picker', 'Grouped bubble did not open chooser')
        keys('Stash themed UI alpha')
        wait(lambda: surface()['pickerCount'] == 1, 'Themed search did not filter')
        subprocess.run(['grim', '-o', s['screen'], '/tmp/stash-themed-picker.png'], check=True)
        keys('-k', 'Return')
        wait(lambda: all(w['id'] != one for w in command('list')['windows']), 'Enter did not restore')
        print('PASS themed bubble, grouped picker, search and keyboard restore', flush=True)

        configure('grouping', 'window')
        record = next(w for w in command('list')['windows'] if w['id'] == two)
        window_key = 'window:' + str(record.get('stableId') or two)
        s = wait(lambda: next((s for s in shell('status')['surfaces']
                              if any(b['key'] == window_key for b in s['bubbles'])), None), 'Individual bubble missing')
        click(next(b for b in s['bubbles'] if b['key'] == window_key), 273)
        wait(lambda: shell('status')['dialog'] == 'menu', 'Context menu missing')
        click(surface()['actions']['original'])
        wait(lambda: all(w['id'] != two for w in command('list')['windows']), 'Native context action failed')
        print('PASS themed context menu and original-workspace restore', flush=True)

        # Minimize last so our test icon is the first dock entry, even with an existing stash.
        last = stash(second)
        configure('presentation', 'dock')
        s = wait(lambda: next((s for s in shell('status')['surfaces'] if s['visible']), None), 'Dock missing')
        r = s['shelf']
        pointer.click(r['x'] + 31, r['y'] + r['height']/2, s['width'], s['height'])
        wait(lambda: all(w['id'] != last for w in command('list')['windows']), 'Themed dock click failed')
        assert not shell('status')['error'], shell('status')
        assert {w['id'] for w in command('list')['windows']} == baseline
        print('PASS themed dock restore; existing stash preserved', flush=True)
    finally:
        shell('dismiss')
        for address in addresses:
            if h.client(address):
                h.dispatch('window.close', window='address:' + address)
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for key, value in settings.items():
            configure(key, value)
        h.dispatch('focus', workspace=str(workspace))
        if original.get('address') and h.client(original['address']):
            h.dispatch('focus', window='address:' + original['address'])
        pointer.close()


if __name__ == '__main__':
    main()
