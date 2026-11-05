#!/usr/bin/env python3
"""Live icon-shape controls, input masks, drag, and persistence regression."""
import json
import subprocess
import time

from live import h, shell, command, configure, spawn, stash, wait, processes, addresses
from pointer import Pointer
from desktop_test import desktop_test


@desktop_test('Window Stash icon shapes test')
def main():
    original = h.read('activewindow')
    workspace = h.read('activeworkspace')['id']
    settings = dict(shell('status')['settings'])
    baseline = {w['id'] for w in command('list')['windows']}
    pointer = Pointer()
    monitor = next(m for m in h.read('monitors') if m['focused'])

    def surface():
        return next(s for s in shell('status')['surfaces'] if s['screen'] == monitor['name'])

    def point(x, y):
        monitors = h.read('monitors')
        left = min(m['x'] for m in monitors); top = min(m['y'] for m in monitors)
        right = max(m['x']+round(m['width']/m['scale']) for m in monitors)
        bottom = max(m['y']+round(m['height']/m['scale']) for m in monitors)
        return monitor['x']+x-left, monitor['y']+y-top, right-left, bottom-top

    def click(x, y):
        pointer.click(*point(x, y))

    def bubble():
        record = next(w for w in command('list')['windows'] if w['address'] == target)
        key = 'window:'+str(record.get('stableId') or record['id'])
        return next((b for b in surface()['bubbles'] if b['key'] == key), None)

    def restored():
        return all(w['address'] != target for w in command('list')['windows'])

    try:
        configure("floatingPlacement","free")
        shell('settings')
        configure('iconShape', 'auto')
        def setting_control():
            return next(c for c in surface()['settingControls'] if c['key'] == 'iconShape')
        def control_ready():
            s = surface(); c = setting_control(); d = s['dialog']; r = c['rect']
            return c if c['value'] == 'auto' and d['visible'] and d['y'] < r['y'] and r['y']+r['height'] < d['y']+d['height'] else None
        control = wait(control_ready, 'Shape selector did not become ready')
        r = control['rect']; click(r['x']+r['width']/2, r['y']+r['height']/2)
        wait(lambda: setting_control()['open'], 'Native shape dropdown did not open')
        subprocess.run(['wtype', *sum((['-k', 'Down'] for _ in range(4)), []), '-k', 'Return'], check=True)
        wait(lambda: shell('status')['settings']['iconShape'] == 'squircle', 'Shape dropdown did not save')
        assert all(shell('status')['settings'][k] == v for k, v in settings.items() if k not in ('iconShape','floatingPlacement'))
        shell('dismiss')
        print('PASS native shape dropdown; other preferences preserved', flush=True)

        target = spawn('Stash icon shape target')
        monitor = next(m for m in h.read('monitors') if m['focused'])
        configure('scope', 'global'); configure('grouping', 'window'); configure('presentation', 'bubbles')
        stash(target)
        for shape in ('auto', 'circle', 'square', 'rounded', 'squircle'):
            configure('iconShape', shape)
            b = wait(lambda: b if (b := bubble()) and b['shape'] == shape else None, 'Bubble shape did not update')
            under = spawn('Stash shape passthrough '+shape)
            h.dispatch('window.float', window='address:'+under, action='on')
            h.dispatch('window.resize', window='address:'+under, x=640, y=420, relative=False)
            s = surface()
            h.dispatch('window.move', window='address:'+under,
                       x=monitor['x']+max(0, min(s['width']-640, b['x']-300)),
                       y=monitor['y']+max(30, min(s['height']-420, b['y']-180)), relative=False)
            time.sleep(.15)
            subprocess.run(['grim', '-g', '%d,%d 60x60' % (monitor['x']+b['x']-6, monitor['y']+b['y']-6),
                            '/tmp/stash-icon-shape-'+shape+'.png'], check=True)
            click(b['x']+(3 if shape == 'square' else 1), b['y']+(3 if shape == 'square' else 1))
            if shape == 'square':
                wait(restored, 'Square corner was not clickable; bubble='+json.dumps(b)+' under='+h.client(under)['title'])
            else:
                wait(lambda: h.client(under)['title'].endswith(' clicked'), 'Transparent corner swallowed input: '+shape)
                assert not restored(), 'Transparent corner restored the target: '+shape
                # This point is inside a squircle but outside a circle.
                offset = 6 if shape == 'squircle' else 24
                click(b['x']+offset, b['y']+offset)
                wait(restored, 'Visible icon did not restore: '+shape)
            h.dispatch('window.close', window='address:'+under)
            stash(target)
            print('PASS %s bubble drawing, corner input, and restore' % shape, flush=True)

        b = bubble()
        x, y = b['x']+24, b['y']+24
        pointer.move(*point(x, y)); pointer.button(True)
        for step in range(1, 6):
            pointer.move(*point(x-step*16, y+step*6)); time.sleep(.03)
        pointer.button(False)
        moved = wait(lambda: bubble() if abs(bubble()['x']-b['x'])>50 else None, 'Squircle drag failed')
        configure('dockSide', 'bottom')
        configure('presentation', 'dock')
        configure('presentation', 'bubbles')
        wait(lambda: abs(bubble()['x']-moved['x'])<2 and abs(bubble()['y']-moved['y'])<2, 'Saved shape position changed')
        print('PASS squircle drag and position across presentation changes', flush=True)

        subprocess.run(['omarchy', 'restart', 'shell'], check=True)
        def loaded():
            result = subprocess.run(['omarchy-shell', 'window-stash', 'status'], capture_output=True, text=True)
            return json.loads(result.stdout) if result.returncode == 0 and result.stdout.startswith('{') else None
        def ready():
            status = loaded()
            return status if status and status['settings']['iconShape'] == 'squircle' else None
        status = wait(ready, 'Saved shape did not load after restart', timeout=15)
        assert not status['error'], status['error']
        wait(lambda: b if (b := bubble()) and b['shape'] == 'squircle' else None, 'Shape did not survive restart')
        configure('dockSide', 'bottom')
        configure('presentation', 'dock')
        s = surface(); shelf = s['shelf']
        click(shelf['x']+31, shelf['y']+shelf['height']/2)
        wait(restored, 'Squircle dock icon did not restore')
        assert {w['id'] for w in command('list')['windows']} == baseline
        print('PASS saved shape after restart, squircle dock restore, and existing stash preserved', flush=True)
    finally:
        shell('dismiss')
        for address in addresses:
            if h.client(address): h.dispatch('window.close', window='address:'+address)
        for process in processes:
            if process.poll() is None: process.terminate()
        for key, value in settings.items(): configure(key, value)
        h.dispatch('focus', workspace=str(workspace))
        if original.get('address') and h.client(original['address']):
            h.dispatch('focus', window='address:'+original['address'])
        pointer.close()


if __name__ == '__main__':
    main()
