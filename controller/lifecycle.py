#!/usr/bin/env python3
"""Own runtime integration and recover parked windows when the plugin is removed.

The guardian preloads its code, then outlives Quickshell's immediate Process.
Removing a Git checkout cannot race a later attempt to execute its cleanup file.
"""
import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import select
import signal
import socket
import subprocess
import sys
import time
import uuid

sys.dont_write_bytecode = True
from stash import CHOICES, DEFAULTS, PLUGIN, PREFIX, Stash, atomic_json, lua
import shortcuts

# Import migration while the checkout still exists. Cleanup uses only code
# already loaded here and in stash/shortcuts; it never imports from that path.
try:
    import migration
except ImportError:
    migration = None

ROOT = Path(__file__).resolve().parents[1]
MAX_MESSAGE = 65536
POLL_SECONDS = .5
DISABLE_GRACE = .35


def bounded_json(path, limit=MAX_MESSAGE):
    with path.open(encoding="utf-8") as stream:
        text = stream.read(limit + 1)
    if len(text) > limit:
        raise ValueError("Window Stash configuration is too large")
    return json.loads(text)


def valid_preferences(value):
    """Keep only validated preferences; checkpoint data is never executable."""
    if not isinstance(value, dict):
        raise ValueError("Window Stash preferences must be an object")
    result = {}
    for key in DEFAULTS:
        if key not in value:
            continue
        item = value[key]
        if key in shortcuts.DEFAULT_SHORTCUTS:
            try:
                result[key] = shortcuts.normalize(item)
            except ValueError:
                continue
        elif key in CHOICES and ((not isinstance(CHOICES[key], range) or type(item) is int)
                                and item in CHOICES[key]):
            result[key] = item
    return result


