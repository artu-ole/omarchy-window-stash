#!/usr/bin/env python3
"""Session-local window stash. No daemon, dependencies, or shell evaluation."""
import argparse
import contextlib
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import uuid

PLUGIN = "community.window-stash"
SPECIAL = "special:minimized"
PREFIX = "window-stash-"
DEFAULTS = dict(presentation="dock", scope="global", restoreDestination="current", grouping="window")
CHOICES = dict(presentation=("dock", "bubbles"), scope=("global", "workspace"),
               restoreDestination=("current", "original"), grouping=("window", "app"))


def lua(value):
    """Encode scalars for Lua without evaluating user/window strings as code."""
    if value is None:
        return "nil"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return '"' + ''.join('\\%03d' % b if b < 32 or b >= 127 else
                         '\\' + chr(b) if b in (34, 92) else chr(b)
                         for b in str(value).encode()) + '"'


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".stash-")
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_json(path, default):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return default


def monitor_identity(monitor):
    return "|".join(str(monitor.get(k, "")) for k in ("make", "model", "serial", "description"))


def workarea(m):
    scale = m.get("scale", 1) or 1
    w, h = m["width"], m["height"]
    if m.get("transform", 0) % 2:
        w, h = h, w
    left, top, right, bottom = m.get("reserved", [0, 0, 0, 0])
    return [m["x"] + left, m["y"] + top,
            max(1, round(w / scale) - left - right), max(1, round(h / scale) - top - bottom)]


def restored_geometry(record, monitor):
    area = workarea(monitor)
    width = min(record["size"][0], area[2])
    height = min(record["size"][1], area[3])
    x = monitor["x"] + record["relativePosition"][0]
    y = monitor["y"] + record["relativePosition"][1]
    return [max(area[0], min(x, area[0] + area[2] - width)),
            max(area[1], min(y, area[1] + area[3] - height)), width, height]


def eligible(records, workspace, scope):
    return sorted((r for r in records if scope == "global" or r["origin"]["id"] == workspace),
                  key=lambda r: r["order"], reverse=True)


class Hyprland:
    def call(self, *args):
        result = subprocess.run(["hyprctl", *args], capture_output=True, text=True, timeout=8)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Hyprland IPC failed")
        return result.stdout.strip()

    def read(self, subject):
        return json.loads(self.call(subject, "-j"))

    def eval(self, code):
        output = self.call("eval", code)
        if output != "ok":
            raise RuntimeError(output)

    def dispatch(self, dispatcher, **args):
        fields = ", ".join(k + " = " + lua(v) for k, v in args.items())
        self.eval("hl.dispatch(hl.dsp." + dispatcher + "({" + fields + "}))")

    def client(self, address):
        return next((c for c in self.read("clients") if c["address"] == address), None)


