#!/usr/bin/env python3
"""Native opacity settings, pixel compositing, hover/focus, modes and persistence."""
import json
import os
from pathlib import Path
import subprocess
import time

from live import ROOT,h,command,shell,configure,wait
from pointer import Pointer
from desktop_test import desktop_test


@desktop_test('Dock and icon transparency test')
def main():
    original=h.read('activewindow');original_ws=h.read('activeworkspace')['id']
    snapshot=command('list');settings=dict(snapshot['settings']);baseline={w['id'] for w in snapshot['windows']}
    monitor=next(m for m in h.read('monitors') if m['focused'])
    processes=[];addresses=[];workspace=1000000+os.getpid()*10;pointer=Pointer()
    assert all(w['id']!=workspace for w in h.read('workspaces'))
    def surface():return next(s for s in shell('status')['surfaces'] if s['screen']==monitor['name'])
    def dock():return surface()['floatingDock']
    def point(x,y):
        monitors=h.read('monitors');m=next(m for m in monitors if m['name']==monitor['name'])
        left=min(m['x'] for m in monitors);top=min(m['y'] for m in monitors)
        right=max(m['x']+round(m['width']/m['scale']) for m in monitors)
        bottom=max(m['y']+round(m['height']/m['scale']) for m in monitors)
        return m['x']+x-left,m['y']+y-top,right-left,bottom-top
    def move(x,y):pointer.move(*point(x-1,y));pointer.move(*point(x,y))
    def hover(rect):move(rect['x']+rect['width']/2,rect['y']+rect['height']/2)
    def click(rect):hover(rect);pointer.button(True);time.sleep(.05);pointer.button(False)
    def away():move(32,80)
    def spawn():
        title='Stash opacity %s %s'%(os.getpid(),len(addresses))
        p=subprocess.Popen(['/usr/bin/python3',str(ROOT/'tests/test-window.py'),title],
            env=dict(os.environ,GDK_BACKEND='wayland',PYTHONDONTWRITEBYTECODE='1'),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        processes.append(p)
        c=wait(lambda:next((c for c in h.read('clients') if c['title']==title),None),'Test window missing')
        addresses.append(c['address']);return c['address']
    def park(a):command('minimize','--address',a)
    def capture(rect,name):
        m=next(m for m in h.read('monitors') if m['name']==monitor['name'])
        path=Path('/tmp/stash-opacity-'+name+'.ppm')
        subprocess.run(['grim','-s','1','-t','ppm','-g','%d,%d %dx%d'%(m['x']+rect['x'],m['y']+rect['y'],rect['width'],rect['height']),str(path)],check=True)
        subprocess.run(['grim','-s','1','-g','%d,%d %dx%d'%(m['x']+rect['x'],m['y']+rect['y'],rect['width'],rect['height']),str(path.with_suffix('.png'))],check=True)
        magic,size,maximum,data=path.read_bytes().split(b'\n',3)
        assert magic==b'P6' and maximum==b'255'
        w,ht=map(int,size.split());assert len(data)==w*ht*3
        return list(data)
    def alpha(getter,value):
        return wait(lambda:getter() if abs(getter()['opacity']-value)<.001 else None,'Opacity did not settle at '+str(value))
    def icon():return surface()['shelf']['icons'][0]
    def icon_feedback():return icon()['appearance']['feedback']
    def frame_feedback():return surface()['shelf']['feedback']
    def mix_check(clear,opaque,dim,factor):
        indices=[i for i,(a,b) in enumerate(zip(clear,opaque)) if abs(a-b)>12]
        assert len(indices)>10,'Capture did not contain enough visible pixels'
        errors=sorted(abs(dim[i]-(clear[i]+factor*(opaque[i]-clear[i]))) for i in indices)
        assert errors[int(len(errors)*.95)]<5,('Rendered alpha differs from configured alpha',errors[int(len(errors)*.95)])
    def settle_static(count):
        wait(lambda:len(surface()['shelf']['icons'])==count and not surface()['shelf']['animating']
            and not surface()['motion']['shelfBusy'] and all(i['appearance']['presence']>.999 for i in surface()['shelf']['icons']),'Static dock did not settle')

    try:
        wait(lambda:monitor['name'] in shell('status')['screens'],'Initial snapshot missing')
        configure('scope','workspace');configure('grouping','window');configure('presentation','dock')
        configure('dockSide','bottom');configure('dockFrame','shown');configure('iconFrame','shown');configure('iconShape','square')
        configure('dockCorners','custom');configure('dockCornerRadius',64);configure('animations','full')
        configure('iconOpacity',100);configure('dockOpacity',100)
        shell('settings');wait(lambda:surface()['dialog']['visible'],'Settings did not settle')
        for key,value in (('dockOpacity',30),('iconOpacity',35)):
            c=next(c for c in surface()['opacityControls'] if c['key']==key)
            assert c['visible'];click(c['rect'])
            subprocess.run(['wtype','-M','ctrl','-k','a','-m','ctrl',str(value),'-k','Return'],check=True)
            wait(lambda:shell('status')['settings'][key]==value,'Numeric opacity did not save: '+key)
            assert type(command('list')['settings'][key]) is int
        shell('configure','iconOpacity','101')
        assert shell('status')['settings']['iconOpacity']==35 and shell('status')['error']
        configure('iconOpacity',35);shell('dismiss')
        h.dispatch('focus',workspace=str(workspace));windows=[spawn(),spawn()]
        for a in windows:park(a)
        settle_static(2);away();alpha(frame_feedback,.3)
        configure('iconOpacity',0);alpha(icon_feedback,0);r=icon();clear=capture(r,'icon-clear')
        configure('iconOpacity',100);alpha(icon_feedback,1);opaque=capture(r,'icon-opaque')
        configure('iconOpacity',35);alpha(icon_feedback,.35);dim=capture(r,'icon-dim')
        mix_check(clear,opaque,dim,.35)
        hover(r);f=alpha(icon_feedback,1);alpha(frame_feedback,1)
        assert f['opacityFrames']>=2 and frame_feedback()['opacityFrames']>=2
        hot=capture(r,'icon-hover')
        configure('iconOpacity',0);alpha(icon_feedback,1)
        hot_zero=capture(r,'icon-zero-hover')
        assert max(abs(a-b) for a,b in zip(hot,hot_zero))<=2,'Hover did not fully override zero icon opacity'
        configure('iconOpacity',35);away();alpha(icon_feedback,.35);alpha(frame_feedback,.3)
        p=surface()['shelf'];sample={'x':p['x']+5,'y':p['y']+p['height']/2-3,'width':6,'height':6}
        configure('dockOpacity',0);alpha(frame_feedback,0);clear=capture(sample,'dock-clear')
        configure('dockOpacity',100);alpha(frame_feedback,1);opaque=capture(sample,'dock-opaque')
        configure('dockOpacity',30);alpha(frame_feedback,.3);dim=capture(sample,'dock-dim')
        mix_check(clear,opaque,dim,.3)
        hover(sample);alpha(frame_feedback,1);assert abs(icon_feedback()['opacity']-.35)<.001
        click(icon());wait(lambda:surface()['groups']==1,'Transparent static icon did not restore');park(windows[-1]);settle_static(2)
        print('PASS native numeric settings, validation, actual independent pixel alpha, smooth full-opacity hover, zero-opacity hit area and restore',flush=True)

        configure('presentation','bubbles');configure('iconFrame','hidden')
        wait(lambda:len(surface()['bubbles'])==2 and not surface()['motion']['bubbleBusy'] and not any(b['animating'] for b in surface()['bubbles']),'Bubbles did not settle')
        def bubble():return surface()['bubbles'][0]
        away();alpha(lambda:bubble()['appearance']['feedback'],.35)
        hover(bubble());alpha(lambda:bubble()['appearance']['feedback'],1)
        assert not bubble()['appearance']['frameVisible']
        click(bubble());wait(lambda:surface()['groups']==1,'Transparent bubble did not restore');park(windows[-1])
        print('PASS frameless bubble opacity, full hover and direct restore',flush=True)

        configure('presentation','floating');configure('iconFrame','shown')
        wait(lambda:dock()['active'] and not dock()['animating'] and not dock()['snapping'],'Stack did not settle')
        away();alpha(lambda:dock()['handle']['appearance']['feedback'],.35)
        hover(dock()['handle']);alpha(lambda:dock()['handle']['appearance']['feedback'],1)
        for direction in ('vertical','horizontal'):
            configure('floatingDirection',direction);click(dock()['handle'])
            wait(lambda:dock()['expanded'] and not dock()['animating'],'Floating dock did not open')
            away();alpha(lambda:dock()['panel']['feedback'],.3)
            assert dock()['icons'][dock()['currentIndex']]['appearance']['feedback']['opacity']>.999
            other=1 if dock()['currentIndex']==0 else 0
            alpha(lambda:dock()['icons'][other]['appearance']['feedback'],.35)
            hover(dock()['icons'][other]);alpha(lambda:dock()['panel']['feedback'],1)
            alpha(lambda:dock()['icons'][other]['appearance']['feedback'],1)
            back=('Up' if dock()['fan']['sign']>0 else 'Down') if direction=='vertical' else ('Left' if dock()['fan']['sign']>0 else 'Right')
            subprocess.run(['wtype','-k',back],check=True)
            wait(lambda:dock()['currentIndex']==0,'Keyboard did not select first icon')
            alpha(lambda:dock()['icons'][0]['appearance']['feedback'],1)
            alpha(lambda:dock()['icons'][1]['appearance']['feedback'],.35)
            subprocess.run(['wtype','-k','Escape'],check=True)
            wait(lambda:not dock()['animating'] and not dock()['expanded'],'Floating dock did not close')
        print('PASS floating handle, both directions, independent chrome, and opaque keyboard selection',flush=True)

        configure('presentation','dock');configure('dockFrame','hidden');configure('iconFrame','hidden');settle_static(2)
        for mode in ('reduced','off'):
            configure('animations',mode);away();alpha(icon_feedback,.35)
            hover(icon());f=alpha(icon_feedback,1)
            assert f['scale']==1
            assert (f['opacityFrames']>=2) if mode=='reduced' else f['opacityFrames']==0
        configure('dockFrame','shown');configure('animations','reduced');away()
        subprocess.run(['omarchy','restart','shell'],check=True)
        def loaded():
            r=subprocess.run(['omarchy-shell','window-stash','status'],capture_output=True,text=True)
            if r.returncode or not r.stdout.startswith('{'):return None
            s=json.loads(r.stdout)
            return s if monitor['name'] in s['screens'] and s['settings'].get('dockOpacity')==30 and s['settings'].get('iconOpacity')==35 else None
        wait(loaded,'Opacity choices did not survive restart',timeout=15)
        settle_static(2);away();alpha(icon_feedback,.35);alpha(frame_feedback,.3)
        assert not shell('status')['error'],shell('status')['error']
        print('PASS hidden frames, Reduced/Off motion and saved percentages after restart',flush=True)
    finally:
        pointer.button(False);shell('dismiss')
        for a in addresses:
            if h.client(a):h.dispatch('window.close',window='address:'+a)
        for p in processes:
            if p.poll() is None:p.terminate()
        wait(lambda:all(not h.client(a) for a in addresses),'Test windows did not close');command('list')
        for key,value in settings.items():configure(key,value)
        h.dispatch('focus',workspace=str(original_ws))
        if original.get('address') and h.client(original['address']):h.dispatch('focus',window='address:'+original['address'])
        pointer.close()
        assert {w['id'] for w in command('list')['windows']}==baseline


if __name__=='__main__':main()
