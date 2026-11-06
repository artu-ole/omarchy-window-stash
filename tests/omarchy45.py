#!/usr/bin/env python3
"""Native Omarchy 4.5 dock coexistence, migration and workspace-mode checks.

Install this checkout first. Only owned fixtures and previously absent
workspaces are changed; NativeSession preserves the user's desktop, and the
mode files are restored separately. Run one desktop suite at a time.
"""
import json
import os
from pathlib import Path
import subprocess
import time

from desktop_test import desktop_test
from live import command, configure, h, wait
from native_session import NativeSession
from stash import LEGACY_SPECIAL, SPECIAL, lua


def window_state(address):
    client = h.client(address)
    return {key: client[key] for key in ("workspace", "tags", "at", "size", "floating", "pid", "stableId")}


def native_dock_membership(clients):
    """Use the installed dock's real model against current compositor clients."""
    source = """
const fs = require('node:fs'), vm = require('node:vm');
const model = vm.createContext({});
vm.runInContext(fs.readFileSync('/usr/share/omarchy/shell/plugins/dock/DockModel.js', 'utf8'), model);
const clients = JSON.parse(fs.readFileSync(0, 'utf8'));
const result = {};
for (const client of clients) result[client.address] = model.isDockWindow({
  key: client.class || client.address, hasEntry: false,
  workspaceId: client.workspace.id,
  minimized: model.isMinimizedWorkspace(client.workspace.name)
});
process.stdout.write(JSON.stringify(result));
"""
    result = subprocess.run(["node", "-e", source], input=json.dumps(clients),
                            capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


class WorkspaceModes:
    def __init__(self, workspaces):
        directory = Path(os.environ.get("XDG_STATE_HOME", Path.home()/".local/state"))/"omarchy/workspace-layouts"
        self.saved = {}
        for workspace in workspaces:
            path = directory/(str(workspace)+".lua")
            mode = subprocess.check_output(["omarchy-hyprland-workspace-layout-current", str(workspace)], text=True).strip()
            assert mode in ("dwindle", "scrolling", "floating"), ("Unknown original workspace mode", mode)
            self.saved[workspace] = (path, path.read_bytes() if path.exists() else None, mode)

    def set(self, workspace, mode):
        path, _, _ = self.saved[workspace]
        path.parent.mkdir(parents=True, exist_ok=True)
        code = "o.workspace_mode({ workspace = "+lua(str(workspace))+", mode = "+lua(mode)+" })"
        # The native dock reads the saved mode, while the compositor applies
        # the same declaration. Save before applying in case titlebars reload.
        path.write_text(code+"\n")
        h.eval(code)
        wait(lambda: subprocess.check_output(["omarchy-hyprland-workspace-layout-current", str(workspace)],
                                              text=True).strip() == mode,
             "The native layout reader did not observe "+mode)

    def restore(self):
        errors = []
        for workspace, (path, data, mode) in self.saved.items():
            try:
                if data is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_bytes(data)
            except OSError as error:
                errors.append(str(error))
            try:
                h.eval("o.workspace_mode({ workspace = "+lua(str(workspace))+", mode = "+lua(mode)+" })")
            except RuntimeError as error:
                errors.append(str(error))
        if errors:
            raise RuntimeError("Workspace-mode cleanup failed: "+"; ".join(errors))


@desktop_test("Omarchy 4.5 dock and workspace compatibility")
def main():
    with NativeSession() as session:
        modes = WorkspaceModes([session.workspace, session.workspace+1])
        try:
            modes.set(session.workspace, "dwindle")
            for key, value in dict(presentation="dock", scope="workspace", grouping="window",
                                   hoverPreview="off", animations="off", restoreDestination="current").items():
                configure(key, value)

            owned, _ = session.spawn(app="org.windowstash.CompatibilityOwned", workspace=session.workspace)
            h.dispatch("window.float", window="address:"+owned, action="on")
            h.dispatch("window.resize", window="address:"+owned, x=622, y=411, relative=False)
            h.dispatch("window.move", window="address:"+owned, x=session.monitor["x"]+120,
                       y=session.monitor["y"]+120, relative=False)
            original_geometry = (h.client(owned)["at"], h.client(owned)["size"])
            record = session.park(owned)

            native, _ = session.spawn(app="org.windowstash.CompatibilityNative", workspace=session.workspace)
            h.dispatch("window.tag", window="address:"+native, tag="+omarchy-minimized-from-"+str(session.workspace))
            h.dispatch("window.move", window="address:"+native, workspace=LEGACY_SPECIAL, follow=False)
            h.dispatch("focus", workspace=str(session.workspace))
            native_before = window_state(native)
            # Simulate an existing 1.23.x ledger without inventing state or
            # tags. Background reconciliation may legitimately win this race.
            h.dispatch_owned("window.move", record, parked=True, workspace=LEGACY_SPECIAL, follow=False)
            listing = command("list")
            migrated = next(window for window in listing["windows"] if window["id"] == record["id"])
            assert migrated == record, "Legacy migration rewrote saved restore metadata"
            assert h.client(owned)["workspace"]["name"] == SPECIAL, "Owned legacy window did not migrate"
            assert window_state(native) == native_before, "Migration changed a native minimized window"
            membership = native_dock_membership(h.read("clients"))
            assert membership[native] and not membership[owned], "The native dock also claims a private stashed window"
            assert native not in [window["address"] for window in listing["windows"]], "Native minimized window was adopted"
            print("PASS exact legacy migration, unchanged saved geometry and native minimized-window isolation", flush=True)

            tiled, _ = session.spawn(app="org.windowstash.CompatibilityTiled", workspace=session.workspace)
            h.dispatch("window.float", window="address:"+tiled, action="off")
            tiled_record = session.park(tiled)
            floating_workspace = session.workspace+1
            # Floating keeps its last tiled layout. Exercise scrolling under
            # it so restore must not run the tiled-width reinsertion path.
            modes.set(floating_workspace, "scrolling")
            modes.set(floating_workspace, "floating")
            h.dispatch("focus", workspace=str(floating_workspace))
            result = command("restore", tiled_record["id"], "--to", "current", "--monitor",
                             session.monitor["name"], "--workspace", floating_workspace)
            assert result["action"] == "restored", result
            wait(lambda: (client := h.client(tiled)) and client["workspace"]["id"] == floating_workspace
                 and client["floating"] and "omarchy-floating-workspace" in client["tags"],
                 "Restoring into a native floating workspace left the window tiled")
            time.sleep(.15)
            assert h.client(tiled)["floating"], "A deferred workspace handler changed the restored state"
            before = window_state(tiled)
            assert command("minimize", "--address", tiled)["action"] == "noop", "Floating mode did not defer to the native dock"
            assert window_state(tiled) == before, "Deferring minimize mutated the floating window"
            print("PASS tiled-window restore into native floating mode and unchanged native minimize ownership", flush=True)

            subprocess.run(["omarchy-hyprland-window-minimize", tiled], check=True)
            wait(lambda: h.client(tiled)["workspace"]["name"] == LEGACY_SPECIAL,
                 "Native minimize did not move its own window")
            assert all(window["address"] != tiled for window in command("list")["windows"]), "Native minimize was adopted by the plugin"
            assert native_dock_membership(h.read("clients"))[tiled], "The native dock lost its minimized window"
            h.dispatch("window.move", window="address:"+tiled, workspace=str(floating_workspace), follow=False)
            modes.set(floating_workspace, "dwindle")
            wait(lambda: "omarchy-floating-workspace" not in h.client(tiled)["tags"],
                 "Returning to tiling retained the native floating-workspace tag")
            assert not h.client(tiled)["floating"], "Leaving native floating mode did not tile its restored window again"
            result = command("minimize", "--address", tiled)
            assert result["action"] == "minimized", "Tiling minimize did not resume after leaving floating mode"
            assert h.client(tiled)["workspace"]["name"] == SPECIAL
            print("PASS native minimize remains independent and plugin stashing resumes in tiling mode", flush=True)

            command("restore", record["id"], "--to", "original", "--monitor", session.monitor["name"])
            assert (h.client(owned)["at"], h.client(owned)["size"]) == original_geometry, "Migrated floating geometry did not restore exactly"
            print("PASS migrated floating window restores its original size and position", flush=True)
        finally:
            modes.restore()


if __name__ == "__main__":
    main()
