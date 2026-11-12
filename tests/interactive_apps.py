#!/usr/bin/env python3
"""Real Ghostty, Chromium and Brave input with isolated terminal/browser profiles."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from urllib.parse import unquote

from desktop_test import desktop_test
from floating_previews import card, park, ready, seed
from interactive_bridge import events
from interactive_previews import active, assert_source, source_click, start, stopped
from live import ROOT, command, configure, h, shell, wait
from native_session import NativeSession


def ink(session, record, rect, bright=False):
    image = card(session, record)['imageRect']
    source = h.client(record['address'])['size']
    x = session.monitor['x']+image['x']+image['width']*rect['x']/source[0]
    y = session.monitor['y']+image['y']+image['height']*rect['y']/source[1]
    width = max(1, round(image['width']*rect['width']/source[0]))
    height = max(1, round(image['height']*rect['height']/source[1]))
    ppm = subprocess.check_output(['grim', '-s', '1', '-t', 'ppm', '-g', f'{round(x)},{round(y)} {width}x{height}', '-'],
                                  stderr=subprocess.DEVNULL)
    pixels = ppm.split(b'\n', 3)[3]
    def matches(index):
        rgb = pixels[index:index+3]
        return min(rgb) > 170 if bright else max(rgb) < 80
    return sum(matches(index) for index in range(0, len(pixels)-2, 3))/max(1, len(pixels)//3)


def spawn(session, argv, title, stderr):
    with stderr.open('w') as output:
        process = subprocess.Popen(argv, env=dict(os.environ), stdout=subprocess.DEVNULL, stderr=output)
    session.processes.append(process)
    try:
        client = wait(lambda: next((client for client in h.read('clients') if title in client['title']), None),
                      'Disposable application did not map: '+argv[0], timeout=30)
    except AssertionError:
        print('Application startup diagnostics:', argv[0], process.poll(), stderr.read_text()[-3000:], flush=True)
        raise
    session.addresses.append(client['address'])
    h.dispatch('window.float', window='address:'+client['address'], action='on')
    h.dispatch('window.resize', window='address:'+client['address'], x=1000, y=700, relative=False)
    return client['address']


def terminal(session, directory):
    title = 'Stash interactive terminal '+str(os.getpid())
    log = directory/'terminal.jsonl'
    address = spawn(session, ['ghostty', '--config-default-files=false', '--gtk-single-instance=false',
                             '--confirm-close-surface=false', '--class=org.windowstash.InteractiveGhostty', '--title='+title,
                             '-e', '/usr/bin/python3', str(ROOT/'tests/interactive_terminal.py'), str(log)],
                    title, directory/'ghostty.stderr')
    wait(lambda: events(log, 'ready'), 'Owned terminal input fixture did not initialize')
    record = park(session, address)
    seed(session, record, 160, 180, 440)
    client = h.client(address)
    original = client['workspace'], client['at'], client['size'], client['floating']
    start(session, record)
    source_click(session, record)
    image_sample = dict(x=client['size'][0]*.05, y=client['size'][1]*.2,
                        width=client['size'][0]*.7, height=client['size'][1]*.4)
    baseline = ink(session, record, image_sample, bright=True)
    phrase = 'native preview ä 123'
    session.keys(phrase)
    def received():
        return b''.join(bytes.fromhex(item['data']) for item in events(log, 'input'))
    wait(lambda: phrase.encode() in received(), 'Actual Ghostty terminal did not receive the synthetic UTF-8 text')
    wait(lambda: ink(session, record, image_sample, bright=True) > baseline+.0005,
         'Ghostty received text but its interactive preview did not show the changed pixels')
    session.keys('-M', 'ctrl', '-k', 'a', '-m', 'ctrl')
    wait(lambda: b'\x01' in received(), 'Actual Ghostty terminal did not receive Ctrl+A')
    session.keys('-k', 'Escape')
    wait(lambda: b'\x1b' in received(), 'Actual Ghostty terminal did not receive plain Escape')
    assert_source(record, original)
    session.keys('-M', 'ctrl', '-M', 'alt', '-k', 'Escape', '-m', 'alt', '-m', 'ctrl')
    wait(stopped, 'Default exit shortcut did not end Ghostty interaction')
    command('restore', record['id'], '--to', 'original')
    wait(lambda: h.client(address)['workspace']['id'] == session.workspace, 'Ghostty did not restore after input')
    assert h.client(address)['size'] == original[2], 'Interactive Ghostty restore lost its real window size'
    h.dispatch('window.close', window='address:'+address)
    wait(lambda: not h.client(address), 'Owned Ghostty fixture did not close')
    print('PASS actual Ghostty input: UTF-8 text, Ctrl+A, Escape, default exit shortcut and exact floating restoration', flush=True)


def page_state(address, title):
    text = h.client(address)['title']
    if title+'|' not in text:
        return None
    try:
        return json.JSONDecoder().raw_decode(unquote(text.split(title+'|', 1)[1]))[0]
    except ValueError:
        return None


def browser(session, directory, executable):
    title = 'Stash interactive '+executable+' '+str(os.getpid())
    page = directory/(executable+'.html')
    page.write_text('''<!doctype html><meta charset="utf-8"><style>
body{margin:0;background:#14283c;color:white;font:20px sans-serif}
input{position:absolute;left:80px;top:70px;width:320px;height:50px;font:24px sans-serif;background:#fff;color:#000}
button{position:absolute;left:100px;top:220px;width:200px;height:80px;font:24px sans-serif}
</style><input autofocus><button>Test button</button><script>
const title='''+json.dumps(title)+''';
const state={text:'',clicks:0,wheel:0,escape:0};
function publish(){state.width=innerWidth;state.height=innerHeight;
 const field=document.querySelector('input').getBoundingClientRect(),button=document.querySelector('button').getBoundingClientRect();
 state.field=[field.x+field.width/2,field.y+field.height/2];state.button=[button.x+button.width/2,button.y+button.height/2];
 document.title=title+'|'+encodeURIComponent(JSON.stringify(state));}
document.querySelector('input').addEventListener('input',event=>{state.text=event.target.value;publish()});
document.querySelector('button').addEventListener('click',()=>{state.clicks++;publish()});
document.addEventListener('wheel',()=>{state.wheel++;publish()},{passive:true});
document.addEventListener('keydown',event=>{if(event.key==='Escape'){state.escape++;publish()}});
addEventListener('resize',publish);publish();
</script>''')
    args = [executable, '--user-data-dir='+str(directory/(executable+'-profile')), '--no-first-run',
            '--no-default-browser-check', '--disable-background-networking', '--disable-component-update',
            '--disable-sync', '--disable-features=MediaRouter', '--ozone-platform=wayland', '--no-sandbox',
            '--app='+page.as_uri(), '--class=org.windowstash.InteractiveBrowser']
    # --no-sandbox is used only within the explicitly network/PID/home-isolated
    # compositor. These profiles never connect to the user's existing browser.
    address = spawn(session, args, title, directory/(executable+'.stderr'))
    state = wait(lambda: page_state(address, title), 'Local browser test page did not initialize')
    time.sleep(.2)
    state = page_state(address, title)
    record = park(session, address)
    seed(session, record, 160, 180, 440)
    client = h.client(address)
    original = client['workspace'], client['at'], client['size'], client['floating']
    # Browser app windows may have a client-side title strip. DOM viewport size
    # describes its actual content; preserve that offset instead of guessing it.
    inset_x = max(0, (client['size'][0]-state['width'])/2)
    inset_y = max(0, client['size'][1]-state['height'])
    start(session, record)
    source_click(session, record, (inset_x+state['field'][0])/client['size'][0],
                 (inset_y+state['field'][1])/client['size'][1])
    text_sample = dict(x=inset_x+110, y=inset_y+80, width=140, height=30)
    baseline = ink(session, record, text_sample)
    session.keys('-M', 'ctrl', '-k', 'a', '-m', 'ctrl', 'browser ä 123')
    wait(lambda: page_state(address, title)['text'] == 'browser ä 123', executable+' did not receive actual field typing')
    wait(lambda: ink(session, record, text_sample) > baseline+.015,
         executable+' received text but its interactive miniature did not render the new field text')
    source_click(session, record, (inset_x+state['button'][0])/client['size'][0],
                 (inset_y+state['button'][1])/client['size'][1])
    wait(lambda: page_state(address, title)['clicks'] == 1, executable+' did not receive its DOM button click')
    from interactive_bridge import scroll
    scroll(session.pointer)
    wait(lambda: page_state(address, title)['wheel'] > 0, executable+' did not receive native wheel input')
    session.keys('-k', 'Escape')
    wait(lambda: page_state(address, title)['escape'] > 0, executable+' did not receive plain Escape')
    assert active(record)
    assert_source(record, original)
    shell('dismiss')
    wait(stopped, executable+' input owner survived dismissal')
    command('restore', record['id'], '--to', 'original')
    wait(lambda: h.client(address)['workspace']['id'] == session.workspace, executable+' did not restore')
    assert h.client(address)['size'] == original[2], executable+' restoration changed the original size'
    h.dispatch('window.close', window='address:'+address)
    wait(lambda: not h.client(address), executable+' fixture did not close')
    print('PASS actual '+executable+': UTF-8 field input, DOM button, wheel, Escape, no automatic restore and exact floating restoration', flush=True)


@desktop_test('Isolated real-application preview interaction compatibility')
def main(apps):
    assert os.environ.get('WINDOW_STASH_ISOLATED_TEST') == '1' and (Path.home()/'.window-stash-isolated').is_file()
    assert not command('list')['windows']
    with tempfile.TemporaryDirectory(prefix='stash-interactive-apps-') as temporary, NativeSession() as session:
        for key, value in dict(presentation='previews', scope='workspace', grouping='window',
                               floatingPreviewInteraction='on', floatingPreviewActivation='explicit', floatingPreviewKeyboard='click',
                               floatingPreviewInteractionFps='60', floatingPreviewControls='always', floatingPreviewUpdate='still',
                               livePreviewCompatibility='standard', hoverPreview='off', floatingPreviewSizing='free',
                               floatingPreviewTitles='hidden', floatingPreviewFrame='hidden', floatingPreviewLock='unlocked',
                               floatingPlacement='free', dragMotion='direct', animations='off').items():
            configure(key, value)
        session.spawn(app='org.windowstash.InteractiveAppControl')
        for name in apps:
            assert shutil.which(name), 'Application unavailable in isolated profile: '+name
            if name == 'ghostty':
                terminal(session, Path(temporary))
            else:
                browser(session, Path(temporary), name)
    assert stopped() and not command('list')['windows']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apps', nargs='+', choices=('ghostty', 'chromium', 'brave'), default=['ghostty', 'chromium'])
    main(parser.parse_args().apps)
