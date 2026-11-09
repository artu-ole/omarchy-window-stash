#!/usr/bin/env python3
"""Set up Window Stash or prepare a git-managed plugin for removal."""
import argparse
from collections import Counter
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import time

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / "controller"))
from stash import DEFAULTS, PLUGIN, atomic_json, lua
import shortcuts

BEGIN = "-- Window Stash: begin"
END = "-- Window Stash: end"
LITERAL = r'''(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')'''


def lua_literal(value):
    """Read generated short Lua strings without executing configuration code."""
    result = bytearray()
    escapes = dict(zip('abfnrtv', ('\a', '\b', '\f', '\n', '\r', '\t', '\v')))
    index = 1
    while index < len(value)-1:
        character = value[index]
        index += 1
        if character != '\\':
            result.extend(character.encode('utf-8'))
            continue
        character = value[index]
        index += 1
        if '0' <= character <= '9':
            digits = character
            while index < len(value)-1 and len(digits) < 3 and '0' <= value[index] <= '9':
                digits += value[index]
                index += 1
            number = int(digits)
            if number > 255:
                raise ValueError('Invalid Lua string escape')
            result.append(number)
        elif character in ('\\', '"', "'"):
            result.extend(character.encode('utf-8'))
        elif character in escapes:
            result.extend(escapes[character].encode('utf-8'))
        else:
            raise ValueError('Unsupported Lua string escape')
    return result.decode('utf-8')


def binding_block(text, binary, target):
    """Accept only our loader or known literal legacy calls inside one block."""
    begins, ends, offset = [], [], 0
    for line in text.splitlines(keepends=True):
        if line.strip() == BEGIN:
            begins.append((offset, offset+len(line), line))
        elif line.strip() == END:
            ends.append((offset, offset+len(line), line))
        offset += len(line)
    if not begins and not ends:
        return None
    if len(begins) != 1 or len(ends) != 1 or begins[0][1] > ends[0][0]:
        raise RuntimeError('Malformed or repeated Window Stash shortcut markers; no configuration changed')
    begin, end = begins[0], ends[0]
    lines, comments, pending_comments = [], {}, []
    for line in text[begin[1]:end[0]].splitlines():
        line=line.strip()
        if not line:
            continue
        if line.startswith('--') and not line.startswith('--['):
            pending_comments.append(line)
            continue
        comments[len(lines)]=pending_comments
        pending_comments=[]
        lines.append(line)
    imported = {key: '' for key in shortcuts.DEFAULT_SHORTCUTS}
    calls, overrides, loader = [], [], None
    try:
        for position,line in enumerate(lines):
            unbind = re.fullmatch(r'hl\.unbind\s*\(\s*('+LITERAL+r')\s*\)\s*;?', line)
            if unbind:
                chord=shortcuts.normalize(lua_literal(unbind[1]))
                if not chord or any(override['chord']==chord for override in overrides):
                    raise ValueError('Empty or repeated legacy override')
                overrides.append(dict(chord=chord,line=line,comments=comments[position],position=position))
                continue
            candidate = re.fullmatch(r'dofile\s*\(\s*('+LITERAL+r')\s*\)\s*;?', line)
            if candidate:
                if loader is not None or lua_literal(candidate[1]) != str(target/'controller/shortcuts.lua'):
                    raise ValueError('Unknown shortcut loader')
                loader=position
                continue
            match = re.fullmatch(r'o\.bind\s*\(\s*('+LITERAL+r')\s*,\s*('+LITERAL+r')\s*,\s*('+LITERAL+r')\s*\)\s*;?', line)
            if not match:
                raise ValueError('Unknown shortcut code')
            chord, description, command = (lua_literal(part) for part in match.groups())
            key = next((key for key, (action, label) in shortcuts.ACTIONS.items()
                        if description == label and command == str(binary)+' '+action), None)
            if key is None or any(call['setting'] == key for call in calls):
                raise ValueError('Unknown or repeated shortcut action')
            chord = shortcuts.normalize(chord)
            imported[key] = chord
            calls.append(dict(setting=key, chord=chord, description=description, command=command,position=position))
        if loader is not None:
            if calls or loader != len(lines)-1:
                raise ValueError('Mixed or misplaced shortcut loader')
            imported={}
        elif any(not any(call['chord']==override['chord'] and call['position']>override['position'] for call in calls)
                 for override in overrides):
            raise ValueError('Legacy override is not paired with its following owned binding')
    except (ValueError, UnicodeError) as error:
        raise RuntimeError('Unrecognized custom code inside the Window Stash shortcut block; '
                           'move that code outside its markers before updating or removing the plugin') from error
    return dict(start=begin[0], end=end[1], beginLine=begin[2], endLine=end[2], legacy=imported, calls=calls,overrides=overrides)


