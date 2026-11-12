#!/usr/bin/env python3
"""Tiled and scrolling windows in resizable persistent previews.

Run on a disposable desktop with an empty stash. Rules target only the reserved
test workspaces and are disabled in finally; no global layout or existing window
rules are changed. NativeSession preserves preferences, positions and focus.
"""
import argparse
import json
import os

from desktop_test import desktop_test
from floating_previews import bounded, card, drain, drag, park, previews, ready, seed
from hover_previews import spawn_color
from live import command, configure, h, shell, wait
from live_compatibility import ready as enhanced_ready
from native_session import NativeSession
from preview import PreviewBridge
from stash import SPECIAL


RESTORATION_FIELDS = ('size', 'relativePosition', 'floating', 'origin', 'monitor', 'monitorName', 'slot',
                      'pinned', 'fullscreen', 'fullscreenClient', 'scrollingWidth')


def layout(workspace):
    value = h.call('repl', 'local ws=hl.get_workspace('+json.dumps(str(workspace))+'); return ws and ws.tiled_layout or ""')
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, str) else value
    except ValueError:
        return value


def active_layout(session, workspace, expected):
    def matches():
        return h.read('activeworkspace')['id'] == workspace and session.surface()['workspaceId'] == workspace \
            and layout(workspace) == expected
    try:
        wait(matches, 'Reserved workspace did not become active with layout '+expected, timeout=12)
    except AssertionError:
        print('Layout activation diagnostics:', {'wantedWorkspace': workspace, 'wantedLayout': expected,
              'activeWorkspace': h.read('activeworkspace'), 'workspaces': h.read('workspaces'),
              'surfaceWorkspace': session.surface()['workspaceId'], 'actualLayout': layout(workspace)}, flush=True)
        raise


def ledger(record):
    value = next(item for item in command('list')['windows'] if item['id'] == record['id'])
    return {name: value.get(name) for name in RESTORATION_FIELDS}


def source_state(record):
    value = h.client(record['address'])
    assert value, 'Tiled preview source disappeared'
    return {name: value[name] for name in ('at', 'size', 'workspace', 'floating', 'pid', 'stableId')}


def ratio_matches(value):
    image = value['image']
    source = image['sourceSize']
    if not image['hasContent'] or source['width'] <= 1 or source['height'] <= 1:
        return False
    rect = value['imageRect']
    wanted = source['width']/source['height']
    return rect['width'] > 0 and rect['height'] > 0 \
        and abs(rect['width']/rect['height']-wanted) <= max(.01, wanted*.01)


def assert_borderless_fit(value):
    image, outer = value['imageRect'], value['rect']
    assert not value['titleVisible'] and not value['frameVisible'], 'Tiled miniature has unsolicited chrome'
    assert ratio_matches(value), ('Tiled preview box does not fit the actual captured frame', value)
    assert all(abs(image[name]-outer[name]) <= 1 for name in ('x', 'y', 'width', 'height')), \
        ('Borderless tiled card leaves margins or mismatched letterboxing around its image', image, outer)


def captured(session, record):
    wait(lambda: enhanced_ready(record), 'Tiled preview did not acquire Enhanced rendering support', timeout=150)
    def fits():
        value = card(session, record)
        if not value or value['held'] or value['resizing'] or not ratio_matches(value):
            return None
        source = value['image']['sourceSize']
        client = h.client(record['address'])
        if not client or not client['floating'] or client['workspace']['name'] != SPECIAL:
            return None
        if any(abs(actual-saved) > 1 for actual, saved in zip(client['size'], record['size'])):
            return None
        actual = client['size'][0]/client['size'][1]
        return value if abs(source['width']/source['height']-actual) <= max(.01, actual*.01) else None
    try:
        value = wait(fits, 'Tiled preview did not retain its original dimensions while parked floating', timeout=12)
    except AssertionError:
        print('Tiled capture diagnostics:', {'record': record['id'], 'savedSize': record['size'],
              'client': source_state(record), 'card': card(session, record), 'preview': previews(session)}, flush=True)
        raise
    assert_borderless_fit(value)
    bounded(session, value)
    assert not ledger(record)['floating'], 'Floating parking changed the saved tiled restoration state'
    return value


def spawn_tiled(session, color, workspace, app):
    address = spawn_color(session, color, app=app, workspace=workspace)
    h.dispatch('window.float', window='address:'+address, action='off')
    wait(lambda: not h.client(address)['floating'] and h.client(address)['workspace']['id'] == workspace,
         'Fixture did not become a tiled window on its reserved workspace')
    return address


