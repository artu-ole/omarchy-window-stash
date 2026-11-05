#!/usr/bin/env python3
"""Live tests use disposable windows. Run from an unlocked Hyprland session."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'controller'))
from stash import Hyprland
from pointer import Pointer
from desktop_test import desktop_test

h=Hyprland()
binary=str(Path.home()/'.local/bin/window-stash')
processes=[]
addresses=[]
original=None
origin_ws=None


def wait(predicate, message, timeout=8):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        value=predicate()
        if value:return value
        time.sleep(.08)
    raise AssertionError(message)


def command(*args):
    result=subprocess.run([binary,*map(str,args)],capture_output=True,text=True)
    data=json.loads(result.stdout)
    assert result.returncode==0,data
    return data


def shell(method,*args):
    text=subprocess.check_output(['omarchy-shell','window-stash',method,*args],text=True)
    return json.loads(text) if text.strip() else None


def configure(key,value):
    shell('configure',key,value)
    wait(lambda:shell('status')['settings'].get(key)==value,'Setting did not update: '+key)


def spawn(title,xwayland=False):
    env=dict(os.environ,GDK_BACKEND='x11' if xwayland else 'wayland')
    log=open('/tmp/window-stash-test-windows.log','a')
    p=subprocess.Popen(['/usr/bin/python3',str(ROOT/'tests/test-window.py'),title],env=env,
                       stdout=log,stderr=log,start_new_session=True)
    processes.append(p)
    c=wait(lambda:next((c for c in h.read('clients') if c['title']==title),None),'Window did not open: '+title)
    addresses.append(c['address'])
    assert c['xwayland']==xwayland,c
    h.dispatch('window.move',window='address:'+c['address'],workspace='9',follow=True)
    return c['address']


def stash(address):
    ident=command('minimize','--address',address)['id']
    wait(lambda:any(w['id']==ident for w in command('list')['windows']),'Stash not recorded')
    wait(lambda:shell('status')['windows']==len(command('list')['windows']),'UI did not update')
    return ident


def main():
    global original,origin_ws
    original=h.read('activewindow');origin_ws=h.read('activeworkspace')['id']
    assert not command('list')['windows'],'Restore your stash before running live tests'
    shell('dismiss')
    native=spawn('Window Stash native test')
    target='address:'+native
    h.dispatch('window.float',window=target,action='on')
    m=next(m for m in h.read('monitors') if m['focused'])
    h.dispatch('window.resize',window=target,x=640,y=420,relative=False)
    h.dispatch('window.move',window=target,x=m['x']+120,y=m['y']+160,relative=False)
    time.sleep(.2)
    before=h.client(native)
    ident=stash(native)
    command('restore',ident,'--to','current','--workspace',9)
    after=h.client(native)
    assert after['floating'] and before['size']==after['size'] and before['at']==after['at'],(before,after)
    print('PASS native floating geometry',flush=True)

    # Fully exercise ordinary maximized and fullscreen state restoration.
    for state in (1,2):
        h.dispatch('window.fullscreen_state',window=target,internal=state,client=state,action='set')
        before_state=h.client(native)['fullscreen']
        assert before_state==state,(before_state,state)
        ident=stash(native)
        command('restore',ident,'--to','current','--workspace',9)
        assert h.client(native)['fullscreen']==state,h.client(native)
        h.dispatch('window.fullscreen_state',window=target,internal=0,client=0,action='set')
    print('PASS maximized and fullscreen restoration',flush=True)

    # XWayland uses the same controller and state, without a separate code path.
    x11=spawn('Window Stash XWayland test',True)
    ident=stash(x11)
    command('restore',ident,'--to','current','--workspace',9)
    assert h.client(x11)['workspace']['id']==9
    print('PASS XWayland minimize/restore',flush=True)

    h.dispatch('window.close',window='address:'+x11)
    x11=spawn('Window Stash second native test')

    # Both application windows must group together; per-window mode must not.
    first=stash(native);second=stash(x11)
    configure('grouping','app')
    wait(lambda:shell('status')['surfaces'][0]['groups']==1,'App grouping failed')
    configure('grouping','window')
    wait(lambda:shell('status')['surfaces'][0]['groups']==2,'Window grouping failed')
    print('PASS grouping',flush=True)

    configure('presentation','bubbles')
    status=wait(lambda:next((s for s in shell('status')['surfaces'] if len(s['bubbles'])==2),None),'Bubbles did not appear')
    pointer=Pointer()
    try:
        bubble=status['bubbles'][0]
        width,height=status['width'],status['height']
        x,y=bubble['x']+24,bubble['y']+24
        pointer.move(x,y,width,height);pointer.button(True)
        for step in range(1,6):
            pointer.move(x-20*step,y+12*step,width,height);time.sleep(.03)
        pointer.button(False)
        wait(lambda:bool(command('list')['positions']),'Bubble position not saved')
        assert len(command('list')['windows'])==2,'Dragging restored a window'
        position=next(s for s in shell('status')['surfaces'] if s['screen']==m['name'])['bubbles'][0]
        assert abs(position['x']-bubble['x'])>30,(position,bubble)
        configure('presentation','dock')
        configure('presentation','bubbles')
        wait(lambda:any(abs(b['x']-position['x'])<3 for s in shell('status')['surfaces'] for b in s['bubbles']),'Bubble position was not retained')
        print('PASS bubble drag and position persistence',flush=True)

        configure('presentation','dock')
        status=wait(lambda:next((s for s in shell('status')['surfaces'] if s['eligible']==2),None),'Dock missing')
        shelf=status['shelf']
        # The first icon is the most recently minimized window.
        pointer.click(shelf['x']+32,shelf['y']+32,status['width'],status['height'])
        wait(lambda:len(command('list')['windows'])==1,'Dock click did not restore')
        print('PASS dock click restoration',flush=True)
    finally:pointer.close()

    command('restore-all','--to','current','--workspace',9)
    # Original destination must differ from the invoking current workspace.
    ident=stash(native)
    h.dispatch('focus',workspace='10')
    command('restore',ident,'--to','original')
    assert h.client(native)['workspace']['id']==9
    ident=stash(native)
    h.dispatch('focus',workspace='10')
    configure('scope','workspace')
    assert command('restore-last')['action']=='noop'
    shell('all')
    wait(lambda:shell('status')['dialog']=='picker','Global recovery picker missing')
    shell('dismiss')
    configure('scope','global')
    command('restore-last')
    assert h.client(native)['workspace']['id']==10
    print('PASS original/current destinations and workspace scope',flush=True)

    # Actual keybindings: restore and stash through the compositor keyboard path.
    h.dispatch('focus',window=target)
    # wtype creates its own keymap; physical-code matching intentionally does
    # not match it. Change matching for this test only, never the installation.
    matching=h.call('repl','return hl.get_config("input.resolve_binds_by_sym")')
    try:
        h.eval('hl.config({input={resolve_binds_by_sym=true}})')
        subprocess.run(['wtype','-M','logo','-s','60','-k','a','-s','60','-m','logo'],check=True)
        wait(lambda:h.client(native)['workspace']['name']=='special:minimized','Super+A did not minimize')
        subprocess.run(['wtype','-M','logo','-s','60','-k','z','-s','60','-m','logo'],check=True)
        wait(lambda:h.client(native)['workspace']['id']==10,'Super+Z did not restore')
    finally:h.eval('hl.config({input={resolve_binds_by_sym='+matching+'}})')
    print('PASS Super+A / Super+Z through virtual-keyboard keysym matching',flush=True)

    ident=stash(native)
    subprocess.run(['omarchy','restart','shell'],check=True,timeout=30)
    wait(lambda:shell('status')['windows']==1,'Stash did not survive shell restart')
    command('restore',ident,'--to','current','--workspace',10)
    assert h.client(native)['floating']
    print('PASS shell restart recovery',flush=True)


@desktop_test('Window Stash live tests')
def run():
    settings=command('list')['settings']
    try:main()
    finally:
        subprocess.run([binary,'restore-all','--to','current'],capture_output=True)
        for address in addresses:
            if h.client(address):h.dispatch('window.close',window='address:'+address)
        for p in processes:
            if p.poll() is None:p.terminate()
        for key,value in settings.items():
            try:configure(key,value)
            except Exception:pass
        shell('dismiss')
        if origin_ws:h.dispatch('focus',workspace=str(origin_ws))
        if original and h.client(original['address']):h.dispatch('focus',window='address:'+original['address'])


if __name__=='__main__':run()
