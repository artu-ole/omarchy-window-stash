#!/usr/bin/env python3
"""Native animation modes, keyed lifecycles, reversals, reduced/off and recovery."""
import json
import os
import subprocess
import time

from live import ROOT,h,command,shell,configure,wait
from pointer import Pointer
from desktop_test import desktop_test


@desktop_test('Coordinated stash animations test')
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
    def click(r):
        x=r['x']+r['width']/2;y=r['y']+r['height']/2
        pointer.move(*point(x-2,y));pointer.click(*point(x,y))
    def spawn(app):
        title='Stash motion %s %s'%(os.getpid(),len(addresses))
        p=subprocess.Popen(['/usr/bin/python3',str(ROOT/'tests/test-window.py'),title,app],
            env=dict(os.environ,GDK_BACKEND='wayland',PYTHONDONTWRITEBYTECODE='1'),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        processes.append(p)
        c=wait(lambda:next((c for c in h.read('clients') if c['title']==title),None),'Test window missing')
        addresses.append(c['address']);return c['address']
    def record(address):return next(w for w in command('list')['windows'] if w['address']==address)
    def park(address):return command('minimize','--address',address)['id']
    def restore(address):command('restore',record(address)['id'],'--to','original')
    def restore_animated(address,view):
        before=surface()['motion']['exitSerial']
        r=record(address);key='window:'+str(r.get('stableId') or r['id'])
        restore(address)
        def completed():
            return next((e for e in surface()['motion']['completedExits'] if e['serial']>before and e['view']==view and e['key']==key),None)
        event=wait(completed,'Icon exit did not finish: '+view)
        assert event['frames']>=2,('Exit skipped its intermediate frames',event)
        return key
    def stable_static(count):
        return wait(lambda:surface() if surface()['visible'] and surface()['width']>100 and len(surface()['shelf']['icons'])==count and not surface()['shelf']['exitingIcons']
            and not surface()['motion']['shelfBusy'] and not surface()['shelf']['animating'] and all(i['appearance']['presence']>.999 for i in surface()['shelf']['icons']) else None,'Static lifecycles did not settle')
    def stable_bubbles(count):
        return wait(lambda:surface() if surface()['visible'] and surface()['width']>100 and len(surface()['bubbles'])==count and not surface()['exitingBubbles']
            and not surface()['motion']['bubbleBusy'] and all(b['appearance']['presence']>.999 and not b['animating'] for b in surface()['bubbles']) else None,'Bubble lifecycles did not settle')
    def empty():
        wait(lambda:not surface()['visible'],'Empty stash left a mapped overlay',timeout=5)
        assert not surface()['shelf']['exitingIcons'] and not surface()['exitingBubbles']
    def capture(name):
        m=next(m for m in h.read('monitors') if m['name']==monitor['name'])
        p=surface()['shelf']
        subprocess.run(['grim','-g','%d,%d %dx%d'%(m['x']+p['x']-4,m['y']+p['y']-4,p['width']+8,p['height']+8),'/tmp/stash-motion-'+name+'.png'],check=True)

    try:
        wait(lambda:monitor['name'] in shell('status')['screens'],'Initial snapshot missing')
        configure('scope','workspace');configure('grouping','window');configure('presentation','dock');configure('dockSide','bottom')
        configure('animations','full')
        shell('settings')
        wait(lambda:surface()['dialog']['visible'],'Animated settings did not settle')
        assert surface()['motion']['dialogFrames']>=2,'Dialog appeared without intermediate frames'
        def control():return next(c for c in surface()['settingControls'] if c['key']=='animations')
        click(control()['rect']);wait(lambda:control()['open'],'Animations selector did not open')
        subprocess.run(['wtype','-k','Down','-k','Return'],check=True)
        wait(lambda:shell('status')['settings']['animations']=='reduced','Reduced option did not save')
        configure('animations','full');shell('dismiss')
        wait(lambda:0<surface()['dialog']['progress']<1 and not surface()['dialog']['visible'],'Dialog did not retain its exit')
        wait(lambda:not surface()['dialog']['rendered'],'Dialog did not finish closing')
        h.dispatch('focus',workspace=str(workspace))
        windows=[spawn(app) for app in ('org.gnome.Nautilus','org.gnome.Nautilus','org.chromium.Chromium')]
        for index,a in enumerate(windows):
            park(a);s=stable_static(index+1)
            assert s['shelf']['icons'][0]['appearance']['presenceFrames']>=2,'Icon arrival had no intermediate frames'
        capture('static-arrived')
        created=s['motion']['createdShelfIcons']
        for _ in range(3):shell('refresh');time.sleep(.1)
        assert surface()['motion']['createdShelfIcons']==created,'Refresh recreated stable icons'
        restore_animated(windows[1],'dock')
        stable_static(2);park(windows[1]);stable_static(3)
        created=surface()['motion']['createdShelfIcons'];keys={i['key'] for i in surface()['shelf']['icons']}
        began=time.monotonic();configure('grouping','app');configure('grouping','window');elapsed=time.monotonic()-began
        s=stable_static(3)
        assert {i['key'] for i in s['shelf']['icons']}==keys
        if elapsed<.13:assert s['motion']['createdShelfIcons']<=created+2,'Rapid reversal recreated returning icons'
        assert s['motion']['createdShelfIcons']<=created+5,'Reversal duplicated active entries'
        print('PASS native animation selector, dialog fade, keyed arrivals/exits, refresh stability and rapid revival',flush=True)

        for a in windows:restore_animated(a,'dock')
        wait(lambda:surface()['groups']==0,'Last icon remained active')
        assert not surface()['shelf']['icons'],'Retiring icons remained actionable'
        empty()
        configure('presentation','bubbles')
        park(windows[0]);stable_bubbles(1)
        before=surface()['createdBubbles'];park(windows[1]);s=stable_bubbles(2)
        assert s['createdBubbles']==before+1,'Adding a bubble recreated its neighbour'
        assert s['bubbles'][0]['appearance']['presenceFrames']>=2
        restore_animated(windows[0],'bubbles')
        stable_bubbles(1);restore_animated(windows[1],'bubbles');empty()
        park(windows[0]);s=stable_bubbles(1);b=s['bubbles'][0]
        pointer.move(*point(b['x']+24,b['y']+24));pointer.button(True)
        wait(lambda:surface()['bubbles'][0]['held'],'Bubble did not hold before external restore')
        restore_animated(windows[0],'bubbles');pointer.button(False);empty()
        print('PASS final-icon exit, no ghost input, stable bubble neighbours, reflow and restore during a drag',flush=True)

        configure('presentation','floating');configure('floatingDirection','vertical')
        for a in windows:park(a)
        wait(lambda:dock()['active'] and dock()['windows']==3 and not dock()['animating'] and not dock()['snapping'],'Floating stack did not settle')
        assert dock()['handle']['appearance']['presenceFrames']>=2
        restore(windows[2])
        wait(lambda:0<dock()['handle']['appearance']['artwork']['blend']<1,'Front artwork changed without a crossfade')
        wait(lambda:not dock()['animating'],'Artwork crossfade did not finish')
        assert dock()['handle']['appearance']['presence']>.999,'New artwork replayed the whole stack'
        park(windows[2]);wait(lambda:not dock()['animating'],'Stack did not settle after stash')
        click(dock()['handle']);wait(lambda:dock()['expanded'] and not dock()['animating'],'Floating dock did not expand')
        subprocess.run(['wtype',*(['-k','Up']*3),'-k','Down'],check=True)
        wait(lambda:dock()['currentIndex']==1,'Middle row was not selected')
        created=dock()['createdIcons'];removed=restore_animated(windows[1],'floating')
        assert dock()['currentKey']!=removed,'Keyboard cursor stayed on a retiring row'
        wait(lambda:not dock()['animating'] and not dock()['exitingIcons'],'Floating row removal did not settle')
        assert dock()['createdIcons']==created,'Removing a row recreated surviving rows'
        restore(windows[0]);restore(windows[2]);empty()
        print('PASS floating stack entry/exit, artwork crossfade and stable expanded-row reflow',flush=True)

        configure('presentation','dock');configure('animations','reduced');park(windows[0]);s=stable_static(1)
        assert s['shelf']['icons'][0]['appearance']['feedback']['scale']==1,'Reduced mode scaled an icon'
        restore_animated(windows[0],'dock');empty()
        configure('animations','full');park(windows[0]);park(windows[1]);stable_static(2)
        restore(windows[0]);wait(lambda:surface()['shelf']['exitingIcons'],'Exit did not start before changing modes')
        configure('animations','off');s=stable_static(1)
        assert not s['shelf']['exitingIcons'] and s['shelf']['icons'][0]['appearance']['feedback']['scale']==1
        restore(windows[1]);empty()
        park(windows[0]);s=stable_static(1)
        assert s['shelf']['icons'][0]['appearance']['presenceFrames']==0,'Off mode still animated an arrival'
        shell('settings');wait(lambda:surface()['dialog']['visible'],'Instant settings missing')
        assert surface()['motion']['dialogFrames']==0,'Off mode animated the dialog'
        shell('dismiss');wait(lambda:not surface()['dialog']['rendered'],'Off dialog lingered')
        restore(windows[0]);empty()
        print('PASS reduced fades without scaling, mid-flight Off, immediate Off arrivals and dialog dismissal',flush=True)

        configure('animations','reduced');subprocess.run(['omarchy','restart','shell'],check=True)
        def loaded():
            r=subprocess.run(['omarchy-shell','window-stash','status'],capture_output=True,text=True)
            if r.returncode or not r.stdout.startswith('{'):return None
            s=json.loads(r.stdout)
            return s if monitor['name'] in s['screens'] and s['settings'].get('animations')=='reduced' else None
        wait(loaded,'Animation mode did not persist',timeout=15)
        assert not shell('status')['error'],shell('status')['error']
        print('PASS saved animation mode after restart',flush=True)
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
