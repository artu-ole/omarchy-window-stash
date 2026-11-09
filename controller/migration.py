"""Retire verified files written by the legacy installer, without reloading Hyprland."""
import ast
from contextlib import contextmanager
from datetime import datetime
import fcntl
import json
import os
from pathlib import Path
import stat
import tempfile
import uuid

from legacy import BEGIN, END, binding_block, integration_patches
import shortcuts


PLUGIN = "community.window-stash"


def _regular(path):
    """Never follow a user-created symlink while retiring generated files."""
    try:
        if not stat.S_ISREG(path.lstat().st_mode):
            return None
        return path.read_bytes()
    except FileNotFoundError:
        return None


def _replace(path, expected, data):
    if _regular(path) != expected:
        raise RuntimeError("A legacy integration file changed during migration; it was left in place")
    if data is None:
        path.unlink()
        return
    mode = stat.S_IMODE(path.stat().st_mode)
    descriptor, temporary = tempfile.mkstemp(prefix=".window-stash-migration-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if _regular(path) != expected:
            raise RuntimeError("A legacy integration file changed during migration; it was left in place")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def owned_wrapper(data, target):
    """Recognize the tiny generated runpy wrapper, without executing Python."""
    if data is None or len(data) > 8192:
        return False
    try:
        body = ast.parse(data.decode("utf-8")).body
        if len(body) != 2 or not isinstance(body[0], ast.Import):
            return False
        if len(body[0].names) != 1 or body[0].names[0].name != "runpy" or body[0].names[0].asname:
            return False
        call = body[1].value if isinstance(body[1], ast.Expr) else None
        return (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                and isinstance(call.func.value, ast.Name) and call.func.value.id == "runpy"
                and call.func.attr == "run_path" and len(call.args) == 1
                and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str)
                and Path(call.args[0].value).resolve() == (target/"controller/stash.py").resolve()
                and len(call.keywords) == 1 and call.keywords[0].arg == "run_name"
                and isinstance(call.keywords[0].value, ast.Constant)
                and call.keywords[0].value.value == "__main__")
    except (SyntaxError, UnicodeError, ValueError):
        return False


def _bindings(data, binary, target):
    if data is None:
        return None, {}, [], False
    text = data.decode("utf-8")
    if BEGIN not in text and END not in text:
        return data, {}, [], False
    block = binding_block(text, binary, target)
    if block is None:
        return data, {}, [], False
    # Keep only statements the operator explicitly wrote. Preserve their raw
    # bytes, indentation, comments and CRLF endings; the loader and generated
    # o.bind calls are the only lines removed with our markers.
    section = text[block["start"]:block["end"]].splitlines(keepends=True)
    retained = []
    for line in section[1:-1]:
        stripped = line.strip()
        if not stripped or stripped.startswith("--") or stripped.startswith("hl.unbind"):
            retained.append(line)
    # Comments that only described generated bindings carry no runtime code;
    # retaining them is safer than guessing the user's intent.
    replacement = "".join(retained)
    rewritten = text[:block["start"]] + replacement + text[block["end"]:]
    return rewritten.encode("utf-8"), block["legacy"], [item["chord"] for item in block["overrides"]], True


def _variants(text):
    yield text.encode("utf-8")
    yield text.replace("\n", "\r\n").encode("utf-8")


def _reverse_switcher(data, changes):
    result = data
    # Earlier releases used a different command/workspace. Normalize only
    # the exact old snippets before reversing our known integration.
    upgrades = [
        ('window-stash", "restore", address]', 'window-stash", "activate", address]'),
        ('stashManaged: workspaceName === "special:minimized",',
         'stashManaged: workspaceName === "special:window-stash",'),
        ('''      stashManaged: workspaceName === "special:minimized" && Array.isArray(ipc.tags)
        && ipc.tags.some(function(tag) { return String(tag).indexOf("window-stash-") === 0 }),''',
         '''      // The controller decides ownership; IPC tag snapshots may lag.
      stashManaged: workspaceName === "special:window-stash",'''),
    ]
    for before, after in upgrades:
        for old, new in zip(_variants(before), _variants(after)):
            result = result.replace(old, new)
    # One intermediate version had the workspace check without its comment.
    bare = b'      stashManaged: workspaceName === "special:window-stash",'
    comment = b'      // The controller decides ownership; IPC tag snapshots may lag.'
    if bare in result and comment not in result:
        newline = b"\r\n" if bare+b"\r\n" in result else b"\n"
        result = result.replace(bare, comment+newline+bare)
    for before, after in reversed(changes):
        for old, new in zip(_variants(after), _variants(before)):
            if result.count(old) > 1:
                return None
            result = result.replace(old, new)
    if any(token in result for token in (b"pendingStashAddress", b"stashAddress", b"stashManaged", b"window-stash")):
        return None
    return result


