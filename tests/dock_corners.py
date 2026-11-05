#!/usr/bin/env python3
"""Independent dock rounding, native numeric input, clipping and persistence."""
import json
import os
import subprocess
import time

from live import ROOT,h,command,shell,configure,wait
from pointer import Pointer
from desktop_test import desktop_test


@desktop_test('Dock corner radius settings test')
def main():
    original=h.read('activewindow');original_ws=h.read('activeworkspace')['id']
    snapshot=command('list');settings=dict(snapshot['settings']);baseline={w['id'] for w in snapshot['windows']}
    monitor=next(m for m in h.read('monitors') if m['focused'])
    processes=[];addresses=[];workspace=1000000+os.getpid()*10;pointer=Pointer()
    assert all(w['id']!=workspace for w in h.read('workspaces'))
    def surface():return next(s for s in shell('status')['surfaces'] if s['screen']==monitor['name'])
    def dock():return surface()['floatingDock']
    def point(x,y):
        monitors=h.read('monitors');current=next(m for m in monitors if m['name']==monitor['name'])
        left=min(m['x'] for m in monitors);top=min(m['y'] for m in monitors)
        right=max(m['x']+round(m['width']/m['scale']) for m in monitors)
        bottom=max(m['y']+round(m['height']/m['scale']) for m in monitors)
        return current['x']+x-left,current['y']+y-top,right-left,bottom-top
    def click(rect):
        x=rect['x']+rect['width']/2;y=rect['y']+rect['height']/2
        pointer.move(*point(x-2,y));pointer.click(*point(x,y))
    def spawn():
        title='Stash corners %s %s'%(os.getpid(),len(addresses))
        p=subprocess.Popen(['/usr/bin/python3',str(ROOT/'tests/test-window.py'),title],
            env=dict(os.environ,GDK_BACKEND='wayland',PYTHONDONTWRITEBYTECODE='1'),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        processes.append(p)
        c=wait(lambda:next((c for c in h.read('clients') if c['title']==title),None),'Test window missing')
        addresses.append(c['address']);return c['address']
    def park(address,count):
        command('minimize','--address',address)
        wait(lambda:surface()['groups']==count,'Dock count did not settle')
    def radius(rect,value):
        assert abs(rect['radius']-min(value,rect['width']/2,rect['height']/2))<.01,rect
    def screenshot(rect,name):
        subprocess.run(['grim','-g','%d,%d %dx%d'%(monitor['x']+rect['x']-2,monitor['y']+rect['y']-2,rect['width']+4,rect['height']+4),name],check=True)

    try:
        wait(lambda:monitor['name'] in shell('status')['screens'],'Initial snapshot missing')
        configure('presentation','dock');configure('dockSide','bottom');configure('scope','workspace');configure('grouping','window')
        configure('dockCorners','theme');configure('dockCornerRadius',12)
        h.dispatch('focus',workspace=str(workspace))
        windows=[spawn() for _ in range(3)]
        for i,address in enumerate(windows):park(address,i+1)
        theme=surface()['theme']['radius'];radius(surface()['shelf'],theme)
        shell('settings')
        def control():return next(c for c in surface()['settingControls'] if c['key']=='dockCorners')
        def ready():
            c=control();r=c['rect'];d=surface()['dialog']
            return c if d['visible'] and d['y']<r['y'] and r['y']+r['height']<d['y']+d['height'] else None
        click(wait(ready,'Dock corners selector missing')['rect']);wait(lambda:control()['open'],'Corner dropdown did not open')
        subprocess.run(['wtype','-k','Down','-k','Return'],check=True)
        wait(lambda:surface()['cornerControl']['visible'],'Custom numeric control missing')
        click(surface()['cornerControl']['rect'])
        subprocess.run(['wtype','-M','ctrl','-k','a','-m','ctrl','7','-k','Return'],check=True)
        wait(lambda:shell('status')['settings']['dockCornerRadius']==7,'Native numeric input did not save')
        assert type(command('list')['settings']['dockCornerRadius']) is int
        shell('dismiss');time.sleep(.2)
        radius(surface()['shelf'],7);assert surface()['theme']['radius']==theme
        print('PASS native Follow desktop/Custom selector, numeric input, typed persistence, and independent desktop rounding',flush=True)

        for side in ('bottom','top','left','right'):
            configure('dockSide',side)
            for value in (0,7,64):
                configure('dockCornerRadius',value);radius(surface()['shelf'],value)
        configure('dockSide','bottom');p=surface()['shelf']
        screenshot(p,'/tmp/stash-custom-corners-static.png')
        under=spawn();target='address:'+under
        h.dispatch('window.float',window=target,action='on');h.dispatch('window.resize',window=target,x=640,y=420,relative=False)
        h.dispatch('window.move',window=target,x=monitor['x']+max(0,min(surface()['width']-640,p['x']-100)),
                   y=monitor['y']+surface()['height']-430,relative=False)
        time.sleep(.2)
        pointer.click(*point(p['x']+1,p['y']+1))
        wait(lambda:h.client(under)['title'].endswith(' clicked'),'Rounded dock corner swallowed outside input')
        click(surface()['shelf']['icons'][0]);wait(lambda:surface()['groups']==2,'Rounded static dock icon did not restore')
        park(windows[-1],3)
        print('PASS all static sides, square/custom/maximum radii, rounded corner passthrough and icon restore',flush=True)

        configure('presentation','floating')
        wait(lambda:dock()['active'] and dock()['handle']['opacity']>.99 and not dock()['snapping'] and not dock()['animating'],'Floating dock did not settle')
        for direction in ('vertical','horizontal'):
            configure('floatingDirection',direction)
            for value in (0,7,64):
                configure('dockCornerRadius',value)
                click(dock()['handle'])
                d=wait(lambda:dock() if dock()['expanded'] and not dock()['animating'] else None,'Floating dock did not expand')
                radius(d['panel'],value)
                if value==64:screenshot(d['panel'],'/tmp/stash-custom-corners-'+direction+'.png')
                subprocess.run(['wtype','-k','Escape'],check=True)
                wait(lambda:not dock()['expanded'] and not dock()['animating'],'Dock did not collapse')
        click(dock()['handle']);wait(lambda:dock()['expanded'] and not dock()['animating'],'Dock did not reopen')
        click(dock()['icons'][0]);wait(lambda:surface()['groups']==2,'Rounded floating dock icon did not restore')
        park(windows[-1],3)
        print('PASS both floating directions, rounded content clipping, radius limits and icon restore',flush=True)

        configure('presentation','dock');configure('dockCornerRadius',7)
        subprocess.run(['omarchy','restart','shell'],check=True)
        def loaded():
            r=subprocess.run(['omarchy-shell','window-stash','status'],capture_output=True,text=True)
            if r.returncode or not r.stdout.startswith('{'):return None
            s=json.loads(r.stdout)
            return s if monitor['name'] in s['screens'] and s['settings'].get('dockCorners')=='custom' and s['settings'].get('dockCornerRadius')==7 else None
        wait(loaded,'Custom dock radius did not persist after restart',timeout=15)
        h.dispatch('focus',monitor=monitor['name']);h.dispatch('focus',workspace=str(workspace))
        wait(lambda:surface()['groups']==3 and surface()['width']>100,'Restored dock did not map')
        radius(surface()['shelf'],7)
        configure('dockCorners','theme');radius(surface()['shelf'],surface()['theme']['radius'])
        assert shell('status')['settings']['dockCornerRadius']==7,'Theme mode discarded custom radius'
        assert not shell('status')['error'],shell('status')['error']
        print('PASS saved radius after restart and Follow desktop restores theme while retaining custom value',flush=True)
    finally:
        pointer.button(False);shell('dismiss')
        for address in addresses:
            if h.client(address):h.dispatch('window.close',window='address:'+address)
        for process in processes:
            if process.poll() is None:process.terminate()
        wait(lambda:all(not h.client(a) for a in addresses),'Test windows did not close');command('list')
        for key,value in settings.items():configure(key,value)
        h.dispatch('focus',workspace=str(original_ws))
        if original.get('address') and h.client(original['address']):h.dispatch('focus',window='address:'+original['address'])
        pointer.close()
        assert {w['id'] for w in command('list')['windows']}==baseline


if __name__=='__main__':main()
