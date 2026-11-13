#!/usr/bin/env python3
"""Own one verified preview input lease; compositor hooks route actual events."""
import argparse
import contextlib
import json
import math
import os
import re
import select
import signal
import sys
import uuid

sys.dont_write_bytecode = True
from preview import API, PreviewBridge, PreviewStopped, preview_records
from stash import Stash, lua
import shortcuts

MAX_REQUEST = 8192
MAX_EXCLUDES = 16
RENEW_SECONDS = .5
RESTART_REQUIRED = 'Reload preview support in Window Stash Settings to use interactive previews'
FULLSCREEN_REQUIRED = 'Reload preview support in Window Stash Settings to keep fullscreen inside a preview, or choose Fullscreen: On desktop'
GEOMETRY_REQUIRED = 'Reload preview support in Window Stash Settings to interact with a reshaped preview'
GEOMETRY_PENDING = 'The application has not finished resizing its preview'
SHORTCUT_REQUIRED = 'Reload preview support in Window Stash Settings to use Super+left click'
CORNER_RESIZE_REQUIRED = 'Reload preview support in Window Stash Settings to resize preview corners with Super'
EXIT_SHORTCUT_KEY = 'floatingPreviewExitShortcut'
RESTORE_REASONS = frozenset(('modal-dialog', 'source-fullscreen', 'popup-outside', 'source-activation', 'window-management'))


def exit_shortcut(value, bindings=()):
    """Validate a session-only chord without creating global shortcut handles."""
    chord = shortcuts.normalize(value)
    if not chord:
        return chord, None
    parts = chord.split(' + ')
    modifiers = sum(shortcuts.MODIFIERS[part] for part in parts[:-1])
    for binding in bindings:
        if not isinstance(binding, dict) or binding.get('enabled') is False or binding.get('disabled') is True:
            continue
        if binding.get('modmask') == modifiers and str(binding.get('key', '')).lower() == parts[-1].lower():
            # Session input routing has no submap. Reserve all compositor
            # bindings, including non-default submaps and our global actions.
            raise ValueError('Interactive preview exit shortcut '+chord
                             +' is already assigned to another desktop action. Choose another shortcut or disable it.')
    return chord, dict(modmask=modifiers, key=parts[-1])


def configure_exit_shortcut(config, value, hypr):
    chord = shortcuts.normalize(value)
    if chord:
        exit_shortcut(chord, hypr.read('binds'))
    # Share the settings lock and conservative atomic merge used for ordinary
    # shortcut edits, while leaving every global binding and config untouched.
    with shortcuts._locked(config):
        data, entry = shortcuts._read(config)
        entry[EXIT_SHORTCUT_KEY] = chord
        shortcuts._atomic_json(config, data)
    return dict(ok=True, action='interaction-exit-shortcut', key=EXIT_SHORTCUT_KEY, binding=chord)


def rectangle(value):
    if not isinstance(value, dict) or set(value) != {'x', 'y', 'width', 'height'}:
        raise ValueError('An interaction rectangle needs x, y, width and height')
    if any(type(number) not in (int, float) or not math.isfinite(number) for number in value.values()):
        raise ValueError('Interaction coordinates must be finite numbers')
    if (any(abs(value[key]) > 10000000 for key in ('x', 'y'))
            or any(not 0 < value[key] <= 32768 for key in ('width', 'height'))):
        raise ValueError('Interaction rectangle is outside the supported coordinate range')
    return {key: value[key] for key in ('x', 'y', 'width', 'height')}


