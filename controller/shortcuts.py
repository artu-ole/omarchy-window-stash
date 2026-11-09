"""Validated, persistent Window Stash shortcuts with exact runtime ownership."""
import argparse
from contextlib import contextmanager
from collections import Counter
import fcntl
import json
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess
import sys
import tempfile


PLUGIN = "community.window-stash"
DEFAULT_SHORTCUTS = {"minimizeShortcut": "SUPER + A", "restoreLastShortcut": "SUPER + Z",
                     "restoreOldestShortcut": ""}
ACTIONS = {"minimizeShortcut": ("minimize", "Window Stash: minimize focused window"),
           "restoreLastShortcut": ("restore-last", "Window Stash: restore last minimized"),
           "restoreOldestShortcut": ("restore-oldest", "Window Stash: restore oldest minimized")}
MODIFIERS = {"SUPER": 64, "CTRL": 4, "ALT": 8, "SHIFT": 1}
MODIFIER_ALIASES = {"SUPER": "SUPER", "WIN": "SUPER", "META": "SUPER", "LOGO": "SUPER", "MOD4": "SUPER",
                    "CTRL": "CTRL", "CONTROL": "CTRL", "ALT": "ALT", "MOD1": "ALT", "SHIFT": "SHIFT"}
KEYS = {key.lower(): key for key in (
    "Escape", "Return", "Tab", "space", "BackSpace", "Delete", "Insert", "Home", "End", "Left", "Right", "Up", "Down",
    "Page_Up", "Page_Down", "Print", "Pause", "Menu", "Caps_Lock", "Num_Lock", "Scroll_Lock", "plus", "minus", "equal",
    "bracketleft", "bracketright", "backslash", "semicolon", "apostrophe", "comma", "period", "slash", "grave",
    "KP_Enter", "KP_Add", "KP_Subtract", "KP_Multiply", "KP_Divide", "KP_Decimal", "KP_Home", "KP_End", "KP_Left",
    "KP_Right", "KP_Up", "KP_Down", "KP_Page_Up", "KP_Page_Down", "KP_Insert", "KP_Delete",
    "XF86AudioMute", "XF86AudioLowerVolume", "XF86AudioRaiseVolume", "XF86AudioPlay", "XF86AudioPause", "XF86AudioStop",
    "XF86AudioNext", "XF86AudioPrev", "XF86HomePage", "XF86Search", "XF86Calculator", "XF86Mail")}
KEYS.update({str(i): str(i) for i in range(10)})
KEYS.update({"kp_"+str(i): "KP_"+str(i) for i in range(10)})
KEYS.update({"enter": "Return", "esc": "Escape", "spacebar": "space", "backspace": "BackSpace", "del": "Delete",
             "ins": "Insert", "pageup": "Page_Up", "pagedown": "Page_Down", "pgup": "Page_Up", "pgdn": "Page_Down",
             "prior": "Page_Up", "next": "Page_Down", "-": "minus", "=": "equal", "[": "bracketleft",
             "]": "bracketright", "\\": "backslash", ";": "semicolon", "'": "apostrophe", ",": "comma",
             ".": "period", "/": "slash", "`": "grave"})


def normalize(value):
    """Return one canonical Hyprland chord, or an empty disabled shortcut."""
    if not isinstance(value, str) or len(value) > 96 or any(ord(c) < 32 or ord(c) > 126 for c in value):
        raise ValueError("Use a shortcut such as SUPER + SHIFT + A, or leave it empty")
    value = value.strip()
    if not value:
        return ""
    parts = [part.strip() for part in value.split("+")]
    if not all(parts):
        raise ValueError("Separate modifiers and one key with +; use 'plus' for the plus key")
    modifiers = []
    for part in parts[:-1]:
        modifier = MODIFIER_ALIASES.get(part.upper())
        if not modifier or modifier in modifiers:
            raise ValueError("Use each of SUPER, CTRL, ALT and SHIFT at most once, followed by one key")
        modifiers.append(modifier)
    last = parts[-1]
    if len(last) == 1 and last.isalpha():
        key = last.upper()
    elif re.fullmatch(r"F(?:[1-9]|1[0-9]|2[0-4])", last.upper()):
        key = last.upper()
    else:
        key = KEYS.get(last.lower())
    if not key:
        raise ValueError("Choose a letter, digit, F1–F24, or a named keyboard key")
    return " + ".join([m for m in MODIFIERS if m in modifiers] + [key])


