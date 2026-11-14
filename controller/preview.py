#!/usr/bin/env python3
"""Keep only currently previewed, owned windows rendering; stdin owns the lease."""
import contextlib
import json
import os
from pathlib import Path
import re
import select
import signal
import subprocess
import sys
import time
import uuid

sys.dont_write_bytecode = True
from stash import Hyprland, PREFIX, SPECIAL, Stash, lua
from bridge_runtime import BUSY, bridge_gate

ROOT = Path(__file__).resolve().parents[1]
API = 'hl.plugin.window_stash_preview'
MISSING_API = 'Preview compatibility extension is unavailable'
RESTART_REQUIRED = 'Reload preview support in Window Stash Settings to use the updated extension'
PROBE = ('if not (hl.plugin and ' + API + ' and type(' + API
         + ".update) == 'function' and type(" + API
         + ".status) == 'function') then error('Preview compatibility extension is unavailable') end\n"
         + 'local info=' + API + ".status(); if type(info) ~= 'table' or info.protocol ~= 1 then error('"
         + RESTART_REQUIRED + "') end\n")
MAX_REQUEST = 65536
MAX_WINDOWS = 128
RENEW_SECONDS = .5


def request_ids(value):
    if (not isinstance(value, list) or len(value) > MAX_WINDOWS
            or any(not isinstance(item, str) or not re.fullmatch(r'[0-9a-f]{32}', item) for item in value)):
        raise ValueError('Preview requests must contain at most 128 stash record IDs')
    return sorted(set(value))


def preview_records(records, clients, wanted, exclude_folded=True):
    """Do not acquire a native lease from a stale UI snapshot alone."""
    result = []
    for record in records:
        ident = record.get('id')
        if (ident not in wanted or record.get('phase') != 'stashed'
                or (exclude_folded and record.get('previewFolded') is True)
                or record.get('tag') != PREFIX + ident):
            continue
        candidates = [client for client in clients if client.get('address') == record.get('address')]
        if len(candidates) != 1:
            continue
        client = candidates[0]
        pid = record.get('pid')
        stable = record.get('stableId') or client.get('stableId')
        if (not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0
                or not isinstance(record.get('address'), str)
                or not re.fullmatch(r'0x[0-9a-fA-F]+', record['address'])
                or not isinstance(stable, str) or not re.fullmatch(r'(?:0x)?[0-9a-fA-F]+', stable)
                or client.get('pid') != pid or client.get('mapped') is not True
                or (record.get('stableId') and record['stableId'] != client.get('stableId'))
                or client.get('workspace', {}).get('name') != SPECIAL
                or not isinstance(client.get('tags'), list)
                or record['tag'] not in client.get('tags', [])):
            continue
        result.append(dict(id=ident, address=record['address'], pid=pid,
                           stable_id=stable, tag=record['tag']))
    return sorted(result, key=lambda record: record['id'])


class PreviewBridge:
    def __init__(self, hypr=None, progress=None, cancelled=None):
        self.hypr = hypr or Hyprland()
        self.progress = progress or (lambda value: None)
        self.cancelled = cancelled or (lambda: False)
        self.version = (ROOT/'native/version.txt').read_text().strip()
        if not re.fullmatch(r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)', self.version):
            raise RuntimeError('Invalid native preview bridge version in native/version.txt')
        versions = [self.version]
        # Keep the known ordinary render/input API usable during a deferred
        # bridge update. New features still require their own capability guard;
        # an older bridge must never silently turn contained fullscreen into
        # desktop fullscreen. Unknown future implementations remain exact-only.
        compatible = {'1.29.2': ('1.29.1',), '1.29.3': ('1.29.1', '1.29.2'),
                      '1.29.4': ('1.29.1', '1.29.2', '1.29.3'),
                      '1.29.5': ('1.29.1', '1.29.2', '1.29.3', '1.29.4'),
                      '1.29.6': ('1.29.1', '1.29.2', '1.29.3', '1.29.4', '1.29.5'),
                      '1.29.7': ('1.29.1', '1.29.2', '1.29.3', '1.29.4', '1.29.5', '1.29.6'),
                      '1.29.8': ('1.29.1', '1.29.2', '1.29.3', '1.29.4', '1.29.5', '1.29.6', '1.29.7'),
                      '1.29.9': ('1.29.1', '1.29.2', '1.29.3', '1.29.4', '1.29.5', '1.29.6', '1.29.7', '1.29.8')}
        versions.extend(compatible.get(self.version, ()))
        self.probe = PROBE + 'if not (' + ' or '.join('info.version == '+lua(value) for value in versions) + ") then error('" + RESTART_REQUIRED + "') end\n"
        self.ready = False
        self.generation = 0
        self.binary_path = None

    def operation(self):
        # Test doubles do not connect to a compositor or need a session lock.
        return bridge_gate() if isinstance(self.hypr, Hyprland) else contextlib.nullcontext()

    def ensure(self):
        with self.operation():
            self._ensure()

    def _ensure(self):
        if self.cancelled():
            raise PreviewStopped()
        if self.ready:
            return
        try:
            self.hypr.eval(self.probe)
        except RuntimeError as error:
            if RESTART_REQUIRED in str(error):
                raise
            version = self.hypr.read('version')
            commit = version.get('commit', '')
            if not isinstance(commit, str) or not re.fullmatch(r'[0-9a-f]{40}', commit):
                raise RuntimeError('Cannot identify the running Hyprland build for preview compatibility')
            cache = Path(os.environ.get('XDG_CACHE_HOME', Path.home()/'.cache'))
            directory = cache/'omarchy/window-stash/preview-bridge'
            self.progress(dict(state='building', ids=[]))
            process = subprocess.run([sys.executable, str(ROOT/'tools/build-preview-bridge.py'),
                                      '--cache-dir', str(directory), '--expected-hash', commit],
                                     capture_output=True, text=True, timeout=120)
            if process.returncode:
                detail = (process.stderr or process.stdout).strip()[-1600:]
                raise RuntimeError('Could not build live preview support. Install matching Hyprland headers and a C++ compiler. '+detail)
            metadata = json.loads(process.stdout)
            fingerprint = metadata.get('fingerprint', '')
            output = directory/commit/(self.version+'-'+fingerprint)/'window-stash-preview.so'
            if (metadata.get('hyprlandHash') != commit or metadata.get('protocol') != 1
                    or not re.fullmatch(r'[0-9a-f]{64}', fingerprint)
                    or metadata.get('path') != str(output.absolute()) or metadata.get('version') != self.version):
                raise RuntimeError('Preview compatibility build does not match the running compositor')
            if self.cancelled():
                raise PreviewStopped()
            self.progress(dict(state='loading', ids=[]))
            self.hypr.call('plugin', 'load', str(output))
            self.binary_path = output
            # Loading schedules a compositor configuration refresh. The Lua
            # namespace may attach on the next event-loop iteration.
            deadline = time.monotonic()+2
            while True:
                try:
                    self.hypr.eval(self.probe)
                    break
                except RuntimeError as error:
                    if RESTART_REQUIRED in str(error) or time.monotonic() >= deadline:
                        raise
                    time.sleep(.05)
        self.ready = True
        self.generation += 1

    def update(self, owner, records):
        with self.operation():
            self._update(owner, records)

    def _update(self, owner, records):
        windows = ','.join('{' + ','.join(key+'='+lua(value) for key, value in record.items()) + '}' for record in records)
        script = (self.probe + 'local result,err=' + API + '.update({owner=' + lua(owner)
                  + ',windows={' + windows + '}}); assert(result,err); '
                  + 'assert(result.accepted==' + str(len(records))
                  + ", 'Preview source changed before the compatibility lease was acquired')")
        try:
            self.hypr.eval(script)
        except RuntimeError as error:
            # A compositor reload unloads runtime-only plugins. Rebuild/reload
            # from the validated cache once, preserving this helper's owner.
            # Identity rejection and protocol/version mismatches are not retryable.
            if MISSING_API not in str(error):
                raise
            self.ready = False
            self.ensure()
            self.hypr.eval(script)

    def release(self, owner):
        self.hypr.eval('if hl.plugin and ' + API + ' then ' + API + '.release(' + lua(owner) + ') end')