def request(value):
    if value is None:
        return None
    fields = {'serial', 'id', 'monitor', 'rect', 'excludeRects', 'keyboard', 'fps', 'fullscreen'}
    if not isinstance(value, dict) or set(value)-fields:
        raise ValueError('Use one preview interaction request, or null to stop')
    ident = value.get('id')
    if not isinstance(ident, str) or not re.fullmatch(r'[0-9a-f]{32}', ident):
        raise ValueError('Interaction needs one exact stash record ID')
    monitor = value.get('monitor')
    if (not isinstance(monitor, str) or not 0 < len(monitor) <= 128
            or any(ord(character) < 32 or ord(character) == 127 for character in monitor)):
        raise ValueError('Interaction needs a valid monitor name')
    serial = value.get('serial', 0)
    if type(serial) is not int or not 0 <= serial <= 2147483647:
        raise ValueError('Interaction serial must be a nonnegative 32-bit integer')
    keyboard = value.get('keyboard', False)
    fps = value.get('fps', 60)
    if type(keyboard) is not bool or type(fps) is not int or fps not in (30, 60):
        raise ValueError('Use a boolean keyboard policy and a 30 or 60 FPS limit')
    fullscreen = value.get('fullscreen', 'preview')
    if not isinstance(fullscreen, str) or fullscreen not in ('preview', 'desktop'):
        raise ValueError('Fullscreen must stay inside the preview or open on the desktop')
    excluded = value.get('excludeRects', [])
    if not isinstance(excluded, list) or len(excluded) > MAX_EXCLUDES:
        raise ValueError('Interaction accepts at most 16 control exclusion rectangles')
    return dict(id=ident, serial=serial, monitor=monitor, rect=rectangle(value.get('rect')),
                excludeRects=[rectangle(item) for item in excluded], keyboard=keyboard, fps=fps, fullscreen=fullscreen)


def monitor_contains(monitor, rect):
    scale = monitor.get('scale', 1)
    if type(scale) not in (int, float) or not math.isfinite(scale) or scale <= 0:
        return False
    width, height = monitor['width'], monitor['height']
    if monitor.get('transform', 0) % 2:
        width, height = height, width
    # Rounding matches Hyprland's logical output dimensions and the placement
    # helpers; the rectangle stays in desktop coordinates, including negatives.
    return (rect['x'] >= monitor['x'] and rect['y'] >= monitor['y']
            and rect['x']+rect['width'] <= monitor['x']+round(width/scale)
            and rect['y']+rect['height'] <= monitor['y']+round(height/scale))


def lua_rectangle(rect):
    return '{'+','.join(key+'='+lua(rect[key]) for key in ('x', 'y', 'width', 'height'))+'}'


def status_json(expression):
    """Return JSON text from repl; native Lua tables otherwise pretty-print."""
    script = ('local result=('+expression+'); assert(type(result)=="table", "Could not read preview interaction state")\n'
        + 'local function quote(value) return \'"\'..tostring(value or ""):gsub('
        + lua('[%z\x01-\x1f\\"]')+',function(c) return string.format('+lua('\\u%04x')
        + ',string.byte(c)) end)..\'"\' end\n'
        + 'local function count(value) return type(value)=="table" and #value or tonumber(value) or 0 end\n')
    fields = []
    for field in ('active', 'keyboard', 'keyboardFocused', 'restoreRequested', 'previewFullscreen'):
        fields.append(lua(json.dumps(field)+':')+'..tostring(result.'+field+'==true)')
    for field in ('owner', 'id', 'reason', 'fullscreen', 'activationOrigin'):
        fields.append(lua(json.dumps(field)+':')+'..quote(result.'+field+')')
    for field in ('fps', 'heldButtons', 'heldKeys', 'motionEvents', 'buttonEvents', 'axisEvents', 'keyEvents',
                  'lastAxisDelta', 'lastAxisDiscrete', 'lastAxisSource', 'pointerActivationAllowance',
                  'pointerActivationRemainingMs', 'clientActivationEvents', 'pointerActivationAcknowledgements',
                  'fullscreenActivationAcknowledgements', 'keyboardActivationAcknowledgements'):
        fields.append(lua(json.dumps(field)+':')+'..tostring(count(result.'+field+'))')
    for name, members in (('rect', ('x', 'y', 'width', 'height')), ('lastLocal', ('x', 'y')), ('lastGlobal', ('x', 'y'))):
        rect = [lua(json.dumps(field)+':')+'..tostring(count((result.'+name+' or {}).'+field+'))' for field in members]
        fields.append(lua(json.dumps(name)+':{')+'..'+('..","..'.join(rect))+'.."}"')
    return script+'return "{"..'+('..","..'.join(fields))+'.."}"'


