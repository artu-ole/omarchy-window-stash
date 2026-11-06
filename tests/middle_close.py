#!/usr/bin/env python3
"""Completed middle-click closure, pending icons, grouping, and save prompts."""
from pathlib import Path
import time

from desktop_test import desktop_test
from live import h,command,shell,configure,wait
from native_session import NativeSession
from stash import SPECIAL,read_json


def window_key(record):return 'window:'+str(record.get('stableId') or record['id'])


@desktop_test('Middle-click close and confirmed lifecycle test')
def main():
    with NativeSession() as t:
        configure('animations','full');configure('floatingPlacement','free')
        configure('grouping','window');configure('iconShape','square')
        if 'dragMotion' in shell('status')['settings']:configure('dragMotion','direct')
        control,_=t.spawn(app='org.windowstash.MiddleControl');control_record=t.park(control)
        control_id=control_record['id']

        def live_record(ident):return next((w for w in command('list')['windows'] if w['id']==ident),None)
        def ledger_record(ident):
            # The controller holds its lock during the grace period. Read its
            # atomic ledger directly; another CLI list would wait for closure.
            return next((w for w in read_json(Path(t.snapshot['statePath']),{}).get('windows',[]) if w['id']==ident),None)
        def ready_icon(key=None):
            t.resting()
            def ready():
                r=t.icon(key)
                return r if r and r['appearance']['presence']>.999 else None
            return wait(ready,'Middle-click icon did not settle')
        def fast_middle(rect,count=1):
            point=t.point(rect['x']+rect['width']/2,rect['y']+rect['height']/2)
            t.pointer.move(*point)
            for _ in range(count):
                t.pointer.button(True,274);time.sleep(.01);t.pointer.button(False,274)
        def view(status):return next(s for s in status['surfaces'] if s['screen']==t.monitor['name'])
        def no_unrelated_ui(status):
            assert status['dialog']=='',('Middle click opened a menu or dialog',status['dialog'])
            assert not view(status)['contextMenu']['opened'],'Middle click opened the context menu'

        for presentation in ('dock','bubbles','floating'):
            configure('presentation',presentation)
            target,_=t.spawn(mode='delay',app='org.windowstash.MiddleDelayed',delay=500)
            record=t.park(target);key=window_key(record)
            rect=ready_icon(None if presentation=='floating' else key)
            if presentation=='floating':
                assert not t.dock()['expanded'] and t.dock()['windows']==2
                assert t.dock()['actors'][0]['key']==key,'Delayed target is not front of the collapsed stack'
            began=time.monotonic()
            fast_middle(rect,3)
            def pending():
                s=shell('status')
                return s if record['id'] in s['pendingCloseIds'] else None
            status=wait(pending,'Middle click did not register a pending close',timeout=.4)
            assert status['pendingCloseIds'].count(record['id'])==1,'Repeated middle clicks duplicated the pending target'
            assert status['queueLength']<=1,'Repeated middle clicks enqueued duplicate close requests'
            no_unrelated_ui(status)
            surface=view(status)
            icons=surface['shelf']['icons'] if presentation=='dock' else surface['bubbles'] if presentation=='bubbles' else [surface['floatingDock']['handle']]
            held_icon=next((i for i in icons if presentation=='floating' or i['key']==key),None)
            assert held_icon and held_icon['appearance']['presence']>.999,'Icon disappeared before the window closed'
            assert not held_icon['appearance']['retiring'],'Pending close started an optimistic icon exit'
            assert abs(held_icon['x']-rect['x'])<.01 and abs(held_icon['y']-rect['y'])<.01,'Middle click moved the icon'
            assert not held_icon.get('held',False),'Middle click started a drag'
            assert not surface['floatingDock']['expanded'],'Middle click expanded the floating stack'
            assert ledger_record(record['id']),'Stash record was removed before confirmed closure'
            c=h.client(target)
            assert c and c['workspace']['name']==SPECIAL,'Pending close restored the window prematurely'
            wait(lambda:not h.client(target),'Middle-clicked delayed window did not close')
            assert time.monotonic()-began>=.4,'Delayed fixture closed without its grace interval'
            wait(lambda:not live_record(record['id']),'Closed window record did not reconcile')
            wait(lambda:record['id'] not in shell('status')['pendingCloseIds'],'Pending close flag did not clear')
            assert h.client(control) and live_record(control_id),'Middle click touched the neighboring stashed window'
            t.resting()
            print('PASS '+presentation+' middle click waits for actual closure, preserves icon/position, and coalesces repeated clicks',flush=True)

        configure('presentation','floating')
        for orientation in ('vertical','horizontal'):
            configure('floatingDirection',orientation)
            target,_=t.spawn(mode='immediate',app='org.windowstash.MiddleFanTarget');record=t.park(target)
            other,_=t.spawn(mode='immediate',app='org.windowstash.MiddleFanOther');other_record=t.park(other)
            ready_icon();t.click(t.dock()['handle'])
            wait(lambda:t.dock()['expanded'] and not t.dock()['animating'],'Fan did not unfold for middle click')
            rect=next(i for i in t.dock()['icons'] if i['key']==window_key(record))
            assert t.dock()['icons'][0]['key']!=window_key(record),'Test must target a non-front fan icon'
            fast_middle(rect)
            wait(lambda:not h.client(target),'Expanded fan middle click did not close the selected window')
            wait(lambda:not live_record(record['id']),'Expanded fan record did not reconcile')
            wait(lambda:t.dock()['expanded'] and not t.dock()['animating'],'Fan closed despite two remaining windows')
            no_unrelated_ui(shell('status'))
            assert h.client(other) and h.client(control),'Expanded middle click closed the wrong icon'
            assert live_record(other_record['id']) and live_record(control_id)
            t.keys('-k','Escape');wait(lambda:not t.dock()['expanded'] and not t.dock()['animating'],'Fan did not fold after test')
            command('close',other_record['id'],'--monitor',t.monitor['name'],'--workspace',t.workspace)
            wait(lambda:not h.client(other),'Temporary fan neighbor did not close')
            print('PASS '+orientation+' fan middle click targets its own icon and keeps the remaining fan open',flush=True)

        configure('presentation','bubbles');configure('grouping','app')
        app='org.windowstash.MiddleGroup'
        first,_=t.spawn(mode='immediate',app=app);one=t.park(first)
        second,_=t.spawn(mode='immediate',app=app);two=t.park(second)
        unstashed,_=t.spawn(mode='immediate',app=app)
        key='app:'+one['app'].lower();rect=ready_icon(key)
        assert rect['appearance']['badge']['visible'],'Grouped middle-click target did not contain both windows'
        fast_middle(rect)
        wait(lambda:not h.client(first) and not h.client(second),'Grouped middle click did not close represented windows')
        wait(lambda:not live_record(one['id']) and not live_record(two['id']),'Grouped close did not reconcile both records')
        assert h.client(unstashed),'Grouped middle click closed an unstashed window of the same app'
        assert h.client(control) and live_record(control_id)
        no_unrelated_ui(shell('status'))
        print('PASS grouped middle click closes represented stashed windows while preserving unstashed app windows',flush=True)

        configure('grouping','window')
        prompt,title=t.spawn(mode='prompt',app='org.windowstash.MiddlePrompt');record=t.park(prompt)
        fast_middle(ready_icon(window_key(record)))
        wait(lambda:(c:=h.client(prompt)) and c['workspace']['id']==t.workspace,'Save-prompt target did not come forward')
        dialog=wait(lambda:next((c for c in h.read('clients') if c['title']==title+' save changes'),None),'Save prompt did not appear')
        wait(lambda:not live_record(record['id']),'Restored save-prompt target stayed in the stash')
        h.dispatch('focus',window='address:'+dialog['address']);t.keys('-k','Return')
        wait(lambda:(c:=h.client(prompt)) and c['title']==title+' cancelled','Save cancellation did not keep the app open')
        assert h.client(prompt)['workspace']['id']==t.workspace and not live_record(record['id'])
        assert h.client(control) and live_record(control_id)
        no_unrelated_ui(shell('status'))
        assert not shell('status')['error'],shell('status')['error']
        print('PASS middle-click save prompt is visible, cancellation keeps the restored window, and no force-close occurs',flush=True)


if __name__=='__main__':main()
