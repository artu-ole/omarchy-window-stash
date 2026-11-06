#!/usr/bin/env python3
"""Live input routing, chooser, context restoration, and install/removal checks."""
import json
from pathlib import Path
import subprocess
import time
import live
from live import h, shell, command, configure, spawn, stash, wait, Pointer,fixture_settings,require_empty_stash
from desktop_test import desktop_test

monitor_name=None

def surface():
    return next(s for s in shell('status')['surfaces'] if s['screen']==monitor_name)


def point(x,y):
    monitors=h.read('monitors');monitor=next(m for m in monitors if m['name']==monitor_name)
    left=min(m['x'] for m in monitors);top=min(m['y'] for m in monitors)
    right=max(m['x']+round(m['width']/m['scale']) for m in monitors)
    bottom=max(m['y']+round(m['height']/m['scale']) for m in monitors)
    return monitor['x']+x-left,monitor['y']+y-top,right-left,bottom-top


def click(pointer,rect,button=272):
    pointer.click(*point(rect['x']+rect['width']/2,rect['y']+rect['height']/2),button=button)


@desktop_test('Window Stash UI lifecycle tests')
def main():
    global monitor_name
    original=h.read('activewindow');original_ws=h.read('activeworkspace')['id']
    monitor_name=next(m['name'] for m in h.read('monitors') if m['focused'])
    snapshot=command('list');settings=snapshot['settings'];pointer=None
    require_empty_stash(snapshot)
    try:
        fixture_settings()
        configure("floatingPlacement","free")
        assert not command('list')['windows']
        first=spawn('Stash UI alpha');second=spawn('Stash UI beta')
        for address in (first,second):
            h.dispatch('window.float',window='address:'+address,action='on')
            h.dispatch('window.resize',window='address:'+address,x=640,y=420,relative=False)
            m=next(m for m in h.read('monitors') if m['name']==monitor_name)
            h.dispatch('window.move',window='address:'+address,x=m['x']+120,y=m['y']+160,relative=False)
        first_id=stash(first)
        configure('presentation','bubbles')
        configure('scope','global')
        configure('grouping','window')
        wait(lambda:len(surface()['bubbles'])==1,'Bubble missing')
        h.dispatch('focus',window='address:'+second)
        pointer=Pointer()
        # The full-screen transparent bubble surface must pass this input to GTK.
        pointer.click(*point(420,350))
        wait(lambda:h.client(second)['title'].endswith('clicked'),'Bubble surface swallowed an outside click')
        click(pointer,surface()['bubbles'][0])
        wait(lambda:not command('list')['windows'],'Bubble click did not restore')
        print('PASS bubble click and outside input passthrough',flush=True)

        first_id=stash(first);second_id=stash(second)
        configure('presentation','dock');configure('grouping','app')
        wait(lambda:surface()['groups']==1,'App group missing')
        shelf=surface()['shelf']
        pointer.click(*point(shelf['x']+32,shelf['y']+32))
        wait(lambda:shell('status')['dialog']=='picker' and surface()['pickerCount']==2,'Grouped icon did not open chooser')
        # The dialog must own keyboard focus, and Enter must restore its filtered row.
        subprocess.run(['wtype','Stash UI alpha'],check=True)
        wait(lambda:surface()['pickerCount']==1,'Chooser keyboard search failed')
        subprocess.run(['wtype','-k','Return'],check=True)
        wait(lambda:h.client(first)['workspace']['id']==9,'Chooser Enter did not restore selected window')
        assert h.client(second)['workspace']['name']=='special:window-stash'
        print('PASS grouped icon, keyboard search and chooser restoration',flush=True)

        first_id=stash(first)
        h.dispatch('focus',workspace='10')
        configure('presentation','bubbles');configure('grouping','window')
        wait(lambda:len(surface()['bubbles'])==2,'Per-window bubbles missing')
        record=next(w for w in command('list')['windows'] if w['id']==first_id)
        key='window:'+record['stableId']
        bubble=next(b for b in surface()['bubbles'] if b['key']==key)
        click(pointer,bubble,273)
        wait(lambda:shell('status')['dialog']=='menu','Bubble context menu missing')
        click(pointer,surface()['actions']['original'])
        wait(lambda:h.client(first)['workspace']['id']==9,'Context restore-original ignored its destination')
        print('PASS explicit original-workspace context action',flush=True)

        # The removal helper must restore parked windows before deleting the UI.
        pointer.close();pointer=None
        subprocess.run(['python3',str(live.ROOT/'tools/install.py'),'--uninstall','--yes'],check=True)
        assert h.client(second)['workspace']['id']>0,'Removal stranded a minimized window'
        config=Path.home()/'.config/omarchy/shell.json'
        assert not any(p.get('id')=='community.window-stash' for p in json.loads(config.read_text())['plugins'])
        assert '-- Window Stash: begin' not in (Path.home()/'.config/hypr/bindings.lua').read_text()
        switcher=Path.home()/'.config/omarchy/plugins/community.window-switcher'
        assert 'pendingStashAddress' not in (switcher/'Switcher.qml').read_text()
        assert 'stashManaged' not in (switcher/'components/WindowRecords.qml').read_text()
        subprocess.run(['python3',str(live.ROOT/'tools/install.py'),'--yes'],check=True)
        subprocess.run(['omarchy','restart','shell'],check=True)
        wait(lambda:shell('status')['loaded'],'Service did not return after reinstall')
        assert not command('list')['windows']
        print('PASS uninstall recovery, integration removal and reinstall',flush=True)
    finally:
        if pointer:pointer.close()
        if not Path(live.binary).exists():subprocess.run(['python3',str(live.ROOT/'tools/install.py'),'--yes'],check=True)
        subprocess.run([live.binary,'restore-all'],capture_output=True)
        for address in live.addresses:
            if h.client(address):h.dispatch('window.close',window='address:'+address)
        for p in live.processes:
            if p.poll() is None:p.terminate()
        for key,value in settings.items():configure(key,value)
        shell('dismiss')
        h.dispatch('focus',workspace=str(original_ws))
        if original and h.client(original['address']):h.dispatch('focus',window='address:'+original['address'])


if __name__=='__main__':main()
