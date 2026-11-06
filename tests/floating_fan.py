#!/usr/bin/env python3
"""Cursor-first persistent actors, curved fan motion, restacking and dismissal."""
import json
import os
import subprocess
import time

from live import ROOT,h,command,shell,configure,wait
from pointer import Pointer
from desktop_test import desktop_test
from stash import Stash,atomic_json,read_json,monitor_identity


@desktop_test('Cursor-first floating fan test')
def main():
    original=h.read('activewindow');original_ws=h.read('activeworkspace')['id']
    originalBinds=[b for b in h.read('binds') if b.get('description')!='Window Stash click observer']
    snapshot=command('list');settings=dict(snapshot['settings']);baseline={w['id'] for w in snapshot['windows']}
    positions=snapshot['positions'];monitor=next(m for m in h.read('monitors') if m['focused'])
    processes=[];addresses=[];output=None;changed=set();pointer=Pointer();workspace=1000000+os.getpid()*10
    assert all(w['id'] not in range(workspace,workspace+3) for w in h.read('workspaces'))
    def surface():return next(s for s in shell('status')['surfaces'] if s['screen']==monitor['name'])
    def dock():return surface()['floatingDock']
    def point(x,y):
        monitors=h.read('monitors');m=next(m for m in monitors if m['name']==monitor['name'])
        left=min(m['x'] for m in monitors);top=min(m['y'] for m in monitors)
        right=max(m['x']+round(m['width']/m['scale']) for m in monitors)
        bottom=max(m['y']+round(m['height']/m['scale']) for m in monitors)
        return m['x']+x-left,m['y']+y-top,right-left,bottom-top
    def click(rect,button=272):
        x=rect['x']+rect['width']/2;y=rect['y']+rect['height']/2
        pointer.move(*point(x-1,y));pointer.click(*point(x,y),button=button)
    def spawn():
        title='Stash fan %s %s'%(os.getpid(),len(addresses))
        p=subprocess.Popen(['/usr/bin/python3',str(ROOT/'tests/test-window.py'),title],env=dict(os.environ,GDK_BACKEND='wayland',PYTHONDONTWRITEBYTECODE='1'),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        processes.append(p);c=wait(lambda:next((c for c in h.read('clients') if c['title']==title),None),'Test window missing')
        addresses.append(c['address']);return c['address']
    def park(a):
        command('minimize','--address',a)
        wait(lambda:any(w['address']==a for w in command('list')['windows']),'Stash missing')
        wait(lambda:dock()['active'] and not dock()['animating'] and not dock()['snapping'],'Stack did not settle')
    def settle(opened,pinned=None):
        def sample():
            d=dock()
            if pinned:
                a=next(a for a in d['actors'] if a['key']==pinned['key'])
                assert abs(a['x']-pinned['x'])<.001 and abs(a['y']-pinned['y'])<.001,('Original icon moved during unfold/fold',a,pinned)
            return d if d['expanded']==opened and not d['animating'] and not d['snapping'] else None
        return wait(sample,'Fan did not settle '+str(opened))
    def expand(offset=0):
        before=dock();r=before['handle'];created=before['createdIcons'];pinned=before['actors'][0]
        x=r['x']+r['width']/2+offset;y=r['y']+24+offset
        pointer.move(*point(x-1,y));pointer.click(*point(x,y))
        d=settle(True,pinned);assert d['createdIcons']==created,'Expansion recreated icon actors'
        first=next(i for i in d['icons'] if i['key']==d['actors'][0]['key'])
        assert first['x']<=x<=first['x']+first['width'] and first['y']<=y<=first['y']+first['height'],('Newest icon missed the pointer',d)
        assert d['currentIndex']==0,d
        assert first['maxBend']==0 and first['maxTilt']<=1.01 and first['minScale']>=.979,'Front icon effect was too large'
        return d
    def collapse():
        pinned=dock()['actors'][0]
        subprocess.run(['wtype','-k','Escape'],check=True);d=settle(False,pinned)
        for a in d['actors']:
            assert abs(a['x']-d['handle']['x'])<.01 and abs(a['y']-d['handle']['y'])<=8.01,'Actor did not return to the stack'
        return d
    def anchor(x,y):
        key=monitor_identity(monitor);changed.add(key)
        command('position',key,'dock:floating',x,y);shell('refresh')
        wait(lambda:abs(dock()['handle']['x']-x)<2 and abs(dock()['handle']['y']-y)<2 and not dock()['snapping'],'Test anchor missing')
    def keyboard(delta):
        d=dock();sign=d['fan']['sign']
        key=('Right' if delta*sign>0 else 'Left') if d['orientation']=='horizontal' else ('Down' if delta*sign>0 else 'Up')
        subprocess.run(['wtype','-k',key],check=True)

    try:
        wait(lambda:monitor['name'] in shell('status')['screens'],'Snapshot missing')
        configure('presentation','floating');configure('scope','workspace');configure('grouping','window')
        configure('floatingPlacement','free');configure('animations','full');configure('floatingAnimation','arc');configure('iconShape','square')
        configure('iconFrame','shown');configure('dockFrame','shown');configure('dockCorners','custom');configure('dockCornerRadius',64)
        configure('dockOpacity',100);configure('iconOpacity',100)
        h.dispatch('focus',workspace=str(workspace));windows=[spawn() for _ in range(3)]
        for a in windows:park(a)
        w=surface()['usableArea']['width'];ht=surface()['usableArea']['height'];created=dock()['createdIcons']
        anchor(round(w/2),round(ht/2))
        styles=('arc','glide','cascade','spring','swing','matryoshka','matryoshka-hop','jumping')
        for style in (*styles[:5],'jumping'):
            index=styles.index(style)
            shell('settings')
            def control():return next(c for c in surface()['settingControls'] if c['key']=='floatingAnimation')
            wait(lambda:surface()['dialog']['visible'],'Style settings missing')
            click(control()['rect']);wait(lambda:control()['open'],'Unfold animation dropdown did not open')
            subprocess.run(['wtype',*(['-k','Up']*len(styles)),*(['-k','Down']*index),'-k','Return'],check=True)
            wait(lambda:shell('status')['settings']['floatingAnimation']==style,'Native style selector did not save '+style)
            shell('dismiss');settle(False)
            for direction in ('vertical','horizontal'):
                configure('floatingDirection',direction);d=expand(offset=-17 if direction=='vertical' else 17)
                assert d['style']==style and d['createdIcons']==created
                assert all(a['frames']>=2 and a['rotation']==0 and abs(a['scale']-1)<.001 for a in d['actors'])
                if style in ('glide','cascade'):assert all(a['maxBend']==0 for a in d['actors'])
                if style=='glide':assert all(abs(a['minScale']-1)<.001 for a in d['actors'])
                if style=='cascade':assert any(a['minScale']<.95 for a in d['actors'])
                if style=='spring':assert any(a['peakProgress']>1.03 for a in d['actors'])
                if style=='swing':assert any(a['maxTilt']>1 and a['minScale']<.95 for a in d['actors'])
                if style=='arc':assert any(a['maxBend']>1 for a in d['actors'])
                collapse()
            print('PASS native '+style+' selection, fixed original icon, both axes, distinct motion and complete restacking',flush=True)
        configure('floatingAnimation','arc')
        for direction in ('vertical','horizontal'):
            configure('floatingDirection',direction)
            for x,y in ((w/2,ht/2),(16,50),(w-70,ht-90)):
                anchor(round(x),round(y));d=expand(offset=3)
                assert len(d['icons'])==3 and d['createdIcons']==created
                assert any(a['maxBend']>1 and a['frames']>=2 for a in d['actors'][1:]),'Fan skipped its curved motion'
                first=d['icons'][0]
                for index,a in enumerate(d['icons']):
                    if direction=='horizontal':assert abs(a['y']-first['y'])<.01 and abs(a['x']-first['x']-index*d['fan']['sign']*52)<.01
                    else:assert abs(a['x']-first['x'])<.01 and abs(a['y']-first['y']-index*d['fan']['sign']*52)<.01
                p=d['panel'];assert p['x']>=0 and p['y']>=0 and p['x']+p['width']<=surface()['width'] and p['y']+p['height']<=surface()['height']
                collapse()
        created=dock()['createdIcons'];expand()
        for _ in range(3):shell('refresh');time.sleep(.12)
        assert dock()['expanded'] and dock()['createdIcons']==created,'Unchanged monitor refresh collapsed or recreated the fan'
        subprocess.run(['wtype','-k','Escape'],check=True)
        wait(lambda:not dock()['expanded'],'Escape was not delivered before reversal')
        click(dock()['handle'])
        try:settle(True)
        except AssertionError:
            print('Rapid reversal state:',json.dumps(dock()),flush=True)
            raise
        assert dock()['createdIcons']==created,'Interrupted fold recreated actors'
        collapse()
        print('PASS cursor coverage, newest-first order, same actors, curved staggered motion, all fan directions, interrupted folding and complete restacking',flush=True)

        d=expand();newest=next(r for r in command('list')['windows'] if r['address']==windows[-1])
        click(d['icons'][0]);wait(lambda:all(r['id']!=newest['id'] for r in command('list')['windows']),'Under-pointer icon did not restore newest')
        settle(False);park(windows[-1]);d=expand();keyboard(1)
        wait(lambda:dock()['currentIndex']==1,'Physical arrow direction did not select next icon')
        collapse()
        under=spawn();target='address:'+under
        h.dispatch('window.float',window=target,action='on');h.dispatch('window.resize',window=target,x=640,y=420,relative=False)
        h.dispatch('window.move',window=target,x=monitor['x']+100,y=monitor['y']+100,relative=False)
        for direction in ('horizontal','vertical'):
            configure('floatingDirection',direction)
            d=expand();wait(lambda:shell('status')['clickObserverActive'],'Click observer did not arm')
            pointer.move(*point(250,220))
            wait(lambda:dock()['dismissal']['pending'],'Leaving did not arm timeout')
            time.sleep(.15)
            assert dock()['expanded'],'Pointer movement collapsed fan before grace period'
            r=dock()['icons'][0];pointer.move(*point(r['x']+24,r['y']+24))
            wait(lambda:not dock()['dismissal']['pending'],'Re-entry did not cancel timeout')
            time.sleep(.9);assert dock()['expanded'],'Cancelled leave timer still closed the fan'
            left=time.monotonic();pointer.move(*point(250,220))
            wait(lambda:not dock()['expanded'],'Leave timeout did not close fan',timeout=2)
            assert .6<time.monotonic()-left<2,'Incorrect leave grace duration'
            settle(False)
            expand();wait(lambda:shell('status')['clickObserverActive'],'Click observer did not rearm')
            pointer.move(*point(250,220));time.sleep(.15)
            assert dock()['expanded'],'Focus follows mouse bypassed timeout'
            beforeClick=shell('status')['clickObserverCount']
            clicked=time.monotonic();pointer.button(True);time.sleep(.02);pointer.button(False)
            try:wait(lambda:not dock()['expanded'],'Outside click did not collapse fan immediately',timeout=.5)
            except AssertionError:
                print('Click observer diagnostics:',beforeClick,shell('status')['clickObserverCount'],json.dumps(dock()),flush=True)
                raise
            assert time.monotonic()-clicked<.5 and dock()['lastDismissal']=='outside-click'
            wait(lambda:h.client(under)['title'].endswith(' clicked'),'Outside click was swallowed')
            settle(False)
            # Clicking unused desktop space must also bypass the delay.
            expand();wait(lambda:shell('status')['clickObserverActive'],'Click observer did not rearm')
            pointer.click(*point(1000,220))
            wait(lambda:not dock()['expanded'],'Desktop click did not close fan',timeout=.5)
            assert dock()['lastDismissal']=='outside-click'
            settle(False)
            expand();wait(lambda:shell('status')['clickObserverActive'],'Click observer did not rearm')
            p=dock()['panel'];assert p['radius']>4
            pointer.click(*point(p['x']+1,p['y']+1))
            wait(lambda:not dock()['expanded'],'Transparent corner click did not close fan',timeout=.5)
            assert dock()['lastDismissal']=='outside-click'
            settle(False)
        print('PASS 800 ms leave grace, re-entry cancellation, immediate app/desktop outside clicks and click-through in both orientations',flush=True)
        expand();h.dispatch('focus',workspace=str(workspace+1));wait(lambda:not dock()['expanded'],'Workspace interaction did not close fan')
        h.dispatch('focus',workspace=str(workspace));settle(False)
        print('PASS newest restore, spatial keyboard selection, one-click outside interaction and workspace dismissal',flush=True)

        configure('floatingAnimation','swing')
        subprocess.run(['omarchy','restart','shell'],check=True)
        deadline=time.monotonic()+15
        while True:
            result=subprocess.run(['omarchy-shell','window-stash','status'],capture_output=True,text=True)
            if result.returncode==0 and result.stdout.startswith('{'):
                loaded=json.loads(result.stdout)
                if monitor['name'] in loaded['screens'] and loaded['windows']==len(baseline)+3:break
            if time.monotonic()>deadline:raise AssertionError('Fan stash did not survive restart')
            time.sleep(.1)
        settle(False);assert expand()['style']=='swing';collapse();configure('floatingAnimation','arc')
        print('PASS saved stack anchor, stash and fan behavior after shell restart',flush=True)

        configure('grouping','app');wait(lambda:dock()['groups']==1,'App grouping missing');d=expand();click(d['icons'][0])
        wait(lambda:shell('status')['dialog']=='picker','App group did not open chooser');shell('dismiss');configure('grouping','window');settle(False)
        for mode in ('reduced','off'):
            configure('animations',mode)
            for style in ('arc','glide','cascade','spring','swing'):
                configure('floatingAnimation',style);d=expand()
                assert all(a['maxBend']==0 and a['maxTilt']==0 and a['scale']==1 for a in d['actors']),'Reduced/Off still used spatial curves or transforms'
                collapse()
        configure('floatingAnimation','arc')
        configure('animations','full');configure('iconFrame','hidden');configure('dockFrame','hidden')
        d=expand();assert not d['panel']['frameVisible'] and all(not a['appearance']['frameVisible'] for a in d['icons']);collapse()
        print('PASS app grouping, Reduced/Off, frameless icons and transparent dock background',flush=True)

        outputs={m['name'] for m in h.read('monitors')};h.call('output','create','headless')
        monitor=wait(lambda:next((m for m in h.read('monitors') if m['name'] not in outputs),None),'Virtual output missing')
        output=monitor['name'];end=max(m['x']+round(m['width']/m['scale']) for m in h.read('monitors') if m['name']!=output)
        h.eval('hl.monitor({output=%s,mode="320x240@60",position=%s,scale=1})'%(json.dumps(output),json.dumps('%dx0'%end)))
        monitor=next(m for m in h.read('monitors') if m['name']==output)
        h.dispatch('focus',monitor=output);h.dispatch('focus',workspace=str(workspace+2))
        for _ in range(7):park(spawn())
        for direction in ('vertical','horizontal'):
            configure('floatingDirection',direction);d=expand()
            assert d['capacity']<7
            p=d['panel'];x=p['x']+p['width']/2;y=p['y']+p['height']/2;sign=d['fan']['sign']
            pointer.move(*point(x,y));pointer.button(True)
            for step in range(1,7):pointer.move(*point(x-sign*step*10 if direction=='horizontal' else x,y-sign*step*10 if direction=='vertical' else y));time.sleep(.04)
            pointer.button(False)
            wait(lambda:dock()['firstIndex']>0,'Fan drag did not reveal more windows')
            collapse()
        print('PASS both fan orientations remain bounded and scroll through overflow on a small monitor',flush=True)
        assert not shell('status')['error'],shell('status')['error']
    finally:
        pointer.button(False);shell('dismiss')
        for a in addresses:
            if h.client(a):h.dispatch('window.close',window='address:'+a)
        for p in processes:
            if p.poll() is None:p.terminate()
        wait(lambda:all(not h.client(a) for a in addresses),'Test windows did not close');command('list')
        if output:h.call('output','remove',output)
        for key,value in settings.items():configure(key,value)
        ledger=Stash();current=read_json(ledger.positions,{})
        for key in changed:
            if 'dock:floating' in positions.get(key,{}):current.setdefault(key,{})['dock:floating']=positions[key]['dock:floating']
            elif key in current:
                current[key].pop('dock:floating',None)
                if not current[key]:current.pop(key)
        atomic_json(ledger.positions,current);shell('refresh')
        h.dispatch('focus',workspace=str(original_ws))
        if original.get('address') and h.client(original['address']):h.dispatch('focus',window='address:'+original['address'])
        pointer.close();assert {r['id'] for r in command('list')['windows']}==baseline
        wait(lambda:not shell('status')['clickObserverActive'],'Click observer stayed active after cleanup')
        assert [b for b in h.read('binds') if b.get('description')!='Window Stash click observer']==originalBinds,'Existing mouse/key bindings changed'


if __name__=='__main__':main()
