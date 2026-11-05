#!/usr/bin/env python3
"""Floating dock orientation, horizontal input, edge placement, and overflow."""
import json
import os
import subprocess
import time

from live import ROOT,h,command,shell,configure,wait
from pointer import Pointer
from desktop_test import desktop_test
from stash import Stash,atomic_json,read_json,monitor_identity


@desktop_test('Floating dock direction test')
def main():
    original=h.read('activewindow');original_ws=h.read('activeworkspace')['id']
    snapshot=command('list');settings=dict(snapshot['settings']);positions_before=snapshot['positions']
    baseline={w['id'] for w in snapshot['windows']}
    processes=[];addresses=[];touched=set();output=None
    monitor=next(m for m in h.read('monitors') if m['focused'])
    workspace=1000000+os.getpid()*10;pointer=Pointer()
    assert all(w['id'] not in range(workspace,workspace+3) for w in h.read('workspaces'))

    def surface():return next(s for s in shell('status')['surfaces'] if s['screen']==monitor['name'])
    def dock():return surface()['floatingDock']
    def point(x,y):
        monitors=h.read('monitors')
        left=min(m['x'] for m in monitors);top=min(m['y'] for m in monitors)
        right=max(m['x']+round(m['width']/m['scale']) for m in monitors)
        bottom=max(m['y']+round(m['height']/m['scale']) for m in monitors)
        return monitor['x']+x-left,monitor['y']+y-top,right-left,bottom-top
    def click(rect):pointer.click(*point(rect['x']+rect['width']/2,rect['y']+rect['height']/2))
    def expand():
        click(dock()['handle'])
        return wait(lambda:dock() if dock()['expanded'] and dock()['icons'] and not dock()['animating'] else None,'Dock did not settle open')
    def spawn(title):
        p=subprocess.Popen(['/usr/bin/python3',str(ROOT/'tests/test-window.py'),title],
            env=dict(os.environ,GDK_BACKEND='wayland',PYTHONDONTWRITEBYTECODE='1'),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        processes.append(p)
        c=wait(lambda:next((c for c in h.read('clients') if c['title']==title),None),'Test window missing')
        addresses.append(c['address']);return c['address']
    def park(address):
        command('minimize','--address',address)
        expected=len([w for w in command('list')['windows'] if w['origin']['id']==h.read('activeworkspace')['id']])
        wait(lambda:dock()['windows']==expected and not dock()['animating'] and not dock()['snapping'],'Dock count lagged')

    try:
        configure("floatingPlacement","free")
        wait(lambda:monitor['name'] in shell('status')['screens'],'Initial controller snapshot did not load')
        configure('presentation','floating');configure('floatingDirection','vertical')
        configure('scope','workspace');configure('grouping','window')
        shell('settings')
        def control():return next(c for c in surface()['settingControls'] if c['key']=='floatingDirection')
        def ready():
            c=control();r=c['rect'];d=surface()['dialog']
            return c if c['value']=='vertical' and d['visible'] and d['y']<r['y'] and r['y']+r['height']<d['y']+d['height'] else None
        c=wait(ready,'Direction selector missing');click(c['rect'])
        wait(lambda:control()['open'],'Direction dropdown did not open')
        subprocess.run(['wtype','-k','Down','-k','Return'],check=True)
        wait(lambda:shell('status')['settings']['floatingDirection']=='horizontal','Direction selection did not save')
        shell('dismiss');h.dispatch('focus',workspace=str(workspace))
        windows=[spawn('Stash direction %s %s'%(os.getpid(),i)) for i in range(3)]
        for address in windows:park(address)
        d=expand();p=d['panel']
        assert d['orientation']=='horizontal' and p['width']>p['height']
        assert abs(d['contentWidth']-d['viewportWidth'])<0.01,('Horizontal row border clipped',d)
        for icon in d['icons']:
            assert abs(icon['y']+icon['height']/2-p['y']-p['height']/2)<0.01,'Horizontal icon is not centered'
            assert icon['x']>=p['x']+p['inset'] and icon['x']+icon['width']<=p['x']+p['width']-p['inset']
        subprocess.run(['grim','-g','%d,%d %dx%d'%(monitor['x']+p['x']-4,monitor['y']+p['y']-4,p['width']+8,p['height']+8),
                        '/tmp/stash-horizontal-dock.png'],check=True)
        subprocess.run(['wtype',*(['-k','Left']*len(windows))],check=True)
        wait(lambda:dock()['currentIndex']==0,'Left arrow did not select first icon')
        subprocess.run(['wtype','-k','Right'],check=True)
        wait(lambda:dock()['currentIndex']==1,'Right arrow did not select next icon')
        subprocess.run(['wtype','-k','Return'],check=True)
        wait(lambda:all(w['address']!=windows[1] for w in command('list')['windows']),'Horizontal keyboard restore failed')
        print('PASS native direction dropdown, horizontal centering, unclipped borders, and keyboard restore',flush=True)

        park(windows[1]);configure('grouping','app')
        wait(lambda:dock()['groups']==1,'App grouping did not update')
        d=expand();click(d['icons'][0])
        wait(lambda:shell('status')['dialog']=='picker','Horizontal app icon did not open chooser')
        shell('dismiss');configure('grouping','window')
        wait(lambda:dock()['active'] and not dock()['animating'],'Dock did not settle collapsed')
        touched.add(monitor_identity(monitor))
        handle=dock()['handle']
        command('position',monitor_identity(monitor),'dock:floating',12,handle['y'])
        shell('refresh')
        wait(lambda:dock()['handle']['x']<20,'Saved left-edge anchor did not apply')
        d=expand();assert d['panel']['right'] and d['panel']['x']>=d['handle']['x']+48
        saved=(d['handle']['x'],d['handle']['y'])
        configure('floatingDirection','vertical')
        wait(lambda:not dock()['expanded'] and dock()['orientation']=='vertical' and not dock()['animating'],'Orientation change did not collapse first')
        d=expand();assert d['panel']['height']>d['panel']['width']
        assert abs(d['handle']['x']-saved[0])<2 and abs(d['handle']['y']-saved[1])<2
        configure('floatingDirection','horizontal')
        wait(lambda:dock()['orientation']=='horizontal' and not dock()['animating'],'Horizontal direction did not return')
        print('PASS horizontal app grouping, rightward expansion, and smooth orientation changes at the same anchor',flush=True)

        subprocess.run(['omarchy','restart','shell'],check=True)
        def loaded():
            r=subprocess.run(['omarchy-shell','window-stash','status'],capture_output=True,text=True)
            if r.returncode or not r.stdout.startswith('{'):return None
            s=json.loads(r.stdout)
            return s if s['settings']['floatingDirection']=='horizontal' and any(s['floatingDock']['active'] for s in s['surfaces']) else None
        wait(loaded,'Direction did not persist after restart',timeout=15)
        wait(lambda:dock()['orientation']=='horizontal' and abs(dock()['handle']['x']-saved[0])<2,'Anchor or direction lost after restart')
        print('PASS direction and anchor persist after shell restart',flush=True)

        outputs={m['name'] for m in h.read('monitors')};h.call('output','create','headless')
        monitor=wait(lambda:next((m for m in h.read('monitors') if m['name'] not in outputs),None),'Virtual output missing')
        output=monitor['name'];end=max(m['x']+round(m['width']/m['scale']) for m in h.read('monitors') if m['name']!=output)
        h.eval('hl.monitor({output=%s,mode="320x240@60",position=%s,scale=1})'%(json.dumps(output),json.dumps('%dx0'%end)))
        monitor=next(m for m in h.read('monitors') if m['name']==output)
        h.dispatch('focus',monitor=output);h.dispatch('focus',workspace=str(workspace+1))
        for i in range(7):park(spawn('Stash horizontal overflow %s %s'%(os.getpid(),i)))
        d=expand();p=d['panel'];s=surface()
        assert p['x']>=0 and p['x']+p['width']<=s['width'] and p['y']>=0 and p['y']+p['height']<=s['height']
        assert d['contentWidth']-d['viewportWidth']>60
        x=p['x']+p['inset']+d['viewportWidth']/2;y=p['y']+p['height']/2
        pointer.move(*point(x,y));pointer.button(True)
        for step in range(1,7):pointer.move(*point(max(1,x-step*15),y));time.sleep(.04)
        pointer.button(False)
        wait(lambda:dock()['contentX']>10,'Horizontal dock could not scroll')
        assert len(command('list')['windows'])==len(baseline)+10,'Scrolling restored a window'
        print('PASS horizontal overflow scrolling and bounds on a small screen',flush=True)
    finally:
        pointer.button(False);shell('dismiss')
        for address in addresses:
            if h.client(address):h.dispatch('window.close',window='address:'+address)
        for process in processes:
            if process.poll() is None:process.terminate()
        command('list')
        if output:h.call('output','remove',output)
        for key,value in settings.items():configure(key,value)
        ledger=Stash();positions=read_json(ledger.positions,{})
        for key in touched:
            if 'dock:floating' in positions_before.get(key,{}):positions.setdefault(key,{})['dock:floating']=positions_before[key]['dock:floating']
            elif key in positions:
                positions[key].pop('dock:floating',None)
                if not positions[key]:positions.pop(key)
        atomic_json(ledger.positions,positions);shell('refresh')
        h.dispatch('focus',workspace=str(original_ws))
        if original.get('address') and h.client(original['address']):h.dispatch('focus',window='address:'+original['address'])
        pointer.close()
        assert {w['id'] for w in command('list')['windows']}==baseline


if __name__=='__main__':main()