@contextmanager
def _migration_lock(state):
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (state/"migration.lock").open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def migrate(plugin_root=None, home=None, config_home=None, state_home=None):
    """Return migration status; unknown custom integration code stays untouched.

    Fresh CLI installations do not write bindings, wrappers or other plugins.
    Only earlier generated files are retired, after a private backup.
    """
    home = Path(home) if home is not None else Path.home()
    config = Path(config_home) if config_home is not None else Path(os.environ.get("XDG_CONFIG_HOME") or home/".config")
    state = Path(state_home) if state_home is not None else Path(os.environ.get("XDG_STATE_HOME") or home/".local/state")
    state = state/"omarchy/window-stash"
    target = Path(plugin_root) if plugin_root is not None else Path(__file__).resolve().parents[1]
    binary = home/".local/bin/window-stash"
    bindings = config/"hypr/bindings.lua"
    shell = config/"omarchy/shell.json"
    switcher = config/"omarchy/plugins/community.window-switcher"
    outcome = dict(migrated=False, changed=[], warnings=[], requiresShortcutSync=False,
                   bindingsChanged=False, legacyShortcuts={}, preservedOverrides=[], backup=None)
    original = _regular(bindings)
    wrapper = _regular(binary)
    switcher_data = {name: _regular(switcher/name) for name in integration_patches()}
    markers = (b"pendingStashAddress", b"stashManaged", b"window-stash")
    has_bindings = original is not None and (BEGIN.encode() in original or END.encode() in original)
    has_switcher = any(data is not None and any(token in data for token in markers) for data in switcher_data.values())
    if not has_bindings and not has_switcher and not owned_wrapper(wrapper, target):
        return outcome
    with _migration_lock(state):
        original = _regular(bindings)
        wrapper = _regular(binary)
        plan = []
        dependency = bindings.is_symlink()
        if dependency:
            outcome["warnings"].append("Legacy shortcut configuration is a symlink; its compatibility command was left unchanged")
        try:
            rewritten, imported, overrides, recognized = _bindings(original, binary, target)
        except (RuntimeError, UnicodeError):
            rewritten, imported, overrides, recognized = original, {}, [], False
            dependency = True
            outcome["warnings"].append("Legacy Window Stash shortcut code was customized; its block and compatibility command were left unchanged")
        outcome["legacyShortcuts"] = imported
        outcome["preservedOverrides"] = overrides
        if recognized and rewritten != original:
            plan.append((bindings, original, rewritten, "bindings.lua"))
        if rewritten and b"window-stash" in rewritten:
            dependency = True
        switcher_plan = []
        for name, changes in integration_patches().items():
            path = switcher/name
            data = _regular(path)
            if data is None or not any(token in data for token in markers):
                continue
            reverted = _reverse_switcher(data, changes)
            if reverted is None:
                dependency = True
                outcome["warnings"].append("Legacy window-switcher integration was customized; its files and compatibility command were left unchanged")
                switcher_plan = None
                break
            if reverted != data:
                switcher_plan.append((path, data, reverted, "switcher_"+name.replace("/", "_")))
        if switcher_plan is not None:
            plan.extend(switcher_plan)
        if owned_wrapper(wrapper, target) and not dependency:
            plan.append((binary, wrapper, None, "window-stash"))
        if not plan and not imported:
            return outcome
        # All original bytes reach a private backup before any file changes.
        backup = state/"backups"/("migration-"+datetime.now().strftime("%Y%m%d-%H%M%S-%f")+"-"+uuid.uuid4().hex[:8])
        backup.mkdir(parents=True, mode=0o700)
        for _, data, _, name in plan:
            (backup/name).write_bytes(data)
            (backup/name).chmod(0o600)
        if imported:
            with shortcuts._locked(shell):
                before = _regular(shell)
                if before is None:
                    raise RuntimeError("Omarchy settings were unavailable during legacy shortcut migration")
                data = json.loads(before)
                entries = [entry for entry in data.get("plugins", []) if isinstance(entry, dict) and entry.get("id") == PLUGIN]
                if len(entries) != 1:
                    raise RuntimeError("Window Stash settings were unavailable during legacy shortcut migration")
                patch = {key: value for key, value in imported.items() if key not in entries[0]}
                if patch:
                    (backup/"shell.json").write_bytes(before)
                    (backup/"shell.json").chmod(0o600)
                    entries[0].update(patch)
                    shortcuts._atomic_json(shell, data)
                    outcome["changed"].append("shell.json")
        for path, before, after, label in plan:
            _replace(path, before, after)
            outcome["changed"].append(label)
        outcome["backup"] = str(backup)
        outcome["bindingsChanged"] = "bindings.lua" in outcome["changed"]
        outcome["migrated"] = bool(outcome["changed"])
        outcome["requiresShortcutSync"] = outcome["migrated"]
    return outcome
