"""Preserving helpers for notified native desktop tests; no actions at import time."""
import copy
import json
import os
import subprocess
import time

from live import ROOT,h,command,shell,configure,wait
from pointer import Pointer
from stash import Stash,atomic_json,read_json,monitor_identity


class NativeSession:
    def __enter__(self):
        self.original=h.read('activewindow');self.original_ws=h.read('activeworkspace')['id']
        self.snapshot=command('list');self.settings=copy.deepcopy(self.snapshot['settings'])
        self.baseline={w['id'] for w in self.snapshot['windows']}
        self.monitor=next(m for m in h.read('monitors') if m['focused'])
        self.workspace=1000000+os.getpid()*10
        assert all(w['id'] not in range(self.workspace,self.workspace+5) for w in h.read('workspaces'))
        self.processes=[];self.addresses=[];self.outputs=[];self.touched={};self.pointer=Pointer()
        shell('dismiss');configure('scope','workspace');configure('grouping','window')
        h.dispatch('focus',workspace=str(self.workspace))
        wait(lambda:self.monitor['name'] in shell('status')['screens'],'Shell snapshot missing')
        return self

    def surface(self):return next(s for s in shell('status')['surfaces'] if s['screen']==self.monitor['name'])
    def dock(self):return self.surface()['floatingDock']
    def menu(self):return self.surface()['contextMenu']
    def point(self,x,y):
        monitors=h.read('monitors');m=next(m for m in monitors if m['name']==self.monitor['name'])
        left=min(m['x'] for m in monitors);top=min(m['y'] for m in monitors)
        right=max(m['x']+round(m['width']/m['scale']) for m in monitors)
        bottom=max(m['y']+round(m['height']/m['scale']) for m in monitors)
        return m['x']+x-left,m['y']+y-top,right-left,bottom-top
    def move(self,x,y):self.pointer.move(*self.point(x,y))
    def click(self,r,button=272):
        x=r['x']+r['width']/2;y=r['y']+r['height']/2
        self.move(x-1,y);self.pointer.click(*self.point(x,y),button=button)
    def keys(self,*args):subprocess.run(['wtype',*args],check=True)
    def spawn(self,mode=None,app='org.windowstash.NativeTest',delay=500):
        title='Stash native %s %s'%(os.getpid(),len(self.addresses))
        args=[title,app] if mode is None else [title,app,mode,str(delay)]
        fixture='test-window.py' if mode is None else 'close-window.py'
        p=subprocess.Popen(['/usr/bin/python3',str(ROOT/'tests'/fixture),*args],
            env=dict(os.environ,GDK_BACKEND='wayland',PYTHONDONTWRITEBYTECODE='1'),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        self.processes.append(p)
        c=wait(lambda:next((c for c in h.read('clients') if c['title']==title),None),'Native test window missing')
        self.addresses.append(c['address']);return c['address'],title
    def park(self,address):
        ident=command('minimize','--address',address)['id']
        r=wait(lambda:next((w for w in command('list')['windows'] if w['id']==ident),None),'Stash record missing')
        wait(lambda:any(w['id']==ident for w in self.surface_records()),'UI stash snapshot missing')
        self.touch('window:'+str(r.get('stableId') or ident));self.touch('app:'+r['app'].lower());self.touch('dock:floating')
        return r
    def surface_records(self):
        # Controller completion and UI snapshot are separately scheduled.
        return command('list')['windows'] if shell('status')['windows']==len(command('list')['windows']) else []
    def touch(self,key):self.touched.setdefault(monitor_identity(self.monitor),set()).add(key)
    def icon(self,key=None):
        s=self.surface();mode=shell('status')['settings']['presentation']
        items=s['bubbles'] if mode=='bubbles' else s['shelf']['icons'] if mode=='dock' else self.dock()['icons'] if self.dock()['expanded'] else [self.dock()['handle']]
        return next((i for i in items if key is None or i.get('key')==key),None)
    def action(self,key):
        items=self.menu()['actions'];return next(a for a in items if a['id']==key)
    def resting(self):
        return wait(lambda:self.surface() if not self.dock()['snapping'] and not self.dock()['animating'] and not any(b['animating'] for b in self.surface()['bubbles']) else None,'Floating items did not settle')
    def position(self,key,x,y):
        self.touch(key);command('position',monitor_identity(self.monitor),key,x,y);shell('refresh')
        wait(lambda:(r:=self.icon(key if key!='dock:floating' else None)) and abs(r['x']-x)<2 and abs(r['y']-y)<2,'Position did not load')
        self.resting()
    def __exit__(self,kind,value,trace):
        try:
            self.pointer.button(False);self.pointer.button(False,273);self.pointer.button(False,274)
            shell('dismiss')
            for p in self.processes:
                if p.poll() is None:p.terminate()
            for p in self.processes:
                try:p.wait(timeout=3)
                except subprocess.TimeoutExpired:p.kill();p.wait(timeout=3)
            wait(lambda:all(not h.client(a) for a in self.addresses),'Native fixtures did not close')
            for output in self.outputs:h.call('output','remove',output)
            command('list')
            for key,value in self.settings.items():configure(key,value)
            ledger=Stash();positions=read_json(ledger.positions,{})
            for monitor,keys in self.touched.items():
                for key in keys:
                    if key in self.snapshot['positions'].get(monitor,{}):positions.setdefault(monitor,{})[key]=self.snapshot['positions'][monitor][key]
                    elif monitor in positions:positions[monitor].pop(key,None)
                if monitor in positions and not positions[monitor]:positions.pop(monitor)
            atomic_json(ledger.positions,positions);shell('refresh')
            h.dispatch('focus',workspace=str(self.original_ws))
            if self.original.get('address') and h.client(self.original['address']):h.dispatch('focus',window='address:'+self.original['address'])
            assert {w['id'] for w in command('list')['windows']}==self.baseline,'Baseline stash changed'
        finally:self.pointer.close()
