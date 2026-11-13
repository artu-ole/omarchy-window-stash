#!/usr/bin/env python3
"""Preview -> icon -> preview -> full-window acceptance in a disposable desktop.

The main path uses real configured managed keyboard bindings, not direct QML
calls. All clients, outputs, settings and geometry belong to the preserving test.
--restart-shell additionally verifies the persisted icon stage and positions.
--scrolling adds narrow/wide tiling-column restoration after both stages.
"""
import argparse
from collections import Counter
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

from desktop_test import desktop_test
from floating_previews import card, drain, drag, key, park, preview_owner, previews, ready, seed, touch
from floating_preview_aspect import shaped, shell_ready, side, spawn as responsive
from floating_preview_layouts import active_layout, ledger
from interactive_bridge import events, native_status, spawn_fixture
from interactive_fullscreen import modes
from interactive_groups import expand, ready_tile
from interactive_keyboard import key_count
from interactive_previews import active, show_controls, source_click, stopped
from live import ROOT, command, configure, h, shell, wait
from native_session import NativeSession
from bridge import BridgeManager
from stash import SPECIAL


SHORTCUT_KEYS = ('minimizeShortcut', 'restoreLastShortcut', 'restoreOldestShortcut')


def current(record):
    return next((item for item in command('list')['windows'] if item['id'] == record['id']), None)


def pause_captures(session):
    shell('dismiss')
    wait(stopped, 'Cleanup retained preview interaction')
    configure('presentation', 'dock')
    drain()
    wait(lambda: not any(item.get('image', {}).get('captureActive') for surface in shell('status')['surfaces']
                         for part in ('cards', 'tiles') for item in surface['floatingPreviews'][part])
         and BridgeManager(h).native().get('owners', 0) == 0,
         'Owned captures did not stop before fixture termination')


def folded(session):
    return previews(session).get('folded', {})


def icon(session, record):
    return next((item for item in folded(session).get('icons', [])
                 if record['id'] in item['recordIds'] and not item.get('retiring')), None)


def folded_ready(session, record):
    def settled():
        saved = current(record)
        state = folded(session)
        value = icon(session, record)
        return saved and saved.get('previewFolded') is True and state.get('sizingReady', True) and value \
            and not value.get('held') and not value.get('moving') and value
    value = wait(settled, 'The exact preview did not fold into a resting icon', timeout=12)
    session.touched.setdefault(preview_owner(session), set()).add(value['key'])
    return value


def source_geometry(record):
    value = h.client(record['address'])
    assert value, 'Owned source disappeared'
    return {field: copy.deepcopy(value[field]) for field in ('workspace', 'at', 'size', 'floating', 'fullscreen', 'fullscreenClient')}


def immutable(record):
    saved = current(record)
    assert saved, 'Owned stash record disappeared'
    return dict(ledger(record), **{field: saved.get(field) for field in ('id', 'address', 'pid', 'stableId', 'tag', 'order')})


def private(record, geometry, metadata):
    assert source_geometry(record) == geometry, ('Folding changed private source geometry or mode', geometry, source_geometry(record))
    assert geometry['workspace']['name'] == SPECIAL
    assert immutable(record) == metadata, ('Folding changed original restoration metadata or order', metadata, immutable(record))


def preview_position(session, record):
    return command('list')['positions'][preview_owner(session)][key(record)]


def shortcut(session, action):
    state = wait(lambda: (value := shell('status')) and value['lifecycle']['ready']
                 and value['activeShortcuts'].get(action) == value['settings'][action] and value,
                 'The managed shortcut owner is not ready for '+action)
    chord = state['settings'][action]
    # First native loading reloads compositor config. Reassert this private
    # fixture setting after that reload: wtype supplies its own keymap, whose
    # high-function keycodes need symbol matching rather than the host keymap.
    if h.call('repl', 'return hl.get_config("input.resolve_binds_by_sym")') != 'true':
        h.eval('hl.config({input={resolve_binds_by_sym=true}})')
    parts = chord.split(' + ')
    names = {'SUPER': 'logo', 'CTRL': 'ctrl', 'ALT': 'alt', 'SHIFT': 'shift'}
    modifiers = [names[value] for value in parts[:-1]]
    args = [part for modifier in modifiers for part in ('-M', modifier)]
    args += ['-s', '40', '-k', parts[-1], '-s', '40']
    args += [part for modifier in reversed(modifiers) for part in ('-m', modifier)]
    session.keys(*args)


