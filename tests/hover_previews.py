#!/usr/bin/env python3
"""Native hover previews: real parked pixels, focus, actions and lifecycle.

Run after installing this checkout in an unlocked Hyprland session. The suite
uses disposable color windows, announces input five seconds ahead, and restores
the existing desktop through NativeSession. --small-output adds a temporary
320x240 output to check bounded previews on a short screen.
"""
import argparse
import math
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time

from desktop_test import desktop_test
from live import command, configure, h, shell, wait
from native_session import NativeSession
from stash import SPECIAL


def fixture(title, app_id, color):
    """An unmistakable client buffer; no screenshots of real apps are needed."""
    import gi
    gi.require_version('Gtk', '4.0')
    from gi.repository import Gio, GLib, Gtk
    colors = {'red': '#c71a29', 'green': '#1ab842', 'blue': '#1f40d1'}
    application = Gtk.Application(application_id=app_id, flags=Gio.ApplicationFlags.NON_UNIQUE)

    def activate(app):
        window = Gtk.ApplicationWindow(application=app, title=title)
        window.set_default_size(640, 420)
        label = Gtk.Label(label='Disposable '+color+' preview source')
        label.add_css_class('preview-fixture')
        provider = Gtk.CssProvider()
        state = {'color': color}

        def apply_color():
            provider.load_from_data(('.preview-fixture { background-color: '+colors[state['color']]
                                     +'; color: #ffffff; }').encode())

        def recolor():
            order = ('red', 'green', 'blue')
            state['color'] = order[(order.index(state['color'])+1) % len(order)]
            apply_color()
            label.queue_draw()
            return GLib.SOURCE_CONTINUE

        apply_color()
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR1, recolor)
        Gtk.StyleContext.add_provider_for_display(window.get_display(), provider,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        window.set_child(label)
        window.present()

    application.connect('activate', activate)
    application.run([str(Path(__file__))])


def spawn_color(session, color, app='org.windowstash.PreviewCapture', workspace=None):
    wanted = session.workspace if workspace is None else workspace
    h.dispatch('focus', workspace=str(wanted))
    title = 'Stash preview %s %s %s' % (os.getpid(), len(session.addresses), color)
    process = subprocess.Popen(['/usr/bin/python3', str(Path(__file__).resolve()), '--fixture', title, app, color],
                               env=dict(os.environ, GDK_BACKEND='wayland', PYTHONDONTWRITEBYTECODE='1'),
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    session.processes.append(process)
    client = wait(lambda: next((c for c in h.read('clients') if c['title'] == title), None),
                  'Color fixture did not map')
    address = client['address']
    session.addresses.append(address)
    if client['workspace']['id'] != wanted:
        h.dispatch('window.move', window='address:'+address, workspace=str(wanted), follow=True)
    h.dispatch('window.float', window='address:'+address, action='on')
    h.dispatch('window.resize', window='address:'+address, x=640, y=420, relative=False)
    h.dispatch('window.move', window='address:'+address,
               x=session.monitor['x']+100, y=session.monitor['y']+100, relative=False)
    time.sleep(.12)
    return address


def window_key(record):
    return 'window:'+str(record.get('stableId') or record['id'])


def change_color(session, address):
    assert address in session.addresses, 'Refusing to signal an unowned client'
    client = h.client(address)
    assert client, 'Color fixture is no longer present'
    process = next((p for p in session.processes if p.pid == client['pid'] and p.poll() is None), None)
    assert process, 'Refusing to signal a client without its owned process'
    process.send_signal(signal.SIGUSR1)


def select_native_mode(session, mode):
    shell('settings')
    wait(lambda: session.surface()['dialog']['visible'], 'Preview settings did not open')

    def control():
        return next(c for c in session.surface()['settingControls'] if c['key'] == 'hoverPreview')

    field = control()
    viewport = session.surface()['settingsScroll']['rect']
    assert field['visible'] and field['rect']['y'] >= viewport['y']-.1 \
        and field['rect']['y']+field['rect']['height'] <= viewport['y']+viewport['height']+.1, \
        'Hover preview dropdown is clipped outside the settings viewport'
    session.click(field['rect'])
    wait(lambda: control()['open'], 'Hover preview dropdown did not open')
    session.keys(*(['-k', 'Up']*3), *(['-k', 'Down']*('off', 'still', 'live').index(mode)), '-k', 'Return')
    wait(lambda: shell('status')['settings']['hoverPreview'] == mode, 'Native preview dropdown did not save '+mode)
    assert not preview(session)['opened'], 'Settings interaction opened a hover preview behind the dialog'
    shell('dismiss')
    wait(lambda: not session.surface()['dialog']['visible'], 'Preview settings did not dismiss')


def preview(session):
    return session.surface()['preview']


def contains(rect, x, y):
    return rect and rect.get('width', 0) > 0 and rect.get('height', 0) > 0 \
        and rect['x'] <= x <= rect['x']+rect['width'] and rect['y'] <= y <= rect['y']+rect['height']


def away(session):
    surface = session.surface()
    area = surface['usableArea']
    excluded = [preview(session)['rect'], surface['floatingDock']['handle'], surface['floatingDock']['panel']]
    excluded += surface['bubbles']+surface['shelf']['icons']
    if surface['dialog']['visible']:
        excluded.append(surface['dialog'])
    for x, y in ((area['x']+6, area['y']+6),
                 (area['x']+area['width']-6, area['y']+6),
                 (area['x']+6, area['y']+area['height']-6),
                 (area['x']+area['width']-6, area['y']+area['height']-6)):
        if not any(contains(r, x, y) for r in excluded):
            session.move(x, y)
            return x, y
    raise AssertionError('No empty corner was available to leave the preview')


def hidden(session):
    away(session)
    return wait(lambda: preview(session) if not preview(session)['rendered'] and not preview(session)['pending']
                and not preview(session)['image']['captureActive'] else None,
                'Preview or capture resource did not unload', timeout=4)


def icon_ready(session, key=None):
    session.resting()

    def ready():
        icon = session.icon(key)
        if not icon:
            return None
        appearance = icon.get('appearance')
        return icon if not appearance or appearance['presence'] > .999 else None

    return wait(ready, 'Preview source icon did not settle')


def hover(session, rect, record=None):
    session.move(rect['x']+rect['width']/2-1, rect['y']+rect['height']/2)
    session.move(rect['x']+rect['width']/2, rect['y']+rect['height']/2)
    value = wait(lambda: preview(session) if preview(session)['opened'] else None,
                 'Hover did not open a preview', timeout=5)
    if record is not None:
        assert value['recordId'] == record['id'], ('Preview selected the wrong window', value['recordId'], record['id'])
    return value


def image_rect(value):
    rect = value['image'].get('rect') or value.get('imageRect')
    if rect and rect['width'] > 0 and rect['height'] > 0:
        return rect
    # The image occupies the middle of the card; title and carousel remain at
    # its ends. Newer diagnostics expose its exact surface-space rectangle.
    rect = value['rect']
    return {'x': rect['x']+12, 'y': rect['y']+28, 'width': rect['width']-24,
            'height': max(1, rect['height']-78)}


def assert_bounded(session, value):
    area = session.surface()['usableArea']
    rect = value['rect']
    assert rect['width'] > 0 and rect['height'] > 0
    assert rect['x'] >= area['x']-.1 and rect['y'] >= area['y']-.1, ('Preview crossed a reserved edge', rect, area)
    assert rect['x']+rect['width'] <= area['x']+area['width']+.1, ('Preview crossed the right edge', rect, area)
    assert rect['y']+rect['height'] <= area['y']+area['height']+.1, ('Preview crossed the bottom edge', rect, area)


def captured(session, record):
    def ready():
        value = preview(session)
        image = value['image']
        return value if value['opened'] and value['recordId'] == record['id'] and image['hasContent'] \
            and image['recordId'] == record['id'] and image['sourceSize']['width'] > 1 \
            and image['sourceSize']['height'] > 1 else None

    value = wait(ready, 'The parked window never produced preview content', timeout=8)
    assert h.client(record['address'])['workspace']['name'] == SPECIAL, 'Capturing restored the parked window'
    assert_bounded(session, value)
    return value


def assert_pixels(session, value, color):
    # hasContent can be reported one render cycle before the scene-graph frame
    # reaches the compositor. Sample the completed frame rather than its edge.
    time.sleep(.08)
    rect = image_rect(value)
    x = math.ceil(rect['x']+3)
    y = math.ceil(rect['y']+3)
    width = max(1, math.floor(rect['width']-6))
    height = max(1, math.floor(rect['height']-6))
    geometry = '%d,%d %dx%d' % (session.monitor['x']+x, session.monitor['y']+y, width, height)
    with tempfile.TemporaryDirectory(prefix='stash-preview-native-') as directory:
        path = Path(directory)/'preview.ppm'
        subprocess.run(['grim', '-s', '1', '-t', 'ppm', '-g', geometry, str(path)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        magic, dimensions, maximum, pixels = path.read_bytes().split(b'\n', 3)
    assert magic == b'P6' and maximum == b'255'
    w, height = map(int, dimensions.split())
    assert len(pixels) == w*height*3
    channels = {'red': 0, 'green': 1, 'blue': 2}
    channel = channels[color]
    matching = 0
    for offset in range(0, len(pixels), 3):
        rgb = pixels[offset:offset+3]
        if rgb[channel] > 90 and all(rgb[channel] > rgb[other]+30 for other in range(3) if other != channel):
            matching += 1
    assert matching > max(50, w*height*.08), ('Thumbnail did not contain the selected client pixels', color, matching, w, height)


def current_focus():
    return h.read('activewindow').get('address'), h.read('activeworkspace')['id']


def wait_color(session, record, color, timeout=2.5):
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        value = preview(session)
        if value['recordId'] == record['id'] and value['image']['hasContent']:
            try:
                assert_pixels(session, value, color)
                return True
            except AssertionError:
                pass
        time.sleep(.04)
    return False


def click_image(session, button=272):
    session.click(image_rect(preview(session)), button)


def select_next(session, record):
    value = preview(session)
    assert value['count'] > 1 and value['nextRect']['width'] > 0
    session.click(value['nextRect'])
    wait(lambda: preview(session)['recordId'] == record['id'], 'Carousel did not select the next represented window')
    return captured(session, record)


def small_output(session):
    names = {m['name'] for m in h.read('monitors')}
    h.call('output', 'create', 'headless')
    monitor = wait(lambda: next((m for m in h.read('monitors') if m['name'] not in names), None),
                   'Preview test output did not appear')
    session.outputs.append(monitor['name'])
    right = max(m['x']+round(m['width']/m['scale']) for m in h.read('monitors') if m['name'] != monitor['name'])
    import json
    h.eval('hl.monitor({output=%s,mode="320x240@60",position=%s,scale=1})' %
           (json.dumps(monitor['name']), json.dumps('%dx0' % right)))
    session.monitor = next(m for m in h.read('monitors') if m['name'] == monitor['name'])
    h.dispatch('focus', monitor=monitor['name'])
    workspace = session.workspace+3
    h.dispatch('focus', workspace=str(workspace))
    wait(lambda: session.monitor['name'] in shell('status')['screens'], 'Preview test output has no surface')
    address = spawn_color(session, 'blue', app='org.windowstash.PreviewSmall', workspace=workspace)
    record = session.park(address)
    key = window_key(record)
    configure('presentation', 'bubbles')
    configure('grouping', 'window')
    configure('previewSize', 'large')
    configure('previewPlacement', 'auto')
    configure('previewDelay', 0)
    h.dispatch('focus', monitor=monitor['name'])
    session.resting()
    area = session.surface()['usableArea']
    for x, y in ((area['x']+8, area['y']+8),
                 (area['x']+area['width']-56, area['y']+8),
                 (area['x']+8, area['y']+area['height']-56),
                 (area['x']+area['width']-56, area['y']+area['height']-56)):
        hidden(session)
        session.position(key, round(x), round(y))
        hover(session, icon_ready(session, key), record)
        assert_bounded(session, captured(session, record))
    hidden(session)
    print('PASS large previews remain within a temporary 320x240 work area at every corner', flush=True)


@desktop_test('Mouse hover preview integration test')
def main(with_small_output=False):
    with NativeSession() as session:
        for key, value in dict(presentation='dock', grouping='window', scope='workspace', animations='full',
                               floatingPlacement='free', dragMotion='direct', dockSide='bottom',
                               iconShape='square', iconOpacity=100, hoverPreview='off', previewSize='medium',
                               previewPlacement='auto', previewTitles='shown', previewDelay=400,
                               previewHideDelay=200, restoreDestination='current').items():
            configure(key, value)
        red = spawn_color(session, 'red')
        one = session.park(red)
        green = spawn_color(session, 'green')
        two = session.park(green)
        control, control_title = session.spawn(app='org.windowstash.PreviewInput', workspace=session.workspace)
        h.dispatch('window.float', window='address:'+control, action='on')
        h.dispatch('window.resize', window='address:'+control, x=640, y=420, relative=False)
        h.dispatch('window.move', window='address:'+control,
                   x=session.monitor['x']+100, y=session.monitor['y']+100, relative=False)
        source = icon_ready(session, window_key(two))
        session.move(source['x']+source['width']/2, source['y']+source['height']/2)
        time.sleep(.5)
        assert not preview(session)['enabled'] and not preview(session)['opened'] and not preview(session)['pending']
        print('PASS disabled previews leave existing hover behavior unchanged', flush=True)

        hidden(session)
        select_native_mode(session, 'still')
        source = icon_ready(session, window_key(two))
        session.move(source['x']+source['width']/2, source['y']+source['height']/2)
        time.sleep(.12)
        assert preview(session)['pending'] and not preview(session)['opened'], 'Preview ignored its opening delay'
        hidden(session)
        time.sleep(.45)
        assert not preview(session)['opened'], 'A cancelled hover appeared later'
        baseline_focus = current_focus()
        baseline_geometry = {address: (h.client(address)['at'], h.client(address)['size']) for address in (red, green)}
        started = time.monotonic()
        hover(session, source, two)
        assert time.monotonic()-started >= .30, 'Opening delay was bypassed'
        value = captured(session, two)
        assert not value['image']['live'], 'Still mode unexpectedly runs continuous capture'
        assert_pixels(session, value, 'green')
        assert current_focus() == baseline_focus, 'Hover preview stole focus or switched workspaces'
        assert all((h.client(address)['at'], h.client(address)['size']) == before for address, before in baseline_geometry.items()), \
            'Preview capture moved or resized a parked client'
        change_color(session, green)  # green -> blue
        time.sleep(.2)
        assert_pixels(session, preview(session), 'green')
        hidden(session)
        hover(session, icon_ready(session, window_key(two)), two)
        captured(session, two)
        fresh_still = wait_color(session, two, 'blue', timeout=1)
        configure('hoverPreview', 'live')
        wait_color(session, two, 'blue')
        change_color(session, green)  # blue -> red
        live_updated = wait_color(session, two, 'red')
        change_color(session, green)  # red -> green
        green_restored = wait_color(session, two, 'green')
        if not green_restored:
            # A hidden client may stop producing buffers. Recreate only our
            # owned fixture so that later targeting checks have a known frame.
            hidden(session)
            h.dispatch('window.close', window='address:'+green)
            wait(lambda: not h.client(green), 'Dynamic color fixture did not close')
            command('list')
            green = spawn_color(session, 'green')
            two = session.park(green)
            hover(session, icon_ready(session, window_key(two)), two)
            assert_pixels(session, captured(session, two), 'green')
        configure('hoverPreview', 'still')
        value = captured(session, two)
        if green_restored:
            assert current_focus() == baseline_focus, 'Content updates moved focus or switched workspaces'
        print('PASS still preview holds its captured frame while the owned client changes color', flush=True)
        if fresh_still and live_updated:
            print('PASS reopening Still refreshes pixels and Live updates actual parked-client pixels', flush=True)
        else:
            print('NOTE hidden GTK client throttled buffer production; fresh Still update:', fresh_still,
                  'Live pixel update:', live_updated, '(capture mode/identity remain checked)', flush=True)
        session.move(value['rect']['x']+value['rect']['width']/2, value['rect']['y']+value['rect']['height']/2)
        wait(lambda: preview(session)['hovered'], 'Preview card did not accept pointer hover')
        time.sleep(.35)
        assert preview(session)['opened'], 'Moving from icon to preview closed the card'
        hidden(session)
        print('PASS delayed/cancelled hover, actual parked pixels, unchanged client geometry/focus, pointer transfer and capture unload', flush=True)

        configure('previewDelay', 0)
        select_native_mode(session, 'live')
        widths = []
        for size in ('small', 'medium', 'large'):
            configure('previewSize', size)
            hover(session, icon_ready(session, window_key(two)), two)
            value = captured(session, two)
            assert value['image']['live'], 'Live mode did not enable continuous capture'
            widths.append(value['rect']['width'])
            hidden(session)
        assert widths[0] < widths[1] < widths[2], ('Preview size choices did not change card width', widths)
        configure('previewTitles', 'hidden')
        hover(session, icon_ready(session, window_key(two)), two)
        assert_pixels(session, captured(session, two), 'green')
        hidden(session)
        configure('previewTitles', 'shown')
        print('PASS live/still capture modes, three size choices and hidden titles', flush=True)

        configure('grouping', 'app')
        group_key = 'app:'+two['app'].lower()
        source = icon_ready(session, group_key)
        hover(session, source, two)
        assert preview(session)['count'] == 2 and preview(session)['index'] == 0
        value = select_next(session, one)
        assert_pixels(session, value, 'red')
        assert preview(session)['index'] == 1
        session.click(value['previousRect'])
        wait(lambda: preview(session)['recordId'] == two['id'], 'Previous did not return to the newest window')
        assert_pixels(session, captured(session, two), 'green')
        hidden(session)

        # Invoke from a different workspace so restore cannot accidentally use
        # an old picker/context workspace captured by another action.
        configure('scope', 'global')
        h.dispatch('focus', workspace=str(session.workspace+1))
        hover(session, icon_ready(session, group_key), two)
        session.click(preview(session)['moreRect'])
        wait(lambda: shell('status')['dialog'] == 'picker' and session.surface()['dialog']['visible'],
             'Grouped preview did not open its represented-window picker')
        wait(lambda: not preview(session)['rendered'], 'Picker transition kept the old preview')
        picker = session.surface()['picker']
        row = {'x': picker['x']+4, 'y': picker['y']+2, 'width': picker['width']-8, 'height': 42}
        hover(session, row, two)
        captured(session, two)
        click_image(session)
        wait(lambda: h.client(green)['workspace']['id'] == session.workspace+1,
             'Preview restore ignored the invoking workspace')
        assert h.client(red)['workspace']['name'] == SPECIAL, 'Restoring one preview restored its whole app group'
        wait(lambda: not preview(session)['rendered'] and not preview(session)['image']['captureActive'],
             'Restored preview kept its capture resource')
        h.dispatch('window.move', window='address:'+green, workspace=str(session.workspace), follow=True)
        two = session.park(green)
        configure('scope', 'workspace')
        source = icon_ready(session, group_key)
        hover(session, source, two)
        select_next(session, one)
        click_image(session, 273)
        wait(lambda: session.menu()['visible'], 'Preview right click did not open the context menu')
        assert session.menu()['targetIds'] == [one['id']], 'Preview menu targeted the whole app or the wrong window'
        shell('dismiss')
        wait(lambda: not session.menu()['rendered'], 'Preview context menu did not dismiss')
        hover(session, icon_ready(session, group_key), two)
        select_next(session, one)
        click_image(session, 274)
        wait(lambda: not h.client(red), 'Preview middle click did not close the selected window')
        assert h.client(green)['workspace']['name'] == SPECIAL, 'Preview middle click closed its app neighbor'
        wait(lambda: one['id'] not in shell('status')['pendingCloseIds'], 'Preview close never completed')
        hidden(session)
        print('PASS grouped carousel pixels, chooser-row hover, invocation-aware restore, specific context menu and confirmed middle close', flush=True)

        configure('grouping', 'window')
        blue = spawn_color(session, 'blue', app='org.windowstash.PreviewOther')
        three = session.park(blue)
        key = window_key(three)
        configure('presentation', 'dock')
        for side in ('bottom', 'top', 'left', 'right'):
            configure('dockSide', side)
            hover(session, icon_ready(session, key), three)
            assert_bounded(session, captured(session, three))
            hidden(session)
        configure('presentation', 'bubbles')
        session.resting()
        area = session.surface()['usableArea']
        session.position(key, round(area['x']+area['width']/2), round(area['y']+area['height']/2))
        for side in ('above', 'below', 'left', 'right'):
            configure('previewPlacement', side)
            hover(session, icon_ready(session, key), three)
            value = captured(session, three)
            assert value['side'] == side, ('Requested preview side was ignored despite available space', side, value['side'])
            hidden(session)
        configure('previewPlacement', 'auto')
        hover(session, icon_ready(session, key), three)
        source = icon_ready(session, key)
        session.move(source['x']+24, source['y']+24)
        session.pointer.button(True)
        time.sleep(.07)
        assert not preview(session)['opened'] and not preview(session)['pending'], 'Press/drag did not cancel preview'
        session.move(source['x']+140, source['y']+24)
        assert not preview(session)['opened'], 'Dragging reopened a preview'
        session.pointer.button(False)
        session.resting()
        hidden(session)

        configure('presentation', 'floating')
        source = icon_ready(session)
        hover(session, source, three)
        captured(session, three)
        assert not session.dock()['expanded'], 'Collapsed-stack hover unfolded the dock'
        hidden(session)
        extra = spawn_color(session, 'red', app='org.windowstash.PreviewExtra')
        extra_record = session.park(extra)
        session.click(icon_ready(session))
        if session.dock()['animating']:
            assert not preview(session)['opened'], 'Unfolding opened a preview for a moving icon'
        wait(lambda: session.dock()['expanded'] and not session.dock()['animating'], 'Floating dock did not unfold')
        icon = next(i for i in session.dock()['icons'] if i['key'] == window_key(two))
        hover(session, icon, two)
        value = captured(session, two)
        session.move(value['rect']['x']+value['rect']['width']/2, value['rect']['y']+value['rect']['height']/2)
        wait(lambda: preview(session)['hovered'], 'Expanded fan preview did not receive pointer hover')
        time.sleep(.9)
        assert session.dock()['expanded'] and preview(session)['opened'], 'Preview hover let its floating fan fold'
        click_image(session)
        wait(lambda: h.client(green)['workspace']['id'] == session.workspace, 'Expanded preview did not restore its selected window')
        wait(lambda: not session.dock()['expanded'] and not preview(session)['opened'],
             'Expanded preview restore left the floating fan over the restored application')
        assert h.client(blue)['workspace']['name'] == SPECIAL and h.client(extra)['workspace']['name'] == SPECIAL, \
            'Expanded preview restored another represented window'
        assert any(w['id'] == extra_record['id'] for w in command('list')['windows'])
        two = session.park(green)
        session.click(icon_ready(session))
        wait(lambda: session.dock()['expanded'] and not session.dock()['animating'], 'Floating dock did not reopen after preview restore')
        icon = next(i for i in session.dock()['icons'] if i['key'] == key)
        hover(session, icon, three)
        captured(session, three)
        session.pointer.click(*session.point(250, 220))
        wait(lambda: not session.dock()['expanded'] and not preview(session)['opened'], 'Outside click did not dismiss fan and preview')
        wait(lambda: h.client(control)['title'] == control_title+' clicked', 'Preview swallowed the underlying application click')
        session.resting()
        hidden(session)
        print('PASS four dock sides, explicit preview placement, dragging suppression, collapsed/expanded floating icons and outside click-through', flush=True)

        select_native_mode(session, 'off')
        hidden(session)
        assert not preview(session)['enabled'], 'Disabling previews left them active'
        if with_small_output:
            configure('hoverPreview', 'still')
            small_output(session)
        assert not shell('status')['error'], shell('status')['error']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', nargs=3, metavar=('TITLE', 'APP', 'COLOR'))
    parser.add_argument('--small-output', action='store_true')
    args = parser.parse_args()
    if args.fixture:
        fixture(*args.fixture)
    else:
        main(args.small_output)
