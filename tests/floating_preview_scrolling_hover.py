#!/usr/bin/env python3
"""Full-width scrolling windows keep stable floating previews during hover.

Uses two explicitly tiled GTK clients on an owned scrolling workspace. Their
original column dimensions must survive parking and Still-to-Live transitions;
the compositor may temporarily float parked sources, but restoration stays tiled.
Run in an isolated desktop with an empty stash. No existing layout rule changes.
"""
import argparse
import json
import os
import time

from desktop_test import desktop_test
from floating_preview_layouts import active_layout, close_owned, layout, ledger, restore_click, spawn_tiled
from floating_previews import away, card, drain, park, previews, ready
from hover_previews import current_focus
from live import command, configure, h, shell, wait
from live_compatibility import bridge_status
from native_session import NativeSession
from preview import PreviewBridge
from stash import SPECIAL


def close_ratio(actual, wanted):
    return abs(actual-wanted) <= max(.01, wanted*.01)


def sample(session, records):
    status = shell('status')
    surface = next(item for item in status['surfaces'] if item['screen'] == session.monitor['name'])
    value = surface['floatingPreviews']
    clients = {client['address']: client for client in h.read('clients')}
    return dict(time=time.monotonic(), workspace=surface['workspaceId'], settings=status['settings'],
                cards={item['recordId']: item for item in value['cards']}, overflow=value['overflow'],
                sources={record['id']: {field: client.get(field) for field in ('at', 'size', 'workspace', 'floating', 'pid', 'stableId')}
                         if (client := clients.get(record['address'])) else None for record in records},
                metadata={record['id']: ledger(record) for record in records},
                compatibility=status['previewCompatibility'])


def check(value, records, metadata, baseline=None, phase='baseline'):
    wanted = {record['id'] for record in records}
    diagnostic = dict(phase=phase, snapshot=value, baseline=baseline)
    assert set(value['cards']) == wanted, ('Hover changed visible preview identity/page', diagnostic)
    assert value['metadata'] == metadata, ('Hover rewrote original scrolling restoration metadata', diagnostic)
    assert not value['overflow']['enabled'] and value['overflow']['page'] == 0, ('Two normal-sized previews unexpectedly changed pages', diagnostic)
    for record in records:
        item = value['cards'][record['id']]
        image = item['image']
        source = value['sources'][record['id']]
        ratio = record['size'][0]/record['size'][1]
        assert not record['floating'] and not metadata[record['id']]['floating'], 'Original scrolling fixture was not tiled'
        assert source and source['workspace']['name'] == SPECIAL, ('Hover restored or lost a source', diagnostic)
        assert image['hasContent'] and image['sourceSize']['width'] > 1 and image['sourceSize']['height'] > 1, ('Hover lost its verified preview frame', diagnostic)
        assert close_ratio(item['imageRect']['width']/item['imageRect']['height'], ratio), ('Preview box changed the original full-width column aspect', diagnostic)
        assert close_ratio(image['sourceSize']['width']/image['sourceSize']['height'], ratio), ('Preview source changed the original full-width column aspect', diagnostic)
        assert all(abs(item['rect'][field]-item['imageRect'][field]) <= 1 for field in ('x', 'y', 'width', 'height')), ('Borderless preview acquired margins or letterboxing', diagnostic)
        if baseline:
            previous = baseline['cards'][record['id']]
            assert all(abs(item['rect'][field]-previous['rect'][field]) <= .75 for field in ('x', 'y', 'width', 'height')), ('Hover moved or resized a floating preview', diagnostic)
            assert all(abs(item['imageRect'][field]-previous['imageRect'][field]) <= .75 for field in ('x', 'y', 'width', 'height')), ('Hover moved or resized captured content', diagnostic)
    if baseline:
        assert all(value['overflow'][field] == baseline['overflow'][field] for field in ('page', 'pages', 'capacity')), ('Hover changed preview pagination', diagnostic)


def stable_baseline(session, records, metadata):
    for record in records:
        ready(session, record)
    away(session)
    previous = None
    stable_since = time.monotonic()
    deadline = stable_since+8
    while time.monotonic() < deadline:
        value = sample(session, records)
        check(value, records, metadata)
        geometry = {ident: item['rect'] for ident, item in value['cards'].items()}
        if previous != geometry:
            previous = geometry
            stable_since = time.monotonic()
        elif time.monotonic()-stable_since >= .35:
            return value
        time.sleep(.06)
    raise AssertionError(('Initial preview capture geometry did not settle before hover', value))