def resize_only_miniature(session, record):
    seed(session, record, x=90, y=100, width=240)
    value = captured(session, record)
    before_source = source_state(record)
    before_ledger = ledger(record)
    drag(session, value['resizeRect'], 80, 40)
    resized = wait(lambda: (item := card(session, record)) and not item['resizing']
                   and item['width'] > value['width']+25 and item,
                   'Tiled miniature did not resize through its corner handle')
    drain()
    captured(session, record)
    assert source_state(record) == before_source, ('Resizing a tiled miniature changed the real window', before_source, source_state(record))
    assert ledger(record) == before_ledger, ('Resizing a tiled miniature changed saved restoration metadata', before_ledger, ledger(record))
    return resized


def restore_click(session, record, workspace, rect=None):
    session.click(rect or ready(session, record)['imageRect'])
    wait(lambda: (client := h.client(record['address'])) and client['workspace']['id'] == workspace,
         'Tiled thumbnail did not restore onto its invoking workspace')
    drain()
    wait(lambda: record['id'] not in {item['id'] for item in command('list')['windows']}
         and record['id'] not in shell('status')['windowIds'], 'Tiled restore did not finish its ledger/UI transaction')
    client = h.client(record['address'])
    assert not client['floating'], 'A tiled window restored as a floating miniature'
    return client


def close_owned(session, addresses):
    drain()
    for address in addresses:
        assert address in session.addresses, 'Refusing to close an unowned layout fixture'
        if h.client(address):
            h.dispatch('window.close', window='address:'+address)
    wait(lambda: all(not h.client(address) for address in addresses), 'Layout fixtures did not close')
    drain()


def dwindle(session):
    first_address = spawn_tiled(session, 'red', session.workspace, 'org.windowstash.FloatingTiled')
    second_address = spawn_tiled(session, 'green', session.workspace, 'org.windowstash.FloatingTiled')
    first = park(session, first_address)
    assert not first['floating'], 'Dwindle fixture was saved as floating'
    initial = captured(session, first)
    initial_ratio = initial['image']['sourceSize']['width']/initial['image']['sourceSize']['height']
    saved_ratio = first['size'][0]/first['size'][1]
    assert abs(initial_ratio-saved_ratio) <= max(.01, saved_ratio*.01), \
        ('Parking a tiled window changed its original preview aspect', first['size'], initial['image']['sourceSize'])
    resized = resize_only_miniature(session, first)
    first_source = source_state(first)
    first_metadata = ledger(first)
    second = park(session, second_address)
    first_after, second_after = captured(session, first), captured(session, second)
    changed_ratio = first_after['image']['sourceSize']['width']/first_after['image']['sourceSize']['height']
    assert abs(changed_ratio-initial_ratio) <= max(.01, initial_ratio*.01), \
        ('Stashing another window reshaped an existing preview source', initial_ratio, changed_ratio)
    assert all(abs(first_after[name]-resized[name]) <= 1 for name in ('width', 'height')), \
        ('Stashing another window resized the existing miniature', resized['rect'], first_after['rect'])
    assert source_state(first) == first_source, 'A new stashed neighbor moved or resized the parked source'
    assert ledger(first) == first_metadata, 'Floating parking rewrote original restoration geometry'
    print('PASS tiled sources park floating at their saved dimensions; adding another stash preserves existing source and miniature proportions', flush=True)

    destination = session.workspace+1
    configure('scope', 'global')
    anchor = spawn_tiled(session, 'blue', destination, 'org.windowstash.FloatingTiledAnchor')
    configure('grouping', 'app')
    group = wait(lambda: (value := card(session)) and value['groupCount'] == 2 and value,
                 'Tiled sources did not form a preview app group')
    session.click(group['imageRect'])
    wait(lambda: previews(session)['expanded'] and len(previews(session)['tiles']) == 2
         and all(ratio_matches(tile) for tile in previews(session)['tiles']),
         'Grouped tiled thumbnails did not each fit their captured surface')
    tiles = previews(session)['tiles']
    for tile in tiles:
        assert_borderless_fit(tile)
    target = next(tile for tile in tiles if tile['recordId'] == first['id'])
    restored = restore_click(session, first, destination, target['imageRect'])
    assert h.client(second_address)['workspace']['name'] == SPECIAL, 'Exact tiled restore restored a neighboring group member'
    members = {client['address'] for client in h.read('clients') if client['workspace']['id'] == destination and not client['floating']}
    assert {anchor, first_address} <= members, ('Restored tile did not join the destination layout', members, restored)
    configure('grouping', 'window')
    captured(session, second)
    restore_click(session, second, destination)
    assert not any(item['id'] in (first['id'], second['id']) for item in command('list')['windows']), 'Dwindle restore retained an owned record'
    close_owned(session, (first_address, second_address, anchor))
    configure('scope', 'workspace')
    print('PASS grouped tiled previews preserve aspect and restore exactly one tiled window into the invoking layout', flush=True)