class PreviewKeeper:
    def __init__(self, stash=None, bridge=None):
        self.stash = stash or Stash()
        self.bridge = bridge or PreviewBridge(self.stash.hypr)
        self.owner = uuid.uuid4().hex
        self.acquired = False

    def _matches_locked(self, wanted):
        settings = self.stash.settings()
        live_source = (settings['hoverPreview'] == 'live'
                       or (settings['presentation'] == 'previews'
                           and settings['floatingPreviewUpdate'] in ('hover', 'live')))
        enabled = live_source and settings['livePreviewCompatibility'] == 'enhanced'
        records = list(self.stash.state['windows']) if enabled else []
        matches = preview_records(records, self.stash.hypr.read('clients'), wanted,
                                  exclude_folded=settings['presentation'] == 'previews') if records and wanted else []
        return enabled, matches

    def sync(self, wanted):
        wanted = request_ids(wanted)
        with self.stash.locked():
            enabled, matches = self._matches_locked(wanted)
        if matches:
            self.bridge.ensure()
            # Native preparation may compile/load for a while. Recheck folding,
            # source identity and policy, then serialize the final update with
            # fold commits so a stale helper cannot revive a hidden capture.
            with self.bridge.operation() if isinstance(self.bridge, PreviewBridge) else contextlib.nullcontext(), self.stash.locked():
                enabled, matches = self._matches_locked(wanted)
                if matches:
                    self.acquired = True
                    self.bridge.update(self.owner, matches)
                    return dict(state='ready', ids=[record['id'] for record in matches])
        self.close()
        return dict(state='idle' if enabled else 'disabled', ids=[])

    def close(self):
        if self.acquired:
            try:
                self.bridge.release(self.owner)
            finally:
                self.acquired = False


class PreviewStopped(BaseException):
    pass


def run_loop(stream, keeper, emit):
    buffer = b''
    wanted = []
    previous = None
    previous_generation = None
    try:
        while True:
            readable, _, _ = select.select([stream], [], [], RENEW_SECONDS)
            if readable:
                chunk = os.read(stream.fileno(), 8192)
                if not chunk:
                    return 0
                buffer += chunk
                if len(buffer) > MAX_REQUEST:
                    raise ValueError('Preview request exceeded the input limit')
                while b'\n' in buffer:
                    line, buffer = buffer.split(b'\n', 1)
                    wanted = request_ids(json.loads(line))
            try:
                status = keeper.sync(wanted)
            except RuntimeError as error:
                if str(error) != BUSY:
                    raise
                keeper.close()
                status = dict(state='paused', ids=[])
            generation = getattr(keeper.bridge, 'generation', 0)
            if status != previous or generation != previous_generation:
                emit(status)
                previous = status
                previous_generation = generation
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
    bridge = PreviewBridge(progress=emit, cancelled=lambda: bool(disconnected.poll(0)))
    keeper = PreviewKeeper(bridge=bridge)
    try:
        return run_loop(sys.stdin.buffer, keeper, emit)
    except PreviewStopped:
        return 0
    except Exception as error:
        emit(dict(state='unavailable', ids=[], error=str(error)))
        return 1


if __name__ == '__main__':
    sys.exit(main())