def settings(entry):
    """Read new and legacy plugin entries without losing valid disabled values."""
    result = {}
    entry = entry if isinstance(entry, dict) else {}
    for key, default in DEFAULT_SHORTCUTS.items():
        try:
            result[key] = normalize(entry.get(key, default))
        except ValueError:
            result[key] = default
    return result


def _identity(binding):
    return (str(binding.get("dispatcher", "")), str(binding.get("arg", "")), binding.get("description", ""),
            binding.get("modmask"), str(binding.get("key", "")).lower(), binding.get("submap", ""))


def validate(values, bindings=(), owned=()):
    """Reject duplicates and foreign bindings before changing config or handles.

    Hyprland 0.56's bind JSON does not expose enabled state. Unknown foreign
    entries are therefore reserved conservatively; our exact cached handles
    include their identities, including disabled historical choices.
    """
    values = {key: normalize(values.get(key, default)) for key, default in DEFAULT_SHORTCUTS.items()}
    occupied = {}
    own = Counter(_identity(binding) for binding in owned)
    foreign = []
    for binding in bindings:
        if not isinstance(binding, dict):
            continue
        identity = _identity(binding)
        if own[identity]:
            own[identity] -= 1
        else:
            foreign.append(binding)
    for key, chord in values.items():
        if not chord:
            continue
        if chord in occupied:
            raise ValueError("Shortcut " + chord + " is already used by another Window Stash action")
        occupied[chord] = key
        parts = chord.split(" + ")
        modmask = sum(MODIFIERS[m] for m in parts[:-1])
        for binding in foreign:
            if binding.get("enabled") is False or binding.get("disabled") is True:
                continue
            universal = binding.get("submap_universal") in (True, "true", "1", 1)
            if binding.get("submap", "") not in ("", "reset") and not universal:
                continue
            if binding.get("modmask") != modmask or str(binding.get("key", "")).lower() != parts[-1].lower():
                continue
            description = binding.get("description") or "another desktop action"
            raise ValueError("Shortcut " + chord + " is already assigned to " + description)
    return values


def _lua(value):
    return '"' + ''.join('\\%03d' % b if b < 32 or b >= 127 else
                          '\\' + chr(b) if b in (34, 92) else chr(b) for b in str(value).encode()) + '"'


def lua_source(values):
    """Export only generated literal data, never config strings as Lua code."""
    values = validate(values)
    return "{" + ",".join(key + "=" + _lua(values[key]) for key in DEFAULT_SHORTCUTS) + "}"


def _run(*args):
    try:
        result = subprocess.run(["hyprctl", *args], text=True, capture_output=True, timeout=8)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError("Could not contact Hyprland to update shortcuts") from error
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Shortcut IPC failed")
    return result.stdout.strip()


def _module():
    return "local m=assert(loadfile(" + _lua(Path(__file__).with_suffix(".lua")) + "))('runtime'); "


def _runtime(runner):
    raw = runner("repl", _module() + "return m.inspect()")
    try:
        owned = json.loads(raw)
        binds = json.loads(runner("binds", "-j"))
    except (TypeError, ValueError) as error:
        raise RuntimeError("Could not read current keyboard shortcuts") from error
    if not isinstance(owned, list) or not isinstance(binds, list):
        raise RuntimeError("Could not read current keyboard shortcuts")
    return binds, owned


def runtime_state(runner=None):
    """Return bind JSON plus the exact identities registered by this manager."""
    return _runtime(runner or _run)


def _apply(values, runner, binary=None):
    binary = Path(binary) if binary is not None else Path.home()/".local/bin/window-stash"
    output = runner("eval", _module() + "m.apply(" + lua_source(values) + "," + _lua(str(binary)) + ")")
    if output != "ok":
        raise RuntimeError(output or "Could not apply keyboard shortcuts")


def _config_path(path=None):
    if path is None:
        path = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home()/".config")/"omarchy/shell.json"
    return Path(path).resolve()


def _read(path):
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as error:
        raise RuntimeError("Could not read Omarchy settings") from error
    if not isinstance(data, dict) or not isinstance(data.get("plugins"), list):
        raise RuntimeError("Omarchy settings do not contain a plugin list")
    entries = [entry for entry in data["plugins"] if isinstance(entry, dict) and entry.get("id") == PLUGIN]
    if len(entries) != 1:
        raise RuntimeError("Window Stash must be installed before configuring shortcuts")
    return data, entries[0]