def held_key_shortcut(chord, key='F8'):
    # One virtual keyboard/keymap contains the held application key and the
    # shortcut. A second wtype map can give the held keycode another keysym.
    parts = chord.split(' + ')
    names = {'SUPER': 'logo', 'CTRL': 'ctrl', 'ALT': 'alt', 'SHIFT': 'shift'}
    modifiers = [names[value] for value in parts[:-1]]
    args = ['wtype', '-s', '100', '-P', key, '-s', '700']
    args += [part for modifier in modifiers for part in ('-M', modifier)]
    args += ['-s', '40', '-k', parts[-1], '-s', '40']
    args += [part for modifier in reversed(modifiers) for part in ('-m', modifier)]
    return args+['-s', '6000', '-p', key, '-s', '100']


def install_shortcuts(session):
    def identity(item):
        return tuple(item.get(field, '') for field in ('dispatcher', 'arg', 'description', 'modmask')) \
            + (str(item.get('key', '')).lower(), item.get('submap', ''))
    registered = json.loads(h.call('repl', 'local m=_community_window_stash_shortcuts;return m and m.inspect() or "[]"'))
    owned = Counter(identity(item) for item in registered)
    occupied = set()
    for item in h.read('binds'):
        ident = identity(item)
        if owned[ident]:
            owned[ident] -= 1
        else:
            occupied.add((item.get('modmask'), str(item.get('key', '')).upper()))
    free = ['SUPER + CTRL + ALT + F'+str(number) for number in range(24, 0, -1)
            if (76, 'F'+str(number)) not in occupied]
    assert len(free) >= 3, 'Three unoccupied managed test chords were unavailable'
    for setting, chord in zip(SHORTCUT_KEYS, free):
        configure(setting, chord)
    wait(lambda: all(shell('status')['activeShortcuts'].get(setting) == chord
                     for setting, chord in zip(SHORTCUT_KEYS, free)),
         'Configured managed shortcut handles did not become active')
    registered = json.loads(h.call('repl', 'local m=_community_window_stash_shortcuts;return m and m.inspect() or "[]"'))
    for setting, chord in zip(SHORTCUT_KEYS, free):
        key_name = chord.split(' + ')[-1].lower()
        matching = [item for item in registered if item.get('enabled') is True and str(item.get('key', '')).lower() == key_name]
        # Lua callback dispatchers expose a registry reference as their arg,
        # not the eventual command text. Actual key events below prove routing.
        assert len(matching) == 1 and matching[0]['description'].startswith('Window Stash:'), \
            ('The real managed shortcut handle was not registered', setting, matching)
    return free


def start(session, record):
    value = show_controls(session, record)
    session.click(value['interaction']['interactRect'])
    return wait(lambda: active(record), 'The exact preview did not acquire native input', timeout=12)


def hover(session, value):
    rect = value.get('imageRect', value.get('rect', value))
    x, y = rect['x']+rect['width']*.35, rect['y']+rect['height']*.7
    session.move(x-1, y)
    session.move(x, y)
    time.sleep(.1)


def fold_by_shortcut(session, record, value=None):
    hover(session, value or ready(session, record))
    shortcut(session, 'minimizeShortcut')
    try:
        result = folded_ready(session, record)
    except AssertionError:
        print('Managed fold shortcut diagnostics:', dict(cursor=h.read('cursorpos'),
              bindings=json.loads(h.call('repl', 'return _community_window_stash_shortcuts.inspect()')),
              resolveBySymbol=h.call('repl', 'return hl.get_config("input.resolve_binds_by_sym")')), flush=True)
        raise
    wait(stopped, 'Folding retained an interaction request')
    drain()
    return result