def replace_binding_block(text, block, target, uninstall=False):
    if uninstall:
        return text[:block['start']]+text[block['end']:] if block else text
    newline = '\r\n' if block and block['beginLine'].endswith('\r\n') else '\n'
    ending = newline if not block or block['endLine'].endswith('\n') else ''
    lines=[BEGIN]
    # Keep only overrides the user already wrote explicitly. A legacy override
    # must be paired with an owned bind; after migration it persists even when
    # that action is rebound in Settings, until this whole block is removed.
    for override in block.get('overrides',[]) if block else []:
        lines.extend(override['comments'])
        lines.append(override['line'])
    lines.extend(['dofile('+lua(str(target/'controller/shortcuts.lua'))+')',END])
    managed = newline.join(lines)+ending
    if block:
        return text[:block['start']]+managed+text[block['end']:]
    return text+('' if not text or text.endswith('\n') else newline)+managed


def foreign_bindings(bindings, block, owned=()):
    """Ignore at most one live handle per literal call proven by the block.

    Lua-backed binds expose opaque callback references, not their exec command.
    The complete known description and chord must match; duplicate lookalikes
    stay foreign, even when their description starts with Window Stash.
    """
    remaining = list(bindings)
    def identity(binding):
        return (str(binding.get('dispatcher','')),str(binding.get('arg','')),binding.get('description',''),
                binding.get('modmask'),str(binding.get('key','')).lower(),binding.get('submap',''))
    cached = Counter(identity(binding) for binding in owned if isinstance(binding,dict))
    cached_indices = set()
    for index,binding in enumerate(remaining):
        if isinstance(binding,dict) and cached[identity(binding)]:
            cached_indices.add(index)
            cached[identity(binding)] -= 1
    removed = set()
    for call in block['calls'] if block else []:
        if not call['chord']:
            continue
        parts = call['chord'].split(' + ')
        mask = sum(shortcuts.MODIFIERS[modifier] for modifier in parts[:-1])
        for index, binding in enumerate(remaining):
            if index in cached_indices or index in removed or not isinstance(binding, dict):
                continue
            if (binding.get('modmask') != mask or str(binding.get('key', '')).lower() != parts[-1].lower()
                    or binding.get('description') != call['description']):
                continue
            if any(binding.get(flag) is True for flag in ('submap_universal', 'release', 'repeat', 'mouse', 'non_consuming', 'transparent', 'ignore_mods')):
                continue
            dispatcher, argument = binding.get('dispatcher'), str(binding.get('arg', ''))
            known = (dispatcher in ('exec', 'exec_cmd') and argument == call['command']) or (dispatcher == '__lua' and argument.isdecimal())
            if not known:
                continue
            if binding.get('submap', '') not in ('', 'reset'):
                raise RuntimeError('A legacy Window Stash shortcut uses a custom submap; migrate it manually first')
            removed.add(index)
            break
    return [binding for index,binding in enumerate(remaining) if index not in removed]


def shortcut_plan(config, text, binary, target):
    block = binding_block(text, binary, target)
    entry = next((entry for entry in config.get('plugins', []) if entry.get('id') == PLUGIN), {})
    desired = shortcuts.settings(entry)
    for key, chord in (block['legacy'] if block else {}).items():
        if key not in entry:
            desired[key] = chord
    return block, desired


