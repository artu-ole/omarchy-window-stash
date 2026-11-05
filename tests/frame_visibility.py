#!/usr/bin/env python3
"""Independent icon/dock frames, larger artwork, input, grouping and persistence."""
import json
import os
import subprocess
import time

from live import ROOT,h,command,shell,configure,wait
from pointer import Pointer
from desktop_test import desktop_test


@desktop_test('Frameless icons and transparent docks test')
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
    def click(rect,button=272):
        x=rect['x']+rect['width']/2;y=rect['y']+rect['height']/2
        pointer.move(*point(x-2,y));pointer.click(*point(x,y),button=button)
    def spawn(app):
        title='Stash frames %s %s'%(os.getpid(),len(addresses))
        p=subprocess.Popen(['/usr/bin/python3',str(ROOT/'tests/test-window.py'),title,app],
            env=dict(os.environ,GDK_BACKEND='wayland',PYTHONDONTWRITEBYTECODE='1'),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        processes.append(p)
        c=wait(lambda:next((c for c in h.read('clients') if c['title']==title),None),'Test window missing')
        addresses.append(c['address']);return c['address']
    def park(address,count):
        command('minimize','--address',address);wait(lambda:surface()['groups']==count,'Group count did not settle')
    def clear(color):return color in ('#00000000','transparent')
    def bare(appearance):
        assert not appearance['frameVisible'] and appearance['borderWidth']==0 and clear(appearance['background']),appearance
        art=appearance['artwork'];assert art['width']>36 and art['width']*art['scale']<appearance['width'],appearance
        assert abs(art['x']+art['width']/2-appearance['width']/2)<.01,appearance
    def hidden_panel(p):assert not p['frameVisible'] and clear(p['background']) and p['borderWidth']==0 and p['radius']==0,p
    def rect(p):return tuple(p[k] for k in ('x','y','width','height'))
    def screenshot(p,name):
        subprocess.run(['grim','-g','%d,%d %dx%d'%(monitor['x']+p['x']-2,monitor['y']+p['y']-2,p['width']+4,p['height']+4),name],check=True)

    try:
        wait(lambda:monitor['name'] in shell('status')['screens'],'Initial snapshot missing')
        configure('presentation','dock');configure('dockSide','bottom');configure('scope','workspace');configure('grouping','window')
        configure('iconFrame','shown');configure('dockFrame','shown');configure('iconShape','squircle')
        configure('dockCorners','custom');configure('dockCornerRadius',24)
        h.dispatch('focus',workspace=str(workspace))
        windows=[spawn(app) for app in ('org.gnome.Nautilus','org.gnome.Nautilus','org.chromium.Chromium')]
        for i,a in enumerate(windows):park(a,i+1)
        shell('settings')
        for key in ('iconFrame','dockFrame'):
            def control():return next(c for c in surface()['settingControls'] if c['key']==key)
            def ready():
                c=control();r=c['rect'];d=surface()['dialog']
                return c if d['visible'] and d['y']<r['y'] and r['y']+r['height']<d['y']+d['height'] else None
            click(wait(ready,'Frame selector missing: '+key)['rect']);wait(lambda:control()['open'],'Frame selector did not open')
            subprocess.run(['wtype','-k','Down','-k','Return'],check=True)
            wait(lambda:shell('status')['settings'][key]=='hidden','Native frame setting did not save: '+key);time.sleep(.15)
        shell('dismiss');time.sleep(.2)
        hidden_panel(surface()['shelf'])
        for icon in surface()['shelf']['icons']:bare(icon['appearance'])
        print('PASS two independent native frame selectors and larger centered frameless artwork',flush=True)

        for side in ('bottom','left'):
            configure('dockSide',side);configure('dockFrame','shown')
            wait(lambda:not surface()['shelf']['animating'],'Static dock did not settle')
            p=surface()['shelf'];shown=rect(p)
            configure('dockFrame','hidden');assert rect(surface()['shelf'])==shown,'Hiding dock frame moved icons'
            hidden_panel(surface()['shelf'])
            for icons in ('shown','hidden'):
                configure('iconFrame',icons);time.sleep(.2)
                if icons=='hidden':
                    for icon in surface()['shelf']['icons']:bare(icon['appearance'])
            click(surface()['shelf']['icons'][0],273);wait(lambda:shell('status')['dialog']=='menu','Frameless dock menu failed');shell('dismiss')
        configure('dockSide','bottom');wait(lambda:not surface()['shelf']['animating'],'Bottom dock did not settle');screenshot(surface()['shelf'],'/tmp/stash-frameless-static.png')
        click(surface()['shelf']['icons'][0]);wait(lambda:surface()['groups']==2,'Frameless static icon did not restore');park(windows[-1],3)
        print('PASS independent icon/dock frames, unchanged static positions, menu and restore',flush=True)

        configure('presentation','bubbles')
        wait(lambda:len(surface()['bubbles'])==3 and not any(b['animating'] for b in surface()['bubbles']),'Bubbles did not settle')
        b=surface()['bubbles'][0];bare(b['appearance']);assert b['radius']==0,b
        pointer.move(*point(b['x']+24,b['y']+24));time.sleep(.2)
        bare(surface()['bubbles'][0]['appearance'])
        # The saved squircle shape must not clip the enlarged frameless hit area.
        pointer.click(*point(b['x']+2,b['y']+2))
        wait(lambda:surface()['groups']==2,'Frameless bubble corner did not restore');park(windows[-1],3)
        configure('grouping','app');wait(lambda:surface()['groups']==2,'Per-app grouping missing')
        time.sleep(.3)
        b=next(b for b in surface()['bubbles'] if b['appearance']['badge']['visible'])
        bare(b['appearance']);click(b);wait(lambda:shell('status')['dialog']=='picker','Frameless app bubble did not open chooser')
        shell('dismiss');configure('grouping','window')
        print('PASS frameless bubble hover, full artwork hit area, retained count badge and app chooser',flush=True)

        configure('presentation','floating')
        wait(lambda:dock()['active'] and dock()['handle']['opacity']>.99 and not dock()['snapping'] and not dock()['animating'],'Floating handle did not settle')
        bare(dock()['handle']['appearance'])
        for direction in ('vertical','horizontal'):
            configure('floatingDirection',direction)
            for container in ('shown','hidden'):
                configure('dockFrame',container);click(dock()['handle'])
                d=wait(lambda:dock() if dock()['expanded'] and not dock()['animating'] else None,'Floating dock did not open')
                if container=='shown':shown=rect(d['panel'])
                else:
                    hidden_panel(d['panel']);assert rect(d['panel'])==shown,'Hiding floating panel moved icons'
                    screenshot(d['panel'],'/tmp/stash-frameless-'+direction+'.png')
                for icon in d['icons']:bare(icon['appearance'])
                subprocess.run(['wtype','-k','Escape'],check=True)
                wait(lambda:not dock()['expanded'] and not dock()['animating'],'Floating dock did not collapse')
        click(dock()['handle']);wait(lambda:dock()['expanded'] and not dock()['animating'],'Dock did not reopen')
        subprocess.run(['wtype',*(['-k','Left']*3),'-k','Return'],check=True)
        wait(lambda:surface()['groups']==2,'Frameless keyboard selection did not restore');park(windows[-1],3)
        print('PASS frameless stack, both floating directions, unchanged positions, keyboard selection and restore',flush=True)

        subprocess.run(['omarchy','restart','shell'],check=True)
        def loaded():
            r=subprocess.run(['omarchy-shell','window-stash','status'],capture_output=True,text=True)
            if r.returncode or not r.stdout.startswith('{'):return None
            s=json.loads(r.stdout)
            return s if monitor['name'] in s['screens'] and s['settings'].get('iconFrame')=='hidden' and s['settings'].get('dockFrame')=='hidden' else None
        wait(loaded,'Frame settings did not persist after restart',timeout=15)
        h.dispatch('focus',monitor=monitor['name']);h.dispatch('focus',workspace=str(workspace))
        wait(lambda:dock()['active'] and dock()['handle']['opacity']>.99 and not dock()['snapping'],'Restored handle missing')
        bare(dock()['handle']['appearance'])
        configure('iconFrame','shown');configure('dockFrame','shown');time.sleep(.2)
        assert shell('status')['settings']['iconShape']=='squircle' and shell('status')['settings']['dockCornerRadius']==24
        assert dock()['handle']['appearance']['frameVisible']
        assert not shell('status')['error'],shell('status')['error']
        print('PASS saved frame choices after restart and original shape/corner preferences restored',flush=True)
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
