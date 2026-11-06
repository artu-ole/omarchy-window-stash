#!/usr/bin/env python3
"""Native velocity, inertia, collisions, interruption, placement, and persistence."""
import math
import time

from desktop_test import desktop_test
from live import command,shell,configure,wait,h
from native_session import NativeSession
from stash import monitor_identity


@desktop_test('Floating drag physics and collision test')
def main():
    with NativeSession() as t:
        configure('sizePreset','100');configure('animationSpeed','normal');configure('hoverPreview','off')
        configure('presentation','bubbles');configure('iconShape','square');configure('animations','full')
        configure('floatingPlacement','free');configure('dragMotion','physics')
        records=[t.park(t.spawn()[0]) for _ in range(3)]
        keys=['window:'+str(r.get('stableId') or r['id']) for r in records]
        initial=t.surface()['bubbles']
        for index,a in enumerate(initial):
            for b in initial[:index]:
                assert a['x']>=b['x']+b['width']+3.5 or b['x']>=a['x']+a['width']+3.5 or a['y']>=b['y']+b['height']+3.5 or b['y']>=a['y']+a['height']+3.5,'New unsaved bubble overlapped an existing resting icon'
        def world():return t.surface()['motion']['dragWorld']
        def body(key):return next(b for b in world()['bodies'] if b['key']==key)
        def asleep():return wait(lambda:world() if not world()['active'] else None,'Physics world did not sleep',timeout=5)
        def target(key):return t.dock()['handle'] if key=='dock:floating' else t.icon(key)
        def position(key,x,y):
            asleep();t.position(key,round(x),round(y));asleep()
        def launch(key,dx,dy,pause=0):
            r=target(key);sx=r['x'];sy=r['y'];t.move(sx+24,sy+24);t.pointer.button(True)
            wait(lambda:body(key)['held'],'Item did not acquire pointer')
            for i in range(1,7):
                t.move(sx+24+dx*i/6,sy+24+dy*i/6);time.sleep(.015)
                if i==3:
                    b=body(key)
                    ex=max(area['x']+8,min(area['x']+area['width']-8-b['width'],sx+dx*i/6))
                    ey=max(area['y']+8,min(area['y']+area['height']-8-b['height'],sy+dy*i/6))
                    assert abs(b['x']-ex)<2 and abs(b['y']-ey)<2,('Held item lagged behind pointer',b,ex,ey)
            # Release directly after the final input. A synchronous status IPC
            # here would itself turn a quick flick into a paused release.
            if pause:time.sleep(pause)
            t.pointer.button(False);return (sx+dx,sy+dy)
        def saved(key):
            b=body(key);identity=monitor_identity(t.monitor)
            wait(lambda:all(abs(x-y)<1 for x,y in zip(command('list')['positions'].get(identity,{}).get(key,[-999,-999]),[b['x'],b['y']])),'Resting coordinates were not saved')
        shell('settings');wait(lambda:t.surface()['dialog']['visible'],'Drag settings did not open')
        from settings_fit import reveal
        def control():return next(c for c in t.surface()['settingControls'] if c['key']=='dragMotion')
        t.click(reveal(t,lambda:control()['rect']));wait(lambda:control()['open'],'Drag motion dropdown did not open')
        t.keys('-k','Down','-k','Return');wait(lambda:shell('status')['settings']['dragMotion']=='direct','Native Direct option did not save')
        t.click(reveal(t,lambda:control()['rect']));wait(lambda:control()['open'],'Drag motion dropdown did not reopen')
        t.keys('-k','Up','-k','Return');wait(lambda:shell('status')['settings']['dragMotion']=='physics','Native Physics option did not save')
        shell('dismiss');asleep()
        print('PASS native Physics/Direct selector and deferred frozen-body configuration',flush=True)
        area=t.surface()['usableArea'];w=t.surface()['width'];height=t.surface()['height']
        position(keys[1],w-80,height*.72);position(keys[2],w-80,height*.86)
        position(keys[0],w*.2,height*.35)
        endpoint=launch(keys[0],170,0)
        def in_motion():
            b=body(keys[0]);return b if b['moving'] else None
        moving=wait(in_motion,'Flick did not gain momentum')
        assert moving['vx']>120 and abs(moving['vy'])<5,moving
        asleep();b=body(keys[0]);assert b['x']>endpoint[0]+20 and abs(b['y']-endpoint[1])<2,b
        assert b['frames']>=2;saved(keys[0])
        print('PASS direct pointer tracking, directional momentum, deceleration, sleeping, final-only persistence',flush=True)

        position(keys[0],w*.2,height*.35);endpoint=launch(keys[0],100,40,pause=.18)
        asleep();b=body(keys[0]);assert math.hypot(b['x']-endpoint[0],b['y']-endpoint[1])<2,'Paused release retained stale velocity'
        position(keys[0],w*.2,height*.35);launch(keys[0],120,0)
        # Pointer is still on the released icon. Catch it before it can coast away.
        t.pointer.button(True);wait(lambda:body(keys[0])['held'],'Could not catch moving icon')
        caught=body(keys[0]);time.sleep(.2);b=body(keys[0])
        assert abs(b['x']-caught['x'])<.01 and abs(b['y']-caught['y'])<.01,'Caught icon continued moving'
        t.move(caught['x']+24+25,caught['y']+24);time.sleep(.18);t.pointer.button(False);asleep()
        print('PASS stale velocity rejection and grabbing a moving icon without jumps',flush=True)

        position(keys[0],w*.25,height*.45);position(keys[1],w*.25+90,height*.45)
        before=body(keys[1]);launch(keys[0],120,0,pause=.18);asleep()
        after=body(keys[1]);assert after['collisions']>before['collisions'] and math.hypot(after['x']-before['x'],after['y']-before['y'])>4,'Collision did not nudge neighbor'
        for key in keys:
            b=body(key);assert b['x']>=area['x']+7.5 and b['y']>=area['y']+7.5 and b['x']+b['width']<=area['x']+area['width']-7.5 and b['y']+b['height']<=area['y']+area['height']-7.5
        saved(keys[0]);saved(keys[1])
        print('PASS gentle collisions, neighbor displacement, bounds, and affected position persistence',flush=True)

        for animations,motion in (('full','direct'),('reduced','physics'),('off','physics')):
            configure('animations',animations);configure('dragMotion',motion);asleep()
            position(keys[0],w*.2,height*.3);end=launch(keys[0],110,0);asleep();b=body(keys[0])
            assert math.hypot(b['x']-end[0],b['y']-end[1])<2,(animations,motion,b,end)
        print('PASS Direct and Reduced/Off suppress momentum without changing click/drag semantics',flush=True)

        configure('animations','full');configure('dragMotion','physics');configure('floatingPlacement','edges');asleep()
        edge_start=body(keys[0])
        launch(keys[0],130 if edge_start['x']<w/2 else -130,70 if edge_start['y']<height/2 else -70);asleep()
        b=body(keys[0]);assert min(abs(b['x']-area['x']-8),abs(b['y']-area['y']-8),abs(b['x']+48-area['x']-area['width']+8),abs(b['y']+48-area['y']-area['height']+8))<.5
        saved(keys[0])
        configure('presentation','floating');configure('floatingPlacement','free');t.resting();asleep()
        key='dock:floating';t.touch(key);position(key,w*.2,height*.4);end=launch(key,150,0)
        wait(lambda:body(key)['moving'],'Stack flick did not gain momentum');asleep();assert body(key)['x']>end[0]+15;saved(key)
        t.click(t.dock()['handle']);wait(lambda:t.dock()['expanded'] and not t.dock()['animating'],'Stack did not unfold')
        frozen=body(key);assert frozen['frozen'];front=t.dock()['actors'][0]
        t.click(t.dock()['icons'][1],273);wait(lambda:t.menu()['visible'],'Moving/frozen context menu did not open')
        assert t.dock()['handle']['x']==front['x'] and t.dock()['handle']['y']==front['y']
        t.keys('-k','Escape');wait(lambda:not t.menu()['opened'],'Menu did not close');asleep()
        configure('floatingPlacement','edges');asleep();saved(key)
        print('PASS collapsed-stack flicks, edge placement, frozen unfold/context origin and zero-momentum resume',flush=True)

        r=t.dock()['handle'];t.move(r['x']+24,r['y']+24);t.pointer.button(True)
        wait(lambda:t.dock()['handle']['held'],'Dock did not grab before mode switch')
        configure('presentation','bubbles')
        wait(lambda:not t.dock()['handle']['held'] and all(b['key']!=key for b in world()['bodies']),'Removed dock left a grab/body behind')
        t.pointer.button(False)
        under,title=t.spawn();h.dispatch('window.float',window='address:'+under,action='on')
        h.dispatch('window.resize',window='address:'+under,x=640,y=420,relative=False)
        h.dispatch('window.move',window='address:'+under,x=t.monitor['x']+100,y=t.monitor['y']+100,relative=False)
        t.pointer.click(*t.point(250,220));wait(lambda:h.client(under)['title']==title+' clicked','Removed dock left ghost fullscreen input')
        configure('presentation','floating');asleep();t.resting()
        print('PASS mode switch during a held dock removes its body and releases fullscreen input',flush=True)
        expected=(body(key)['x'],body(key)['y'])
        import subprocess,json
        subprocess.run(['omarchy','restart','shell'],check=True)
        def loaded():
            r=subprocess.run(['omarchy-shell','window-stash','status'],capture_output=True,text=True)
            if r.returncode or not r.stdout.startswith('{'):return False
            s=json.loads(r.stdout)
            return t.monitor['name'] in s['screens'] and s['settings'].get('dragMotion')=='physics' and not s['error']
        wait(loaded,'Physics setting did not survive shell restart',timeout=15)
        h.dispatch('focus',workspace=str(t.workspace));t.resting();asleep()
        assert math.hypot(body(key)['x']-expected[0],body(key)['y']-expected[1])<1
        assert body(key)['vx']==0 and body(key)['vy']==0
        print('PASS Physics selection and final resting position survive restart without stored momentum',flush=True)


if __name__=='__main__':main()
