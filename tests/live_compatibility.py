#!/usr/bin/env python3
"""Actual Ghostty/btop and browser pixel updates through scoped live leases.

Install this checkout first. Uses disposable profiles, local canvas content and
NativeSession's preserving cleanup. No user's terminal/browser is touched.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

from desktop_test import desktop_test
from hover_previews import captured, captured_tiles, current_focus, hidden, hover, icon_ready, image_rect, preview, tile_for, window_key
from live import command, configure, h, shell, wait
from native_session import NativeSession
from stash import SPECIAL


def bridge_status():
    code = ('local p=hl.plugin.window_stash_preview; if not p then return "{}" end; '
            'local s=p.status(); return string.format('
            "'{\"owners\":%d,\"windows\":%d,\"frames\":%d,\"preventedSuspends\":%d}',"
            's.owners,s.windows,s.frames,s.preventedSuspends)')
    return json.loads(h.call('repl', code))


def frame_samples(session, record, count=7):
    hashes = []
    for _ in range(count):
        def ready_tile():
            tile = tile_for(preview(session), record)
            return tile if tile and tile['visible'] and tile['image']['hasContent'] else None
        tile = wait(ready_tile, 'Live preview source tile is not visible')
        rect = tile['imageRect']
        # Sample only our source's central pixels, excluding card/title effects.
        x = round(session.monitor['x']+rect['x']+rect['width']*.1)
        y = round(session.monitor['y']+rect['y']+rect['height']*.1)
        geometry = f'{x},{y} {max(1,round(rect["width"]*.8))}x{max(1,round(rect["height"]*.8))}'
        pixels = subprocess.check_output(['grim', '-s', '1', '-t', 'ppm', '-g', geometry, '-'],
                                         stderr=subprocess.DEVNULL)
        hashes.append(hashlib.sha256(pixels).hexdigest())
        time.sleep(.45)
    return hashes


def spawn(session, executable, directory):
    title = f'Stash live compatibility {executable} {os.getpid()} {time.monotonic_ns()}'
    env = dict(os.environ)
    if executable == 'ghostty':
        config = directory/'btop.conf'
        config.write_text('update_ms = 200\ncheck_temp = false\n')
        args = ['ghostty', '--config-default-files=false', '--gtk-single-instance=false', '--confirm-close-surface=false',
                '--class=org.windowstash.LiveGhostty', '--title='+title,
                '-e', 'btop', '--force-utf', '--config', str(config), '--update', '200']
    else:
        page = directory/(executable+'.html')
        page.write_text('<!doctype html><title>'+title+'</title><style>body{margin:0}canvas{width:100vw;height:100vh}</style>'
                        '<canvas width="800" height="500"></canvas><script>let n=0;const c=document.querySelector("canvas").getContext("2d");'
                        'function draw(){c.fillStyle=["#e52a40","#1acb56","#2447df"][n++%3];c.fillRect(0,0,800,500);'
                        'c.fillStyle="white";c.font="70px sans-serif";c.fillText("Live frame "+n,60,250)}draw();setInterval(draw,250)</script>')
        args = [executable, '--user-data-dir='+str(directory/(executable+'-profile')), '--no-first-run',
                '--no-default-browser-check', '--disable-background-networking', '--disable-component-update',
                '--disable-sync', '--disable-features=MediaRouter', '--ozone-platform=wayland',
                '--app='+page.as_uri(), '--class=org.windowstash.LiveBrowser']
        # Only the disposable, network-isolated compositor needs this fallback.
        if Path('/mnt/ready').exists() and Path('/mnt/source.txt').exists():
            args.append('--no-sandbox')
    process = subprocess.Popen(args, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    session.processes.append(process)
    client = wait(lambda: next((c for c in h.read('clients') if title in c['title']), None),
                  executable+' live fixture did not map', timeout=20)
    session.addresses.append(client['address'])
    time.sleep(1)
    return client['address']


def ready(record):
    value = shell('status')['previewCompatibility']
    if value.get('error'):
        raise AssertionError('Enhanced preview support failed: '+value['error'])
    status = value.get('status', {})
    return status.get('state') == 'ready' and record['id'] in status.get('ids', [])


@desktop_test('Enhanced live preview rendering tests')
def main(apps):
    with tempfile.TemporaryDirectory(prefix='stash-live-fixtures-') as temporary, NativeSession() as session:
        directory = Path(temporary)
        for key, value in dict(presentation='dock', scope='workspace', grouping='window', hoverPreview='live',
                               livePreviewCompatibility='standard', previewDelay=0, previewHideDelay=100,
                               dockSide='bottom', animations='off', iconOpacity=100, dockOpacity=100,
                               sizePreset='100', restoreDestination='current').items():
            configure(key, value)
        control, _ = session.spawn(app='org.windowstash.LiveControl')
        for index, executable in enumerate(apps):
            configure('presentation', ('dock', 'bubbles', 'floating')[index % 3])
            assert shutil.which(executable), 'Required fixture executable is missing: '+executable
            address = spawn(session, executable, directory)
            record = session.park(address)
            h.dispatch('focus', window='address:'+control)
            baseline_focus = current_focus()
            client = h.client(address)
            baseline_geometry = (client['at'], client['size'])
            key = None if shell('status')['settings']['presentation'] == 'floating' else window_key(record)
            hover(session, icon_ready(session, key), record)
            captured(session, record)
            time.sleep(.3)
            standard = frame_samples(session, record)
            configure('livePreviewCompatibility', 'enhanced')
            wait(lambda: ready(record), 'Enhanced preview lease did not become ready', timeout=150)
            active = wait(lambda: s if (s:=bridge_status()).get('windows') == 1 else None,
                          'Native bridge did not acquire exactly the previewed window')
            enhanced = frame_samples(session, record, count=9)
            assert len(set(enhanced)) >= 3, (executable, 'Enhanced preview pixels remained frozen',
                                             len(set(enhanced)), bridge_status())
            assert current_focus() == baseline_focus, 'Enhanced preview changed focus or workspace'
            client = h.client(address)
            assert client['workspace']['name'] == SPECIAL, 'Enhanced preview restored the source'
            assert (client['at'], client['size']) == baseline_geometry, 'Enhanced preview moved or resized the source'
            if executable == 'ghostty':
                h.call('reload')
                wait(lambda: ready(record) and bridge_status().get('windows') == 1,
                     'Active preview did not recover after a compositor configuration reload', timeout=30)
                assert len(set(frame_samples(session, record))) >= 3, 'Configuration reload froze the active preview'
                print('PASS active Ghostty preview recovers after compositor configuration reload', flush=True)
            hidden(session)
            wait(lambda: bridge_status().get('windows') == 0, 'Hiding preview retained rendering lease', timeout=4)
            print('PASS '+executable+': '+str(len(set(standard)))+' distinct Standard frames, '
                  +str(len(set(enhanced)))+' Enhanced frames; scoped lease and unchanged focus/geometry', flush=True)
            configure('livePreviewCompatibility', 'standard')
            h.dispatch('window.close', window='address:'+address)
            wait(lambda: not h.client(address), 'Live fixture did not close')
        if 'ghostty' in apps:
            configure('presentation', 'dock')
            configure('grouping', 'app')
            configure('livePreviewCompatibility', 'enhanced')
            addresses = [spawn(session, 'ghostty', directory) for _ in range(2)]
            records = [session.park(address) for address in addresses]
            h.dispatch('focus', window='address:'+control)
            focus = current_focus()
            hover(session, icon_ready(session, 'app:'+records[-1]['app'].lower()), records[-1])
            captured_tiles(session, records)
            wait(lambda: set(shell('status')['previewCompatibility']['status'].get('ids', [])) == {r['id'] for r in records}
                 and bridge_status().get('windows') == 2, 'Grouped live thumbnails did not acquire both leases', timeout=20)
            for record in records:
                assert len(set(frame_samples(session, record))) >= 3, 'A grouped terminal preview stayed frozen'
            assert current_focus() == focus, 'Grouped live previews changed focus or workspace'
            command('restore', records[0]['id'], '--to', 'current', '--monitor', session.monitor['name'],
                    '--workspace', session.workspace)
            wait(lambda: bridge_status().get('windows') == 1, 'Restoring a grouped source retained its rendering lease')
            assert h.client(addresses[1])['workspace']['name'] == SPECIAL
            try:
                hidden(session)
            except AssertionError:
                print('Grouped dismissal diagnostics:', {'preview': preview(session),
                      'compatibility': shell('status')['previewCompatibility'], 'cursor': h.read('cursorpos')}, flush=True)
                raise
            wait(lambda: bridge_status().get('windows') == 0, 'Grouped preview dismissal retained rendering leases')
            before = bridge_status()['frames']
            time.sleep(.3)
            assert bridge_status()['frames'] == before, 'Idle bridge kept rendering without a visible preview'
            print('PASS two simultaneous grouped Ghostty previews, per-window restore, lease removal and idle renderer', flush=True)
        assert bridge_status().get('windows') == 0, 'Preview cleanup left a live window lease'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apps', nargs='+', default=['ghostty', 'chromium', 'brave'])
    main(parser.parse_args().apps)
