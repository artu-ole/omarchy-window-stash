#!/usr/bin/env python3
"""Verify dock overflow on a small disposable virtual output."""
import json
import subprocess
import time
import live
from live import h,shell,command,configure,spawn,stash,wait,Pointer

old=h.read('activewindow');old_ws=h.read('activeworkspace')['id']
monitors=h.read('monitors');settings=command('list')['settings'];virtual=None;pointer=None
try:
    assert not command('list')['windows']
    before={m['name'] for m in monitors}
    h.call('output','create','headless')
    m=wait(lambda:next((m for m in h.read('monitors') if m['name'] not in before),None),'Virtual screen missing')
    virtual=m['name']
    end=max(m['x']+round(m['width']/m['scale']) for m in monitors)
    h.eval('hl.monitor({output=%s,mode="640x480@60",position=%s,scale=1})'%(json.dumps(virtual),json.dumps('%dx0'%end)))
    configure('scope','global');configure('grouping','window');configure('presentation','dock')
    for index in range(12):
        address=spawn('Stash overflow %02d'%index)
        stash(address)
    def get_surface():return next(s for s in shell('status')['surfaces'] if s['screen']==virtual)
    s=wait(lambda:get_surface() if get_surface()['groups']==12 else None,'All dock entries did not appear')
    assert s['shelf']['contentWidth']>s['shelf']['viewportWidth'],s
    assert s['shelf']['width']<=s['width']-32,s
    pointer=Pointer()
    all_monitors=h.read('monitors')
    left=min(m['x'] for m in all_monitors);top=min(m['y'] for m in all_monitors)
    right=max(m['x']+round(m['width']/m['scale']) for m in all_monitors)
    bottom=max(m['y']+round(m['height']/m['scale']) for m in all_monitors)
    m=next(m for m in all_monitors if m['name']==virtual)
    x=m['x']-left+s['shelf']['x']+s['shelf']['width']-90
    y=m['y']-top+s['shelf']['y']+32
    pointer.move(x,y,right-left,bottom-top);pointer.button(True)
    for step in range(1,9):
        pointer.move(x-24*step,y,right-left,bottom-top);time.sleep(.025)
    pointer.button(False)
    wait(lambda:get_surface()['shelf']['contentX']>20,'Overflow shelf could not be scrolled')
    assert len(command('list')['windows'])==12,'Dragging the dock restored an unintended window'
    print('PASS constrained dock width and real horizontal overflow scrolling',flush=True)
finally:
    if pointer:pointer.close()
    for address in live.addresses:
        if h.client(address):h.dispatch('window.close',window='address:'+address)
    for p in live.processes:
        if p.poll() is None:p.terminate()
    command('list')
    if virtual:h.call('output','remove',virtual)
    for key,value in settings.items():configure(key,value)
    shell('dismiss');h.dispatch('focus',workspace=str(old_ws))
    if old and h.client(old['address']):h.dispatch('focus',window='address:'+old['address'])