class InteractionBridge(PreviewBridge):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.interaction_probe = self.probe + ('if type('+API+'.interaction_update)~="function" or type('
            + API+'.interaction_release)~="function" or type('+API+'.interaction_status)~="function" then error('
            + lua(RESTART_REQUIRED)+') end\n')

    def ensure(self):
        super().ensure()
        self.hypr.eval(self.interaction_probe)

    def prepare_shortcut(self, resize=False):
        # Prepare interception before the first click, including Standard/Still
        # previews. This takes no input/rendering lease and never replaces a
        # loaded bridge. Older bridges retain their ordinary Interact control.
        self.ensure()
        with self.operation():
            supported = self.hypr.call('repl', self.interaction_probe
                + 'return info.capabilities and info.capabilities.superClickActivation==true'
                + (' and info.capabilities.superCornerResize==true' if resize else '')+' or false')
            interactive_resize = resize and supported == 'true' and self.hypr.call('repl', self.interaction_probe
                + 'return info.capabilities and info.capabilities.interactiveResize==true or false') == 'true'
        if supported != 'true':
            raise RuntimeError(CORNER_RESIZE_REQUIRED if resize else SHORTCUT_REQUIRED)
        return dict(state='ready', cornerResize=True, interactiveResize=interactive_resize) if resize else dict(state='ready')

    def interaction_update(self, owner, source, target):
        with self.operation():
            return self._interaction_update(owner, source, target)

    def _interaction_update(self, owner, source, target):
        identity = '{'+','.join(key+'='+lua(value) for key, value in source.items())+'}'
        excluded = '{'+','.join(lua_rectangle(rect) for rect in target['excludeRects'])+'}'
        exit_binding = target.get('exitShortcut')
        exit_value = ('{modmask='+lua(exit_binding['modmask'])+',key='+lua(exit_binding['key'])+'}'
                      if exit_binding else 'nil')
        fullscreen = target.get('fullscreen', 'preview')
        capability = ('assert(info.capabilities and info.capabilities.constrainedFullscreen==true,'
                      +lua(FULLSCREEN_REQUIRED)+')\n') if fullscreen == 'preview' else ''
        geometry = ('assert(info.capabilities and info.capabilities.sourceGeometry==true and type('+API+'.source_geometry)=="function",'
                    +lua(GEOMETRY_REQUIRED)+')\nlocal geometry,geometryError='+API+'.source_geometry('+identity+'); assert(geometry,geometryError); '
                    +'assert(type(geometry)=="table" and geometry.ready==true,'+lua(GEOMETRY_PENDING)+')\n') if target.get('requireSourceGeometry') is True else ''
        script = (self.interaction_probe+capability+geometry+'local result,err='+API+'.interaction_update({owner='+lua(owner)
            + ',window='+identity+',monitor='+lua(target['monitor'])+',rect='+lua_rectangle(target['rect'])
            + ',excludeRects='+excluded+',keyboard='+lua(target['keyboard'])+',fps='+lua(target['fps'])
            + ',exitShortcut='+exit_value
            + ',fullscreen='+lua(fullscreen)
            + '}); assert(result,err); '+status_json('result'))
        return self._status(self.hypr.call('repl', script))

    def interaction_status(self, owner):
        return self._status(self.hypr.call('repl', self.interaction_probe+status_json(API+'.interaction_status('+lua(owner)+')')))

    @staticmethod
    def _status(raw):
        value = json.loads(raw)
        if not isinstance(value, dict) or type(value.get('active')) is not bool:
            raise RuntimeError('Could not read preview interaction state')
        return value

    def interaction_release(self, owner):
        self.hypr.eval('if hl.plugin and '+API+' and type('+API+'.interaction_release)=="function" then '
                       +API+'.interaction_release('+lua(owner)+') end')

    def interaction_handoff(self, owner):
        self.hypr.eval(self.interaction_probe+'assert(type('+API+'.interaction_handoff)=="function",'
                       +lua(RESTART_REQUIRED)+'); local result,err='+API+'.interaction_handoff('+lua(owner)+'); assert(result,err)')


