#!/usr/bin/env python3
"""Static dock edges, native settings, live bar reservations and axis scrolling."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

from live import ROOT,h,command,shell,configure,wait
from pointer import Pointer
from desktop_test import desktop_test


@desktop_test('Static dock sides and bar avoidance test')
def main():
    original=h.read('activewindow');original_ws=h.read('activeworkspace')['id']
    snapshot=command('list');settings=dict(snapshot['settings'])
    baseline={w['id'] for w in snapshot['windows']}
    monitor=next(m for m in h.read('monitors') if m['focused'])
    workspace=1000000+os.getpid()*10
    assert all(w['id'] not in range(workspace,workspace+2) for w in h.read('workspaces'))
    processes=[];addresses=[];output=None;bar=None;pointer=Pointer()

    def surface():return next(s for s in shell('status')['surfaces'] if s['screen']==monitor['name'])
    def point(x,y):
        monitors=h.read('monitors')
        left=min(m['x'] for m in monitors);top=min(m['y'] for m in monitors)
        right=max(m['x']+round(m['width']/m['scale']) for m in monitors)
        bottom=max(m['y']+round(m['height']/m['scale']) for m in monitors)
        return monitor['x']+x-left,monitor['y']+y-top,right-left,bottom-top
    def click(rect,button=272):pointer.click(*point(rect['x']+rect['width']/2,rect['y']+rect['height']/2),button=button)
    def spawn():
        title='Stash dock sides %s %s'%(os.getpid(),len(addresses))
        p=subprocess.Popen(['/usr/bin/python3',str(ROOT/'tests/test-window.py'),title],
            env=dict(os.environ,GDK_BACKEND='wayland',PYTHONDONTWRITEBYTECODE='1'),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        processes.append(p)
        c=wait(lambda:next((c for c in h.read('clients') if c['title']==title),None),'Test window missing')
        addresses.append(c['address']);return c['address']
    def park(address,count):
        command('minimize','--address',address)
        wait(lambda:surface()['groups']==count and not surface()['shelf']['animating'] and not surface()['motion']['shelfBusy'],'Dock group count did not settle')
    def bounds(side):
        wait(lambda:not surface()['shelf']['animating'],'Dock resize did not settle')
        s=surface();p=s['shelf'];a=s['usableArea']
        assert p['side']==side
        assert p['x']>=a['x'] and p['y']>=a['y'],s
        assert p['x']+p['width']<=a['x']+a['width'] and p['y']+p['height']<=a['y']+a['height'],s
        if side in ('left','right'):
            assert p['height']>p['width'],s
            assert abs(p['y']+p['height']/2-a['y']-a['height']/2)<=0.5,s
            for icon in p['icons']:assert abs(icon['x']+icon['width']/2-p['x']-p['width']/2)<0.01,s
        else:
            assert p['width']>p['height'],s
            assert abs(p['x']+p['width']/2-a['x']-a['width']/2)<=0.5,s
            for icon in p['icons']:assert abs(icon['y']+icon['height']/2-p['y']-p['height']/2)<0.01,s
        return p

    try:
        wait(lambda:monitor['name'] in shell('status')['screens'],'Snapshot did not load')
        configure('presentation','dock');configure('scope','workspace');configure('grouping','window');configure('dockSide','bottom')
        configure('dockFrame','shown');configure('dockCorners','custom');configure('dockCornerRadius',64)
        shell('settings')
        def control():return next(c for c in surface()['settingControls'] if c['key']=='dockSide')
        def ready():
            c=control();r=c['rect'];d=surface()['dialog']
            return c if d['visible'] and d['y']<r['y'] and r['y']+r['height']<d['y']+d['height'] else None
        click(wait(ready,'Dock side selector missing')['rect'])
        wait(lambda:control()['open'],'Dock side dropdown did not open')
        subprocess.run(['wtype','-k','Down','-k','Return'],check=True)
        wait(lambda:shell('status')['settings']['dockSide']=='top','Native dock side choice did not save')
        shell('dismiss');h.dispatch('focus',workspace=str(workspace))
        windows=[spawn() for _ in range(3)]
        for i,address in enumerate(windows):park(address,i+1)
        for side in ('top','left','right','bottom'):
            configure('dockSide',side)
            wait(lambda:surface()['shelf']['side']==side,'Side did not update')
            p=bounds(side)
            if side in ('top','left'):
                subprocess.run(['grim','-g','%d,%d %dx%d'%(monitor['x']+p['x']-2,monitor['y']+p['y']-2,p['width']+4,p['height']+4),'/tmp/stash-static-'+side+'.png'],check=True)
            assert len(p['icons'])==3
            click(p['icons'][0])
            wait(lambda:surface()['groups']==2,'Icon did not restore from '+side)
            park(windows[-1],3)
            click(surface()['shelf']['icons'][0],273)
            wait(lambda:shell('status')['dialog']=='menu','Dock menu did not open from '+side)
            wait(lambda:surface()['dialog']['visible'],'Context menu did not settle')
            click(surface()['actions']['settings'])
            wait(lambda:shell('status')['dialog']=='settings','Right-click Settings did not open')
            shell('dismiss')
        print('PASS native dock-side selector, all four edges, centered icons, restore and menu input',flush=True)

        configure('dockSide','left')
        subprocess.run(['omarchy','restart','shell'],check=True)
        def loaded():
            r=subprocess.run(['omarchy-shell','window-stash','status'],capture_output=True,text=True)
            if r.returncode or not r.stdout.startswith('{'):return None
            s=json.loads(r.stdout)
            return s if s['settings']['dockSide']=='left' and any(x['groups']==3 for x in s['surfaces']) else None
        wait(loaded,'Dock side did not persist after restart',timeout=15)
        bounds('left')
        print('PASS static dock side persists after shell restart',flush=True)

        outputs={m['name'] for m in h.read('monitors')};h.call('output','create','headless')
        monitor=wait(lambda:next((m for m in h.read('monitors') if m['name'] not in outputs),None),'Virtual output missing')
        output=monitor['name'];end=max(m['x']+round(m['width']/m['scale']) for m in h.read('monitors') if m['name']!=output)
        h.eval('hl.monitor({output=%s,mode="400x300@60",position=%s,scale=1.25})'%(json.dumps(output),json.dumps('%dx0'%end)))
        monitor=next(m for m in h.read('monitors') if m['name']==output)
        h.dispatch('focus',monitor=output);h.dispatch('focus',workspace=str(workspace+1))
        configure('dockSide','top')
        for i in range(6):park(spawn(),i+1)
        wait(lambda:surface()['width']==320 and surface()['height']==240,'Scaled surface did not settle')
        p=bounds('top');initial_y=p['y']
        initial_reserved=surface()['usableArea']['y']
        with tempfile.TemporaryDirectory(prefix='stash-test-bar-') as directory:
            path=Path(directory)/'shell.qml'
            path.write_text('''import Quickshell
import QtQuick
ShellRoot {
  PanelWindow {
    screen: Quickshell.screens.find(s => s.name === Quickshell.env("STASH_TEST_SCREEN"))
    anchors { top:true; left:true; right:true }
    implicitHeight:40
    exclusiveZone:40
    color:"#1a1b26"
    mask: Region {}
  }
}
''')
            bar=subprocess.Popen(['qs','-p',str(path)],env=dict(os.environ,STASH_TEST_SCREEN=output),
                                 stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            wait(lambda:surface()['usableArea']['y']==initial_reserved+40,'Dock did not react to an appearing bar',timeout=10)
            assert bounds('top')['y']==initial_y+40,'Top dock overlaps reserved bar space'
            bar.terminate();bar.wait(timeout=5);bar=None
            wait(lambda:surface()['usableArea']['y']==initial_reserved,'Dock did not reclaim hidden bar space',timeout=10)
            assert bounds('top')['y']==initial_y
        print('PASS top dock tracks additional bar appearance/removal above the existing bar reservation',flush=True)

        for side in ('top','bottom','left','right'):
            configure('dockSide',side);time.sleep(.2);p=bounds(side)
            vertical=side in ('left','right')
            assert p['contentHeight']>p['viewportHeight'] if vertical else p['contentWidth']>p['viewportWidth'],p
            x=p['x']+p['width']/2;y=p['y']+p['height']/2
            pointer.move(*point(x,y));pointer.button(True)
            for step in range(1,7):
                # Cross a reserve refresh while dragging; unchanged entries must
                # keep their delegates and mouse grab.
                if step==2:time.sleep(1.7)
                pointer.move(*point(x if vertical else max(1,x-step*10),max(1,y-step*10) if vertical else y));time.sleep(.04)
            pointer.button(False)
            wait(lambda:surface()['shelf']['contentY' if vertical else 'contentX']>10,'Could not scroll '+side+' dock')
            assert len(command('list')['windows'])==len(baseline)+9,'Scrolling restored an unintended window'
        print('PASS all four dock sides scroll along their edge on a 1.25-scale small output',flush=True)
    finally:
        pointer.button(False)
        if bar:bar.terminate();bar.wait(timeout=5)
        shell('dismiss')
        for address in addresses:
            if h.client(address):h.dispatch('window.close',window='address:'+address)
        for process in processes:
            if process.poll() is None:process.terminate()
        command('list')
        if output:h.call('output','remove',output)
        for key,value in settings.items():configure(key,value)
        h.dispatch('focus',workspace=str(original_ws))
        if original.get('address') and h.client(original['address']):h.dispatch('focus',window='address:'+original['address'])
        pointer.close()
        assert {w['id'] for w in command('list')['windows']}==baseline


if __name__=='__main__':main()
