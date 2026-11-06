#!/usr/bin/env python3
"""Pointer menu geometry, targeting, native actions, dismissal, and scoped close-all."""
import time
import json

from desktop_test import desktop_test
from live import h,command,shell,configure,wait
from native_session import NativeSession


@desktop_test('Pointer context menu and scoped actions test')
def main():
    with NativeSession() as t:
        configure('sizePreset','100');configure('animationSpeed','normal');configure('hoverPreview','off')
        configure('animations','full');configure('presentation','bubbles');configure('floatingPlacement','free')
        if 'dragMotion' in shell('status')['settings']:configure('dragMotion','direct')
        configure('iconShape','square')
        a,_=t.spawn();b,_=t.spawn();ra=t.park(a);rb=t.park(b);t.resting()
        key='window:'+str(rb.get('stableId') or rb['id'])
        def open_menu(rect):
            if rect.get('key') and rect.get('appearance',{}).get('pointer'):
                # A saved-position update acknowledges logical geometry before
                # the next Wayland frame commits its new input region.
                x=rect['x']+rect['width']/2;y=rect['y']+rect['height']/2
                motion=[False]
                def entered():
                    motion[0]=not motion[0]
                    t.move(x+(1 if motion[0] else 0),y)
                    icon=t.icon(rect['key'])
                    return icon and icon['appearance']['pointer']['hover']
                wait(entered,'The repositioned context-menu icon never became interactive')
            before=shell('status');serial=t.menu()['serial'];history=[]
            def sample():
                status=shell('status');m=t.menu()
                state=dict(serial=m['serial'],opened=m['opened'],progress=m['progress'],
                           observer=status['clickObserverCount'],armed=status['clickObserverActive'],
                           context=status['context'],surfaceWorkspace=t.surface()['workspaceId'],
                           activeWorkspace=h.read('activeworkspace')['id'])
                if not history or history[-1]!=state:
                    history.append(state)
                return m if m['serial']>serial and m['visible'] else None
            t.click(rect,273)
            try:
                m=wait(sample,'Pointer context menu did not open')
                if before['clickObserverActive']:
                    wait(lambda:shell('status')['clickObserverCount']>before['clickObserverCount'],
                         'The already-armed observer did not report the opening right press')
                    assert t.menu()['opened'],'The opening right press dismissed its own context menu'
            except AssertionError:
                print('Menu invocation diagnostics:',{'before':before['context'],'observerBefore':before['clickObserverCount'],
                      'armedBefore':before['clickObserverActive'],'requestedRect':rect,'history':history[:8]+history[-16:],
                      'cursor':h.read('cursorpos'),'input':t.surface().get('input'),'menu':t.menu()},flush=True)
                raise
            assert not shell('status')['error'],shell('status')['error']
            return m
        def dismiss():
            t.keys('-k','Escape');wait(lambda:not t.menu()['rendered'],'Escape did not dismiss context menu')
        def restore_diagnostics(record,workspace,menu):
            status=shell('status');client=h.client(record['address'])
            print('Restore invocation diagnostics:',{'expectedWorkspace':workspace,'expectedId':record['id'],
                  'surfaceWorkspace':t.surface()['workspaceId'],'activeWorkspace':h.read('activeworkspace')['id'],
                  'clientWorkspace':client['workspace']['id'] if client else None,
                  'menuWorkspace':menu['workspace'],'menuIds':menu['targetIds'],'context':status['context'],
                  'controllerBusy':status['controllerBusy'],'queueLength':status['queueLength'],'error':status['error'],
                  'ledger':[{'id':w['id'],'originWorkspace':w['origin']['id']} for w in command('list')['windows']]},flush=True)
        def invocation_menu(record,workspace):
            h.dispatch('focus',workspace=str(workspace))
            wait(lambda:t.surface()['workspaceId']==workspace and h.read('activeworkspace')['id']==workspace,
                 'Invoking workspace did not reach the UI before opening its menu')
            menu_key='window:'+str(record.get('stableId') or record['id'])
            m=open_menu(t.icon(menu_key))
            if m['targetIds']!=[record['id']] or m['workspace']!=workspace:
                restore_diagnostics(record,workspace,m)
            assert m['targetIds']==[record['id']],'Restore menu captured a stale stash record'
            assert m['workspace']==workspace,'Restore menu captured the wrong invoking workspace'
            return m
        for x,y in ((20,60),(t.surface()['width']-70,60),(20,t.surface()['height']-90),(t.surface()['width']-70,t.surface()['height']-90)):
            t.position(key,x,y);r=t.icon(key);px=r['x']+24;py=r['y']+24
            m=open_menu(r);p=m['rect'];area=t.surface()['usableArea']
            assert abs(m['point']['x']-px)<1 and abs(m['point']['y']-py)<1,'Context anchor was not the actual click'
            assert p['x']>=area['x'] and p['y']>=area['y'] and p['x']+p['width']<=area['x']+area['width'] and p['y']+p['height']<=area['y']+area['height'],m
            assert min(abs(p['x']-px),abs(p['x']+p['width']-px))<12,'Menu moved away from pointer'
            assert m['targetIds']==[rb['id']]
            assert t.action('close')['rect']['y']<m['separatorY']<t.action('all')['rect']['y']
            t.move(t.surface()['width']/2,40);time.sleep(.9);assert t.menu()['opened'],'Leaving unexpectedly dismissed menu'
            dismiss()
        print('PASS actual pointer anchor, all screen corners, separator, exact icon target, pointer leave and Escape',flush=True)

        under,title=t.spawn();h.dispatch('window.float',window='address:'+under,action='on')
        h.dispatch('window.resize',window='address:'+under,x=640,y=420,relative=False)
        h.dispatch('window.move',window='address:'+under,x=t.monitor['x']+100,y=t.monitor['y']+100,relative=False)
        open_menu(t.icon(key));t.pointer.click(*t.point(250,220))
        wait(lambda:not t.menu()['opened'],'Outside click did not close menu')
        wait(lambda:h.client(under)['title']==title+' clicked','Menu swallowed the outside click')
        open_menu(t.icon(key));t.keys('-k','End','-k','Return')
        wait(lambda:shell('status')['dialog']=='settings' and t.surface()['dialog']['visible'],'Keyboard Settings did not open')
        assert not t.menu()['opened'];shell('dismiss')
        open_menu(t.icon(key));h.dispatch('focus',workspace=str(t.workspace+1))
        wait(lambda:not t.menu()['opened'],'Workspace switch did not close menu')
        h.dispatch('focus',workspace=str(t.workspace))
        print('PASS single-click outside delivery, keyboard navigation, Settings transition, and workspace dismissal',flush=True)

        for mode in ('dock','floating'):
            configure('presentation',mode);t.resting()
            r=t.icon(key) if mode=='dock' else t.dock()['handle']
            m=open_menu(r);assert m['targetIds']==[rb['id']],'Collapsed stack did not target front icon'
            dismiss()
            if mode=='floating':
                t.click(t.dock()['handle']);wait(lambda:t.dock()['expanded'] and not t.dock()['animating'],'Fan did not unfold')
                wait(lambda:shell('status')['clickObserverActive'],'Expanded fan did not arm the opening-press regression fixture')
                m=open_menu(t.dock()['icons'][1]);assert m['targetIds']==[ra['id']]
                dismiss()
        print('PASS static dock, expanded fan, and collapsed front-icon menus',flush=True)

        configure('presentation','bubbles');configure('scope','global')
        m=invocation_menu(rb,t.workspace+1);t.click(t.action('original')['rect'])
        wait(lambda:h.client(b)['workspace']['id']==t.workspace,'Original-workspace action restored wrong destination')
        rb=t.park(b);key='window:'+str(rb.get('stableId') or rb['id'])
        m=invocation_menu(rb,t.workspace+1);t.click(t.action('here')['rect'])
        try:wait(lambda:h.client(b)['workspace']['id']==t.workspace+1,'Restore-here action ignored invoking workspace')
        except AssertionError:
            restore_diagnostics(rb,t.workspace+1,m)
            raise
        h.dispatch('focus',workspace=str(t.workspace));configure('scope','workspace')
        h.dispatch('window.move',window='address:'+b,workspace=str(t.workspace),follow=True)
        rb=t.park(b);key='window:'+str(rb.get('stableId') or rb['id'])
        configure('grouping','app');t.resting()
        t.click(t.icon());wait(lambda:shell('status')['dialog']=='picker' and t.surface()['dialog']['visible'],'Grouped picker did not open')
        picker=t.surface()['picker']
        m=open_menu({'x':picker['x'],'y':picker['y'],'width':80,'height':48})
        assert len(m['targetIds'])==1,'Chooser-row menu did not target just that row'
        dismiss();t.keys(ra['title'])
        wait(lambda:t.surface()['pickerCount']==1,'Search focus did not return after dismissing row context menu')
        shell('dismiss');t.resting();m=open_menu(t.icon())
        assert set(m['targetIds'])=={ra['id'],rb['id']} and '2' in t.action('close')['text']
        t.click(t.action('close')['rect'])
        wait(lambda:not h.client(a) and not h.client(b),'Grouped menu did not close represented windows')
        assert h.client(under),'Grouped close touched unstashed window of same app'
        print('PASS restore destinations and grouped close without touching unstashed app windows',flush=True)

        configure('grouping','window');h.dispatch('focus',workspace=str(t.workspace))
        a,_=t.spawn();ra=t.park(a)
        h.dispatch('focus',workspace=str(t.workspace+1));b,_=t.spawn();rb=t.park(b)
        h.dispatch('focus',workspace=str(t.workspace));t.resting();m=open_menu(t.icon())
        assert 'workspace' in t.action('closeAll')['text'].lower()
        t.click(t.action('closeAll')['rect'])
        wait(lambda:not h.client(a),'Workspace close-all did not close target')
        assert h.client(b) and h.client(under),'Workspace close-all escaped its scope'
        configure('scope','global');t.resting();m=open_menu(t.icon('window:'+str(rb.get('stableId') or rb['id'])))
        assert 'workspace' not in t.action('closeAll')['text'].lower()
        if not t.baseline:
            t.click(t.action('closeAll')['rect']);wait(lambda:not h.client(b),'Global UI close-all did not close eligible stash')
        else:dismiss()
        print('PASS visibility-dependent close-all labels and workspace scope; isolated backend suite covers global closure safely',flush=True)
        # A close action from a chooser row must not leave the picker over a Save prompt.
        configure('scope','workspace');configure('grouping','window');h.dispatch('focus',workspace=str(t.workspace))
        prompted,title=t.spawn(mode='prompt',app='org.windowstash.MenuPrompt');record=t.park(prompted)
        shell('all');wait(lambda:t.surface()['dialog']['visible'],'Recovery picker did not open')
        t.keys(title);wait(lambda:t.surface()['pickerCount']==1,'Prompt target search did not narrow picker')
        picker=t.surface()['picker'];m=open_menu({'x':picker['x'],'y':picker['y'],'width':80,'height':48})
        assert m['targetIds']==[record['id']]
        t.click(t.action('close')['rect'])
        prompt=wait(lambda:next((c for c in h.read('clients') if c['title']==title+' save changes' and c['workspace']['id']==t.workspace),None),'Chooser close did not show Save prompt')
        assert shell('status')['dialog']=='' and not t.surface()['dialog']['visible'],'Picker obscured application Save prompt'
        h.dispatch('focus',window='address:'+prompt['address']);t.keys('-k','Escape')
        wait(lambda:not h.client(prompt['address']),'Save prompt Cancel failed');assert h.client(prompted)
        print('PASS chooser-origin close dismisses picker and exposes native Save/Cancel prompt',flush=True)

        # Real secondary scaled output; no physical output profile is modified.
        old_outputs={m['name'] for m in h.read('monitors')};h.call('output','create','headless')
        extra=wait(lambda:next((m for m in h.read('monitors') if m['name'] not in old_outputs),None),'Headless monitor did not appear')
        t.outputs.append(extra['name'])
        end=max(m['x']+round(m['width']/m['scale']) for m in h.read('monitors') if m['name']!=extra['name'])
        h.eval('hl.monitor({output=%s,mode="640x480@60",position=%s,scale=1.25})'%(json.dumps(extra['name']),json.dumps('%dx0'%end)))
        t.monitor=wait(lambda:next((m for m in h.read('monitors') if m['name']==extra['name'] and m['width']==640 and abs(m['scale']-1.25)<.01),None),'Scaled profile did not apply')
        t.move(round(t.monitor['width']/t.monitor['scale']/2),round(t.monitor['height']/t.monitor['scale']/2))
        h.dispatch('focus',monitor=t.monitor['name']);h.dispatch('focus',workspace=str(t.workspace+3))
        configure('presentation','bubbles');configure('floatingPlacement','free')
        scaled,_=t.spawn(workspace=t.workspace+3);scaled_record=t.park(scaled);scaled_key='window:'+str(scaled_record.get('stableId') or scaled_record['id'])
        t.resting();s=t.surface();area=s['usableArea']
        assert scaled_record['origin']['id']==t.workspace+3,'Scaled fixture was not placed on its explicit workspace'
        t.position(scaled_key,area['x']+area['width']-65,area['y']+area['height']-65)
        m=open_menu(t.icon(scaled_key));p=m['rect'];area=t.surface()['usableArea']
        assert m['screen']==t.monitor['name'] and p['x']>=area['x'] and p['y']>=area['y'] and p['x']+p['width']<=area['x']+area['width'] and p['y']+p['height']<=area['y']+area['height']
        t.keys('-k','End','-k','Return');wait(lambda:shell('status')['dialog']=='settings','Scaled menu keyboard Settings failed')
        shell('dismiss')
        print('PASS second scaled monitor pointer coordinates, edge fitting, and keyboard action',flush=True)
        assert not shell('status')['error'],shell('status')['error']


if __name__=='__main__':main()
