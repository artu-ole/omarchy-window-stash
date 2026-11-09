#!/usr/bin/env python3
"""Scrolling width regression on an isolated, temporary headless output."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from live import ROOT, h, wait
from desktop_test import desktop_test


@desktop_test('Window Stash scrolling width test')
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installed', action='store_true')
    args = parser.parse_args()
    controller = [str(Path.home()/'.config/omarchy/plugins/community.window-stash/window-stash')] if args.installed else [sys.executable, str(ROOT/'controller/stash.py')]
    original = h.read('activewindow')
    original_workspace = h.read('activeworkspace')['id']
    monitors = h.read('monitors')
    processes, addresses = [], []
    output = None
    rule_key = '__window_stash_width_test_' + str(os.getpid())
    base = 1000000 + os.getpid()*10
    assert all(w['id'] not in range(base, base+10) for w in h.read('workspaces'))

    def command(*arguments):
        result = subprocess.run([*controller, *map(str, arguments)], capture_output=True, text=True, check=True)
        return json.loads(result.stdout)

    baseline = {r['id'] for r in command('list')['windows']}

    def rule(workspace, layout='scrolling', direction='right'):
        h.eval('table.insert(_G.%s, hl.workspace_rule({workspace=%s, layout=%s, layout_opts={direction=%s}}))' %
               (rule_key, json.dumps(str(workspace)), json.dumps(layout), json.dumps(direction)))

    def spawn(workspace, title):
        h.dispatch('focus', monitor=output)
        h.dispatch('focus', workspace=str(workspace))
        env = dict(os.environ, GDK_BACKEND='wayland', PYTHONDONTWRITEBYTECODE='1')
        process = subprocess.Popen(['/usr/bin/python3', str(ROOT/'tests/test-window.py'), title],
                                   env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        processes.append(process)
        client = wait(lambda: next((c for c in h.read('clients') if c['title'] == title), None), 'Test window missing')
        addresses.append(client['address'])
        h.dispatch('window.move', window='address:'+client['address'], workspace=str(workspace), follow=True)
        h.dispatch('window.float', window='address:'+client['address'], action='off')
        return client['address']

    def cycle(address, destination, original=False):
        width = h.client(address)['size'][0]
        ident = command('minimize', '--address', address)['id']
        command('restore', ident, '--to', 'original' if original else 'current',
                '--monitor', output, '--workspace', destination)
        client = h.client(address)
        assert client['workspace']['id'] == destination, client
        assert not client['floating'], client
        assert abs(client['size'][0]-width) <= 1, (width, client['size'][0])
        h.eval('''local w=hl.get_window(%s)
for _, other in pairs(hl.get_workspace_windows(w.workspace)) do
  if other.address~=w.address and not other.floating then
    assert(w.layout.column.index > other.layout.column.index, "Restored column is not last")
  end
end''' % json.dumps('address:'+address))
        return width

    try:
        h.eval('_G.%s = {}' % rule_key)
        h.call('output', 'create', 'headless')
        output = wait(lambda: next((m['name'] for m in h.read('monitors')
                                  if m['name'] not in {m['name'] for m in monitors}), None), 'Test output missing')
        end = max(m['x'] + round(m['width']/m['scale']) for m in monitors)
        h.eval('hl.monitor({output=%s,mode="1920x1080@60",position=%s,scale=1})' %
               (json.dumps(output), json.dumps('%dx0' % end)))
        for index, direction in enumerate(('right', 'left')):
            workspace = base+index
            rule(workspace, direction=direction)
            windows = [spawn(workspace, 'Stash width %s %s %s' % (os.getpid(), direction, n)) for n in range(3)]
            address = windows[0]
            for fraction in (0.31, 0.78):
                h.dispatch('focus', window='address:'+address)
                h.eval('hl.dispatch(hl.dsp.layout("colresize %s"))' % fraction)
                width = cycle(address, workspace)
                cycle(address, workspace, original=True)
                print('PASS %s scrolling width %s px and end-column placement across repeated restores' % (direction, width), flush=True)

        # Different workspace and destination layout.
        source = addresses[0]
        destination = base+1
        h.dispatch('focus', window='address:'+source)
        cycle(source, destination)
        print('PASS saved width on a different scrolling workspace', flush=True)

        # Maximizing/fullscreening must preserve the underlying column width too.
        for state in (1, 2):
            width = h.client(source)['size'][0]
            h.dispatch('focus', window='address:'+source)
            h.dispatch('window.fullscreen_state', window='address:'+source, internal=state, client=state, action='set')
            ident = command('minimize', '--address', source)['id']
            command('restore', ident, '--to', 'current', '--monitor', output, '--workspace', destination)
            assert h.client(source)['fullscreen'] == state
            h.dispatch('window.fullscreen_state', window='address:'+source, internal=0, client=0, action='set')
            assert abs(h.client(source)['size'][0]-width) <= 1
        print('PASS underlying width after maximized/fullscreen stash and restore', flush=True)

        rule(base+2, layout='dwindle')
        ident = command('minimize', '--address', source)['id']
        command('restore', ident, '--to', 'current', '--monitor', output, '--workspace', base+2)
        assert not h.client(source)['floating']
        assert {r['id'] for r in command('list')['windows']} == baseline
        print('PASS dwindle restoration and existing-stash preservation', flush=True)
    finally:
        for address in addresses:
            if h.client(address):
                h.dispatch('window.close', window='address:'+address)
        for process in processes:
            if process.poll() is None:
                process.terminate()
        h.eval('if _G.%s then for _, rule in ipairs(_G.%s) do rule:set_enabled(false) end; _G.%s=nil end' %
               (rule_key, rule_key, rule_key))
        if output:
            h.call('output', 'remove', output)
        h.dispatch('focus', workspace=str(original_workspace))
        if original.get('address') and h.client(original['address']):
            h.dispatch('focus', window='address:'+original['address'])


if __name__ == '__main__':
    main()