class InteractionKeeper:
    def __init__(self, stash=None, bridge=None):
        self.stash = stash or Stash()
        self.bridge = bridge or InteractionBridge(self.stash.hypr)
        self.owner = uuid.uuid4().hex
        self.acquired = False
        self.activation = None
        self.target = None
        self.terminal = None
        self.exit_chord = None
        self.exit_binding = None
        self.bound_source = None
        self.keyboard_policy = None
        self.fullscreen_policy = None

    def _source(self, target):
        with self.stash.locked():
            settings = self.stash.settings()
            saved = list(self.stash.state['windows'])
        return self._validated_source(target, settings, saved)

    def _validated_source(self, target, settings, saved):
        if settings['presentation'] != 'previews' or settings['floatingPreviewInteraction'] != 'on':
            return None
        if any(record.get('id') == target['id'] and record.get('previewFolded') is True for record in saved):
            return None
        sources = preview_records(saved, self.stash.hypr.read('clients'), [target['id']])
        monitors = [monitor for monitor in self.stash.hypr.read('monitors') if monitor.get('name') == target['monitor']]
        if len(sources) != 1 or len(monitors) != 1 or monitors[0].get('dpmsStatus') is False:
            return None
        if settings['scope'] == 'workspace':
            origin = next((record.get('origin') for record in saved if record.get('id') == target['id']), None)
            active = monitors[0].get('activeWorkspace')
            if (not isinstance(origin, dict) or not isinstance(active, dict) or type(active.get('id')) is not int
                    or origin.get('id') != active['id']):
                return None
        if not all(monitor_contains(monitors[0], rect) for rect in [target['rect'], *target['excludeRects']]):
            return None
        parameters = dict(target, keyboard=target['keyboard'] and settings['floatingPreviewKeyboard'] == 'click',
                          fps=int(settings['floatingPreviewInteractionFps']), exitShortcut=settings[EXIT_SHORTCUT_KEY],
                          fullscreen=settings['floatingPreviewFullscreen'],
                          requireSourceGeometry=any(record.get('previewResized') is True for record in saved if record.get('id') == target['id']))
        return sources[0], parameters

    def _restore_handoff(self, target):
        with self.bridge.operation() if isinstance(self.bridge, PreviewBridge) else contextlib.nullcontext():
            return self._guarded_restore_handoff(target)

    def _guarded_restore_handoff(self, target):
        # Native detection is a request, not authority to mutate a client. Hold
        # the ledger lock and recheck the exact initially accepted identity,
        # ownership, phase, monitor and visibility policy before restoration.
        with self.stash.locked():
            settings = self.stash.settings()
            saved = list(self.stash.state['windows'])
            source = self._validated_source(target, settings, saved)
            if source is None or self.bound_source is None or source[0] != self.bound_source:
                return dict(restored=False)
            record = next(record for record in saved if record['id'] == target['id'])
            result = self.stash.restore(record['id'], to=settings['restoreDestination'],
                                        monitor=target['monitor'],
                                        expected=dict(record, stableId=self.bound_source['stable_id']))
            if result.get('action') != 'restored':
                return dict(restored=False)
        # The native owner tombstone retains weak exact transient identities;
        # it may move/focus only those children after validating the now-public
        # parent. No titles, app IDs or PIDs alone can adopt another window.
        self.bridge.interaction_handoff(self.owner)
        return dict(restored=True)

    def _finish(self, target, status):
        result = dict(state='ended', id=target['id'], serial=target['serial'],
                      reason=status.get('reason') or 'Interaction ended', status=status)
        try:
            if status.get('restoreRequested') is True and status.get('reason') in RESTORE_REASONS:
                if status.get('owner') != self.owner or status.get('id') != target['id']:
                    raise RuntimeError('Native restore request does not match the active window and owner')
                result.update(self._restore_handoff(target))
        finally:
            self.close()
        self.terminal = result
        return result

    def sync(self, value):
        target = request(value)
        if target is None:
            self.close()
            return dict(state='idle', id='')
        activation = (target['serial'], target['id'])
        if self.activation != activation:
            self.close()
            self.owner = uuid.uuid4().hex
            self.activation = activation
            self.terminal = None
            self.bound_source = None
            self.keyboard_policy = None
            self.fullscreen_policy = None
        self.target = target
        if self.terminal:
            return self.terminal
        if self.acquired:
            status = self.bridge.interaction_status(self.owner)
            self._verify_status(status, target)
            if not status['active']:
                return self._finish(target, status)
        source = self._source(target)
        if source is None:
            self.close()
            self.terminal = dict(state='ended', id=target['id'], serial=target['serial'], reason='Preview is no longer available')
            return self.terminal
        if not self.acquired:
            self.bridge.ensure()
            # Building/loading the extension can take time and refresh compositor
            # configuration. Do not acquire from the pre-build identity or output.
            source = self._source(target)
            if source is None:
                self.terminal = dict(state='ended', id=target['id'], serial=target['serial'], reason='Preview changed while interaction was starting')
                return self.terminal
        identity, parameters = source
        verified_parameters = dict(parameters)
        if self.bound_source is not None and identity != self.bound_source:
            return self._finish(target, dict(active=False, reason='window-unavailable'))
        if self.acquired and self.keyboard_policy != parameters['keyboard']:
            return self._finish(target, dict(active=False, reason='keyboard-policy-changed'))
        if self.acquired and self.fullscreen_policy != parameters['fullscreen']:
            return self._finish(target, dict(active=False, reason='fullscreen-policy-changed'))
        chord = parameters.pop('exitShortcut')
        if not self.acquired or chord != self.exit_chord:
            _, self.exit_binding = exit_shortcut(chord, self.stash.hypr.read('binds') if chord else [])
            self.exit_chord = chord
        parameters['exitShortcut'] = self.exit_binding
        self.bound_source = dict(identity)
        self.keyboard_policy = parameters['keyboard']
        self.fullscreen_policy = parameters['fullscreen']
        with self.bridge.operation() if isinstance(self.bridge, PreviewBridge) else contextlib.nullcontext(), self.stash.locked():
            # Serialize the last authoritative check with fold commits. Builds
            # remain outside the ledger lock; stale snapshots cannot reacquire
            # input after the UI has switched this window to its folded icon.
            fresh = self._validated_source(target, self.stash.settings(), list(self.stash.state['windows']))
            if fresh is None or fresh[0] != identity or fresh[1] != verified_parameters:
                self.close()
                self.terminal = dict(state='ended', id=target['id'], serial=target['serial'],
                                     reason='Preview changed before interaction was acquired')
                return self.terminal
            self.acquired = True  # Also release an acquisition that fails halfway.
            status = self.bridge.interaction_update(self.owner, identity, parameters)
        self._verify_status(status, target)
        if not status['active']:
            return self._finish(target, status)
        return dict(state='active', id=target['id'], serial=target['serial'], reason=status.get('reason', ''), status=status)

    def _verify_status(self, status, target):
        if status['active'] and (status.get('owner') != self.owner or status.get('id') != target['id']):
            raise RuntimeError('Native interaction did not acknowledge the requested window and owner')

    def close(self):
        if self.acquired:
            try:
                self.bridge.interaction_release(self.owner)
            finally:
                self.acquired = False