class Stash:
    def __init__(self, hypr=None, runtime=None, config=None, state_home=None):
        self.hypr = hypr or Hyprland()
        signature = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", "")
        if runtime is None and not signature:
            raise RuntimeError("Run Window Stash inside a Hyprland session")
        self.directory = Path(runtime) if runtime else Path(os.environ["XDG_RUNTIME_DIR"]) / "omarchy-window-stash" / re.sub(r"[^A-Za-z0-9_-]", "_", signature)
        self.path = self.directory / "state.json"
        self.config = Path(config) if config else Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "omarchy/shell.json"
        self.positions = (Path(state_home) if state_home else Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))) / "omarchy/window-stash/bubbles.json"
        self.state = {"version": 1, "windows": []}

    @contextlib.contextmanager
    def locked(self):
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (self.directory / "lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self.state = read_json(self.path, self.state)
            if not self.path.exists():
                self.save()
            yield self

    def save(self):
        atomic_json(self.path, self.state)

    def settings(self):
        config = read_json(self.config, {})
        entry = next((p for p in config.get("plugins", []) if p.get("id") == PLUGIN), {})
        return {k: entry.get(k) if entry.get(k) in CHOICES[k] else v for k, v in DEFAULTS.items()}

    def snapshot(self):
        return self.hypr.read("clients"), self.hypr.read("monitors"), self.hypr.read("workspaces")

    def matches(self, record, client):
        return (client and record["address"] == client["address"] and record["pid"] == client["pid"]
                and (not record.get("stableId") or record["stableId"] == client.get("stableId")))

    def reconcile(self, clients):
        live = {c["address"]: c for c in clients}
        old = json.dumps(self.state, sort_keys=True)
        kept = []
        for r in self.state["windows"]:
            c = live.get(r["address"])
            if not self.matches(r, c):
                continue
            tagged = r["tag"] in c.get("tags", [])
            parked = c["workspace"]["name"] == SPECIAL
            if parked and tagged:
                r["phase"] = "stashed"
            elif r["phase"] == "restoring" and tagged:
                pass  # Preserve metadata after a partial geometry failure for retry.
            else:
                continue
            r.update(title=c["title"], app=c["class"])
            kept.append(r)
        self.state["windows"] = kept
        if old != json.dumps(self.state, sort_keys=True):
            self.save()

    def invoke_context(self, monitor_name=None, workspace=None):
        monitors = self.hypr.read("monitors")
        m = next((m for m in monitors if m["name"] == monitor_name), None) if monitor_name else None
        m = m or next((m for m in monitors if m.get("focused")), None)
        if not m:
            raise RuntimeError("No available monitor")
        return m, workspace or m["activeWorkspace"]["id"]

    def minimize(self, address=None):
        clients, monitors, _ = self.snapshot()
        self.reconcile(clients)
        active = self.hypr.read("activewindow") if address is None else next((c for c in clients if c["address"] == address), {})
        if not active or not active.get("mapped", True):
            return {"ok": True, "action": "noop", "reason": "No focused application window"}
        if active["workspace"]["name"].startswith("special:"):
            return {"ok": True, "action": "noop", "reason": "Special workspaces are separate from Window Stash"}
        if any(r["address"] == active["address"] for r in self.state["windows"]):
            return {"ok": True, "action": "noop"}
        monitor = next(m for m in monitors if m["id"] == active["monitor"])
        ident = uuid.uuid4().hex
        record = dict(id=ident, tag=PREFIX+ident, address=active["address"], pid=active["pid"],
                      stableId=active.get("stableId"), title=active["title"], app=active["class"],
                      origin=active["workspace"].copy(), monitor=monitor_identity(monitor),
                      monitorName=monitor["name"], slot=((active["workspace"]["id"] - 1) % 10) + 1,
                      floating=active["floating"], pinned=active.get("pinned", False),
                      fullscreen=active.get("fullscreen", 0), fullscreenClient=active.get("fullscreenClient", 0),
                      size=active["size"], relativePosition=[active["at"][0]-monitor["x"], active["at"][1]-monitor["y"]],
                      order=time.time_ns(), phase="preparing")
        self.state["windows"].append(record)
        self.save()  # Snapshot reaches disk before any window state is changed.
        target = "address:" + active["address"]
        try:
            self.hypr.dispatch("window.tag", window=target, tag="+"+record["tag"])
            if record["fullscreen"] or record["fullscreenClient"]:
                self.hypr.dispatch("window.fullscreen_state", window=target, internal=0, client=0, action="set")
                base = self.hypr.client(active["address"])
                record.update(size=base["size"], relativePosition=[base["at"][0]-monitor["x"],base["at"][1]-monitor["y"]])
                self.save()
            if record["pinned"]:
                self.hypr.dispatch("window.pin", window=target, action="toggle")
            if len(active.get("grouped", [])) > 1:
                self.hypr.dispatch("window.move", window=target, out_of_group=True)
            self.hypr.dispatch("window.move", window=target, workspace=SPECIAL, follow=False)
            after = self.hypr.client(active["address"])
            if not after or after["workspace"]["name"] != SPECIAL:
                raise RuntimeError("The window did not reach the stash")
            record["phase"] = "stashed"
            self.save()
            # Avoid leaving keyboard focus on the parked client.
            self.hypr.dispatch("focus", workspace=self.workspace_selector(record["origin"]))
            return {"ok": True, "action": "minimized", "id": ident}
        except Exception as error:
            record["lastError"] = str(error)
            record["phase"] = "restoring"
            self.save()
            raise

    @staticmethod
    def workspace_selector(workspace):
        return str(workspace["id"]) if workspace["id"] > 0 else "name:"+workspace["name"]

    def destination(self, record, to, monitor_name=None, workspace=None):
        current, current_ws = self.invoke_context(monitor_name, workspace)
        if to == "current":
            return str(current_ws), current
        monitors = self.hypr.read("monitors")
        origin_monitor = next((m for m in monitors if monitor_identity(m) == record["monitor"]), None)
        workspaces = self.hypr.read("workspaces")
        if origin_monitor:
            existing = next((w for w in workspaces if w["id"] == record["origin"]["id"]), None)
            if existing:
                owner = next((m for m in monitors if m["name"] == existing["monitor"]), origin_monitor)
                return self.workspace_selector(existing), owner
            return self.workspace_selector(record["origin"]), origin_monitor
        # Current fixed-bank setup: carry the absent screen's local slot home.
        bank = ((current_ws - 1) // 10) * 10
        # Honor the user's existing fixed-bank configuration, including when
        # the laptop is temporarily showing a disconnected screen's guest ID.
        bank_file = self.config.parent.parent / "hypr/monitor-workspaces.lua"
        try:
            banks = dict(re.findall(r'\["([^"\n]+)"\]\s*=\s*(\d+)', bank_file.read_text()))
            bank = int(banks.get(current["name"], bank))
        except FileNotFoundError:
            pass
        return str(bank + record["slot"]), current

    def restore(self, ident, to=None, monitor=None, workspace=None):
        clients = self.hypr.read("clients")
        self.reconcile(clients)
        record = next((r for r in self.state["windows"] if r["id"] == ident or r["address"] == ident), None)
        if not record:
            return {"ok": True, "action": "noop", "reason": "Window is no longer stashed"}
        destination, dest_monitor = self.destination(record, to or self.settings()["restoreDestination"], monitor, workspace)
        target = "address:"+record["address"]
        record["phase"] = "restoring"
        self.save()
        try:
            self.hypr.dispatch("focus", monitor=dest_monitor["name"])
            self.hypr.dispatch("focus", workspace=destination)
            self.hypr.dispatch("window.move", window=target, workspace=destination, follow=False)
            self.hypr.dispatch("window.float", window=target, action="on" if record["floating"] else "off")
            if record["floating"]:
                x, y, width, height = restored_geometry(record, dest_monitor)
                self.hypr.dispatch("window.resize", window=target, x=width, y=height, relative=False)
                self.hypr.dispatch("window.move", window=target, x=x, y=y, relative=False)
            else:
                self.append_scrolling(record["address"], destination)
            self.hypr.dispatch("focus", window=target)
            pin_state = self.hypr.client(record["address"])
            if pin_state is None:
                raise RuntimeError("Window closed during restoration")
            if bool(pin_state.get("pinned")) != record["pinned"]:
                self.hypr.dispatch("window.pin", window=target, action="toggle")
            if record["fullscreen"] or record["fullscreenClient"]:
                self.hypr.dispatch("window.fullscreen_state", window=target, internal=record["fullscreen"],
                                   client=record["fullscreenClient"], action="set")
            after = self.hypr.client(record["address"])
            if not after or self.workspace_selector(after["workspace"]) != destination:
                raise RuntimeError("The window did not reach the destination workspace")
            if after["floating"] != record["floating"]:
                raise RuntimeError("A window rule prevented restoration of floating state")
            self.hypr.dispatch("window.tag", window=target, tag="-"+record["tag"])
            self.state["windows"].remove(record)
            self.save()
            return {"ok": True, "action": "restored", "id": record["id"], "workspace": after["workspace"]}
        except Exception as error:
            record["lastError"] = str(error)
            self.save()
            raise

    def append_scrolling(self, address, destination):
        # Query Lua layout state rather than infer order from off-screen coordinates.
        # Focus the terminal column first, then reinsert this exact window after it.
        code = '''local w = hl.get_window(%s)
local ws = hl.get_workspace(%s)
if w and ws and ws.tiled_layout == "scrolling" then
  hl.dispatch(hl.dsp.focus({window=w}))
  hl.dispatch(hl.dsp.window.float({window=w, action="on"}))
  local windows = hl.get_workspace_windows(ws)
  local last = nil
  local direction = hl.get_config("scrolling.direction")
  for _, candidate in pairs(windows) do
    if candidate.address ~= w.address and not candidate.floating then
      if not last then last = candidate else
        local vertical = direction == "up" or direction == "down"
        local axis = vertical and "y" or "x"
        local sign = (direction == "left" or direction == "up") and -1 or 1
        if candidate.at[axis] * sign > last.at[axis] * sign then last = candidate end
      end
    end
  end
  if last then hl.dispatch(hl.dsp.focus({window=last})) end
  hl.dispatch(hl.dsp.window.float({window=w, action="off"}))
end''' % (lua("address:"+address), lua(destination))
        self.hypr.eval(code)

    def listing(self):
        clients, monitors, workspaces = self.snapshot()
        self.reconcile(clients)
        return dict(ok=True, windows=sorted(self.state["windows"], key=lambda r:r["order"], reverse=True),
                    monitors=monitors, workspaces=workspaces, settings=self.settings(),
                    statePath=str(self.path), positions=read_json(self.positions, {}))

    def restore_last(self, to=None, monitor=None, workspace=None):
        self.reconcile(self.hypr.read("clients"))
        _, current = self.invoke_context(monitor, workspace)
        choices = eligible(self.state["windows"], current, self.settings()["scope"])
        return self.restore(choices[0]["id"], to, monitor, workspace) if choices else {"ok":True,"action":"noop"}

    def rebase(self, old, new):
        for record in self.state["windows"]:
            if record["origin"]["id"] == old:
                record["origin"] = dict(id=new, name=str(new))
                record["slot"] = (new - 1) % 10 + 1
        self.save()
        return {"ok":True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    minimize = sub.add_parser("minimize", help="Stash the focused window")
    minimize.add_argument("--address")
    for action in ("restore", "restore-last", "restore-all", "activate"):
        p = sub.add_parser(action)
        if action in ("restore", "activate"): p.add_argument("id")
        p.add_argument("--to", choices=("current","original"))
        p.add_argument("--monitor")
        p.add_argument("--workspace", type=int)
    for action in ("list", "status"):
        sub.add_parser(action)
    pos = sub.add_parser("position")
    pos.add_argument("monitor")
    pos.add_argument("key")
    pos.add_argument("x", type=float)
    pos.add_argument("y", type=float)
    rebase = sub.add_parser("rebase")
    rebase.add_argument("old", type=int)
    rebase.add_argument("new", type=int)
    args = parser.parse_args(argv)
    try:
        stash = Stash()
        with stash.locked():
            if args.command == "minimize": result=stash.minimize(args.address)
            elif args.command == "restore": result=stash.restore(args.id,args.to,args.monitor,args.workspace)
            elif args.command == "activate":
                result=stash.restore(args.id,args.to,args.monitor,args.workspace)
                if result.get("action")=="noop":
                    address=args.id if args.id.startswith("0x") else "0x"+args.id
                    if stash.hypr.client(address):
                        stash.hypr.dispatch("focus",window="address:"+address)
                        result=dict(ok=True,action="activated")
            elif args.command == "restore-last": result=stash.restore_last(args.to,args.monitor,args.workspace)
            elif args.command == "restore-all":
                context, workspace=stash.invoke_context(args.monitor,args.workspace)
                stash.reconcile(stash.hypr.read("clients"))
                results=[]
                for r in list(stash.state["windows"]):
                    results.append(stash.restore(r["id"],args.to or "current",context["name"],workspace))
                result=dict(ok=True,results=results)
            elif args.command == "rebase": result=stash.rebase(args.old,args.new)
            elif args.command == "position":
                positions=read_json(stash.positions,{})
                positions.setdefault(args.monitor,{})[args.key]=[args.x,args.y]
                atomic_json(stash.positions,positions)
                result=dict(ok=True)
            else: result=stash.listing()
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as error:
        print(json.dumps(dict(ok=False,error=str(error))))
        return 1


if __name__ == "__main__":
    sys.exit(main())