class LifecycleKeeper:
    def __init__(self, owner=None, stash=None, root=None, emit=None, migrate=None, notifier=None):
        self.owner = owner or uuid.uuid4().hex
        shortcuts._owner(self.owner)
        self.stash = stash or Stash()
        self.root = Path(root) if root is not None else ROOT
        self.emit = emit or (lambda value: None)
        self.notifier = notifier or (lambda: None)
        self.migrate = migrate if migrate is not None else (migration.migrate if migration else None)
        self.owner_path = self.stash.directory / "lifecycle-owner.json"
        self.lock_path = self.stash.directory / "lifecycle.lock"
        self.preferences_path = self.stash.positions.parent / "preferences.json"
        self.error_path = self.stash.positions.parent / "lifecycle-error.json"
        self.started = False
        self.initialized = False
        self.inactive_since = None
        self.last_settings = None
        self.pending_settings = None
        self.pending_until = 0
        self.last_shortcuts = None
        self.last_result = None

    @contextmanager
    def locked(self):
        self.stash.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.lock_path.open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def owns(self):
        try:
            marker = bounded_json(self.owner_path)
        except (OSError, ValueError):
            return False
        return isinstance(marker, dict) and marker.get("owner") == self.owner

    def configuration(self):
        if not (self.root / "manifest.json").is_file():
            return "removed", None
        try:
            data = bounded_json(self.stash.config, limit=4 * 1024 * 1024)
        except (OSError, ValueError):
            # An in-progress/manual config edit must never restore windows.
            return "unknown", None
        if not isinstance(data, dict) or not isinstance(data.get("plugins"), list):
            return "unknown", None
        entries = [entry for entry in data["plugins"]
                   if isinstance(entry, dict) and entry.get("id") == PLUGIN]
        if len(entries) > 1:
            return "unknown", None
        disabled = data.get("disabledPlugins")
        if not entries or isinstance(disabled, list) and PLUGIN in disabled:
            return "disabled", entries[0] if entries else None
        return "enabled", entries[0]

    def restore_preferences(self):
        try:
            saved = bounded_json(self.preferences_path)
            values = valid_preferences(saved["settings"]) if saved.get("version") == 1 else {}
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return
        with shortcuts._locked(self.stash.config):
            data, entry = shortcuts._read(self.stash.config)
            disabled = data.get("disabledPlugins")
            if isinstance(disabled, list) and PLUGIN in disabled:
                return
            additions = {key: value for key, value in values.items() if key not in entry}
            if additions:
                entry.update(additions)
                shortcuts._atomic_json(self.stash.config, data)

    def checkpoint(self, values=None):
        if values is None:
            state, entry = self.configuration()
            if state != "enabled":
                return
            values = valid_preferences(entry)
            # Canonical defaults make an id-only first installation persist
            # all choices, while explicit empty shortcuts remain empty.
            values = dict(DEFAULTS, **values)
            if self.pending_settings is not None:
                if values == self.pending_settings or time.monotonic() >= self.pending_until:
                    self.pending_settings = None
                else:
                    # The host can acknowledge QML before its atomic file
                    # save lands. Keep the newer pipe snapshot until then.
                    return
        else:
            values = valid_preferences(values)
            if not values:
                return
            values = dict(self.last_settings or DEFAULTS, **values)
            self.pending_settings = values
            self.pending_until = time.monotonic() + 2
        if values != self.last_settings:
            atomic_json(self.preferences_path, dict(version=1, settings=values))
            self.last_settings = values

    def _runner(self, *args):
        return self.stash.hypr.call(*args)

    def _sync_locked(self):
        shortcuts.claim(self.owner, self.stash.config, self._runner)
        result = shortcuts.sync(self.stash.config, self._runner, owner=self.owner)
        self.last_shortcuts = shortcuts.settings(self.configuration()[1])
        self.last_result = result
        return result

    def _migration(self):
        if not self.migrate:
            return {}
        monitors = self.stash.hypr.read("monitors")
        bindings = self.stash.config.parent.parent / "hypr/bindings.lua"
        def binding_bytes():
            try:
                return bindings.read_bytes()
            except FileNotFoundError:
                return None
        before = binding_bytes()
        # Subscribe before changing the legacy included file, so either its
        # watcher reload or our explicit reload can be acknowledged safely.
        events = None
        try:
            signature = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
            runtime = os.environ.get("XDG_RUNTIME_DIR")
            if signature and runtime:
                events = socket.socket(socket.AF_UNIX)
                events.settimeout(5)
                events.connect(str(Path(runtime) / "hypr" / signature / ".socket2.sock"))
            result = {}
            try:
                result = self.migrate(plugin_root=self.root)
            finally:
                # A later migration edit can fail after the included file
                # was already replaced; preserve scaling on that path too.
                changed = result.get("bindingsChanged") or binding_bytes() != before
                if changed:
                    self._reload_preserving_monitors(monitors, events)
            return result
        finally:
            if events is not None:
                events.close()

    def _reload_preserving_monitors(self, monitors, events):
        self.stash.hypr.call("reload")
        if events is not None:
            data = b""
            while b"configreloaded>>" not in data:
                chunk = events.recv(65536)
                if not chunk:
                    raise RuntimeError("Hyprland closed the migration reload event socket")
                data += chunk
        for monitor in monitors:
            self.stash.hypr.eval('hl.monitor({output=%s,mode=%s,position=%s,scale=%s,transform=%s})' % (
                lua(monitor["name"]), lua('%dx%d@%.2f' % (monitor["width"], monitor["height"], monitor["refreshRate"])),
                lua('%dx%d' % (monitor["x"], monitor["y"])), monitor["scale"], monitor["transform"]))
        errors = self.stash.hypr.call("configerrors")
        if errors:
            raise RuntimeError(errors)
        deadline = time.monotonic() + 5
        while True:
            current = {m["name"]: m for m in self.stash.hypr.read("monitors")}
            keys = ("width", "height", "scale", "x", "y", "transform")
            if all(m["name"] in current and all(current[m["name"]][key] == m[key] for key in keys)
                   for m in monitors):
                return
            if time.monotonic() >= deadline:
                raise RuntimeError("The runtime display profile was not restored after legacy migration")
            time.sleep(.05)

    def start(self):
        with self.locked():
            atomic_json(self.owner_path, dict(owner=self.owner, pid=os.getpid()))
            self.started = True
            state, _ = self.configuration()
            if state != "enabled":
                return self._cleanup_locked() if state in ("disabled", "removed") else {"state": "waiting"}
            return self._activate_locked()

    def _activate_locked(self):
        migration_result = self._migration()
        self.restore_preferences()
        self.checkpoint()
        result = self._sync_locked()
        self.initialized = True
        value = dict(state="ready", owner=self.owner, activeShortcuts=result.get("activeShortcuts", {}),
                     conflicts=result.get("conflicts", {}), warnings=migration_result.get("warnings", []))
        self.emit(value)
        return value

    def update(self, message=None):
        with self.locked():
            if not self.owns():
                return {"state": "superseded"}
            # Host disable/remove deletes the entry before the process pipe
            # drains. Save an already committed UI snapshot before looking
            # at that now-missing entry, and process every queued message.
            if isinstance(message, dict) and isinstance(message.get("settings"), dict):
                self.checkpoint(message["settings"])
            state, _ = self.configuration()
            if state in ("disabled", "removed"):
                now = time.monotonic()
                if self.inactive_since is None:
                    self.inactive_since = now
                if now - self.inactive_since < DISABLE_GRACE:
                    return {"state": "waiting"}
                return self._cleanup_locked()
            self.inactive_since = None
            if state == "unknown":
                return {"state": "waiting"}
            if not self.initialized:
                return self._activate_locked()
            self.checkpoint()
            force = isinstance(message, dict) and message.get("action") == "sync"
            desired = shortcuts.settings(self.configuration()[1])
            if force or desired != self.last_shortcuts:
                result = self._sync_locked()
                value = dict(state="ready", owner=self.owner, activeShortcuts=result.get("activeShortcuts", {}),
                             conflicts=result.get("conflicts", {}), warnings=[])
                self.emit(value)
                return value
            return {"state": "active"}

    def _cleanup_locked(self):
        if not self.owns():
            return {"state": "superseded"}
        state, _ = self.configuration()
        if state not in ("disabled", "removed"):
            return {"state": "preserved"}
        errors = []
        try:
            # The runtime marker is authoritative and the lifecycle lock
            # excludes a successor. A compositor reload can reset Lua's
            # owner before deferred bootstrap creates unowned handles, so
            # release every exact handle in our manager on true removal.
            shortcuts.disable(self.stash.config, self._runner)
        except (OSError, RuntimeError, ValueError) as error:
            errors.append(str(error))
        # This guard's runtime marker is still current under the shared lock.
        # A successor cannot be claiming new observer handles concurrently.
        try:
            self.stash.hypr.eval('local s=_community_window_stash_clicks; if s then s.tracking=false; '
                's.watching=false; s.held={}; if s.timer then s.timer:set_enabled(false) end; '
                'for _,b in ipairs(s.binds or {}) do b:set_enabled(false) end end')
        except (OSError, RuntimeError) as error:
            errors.append(str(error))
        active = None
        monitors = []
        try:
            active = self.stash.hypr.read("activewindow")
            monitors = self.stash.hypr.read("monitors")
        except (OSError, RuntimeError, ValueError):
            pass
        restored = 0
        pending = 0
        try:
            for attempt in range(3):
                attempt_errors = []
                with self.stash.locked():
                    pending = len(self.stash.state["windows"])
                    clients = self.stash.hypr.read("clients")
                    live = {client["address"]: client for client in clients}
                    promoted = False
                    for record in self.stash.state["windows"]:
                        client = live.get(record.get("address"))
                        ident = record.get("id")
                        if (record.get("phase") == "preparing" and isinstance(ident, str)
                                and record.get("tag") == PREFIX + ident
                                and self.stash.matches(record, client)
                                and record["tag"] in client.get("tags", [])):
                            # QML can be destroyed after tagging/fullscreen
                            # clearing but before moving the client away.
                            record["phase"] = "restoring"
                            promoted = True
                    if promoted:
                        self.stash.save()
                    self.stash.reconcile(clients)
                    records = list(self.stash.state["windows"])
                    for record in records:
                        try:
                            result = self.stash.restore(record["id"], "original", expected=dict(record))
                            restored += int(result.get("action") == "restored")
                        except (OSError, RuntimeError, ValueError, KeyError) as error:
                            attempt_errors.append(str(error))
                    pending = len(self.stash.state["windows"])
                if not pending:
                    break
                if attempt < 2:
                    time.sleep(.2)
                else:
                    errors.extend(attempt_errors or ["Some stashed windows could not be restored"])
        except (OSError, RuntimeError, ValueError, KeyError) as error:
            errors.append(str(error))
        finally:
            try:
                current = {m["name"]: m for m in self.stash.hypr.read("monitors")}
                for monitor in monitors:
                    if monitor["name"] not in current:
                        continue
                    self.stash.hypr.dispatch("focus", monitor=monitor["name"])
                    self.stash.hypr.dispatch("focus", workspace=Stash.workspace_selector(monitor["activeWorkspace"]))
                focused = next((m for m in monitors if m.get("focused")), None)
                if focused and focused["name"] in current:
                    self.stash.hypr.dispatch("focus", monitor=focused["name"])
                if active and active.get("address"):
                    client = self.stash.hypr.client(active["address"])
                    if self.stash.matches(active, client):
                        self.stash.hypr.dispatch("focus", window="address:" + active["address"])
            except (OSError, RuntimeError, ValueError, KeyError) as error:
                errors.append("Could not restore desktop focus: " + str(error))
        value = dict(state="error" if errors else "cleaned", owner=self.owner, restored=restored, remaining=pending)
        if errors:
            value["error"] = "; ".join(dict.fromkeys(errors))
            try:
                atomic_json(self.error_path, value)
            finally:
                try:
                    self.notifier()
                except Exception:
                    # Notification availability must not mask the saved
                    # recovery error or interfere with the window ledger.
                    pass
        else:
            self.error_path.unlink(missing_ok=True)
        self.emit(value)
        return value

    def recover_after_error(self):
        """A removal racing startup must still use the preloaded cleanup.

        Startup already replaced the ownership marker, so the previous
        generation can no longer recover these windows on our behalf.
        """
        if not self.started:
            return None
        with self.locked():
            if not self.owns():
                return {"state": "superseded"}
            state, _ = self.configuration()
            if state in ("disabled", "removed"):
                return self._cleanup_locked()
        return None