def hover_for_three_seconds(session, record, records, metadata, baseline, compatibility, phase):
    rect = baseline['cards'][record['id']]['imageRect']
    x, y = rect['x']+rect['width']/2, rect['y']+rect['height']/2
    focus = current_focus()
    session.move(x-1, y)
    session.move(x, y)
    def live_ready():
        value = sample(session, records)
        check(value, records, metadata, baseline, phase+' enter')
        item = value['cards'][record['id']]
        if not item['hovered'] or not item['image']['live']:
            return False
        if compatibility == 'enhanced':
            detail = value['compatibility']
            if detail.get('error'):
                raise AssertionError(('Enhanced hover support failed', detail))
            return set(detail['requestedIds']) == {record['id']} and detail['status'].get('state') == 'ready' \
                and set(detail['status'].get('ids', [])) == {record['id']}
        return True
    wait(live_ready, 'Pointer did not start its scoped live preview', timeout=150 if compatibility == 'enhanced' else 5)
    deadline = time.monotonic()+3.1
    samples = 0
    while time.monotonic() < deadline:
        value = sample(session, records)
        check(value, records, metadata, baseline, phase)
        assert value['cards'][record['id']]['hovered'] and value['cards'][record['id']]['image']['live'], ('Hovered preview lost its live state', phase, value)
        assert current_focus() == focus, 'Preview hover changed focus or workspace'
        samples += 1
        time.sleep(.075)
    assert samples >= 8, 'Hover regression did not sample the delayed transition repeatedly'
    away(session)
    wait(lambda: not card(session, record)['image']['live'], 'Leaving the preview kept its live stream active')
    if compatibility == 'enhanced':
        wait(lambda: not shell('status')['previewCompatibility']['requestedIds']
             and bridge_status().get('windows', 0) == 0, 'Leaving the last hovered card retained its rendering lease')
    check(sample(session, records), records, metadata, baseline, phase+' leave')


def column_width(address):
    return float(h.call('repl', 'local w=hl.get_window('+json.dumps('address:'+address)+'); return w.layout.column.width'))


def assert_column(record, client, references):
    members = [item for item in h.read('clients') if item['workspace']['id'] == record['origin']['id'] and not item['floating']]
    assert len(members) in (1, 2), ('Unexpected owned scrolling topology during restoration', members)
    # Hyprland 0.56 removes the inner gap when a full-width column is alone;
    # fullscreen_on_one_column can also force that sole column to fill the view.
    # Compare with measured fixtures in the same topology, keeping exact pixel
    # checks rather than accepting the gap as an arbitrary tolerance.
    expected = references['single'] if len(members) == 1 else references['pair'][record['address']]
    actual_fraction = column_width(record['address'])
    assert not client['floating'] and abs(client['size'][0]-expected) <= 1, \
        ('Restored scrolling window lost tiled state or its topology-specific full width',
         {'savedSize': record['size'], 'expectedWidth': expected, 'actual': client, 'references': references})
    assert abs(actual_fraction-1.0) <= .000001, \
        ('Restored full-width column lost its original logical width', actual_fraction, client, references)
    h.eval('''local w=hl.get_window(%s)
for _,other in pairs(hl.get_workspace_windows(w.workspace)) do
  if other.address~=w.address and not other.floating then
    assert(w.layout.column.index>other.layout.column.index,"Restored full-width window was not appended last")
  end
end''' % json.dumps('address:'+record['address']))