def unfold_icon(session, record, grouped=False):
    value = folded_ready(session, record)
    session.click(value['rect'])
    wait(lambda: (saved := current(record)) and saved.get('previewFolded') is False,
         'Clicking a folded icon did not unfold its preview')
    def shown():
        if grouped:
            return next((item for item in previews(session)['cards']
                         if item['key'] == 'preview:app:'+record['app'].lower()), None)
        return card(session, record)
    return wait(lambda: (value := shown()) and value.get('geometryReady')
                and value['image']['hasContent'] and not value['held'] and not value['resizing'] and value,
                'Unfolded preview did not recover its own fresh-frame readiness', timeout=12)


def no_folded_capture(records):
    ids = {record['id'] for record in records}
    def stopped_captures():
        state = shell('status')
        images = [item for surface in state['surfaces'] for part in ('cards', 'tiles')
                  for item in surface['floatingPreviews'][part] if item['recordId'] in ids]
        return not any(item.get('image', {}).get('captureActive') for item in images) \
            and not any(state.get('previewGeometry', {}).get(ident, {}).get('pending') for ident in ids)
    wait(stopped_captures, 'A folded source retained preview capture or geometry work')


def same_card(before, after):
    assert all(abs(before[field]-after[field]) <= 1 for field in ('x', 'y', 'width', 'height', 'aspectOverride')), \
        ('Unfolding lost the remembered preview position, scale or proportions', before['rect'], after['rect'])


