#!/usr/bin/env python3
"""Owned native interaction validation, display lifecycle and coordinate proof.

Use an explicitly disposable compositor with one output and an empty stash.
Only synthetic clients and outputs created here are changed. The optional real
session-lock check additionally requires --session-lock and a separate opt-in
environment variable; its finally path sends unlock on the owning connection.
"""
import argparse
import json
import os
from pathlib import Path
import re
import socket
import struct
import tempfile
import time
import uuid

from desktop_test import desktop_test
from interactive_bridge import begin, end, events, native_status, spawn_fixture
from live import command, configure, h, wait
from native_session import NativeSession
from pointer import Pointer
from preview import API, PreviewBridge, preview_records
from stash import SPECIAL, lua


def output(name):
    return next((monitor for monitor in h.read('monitors') if monitor['name'] == name),None)


def bounds(monitor):
    width,height = monitor['width'],monitor['height']
    if monitor.get('transform',0) % 2:width,height = height,width
    return dict(x=monitor['x'],y=monitor['y'],width=round(width/monitor['scale']),height=round(height/monitor['scale']))


def global_point(x,y):
    monitors = [bounds(monitor) for monitor in h.read('monitors')]
    left,top = min(m['x'] for m in monitors),min(m['y'] for m in monitors)
    right,bottom = max(m['x']+m['width'] for m in monitors),max(m['y']+m['height'] for m in monitors)
    return x-left,y-top,right-left,bottom-top


def click(session,rect,x=.75,y=.75):
    gx,gy = rect['x']+rect['width']*x,rect['y']+rect['height']*y
    session.pointer.move(*global_point(gx-1,gy))
    session.pointer.click(*global_point(gx,gy))


def create_output(session,position,mode='640x480@60',scale=1,transform=0):
    before = {monitor['name'] for monitor in h.read('monitors')}
    h.call('output','create','headless')
    monitor = wait(lambda:next((value for value in h.read('monitors') if value['name'] not in before),None),'Owned output did not appear')
    session.outputs.append(monitor['name'])
    h.eval('hl.monitor({output=%s,mode=%s,position=%s,scale=%s,transform=%s})' %
           (lua(monitor['name']),lua(mode),lua(position),scale,transform))
    dimensions = tuple(map(int, mode.split('@')[0].split('x')))
    coordinates = tuple(map(int, re.fullmatch(r'(-?\d+)x(-?\d+)', position).groups()))
    return wait(lambda:(value:=output(monitor['name'])) and value['scale'] == scale and value.get('transform',0) == transform
                and (value['width'],value['height']) == dimensions and (value['x'],value['y']) == coordinates and value,
                'Owned output did not apply its display geometry')


def native_request(owner_key,record,monitor_name,rect_value,**changes):
    identity = preview_records([record],h.read('clients'),[record['id']])[0]
    request = dict(owner=owner_key,window=identity,monitor=monitor_name,rect=rect_value,keyboard=False,fps=60)
    request.update(changes)
    def value(item):
        if isinstance(item,dict):return '{'+','.join(key+'='+value(member) for key,member in item.items())+'}'
        return lua(item)
    return API+'.interaction_update('+value(request)+')'


def rejected(owner_key,record,monitor_name,rect_value,**changes):
    h.eval('local result,err='+native_request(owner_key,record,monitor_name,rect_value,**changes)
           +';assert(not result and err,"Invalid native input request was accepted")')


def remains_ended(owner,record,monitor,rect):
    h.eval('local result,err='+native_request(owner,record,monitor,rect)
           +';assert(result,err);assert(not result.active,"Ended native input session was resurrected")')