def run_loop(stream, keeper, stopped=lambda: False):
    """EOF preserves an enabled stash, while the guardian watches for removal.

    A replacement generation takes ownership and ends this one. This also
    handles a shell crash followed by removal before the shell can restart.
    """
    initial = keeper.start()
    if initial.get("state") in ("cleaned", "error", "superseded"):
        return initial
    buffer = b""
    connected = True
    while True:
        messages = []
        if stopped():
            with keeper.locked():
                return keeper._cleanup_locked()
        if connected:
            readable, _, _ = select.select([stream], [], [], POLL_SECONDS)
            if readable:
                chunk = os.read(stream.fileno(), 8192)
                if not chunk:
                    connected = False
                else:
                    buffer += chunk
                    if len(buffer) > MAX_MESSAGE:
                        raise ValueError("Lifecycle request exceeded the size limit")
                    lines = buffer.split(b"\n")
                    buffer = lines.pop()
                    for line in lines:
                        if line:
                            value = json.loads(line)
                            if not isinstance(value, dict):
                                raise ValueError("Lifecycle requests must be objects")
                            messages.append(value)
        else:
            time.sleep(POLL_SECONDS)
        for message in messages or [None]:
            result = keeper.update(message)
            if result.get("state") in ("cleaned", "error", "superseded"):
                return result


