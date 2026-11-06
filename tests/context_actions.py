#!/usr/bin/env python3
"""Pointer menu geometry, targeting, native actions, dismissal, and scoped close-all."""
import time

from desktop_test import desktop_test
from live import h,command,shell,configure,wait
from native_session import NativeSession


@desktop_test('Pointer context menu and scoped actions test')
def main():
    with NativeSession() as t:
        configure('animations','full');configure('presentation','bubbles');configure('floatingPlacement','free')
        if 'dragMotion' in shell('status')['settings']:configure('dragMotion','direct')
        configure('iconShape','square')
        a,_=t.spawn();b,_=t.spawn();ra=t.park(a);rb=t.park(b);t.resting()
        key='window:'+str(rb.get('stableId') or rb['id'])
        def open_menu(rect):
            t.click(rect,273)
            m=wait(lambda:t.menu() if t.menu()['visible'] else None,'Pointer context menu did not open')
            assert not shell('status')['error'],shell('status')['error']
            return m
        def dismiss():
            t.keys('-k','Escape');wait(lambda:not t.menu()['rendered'],'Escape did not dismiss context menu')
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
                m=open_menu(t.dock()['icons'][1]);assert m['targetIds']==[ra['id']]
                dismiss()
        print('PASS static dock, expanded fan, and collapsed front-icon menus',flush=True)

        configure('presentation','bubbles');configure('scope','global');h.dispatch('focus',workspace=str(t.workspace+1))
        open_menu(t.icon(key));t.click(t.action('original')['rect'])
        wait(lambda:h.client(b)['workspace']['id']==t.workspace,'Original-workspace action restored wrong destination')
        rb=t.park(b);key='window:'+str(rb.get('stableId') or rb['id'])
        h.dispatch('focus',workspace=str(t.workspace+1));open_menu(t.icon(key));t.click(t.action('here')['rect'])
        wait(lambda:h.client(b)['workspace']['id']==t.workspace+1,'Restore-here action ignored invoking workspace')
        h.dispatch('focus',workspace=str(t.workspace));configure('scope','workspace')
        h.dispatch('window.move',window='address:'+b,workspace=str(t.workspace),follow=True)
        rb=t.park(b);key='window:'+str(rb.get('stableId') or rb['id'])
        configure('grouping','app');t.resting();m=open_menu(t.icon())
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
        assert not shell('status')['error'],shell('status')['error']


if __name__=='__main__':main()