class SessionLock(Pointer):
    """Small protocol client used only with three explicit isolation guards."""
    def __init__(self):
        assert os.environ.get('WINDOW_STASH_ISOLATED_TEST') == '1'
        assert os.environ.get('WINDOW_STASH_SESSION_LOCK_TEST') == '1'
        assert (Path.home()/'.window-stash-isolated').is_file()
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.settimeout(3)
        self.sock.connect(os.path.join(os.environ['XDG_RUNTIME_DIR'],os.environ['WAYLAND_DISPLAY']))
        self.buffer = b''
        self.locked = False
        self.requested = False
        self.finished = False
        self.send(1,1,self.uint(2));self.send(1,0,self.uint(3))
        manager = None
        while True:
            obj,opcode,payload = self.receive()
            if obj == 2 and opcode == 0:
                name,length = struct.unpack_from('II',payload)
                if payload[8:8+length-1].decode() == 'ext_session_lock_manager_v1':manager = name
            if obj == 3:break
        assert manager is not None,'Disposable compositor does not offer ext-session-lock'
        self.send(2,0,self.uint(manager)+self.string('ext_session_lock_manager_v1')+self.uint(1)+self.uint(4))

    def wait_lock(self):
        self.sock.settimeout(.5)
        deadline = time.monotonic()+15
        while time.monotonic() < deadline:
            try:obj,opcode,_ = self.receive()
            except socket.timeout:continue
            if obj == 5 and opcode == 0:self.locked = True;return
            if obj == 5 and opcode == 1:self.finished = True;raise RuntimeError('Disposable session lock was refused')
        raise RuntimeError('Disposable session lock did not acknowledge; restart the disposable compositor')

    def acquire(self):
        self.send(4,1,self.uint(5));self.requested = True
        self.wait_lock()

    def unlock(self):
        if self.requested and not self.locked and not self.finished:self.wait_lock()
        if self.locked:
            self.send(5,2)  # ext_session_lock_v1.unlock_and_destroy
            self.locked = False;self.requested = False
            self.sync()
        elif self.finished:
            self.send(5,0)
        self.send(4,0)
        self.close()