def scrolling(session):
    workspace = session.workspace+2
    addresses = [spawn_tiled(session, color, workspace, 'org.windowstash.FloatingScrolling')
                 for color in ('red', 'green', 'blue')]
    address = addresses[0]
    for fraction in (.31, .78):
        h.dispatch('focus', window='address:'+address)
        h.eval('hl.dispatch(hl.dsp.layout('+json.dumps('colresize '+str(fraction))+'))')
        width = h.client(address)['size'][0]
        record = park(session, address)
        assert not record['floating'] and record['size'][0] == width, 'Scrolling fixture did not save its original column width'
        captured(session, record)
        resize_only_miniature(session, record)
        saved = ledger(record)
        assert saved['size'][0] == width, 'Preview sizing replaced the scrolling restoration width'
        restored = restore_click(session, record, workspace)
        assert abs(restored['size'][0]-width) <= 1, ('Scrolling restore used preview width instead of original column width', width, restored['size'])
        h.eval('''local w=hl.get_window(%s)
for _,other in pairs(hl.get_workspace_windows(w.workspace)) do
  if other.address~=w.address and not other.floating then
    assert(w.layout.column.index>other.layout.column.index, "Restored preview tile is not the last scrolling column")
  end
end''' % json.dumps('address:'+address))
    close_owned(session, addresses)
    print('PASS narrow/wide scrolling columns retain original width and append at the end after direct miniature resizing', flush=True)


@desktop_test('Floating previews in dwindle and scrolling layouts')
def main(scrolling_only=False):
    assert not command('list')['windows'], 'Run tiled preview layout tests in an isolated desktop with an empty stash'
    original_workspace = h.read('activeworkspace')['id']
    original_layout = layout(original_workspace)
    rule_key = '__window_stash_preview_layouts_'+str(os.getpid())
    with NativeSession() as session:
        # A first native-plugin load reloads compositor configuration. Finish
        # that before installing runtime-only rules for the owned workspaces.
        PreviewBridge(h).ensure()
        h.eval('_G.'+rule_key+'={}')
        try:
            for workspace, mode in ((session.workspace, 'dwindle'), (session.workspace+1, 'dwindle'), (session.workspace+2, 'scrolling')):
                h.eval('table.insert(_G.%s,hl.workspace_rule({workspace=%s,layout=%s,layout_opts={direction="right"}}))' %
                       (rule_key, json.dumps(str(workspace)), json.dumps(mode)))
            for key, value in dict(presentation='previews', scope='workspace', grouping='window', animations='off',
                                   hoverPreview='off', livePreviewCompatibility='enhanced', floatingPreviewUpdate='live',
                                   floatingPreviewSizing='free', floatingPreviewScale='100', floatingPreviewTitles='hidden',
                                   floatingPreviewFrame='hidden', floatingPreviewLock='unlocked', floatingPlacement='free',
                                   dragMotion='direct', iconOpacity=100, restoreDestination='current').items():
                configure(key, value)
            active_layout(session, session.workspace, 'dwindle')
            if not scrolling_only:
                dwindle(session)
            h.dispatch('focus', workspace=str(session.workspace+2))
            active_layout(session, session.workspace+2, 'scrolling')
            scrolling(session)
            drain()
            assert not shell('status')['error'], shell('status')['error']
        finally:
            h.eval('if _G.%s then for _,rule in ipairs(_G.%s) do rule:set_enabled(false) end; _G.%s=nil end' %
                   (rule_key, rule_key, rule_key))
    drain()
    assert layout(original_workspace) == original_layout, 'Layout tests changed the original workspace layout'
    assert not command('list')['windows'], 'Tiled preview cleanup left owned stash records'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scrolling-only', action='store_true', help='Run only the scrolling-width regression')
    main(parser.parse_args().scrolling_only)
