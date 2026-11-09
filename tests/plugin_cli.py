#!/usr/bin/env python3
"""Native CLI lifecycle acceptance; explicit disposable desktop profiles only.

Requires WINDOW_STASH_ISOLATED_TEST=1 and ~/.window-stash-isolated. The source
fixture defaults to file:///mnt/fixture; override with STASH_CLI_FIXTURE. This
suite deliberately disables/removes the plugin and must never use a real home.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from urllib.parse import unquote, urlparse

from desktop_test import desktop_test
from live import command, configure, h, shell, wait
from native_session import NativeSession
from stash import SPECIAL


PLUGIN = "community.window-stash"
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home()/".config")
TARGET = CONFIG/"omarchy/plugins"/PLUGIN
FIXTURE = os.environ.get("STASH_CLI_FIXTURE", "file:///mnt/fixture")
KEYS = {"minimizeShortcut":"SUPER + ALT + A", "restoreLastShortcut":"SUPER + ALT + Z"}


def require_isolated():
    if os.environ.get("WINDOW_STASH_ISOLATED_TEST") != "1" or not (Path.home()/".window-stash-isolated").is_file():
        raise RuntimeError("Refusing destructive CLI tests outside an explicit disposable profile")
    location = urlparse(FIXTURE)
    if location.scheme != "file" or location.netloc or not Path(unquote(location.path)).is_dir():
        raise RuntimeError("Use a local disposable Git fixture for CLI lifecycle tests")


def run(*args):
    result = subprocess.run(list(map(str, args)), capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, (args, result.stdout, result.stderr)
    return result.stdout.strip()


def cli(action, *args):
    return run("omarchy", "plugin", action, *args)


def status():
    try:
        return shell("status")
    except (subprocess.CalledProcessError, ValueError):
        return None


def ready(owner=None):
    def current():
        value = status()
        return value if value and value.get("lifecycle", {}).get("ready") and value.get("screens") and not value["error"] \
            and (owner is None or value["lifecycle"]["owner"] != owner) else None
    return wait(current, "CLI-installed service did not become ready", timeout=25)


def owned():
    return json.loads(h.call("repl", 'local m=_community_window_stash_shortcuts; return m and m.inspect() or "[]"'))


def active():
    return [binding for binding in owned() if binding.get("enabled") is True]


def native_select_all():
    # The stock shortcut must survive registration/release of the plugin's
    # independent Super+Alt chords. Opaque Lua callback IDs may change on reload.
    return sorted((binding.get("description", ""), binding.get("submap", ""))
                  for binding in h.read("binds") if binding.get("modmask") == 64
                  and str(binding.get("key", "")).lower() == "a"
                  and not str(binding.get("description", "")).startswith("Window Stash:"))


def assert_runtime_shortcuts():
    handles = active()
    assert {(b["modmask"], b["key"].lower()) for b in handles} == {(72, "a"), (72, "z")}, handles
    assert ready()["activeShortcuts"] == dict(KEYS, restoreOldestShortcut="")


def ensure_installed():
    if not TARGET.is_dir():
        cli("add", FIXTURE, "--enable", "--yes")
    else:
        cli("enable", PLUGIN)
    ready()


def record_for(address):
    return next((record for record in command("list")["windows"] if record["address"] == address), None)


def restored(address, before):
    def current():
        client = h.client(address)
        return client if client and client["workspace"]["id"] == before["workspace"]["id"] \
            and client["floating"] and client["at"] == before["at"] and client["size"] == before["size"] else None
    client = wait(current, "Guardian did not restore the owned fixture to its original workspace", timeout=12)
    assert client["pid"] == before["pid"] and client.get("stableId") == before.get("stableId")
    assert client["floating"] and client["at"] == before["at"] and client["size"] == before["size"]


def trigger(session, letter):
    session.keys("-M", "logo", "-M", "alt", "-s", "60", "-k", letter.lower(),
                 "-s", "60", "-m", "alt", "-m", "logo")


def source_free():
    assert not (Path.home()/".local/bin/window-stash").exists(), "Setup created an external controller wrapper"
    assert b"-- Window Stash: begin" not in (CONFIG/"hypr/bindings.lua").read_bytes()


@desktop_test("Isolated one-command plugin CLI lifecycle")
def acceptance():
    initial_native = native_select_all()
    assert initial_native, "The disposable profile must include stock Super+A"
    if TARGET.is_dir():
        assert not command("list")["windows"], "CLI lifecycle fixtures require an empty isolated stash"
        cli("remove", PLUGIN, "--yes")
        wait(lambda: not active(), "Initial CLI removal did not release shortcuts", timeout=12)
    cli("add", FIXTURE, "--enable", "--yes")
    ready(); source_free(); assert_runtime_shortcuts()
    assert native_select_all() == initial_native
    print("PASS one-command add/enable, bundled controller, runtime shortcuts and stock Super+A", flush=True)
    with NativeSession() as session:
        try:
            for key, value in dict(presentation="dock", animations="off", hoverPreview="off",
                                  restoreDestination="original", sizePreset="100", staticDockLock="locked").items():
                configure(key, value)
            fixtures = []
            for index in range(2):
                address, _ = session.spawn(app="org.windowstash.CliLifecycle"+str(index))
                h.dispatch("window.float", window="address:"+address, action="on")
                h.dispatch("window.resize", window="address:"+address, x=480, y=320, relative=False)
                h.dispatch("window.move", window="address:"+address,
                           x=session.monitor["x"]+100+index*70, y=session.monitor["y"]+100+index*70, relative=False)
                fixtures.append((address, h.client(address)))
            first, before_first = fixtures[0]
            second, before_second = fixtures[1]
            record = session.park(first)
            session.resting()
            session.click(wait(lambda: session.icon("window:"+str(record["stableId"])), "Static icon did not appear"))
            restored(first, before_first)
            matching = h.call("repl", 'return hl.get_config("input.resolve_binds_by_sym")')
            following = h.call("repl", 'return hl.get_config("input.follow_mouse")')
            assert matching in ("true", "false")
            assert following in ("0", "1", "2", "3")
            try:
                h.eval("hl.config({input={resolve_binds_by_sym=true,follow_mouse=0}})")
                h.dispatch("focus", window="address:"+first)
                wait(lambda:h.read("activewindow").get("address")==first,"Keyboard fixture did not focus")
                trigger(session, "A")
                record = wait(lambda: record_for(first), "Default keyboard minimize did not stash")
                session.touch("window:"+str(record["stableId"]))
                wait(lambda: h.client(first)["workspace"]["name"] == SPECIAL, "Keyboard minimize did not complete")
                trigger(session, "Z")
                restored(first, before_first)
            finally:
                h.eval("hl.config({input={resolve_binds_by_sym="+matching+",follow_mouse="+following+"}})")
            print("PASS icon and real Super+Alt+A/Z restoration with exact geometry", flush=True)
            configure("presentation", "floating")
            configure("dockOpacity", 73)
            first_record, second_record = session.park(first), session.park(second)
            h.dispatch("focus", window="address:"+first)
            wait(lambda: record_for(first) is None, "External switcher activation did not restore the window")
            restored(first, before_first)
            assert h.client(second)["workspace"]["name"] == SPECIAL
            monitor = next(m for m in h.read("monitors") if m["name"] == session.monitor["name"])
            assert monitor.get("specialWorkspace", {}).get("name") not in (SPECIAL, "window-stash"), "Private workspace overlay stayed visible"
            first_record = session.park(first)
            ids = {first_record["id"], second_record["id"]}
            print("PASS external activation restores only its target and hides the private overlay", flush=True)
            h.call("reload")
            wait(lambda: len(active()) == 2, "Config reload did not recreate runtime shortcuts", timeout=12)
            assert {w["id"] for w in command("list")["windows"]} == ids
            assert_runtime_shortcuts()
            with tempfile.TemporaryDirectory(prefix="stash-cli-upstream-") as directory:
                upstream = Path(directory)/"upstream"
                run("git", "clone", "--quiet", "--no-hardlinks", FIXTURE, upstream)
                service = upstream/"Service.qml"
                service.write_text(service.read_text()+"\n// Disposable CLI update acceptance revision.\n")
                run("git", "-C", upstream, "add", "Service.qml")
                run("git", "-C", upstream, "-c", "user.name=Window Stash Test", "-c", "user.email=test@example.invalid",
                    "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "Disposable CLI update")
                owner = ready()["lifecycle"]["owner"]
                run("git", "-C", TARGET, "remote", "set-url", "origin", upstream.as_uri())
                try:
                    cli("update", PLUGIN, "--yes")
                    ready(owner)
                    assert run("git", "-C", TARGET, "rev-parse", "HEAD") == run("git", "-C", upstream, "rev-parse", "HEAD")
                    assert {w["id"] for w in command("list")["windows"]} == ids
                    assert not run("git", "-C", TARGET, "status", "--porcelain")
                finally:
                    if TARGET.is_dir():run("git", "-C", TARGET, "remote", "set-url", "origin", FIXTURE)
            print("PASS config reload reclaims shortcuts; actual CLI update hands off without restoring stash", flush=True)
            preferences = dict(ready()["settings"])
            cli("disable", PLUGIN)
            for address, before in fixtures:restored(address, before)
            wait(lambda: not active(), "Disable did not release exact shortcut handles", timeout=12)
            assert native_select_all() == initial_native
            cli("enable", PLUGIN)
            assert ready()["settings"] == preferences, "Disable/enable lost preferences"
            assert_runtime_shortcuts()
            print("PASS CLI disable restores original workspaces, releases shortcuts and preserves preferences", flush=True)
            for address, _ in fixtures:session.park(address)
            cli("remove", PLUGIN, "--yes")
            assert not TARGET.exists(), "CLI did not delete the plugin source"
            # Only compositor reads and the already loaded Lua manager are
            # used below: the deleted controller cannot perform recovery.
            for address, before in fixtures:restored(address, before)
            wait(lambda: not active(), "Removal left active shortcut handles", timeout=12)
            assert native_select_all() == initial_native
            print("PASS source-deleted removal recovers parked fixtures through the in-memory guardian", flush=True)
            cli("add", FIXTURE, "--enable", "--yes")
            assert ready()["settings"] == preferences, "Remove/reinstall lost checkpointed preferences"
            source_free(); assert_runtime_shortcuts()
        finally:
            ensure_installed()
    source_free()
    assert native_select_all() == initial_native
    print("PASS CLI reinstall and native fixture cleanup", flush=True)


if __name__ == "__main__":
    require_isolated()
    acceptance()
