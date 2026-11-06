#!/usr/bin/env python3
"""Additional live checks: layouts, switcher, concurrency, and virtual monitors."""
import json
import subprocess
import time
import live
from live import h, shell, command, configure, spawn, stash, wait,fixture_settings,require_empty_stash
from desktop_test import desktop_test


def plugin_call(method,arg=''):
    text=subprocess.check_output(['omarchy-shell','shell','call','community.window-switcher',method,arg],text=True).strip()
    return json.loads(text) if text.startswith('{') else text


@desktop_test('Window Stash layout and monitor tests')
def main():
    old_window=h.read('activewindow');old_ws=h.read('activeworkspace')['id']
    monitors=h.read('monitors');snapshot=command('list');settings=snapshot['settings']
    virtual=[]
    require_empty_stash(snapshot)
    try:
        fixture_settings()
        assert not command('list')['windows'],'Restore your stash before running live tests'
        first=spawn('Stash layout alpha');second=spawn('Stash layout beta');third=spawn('Stash layout gamma')
        for a in (first,second,third):h.dispatch('window.float',window='address:'+a,action='off')
        h.eval('hl.workspace_rule({workspace="9",layout="scrolling"})')
        ident=stash(first)
        command('restore',ident,'--to','current','--workspace',9)
        clients={a:h.client(a) for a in (first,second,third)}
        assert all(not c['floating'] for c in clients.values())
        assert clients[first]['at'][0]>max(clients[a]['at'][0] for a in (second,third)),clients
        print('PASS tiled scrolling append',flush=True)

        h.eval('hl.workspace_rule({workspace="9",layout="dwindle"})')
        ident=stash(second)
        command('restore',ident,'--to','current','--workspace',9)
        assert not h.client(second)['floating']
        print('PASS dwindle tiled restore',flush=True)

        h.dispatch('window.close',window='address:'+third)
        h.eval('hl.workspace_rule({workspace="9",layout="scrolling"})')
        # Put the two windows in one explicit Hyprland group.
        h.dispatch('focus',window='address:'+first)
        h.dispatch('group.toggle')
        h.dispatch('focus',window='address:'+second)
        direction='l' if h.client(second)['at'][0]>h.client(first)['at'][0] else 'r'
        h.dispatch('window.move',window='address:'+second,into_group=direction)
        assert len(h.client(second)['grouped'])==2,h.client(second)['grouped']
        ident=stash(second)
        assert h.client(first)['workspace']['id']==9
        command('restore',ident,'--to','current','--workspace',9)
        assert len(h.client(second)['grouped'])<=1
        print('PASS individual grouped-window stash',flush=True)

        # Race two shortcuts against the same client: only one record may win.
        p1=subprocess.Popen([live.binary,'minimize','--address',first],stdout=subprocess.PIPE,text=True)
        p2=subprocess.Popen([live.binary,'minimize','--address',first],stdout=subprocess.PIPE,text=True)
        for p in (p1,p2):
            output=p.communicate(timeout=10)[0];assert p.returncode==0,output
        records=command('list')['windows'];assert len(records)==1,records
        command('restore-last','--to','current','--workspace',9)
        print('PASS concurrent minimize idempotence',flush=True)

        # Select a parked client through the user's existing switcher.
        ident=stash(first)
        payload=json.dumps(dict(query='Stash layout alpha',view='windows',filter='all',showMinimized=True,
                                activation='enter',animationMs=0))
        subprocess.run(['omarchy-shell','shell','summon','community.window-switcher',payload],check=True,capture_output=True)
        wait(lambda:plugin_call('status').get('filteredCount')==1,'Switcher did not find parked window')
        assert plugin_call('status')['selectedAddress'].removeprefix('0x')==first.removeprefix('0x')
        plugin_call('commitSelected')
        wait(lambda:h.client(first)['workspace']['id']==9,'Switcher did not restore parked client')
        assert not command('list')['windows']
        print('PASS existing window-switcher restore',flush=True)

        for n in (2,3):
            before={m['name'] for m in h.read('monitors')}
            print(h.call('output','create','headless'),flush=True)
            new=wait(lambda:next((m for m in h.read('monitors') if m['name'] not in before),None),'Virtual output not created')
            virtual.append(new['name'])
            h.eval('hl.monitor({output=%s,mode="1280x720@60",position=%s,scale=%s})' %
                   (json.dumps(new['name']),json.dumps('%dx0'%(monitors[0]['x']+round(monitors[0]['width']/monitors[0]['scale'])+1280*(n-2))),1.25 if n==2 else 1))
            wait(lambda:len(shell('status')['surfaces'])==len(monitors)+len(virtual),'Missing per-monitor UI surface')
            if n==2:
                h.dispatch('focus',window='address:'+first)
                h.dispatch('window.float',window='address:'+first,action='on')
                h.dispatch('window.resize',window='address:'+first,x=1200,y=900,relative=False)
                ident=stash(first)
                h.dispatch('focus',monitor=new['name'])
                h.dispatch('focus',workspace='19')
                command('restore',ident,'--to','current','--monitor',new['name'],'--workspace',19)
                small=next(m for m in h.read('monitors') if m['name']==new['name'])
                from stash import workarea
                area=workarea(small);client=h.client(first)
                assert client['floating']
                assert client['at'][0]>=area[0] and client['at'][1]>=area[1],(area,client)
                assert client['at'][0]+client['size'][0]<=area[0]+area[2],(area,client)
                assert client['at'][1]+client['size'][1]<=area[1]+area[3],(area,client)
                print('PASS floating restore across resolution and scale with clamping',flush=True)
                ident=stash(first)
            status=wait(lambda:all(s['eligible']==1 for s in shell('status')['surfaces']),'Global stash missing on a monitor')
            configure('scope','workspace')
            wait(lambda:sum(s['eligible'] for s in shell('status')['surfaces'])==1,'Local scope leaked between monitors')
            configure('presentation','bubbles')
            try:
                wait(lambda:sum(len(s['bubbles']) for s in shell('status')['surfaces'])==1,'Local bubbles missing')
            except AssertionError:
                print('BUBBLE DIAGNOSTICS',json.dumps(shell('status')),flush=True)
                raise
            configure('scope','global')
            wait(lambda:all(len(s['bubbles'])==1 for s in shell('status')['surfaces']),'Global bubbles missing on a monitor')
            configure('presentation','dock')
            print('PASS %d-monitor global/local dock and bubbles'% (len(monitors)+len(virtual)),flush=True)

        # Remove the origin display while the client is parked; restore to
        # its local workspace number on the remaining laptop.
        for name in reversed(virtual):h.call('output','remove',name)
        virtual=[]
        wait(lambda:len(h.read('monitors'))==len(monitors),'Output cleanup did not settle')
        h.dispatch('focus',monitor=monitors[0]['name']);h.dispatch('focus',workspace='9')
        command('restore',ident,'--to','original')
        assert h.client(first)['workspace']['id']==9,h.client(first)
        assert h.client(first)['monitor']==monitors[0]['id']
        print('PASS disconnected-monitor origin fallback',flush=True)

        ident=stash(second)
        h.dispatch('window.close',window='address:'+second)
        wait(lambda:not command('list')['windows'],'Closed minimized window left stale record')
        print('PASS close-while-minimized cleanup',flush=True)
    finally:
        subprocess.run(['omarchy-shell','shell','hide','community.window-switcher'],capture_output=True)
        subprocess.run([live.binary,'restore-all','--to','current'],capture_output=True)
        for address in live.addresses:
            if h.client(address):h.dispatch('window.close',window='address:'+address)
        for p in live.processes:
            if p.poll() is None:p.terminate()
        for name in reversed(virtual):h.call('output','remove',name)
        for key,value in settings.items():configure(key,value)
        shell('dismiss')
        h.call('reload')
        for m in monitors:
            h.eval('hl.monitor({output=%s,mode=%s,position=%s,scale=%s,transform=%s})'%(
                json.dumps(m['name']),json.dumps('%dx%d@%.2f'%(m['width'],m['height'],m['refreshRate'])),
                json.dumps('%dx%d'%(m['x'],m['y'])),m['scale'],m['transform']))
        h.dispatch('focus',workspace=str(old_ws))
        if old_window and h.client(old_window['address']):h.dispatch('focus',window='address:'+old_window['address'])


if __name__=='__main__':main()