def restart_private_shell(directory):
    assert os.environ.get('WINDOW_STASH_ISOLATED_TEST') == '1' and (Path.home()/'.window-stash-isolated').is_file()
    config = Path(os.environ['OMARCHY_PATH'])/'shell'
    assert config.is_absolute() and (config/'shell.qml').is_file()
    with (directory/'restarted-folding-shell.log').open('w') as output:
        subprocess.run(['quickshell', 'kill', '-p', str(config), '--any-display'], check=True, timeout=20,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        process = subprocess.Popen(['qs', '-p', str(config/'shell.qml')], stdout=output, stderr=output)
    wait(shell_ready, 'Replacement private shell did not become ready', timeout=25)
    assert process.poll() is None, 'Replacement private shell exited'


def basic(session, directory, witness, restart_shell=False):
    log = directory/'responsive.jsonl'
    address = responsive(session, log)
    original = source_geometry({'address': address})
    record = park(session, address)
    seed(session, record, 230, 190, 360)
    # A non-natural shape makes accidental preview-geometry replacement visible.
    side(session, record, 'right', 70, 0)
    before = shaped(session, record)
    position = preview_position(session, record)
    metadata, geometry = immutable(record), source_geometry(record)
    witness_before = source_geometry({'address': witness})
    h.dispatch('focus', window='address:'+witness)
    value = fold_by_shortcut(session, record)
    private(record, geometry, metadata)
    assert source_geometry({'address': witness}) == witness_before, 'Hover folding minimized or moved the focused window behind the preview'
    no_folded_capture([record])
    wait(lambda: BridgeManager(h).native()['owners'] == 0 and not BridgeManager(h).native()['inputActive'],
         'A completely folded stash retained a rendering or input lease')
    assert preview_position(session, record) == position, 'Folded icon geometry replaced saved preview dimensions'
    hover(session, value)
    shortcut(session, 'minimizeShortcut')
    drain()
    assert len(command('list')['windows']) == 1 and current(record)['previewFolded'] is True, \
        'Minimize over the terminal icon stage minimized the underlying witness'
    print('PASS managed minimize folds only the hovered preview, preserves source/restore metadata and stops captures/render/input; folded-icon minimize is a no-op', flush=True)

    icon_before = folded_ready(session, record)
    drag(session, icon_before['rect'], 85, 35)
    moved = wait(lambda: (value := folded_ready(session, record)) and abs(value['x']-icon_before['x']) > 30 and value,
                 'The folded floating icon did not move')
    drain()
    assert preview_position(session, record) == position, 'Dragging an icon overwrote preview placement'
    if restart_shell:
        before_positions = copy.deepcopy(command('list')['positions'])
        stored_icon = before_positions.get(preview_owner(session), {}).get(moved['key'])
        assert stored_icon and abs(stored_icon[0]-moved['x']) <= 1 and abs(stored_icon[1]-moved['y']) <= 1, \
            ('Dragged icon did not persist its own position before restarting', moved, before_positions)
        restart_private_shell(directory)
        try:
            moved_after = wait(lambda: (value := icon(session, record)) and not value['held'] and not value['moving']
                               and abs(value['x']-moved['x']) <= 1 and abs(value['y']-moved['y']) <= 1 and value,
                               'Shell replacement lost the folded icon position', timeout=5)
        except AssertionError:
            print('Folded restart persistence diagnostics:', dict(before=moved, after=icon(session, record),
                  beforePositions=before_positions, afterPositions=command('list')['positions'],
                  monitor=session.monitor, monitors=command('list')['monitors'],
                  surfaces=[dict(screen=item['screen'], workspace=item['workspaceId'], folded=item['floatingPreviews']['folded'])
                            for item in shell('status')['surfaces']]), flush=True)
            raise
        assert current(record)['previewFolded'] is True and preview_position(session, record) == position
        no_folded_capture([record])
    after = unfold_icon(session, record)
    same_card(before, after)
    private(record, geometry, metadata)
    for _ in range(2):
        fold_by_shortcut(session, record)
        same_card(before, unfold_icon(session, record))
        private(record, geometry, metadata)
    session.click(ready(session, record)['imageRect'])
    wait(lambda: not current(record), 'Clicking the unfolded preview did not restore the real window')
    wait(lambda: source_geometry(record) == original, 'Two-stage restoration lost original floating geometry')
    print('PASS icon drag has independent persistence'+(' across a shell restart' if restart_shell else '')+'; repeated unfold restores custom preview geometry before full floating-window restoration', flush=True)
    return address


def keyboard_fold(session, directory, witness):
    log = directory/'keyboard.jsonl'
    address = spawn_fixture(session, log)
    record = park(session, address)
    seed(session, record, 260, 170, 400)
    geometry, metadata = source_geometry(record), immutable(record)
    configure('floatingPreviewKeyboard', 'click')
    result = start(session, record)
    owner = result['status']['status']['owner']
    source_click(session, record)
    wait(lambda: native_status(owner)['keyboardFocused'], 'Preview content click did not acquire keyboard focus')
    session.keys('-k', 'F11')
    wait(lambda: modes(address) == (0, 2), 'Keyboard fixture did not enter contained fullscreen')
    fullscreen_geometry = source_geometry(record)
    presses, releases = key_count(log, 'F8'), key_count(log, 'F8', 'key-release')
    hover(session, ready(session, record))
    held = subprocess.Popen(held_key_shortcut(shell('status')['settings']['minimizeShortcut']),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait(lambda: key_count(log, 'F8') == presses+1 and native_status(owner)['heldKeys'] > 0,
             'Held application key did not reach the exact source')
        folded_ready(session, record)
        wait(stopped, 'Folding retained the native input owner')
        wait(lambda: key_count(log, 'F8', 'key-release') == releases+1,
             'Folding did not release the held application key')
        assert held.poll() is None, 'Held-key fixture released physically before the folding acknowledgement'
        assert not native_status(owner)['active'] and not native_status(owner)['heldKeys'], 'Folded source retained native keyboard ownership'
        assert modes(address) == (0, 2), 'Folding exited contained fullscreen'
        private(record, fullscreen_geometry, metadata)
    except BaseException:
        print('Held-key folding diagnostics:', dict(events=events(log)[-25:], native=native_status(owner),
              current=BridgeManager(h).native()), flush=True)
        raise
    finally:
        held.wait(timeout=8)
    assert key_count(log, 'F8', 'key-release') == releases+1, 'Physical release was delivered twice after folding'
    no_folded_capture([record])
    assert BridgeManager(h).native()['owners'] == 0
    value = folded_ready(session, record)
    request = dict(serial=1, id=record['id'], monitor=session.monitor['name'], rect=dict(
        x=session.monitor['x']+value['x'], y=session.monitor['y']+value['y'], width=value['width'], height=value['height']),
        excludeRects=[], keyboard=False, fps=60, fullscreen='preview')
    rejected = subprocess.run(['python3', str(ROOT/'controller/interaction.py')], input=json.dumps(request)+'\n',
                              text=True, capture_output=True, timeout=8)
    outputs = [json.loads(line) for line in rejected.stdout.splitlines() if line.strip()]
    assert outputs and not any(item.get('state') == 'active' for item in outputs), ('Stale input helper reacquired a folded source', outputs)
    assert not BridgeManager(h).native()['inputActive'], 'Rejected folded helper retained input'
    unfold_icon(session, record)
    assert modes(address) == (0, 2), 'Unfolding lost passive fullscreen'
    command('restore', record['id'], '--to', 'original')
    wait(lambda: not current(record), 'Plain CLI restoration failed after folding')
    assert source_geometry(record)['size'] == geometry['size'] and modes(address) == (0, 0)
    configure('floatingPreviewKeyboard', 'mouse')
    print('PASS keyboard-focused fold drains held keys once before persistence, rejects stale helper input, and preserves passive fullscreen until real restoration', flush=True)


def restore_order(session, directory):
    records, originals = [], []
    for index, x in enumerate((180, 950)):
        address = responsive(session, directory/('order-'+str(index)+'.jsonl'), app='org.windowstash.FoldOrder')
        originals.append(source_geometry({'address': address}))
        record = park(session, address)
        records.append(record)
        seed(session, record, x, 200, 320)
        fold_by_shortcut(session, record)
    orders = {record['id']: current(record)['order'] for record in records}
    shortcut(session, 'restoreLastShortcut')
    wait(lambda: current(records[1]).get('previewFolded') is False, 'Newest restore skipped its preview stage')
    assert current(records[0])['previewFolded'] is True
    assert {record['id']: current(record)['order'] for record in records} == orders, 'Unfolding changed newest/FIFO ordering'
    assert source_geometry(records[1])['workspace']['name'] == SPECIAL
    shortcut(session, 'restoreLastShortcut')
    wait(lambda: not current(records[1]), 'Second newest restore did not restore the actual window')
    assert source_geometry(records[1]) == originals[1]
    shortcut(session, 'restoreOldestShortcut')
    wait(lambda: current(records[0]).get('previewFolded') is False, 'FIFO restore skipped its preview stage')
    assert current(records[0])['order'] == orders[records[0]['id']]
    shortcut(session, 'restoreOldestShortcut')
    wait(lambda: not current(records[0]), 'Second FIFO restore did not restore the actual window')
    assert source_geometry(records[0]) == originals[0]
    print('PASS real newest/FIFO managed bindings each unfold once then fully restore, keeping original order and exact floating geometry', flush=True)


def groups(session, directory):
    records = []
    for index in range(2):
        address = responsive(session, directory/('group-'+str(index)+'.jsonl'), app='org.windowstash.FoldGroup')
        records.append(park(session, address))
    configure('grouping', 'app')
    app_key = 'app:'+records[0]['app'].lower()
    monitor = preview_owner(session)
    session.touched.setdefault(monitor, set()).update(('preview:'+app_key, 'folded-preview:'+app_key))
    command('preview-position', monitor, 'preview:'+app_key, 440, 180, 400)
    shell('refresh')
    expand(session)
    fold_by_shortcut(session, records[0], ready_tile(session, records[0]))
    assert current(records[1]).get('previewFolded') is not True, 'Folding an exact group tile folded its sibling'
    wait(lambda: len(folded(session)['icons']) == 1 and any(item['recordId'] == records[1]['id'] for item in previews(session)['cards']),
         'Partial app folding did not partition the icon and surviving preview')
    unfold_icon(session, records[0], grouped=True)
    cover = wait(lambda: (value := ready(session)) and value['groupCount'] == 2 and value,
                 'Unfolded member did not rejoin its app cover')
    fold_by_shortcut(session, records[0], cover)
    wait(lambda: all(current(record).get('previewFolded') is True for record in records), 'App-cover folding did not fold all represented windows')
    value = folded_ready(session, records[0])
    assert set(value['recordIds']) == {record['id'] for record in records} and len(folded(session)['icons']) == 1, \
        'Folded app grouping duplicated icons or lost a represented window'
    session.click(value['rect'])
    wait(lambda: all(current(record).get('previewFolded') is False for record in records), 'Clicking a grouped folded icon did not unfold its represented subset')
    cover = wait(lambda: (value := ready(session)) and value['groupCount'] == 2 and value, 'Group cover did not return after unfold')
    fold_by_shortcut(session, records[0], cover)
    configure('grouping', 'window')
    wait(lambda: len(folded(session)['icons']) == 2, 'Per-window mode did not separate folded records')
    for record in records:
        session.touched.setdefault(monitor, set()).add(folded_ready(session, record)['key'])
    unfold_icon(session, records[0])
    assert current(records[1])['previewFolded'] is True
    value = folded_ready(session, records[1])
    session.click(value['rect'], button=273)
    wait(lambda: session.menu()['opened'], 'Folded icon did not open its window context menu')
    assert 'settings' in {item['id'] for item in session.menu()['actions']}, 'Folded context menu lost global settings'
    shell('dismiss')
    session.click(folded_ready(session, records[1])['rect'], button=274)
    wait(lambda: not h.client(records[1]['address']) and not current(records[1]), 'Middle-click did not close the folded window normally')
    assert h.client(records[0]['address']) and current(records[0]), 'Closing a folded icon affected its unfolded sibling'
    command('restore', records[0]['id'])
    print('PASS exact grouped tiles and app covers fold only their represented windows; icon grouping, context actions, subset unfolding and middle-close remain consistent', flush=True)


def hover_miss_and_mode(session, directory, witness):
    h.dispatch('focus', window='address:'+witness)
    session.move(1200, 700)
    shortcut(session, 'minimizeShortcut')
    record = wait(lambda: next((item for item in command('list')['windows'] if item['address'] == witness), None),
                  'Minimize away from previews did not stash the focused public window')
    touch(session, record)
    assert record.get('previewFolded') is not True, 'Ordinary window minimization skipped its preview stage'
    command('restore', record['id'])
    address = responsive(session, directory/'mode.jsonl', app='org.windowstash.FoldMode')
    record = park(session, address)
    seed(session, record, 270, 180, 320)
    fold_by_shortcut(session, record)
    configure('presentation', 'dock')
    shortcut(session, 'restoreLastShortcut')
    wait(lambda: not current(record) and h.client(address)['workspace']['name'] != SPECIAL,
         'Changing presentation stranded a folded window behind an invisible preview stage')
    configure('presentation', 'previews')
    print('PASS hover miss retains normal focused-window minimize and another presentation restores fully without a hidden extra stage', flush=True)


def scrolling(session, directory):
    workspace = session.workspace+2
    name = '__window_stash_fold_scrolling_'+str(os.getpid())
    h.eval('_G.'+name+'=hl.workspace_rule({workspace='+json.dumps(str(workspace))+',layout="scrolling",layout_opts={direction="right"}})')
    try:
        h.dispatch('focus', workspace=str(workspace))
        active_layout(session, workspace, 'scrolling')
        addresses = []
        for index in range(3):
            address = responsive(session, directory/('scrolling-'+str(index)+'.jsonl'), workspace,
                                 app='org.windowstash.FoldScrolling')
            h.dispatch('window.float', window='address:'+address, action='off')
            wait(lambda: not h.client(address)['floating'], 'Scrolling fixture did not tile')
            addresses.append(address)
        address = addresses[0]
        for fraction in (.31, .78):
            h.dispatch('focus', window='address:'+address)
            h.eval('hl.dispatch(hl.dsp.layout('+json.dumps('colresize '+str(fraction))+'))')
            width = h.client(address)['size'][0]
            record = park(session, address)
            seed(session, record, 220, 180, 320)
            metadata = immutable(record)
            fold_by_shortcut(session, record)
            shortcut(session, 'restoreLastShortcut')
            wait(lambda: current(record).get('previewFolded') is False, 'Scrolling source skipped preview unfolding')
            assert immutable(record) == metadata
            shortcut(session, 'restoreLastShortcut')
            restored = wait(lambda: (value := h.client(address)) and value['workspace']['id'] == workspace and not value['floating'] and value,
                            'Two-stage scrolling restoration did not return tiled')
            assert abs(restored['size'][0]-width) <= 1, ('Two-stage restore changed scrolling column pixels', width, restored['size'])
        print('PASS narrow and wide scrolling columns preserve saved pixel widths through icon and preview restoration stages', flush=True)
    finally:
        h.eval('if _G.'+name+' then _G.'+name+':set_enabled(false);_G.'+name+'=nil end')
        h.dispatch('focus', workspace=str(session.workspace))


@desktop_test('Isolated staged floating-preview minimization')
def main(proof_only=False, restart_shell=False, with_scrolling=False):
    assert os.environ.get('WINDOW_STASH_ISOLATED_TEST') == '1' and (Path.home()/'.window-stash-isolated').is_file(), \
        'Run only in the explicit disposable compositor'
    assert not command('list')['windows'], 'Staged preview acceptance requires an empty disposable stash'
    matching = h.call('repl', 'return hl.get_config("input.resolve_binds_by_sym")')
    assert matching in ('true', 'false')
    with tempfile.TemporaryDirectory(prefix='stash-preview-folding-') as temporary, NativeSession() as session:
        directory = Path(temporary)
        try:
            h.eval('hl.config({input={resolve_binds_by_sym=true}})')
            for setting, value in dict(presentation='previews', scope='workspace', grouping='window',
                                       floatingPreviewInteraction='on', floatingPreviewActivation='explicit',
                                       floatingPreviewKeyboard='mouse', floatingPreviewFullscreen='preview',
                                       floatingPreviewControls='hover', floatingPreviewUpdate='live',
                                       livePreviewCompatibility='enhanced', hoverPreview='off',
                                       floatingPreviewSizing='free', floatingPreviewTitles='hidden', floatingPreviewFrame='hidden',
                                       floatingPreviewLock='unlocked', floatingPlacement='free', dragMotion='direct', animations='off').items():
                configure(setting, value)
            witness, _title = session.spawn(app='org.windowstash.FoldingWitness')
            h.dispatch('window.float', window='address:'+witness, action='on')
            h.dispatch('window.resize', window='address:'+witness, x=1300, y=850, relative=False)
            h.dispatch('window.move', window='address:'+witness, x=session.monitor['x']+40, y=session.monitor['y']+50, relative=False)
            install_shortcuts(session)
            basic(session, directory, witness, restart_shell)
            if not proof_only:
                keyboard_fold(session, directory, witness)
                restore_order(session, directory)
                groups(session, directory)
                hover_miss_and_mode(session, directory, witness)
                if with_scrolling:
                    scrolling(session, directory)
            assert not command('list')['windows'], 'Staged acceptance retained an owned stash record'
        except BaseException:
            state = shell('status')
            print('Folding diagnostics:', dict(settings=state['settings'], windowIds=state['windowIds'],
                  preview=previews(session), interaction=state['previewInteraction'], lifecycle=state['lifecycle'],
                  native=BridgeManager(h).native(), ledger=command('list')['windows'], error=state['error']), flush=True)
            raise
        finally:
            pause_captures(session)
            h.eval('hl.config({input={resolve_binds_by_sym='+matching+'}})')
    native = BridgeManager(h).native()
    assert not native['inputActive'] and native['owners'] == 0 and native['pendingButtons'] == native['pendingKeys'] == 0, native
    assert shell('status')['lifecycle']['ready'] and not shell('status')['lifecycle']['error']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--proof-only', action='store_true', help='Only exercise physical fold/unfold and original floating restoration')
    parser.add_argument('--restart-shell', action='store_true', help='Verify stage and both saved positions through private shell replacement')
    parser.add_argument('--scrolling', action='store_true', help='Also verify narrow/wide scrolling restoration')
    args = parser.parse_args()
    main(args.proof_only, args.restart_shell, args.scrolling)
