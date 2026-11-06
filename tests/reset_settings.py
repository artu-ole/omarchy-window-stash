#!/usr/bin/env python3
"""Native reset confirmation, canonical defaults and preserved window state.

Install this checkout before running in an unlocked Hyprland session. Only
owned fixtures and unused temporary shortcut chords are used; NativeSession
restores the original desktop preferences, bindings, positions and focus.
"""
import copy
import importlib.util
import json

from desktop_test import desktop_test
from live import ROOT, command, configure, h, shell, wait
from native_session import NativeSession
from stash import DEFAULTS, PLUGIN, Stash, read_json
import shortcuts


spec = importlib.util.spec_from_file_location('reset_shortcut_helpers', ROOT/'tests/shortcuts.py')
shortcut_helpers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shortcut_helpers)


def idle():
    return wait(lambda: (s if not (s := shell('status'))['controllerBusy'] and not s['queueLength'] else None),
                'Reset controller did not finish')


def clients():
    # Ignore changing titles and focus; reset must preserve real window
    # identity, workspaces, geometry and compositor state.
    fields = ('address', 'pid', 'stableId', 'workspace', 'floating', 'at', 'size',
              'fullscreen', 'fullscreenClient', 'pinned', 'tags')
    return sorted((json.dumps({key: client.get(key) for key in fields}, sort_keys=True)
                   for client in h.read('clients')))


def snapshot():
    idle()
    value = command('list')
    ledger = Stash()
    return {'settings': copy.deepcopy(value['settings']), 'windows': copy.deepcopy(value['windows']),
            'positions': copy.deepcopy(value['positions']), 'clients': clients(),
            'state': ledger.path.read_bytes(),
            'positionBytes': ledger.positions.read_bytes() if ledger.positions.exists() else None,
            'bindings': shortcut_helpers.active_signature(),
            'foreign': sorted(json.dumps(b, sort_keys=True) for b in shortcut_helpers.foreign_bindings())}


def unchanged(expected, preferences=True):
    actual = snapshot()
    for key in ('windows', 'positions', 'clients', 'state', 'positionBytes', 'foreign'):
        assert actual[key] == expected[key], 'Reset interaction changed '+key
    if preferences:
        assert actual['settings'] == expected['settings'], 'Unconfirmed reset changed preferences'
        assert actual['bindings'] == expected['bindings'], 'Unconfirmed reset changed managed shortcuts'


def open_settings(session):
    shell('settings')
    wait(lambda: session.surface()['dialog']['visible'], 'Reset settings panel did not open')
    assert not session.surface()['reset']['confirming'], 'A dismissed confirmation survived reopening settings'


def ask(session):
    reset = session.surface()['reset']
    assert reset['requestEnabled'] and not reset['busy'], 'Reset action was unavailable while idle'
    session.click(reset['requestRect'])
    return wait(lambda: (r if (r := session.surface()['reset'])['confirming'] else None),
                'Reset action did not open its confirmation')


def defaults_active():
    active = sorted((b['description'], b['modmask'], str(b['key']).upper())
                    for b in shortcut_helpers.owned() if b.get('enabled') is True)
    expected = []
    for key, binding in shortcuts.DEFAULT_SHORTCUTS.items():
        if binding:
            parts = binding.split(' + ')
            expected.append((shortcuts.ACTIONS[key][1], sum(shortcuts.MODIFIERS[m] for m in parts[:-1]), parts[-1].upper()))
    assert active == sorted(expected), 'Reset defaults were saved without replacing active managed shortcuts'


