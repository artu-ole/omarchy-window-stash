#!/usr/bin/env python3
"""Actual GTK input through fan/preview dismissal with both focus-follow policies."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

from desktop_test import desktop_test
from hover_previews import captured, hidden, hover, icon_ready, preview, spawn_color, window_key
from live import configure, h, shell, wait
from native_session import NativeSession
from stash import atomic_json, read_json


def fixture(title, log):
    import gi
    gi.require_version('Gtk', '4.0')
    from gi.repository import Gio, Gtk
    app = Gtk.Application(application_id='org.windowstash.OutsideInput', flags=Gio.ApplicationFlags.NON_UNIQUE)
    def activate(application):
        window = Gtk.ApplicationWindow(application=application, title=title)
        window.set_default_size(640, 420)
        window.set_decorated(False)
        button = Gtk.Button(label='Disposable click-through input target')
        state = dict(presses=0, releases=0, clicks=0, events=[])
        def event(kind):
            if kind in ('presses', 'releases', 'clicks'):
                state[kind] += 1
            state['events'].append(dict(kind=kind, active=window.is_active(), at=time.monotonic()))
            state['events'] = state['events'][-24:]
            atomic_json(Path(log), state)
        click = Gtk.GestureClick.new()
        click.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        click.connect('pressed', lambda *_args: event('presses'))
        click.connect('released', lambda *_args: event('releases'))
        click.connect('cancel', lambda *_args: event('cancel'))
        button.add_controller(click)
        def clicked(_button):
            event('clicks')
            window.set_title(title+' clicked '+str(state['clicks']))
        button.connect('clicked', clicked)
        window.connect('notify::is-active', lambda *_args: event('focus'))
        window.set_child(button)
        event('created')
        window.present()
    app.connect('activate', activate)
    app.run([str(Path(__file__))])


def spawn_target(session, log):
    h.dispatch('focus', workspace=str(session.workspace))
    title = 'Owned outside input '+str(os.getpid())+' '+str(len(session.addresses))
    process = subprocess.Popen(['/usr/bin/python3', str(Path(__file__).resolve()), '--fixture', title, str(log)],
                               env=dict(os.environ, GDK_BACKEND='wayland', PYTHONDONTWRITEBYTECODE='1'),
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    session.processes.append(process)
    client = wait(lambda: next((c for c in h.read('clients') if c['title'] == title), None), 'Input fixture did not map')
    address = client['address']
    session.addresses.append(address)
    area = session.surface()['usableArea']
    width, height = min(640, int(area['width'])-40), min(420, int(area['height'])-100)
    x, y = session.monitor['x']+area['x']+20, session.monitor['y']+area['y']+50
    h.dispatch('window.float', window='address:'+address, action='on')
    h.dispatch('window.resize', window='address:'+address, x=width, y=height, relative=False)
    h.dispatch('window.move', window='address:'+address, x=x, y=y, relative=False)
    wait(lambda: (c := h.client(address)) and c['workspace']['id'] == session.workspace
         and c['floating'] and c['at'] == [x,y] and c['size'] == [width,height], 'Input fixture geometry did not settle')
    return address


def inside(point, rect):
    return rect['x'] <= point[0] <= rect['x']+rect['width'] and rect['y'] <= point[1] <= rect['y']+rect['height']


def input_point(session, address):
    client = h.client(address)
    excluded = [session.dock()['panel'], preview(session)['rect'], session.surface()['shelf']]
    for fx,fy in ((.5,.5),(.25,.25),(.75,.25),(.25,.75),(.75,.75)):
        point = (client['at'][0]-session.monitor['x']+client['size'][0]*fx,
                 client['at'][1]-session.monitor['y']+client['size'][1]*fy)
        if not any(inside(point, rect) for rect in excluded if rect['width'] > 0 and rect['height'] > 0):
            return point
    raise AssertionError('No unobscured point is available in the owned GTK button')


@desktop_test('Outside-click delivery under both focus policies')
def main():
    before = json.loads(h.call('getoption', 'input:follow_mouse', '-j'))['int']
    failures = []
    try:
        with tempfile.TemporaryDirectory(prefix='stash-outside-input-') as directory, NativeSession() as session:
            for key,value in dict(presentation='floating',scope='workspace',grouping='window',hoverPreview='off',
                                  floatingPlacement='free',dragMotion='direct',floatingDirection='vertical',
                                  animations='full',animationSpeed='normal',sizePreset='100',
                                  previewDelay=0,previewHideDelay=1000).items():
                configure(key,value)
            one = session.park(spawn_color(session,'red'))
            two = session.park(spawn_color(session,'green'))
            area = session.surface()['usableArea']
            session.position('dock:floating', round(area['x']+area['width']-80), round(area['y']+80))
            for follow in (0,1):
                h.eval('hl.config({input={follow_mouse='+str(follow)+'}})')
                assert json.loads(h.call('getoption','input:follow_mouse','-j'))['int'] == follow
                for kind in ('fan','preview'):
                    log = Path(directory)/('%s-%s.json' % (follow,kind))
                    address = spawn_target(session,log)
                    try:
                        # Establish that this same button receives normal input
                        # before opening an overlay; compare one-click deltas.
                        baseline_point=input_point(session,address)
                        session.pointer.click(*session.point(*baseline_point))
                        wait(lambda:read_json(log,{}).get('clicks') == 1,'The unobscured GTK control click failed')
                        baseline_events=read_json(log,{})
                        assert baseline_events['presses']==1 and baseline_events['releases']==1,baseline_events
                        if kind == 'fan':
                            configure('hoverPreview','off');configure('presentation','floating')
                            session.click(session.dock()['handle'])
                            wait(lambda:session.dock()['expanded'] and not session.dock()['animating'],'Input fixture fan did not open')
                        else:
                            configure('presentation','dock');configure('hoverPreview','still')
                            hover(session,icon_ready(session,window_key(two)),two)
                            captured(session,two)
                        wait(lambda:shell('status')['clickObserverActive'],'Outside-click observer did not arm')
                        point = input_point(session,address)
                        before_events = read_json(log,{})
                        assert before_events.get('clicks') == 1,'Opening the overlay unexpectedly clicked its underlying app'
                        session.move(*point)
                        time.sleep(.1)
                        assert session.dock()['expanded'] if kind == 'fan' else preview(session)['opened'], 'Overlay dismissed before the outside press'
                        observed = shell('status')['clickObserverCount']
                        clicked_at = time.monotonic()
                        session.pointer.button(True)
                        wait(lambda:not session.dock()['expanded'] if kind == 'fan' else not preview(session)['opened'],
                             'Outside click did not dismiss '+kind,timeout=.6)
                        assert time.monotonic()-clicked_at < .6,'Outside dismissal used the leave timeout'
                        if follow==0 and kind=='fan':
                            wait(lambda:'272' in shell('status')['pressedPointerButtons'] and session.surface()['retainingPointerFocus'],
                                 'The outside press did not retain its layer focus until release')
                            time.sleep(3.3)
                            held=shell('status')
                            assert '272' in held['pressedPointerButtons'] and held['clickObserverActive'], 'A legitimate long button hold expired'
                            assert session.surface()['retainingPointerFocus'], 'Long press lost retained focus before release'
                            held_events=read_json(log,{})
                            assert held_events['presses']==2 and held_events['releases']==1 and held_events['clicks']==1,held_events
                        session.pointer.button(False)
                        wait(lambda:read_json(log,{}).get('clicks') == 2,'The outside click did not reach the owned GTK button',timeout=2)
                        events = read_json(log,{})
                        assert all(events[key]-baseline_events[key]==1 for key in ('presses','releases','clicks')),events
                        assert shell('status')['clickObserverCount'] > observed,'Compositor observer missed the outside press'
                        wait(lambda:not shell('status')['pressedPointerButtons'] and not session.surface()['retainingPointerFocus'],
                             'Pointer state or retained focus stayed active after physical release')
                        if follow==0 and kind=='fan':
                            session.click(session.dock()['handle'])
                            wait(lambda:session.dock()['expanded'] and not session.dock()['animating']
                                 and shell('status')['clickObserverActive'],'Escape recovery fan did not open')
                            empty=(area['x']+area['width']*.85,area['y']+area['height']*.85)
                            clients=[c for c in h.read('clients') if c.get('mapped')
                                     and (c['workspace']['id']==session.workspace or c.get('pinned'))]
                            assert all(not inside(empty,dict(x=c['at'][0]-session.monitor['x'],y=c['at'][1]-session.monitor['y'],
                                                            width=c['size'][0],height=c['size'][1])) for c in clients), 'Escape recovery requires unused desktop space'
                            session.move(*empty);session.pointer.button(True)
                            wait(lambda:not session.dock()['expanded'] and session.surface()['retainingPointerFocus']
                                 and session.surface()['nativeKeyboardActive'],'Recovery fixture did not leave a hidden retained keyboard layer')
                            session.keys('-k','Escape')
                            wait(lambda:not shell('status')['pressedPointerButtons'] and not session.surface()['retainingPointerFocus'],
                                 'Window-local Escape did not release the retained hidden layer')
                            session.pointer.button(False)
                            assert read_json(log,{})['clicks']==2,'Hidden-layer recovery touched the GTK app'
                            print('PASS long outside hold and hidden-layer WindowShortcut Escape recovery',flush=True)
                        print('PASS follow_mouse=%d %s: immediate dismissal and one GTK press/release/click' % (follow,kind),flush=True)
                    except AssertionError as error:
                        client = h.client(address)
                        detail = dict(follow_mouse=follow,kind=kind,error=str(error),events=read_json(log,{}),
                                      client={key:client.get(key) for key in ('at','size','workspace','floating','title')} if client else None,
                                      activeAddress=h.read('activewindow').get('address'),cursor=h.read('cursorpos'),
                                      dock=session.dock(),preview=preview(session))
                        print('FAIL outside input diagnostics:',json.dumps(detail),flush=True)
                        failures.append('%d/%s: %s' % (follow,kind,error))
                    finally:
                        session.pointer.button(False)
                        hidden(session)
                        session.keys('-k','Escape')
                        h.dispatch('window.close',window='address:'+address)
                        wait(lambda:not h.client(address),'Owned input fixture did not close')
            assert not failures,'Outside input failures: '+ '; '.join(failures)
    finally:
        h.eval('hl.config({input={follow_mouse='+str(before)+'}})')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture',nargs=2,metavar=('TITLE','LOG'))
    args = parser.parse_args()
    if args.fixture:
        fixture(*args.fixture)
    else:
        main()
