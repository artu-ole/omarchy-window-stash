#!/usr/bin/env python3
"""Normal close and scope checks against disposable windows and an isolated ledger."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from live import ROOT,h,command,wait
from desktop_test import desktop_test


@desktop_test('Confirmed close and save-prompt test')
def main():
    original=h.read('activewindow');workspace_before=h.read('activeworkspace')['id']
    baseline={w['id'] for w in command('list')['windows']}
    workspace=1000000+os.getpid()*10;monitor=next(m for m in h.read('monitors') if m['focused'])
    processes=[];addresses=[]
    assert all(w['id'] not in (workspace,workspace+1) for w in h.read('workspaces'))
    with tempfile.TemporaryDirectory(prefix='stash-close-live-') as directory:
        directory=Path(directory);config=directory/'shell.json'
        def settings(scope):config.write_text(json.dumps({'plugins':[{'id':'community.window-stash','scope':scope}]}))
        settings('workspace')
        code='''import sys
sys.path.insert(0,sys.argv.pop(1))
import stash
root=sys.argv.pop(1)
Base=stash.Stash
class Isolated(Base):
 def __init__(self,*args,**kwargs):
  kwargs.update(runtime=root+'/runtime',config=root+'/shell.json',state_home=root+'/state')
  super().__init__(*args,**kwargs)
stash.Stash=Isolated
raise SystemExit(stash.main())
'''
        prefix=[sys.executable,'-c',code,str(ROOT/'controller'),str(directory)]
        env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1')
        def run(*args):
            r=subprocess.run(prefix+list(map(str,args)),capture_output=True,text=True,env=env)
            data=json.loads(r.stdout);assert r.returncode==0,data;return data
        def begin(*args):return subprocess.Popen(prefix+list(map(str,args)),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=env)
        def spawn(mode='immediate',app='org.windowstash.CloseTest'):
            title='Stash close %s %s'%(os.getpid(),len(addresses))
            p=subprocess.Popen(['/usr/bin/python3',str(ROOT/'tests/close-window.py'),title,app,mode,'500'],
                env=dict(env,GDK_BACKEND='wayland'),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            processes.append(p)
            c=wait(lambda:next((c for c in h.read('clients') if c['title']==title),None),'Close fixture did not open')
            addresses.append(c['address']);return c['address'],title
        def park(address):return run('minimize','--address',address)['id']
        def close_args(*ids):return ['close',*ids,'--monitor',monitor['name'],'--workspace',str(workspace)]
        try:
            h.dispatch('focus',workspace=str(workspace))
            unstashed,_=spawn();a,_=spawn();b,_=spawn()
            ia=park(a);ib=park(b)
            r=run(*close_args(ia));assert r['ok'] and not h.client(a),r
            assert h.client(b) and h.client(unstashed),'Single close touched other windows'
            run(*close_args(ib));assert not h.client(b) and h.client(unstashed)
            print('PASS normal individual close and unstashed windows of the same app preserved',flush=True)

            a,title=spawn('delay');ident=park(a);started=time.monotonic();p=begin(*close_args(ident))
            wait(lambda:h.client(a) and h.client(a)['title']==title+' requested','Close request did not reach delayed window')
            state=json.loads((directory/'runtime/state.json').read_text())
            assert any(w['id']==ident for w in state['windows']) and h.client(a),'Pending record removed before actual closure'
            out,err=p.communicate(timeout=5);assert p.returncode==0,(out,err)
            assert not h.client(a) and time.monotonic()-started>=.4
            print('PASS delayed close keeps the record until real window destruction',flush=True)

            a,title=spawn('prompt');before=h.client(a)
            h.dispatch('window.float',window='address:'+a,action='on')
            h.dispatch('window.resize',window='address:'+a,x=610,y=390,relative=False)
            ident=park(a);r=run(*close_args(ident))
            assert h.client(a) and h.client(a)['workspace']['id']==workspace,r
            assert all(w['id']!=ident for w in run('list')['windows'])
            prompt=wait(lambda:next((c for c in h.read('clients') if c['title']==title+' save changes'),None),'Save prompt was not presented')
            assert prompt['workspace']['id']==workspace,'Save prompt remained hidden in the stash'
            h.dispatch('focus',window='address:'+prompt['address'])
            subprocess.run(['wtype','-k','Escape'],check=True)
            wait(lambda:not h.client(prompt['address']),'Cancel did not dismiss save prompt')
            assert h.client(a) and h.client(a)['workspace']['id']==workspace,'Cancel lost the surviving window'
            print('PASS surviving windows and save prompt restored, Cancel preserves usable application',flush=True)

            h.dispatch('focus',workspace=str(workspace));a,_=spawn();ia=park(a)
            h.dispatch('focus',workspace=str(workspace+1));b,_=spawn();ib=park(b)
            r=run('close-all','--monitor',monitor['name'],'--workspace',workspace)
            assert not h.client(a) and h.client(b) and h.client(unstashed),r
            assert {w['id'] for w in run('list')['windows']}=={ib}
            settings('global');r=run('close-all','--monitor',monitor['name'],'--workspace',workspace)
            assert not h.client(b) and h.client(unstashed) and not run('list')['windows'],r
            print('PASS workspace and global close-all against isolated ledger; real stash and unstashed app windows untouched',flush=True)
        finally:
            for p in processes:
                if p.poll() is None:p.terminate()
            for p in processes:
                try:p.wait(timeout=3)
                except subprocess.TimeoutExpired:p.kill();p.wait(timeout=3)
            wait(lambda:all(not h.client(a) for a in addresses),'Close fixtures did not clean up')
            h.dispatch('focus',workspace=str(workspace_before))
            if original.get('address') and h.client(original['address']):h.dispatch('focus',window='address:'+original['address'])
            assert {w['id'] for w in command('list')['windows']}==baseline,'Real stash changed during isolated close tests'


if __name__=='__main__':main()