@desktop_test('Window Stash reset settings test')
def main():
    with NativeSession() as session:
        configure('scope', 'workspace')
        configure('animations', 'off')
        configure('hoverPreview', 'off')
        for app in ('org.windowstash.ResetOne', 'org.windowstash.ResetTwo'):
            session.park(session.spawn(app=app, workspace=session.workspace)[0])
        chords = shortcut_helpers.free_chords(shell('status')['settings'])
        custom = dict(presentation='dock', scope='workspace', restoreDestination='original', grouping='app',
                      iconShape='squircle', sizePreset='175', floatingDirection='horizontal', floatingAnimation='jumping',
                      dragMotion='direct', dockSide='left', floatingPlacement='free', dockCorners='custom',
                      dockCornerRadius=39, iconFrame='shown', dockFrame='shown', animations='off', animationSpeed='ultrafast',
                      dockOpacity=33, iconOpacity=44, hoverPreview='still', previewSize='large', previewPlacement='above',
                      previewTitles='hidden', previewDelay=75, previewHideDelay=87,
                      minimizeShortcut=chords[0], restoreLastShortcut=chords[1], restoreOldestShortcut=chords[2])
        assert set(custom) == set(DEFAULTS), 'Reset fixture does not exercise every current preference'
        assert all(custom[key] != DEFAULTS[key] for key in DEFAULTS), 'Reset fixture contains an unchanged default'
        for key, value in custom.items():
            configure(key, 'floating' if key == 'presentation' else value)
        session.resting()
        area = session.surface()['usableArea']
        # This position is valid for both the custom free-placement stack and
        # the smaller default stack with edge gravity enabled.
        session.position('dock:floating', round(area['x']+8), round(area['y']+8))
        configure('presentation', custom['presentation'])
        session.resting()
        before = snapshot()
        assert before['settings'] == custom, 'Custom reset fixture was not fully saved'
        open_settings(session)
        serial = session.surface()['reset']['serial']

        prompt = ask(session)
        session.click(prompt['cancelRect'])
        wait(lambda: not session.surface()['reset']['confirming'], 'Cancel did not return to settings')
        assert session.surface()['dialog']['visible'], 'Cancel unexpectedly closed settings'
        unchanged(before)

        ask(session)
        session.keys('-k', 'Return')
        wait(lambda: not session.surface()['reset']['confirming'], 'Default Enter did not cancel reset')
        unchanged(before)

        ask(session)
        session.keys('-k', 'Escape')
        wait(lambda: not session.surface()['reset']['confirming'], 'Escape did not cancel reset')
        assert session.surface()['dialog']['visible'], 'Escape did not return to settings'
        unchanged(before)

        ask(session)
        session.click({'x': 4, 'y': 4, 'width': 4, 'height': 4})
        wait(lambda: not session.surface()['dialog']['rendered'], 'Outside click did not dismiss the reset panel')
        unchanged(before)
        open_settings(session)
        ask(session)
        shell('dismiss')
        wait(lambda: not session.surface()['dialog']['rendered'], 'Explicit dismiss did not close the reset panel')
        open_settings(session)
        assert session.surface()['reset']['serial'] == serial, 'An unconfirmed interaction queued a reset'
        unchanged(before)
        print('PASS Cancel, default Enter, Escape, outside dismissal and reopen leave preferences, shortcuts and windows unchanged', flush=True)

        # Draft text is intentionally never submitted. Reset must discard all
        # three drafts, including fields whose dirty state blocks normal sync.
        for key in shortcut_helpers.KEYS:
            session.click(shortcut_helpers.reveal(session, key))
            session.keys('-M', 'ctrl', '-k', 'a', '-m', 'ctrl')
            session.keys(chords[3])
            wait(lambda: (c := shortcut_helpers.control(session, key))['text'] == chords[3]
                 and c['dirty'] and not c['pending'], 'Shortcut draft did not remain unapplied: '+key)
        prompt = ask(session)
        session.click(prompt['cancelRect'])
        wait(lambda: not session.surface()['reset']['confirming'], 'Cancel did not preserve the shortcut drafts')
        assert all(c['dirty'] and c['text'] == chords[3] for c in session.surface()['shortcutControls']), \
            'Cancelling reset discarded unapplied shortcut drafts'
        unchanged(before)

        prompt = ask(session)
        rect = prompt['confirmRect']
        session.move(rect['x']+rect['width']/2, rect['y']+rect['height']/2)
        # Two actual releases exercise busy/confirmation guards while the
        # controller is still starting, rather than repeating an IPC command.
        for _ in range(2):
            session.pointer.button(True)
            session.pointer.button(False)
        wait(lambda: shell('status')['settings'] == DEFAULTS and not session.surface()['reset']['busy'],
             'Confirmed reset did not apply canonical defaults')
        idle()
        reset = session.surface()['reset']
        assert reset['serial'] == serial+1, 'Repeated confirmation queued more than one reset'
        assert not reset['confirming'], 'Successful reset retained its confirmation'
        assert command('list')['settings'] == DEFAULTS, 'Canonical defaults were not persisted'
        ledger = Stash()
        entry = next(p for p in read_json(ledger.config, {})['plugins'] if p.get('id') == PLUGIN)
        assert {key: entry.get(key) for key in DEFAULTS} == DEFAULTS, 'Reset persisted incomplete defaults'
        assert all(c['text'] == DEFAULTS[c['key']] and c['binding'] == DEFAULTS[c['key']]
                   and not c['dirty'] and not c['pending'] for c in session.surface()['shortcutControls']), \
            'Successful reset retained dirty shortcut drafts'
        defaults_active()
        unchanged(before, preferences=False)
        assert shell('status')['settings']['sizePreset'] == '100', 'Reset retained custom icon sizing'
        assert not shell('status')['error'], shell('status')['error']
        shell('dismiss')
        wait(lambda: not session.surface()['dialog']['rendered'], 'Default settings did not finish dismissing')
        open_settings(session)
        assert not session.surface()['reset']['confirming'] and not session.surface()['reset']['busy']
        print('PASS one confirmed reset persists every default, replaces managed shortcuts and preserves stash, positions and client geometry', flush=True)
    idle()


if __name__ == '__main__':
    main()
