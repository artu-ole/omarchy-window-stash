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
from legacy import (BEGIN, END, LITERAL, lua_literal, binding_block, replace_binding_block,
                    integration_patches, upgrade_integration)

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