def case(session, compatibility, restash, always_live):
    for key, value in dict(presentation='previews', scope='workspace', grouping='window', animations='off',
                           hoverPreview='off', livePreviewCompatibility=compatibility, floatingPreviewUpdate='hover',
                           floatingPreviewSizing='free', floatingPreviewScale='100', floatingPreviewTitles='hidden',
                           floatingPreviewFrame='hidden', floatingPreviewLock='unlocked', floatingPlacement='free',
                           dragMotion='direct', iconOpacity=100, restoreDestination='current').items():
        configure(key, value)
    addresses = []
    references = {'pair': {}}
    for color in ('red', 'green'):
        address = spawn_tiled(session, color, session.workspace, 'org.windowstash.ScrollingHover')
        addresses.append(address)
        h.dispatch('focus', window='address:'+address)
        h.eval('hl.dispatch(hl.dsp.layout("colresize 1.0"))')
        wait(lambda: h.client(address)['size'][0] >= session.surface()['usableArea']['width']*.85,
             'Scrolling source did not become a full-width column')
        wait(lambda: abs(column_width(address)-1.0) <= .000001, 'Scrolling source did not apply its full logical column width')
        if len(addresses) == 1:
            references['single'] = h.client(address)['size'][0]
    for address in addresses:
        assert abs(column_width(address)-1.0) <= .000001, 'A neighboring source changed the original full logical column width'
        references['pair'][address] = h.client(address)['size'][0]
    first = park(session, addresses[0])
    ready(session, first)
    away(session)
    wait(lambda: not card(session, first)['image']['live'], 'First stash did not establish its idle snapshot')
    second = park(session, addresses[1])
    records = [first, second]
    metadata = {record['id']: ledger(record) for record in records}
    baseline = stable_baseline(session, records, metadata)
    for index in (0, 1, 0, 1):
        hover_for_three_seconds(session, records[index], records, metadata, baseline, compatibility,
                                compatibility+' hover '+str(index))
    if always_live:
        configure('floatingPreviewUpdate', 'live')
        wait(lambda: all(card(session, record)['image']['live'] for record in records), 'Always-live did not enable both persistent previews')
        deadline = time.monotonic()+3.1
        while time.monotonic() < deadline:
            check(sample(session, records), records, metadata, baseline, compatibility+' always-live')
            time.sleep(.075)
        configure('floatingPreviewUpdate', 'hover')
        away(session)
    if restash:
        restored = restore_click(session, first, session.workspace)
        assert_column(first, restored, references)
        records[0] = park(session, first['address'])
        metadata = {record['id']: ledger(record) for record in records}
        baseline = stable_baseline(session, records, metadata)
        hover_for_three_seconds(session, records[0], records, metadata, baseline, compatibility, compatibility+' restash')
    for record in records:
        restored = restore_click(session, record, session.workspace)
        assert_column(record, restored, references)
    close_owned(session, addresses)
    print('PASS '+compatibility+': two full-width scrolling previews keep original aspect, positions and pages through delayed hover/re-entry and restore tiled widths at the end', flush=True)


@desktop_test('Scrolling floating-preview hover geometry regression')
def main(compatibility, restash=False, always_live=False):
    assert not command('list')['windows'], 'Run scrolling-hover regression in an isolated desktop with an empty stash'
    original_workspace = h.read('activeworkspace')['id']
    original_layout = layout(original_workspace)
    rule_key = '__window_stash_scrolling_hover_'+str(os.getpid())
    with NativeSession() as session:
        # Loading the native bridge schedules a compositor configuration
        # reload, which discards runtime-only workspace rules. Warm it first.
        if compatibility in ('enhanced', 'both'):
            PreviewBridge(h).ensure()
        h.eval('_G.%s=hl.workspace_rule({workspace=%s,layout="scrolling",layout_opts={direction="right"}})' %
               (rule_key, json.dumps(str(session.workspace))))
        try:
            active_layout(session, session.workspace, 'scrolling')
            for mode in ('standard', 'enhanced') if compatibility == 'both' else (compatibility,):
                case(session, mode, restash, always_live)
            drain()
            assert not shell('status')['error'], shell('status')['error']
        finally:
            h.eval('if _G.%s then _G.%s:set_enabled(false);_G.%s=nil end' % (rule_key, rule_key, rule_key))
    drain()
    assert layout(original_workspace) == original_layout, 'Scrolling hover regression changed the original workspace layout'
    assert not command('list')['windows'], 'Scrolling hover cleanup left disposable stash records'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compatibility', choices=('standard', 'enhanced', 'both'), default='both')
    parser.add_argument('--restash', action='store_true')
    parser.add_argument('--always-live', action='store_true')
    options = parser.parse_args()
    main(options.compatibility, options.restash, options.always_live)
