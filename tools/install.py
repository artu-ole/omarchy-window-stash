#!/usr/bin/env python3
"""Install/uninstall Window Stash in user configuration, preserving other edits."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / "controller"))
from stash import DEFAULTS, PLUGIN, atomic_json, lua

BEGIN = "-- Window Stash: begin"
END = "-- Window Stash: end"


def run(*args):
    p = subprocess.run(args, capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(p.stderr or p.stdout)
    return p.stdout.strip()


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
      stashManaged: workspaceName === "special:minimized",
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
      stashManaged: workspaceName === "special:minimized",''')


def confirm_changes(target, bindings, shell, binary, switcher, uninstall, assume_yes):
    action = "Remove" if uninstall else "Install/update"
    print(f"{action} Window Stash for the current user:", file=sys.stderr)
    print(f"  Plugin files: {target}", file=sys.stderr)
    print(f"  Controller command: {binary}", file=sys.stderr)
    print(f"  Shortcut block: {bindings}", file=sys.stderr)
    print(f"  Plugin entry: {shell}", file=sys.stderr)
    if switcher.is_dir():
        print(f"  Window-switcher integration: {switcher}", file=sys.stderr)
    if uninstall:
        print("  Restore all stashed windows before removing files.", file=sys.stderr)
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
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--yes", action="store_true", help="Confirm the displayed file changes without prompting")
    args = parser.parse_args()
    home = Path.home()
    config = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
    target = config / "omarchy/plugins" / PLUGIN
    bindings = config / "hypr/bindings.lua"
    shell = config / "omarchy/shell.json"
    binary = home / ".local/bin/window-stash"
    switcher = config / "omarchy/plugins/community.window-switcher"
    confirm_changes(target, bindings, shell, binary, switcher, args.uninstall, args.yes)
    backup = Path(os.environ.get("XDG_STATE_HOME", home / ".local/state")) / "omarchy/window-stash/backups" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup.mkdir(parents=True)
    for p in (bindings, shell):
        shutil.copy2(p, backup / p.name)
    config_data = json.loads(shell.read_text())
    monitor_state = json.loads(run("hyprctl", "monitors", "-j"))
    patches = integration_patches()
    if args.uninstall:
        if binary.exists(): run(str(binary), "restore-all", "--to", "current")
        data = bindings.read_text()
        if BEGIN in data:
            start, end = data.index(BEGIN), data.index(END) + len(END)
            bindings.write_text(data[:start] + data[end:].lstrip("\n"))
        config_data["plugins"] = [p for p in config_data.get("plugins", []) if p.get("id") != PLUGIN]
        atomic_json(shell, config_data)
        for name, changes in patches.items():
            p = switcher / name
            if not p.exists(): continue
            data = upgrade_integration(p.read_text())
            for original, modified in reversed(changes): data = data.replace(modified, original)
            p.write_text(data)
        if binary.exists(): binary.unlink()
        if target.exists(): shutil.rmtree(target)
    else:
        run("omarchy", "plugin", "validate", str(SOURCE))
        live = json.loads(run("hyprctl", "binds", "-j"))
        conflicts = [b for b in live if b.get("modmask") == 64 and b.get("key", "").upper() in ("A", "Z")
                     and not b.get("description", "").startswith("Window Stash:")]
        if conflicts: raise RuntimeError("Shortcut conflict: " + repr([(b["key"], b["description"]) for b in conflicts]))
        # Verify all optional switcher patch anchors before modifying anything.
        for name, changes in patches.items():
            p = switcher / name
            if not p.exists(): continue
            data = upgrade_integration(p.read_text())
            for original, modified in changes:
                if original not in data and modified not in data:
                    raise RuntimeError("Window switcher changed; missing integration anchor in " + name)
        target.mkdir(parents=True, exist_ok=True)
        for name in ("manifest.json", "Service.qml", "ui", "controller", "window-stash", "README.md", "assets", "LICENSE", "THIRD_PARTY_NOTICES.md", "VALIDATION.md"):
            source = SOURCE / name
            dest = target / name
            if source.is_dir(): shutil.copytree(source, dest, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
            else: shutil.copy2(source, dest)
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
        text = bindings.read_text()
        if BEGIN not in text:
            text += '\n' + BEGIN + '\n'
            text += 'o.bind("SUPER + A", "Window Stash: minimize focused window", ' + lua(str(binary) + " minimize") + ')\n'
            text += 'o.bind("SUPER + Z", "Window Stash: restore last minimized", ' + lua(str(binary) + " restore-last") + ')\n'
            text += END + '\n'
            bindings.write_text(text)
        config_data.setdefault("plugins", [])
        if not any(p.get("id") == PLUGIN for p in config_data["plugins"]):
            config_data["plugins"].append(dict(id=PLUGIN, **DEFAULTS))
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
    print(json.dumps(dict(ok=True, installed=not args.uninstall, backup=str(backup))))


if __name__ == "__main__":
    try: main()
    except (OSError, RuntimeError, ValueError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
