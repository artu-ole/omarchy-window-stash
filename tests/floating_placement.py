#!/usr/bin/env python3
"""Edge gravity, interrupted motion, packing, free placement, and persistence."""
import json
import os
import subprocess
import time

from live import ROOT,h,command,shell,configure,wait,fixture_settings
from pointer import Pointer
from desktop_test import desktop_test
from stash import Stash,atomic_json,read_json,monitor_identity


@desktop_test('Floating placement and edge animation test')
def main():
    original=h.read('activewindow');original_ws=h.read('activeworkspace')['id']
    snapshot=command('list');settings=dict(snapshot['settings']);before=snapshot['positions']
    baseline={w['id'] for w in snapshot['windows']};processes=[];addresses=[];touched=set()
    monitor=next(m for m in h.read('monitors') if m['focused']);identity=monitor_identity(monitor)
    workspace=1000000+os.getpid()*10;pointer=Pointer()
    assert all(w['id']!=workspace for w in h.read('workspaces'))
    def surface():return next(s for s in shell('status')['surfaces'] if s['screen']==monitor['name'])
    def dock():return surface()['floatingDock']
    def bubble(key):
        s=surface()
        return next((b for b in s['bubbles'] if b['key']==key), {'missing':key,'surface':s,'workspace':h.read('activeworkspace')})
    def point(x,y):
        monitors=h.read('monitors');left=min(m['x'] for m in monitors);top=min(m['y'] for m in monitors)
        right=max(m['x']+round(m['width']/m['scale']) for m in monitors)
        bottom=max(m['y']+round(m['height']/m['scale']) for m in monitors)
        current=next(m for m in monitors if m['name']==monitor['name'])
        return current['x']+x-left,current['y']+y-top,right-left,bottom-top
    def click(r):
        # Generate pointer motion after a surface is remapped even when its
        # saved icon position is already under the cursor.
        pointer.move(*point(r['x']+r['width']/2-2,r['y']+r['height']/2))
        pointer.click(*point(r['x']+r['width']/2,r['y']+r['height']/2))
    def spawn():
        title='Stash edge %s %s'%(os.getpid(),len(addresses))
        p=subprocess.Popen(['/usr/bin/python3',str(ROOT/'tests/test-window.py'),title],
            env=dict(os.environ,GDK_BACKEND='wayland',PYTHONDONTWRITEBYTECODE='1'),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        processes.append(p)
        c=wait(lambda:next((c for c in h.read('clients') if c['title']==title),None),'Test window missing')
        addresses.append(c['address']);return c['address']
    def drag(get,x,y,hold=False):
        r=get();sx=r['x']+24;sy=r['y']+24
        pointer.move(*point(sx,sy));time.sleep(.05);pointer.button(True)
        assert get()['held'],('Drag did not capture the item',get(),surface()['dialog'])
        generation=surface()['createdBubbles']
        for step in range(1,7):
            if hold and step==3:time.sleep(1.7)
            pointer.move(*point(sx+(x+24-sx)*step/6,sy+(y+24-sy)*step/6));time.sleep(.025)
            sample=get()
            assert sample.get('held'),('Lost mouse grab',step,sample,generation,surface()['createdBubbles'])
        held=get()
        assert abs(held['x']-x)<2 and abs(held['y']-y)<2,('Dragged item lags behind pointer',held,x,y)
        pointer.button(False)
    def edge(r):
        a=surface()['usableArea'];x=r['x'];y=r['y'];w=r['width'];height=r['height']
        assert x>=a['x']+7.5 and y>=a['y']+7.5 and x+w<=a['x']+a['width']-7.5 and y+height<=a['y']+a['height']-7.5,r
        assert min(abs(x-a['x']-8),abs(y-a['y']-8),abs(x+w-a['x']-a['width']+8),abs(y+height-a['y']-a['height']+8))<0.5,r
    def settle_bubbles():
        return wait(lambda:surface()['bubbles'] if len(surface()['bubbles'])==3 and not any(b['animating'] for b in surface()['bubbles']) else None,'Bubbles did not settle')
    def saved(key,rect):
        wait(lambda:all(abs(a-b)<1 for a,b in zip(command('list')['positions'].get(identity,{}).get(key,[-999,-999]),[rect['x'],rect['y']])),'Final resting position was not saved')
    def restart():
        subprocess.run(['omarchy','restart','shell'],check=True)
        def loaded():
            r=subprocess.run(['omarchy-shell','window-stash','status'],capture_output=True,text=True)
            if r.returncode or not r.stdout.startswith('{'):return None
            s=json.loads(r.stdout)
            return s if s['windows']==len(baseline)+3 and monitor['name'] in s['screens'] else None
        wait(loaded,'Plugin did not recover after restart',timeout=15)
        # An empty test workspace can lose focus during shell startup. Return
        # to it before testing workspace-scoped input.
        h.dispatch('focus',monitor=monitor['name']);h.dispatch('focus',workspace=str(workspace))
        wait(lambda:dock()['active'] and dock()['handle']['opacity']>.99 and not dock()['animating'] and not dock()['snapping'] and surface()['width']>100,
             'Restored dock did not finish mapping and placement')
        time.sleep(.1)

    try:
        fixture_settings()
        configure('animations','full');configure('dragMotion','direct')
        wait(lambda:monitor['name'] in shell('status')['screens'],'Snapshot did not load')
        configure('scope','workspace');configure('grouping','window');configure('presentation','bubbles');configure('floatingPlacement','free')
        h.dispatch('focus',workspace=str(workspace))
        for i in range(3):command('minimize','--address',spawn())
        wait(lambda:len(surface()['bubbles'])==3,'Bubbles missing')
        key=surface()['bubbles'][0]['key'];touched.add(key)
        w=surface()['width'];height=surface()['height'];cx=w/2-24;cy=height/2-24
        drag(lambda:bubble(key),cx,cy);time.sleep(.3)
        r=bubble(key);assert abs(r['x']-cx)<2 and abs(r['y']-cy)<2,r
        saved(key,r)
        shell('settings')
        def control():return next(c for c in surface()['settingControls'] if c['key']=='floatingPlacement')
        wait(lambda:surface()['dialog']['visible'],'Settings did not map');time.sleep(.2)
        click(control()['rect']);wait(lambda:control()['open'],'Placement selector did not open')
        subprocess.run(['wtype','-k','Up','-k','Return'],check=True)
        wait(lambda:shell('status')['settings']['floatingPlacement']=='edges','Native edge setting did not save')
        shell('dismiss');time.sleep(.35);settle_bubbles()
        for r in surface()['bubbles']:edge(r)
        print('PASS native floating placement selector, free dragging, and default edge placement',flush=True)

        for index,(x,y) in enumerate(((w*.2,cy),(cx,height*.2),(w*.75,cy),(cx,height*.75))):
            drag(lambda:bubble(key),x,y,hold=index==0)
            moving=wait(lambda:bubble(key) if bubble(key)['animating'] else None,'Bubble skipped its snap animation')
            r=wait(lambda:bubble(key) if not bubble(key)['animating'] else None,'Bubble snap did not finish')
            edge(r);saved(key,r)
            assert abs(moving['x']-r['x'])+abs(moving['y']-r['y'])>0.5,'Snap had no intermediate position'
        # Another bubble released at the same point must find its own edge slot.
        other=next(b['key'] for b in surface()['bubbles'] if b['key']!=key);touched.add(other)
        r=bubble(key);drag(lambda:bubble(other),r['x'],r['y']);positions=settle_bubbles()
        for i,a in enumerate(positions):
            edge(a)
            for b in positions[:i]:assert a['x']>=b['x']+52 or a['x']+52<=b['x'] or a['y']>=b['y']+52 or a['y']+52<=b['y'],positions
        print('PASS smooth snapping to all four edges, saved endpoints, and separate bubble slots',flush=True)

        configure('floatingPlacement','free');drag(lambda:bubble(key),cx,cy);time.sleep(.3)
        configure('floatingPlacement','edges')
        wait(lambda:bubble(key)['animating'],'Setting change did not animate')
        time.sleep(.14)
        # Grabbing an icon during its glide cancels motion until release.
        drag(lambda:bubble(key),w*.2,cy)
        wait(lambda:not bubble(key)['animating'],'Interrupted snap did not settle');edge(bubble(key))
        configure('grouping','app');wait(lambda:len(surface()['bubbles'])==1,'App grouping missing')
        time.sleep(.3);click(surface()['bubbles'][0]);wait(lambda:shell('status')['dialog']=='picker','Snapped app bubble did not open chooser')
        shell('dismiss');configure('grouping','window');settle_bubbles()
        print('PASS interrupted glide follows the pointer and grouped snapped icons remain clickable',flush=True)

        configure('presentation','floating');configure('floatingPlacement','free');touched.add('dock:floating')
        wait(lambda:dock()['active'] and not dock()['snapping'],'Floating dock missing')
        drag(lambda:dock()['handle'],cx,cy);time.sleep(.3);saved('dock:floating',dock()['handle'])
        restart();wait(lambda:not dock()['snapping'],'Free dock did not settle')
        assert abs(dock()['handle']['x']-cx)<2 and abs(dock()['handle']['y']-cy)<2
        configure('floatingPlacement','edges')
        wait(lambda:dock()['snapping'],'Dock skipped its placement animation')
        wait(lambda:not dock()['snapping'],'Dock snap did not finish');edge(dock()['handle'])
        for orientation in ('vertical','horizontal'):
            configure('floatingDirection',orientation)
            for x,y in ((w*.2,cy),(cx,height*.2),(w*.75,cy),(cx,height*.75)):
                drag(lambda:dock()['handle'],x,y)
                wait(lambda:dock()['snapping'],'Dock drag did not glide')
                wait(lambda:not dock()['snapping'],'Dock glide did not finish')
                edge(dock()['handle']);saved('dock:floating',dock()['handle'])
                click(dock()['handle'])
                d=wait(lambda:dock() if dock()['expanded'] and not dock()['animating'] else None,'Edge dock did not expand')
                p=d['panel'];s=surface()
                assert p['x']>=0 and p['y']>=0 and p['x']+p['width']<=s['width'] and p['y']+p['height']<=s['height'],d
                subprocess.run(['wtype','-k','Escape'],check=True)
                wait(lambda:not dock()['animating'] and not dock()['expanded'],'Dock did not collapse')
        restart();wait(lambda:not dock()['snapping'],'Restored dock did not settle');edge(dock()['handle'])
        assert shell('status')['settings']['floatingPlacement']=='edges'
        print('PASS dock glides to every edge in both directions, expands in bounds, and preserves free/edge settings across restart',flush=True)
        click(dock()['handle'])
        try:wait(lambda:dock()['expanded'] and not dock()['animating'],'Dock did not reopen')
        except AssertionError:
            raise AssertionError(('Post-restart dock input',dock(),h.read('cursorpos'),h.read('monitors')))

        click(dock()['icons'][0]);wait(lambda:dock()['windows']==2,'Snapped dock icon did not restore')
        assert not shell('status')['error'],shell('status')['error']
    finally:
        pointer.button(False);shell('dismiss')
        for address in addresses:
            if h.client(address):h.dispatch('window.close',window='address:'+address)
        for process in processes:
            if process.poll() is None:process.terminate()
        wait(lambda:all(not h.client(a) for a in addresses),'Test windows did not close')
        command('list')
        for key,value in settings.items():configure(key,value)
        ledger=Stash();positions=read_json(ledger.positions,{})
        for key in touched:
            if key in before.get(identity,{}):positions.setdefault(identity,{})[key]=before[identity][key]
            elif identity in positions:positions[identity].pop(key,None)
        if identity in positions and not positions[identity]:positions.pop(identity)
        atomic_json(ledger.positions,positions);shell('refresh')
        h.dispatch('focus',workspace=str(original_ws))
        if original.get('address') and h.client(original['address']):h.dispatch('focus',window='address:'+original['address'])
        pointer.close()
        assert {w['id'] for w in command('list')['windows']}==baseline


if __name__=='__main__':main()