@desktop_test('Isolated interactive-preview lifecycle and display proof')
def main(session_lock=False):
    assert os.environ.get('WINDOW_STASH_ISOLATED_TEST') == '1' and (Path.home()/'.window-stash-isolated').is_file(), \
        'Run only in the explicit disposable compositor'
    assert len(h.read('monitors')) == 1 and not command('list')['windows'], 'Use one disposable output and an empty stash'
    PreviewBridge(h).ensure()
    with tempfile.TemporaryDirectory(prefix='stash-interaction-lifecycle-') as temporary, NativeSession() as session:
        primary = session.monitor
        first = bounds(primary)
        second = create_output(session,str(first['x']+first['width'])+'x0')
        third = create_output(session,str(first['x']+first['width']+640)+'x-100','1200x900@60',1.5,1)
        h.dispatch('focus',monitor=primary['name']);h.dispatch('focus',workspace=str(session.workspace))
        configure('presentation','dock');configure('hoverPreview','off')
        log = Path(temporary)/'source.jsonl'
        address = spawn_fixture(session,log)
        record = session.park(address)
        source = h.client(address)
        original = (source['workspace'],source['at'],source['size'])
        rect = dict(x=primary['x']+400,y=primary['y']+300,width=400,height=280)
        owner = uuid.uuid4().hex
        try:
            begin(owner,record,primary['name'],rect)
            identity = preview_records([record],h.read('clients'),[record['id']])[0]
            for changes in (dict(owner='invalid'),dict(owner=uuid.uuid4().hex),
                            dict(window=dict(identity,pid=identity['pid']+1)),
                            dict(window=dict(identity,stable_id='ffffffff')),
                            dict(rect=dict(rect,width=32769)),dict(rect=dict(rect,width=0))):
                begin(owner,record,primary['name'],rect)
                rejected(owner,record,primary['name'],rect,**changes)
                state = native_status(owner)
                assert state['active'] and state['owner'] == owner and state['id'] == record['id'], \
                    ('Invalid request changed the existing input owner',changes,state)
            print('PASS invalid owners, foreign owners, stale identities and invalid dimensions leave the valid active session untouched',flush=True)

            for rect in (rect,dict(rect,x=primary['x']+500,y=primary['y']+200,width=300,height=210)):
                begin(owner,record,primary['name'],rect)
                count = len(events(log,'press'))
                click(session,rect,.6,.7)
                press = wait(lambda:len(values:=events(log,'press')) > count and values[-1],'Renewed viewport did not forward its click')
                assert abs(press['x']-source['size'][0]*.6) <= 3 and abs(press['y']-source['size'][1]*.7) <= 3, \
                    ('Viewport renewal used stale source coordinates',press,rect)
            end(owner)
            print('PASS viewport position/size renewal keeps exact source-relative hit coordinates',flush=True)

            control,control_title = session.spawn(app='org.windowstash.InteractionLifecycleControl')
            h.dispatch('window.float',window='address:'+control,action='on')
            h.dispatch('window.resize',window='address:'+control,x=1100,y=700,relative=False)
            h.dispatch('window.move',window='address:'+control,x=primary['x']+50,y=primary['y']+50,relative=False)
            owner = uuid.uuid4().hex
            excluded = dict(x=rect['x']+100,y=rect['y']+100,width=40,height=30)
            begin(owner,record,primary['name'],rect,[excluded])
            count = len(events(log,'press'))
            click(session,excluded,.5,.5)
            wait(lambda:h.client(control)['title'] == control_title+' clicked','Excluded management click did not reach its visible owner')
            assert native_status(owner)['active'],'Clicking a management exclusion prematurely ended interaction'
            assert len(events(log,'press')) == count,'Management control click leaked to the hidden application'
            end(owner)
            print('PASS management exclusions preserve the native session and route their click to the visible control',flush=True)

            # Only owned temporary outputs are ever slept or removed.
            h.dispatch('focus',monitor=second['name']);h.dispatch('focus',workspace=str(session.workspace+1))
            rect_second = dict(x=second['x']+80,y=second['y']+100,width=400,height=280)
            owner = uuid.uuid4().hex
            begin(owner,record,second['name'],rect_second)
            try:
                h.dispatch('dpms',action='off',monitor=second['name'])
                wait(lambda:not native_status(owner)['active'],'DPMS off did not release input ownership')
            finally:
                h.dispatch('dpms',action='on',monitor=second['name'])
            wait(lambda:output(second['name']).get('dpmsStatus') is True,'Owned output did not wake')
            remains_ended(owner,record,second['name'],rect_second)
            assert not native_status(owner)['active'],'Waking an output resurrected its ended input session'
            print('PASS output sleep ends interaction and waking cannot resurrect an old owner',flush=True)

            h.dispatch('focus',monitor=third['name']);h.dispatch('focus',workspace=str(session.workspace+2))
            box = bounds(output(third['name']))
            rect_third = dict(x=box['x']+80,y=box['y']+140,width=400,height=280)
            owner = uuid.uuid4().hex
            begin(owner,record,third['name'],rect_third)
            count = len(events(log,'press'))
            click(session,rect_third,.7,.6)
            press = wait(lambda:len(values:=events(log,'press')) > count and values[-1],'Rotated/scaled third output did not forward input')
            assert abs(press['x']-source['size'][0]*.7) <= 3 and abs(press['y']-source['size'][1]*.6) <= 3, \
                ('Rotated/scaled global coordinates were mapped incorrectly',press,rect_third,box)
            assert next(monitor for monitor in h.read('monitors') if monitor['focused'])['name'] == third['name'], \
                'Input on the third monitor focused the source window monitor'
            assert (h.client(address)['workspace'],h.client(address)['at'],h.client(address)['size']) == original, \
                'Cross-monitor input changed the source geometry or private workspace'
            h.call('output','remove',third['name']);session.outputs.remove(third['name'])
            wait(lambda:not native_status(owner)['active'],'Removing the interaction monitor retained its input owner')
            print('PASS rotated/scaled third-monitor input preserves monitor focus and source geometry; output removal ends routing',flush=True)

            h.dispatch('focus',monitor=primary['name']);h.dispatch('focus',workspace=str(session.workspace))
            session.monitor = output(primary['name'])
            if session_lock:
                assert os.environ.get('WINDOW_STASH_SESSION_LOCK_TEST') == '1', 'Session-lock proof needs its separate environment opt-in'
                owner = uuid.uuid4().hex
                begin(owner,record,primary['name'],rect)
                lock = SessionLock()
                try:
                    lock.acquire()
                    wait(lambda:not native_status(owner)['active'],'Real session lock did not terminate input routing')
                    state = native_status(owner)
                    assert state['reason'] == 'locked',('Lock proof ended for a different reason',state)
                    assert state['heldButtons'] == 0,'Lock retained pressed application buttons'
                    count = len(events(log,'press'))
                    click(session,rect)
                    assert len(events(log,'press')) == count,'The locked session forwarded input to the hidden source'
                finally:
                    lock.unlock()
                remains_ended(owner,record,primary['name'],rect)
                assert not native_status(owner)['active'],'Unlocking resurrected the previous input session'
                print('PASS actual ext-session-lock terminates input and unlock does not re-arm the previous owner',flush=True)

            owner = uuid.uuid4().hex
            begin(owner,record,primary['name'],rect)
            command('restore',record['id'],'--to','original')
            wait(lambda:not native_status(owner)['active'],'Restoring the source retained native input ownership')
            assert h.client(address)['workspace']['name'] != SPECIAL,'Source restore did not leave the private workspace'
            print('PASS ordinary source restoration ends the exact native input lease',flush=True)
        finally:
            end(owner)
            session.monitor = output(primary['name']) or primary
            for name in list(session.outputs):
                current = output(name)
                if current and current.get('dpmsStatus') is False:h.dispatch('dpms',action='on',monitor=name)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session-lock',action='store_true',help='Also exercise actual session lock in the explicitly opted-in disposable profile')
    main(parser.parse_args().session_lock)
