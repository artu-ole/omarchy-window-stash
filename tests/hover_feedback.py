#!/usr/bin/env python3
"""Whole-artwork/glyph tint, alpha preservation, animated press, and keyboard hover."""
import json
import os
from pathlib import Path
import subprocess
import time

from live import ROOT,h,command,shell,configure,wait,fixture_settings
from pointer import Pointer
from desktop_test import desktop_test


@desktop_test('Whole-icon and button hover feedback test')
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
    def hover(rect):
        pointer.move(*point(rect['x']+rect['width']/2-2,rect['y']+rect['height']-3))
        pointer.move(*point(rect['x']+rect['width']/2,rect['y']+rect['height']-3))
    def away():pointer.move(*point(32,80))
    def spawn(app):
        title='Stash hover %s %s'%(os.getpid(),len(addresses))
        p=subprocess.Popen(['/usr/bin/python3',str(ROOT/'tests/test-window.py'),title,app],
            env=dict(os.environ,GDK_BACKEND='wayland',PYTHONDONTWRITEBYTECODE='1'),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        processes.append(p)
        c=wait(lambda:next((c for c in h.read('clients') if c['title']==title),None),'Test window missing')
        addresses.append(c['address']);return c['address']
    def park(address):
        command('minimize','--address',address);wait(lambda:surface()['groups']==3,'Stash did not settle')
    def capture(rect,name):
        m=next(m for m in h.read('monitors') if m['name']==monitor['name'])
        geometry='%d,%d %dx%d'%(m['x']+rect['x'],m['y']+rect['y'],rect['width'],rect['height'])
        path='/tmp/stash-hover-'+name
        subprocess.run(['grim','-s','1','-t','ppm','-g',geometry,path+'.ppm'],check=True)
        subprocess.run(['grim','-s','1','-g',geometry,path+'.png'],check=True)
        magic,dimensions,maximum,data=Path(path+'.ppm').read_bytes().split(b'\n',3)
        assert magic==b'P6' and maximum==b'255'
        width,height=map(int,dimensions.split());assert len(data)==width*height*3
        return width,height,[tuple(data[i:i+3]) for i in range(0,len(data),3)]
    def changed(a,b,indices):return sum(max(abs(x-y) for x,y in zip(a[2][i],b[2][i]))>3 for i in indices)
    def geom(r):return tuple(r[k] for k in ('x','y','width','height'))

    try:
        fixture_settings()
        wait(lambda:monitor['name'] in shell('status')['screens'],'Initial snapshot missing')
        configure('animations','full');configure('scope','workspace');configure('grouping','window');configure('presentation','dock')
        configure('dockSide','bottom');configure('dockFrame','hidden');configure('iconShape','square')
        h.dispatch('focus',workspace=str(workspace))
        windows=[spawn(app) for app in ('org.gnome.Nautilus','org.gnome.Nautilus','org.chromium.Chromium')]
        for a in windows:command('minimize','--address',a)
        wait(lambda:surface()['groups']==3,'Icons missing')
        def icon():return surface()['shelf']['icons'][0]
        for mode in ('shown','hidden'):
            configure('iconFrame',mode);away()
            wait(lambda:icon()['appearance']['presence']>.999 and not surface()['motion']['shelfBusy'] and icon()['appearance']['feedback']['hover']<.001,'Idle hover did not clear')
            time.sleep(.15)
            r=icon();idle=capture(r,mode+'-idle');initial=geom(r);art=r['appearance']['artwork']
            hover(r)
            f=wait(lambda:icon()['appearance']['feedback'] if icon()['appearance']['feedback']['hover']>.999 else None,'Hover did not settle')
            assert f['hoverFrames']>=2 and f['tint']>.3,f
            lit=capture(icon(),mode+'-hot')
            center=[y*idle[0]+x for y in range(idle[1]//2-7,idle[1]//2+7) for x in range(idle[0]//2-7,idle[0]//2+7)]
            assert changed(idle,lit,center)>30,'Artwork pixels did not tint; only the background changed'
            assert geom(icon())==initial and icon()['appearance']['artwork']['width']==art['width'],'Hover changed icon layout or artwork size'
            if mode=='hidden':
                corners=(0,idle[0]-1,(idle[1]-1)*idle[0],idle[0]*idle[1]-1)
                assert changed(idle,lit,corners)==0,'Tint painted the transparent corners'
            pointer.button(True)
            f=wait(lambda:icon()['appearance']['feedback'] if icon()['appearance']['feedback']['press']>.999 else None,'Press did not settle')
            assert f['pressFrames']>=2 and f['scale']<.95 and f['tint']>.4,f
            assert geom(icon())==initial,'Press moved the clickable tile'
            capture(icon(),mode+'-pressed');pointer.button(False)
            wait(lambda:surface()['groups']==2,'Styled icon click failed to restore');park(windows[-1])
            print('PASS '+mode+' icon artwork pixel tint, smooth hover/press, stable input geometry and restore',flush=True)

        hover(icon());pointer.button(True,273);pointer.button(False,273)
        wait(lambda:surface()['dialog']['visible'] and shell('status')['dialog']=='menu','Right-click menu did not open')
        away()
        def button():return surface()['actions']['settings']
        wait(lambda:button()['feedback']['hover']<.001,'Button idle did not clear')
        idle=capture(button(),'button-idle');hover(button())
        f=wait(lambda:button()['feedback'] if button()['feedback']['hover']>.999 else None,'Button hover did not settle')
        assert f['hoverFrames']>=2 and f['tint']>.3
        lit=capture(button(),'button-hot');glyphs=[i for i,p in enumerate(idle[2]) if sum(p)>400]
        assert len(glyphs)>2 and changed(idle,lit,glyphs)>2,'Button glyph did not tint'
        pointer.button(True)
        wait(lambda:button()['feedback']['press']>.999,'Button press feedback missing')
        pointer.button(False);wait(lambda:shell('status')['dialog']=='settings','Context Settings action was intercepted')
        shell('dismiss')
        print('PASS right-click Settings, whole button text tint, eased press and native activation',flush=True)

        configure('presentation','floating');configure('floatingDirection','horizontal')
        wait(lambda:dock()['active'] and dock()['handle']['opacity']>.99 and not dock()['snapping'] and not dock()['animating'],'Floating handle did not settle')
        away();wait(lambda:dock()['handle']['appearance']['feedback']['hover']<.001,'Stack hover did not clear')
        hover(dock()['handle'])
        wait(lambda:dock()['handle']['appearance']['feedback']['hover']>.999,'Stack hover missing')
        pointer.button(True)
        wait(lambda:dock()['handle']['appearance']['feedback']['press']>.999,'External stack press missing')
        pointer.button(False)
        wait(lambda:dock()['expanded'] and not dock()['animating'],'Styled stack did not expand')
        # Mouse and keyboard must share one highlighted row even with the
        # pointer still resting on the row selected by the mouse.
        hover(dock()['icons'][1])
        wait(lambda:dock()['currentIndex']==1,'Pointer did not select row')
        back='Left' if dock()['fan']['sign']>0 else 'Right'
        subprocess.run(['wtype','-k',back],check=True)
        wait(lambda:dock()['currentIndex']==0 and dock()['icons'][0]['appearance']['feedback']['hover']>.999
             and dock()['icons'][1]['appearance']['feedback']['hover']<.001,'Mouse and keyboard highlights diverged')
        subprocess.run(['wtype','-k','Return'],check=True)
        wait(lambda:surface()['groups']==2,'Styled keyboard restore failed')
        assert not shell('status')['error'],shell('status')['error']
        print('PASS floating stack hover/press, a single mouse/keyboard highlight and keyboard restore',flush=True)
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