@contextmanager
def _locked(path):
    # Shared by settings edits and the asynchronous login/reload bootstrap.
    with (path.parent/".window-stash-shortcuts.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def _atomic_json(path, data):
    mode = stat.S_IMODE(path.stat().st_mode)
    descriptor, temporary = tempfile.mkstemp(prefix=".window-stash-shortcuts-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as stream:
            os.fchmod(stream.fileno(), mode)
            json.dump(data, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def configure(config_path, key, value, runner=None, binary=None):
    if key not in DEFAULT_SHORTCUTS:
        raise ValueError("Unknown Window Stash shortcut action")
    chord = normalize(value)
    path = _config_path(config_path)
    runner = runner or _run
    with _locked(path):
        _, entry = _read(path)
        previous = settings(entry)
        desired = dict(previous, **{key: chord})
        binds, owned = _runtime(runner)
        desired = validate(desired, binds, owned)
        _apply(desired, runner, binary)
        try:
            # Merge into the latest file so unrelated simultaneous settings
            # edits survive the IPC round trip.
            data, latest = _read(path)
            if settings(latest) != previous:
                raise RuntimeError("Shortcuts changed during this edit; try again")
            latest[key] = chord
            _atomic_json(path, data)
        except (OSError, RuntimeError, ValueError):
            _apply(previous, runner, binary)
            raise
    return {"ok": True, "key": key, "binding": chord, "shortcuts": desired}


def reset_settings(config_path, defaults, runner=None, binary=None):
    """Reset plugin preferences and managed bindings as one guarded edit.

    Only the supplied canonical settings belong to this transaction. Preserve
    host metadata, other plugins and unrelated concurrent edits in the latest
    file, but reject changes to settings the reset would otherwise overwrite.
    """
    path = _config_path(config_path)
    runner = runner or _run
    defaults = dict(defaults)

    def managed_stamp(entry):
        return json.dumps({key: entry[key] for key in defaults if key in entry},
                          sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    with _locked(path):
        _, entry = _read(path)
        previous = settings(entry)
        before = managed_stamp(entry)
        binds, owned = _runtime(runner)
        desired = validate(defaults, binds, owned)
        _apply(desired, runner, binary)
        try:
            data, latest = _read(path)
            if managed_stamp(latest) != before:
                raise RuntimeError("Settings changed during the reset; try again")
            latest.update(defaults)
            _atomic_json(path, data)
        except (OSError, RuntimeError, ValueError) as error:
            try:
                _apply(previous, runner, binary)
            except (OSError, RuntimeError, ValueError) as rollback:
                raise RuntimeError("Settings reset failed: " + str(error)
                                   + "; could not restore previous shortcuts: " + str(rollback)) from error
            raise
    return {"ok": True, "action": "settings-reset", "settings": defaults, "shortcuts": desired}


def sync(config_path=None, runner=None, binary=None):
    path = _config_path(config_path)
    runner = runner or _run
    with _locked(path):
        data, entry = _read(path)
        disabled = data.get("disabledPlugins")
        if isinstance(disabled, list) and PLUGIN in disabled:
            # A service update queued before --prepare-remove may start after
            # the host unloads it. Never recreate its handles during cleanup.
            return _disable(runner)
        binds, owned = _runtime(runner)
        values = validate(settings(entry), binds, owned)
        _apply(values, runner, binary)
    return {"ok": True, "shortcuts": values}


def _disable(runner):
    output = runner("eval", _module() + "m.disable()")
    if output != "ok":
        raise RuntimeError(output or "Could not disable Window Stash shortcuts")
    return {"ok": True, "action": "shortcuts-disabled"}


def disable(config_path=None, runner=None):
    path = _config_path(config_path)
    runner = runner or _run
    with _locked(path):
        return _disable(runner)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("export", "sync", "disable"))
    parser.add_argument("config", nargs="?")
    args = parser.parse_args()
    if args.action == "export":
        _, entry = _read(_config_path(args.config))
        print("return " + lua_source(settings(entry)))
    else:
        print(json.dumps((sync if args.action == "sync" else disable)(args.config)))


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError) as error:
        print(json.dumps({"ok": False, "error": str(error)}))
        sys.exit(1)
