"""Ownership and recovery tests use private files and a simulated compositor."""
import copy
import json
import os
from pathlib import Path
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "controller"))
import lifecycle
from stash import DEFAULTS, PLUGIN, SPECIAL, Stash, atomic_json
from test_controller import FakeHypr, client


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "plugins" / PLUGIN
        self.root.mkdir(parents=True)
        (self.root / "manifest.json").write_text(json.dumps(dict(id=PLUGIN)))
        self.config = self.base / "config/omarchy/shell.json"
        self.config.parent.mkdir(parents=True)
        self.original = dict(plugins=[dict(id=PLUGIN, presentation="dock", previewDelay=123)],
                             other=dict(value="retain"))
        atomic_json(self.config, self.original)
        self.hypr = FakeHypr()
        self.hypr.clients[0].update(floating=True, at=[123, 177], size=[777, 444])
        self.control = client("0x9", pid=999)
        self.hypr.clients.append(self.control)
        self.stash = Stash(self.hypr, self.base / "run", self.config, self.base / "state")
        with self.stash.locked():
            self.ident = self.stash.minimize("0x1")["id"]
        self.hypr.active = "0x9"
        self.hypr.commands.clear()
        self.events = []
        self.owner = None
        self.claims = []
        self.disables = []
        self.syncs = []
        self.notifications = []
        self.patchers = [patch.object(lifecycle.shortcuts, "claim", side_effect=self.claim),
                         patch.object(lifecycle.shortcuts, "disable", side_effect=self.disable),
                         patch.object(lifecycle.shortcuts, "sync", side_effect=self.sync)]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.keeper = self.make_keeper("generation-one")

    def make_keeper(self, owner):
        return lifecycle.LifecycleKeeper(owner, self.stash, self.root, self.events.append, migrate=False,
                                         notifier=lambda: self.notifications.append(True))

    def claim(self, owner, config_path=None, runner=None):
        self.claims.append(owner)
        self.owner = owner
        return dict(ok=True)

    def disable(self, config_path=None, runner=None, owner=None):
        self.disables.append(owner)
        return dict(ok=True)

    def sync(self, config_path=None, runner=None, binary=None, owner=None):
        self.syncs.append(owner)
        self.assertEqual(owner, self.owner)
        return dict(ok=True, shortcuts=dict(lifecycle.shortcuts.DEFAULT_SHORTCUTS),
                    activeShortcuts=dict(lifecycle.shortcuts.DEFAULT_SHORTCUTS), conflicts={})

    def disable_config(self, denied=False):
        data = json.loads(self.config.read_text())
        if denied:
            data["disabledPlugins"] = [PLUGIN]
        else:
            data["plugins"] = []
        atomic_json(self.config, data)

    def cleanup(self):
        with self.keeper.locked():
            return self.keeper._cleanup_locked()

    def test_focus_guard_resyncs_owned_records_and_only_current_removal_releases_it(self):
        synced, cleared = [], []
        self.hypr.sync_focus_guard = lambda records: synced.append(copy.deepcopy(records))
        self.hypr.clear_focus_guard = lambda: cleared.append(copy.deepcopy(self.stash.state["windows"]))
        self.keeper.start()
        self.assertEqual([r["id"] for r in synced[-1]], [self.ident])
        self.keeper.update({"action": "sync"})
        self.assertEqual(len(synced), 2)
        successor = self.make_keeper("generation-two")
        successor.start()
        self.assertEqual(len(synced), 3)
        self.assertEqual(cleared, [])
        self.disable_config()
        self.assertEqual(self.cleanup()["state"], "superseded")
        self.assertEqual(cleared, [])
        with successor.locked():
            self.assertEqual(successor._cleanup_locked()["state"], "cleaned")
        self.assertEqual(cleared, [[]], "The focus guard was released before window recovery completed")

    def test_focus_guard_cleanup_failure_reports_error_after_restoring_owned_windows(self):
        self.hypr.sync_focus_guard = lambda records: None
        def refuse():
            raise RuntimeError("Owned focus observer could not be released")
        self.hypr.clear_focus_guard = refuse
        self.keeper.start()
        self.disable_config()
        result = self.cleanup()
        self.assertEqual(result["state"], "error")
        self.assertEqual(result["remaining"], 0)
        self.assertIn("Owned focus observer could not be released", result["error"])
        self.assertNotEqual(self.hypr.client("0x1")["workspace"]["name"], SPECIAL)

    def test_enabled_start_claims_runtime_without_touching_hypr_config(self):
        before = self.config.read_bytes()
        result = self.keeper.start()
        self.assertEqual(result["state"], "ready")
        self.assertEqual(self.claims, ["generation-one"])
        self.assertEqual(self.syncs, ["generation-one"])
        self.assertEqual(self.config.read_bytes(), before)
        self.assertTrue(self.keeper.owns())
        self.assertFalse(any(isinstance(action, tuple) and action[0] in ("window.move", "window.close")
                             for action in self.hypr.commands))

    def test_shell_restart_preserves_stash_and_owned_shortcuts(self):
        self.keeper.start()
        before = copy.deepcopy(self.hypr.clients)
        result = self.cleanup()
        self.assertEqual(result["state"], "preserved")
        self.assertEqual(self.hypr.clients, before)
        self.assertEqual(self.disables, [])
        with self.stash.locked():
            self.assertEqual([r["id"] for r in self.stash.state["windows"]], [self.ident])

    def test_cli_disable_restores_only_owned_windows_to_original_geometry(self):
        self.keeper.start()
        self.disable_config()
        foreign = copy.deepcopy(self.control)
        result = self.cleanup()
        self.assertEqual(result["state"], "cleaned")
        self.assertEqual(result["restored"], 1)
        self.assertEqual(self.hypr.clients[0]["workspace"]["id"], 1)
        self.assertEqual(self.hypr.clients[0]["at"], [123, 177])
        self.assertEqual(self.hypr.clients[0]["size"], [777, 444])
        self.assertEqual(self.hypr.client("0x9"), foreign)
        self.assertEqual(self.hypr.active, "0x9")
        self.assertEqual(self.disables, [None])
        self.assertEqual(self.notifications, [])
        self.assertFalse(any(isinstance(action, tuple) and action[0] == "window.close" for action in self.hypr.commands))

    def test_directory_deletion_cleanup_uses_already_loaded_code(self):
        self.keeper.start()
        shutil.rmtree(self.root)
        result = self.cleanup()
        self.assertEqual(result["state"], "cleaned")
        self.assertEqual(self.hypr.clients[0]["workspace"]["id"], 1)
        self.assertEqual(self.disables, [None])

    def test_missing_lua_manager_after_reload_does_not_block_window_recovery(self):
        self.keeper.start()
        self.owner = None
        self.disable_config(denied=True)
        self.assertEqual(self.cleanup()["state"], "cleaned")
        self.assertEqual(self.hypr.clients[0]["workspace"]["id"], 1)
        self.assertEqual(self.disables, [None], "Reloaded unowned handles must also be disabled")

    def test_successor_claim_prevents_old_cleanup_and_observer_disable(self):
        self.keeper.start()
        successor = self.make_keeper("generation-two")
        successor.start()
        self.disable_config()
        self.hypr.commands.clear()
        result = self.cleanup()
        self.assertEqual(result["state"], "superseded")
        self.assertEqual(self.hypr.commands, [])
        self.assertEqual(self.disables, [])
        self.assertEqual(self.notifications, [])
        self.assertEqual(self.hypr.clients[0]["workspace"]["name"], SPECIAL)

    def test_cleanup_retries_partial_failure_and_retains_recovery_ledger(self):
        self.keeper.start()
        self.disable_config()
        self.hypr.fail = "window.move"
        with patch.object(lifecycle.time, "sleep") as sleep:
            result = self.cleanup()
        self.assertEqual(result["state"], "error")
        self.assertEqual(result["remaining"], 1)
        self.assertEqual(sleep.call_count, 2)
        self.assertTrue(self.keeper.error_path.is_file())
        self.assertEqual(self.notifications, [True])
        with self.stash.locked():
            self.assertEqual([r["id"] for r in self.stash.state["windows"]], [self.ident])
        self.hypr.fail = None
        self.assertEqual(self.cleanup()["state"], "cleaned")
        self.assertFalse(self.keeper.error_path.exists())
        self.assertEqual(self.notifications, [True])

    def test_reused_address_is_never_restored_or_closed(self):
        self.keeper.start()
        self.disable_config()
        self.hypr.clients[0]["pid"] += 1
        self.hypr.commands.clear()
        self.assertEqual(self.cleanup()["state"], "cleaned")
        self.assertFalse(any(isinstance(action, tuple) and action[0].startswith("window.") for action in self.hypr.commands))
        self.assertEqual(self.hypr.clients[0]["workspace"]["name"], SPECIAL)

    def test_malformed_config_does_not_trigger_window_recovery(self):
        self.keeper.start()
        self.config.write_text("{")
        self.assertEqual(self.keeper.update()["state"], "waiting")
        self.assertEqual(self.cleanup()["state"], "preserved")
        self.assertEqual(self.disables, [])

    def test_brief_disable_transition_is_debounced(self):
        self.keeper.start()
        self.disable_config()
        with patch.object(lifecycle.time, "monotonic", return_value=10):
            self.assertEqual(self.keeper.update()["state"], "waiting")
        atomic_json(self.config, self.original)
        self.assertEqual(self.keeper.update()["state"], "active")
        self.assertEqual(self.disables, [])

    def test_persistent_disable_is_cleaned_without_waiting_for_parent_eof(self):
        self.keeper.start()
        self.disable_config()
        with patch.object(lifecycle.time, "monotonic", side_effect=[10, 11]):
            self.assertEqual(self.keeper.update()["state"], "waiting")
            self.assertEqual(self.keeper.update()["state"], "cleaned")

    def test_preferences_survive_host_entry_removal_and_merge_only_missing(self):
        self.keeper.start()
        checkpoint = json.loads(self.keeper.preferences_path.read_text())["settings"]
        self.disable_config()
        atomic_json(self.config, dict(plugins=[dict(id=PLUGIN, presentation="bubbles")], other=self.original["other"]))
        successor = self.make_keeper("generation-two")
        successor.start()
        actual = json.loads(self.config.read_text())
        entry = actual["plugins"][0]
        self.assertEqual(entry["presentation"], "bubbles")
        self.assertEqual(entry["previewDelay"], 123)
        self.assertEqual(entry["animationSpeed"], checkpoint["animationSpeed"])
        self.assertEqual(actual["other"], self.original["other"])

    def test_checkpoint_ignores_unknown_keys_and_preserves_empty_shortcuts(self):
        self.keeper.start()
        self.keeper.update(dict(settings=dict(restoreOldestShortcut="", previewDelay=321,
                                             unrelatedSecret="must not persist")))
        saved = json.loads(self.keeper.preferences_path.read_text())["settings"]
        self.assertEqual(saved["previewDelay"], 321)
        self.assertEqual(saved["restoreOldestShortcut"], "")
        self.assertNotIn("unrelatedSecret", saved)

    def test_latest_pipe_preferences_survive_entry_removal(self):
        self.keeper.start()
        self.disable_config()
        self.keeper.update(dict(settings=dict(previewDelay=456)))
        saved = json.loads(self.keeper.preferences_path.read_text())["settings"]
        self.assertEqual(saved["previewDelay"], 456)

    def test_delayed_host_save_does_not_overwrite_newer_pipe_preferences(self):
        self.keeper.start()
        self.keeper.update(dict(settings=dict(previewDelay=456)))
        self.keeper.update()
        saved = json.loads(self.keeper.preferences_path.read_text())["settings"]
        self.assertEqual(saved["previewDelay"], 456)
        data = json.loads(self.config.read_text())
        data["plugins"][0]["previewDelay"] = 456
        atomic_json(self.config, data)
        self.keeper.update()
        self.assertIsNone(self.keeper.pending_settings)

    def test_invalid_shortcut_snapshot_does_not_terminate_recovery_guard(self):
        self.keeper.start()
        self.keeper.update(dict(settings=dict(minimizeShortcut="INVALID KEY", previewDelay=654)))
        saved = json.loads(self.keeper.preferences_path.read_text())["settings"]
        self.assertEqual(saved["previewDelay"], 654)
        self.assertEqual(saved["minimizeShortcut"], lifecycle.shortcuts.DEFAULT_SHORTCUTS["minimizeShortcut"])

    def test_tagged_interrupted_minimize_on_normal_workspace_is_recovered(self):
        self.keeper.start()
        with self.stash.locked():
            record = self.stash.state["windows"][0]
            record.update(phase="preparing", fullscreen=1)
            self.stash.save()
        self.hypr.clients[0].update(workspace=dict(id=1, name="1"), fullscreen=0,
                                    at=[500, 300], size=[1000, 700])
        self.disable_config()
        result = self.cleanup()
        self.assertEqual(result["restored"], 1)
        self.assertEqual(self.hypr.clients[0]["fullscreen"], 1)
        self.assertEqual(self.hypr.clients[0]["at"], [123, 177])
        self.assertEqual(self.hypr.clients[0]["size"], [777, 444])

    def test_untagged_interrupted_minimize_is_not_adopted(self):
        self.keeper.start()
        with self.stash.locked():
            self.stash.state["windows"][0]["phase"] = "preparing"
            self.stash.save()
        self.hypr.clients[0].update(workspace=dict(id=1, name="1"), tags=[])
        self.disable_config()
        self.hypr.commands.clear()
        result = self.cleanup()
        self.assertEqual(result["restored"], 0)
        self.assertFalse(any(isinstance(action, tuple) and action[0].startswith("window.") for action in self.hypr.commands))

    def test_config_reload_message_reclaims_lua_owner_before_sync(self):
        self.keeper.start()
        self.owner = None
        result = self.keeper.update(dict(action="sync"))
        self.assertEqual(result["state"], "ready")
        self.assertEqual(self.claims, ["generation-one", "generation-one"])
        self.assertEqual(self.owner, "generation-one")

    def test_unknown_start_waits_then_initializes_and_restores_preferences(self):
        atomic_json(self.keeper.preferences_path, dict(version=1, settings=dict(iconOpacity=72)))
        self.config.write_text("{")
        self.assertEqual(self.keeper.start()["state"], "waiting")
        atomic_json(self.config, dict(plugins=[dict(id=PLUGIN)]))
        self.assertEqual(self.keeper.update()["state"], "ready")
        self.assertEqual(json.loads(self.config.read_text())["plugins"][0]["iconOpacity"], 72)

    def test_removal_during_failed_startup_recovers_previous_stash(self):
        def removed_during_migration(**kwargs):
            shutil.rmtree(self.root)
            self.disable_config()
            raise RuntimeError("Checkout removed during migration")
        self.keeper.migrate = removed_during_migration
        with patch.dict(os.environ, {"HYPRLAND_INSTANCE_SIGNATURE": ""}):
            with self.assertRaisesRegex(RuntimeError, "removed during migration"):
                self.keeper.start()
        result = self.keeper.recover_after_error()
        self.assertEqual(result["state"], "cleaned")
        self.assertEqual(result["restored"], 1)
        self.assertEqual(self.hypr.clients[0]["workspace"]["id"], 1)

    def test_guardian_exception_path_runs_cached_startup_removal_cleanup(self):
        def removed_during_migration(**kwargs):
            shutil.rmtree(self.root)
            self.disable_config()
            raise RuntimeError("Checkout removed during startup")
        self.keeper.migrate = removed_during_migration
        with patch.dict(os.environ, {"HYPRLAND_INSTANCE_SIGNATURE": ""}), \
                patch.object(lifecycle, "LifecycleKeeper", return_value=self.keeper), \
                patch.object(lifecycle.signal, "signal"):
            result = lifecycle.guardian(self.keeper.owner)
        self.assertEqual(result, 0)
        self.assertEqual(self.events[-1]["state"], "cleaned")
        self.assertEqual(self.hypr.clients[0]["workspace"]["id"], 1)

    def test_eof_watchdog_survives_shell_gap_then_cleans_removed_checkout(self):
        read, write = os.pipe()
        connected = os.fdopen(read, "rb", buffering=0)
        self.addCleanup(connected.close)
        ready = threading.Event()
        outcome = []
        self.keeper.emit = lambda value: ready.set() if value.get("state") == "ready" else None
        def run():
            outcome.append(lifecycle.run_loop(connected, self.keeper))
        with patch.object(lifecycle, "POLL_SECONDS", .01), patch.object(lifecycle, "DISABLE_GRACE", .01):
            thread = threading.Thread(target=run)
            thread.start()
            try:
                self.assertTrue(ready.wait(2))
                os.close(write)
                write = None
                time.sleep(.04)
                self.assertTrue(thread.is_alive(), "A shell restart must retain removal recovery")
                self.assertEqual(self.hypr.clients[0]["workspace"]["name"], SPECIAL)
                shutil.rmtree(self.root)
                thread.join(2)
                self.assertFalse(thread.is_alive())
                self.assertEqual(outcome[0]["state"], "cleaned")
                self.assertEqual(self.hypr.clients[0]["workspace"]["id"], 1)
            finally:
                if write is not None:
                    os.close(write)
                if thread.is_alive():
                    self.disable_config()
                    thread.join(2)

    def test_partial_migration_failure_still_restores_runtime_monitor_profile(self):
        bindings = self.config.parent.parent / "hypr/bindings.lua"
        bindings.parent.mkdir(parents=True)
        bindings.write_text("legacy loader\n")
        def failed_migration(**kwargs):
            bindings.write_text("retired loader\n")
            raise RuntimeError("Later migration edit failed")
        self.keeper.migrate = failed_migration
        with patch.dict(os.environ, {"HYPRLAND_INSTANCE_SIGNATURE": ""}), \
                patch.object(self.keeper, "_reload_preserving_monitors") as restore:
            with self.assertRaisesRegex(RuntimeError, "Later migration edit failed"):
                self.keeper.start()
        restore.assert_called_once()

    def test_recovery_notification_is_generic_bounded_and_best_effort(self):
        with patch.object(lifecycle.subprocess, "run") as run:
            lifecycle.notify_failure()
        args, kwargs = run.call_args
        self.assertEqual(args[0][0], "notify-send")
        self.assertIn("Window Stash recovery needs attention", args[0])
        self.assertNotIn(str(self.base), " ".join(args[0]))
        self.assertEqual(kwargs["timeout"], 3)
        self.assertEqual(kwargs["stdout"], subprocess.DEVNULL)
        self.assertEqual(kwargs["stderr"], subprocess.DEVNULL)
        with patch.object(lifecycle.subprocess, "run", side_effect=FileNotFoundError):
            lifecycle.notify_failure()

    def test_failed_notification_does_not_mask_recovery_failure(self):
        self.keeper.start()
        self.disable_config()
        self.hypr.fail = "window.move"
        self.keeper.notifier = lambda: (_ for _ in ()).throw(RuntimeError("Notification unavailable"))
        with patch.object(lifecycle.time, "sleep"):
            result = self.cleanup()
        self.assertEqual(result["state"], "error")
        self.assertEqual(result["remaining"], 1)

    def test_batched_settings_then_sync_preserves_latest_preferences_on_remove(self):
        read, write = os.pipe()
        connected = os.fdopen(read, "rb", buffering=0)
        self.addCleanup(connected.close)
        ready = threading.Event()
        outcome = []
        self.keeper.emit = lambda value: ready.set() if value.get("state") == "ready" else None
        with patch.object(lifecycle, "POLL_SECONDS", .01), patch.object(lifecycle, "DISABLE_GRACE", .01):
            thread = threading.Thread(target=lambda: outcome.append(lifecycle.run_loop(connected, self.keeper)))
            thread.start()
            try:
                self.assertTrue(ready.wait(2))
                self.disable_config()
                os.write(write, b'{"settings":{"previewDelay":432}}\n{"action":"sync"}\n')
                os.close(write)
                write = None
                thread.join(2)
                self.assertFalse(thread.is_alive())
                self.assertEqual(outcome[0]["state"], "cleaned")
                saved = json.loads(self.keeper.preferences_path.read_text())["settings"]
                self.assertEqual(saved["previewDelay"], 432)
            finally:
                if write is not None:
                    os.close(write)
                if thread.is_alive():
                    self.disable_config()
                    thread.join(2)

    @unittest.skipUnless(hasattr(os, "fork"), "Guardian detachment requires POSIX fork")
    def test_detached_guardian_restores_after_transport_is_killed_and_source_deleted(self):
        source = Path(__file__).resolve().parents[1]
        package = self.base / "copied-plugin"
        shutil.copytree(source / "controller", package / "controller", ignore=shutil.ignore_patterns("__pycache__"))
        (package / "manifest.json").write_text(json.dumps(dict(id=PLUGIN)))
        script = r'''
import json, pathlib, sys
package, tests, base = map(pathlib.Path, sys.argv[1:])
sys.path.insert(0, str(package / 'controller'))
sys.path.insert(1, str(tests))
import lifecycle
from stash import PLUGIN, Stash, atomic_json
from test_controller import FakeHypr, client
def guardian(owner):
    hypr = FakeHypr()
    hypr.clients[0]['floating'] = True
    hypr.clients.append(client('0x9', pid=999))
    config = base / 'process-config/omarchy/shell.json'
    atomic_json(config, dict(plugins=[dict(id=PLUGIN)]))
    stash = Stash(hypr, base / 'process-runtime', config, base / 'process-state')
    with stash.locked(): stash.minimize('0x1')
    hypr.active = '0x9'
    lifecycle.shortcuts.claim = lambda *a, **kw: None
    lifecycle.shortcuts.sync = lambda *a, **kw: dict(activeShortcuts={}, conflicts={})
    lifecycle.shortcuts.disable = lambda *a, **kw: None
    keeper = lifecycle.LifecycleKeeper(owner, stash, package, lifecycle.emit, migrate=False)
    result = lifecycle.run_loop(sys.stdin.buffer, keeper)
    print(json.dumps(dict(guardianState=result['state'], targetWorkspace=hypr.clients[0]['workspace']['id'])), flush=True)
    return 0
lifecycle.guardian = guardian
sys.argv = ['lifecycle.py', '--owner', 'process-test']
raise SystemExit(lifecycle.main())
'''
        process = subprocess.Popen([sys.executable, "-u", "-c", script, str(package), str(source / "tests"), str(self.base)],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        guardian_pid = None
        try:
            self.assertTrue(select.select([process.stdout], [], [], 5)[0], "Guardian did not become ready")
            first = json.loads(process.stdout.readline())
            self.assertEqual(first["state"], "ready")
            marker = json.loads((self.base / "process-runtime/lifecycle-owner.json").read_text())
            guardian_pid = marker["pid"]
            self.assertNotEqual(guardian_pid, process.pid)
            os.kill(process.pid, signal.SIGKILL)
            process.wait(timeout=3)
            shutil.rmtree(package)
            process.stdin.close()
            process.stdin = None
            stdout, stderr = process.communicate(timeout=5)
            self.assertFalse(stderr.strip(), stderr)
            result = json.loads(stdout.splitlines()[-1])
            self.assertEqual(result, dict(guardianState="cleaned", targetWorkspace=1))
        finally:
            if process.poll() is None:
                process.kill()
            if guardian_pid:
                try:
                    os.kill(guardian_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            process.communicate(timeout=3)


if __name__ == "__main__":
    unittest.main()
