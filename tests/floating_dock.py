#!/usr/bin/env python3
"""Floating dock interaction, grouping, persistence, scope, and overflow."""
import json
import os
from pathlib import Path
import subprocess
import time

from live import ROOT, h, command, shell, configure, wait
from desktop_test import desktop_test
from pointer import Pointer
from stash import Stash, atomic_json, read_json, monitor_identity


@desktop_test('Window Stash floating dock test')
def main():
    original = h.read('activewindow'); original_ws = h.read('activeworkspace')['id']
    snapshot = command('list'); settings = dict(snapshot['settings'])
    baseline = {w['id'] for w in snapshot['windows']}
    old_positions = snapshot['positions']
    touched = set(); processes = []; addresses = []; output = None
    monitor = next(m for m in h.read('monitors') if m['focused'])
    pointer = Pointer(); workspace = 1000000+os.getpid()*10
    assert all(w['id'] not in range(workspace,workspace+4) for w in h.read('workspaces'))

    def surface():
        return next(s for s in shell('status')['surfaces'] if s['screen'] == monitor['name'])

    def dock(): return surface()['floatingDock']

    def point(x,y):
        monitors=h.read('monitors')
        left=min(m['x'] for m in monitors);top=min(m['y'] for m in monitors)
        right=max(m['x']+round(m['width']/m['scale']) for m in monitors)
        bottom=max(m['y']+round(m['height']/m['scale']) for m in monitors)
        return monitor['x']+x-left,monitor['y']+y-top,right-left,bottom-top

    def click(rect,button=272):
        pointer.click(*point(rect['x']+rect['width']/2,rect['y']+rect['height']/2),button=button)
        time.sleep(.15)

    def spawn(title):
        process=subprocess.Popen(['/usr/bin/python3',str(ROOT/'tests/test-window.py'),title],
            env=dict(os.environ,GDK_BACKEND='wayland',PYTHONDONTWRITEBYTECODE='1'),
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        processes.append(process)
        c=wait(lambda:next((c for c in h.read('clients') if c['title']==title),None),'Test window missing')
        addresses.append(c['address'])
        return c['address']

    def park(address):
        command('minimize','--address',address)
        wait(lambda:any(w['address']==address for w in command('list')['windows']),'Minimize failed')
        wait(lambda:dock()['windows']==len([w for w in command('list')['windows'] if w['origin']['id']==h.read('activeworkspace')['id']]),'Floating count lagged')

    def expand():
        click(dock()['handle'])
        try:
            return wait(lambda:dock() if dock()['expanded'] and dock()['icons'] and not dock()['animating'] else None,'Stack did not expand')
        except AssertionError:
            print('Floating dock diagnostics:',json.dumps(dock()),flush=True)
            raise

    try:
        configure("animations","full")
        configure("floatingPlacement","free")
        wait(lambda:monitor['name'] in shell('status')['screens'],'Initial controller snapshot did not load')
        configure('floatingDirection','vertical')
        configure('presentation','dock');shell('settings')
        def appearance():
            return next(c for c in surface()['settingControls'] if c['key']=='presentation')
        def appearance_ready():
            c=appearance();d=surface()['dialog'];r=c['rect']
            return c if c['value']=='dock' and d['visible'] and d['y']<r['y'] and r['y']+r['height']<d['y']+d['height'] else None
        c=wait(appearance_ready,'Appearance dropdown not ready');click(c['rect'])
        wait(lambda:appearance()['open'],'Appearance dropdown did not open')
        subprocess.run(['wtype',*(['-k','Up']*3+['-k','Down']*2+['-k','Return'])],check=True)
        wait(lambda:shell('status')['settings']['presentation']=='floating','Third presentation did not save')
        shell('dismiss')
        print('PASS native Appearance selector exposes floating dock as third option',flush=True)
        configure('scope','workspace');configure('grouping','window')
        configure('iconShape','squircle')
        h.dispatch('focus',workspace=str(workspace))
        one=spawn('Stash floating one %s'%os.getpid());park(one)
        wait(lambda:dock()['active'] and dock()['windows']==1 and not dock()['animating'] and not dock()['snapping'],'Single floating icon missing')
        assert not dock()['expanded'] and not surface()['bubbles']
        click(dock()['handle'])
        wait(lambda:not any(w['address']==one for w in command('list')['windows']),'Single icon did not restore immediately')
        print('PASS single window restores directly from floating handle',flush=True)

        park(one)
        two=spawn('Stash floating two %s'%os.getpid());park(two)
        under=spawn('Stash floating passthrough %s'%os.getpid())
        handle=dock()['handle'];s=surface()
        h.dispatch('window.float',window='address:'+under,action='on')
        h.dispatch('window.resize',window='address:'+under,x=640,y=420,relative=False)
        h.dispatch('window.move',window='address:'+under,x=monitor['x']+max(0,handle['x']-550),
                   y=monitor['y']+max(30,handle['y']-80),relative=False)
        handle=dock()['handle']
        pointer.click(*point(handle['x']+24,handle['y']+24))
        opening=wait(lambda:dock() if dock()['expanded'] else None,'Stack did not start opening')
        expanded=wait(lambda:dock() if dock()['expanded'] and dock()['icons'] and not dock()['animating'] else None,'Unroll animation did not settle')
        assert expanded['animation']['openingFrames']>=2,'Expansion did not produce intermediate frames'
        assert expanded['windows']==2 and expanded['groups']==2
        assert abs(expanded['contentHeight']-expanded['viewportHeight'])<0.01,'Icon row borders are clipped'
        for entry in expanded['icons']:
            assert abs(entry['x']+entry['width']/2-expanded['panel']['x']-expanded['panel']['width']/2)<0.01
        for a in [expanded['handle']['appearance']]+[entry['appearance'] for entry in expanded['icons']]:
            art=a['artwork'];badge=a['badge']
            assert abs(art['x']+art['width']/2-a['width']/2)<0.01
            assert abs(art['y']+art['height']/2-a['height']/2)<0.01
            assert art['x']>=0 and art['y']>=0 and art['x']+art['width']<=a['width']
            if badge['visible']:
                assert badge['x']>=0 and badge['y']>=0 and badge['x']+badge['width']<=a['width'] and badge['y']+badge['height']<=a['height']
        created=expanded['createdIcons']
        for _ in range(3):shell('refresh')
        time.sleep(.3)
        assert dock()['createdIcons']==created,'Refreshing the stash recreated icon widgets'
        print('PASS smooth unroll, centered artwork, bounded badges, and stable delegates',flush=True)
        assert len([w for w in command('list')['windows'] if w['origin']['id']==workspace])==2
        p=expanded['panel']
        assert p['x']>=0 and p['y']>=0 and p['x']+p['width']<=s['width'] and p['y']+p['height']<=s['height']
        subprocess.run(['grim','-g','%d,%d %dx%d'%(monitor['x']+p['x']-4,monitor['y']+min(p['y'],handle['y'])-4,
                         p['width']+8,p['height']+handle['height']+24),'/tmp/stash-floating-dock-expanded.png'],check=True)
        # Outside clicks close the popover; the collapsed dock leaves the desktop usable.
        outside={'x':handle['x']-250,'y':handle['y']+100,'width':2,'height':2}
        click(outside)
        wait(lambda:not dock()['expanded'],'Outside click did not collapse')
        click(outside)
        wait(lambda:h.client(under)['title'].endswith(' clicked'),'Collapsed dock swallowed outside input')
        expand();subprocess.run(['wtype','-k','Escape'],check=True)
        wait(lambda:not dock()['expanded'],'Escape did not collapse')
        wait(lambda:not dock()['panel']['visible'],'Collapse animation did not finish')
        assert dock()['animation']['closingFrames']>=2,'Collapse skipped its intermediate frames'
        expanded=expand();click(expanded['icons'][0])
        wait(lambda:dock()['windows']==1 and not dock()['expanded'],'Icon choice did not restore and collapse')
        remaining={w['address'] for w in command('list')['windows'] if w['origin']['id']==workspace}
        assert len(remaining)==1
        print('PASS stacked handle, expansion, outside/Escape dismissal, and icon selection',flush=True)

        for address in (one,two):
            if address not in remaining:park(address)
        configure('grouping','app')
        wait(lambda:dock()['groups']==1,'App grouping failed')
        expanded=expand();assert expanded['windows']==2 and expanded['groups']==1
        click(expanded['icons'][0])
        wait(lambda:shell('status')['dialog']=='picker','App icon did not open existing window chooser')
        subprocess.run(['wtype','Stash floating two %s'%os.getpid()],check=True)
        wait(lambda:surface()['pickerCount']==1,'Grouped chooser did not filter')
        subprocess.run(['wtype','-k','Return'],check=True)
        wait(lambda:all(w['address']!=two for w in command('list')['windows']),'Grouped chooser did not restore selected window')
        print('PASS per-app grouping and individual window chooser',flush=True)

        park(two);configure('grouping','window')
        touched.add(monitor_identity(monitor))
        before=dock()['handle'];target_y=surface()['height']-90
        x,y=before['x']+24,before['y']+24
        dx=-80;dy=target_y-before['y']
        pointer.move(*point(x,y));pointer.button(True)
        for step in range(1,7):
            pointer.move(*point(x+dx*step/6,y+dy*step/6));time.sleep(.04)
        pointer.button(False)
        moved=wait(lambda:dock()['handle'] if abs(dock()['handle']['x']-before['x'])>50 else None,'Stack drag did not move')
        expanded=expand()
        assert not expanded['panel']['down'] and expanded['panel']['y']>=0
        subprocess.run(['wtype','-k','Escape'],check=True)
        wait(lambda:not dock()['expanded'],'Escape did not collapse the fan')
        configure('presentation','bubbles');configure('presentation','floating')
        wait(lambda:abs(dock()['handle']['x']-moved['x'])<2,'Dock position changed across mode switch')
        h.dispatch('focus',workspace=str(workspace+1))
        wait(lambda:not dock()['active'],'Workspace visibility leaked')
        configure('scope','global')
        wait(lambda:dock()['windows']==len(baseline)+2,'Global floating dock missing windows')
        configure('scope','workspace');h.dispatch('focus',workspace=str(workspace))
        print('PASS shared drag position, upward expansion, mode changes, and visibility scope',flush=True)

        subprocess.run(['omarchy','restart','shell'],check=True)
        def ready():
            r=subprocess.run(['omarchy-shell','window-stash','status'],capture_output=True,text=True)
            if r.returncode or not r.stdout.startswith('{'):return None
            status=json.loads(r.stdout)
            return status if status['settings']['presentation']=='floating' and any(s['floatingDock']['active'] for s in status['surfaces']) else None
        wait(ready,'Floating dock did not load after restart',timeout=15)
        wait(lambda:abs(dock()['handle']['x']-moved['x'])<2,'Dock position did not survive restart')
        print('PASS floating presentation and dock position after shell restart',flush=True)

        before_outputs={m['name'] for m in h.read('monitors')}
        h.call('output','create','headless')
        monitor=wait(lambda:next((m for m in h.read('monitors') if m['name'] not in before_outputs),None),'Virtual output missing')
        output=monitor['name']
        end=max(m['x']+round(m['width']/m['scale']) for m in h.read('monitors') if m['name']!=output)
        h.eval('hl.monitor({output=%s,mode="640x360@60",position=%s,scale=1})'%(json.dumps(output),json.dumps('%dx0'%end)))
        monitor=next(m for m in h.read('monitors') if m['name']==output)
        h.dispatch('focus',monitor=output);h.dispatch('focus',workspace=str(workspace+2))
        for i in range(5):park(spawn('Stash floating overflow %s %s'%(os.getpid(),i)))
        expanded=expand();p=expanded['panel'];s=surface()
        assert p['y']>=0 and p['y']+p['height']<=s['height']
        assert expanded['contentHeight']>expanded['viewportHeight']
        x=p['x']+p['width']/2;y=p['y']+min(expanded['viewportHeight']/2+6,30)
        pointer.move(*point(x,y));pointer.button(True)
        for step in range(1,7):pointer.move(*point(x,max(1,min(surface()['height']-1,y-expanded['fan']['sign']*step*12))));time.sleep(.04)
        pointer.button(False)
        wait(lambda:dock()['contentY']>10,'Floating dock could not scroll')
        configure('scope','global')
        wait(lambda:all(s['floatingDock']['windows']==len(baseline)+7 for s in shell('status')['surfaces']),'Global stack missing on a monitor')
        print('PASS small-screen vertical overflow and global stack on two monitors',flush=True)
    finally:
        pointer.button(False)
        shell('dismiss')
        for address in addresses:
            if h.client(address):h.dispatch('window.close',window='address:'+address)
        for process in processes:
            if process.poll() is None:process.terminate()
        command('list')
        if output:h.call('output','remove',output)
        for key,value in settings.items():configure(key,value)
        ledger=Stash();positions=read_json(ledger.positions,{})
        for key in touched:
            if 'dock:floating' in old_positions.get(key,{}):
                positions.setdefault(key,{})['dock:floating']=old_positions[key]['dock:floating']
            elif key in positions:
                positions[key].pop('dock:floating',None)
                if not positions[key]:positions.pop(key)
        atomic_json(ledger.positions,positions);shell('refresh')
        h.dispatch('focus',workspace=str(original_ws))
        if original.get('address') and h.client(original['address']):h.dispatch('focus',window='address:'+original['address'])
        pointer.close()
        assert {w['id'] for w in command('list')['windows']}==baseline


if __name__=='__main__':main()
