#!/usr/bin/env python3
"""Inspect or explicitly replace only Window Stash's optional native bridge."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import select
import signal
import subprocess
import sys
import time

sys.dont_write_bytecode = True
from bridge_runtime import BUSY, bridge_gate
from preview import API, PreviewBridge, ROOT
from stash import Hyprland, lua

SEMVER = r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)'
HASH = r'[0-9a-f]{40}'
FINGERPRINT = r'[0-9a-f]{64}'

# repl renders Lua tables as addresses. Serialize a bounded set of scalars in
# Lua, including proper JSON escaping rather than Lua's incompatible %q escapes.
STATUS_SCRIPT = r'''
local api=hl.plugin and hl.plugin.window_stash_preview
if not api or type(api.status)~='function' then return '{"available":false}' end
local s=api.status(); assert(type(s)=='table','Unreadable native preview status')
local function encode(v)
 if type(v)=='boolean' then return v and 'true' or 'false' end
 if type(v)=='number' then return tostring(v) end
 if type(v)~='string' then return 'null' end
 return '"'..v:gsub('[%z\1-\31\\"]',function(c)
  if c=='"' then return '\\"' end
  if c=='\\' then return '\\\\' end
  return string.format('\\u%04x',string.byte(c))
 end)..'"'
end
local i=type(s.interaction)=='table' and s.interaction or {}
local fields={available=true,protocol=s.protocol,version=s.version,hyprlandHash=s.hyprlandHash,
 fingerprint=s.fingerprint,modulePath=s.modulePath,owners=s.owners,windows=s.windows,
 reloadProtocol=s.reloadProtocol,reloadPending=s.reloadPending,reloadReady=s.reloadReady,pendingButtons=s.pendingButtons,pendingKeys=s.pendingKeys,
 hasPrepare=type(api.prepare_reload)=='function',hasCancel=type(api.cancel_reload)=='function',
 hasInteraction=type(api.interaction_update)=='function',inputActive=i.active==true,
 heldButtons=i.heldButtons or 0,heldKeys=i.heldKeys or 0}
local out={};for k,v in pairs(fields) do out[#out+1]='"'..k..'":'..encode(v) end
return '{'..table.concat(out,',')..'}'
'''


def decode_status(raw):
    value = json.loads(raw)
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict) or type(value.get('available')) is not bool:
        raise RuntimeError('Could not read native preview support status')
    if not value['available']:
        return value
    if (not isinstance(value.get('version'), str) or not re.fullmatch(SEMVER, value['version'])
            or type(value.get('protocol')) is not int
            or not isinstance(value.get('hyprlandHash'), str) or not re.fullmatch(HASH, value['hyprlandHash'])):
        raise RuntimeError('Native preview support returned an unrecognized identity')
    required = ('owners', 'windows', 'hasPrepare', 'hasCancel', 'hasInteraction', 'inputActive')
    if any(name not in value for name in required):
        raise RuntimeError('Native preview support returned incomplete reload state')
    for name in ('owners', 'windows', 'pendingButtons', 'pendingKeys', 'heldButtons', 'heldKeys'):
        if name in value and (type(value[name]) is not int or not 0 <= value[name] <= 100000):
            raise RuntimeError('Native preview support returned invalid lease counters')
    for name in ('hasPrepare', 'hasCancel', 'hasInteraction', 'inputActive', 'reloadPending', 'reloadReady'):
        if name in value and type(value[name]) is not bool:
            raise RuntimeError('Native preview support returned invalid reload state')
    if value.get('hasPrepare'):
        if (type(value.get('reloadProtocol')) is not int or value['reloadProtocol'] != 1
                or not isinstance(value.get('fingerprint'), str) or not re.fullmatch(FINGERPRINT, value['fingerprint'])
                or not isinstance(value.get('modulePath'), str) or not 1 <= len(value['modulePath']) <= 4096
                or any(name not in value for name in ('reloadPending', 'reloadReady', 'pendingButtons', 'pendingKeys'))):
            raise RuntimeError('Native preview support returned incomplete reload capabilities')
    return value


class BridgeManager:
    def __init__(self, hypr=None, emit=None, cancelled=None):
        self.hypr = hypr or Hyprland()
        self.expected = PreviewBridge(self.hypr).version
        self.emit = emit or (lambda value: None)
        self.cancelled = cancelled or (lambda: False)
        self.cache = Path(os.environ.get('XDG_CACHE_HOME', Path.home()/'.cache'))/'omarchy/window-stash/preview-bridge'

    def report(self, value):
        try:
            self.emit(value)
        except BrokenPipeError:
            # The owning shell can exit after unload. Progress delivery must
            # never prevent the verified replacement from completing.
            pass

    def native(self):
        return decode_status(self.hypr.call('repl', STATUS_SCRIPT))

    def commit(self):
        commit = self.hypr.read('version').get('commit')
        if not isinstance(commit, str) or not re.fullmatch(HASH, commit):
            raise RuntimeError('Cannot identify the running Hyprland build')
        return commit

    @staticmethod
    def supported(value):
        # The unpublished first interactive bridge cannot prove that its held
        # input cleanup filters have drained. Never unload that legacy code.
        return (value.get('protocol') == 1 and ((value.get('reloadProtocol') == 1 and value.get('hasPrepare') and value.get('hasCancel'))
                or (value.get('version') == '1.24.0' and not value.get('hasInteraction'))))

    def status(self):
        commit = self.commit()
        value = self.native()
        result = dict(ok=True, expectedVersion=self.expected, hyprlandHash=commit,
                      loadedVersion=value.get('version', ''), error='')
        if not value['available']:
            return dict(result, state='absent', canReload=False)
        if value['hyprlandHash'] != commit:
            raise RuntimeError('Loaded preview support belongs to another Hyprland build')
        current = value['version'] == self.expected and value['protocol'] == 1 and not value.get('reloadPending')
        supported = self.supported(value)
        return dict(result, state='current' if current else 'update-required', canReload=supported,
                    error='' if supported or current else
                    'Existing previews can keep working, but this older interactive bridge cannot be replaced safely. Log out and back in once; subsequent bridge updates support reloading here.')

    def checkpoint(self):
        if self.cancelled():
            raise RuntimeError('Preview support reload cancelled')
        if self.hypr.read('locked').get('locked') is not False:
            raise RuntimeError('Unlock the session before reloading preview support')

    def build(self, commit):
        self.report(dict(ok=True, state='building'))
        arguments = [sys.executable, str(ROOT/'tools/build-preview-bridge.py'),
                     '--cache-dir', str(self.cache), '--expected-hash', commit]
        with subprocess.Popen(arguments, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True, start_new_session=True) as process:
            try:
                deadline = time.monotonic()+120
                while True:
                    self.checkpoint()
                    if time.monotonic() >= deadline:
                        raise RuntimeError('Preview support build timed out; the loaded bridge was preserved')
                    try:
                        stdout, stderr = process.communicate(timeout=.2)
                        break
                    except subprocess.TimeoutExpired:
                        pass
            except BaseException:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.communicate(timeout=1)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.communicate()
                raise
        result = subprocess.CompletedProcess(arguments, process.returncode, stdout, stderr)
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()[-1600:]
            raise RuntimeError('Could not build preview support. The loaded bridge was preserved. '+detail)
        value = json.loads(result.stdout)
        path = Path(value.get('path', ''))
        fingerprint = value.get('fingerprint', '')
        expected = self.cache/commit/(self.expected+'-'+fingerprint)/'window-stash-preview.so'
        if (value.get('version') != self.expected or value.get('hyprlandHash') != commit
                or value.get('protocol') != 1 or not re.fullmatch(FINGERPRINT, fingerprint)
                or path != expected.absolute() or path.is_symlink() or not path.is_file()
                or path.resolve() != path.absolute() or any(c.isspace() for c in str(path))):
            raise RuntimeError('Preview support build returned an unverified binary')
        metadata = json.loads(path.with_suffix('.so.json').read_text())
        if metadata != dict(value, sha256=hashlib.sha256(path.read_bytes()).hexdigest()):
            raise RuntimeError('Preview support build failed its integrity check')
        return value

    def loaded_path(self, value, commit):
        plugins = json.loads(self.hypr.call('-j', 'plugin', 'list'))
        matches = [plugin for plugin in plugins if plugin.get('name') == 'window-stash-preview']
        if (len(matches) != 1 or matches[0].get('author') != 'artu-ole'
                or matches[0].get('version') != value['version']):
            raise RuntimeError('Could not verify ownership of the loaded preview bridge')
        root = (self.cache/commit).absolute()
        path = value.get('modulePath')
        if not path:
            signature = os.environ.get('HYPRLAND_INSTANCE_SIGNATURE', '')
            instances = json.loads(self.hypr.call('-j', 'instances'))
            pids = [item.get('pid') for item in instances if item.get('instance') == signature]
            if len(pids) != 1 or type(pids[0]) is not int or pids[0] <= 0:
                raise RuntimeError('Could not identify the compositor that owns preview support')
            paths = set()
            for line in Path('/proc/'+str(pids[0])+'/maps').read_text().splitlines():
                fields = line.split(None, 5)
                if len(fields) != 6:
                    continue
                candidate = re.sub(r'\\([0-7]{3})', lambda m: chr(int(m[1], 8)), fields[5].removesuffix(' (deleted)'))
                if candidate.startswith(str(root)+'/') and candidate.endswith('/window-stash-preview.so'):
                    paths.add(candidate)
            if len(paths) != 1:
                raise RuntimeError('Could not identify one owned preview bridge binary')
            path = paths.pop()
        path = Path(path)
        if (not path.is_absolute() or root not in path.parents or path.name != 'window-stash-preview.so'
                or '..' in path.parts or any(c.isspace() for c in str(path))
                or path.parent.resolve() != path.parent):
            raise RuntimeError('Refusing to unload preview support outside its owned cache')
        return path

    def wait_idle(self, original):
        self.report(dict(ok=True, state='stopping'))
        if original.get('hasPrepare'):
            self.hypr.eval('assert('+API+'.prepare_reload())')
        deadline = time.monotonic()+5
        while True:
            self.checkpoint()
            value = self.native()
            if (value.get('version'), value.get('hyprlandHash')) != (original['version'], original['hyprlandHash']):
                raise RuntimeError('Preview support changed during reload; try again')
            idle = value.get('owners') == 0 and value.get('windows') == 0 and not value.get('inputActive')
            if original.get('hasPrepare'):
                idle = idle and value.get('reloadPending') is True and value.get('reloadReady') is True
            if idle:
                return
            if time.monotonic() >= deadline:
                raise RuntimeError('Preview support is still in use. Release held keys and mouse buttons, then try again.')
            time.sleep(.05)

    def verify(self, built):
        deadline = time.monotonic()+2
        while True:
            value = self.native()
            if value['available']:
                if ((value.get('version'), value.get('hyprlandHash'), value.get('fingerprint'), value.get('modulePath')) != (
                        self.expected, built['hyprlandHash'], built['fingerprint'], built['path'])
                        or value.get('protocol') != 1 or value.get('reloadPending') is not False):
                    raise RuntimeError('The updated preview bridge did not load; old native code may still be retained')
                return
            if time.monotonic() >= deadline:
                raise RuntimeError('Updated preview support did not become available')
            time.sleep(.05)

    def reload(self):
        with bridge_gate(exclusive=True):
            self.checkpoint()
            initial = self.status()
            if initial['state'] == 'current':
                return dict(initial, state='ready')
            if initial['state'] == 'update-required' and not initial['canReload']:
                raise RuntimeError(initial['error'])
            original = self.native()
            commit = initial['hyprlandHash']
            if original['available'] and (original['version'] != initial['loadedVersion']
                    or original['hyprlandHash'] != commit or not self.supported(original)):
                raise RuntimeError('Preview support changed during reload; try again')
            old_path = self.loaded_path(original, commit) if original['available'] else None
            rollback = self.rollback_path(old_path, original, commit) if old_path else None
            built = self.build(commit)
            self.checkpoint()
            unloaded = False
            prepared = False
            try:
                if old_path:
                    prepared = bool(original.get('hasPrepare'))
                    self.wait_idle(original)
                    self.checkpoint()
                    if self.commit() != commit or self.loaded_path(self.native(), commit) != old_path:
                        raise RuntimeError('The running compositor or preview bridge changed during reload')
                    try:
                        self.hypr.call('plugin', 'unload', str(old_path))
                    except (RuntimeError, subprocess.SubprocessError):
                        # A timed-out IPC client can lose an otherwise
                        # successful unload acknowledgement. Reconcile before
                        # deciding whether to cancel or finish replacement.
                        if self.native()['available']:
                            raise
                    unloaded = True
                    if self.native()['available']:
                        raise RuntimeError('The old preview bridge did not unload')
                # Once unloaded, complete the verified load even if cancellation
                # arrives. Never leave replacement half-finished on shell exit.
                self.report(dict(ok=True, state='loading'))
                self.hypr.call('plugin', 'load', built['path'])
                self.verify(built)
            except BaseException as error:
                try:
                    if prepared and not unloaded:
                        self.hypr.eval('if hl.plugin and '+API+' and '+API+'.cancel_reload then '+API+'.cancel_reload() end')
                    elif unloaded and rollback and not self.native()['available']:
                        # Immutable artifacts can be restored without guessing
                        # at overwritten legacy binaries.
                        self.hypr.call('plugin', 'load', str(rollback))
                except (OSError, RuntimeError, subprocess.SubprocessError) as recovery:
                    raise RuntimeError(str(error)+'; preview support recovery failed: '+str(recovery)) from error
                raise
            return dict(ok=True, state='ready', expectedVersion=self.expected, loadedVersion=self.expected,
                        previousVersion=initial['loadedVersion'], hyprlandHash=commit, error='')

    @staticmethod
    def rollback_path(path, original, commit):
        try:
            metadata = json.loads(path.with_suffix('.so.json').read_text())
            if (path.is_symlink() or metadata.get('version') != original['version']
                    or metadata.get('hyprlandHash') != commit or metadata.get('path') != str(path)
                    or metadata.get('sha256') != hashlib.sha256(path.read_bytes()).hexdigest()
                    or (original.get('fingerprint') and metadata.get('fingerprint') != original['fingerprint'])):
                return None
            return path
        except (OSError, ValueError):
            return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('status', 'reload'))
    parser.add_argument('--watch-stdin', action='store_true', help='Cancel before unloading if the owning shell closes its pipe')
    args = parser.parse_args()
    cancelled = False
    def stop(_signal, _frame):
        nonlocal cancelled
        cancelled = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    def emit(value):
        try:
            print(json.dumps(value), flush=True)
        except BrokenPipeError:
            sys.stdout = open(os.devnull, 'w')
    def is_cancelled():
        if cancelled:
            return True
        if args.watch_stdin and select.select([sys.stdin], [], [], 0)[0]:
            return not os.read(sys.stdin.fileno(), 1024)
        return False
    try:
        manager = BridgeManager(emit=emit, cancelled=is_cancelled)
        if args.action == 'reload':
            emit(manager.reload())
        else:
            with bridge_gate():
                emit(manager.status())
        return 0
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        emit(dict(ok=False, state='busy' if str(error) == BUSY else 'error', error=str(error)[-2000:]))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