def run(*args):
    p = subprocess.run(args, capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(p.stderr or p.stdout)
    return p.stdout.strip()


def wait_for_disabled():
    """Wait for the host to observe our deny-list entry before CLI removal.

    A rescan alone does not wait for shell.json's asynchronous file watcher.
    Removing an apparently enabled plugin makes the host erase its settings.
    """
    if run("omarchy-shell", "shell", "reloadConfig") != "ok":
        raise RuntimeError("Could not reload the shell configuration; plugin files were retained")
    deadline = time.monotonic() + 5
    while True:
        try:
            discovered = json.loads(run("omarchy-shell", "shell", "listPlugins"))
        except ValueError as error:
            raise RuntimeError("Could not read shell plugin state; plugin files were retained") from error
        if not isinstance(discovered, list) or any(not isinstance(entry, dict) for entry in discovered):
            raise RuntimeError("Could not read shell plugin state; plugin files were retained")
        matches = [entry for entry in discovered if entry.get("id") == PLUGIN]
        if len(matches) == 1 and matches[0].get("enabled") is False:
            return
        if time.monotonic() >= deadline:
            reason = "not known to the shell" if not matches else "still enabled in the shell"
            raise RuntimeError("Window Stash is " + reason + "; plugin files were retained. "
                               "Run omarchy-shell shell rescanPlugins and retry --prepare-remove")
        time.sleep(0.05)


def integration_patches():
    return {
        "Switcher.qml": [
            ('  property var pendingActivation: null', '  property var pendingActivation: null\n  // Window Stash integration\n  property string pendingStashAddress: ""'),
            ('    pendingActivation = originalToplevel\n', '    pendingStashAddress = ""\n    pendingActivation = originalToplevel\n'),
            ('    pendingActivation = selected.toplevel\n', '    pendingStashAddress = selected.stashManaged ? selected.address : ""\n    pendingActivation = selected.toplevel\n'),
            ('    pendingActivation = record.toplevel\n', '    pendingStashAddress = record.stashManaged ? record.address : ""\n    pendingActivation = record.toplevel\n'),
            ('      var target = root.pendingActivation\n', '      var target = root.pendingActivation\n      var stashAddress = root.pendingStashAddress\n      root.pendingStashAddress = ""\n'),
            ('        if (serial === root.openSerial && !root.opened && target) target.activate()',
             '''        if (serial === root.openSerial && !root.opened && target) {
          if (stashAddress) {
            var address = stashAddress.indexOf("0x") === 0 ? stashAddress : "0x" + stashAddress
            Quickshell.execDetached([Quickshell.env("HOME") + "/.local/bin/window-stash", "activate", address])
          } else target.activate()
        }'''),
        ],
        "components/WindowRecords.qml": [
            ('      minimized: toplevel && toplevel.minimized === true',
             '''      // The controller decides ownership; IPC tag snapshots may lag.
      stashManaged: workspaceName === "special:window-stash",
      minimized: toplevel && toplevel.minimized === true''')
        ],
        "model/WindowSnapshot.js": [
            ('  "minimized"', '  "minimized",\n  "stashManaged"')
        ]
    }


def upgrade_integration(text):
    return text.replace('window-stash", "restore", address]', 'window-stash", "activate", address]').replace(
        '''      stashManaged: workspaceName === "special:minimized" && Array.isArray(ipc.tags)
        && ipc.tags.some(function(tag) { return String(tag).indexOf("window-stash-") === 0 }),''',
        '''      // The controller decides ownership; IPC tag snapshots may lag.
      stashManaged: workspaceName === "special:window-stash",''').replace(
        'stashManaged: workspaceName === "special:minimized",',
        'stashManaged: workspaceName === "special:window-stash",')


def confirm_changes(target, bindings, shell, binary, switcher, uninstall, assume_yes, prepare_remove=False):
    action = "Prepare removal of" if prepare_remove else "Remove" if uninstall else "Install/update"
    print(f"{action} Window Stash for the current user:", file=sys.stderr)
    print(f"  Plugin files: {target}", file=sys.stderr)
    print(f"  Controller command: {binary}", file=sys.stderr)
    print(f"  Shortcut block: {bindings}", file=sys.stderr)
    print(f"  Plugin entry: {shell}", file=sys.stderr)
    if switcher.is_dir():
        print(f"  Window-switcher integration: {switcher}", file=sys.stderr)
    if uninstall or prepare_remove:
        print("  Restore all stashed windows before removing files.", file=sys.stderr)
    if prepare_remove:
        print("  Disable the plugin and retain its checkout and saved preferences.", file=sys.stderr)
        print("  Finish with: omarchy plugin remove " + PLUGIN, file=sys.stderr)
    elif not uninstall and SOURCE.resolve() == target.resolve():
        print("  Keep the installed checkout unchanged; set up desktop integration only.", file=sys.stderr)
    print("  Back up affected configuration; reload Hyprland and rescan shell plugins.", file=sys.stderr)
    print("  No root privileges, downloads, or packaged Omarchy-file changes.", file=sys.stderr)
    if assume_yes:
        return
    if not sys.stdin.isatty():
        raise RuntimeError("No files changed. Review the plan above and pass --yes to confirm non-interactively.")
    if input("Proceed? [y/N] ").strip().lower() not in ("y", "yes"):
        raise RuntimeError("Cancelled; no files changed.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    removal = parser.add_mutually_exclusive_group()
    removal.add_argument("--uninstall", action="store_true", help="Clean up and delete the plugin files")
    removal.add_argument("--prepare-remove", action="store_true",
                         help="Clean up but retain the checkout for omarchy plugin remove")
    parser.add_argument("--yes", action="store_true", help="Confirm the displayed file changes without prompting")
    args = parser.parse_args()
    home = Path.home()
    config = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
    target = config / "omarchy/plugins" / PLUGIN
    bindings = config / "hypr/bindings.lua"
    shell = config / "omarchy/shell.json"
    binary = home / ".local/bin/window-stash"
    switcher = config / "omarchy/plugins/community.window-switcher"
    confirm_changes(target, bindings, shell, binary, switcher, args.uninstall, args.yes, args.prepare_remove)
    backup = Path(os.environ.get("XDG_STATE_HOME", home / ".local/state")) / "omarchy/window-stash/backups" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup.mkdir(parents=True)
    for p in (bindings, shell):
        shutil.copy2(p, backup / p.name)
    config_data = json.loads(shell.read_text())
    # Reading bytes keeps every character outside the owned block unchanged,
    # including CRLF files and their intentional leading/trailing blank lines.
    binding_text = bindings.read_bytes().decode('utf-8')
    block, desired_shortcuts = shortcut_plan(config_data, binding_text, binary, target)
    monitor_state = json.loads(run("hyprctl", "monitors", "-j"))
    patches = integration_patches()
    if args.uninstall or args.prepare_remove:
        if binary.exists(): run(str(binary), "restore-all", "--to", "current")
        shortcuts.disable(shell, runner=lambda *arguments: run('hyprctl', *arguments))
        bindings.write_bytes(replace_binding_block(binding_text, block, target, uninstall=True).encode('utf-8'))
        if args.prepare_remove:
            # Omarchy ignores an entry's `enabled` field. Keep its preferences
            # but disable it through the host's explicit deny list; `plugin
            # enable` removes this marker if removal is cancelled.
            disabled = config_data.setdefault("disabledPlugins", [])
            if PLUGIN not in disabled:
                disabled.append(PLUGIN)
        else:
            config_data["plugins"] = [p for p in config_data.get("plugins", []) if p.get("id") != PLUGIN]
        atomic_json(shell, config_data)
        if args.prepare_remove:
            wait_for_disabled()
            # A queued service update might have synchronized handles while
            # the shell was still loading its new configuration.
            shortcuts.disable(shell, runner=lambda *arguments: run('hyprctl', *arguments))
        for name, changes in patches.items():
            p = switcher / name
            if not p.exists(): continue
            data = upgrade_integration(p.read_text())
            for original, modified in reversed(changes): data = data.replace(modified, original)
            p.write_text(data)
        if binary.exists(): binary.unlink()
        if args.uninstall and target.exists(): shutil.rmtree(target)
    else:
        run("omarchy", "plugin", "validate", str(SOURCE))
        live, owned = shortcuts.runtime_state(runner=lambda *arguments: run('hyprctl', *arguments))
        try:
            desired_shortcuts = shortcuts.validate(desired_shortcuts, foreign_bindings(live, block, owned), owned)
        except ValueError as error:
            raise RuntimeError(str(error)) from error
        # Verify all optional switcher patch anchors before modifying anything.
        for name, changes in patches.items():
            p = switcher / name
            if not p.exists(): continue
            data = upgrade_integration(p.read_text())
            for original, modified in changes:
                if original not in data and modified not in data:
                    raise RuntimeError("Window switcher changed; missing integration anchor in " + name)
        if SOURCE.resolve() != target.resolve():
            target.mkdir(parents=True, exist_ok=True)
            for name in ("manifest.json", "Service.qml", "ui", "controller", "native", "tools/build-preview-bridge.py", "tools/install.py", "window-stash", "README.md", "preview.png", "LICENSE", "THIRD_PARTY_NOTICES.md", "VALIDATION.md"):
                source = SOURCE / name
                dest = target / name
                if source.is_dir(): shutil.copytree(source, dest, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
                else:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, dest)
        binary.parent.mkdir(parents=True, exist_ok=True)
        binary.write_text('#!/usr/bin/env python3\nimport runpy\nrunpy.run_path(' + repr(str(target / "controller/stash.py")) + ', run_name="__main__")\n')
        binary.chmod(0o755)
        for name, changes in patches.items():
            p = switcher / name
            if not p.exists(): continue
            data = upgrade_integration(p.read_text())
            shutil.copy2(p, backup / name.replace("/", "_"))
            for original, modified in changes:
                if modified not in data: data = data.replace(original, modified, 1)
            p.write_text(data)
        bindings.write_bytes(replace_binding_block(binding_text, block, target).encode('utf-8'))
        config_data.setdefault("plugins", [])
        if not any(p.get("id") == PLUGIN for p in config_data["plugins"]):
            entry = dict(id=PLUGIN, **DEFAULTS)
            entry.update(desired_shortcuts)
            config_data["plugins"].append(entry)
        entry = next(p for p in config_data['plugins'] if p.get('id') == PLUGIN)
        for key, value in desired_shortcuts.items():
            entry.setdefault(key, value)
        atomic_json(shell, config_data)
    # reload acknowledges scheduling before the configuration has actually
    # been applied. Wait for its event before restoring runtime-only scaling.
    event_socket = socket.socket(socket.AF_UNIX)
    event_socket.settimeout(5)
    event_socket.connect(str(Path(os.environ["XDG_RUNTIME_DIR"]) / "hypr" /
                             os.environ["HYPRLAND_INSTANCE_SIGNATURE"] / ".socket2.sock"))
    try:
        run("hyprctl", "reload")
        events = b""
        while b"configreloaded>>" not in events:
            chunk = event_socket.recv(65536)
            if not chunk: raise RuntimeError("Hyprland closed the reload event socket")
            events += chunk
    finally:
        event_socket.close()
    # A reload must not reset a scale/position the owner adjusted at runtime.
    for monitor in monitor_state:
        run("hyprctl", "eval", 'hl.monitor({output=%s, mode=%s, position=%s, scale=%s, transform=%s})' % (
            lua(monitor["name"]), lua('%dx%d@%.2f' % (monitor["width"],monitor["height"],monitor["refreshRate"])),
            lua('%dx%d' % (monitor["x"],monitor["y"])), monitor["scale"],monitor["transform"]))
    deadline = time.monotonic() + 5
    while True:
        current = {m["name"]:m for m in json.loads(run("hyprctl", "monitors", "-j"))}
        if all(m["name"] in current and all(current[m["name"]][key] == m[key] for key in ("scale","x","y","transform")) for m in monitor_state):
            break
        if time.monotonic() > deadline: raise RuntimeError("Runtime display profile was not restored")
        time.sleep(0.05)
    errors = run("hyprctl", "configerrors")
    if errors: raise RuntimeError(errors)
    run("omarchy-shell", "shell", "rescanPlugins")
    result = dict(ok=True, installed=not args.uninstall, backup=str(backup))
    if args.prepare_remove:
        result.update(preparedRemoval=True, enabled=False)
    print(json.dumps(result))


if __name__ == "__main__":
    try: main()
    except (OSError, RuntimeError, ValueError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
