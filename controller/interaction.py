#!/usr/bin/env python3
"""Own one verified preview input lease; compositor hooks route actual events."""
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

MAX_REQUEST = 8192
MAX_EXCLUDES = 16
RENEW_SECONDS = .5
RESTART_REQUIRED = 'Restart Hyprland to load interactive Window Stash previews'


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
    fields = {'serial', 'id', 'monitor', 'rect', 'excludeRects', 'keyboard', 'fps'}
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
    excluded = value.get('excludeRects', [])
    if not isinstance(excluded, list) or len(excluded) > MAX_EXCLUDES:
        raise ValueError('Interaction accepts at most 16 control exclusion rectangles')
    return dict(id=ident, serial=serial, monitor=monitor, rect=rectangle(value.get('rect')),
                excludeRects=[rectangle(item) for item in excluded], keyboard=keyboard, fps=fps)


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
    for field in ('active', 'keyboard', 'keyboardFocused'):
        fields.append(lua(json.dumps(field)+':')+'..tostring(result.'+field+'==true)')
    for field in ('owner', 'id', 'reason'):
        fields.append(lua(json.dumps(field)+':')+'..quote(result.'+field+')')
    for field in ('fps', 'heldButtons', 'heldKeys', 'motionEvents', 'buttonEvents', 'axisEvents', 'keyEvents',
                  'lastAxisDelta', 'lastAxisDiscrete', 'lastAxisSource'):
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

    def interaction_update(self, owner, source, target):
        identity = '{'+','.join(key+'='+lua(value) for key, value in source.items())+'}'
        excluded = '{'+','.join(lua_rectangle(rect) for rect in target['excludeRects'])+'}'
        script = (self.interaction_probe+'local result,err='+API+'.interaction_update({owner='+lua(owner)
            + ',window='+identity+',monitor='+lua(target['monitor'])+',rect='+lua_rectangle(target['rect'])
            + ',excludeRects='+excluded+',keyboard='+lua(target['keyboard'])+',fps='+lua(target['fps'])
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


class InteractionKeeper:
    def __init__(self, stash=None, bridge=None):
        self.stash = stash or Stash()
        self.bridge = bridge or InteractionBridge(self.stash.hypr)
        self.owner = uuid.uuid4().hex
        self.acquired = False
        self.activation = None
        self.target = None
        self.terminal = None

    def _source(self, target):
        with self.stash.locked():
            settings = self.stash.settings()
            if settings['presentation'] != 'previews' or settings['floatingPreviewInteraction'] != 'on':
                return None
            saved = list(self.stash.state['windows'])
        sources = preview_records(saved, self.stash.hypr.read('clients'), [target['id']])
        monitors = [monitor for monitor in self.stash.hypr.read('monitors') if monitor.get('name') == target['monitor']]
        if len(sources) != 1 or len(monitors) != 1 or monitors[0].get('dpmsStatus') is False:
            return None
        if not all(monitor_contains(monitors[0], rect) for rect in [target['rect'], *target['excludeRects']]):
            return None
        parameters = dict(target, keyboard=target['keyboard'] and settings['floatingPreviewKeyboard'] == 'click',
                          fps=int(settings['floatingPreviewInteractionFps']))
        return sources[0], parameters

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
        self.target = target
        if self.terminal:
            return self.terminal
        if self.acquired:
            status = self.bridge.interaction_status(self.owner)
            self._verify_status(status, target)
            if not status['active']:
                self.close()
                self.terminal = dict(state='ended', id=target['id'], serial=target['serial'],
                                     reason=status.get('reason') or 'Interaction ended', status=status)
                return self.terminal
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
        self.acquired = True  # Also release an acquisition that fails halfway.
        status = self.bridge.interaction_update(self.owner, *source)
        self._verify_status(status, target)
        result = dict(state='active' if status['active'] else 'ended', id=target['id'], serial=target['serial'],
                      reason=status.get('reason', ''), status=status)
        if not status['active']:
            self.terminal = result
            self.close()
        return result

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
    def emit(value):
        print(json.dumps(value), flush=True)

    def stop(_signal, _frame):
        raise PreviewStopped()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
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