def emit(value):
    try:
        print(json.dumps(value), flush=True)
    except (BrokenPipeError, OSError):
        # The Qt object may already have been deleted. Cleanup still owns its
        # private state/error file and must not depend on an output listener.
        pass


def notify_failure():
    """Notify the desktop owner without exposing window data or local paths."""
    try:
        subprocess.run(["notify-send", "--app-name=Window Stash", "--expire-time=10000",
                        "Window Stash recovery needs attention",
                        "Reinstall or enable Window Stash to recover remaining windows. Details are saved locally."],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3, check=False)
    except (OSError, subprocess.SubprocessError):
        pass


def guardian(owner):
    stopped = [False]
    def stop(_signal, _frame):
        stopped[0] = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    keeper = LifecycleKeeper(owner=owner, emit=emit, notifier=notify_failure)
    try:
        result = run_loop(sys.stdin.buffer, keeper, lambda: stopped[0])
        return int(result.get("state") == "error")
    except (OSError, RuntimeError, ValueError, KeyError) as error:
        try:
            recovered = keeper.recover_after_error()
            if recovered is not None:
                return int(recovered.get("state") == "error")
        except (OSError, RuntimeError, ValueError, KeyError) as recovery_error:
            error = RuntimeError(str(error) + "; cleanup also failed: " + str(recovery_error))
        emit(dict(state="error", owner=owner, error=str(error)))
        print("Window Stash lifecycle: " + str(error), file=sys.stderr, flush=True)
        return 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", default=uuid.uuid4().hex)
    parser.add_argument("--foreground", action="store_true", help="Run the guardian directly for diagnostics")
    args = parser.parse_args()
    shortcuts._owner(args.owner)
    os.umask(0o077)
    if args.foreground:
        return guardian(args.owner)
    child = os.fork()
    if child == 0:
        os.setsid()
        os._exit(guardian(args.owner))
    # Qt owns this transport PID, while the setsid guardian retains the pipe.
    # Killing the immediate Process cannot interrupt directory-deletion cleanup.
    os.close(0)
    while True:
        try:
            _, status = os.waitpid(child, 0)
            return os.waitstatus_to_exitcode(status)
        except InterruptedError:
            continue


if __name__ == "__main__":
    raise SystemExit(main())
