#!/usr/bin/env python3
"""Pending Desktop fullscreen ACK ownership, cancellation and expiry in isolation."""
from pathlib import Path
import tempfile
import uuid

from desktop_test import desktop_test
from interactive_bridge import events, native_status, spawn_fixture
from interactive_fullscreen import modes, require_isolated
from live import command, configure, h, shell, wait
from bridge import BridgeManager
from native_session import NativeSession
from preview import API, PreviewBridge, preview_records
from stash import SPECIAL, lua


def pending(session, directory, ordinal, maximized=False):
    log=directory/(str(ordinal)+'.jsonl')
    address=spawn_fixture(session,log)
    if maximized:
        h.dispatch('window.fullscreen_state',window='address:'+address,internal=1,client=1,action='set')
        wait(lambda:modes(address)==(1,1),'Original GTK maximize did not settle')
    record=session.park(address)
    if maximized:assert (record['fullscreen'],record['fullscreenClient'])==(1,1)
    original=h.client(address)
    owner=uuid.uuid4().hex
    identity=preview_records([record],h.read('clients'),[record['id']])[0]
    payload='{'+','.join(key+'='+lua(value) for key,value in identity.items())+'}'
    rect=dict(x=session.monitor['x']+400,y=session.monitor['y']+300,width=500,height=350)
    box='{'+','.join(key+'='+lua(value) for key,value in rect.items())+'}'
    h.eval('local r,e='+API+'.interaction_update({owner='+lua(owner)+',window='+payload
           +',monitor='+lua(session.monitor['name'])+',rect='+box+',keyboard=false,fps=60,fullscreen="desktop"});assert(r,e);assert(r.active,r.reason)')
    x=rect['x']-session.monitor['x']+rect['width']*900/original['size'][0]
    y=rect['y']-session.monitor['y']+rect['height']*46/original['size'][1]
    session.move(x-1,y)
    session.pointer.click(*session.point(x,y))
    wait(lambda:events(log,'fullscreen-request'),'Owned GTK client did not request fullscreen')
    wait(lambda:(state:=native_status(owner)) and state['restoreRequested'] and state.get('desktopFullscreenPending'),
         'Native Desktop fullscreen request did not wait for handoff')
    wait(lambda:modes(address)==(0,2) and (values:=events(log,'fullscreen-state')) and values[-1]['active'],
         'Pending handoff did not acknowledge actual client fullscreen without layout fullscreen')
    assert h.client(address)['workspace']['name']==SPECIAL
    return owner,record,original,payload,log


def ordinary_restore(session,record,original,log):
    command('restore',record['id'],'--to','original')
    expected=(record['fullscreen'],record['fullscreenClient'])
    wait(lambda:h.client(record['address'])['workspace']['id']==record['origin']['id'] and modes(record['address'])==expected,
         'Manual restore retained the temporary Desktop fullscreen acknowledgment')
    wait(lambda:(values:=events(log,'fullscreen-state')) and not values[-1]['active'],
         'Manual restore did not tell the application that fullscreen ended')
    client=h.client(record['address'])
    assert client['floating'] and client['size']==original['size'] and client['at']==original['at'], \
        'Pending fullscreen changed ordinary restoration geometry'


@desktop_test('Pending Desktop fullscreen cancellation and expiry')
def main():
    require_isolated()
    PreviewBridge(h).ensure()
    manager=BridgeManager(h)
    assert manager.native()['fingerprint']==manager.build(manager.commit())['fingerprint']
    with tempfile.TemporaryDirectory(prefix='stash-desktop-handoff-') as temporary, NativeSession() as session:
        for key,value in dict(presentation='dock',scope='workspace',grouping='window',hoverPreview='off',
                              floatingPreviewInteraction='off',animations='off',restoreDestination='original').items():
            configure(key,value)
        directory=Path(temporary)
        owner,record,original,payload,log=pending(session,directory,0)
        saved=next(value for value in command('list')['windows'] if value['id']==record['id'])
        h.eval('local r,e='+API+'.clear_fullscreen('+payload+','+lua(uuid.uuid4().hex)+');assert(r==nil and e)')
        assert modes(record['address'])==(0,2) and native_status(owner)['restoreRequested']
        h.eval('local r,e='+API+'.clear_fullscreen('+payload+','+lua(owner)+');assert(r==false and e==nil)')
        assert modes(record['address'])==(0,2), 'Exact handoff owner lost its client acknowledgment'
        assert next(value for value in command('list')['windows'] if value['id']==record['id'])==saved
        ordinary_restore(session,record,original,log)
        assert not native_status(owner)['restoreRequested']
        print('PASS foreign owner rejected, exact owner preserves client-only ACK, ordinary restore cancels it and retains saved geometry',flush=True)

        owner,record,original,payload,log=pending(session,directory,3,maximized=True)
        ordinary_restore(session,record,original,log)
        assert modes(record['address'])==(1,1)
        print('PASS ordinary restore cancels pending video fullscreen while retaining the originally maximized window mode',flush=True)

        owner,record,original,payload,log=pending(session,directory,1)
        wait(lambda:not native_status(owner)['desktopFullscreenPending'] and modes(record['address'])==(0,0),
             'Abandoned Desktop fullscreen request did not expire to the original client state',timeout=15)
        assert h.client(record['address'])['workspace']['name']==SPECIAL
        ordinary_restore(session,record,original,log)
        print('PASS abandoned handoff expires without restoring/exposing its source; later ordinary restore remains normal',flush=True)

        owner,record,original,payload,log=pending(session,directory,2)
        try:
            h.eval('assert('+API+'.prepare_reload())')
            wait(lambda:manager.native()['reloadReady'],'Pending Desktop fullscreen ACK did not drain before reload',timeout=12)
            assert modes(record['address'])==(0,0) and not native_status(owner)['restoreRequested']
            assert h.client(record['address'])['workspace']['name']==SPECIAL
        finally:
            h.eval('assert('+API+'.cancel_reload())')
        ordinary_restore(session,record,original,log)
        print('PASS bridge reload cancellation acknowledges original client mode, keeps source private and never re-arms old fullscreen',flush=True)
        assert not shell('status')['error']
    assert not command('list')['windows']
    wait(lambda:manager.native()['pendingFullscreen']==0,'Desktop handoff cleanup retained pending fullscreen state')


if __name__=='__main__':main()
