#!/usr/bin/env python3
"""Exercise Omarchy controls with disposable windows in an unlocked session."""
import subprocess
import time

from live import h, command, shell, configure, spawn, stash, wait, processes, addresses,fixture_settings
from pointer import Pointer
from desktop_test import desktop_test


@desktop_test('Window Stash themed controls test')
def main():
    original = h.read('activewindow')
    workspace = h.read('activeworkspace')['id']
    settings = dict(shell('status')['settings'])
    baseline = {w['id'] for w in command('list')['windows']}
    pointer = Pointer()
    monitor_name=next(m['name'] for m in h.read('monitors') if m['focused'])

    def surface():
        return next(s for s in shell('status')['surfaces'] if s['screen']==monitor_name)

    def point(x,y):
        monitors=h.read('monitors');monitor=next(m for m in monitors if m['name']==monitor_name)
        left=min(m['x'] for m in monitors);top=min(m['y'] for m in monitors)
        right=max(m['x']+round(m['width']/m['scale']) for m in monitors)
        bottom=max(m['y']+round(m['height']/m['scale']) for m in monitors)
        return monitor['x']+x-left,monitor['y']+y-top,right-left,bottom-top

    def click(rect, button=272):
        pointer.click(*point(rect['x'] + rect['width']/2, rect['y'] + rect['height']/2),button=button)
        time.sleep(.15)

    def keys(*args):
        subprocess.run(['wtype', *args], check=True)
        time.sleep(.15)

    try:
        fixture_settings()
        shell('settings')
        wait(lambda: shell('status')['dialog'] == 'settings', 'Settings did not open')
        time.sleep(.3)
        alternatives = {'presentation': ('dock', 'bubbles', 'floating'), 'scope': ('global', 'workspace'),
                        'restoreDestination': ('current', 'original'), 'grouping': ('window', 'app')}
        for key, values in alternatives.items():
            control = next(c for c in surface()['settingControls'] if c['key'] == key)
            wanted_index = (values.index(settings[key]) + 1) % len(values)
            wanted = values[wanted_index]
            click(control['rect'])
            wait(lambda: next(c for c in surface()['settingControls'] if c['key']==key)['open'], 'Dropdown did not open: '+key)
            keys(*(['-k','Up']*len(values)+['-k','Down']*wanted_index+['-k','Return']))
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
        configure('dockSide', 'bottom')
        configure('presentation', 'dock')
        s = wait(lambda: surface() if surface()['visible'] else None, 'Dock missing')
        r = s['shelf']
        pointer.click(*point(r['x'] + 31, r['y'] + r['height']/2))
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