def run_loop(stream, keeper, emit):
    buffer = b''
    wanted = None
    received = False
    previous = None
    try:
        while True:
            readable, _, _ = select.select([stream], [], [], RENEW_SECONDS)
            if readable:
                chunk = os.read(stream.fileno(), 8192)
                if not chunk:
                    return 0
                buffer += chunk
                while b'\n' in buffer:
                    line, buffer = buffer.split(b'\n', 1)
                    if len(line) > MAX_REQUEST:
                        raise ValueError('Interaction request exceeded the input limit')
                    wanted = request(json.loads(line))
                    received = True
                if len(buffer) > MAX_REQUEST:
                    raise ValueError('Interaction request exceeded the input limit')
            if not received:
                continue
            state = keeper.sync(wanted)
            if state != previous:
                emit(state)
                previous = state
            if state['state'] in ('ended', 'idle'):
                return 0
    finally:
        keeper.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare', action='store_true',
                        help='Prepare preview Super-click/resize gestures without acquiring input or rendering')
    arguments = parser.parse_args()

    def emit(value):
        print(json.dumps(value), flush=True)

    def stop(_signal, _frame):
        raise PreviewStopped()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    if arguments.prepare:
        try:
            settings = Stash().settings()
            resize = (settings.get('floatingPreviewSizing', 'free') != 'preset'
                      and settings.get('floatingPreviewLock', 'unlocked') != 'locked')
            if settings['presentation'] != 'previews' or (settings['floatingPreviewInteraction'] != 'on' and not resize):
                emit(dict(state='disabled'))
            else:
                emit(InteractionBridge(progress=emit).prepare_shortcut(resize=resize))
            return 0
        except PreviewStopped:
            return 0
        except Exception as error:
            emit(dict(state='unavailable', error=str(error)))
            return 1
    disconnected = select.poll()
    disconnected.register(sys.stdin.fileno(), select.POLLHUP | select.POLLERR | select.POLLNVAL)
    bridge = InteractionBridge(progress=emit, cancelled=lambda: bool(disconnected.poll(0)))
    keeper = InteractionKeeper(bridge=bridge)
    try:
        return run_loop(sys.stdin.buffer, keeper, emit)
    except PreviewStopped:
        return 0
    except Exception as error:
        emit(dict(state='unavailable', id=(keeper.target or {}).get('id', ''), error=str(error)))
        return 1


if __name__ == '__main__':
    sys.exit(main())
