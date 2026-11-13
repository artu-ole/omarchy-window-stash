#!/usr/bin/env python3
"""Session-local window stash. No daemon, dependencies, or shell evaluation."""
import argparse
import contextlib
import fcntl
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import uuid

# The shell watches the checkout for code changes. Runtime imports must not
# create cache files there and trigger a service reload.
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import shortcuts
from bridge_runtime import bridge_gate

PLUGIN = "community.window-stash"
SPECIAL = "special:window-stash"
LEGACY_SPECIAL = "special:minimized"
PREFIX = "window-stash-"
FULLSCREEN_CLEANUP_PENDING = 'Window Stash preview fullscreen cleanup is pending'
PREVIEW_MAX_DIMENSION = 8192
PREVIEW_MAX_PIXELS = 16_777_216
MAX_PREVIEW_FOLD_IDS = 256
LOCAL_SHORTCUT_DEFAULTS = {"floatingPreviewExitShortcut": "CTRL + ALT + Escape"}
DEFAULTS = dict(presentation="floating", scope="global", restoreDestination="current", grouping="window", iconShape="auto", sizePreset="100", floatingDirection="vertical", floatingAnimation="arc", dragMotion="physics", dockSide="bottom", staticDockLock="locked", floatingPlacement="edges", dockCorners="theme", dockCornerRadius=12, iconFrame="hidden", dockFrame="hidden", animations="full", animationSpeed="normal", dockOpacity=100, iconOpacity=100,
                hoverPreview="off", livePreviewCompatibility="standard", previewSize="medium", previewPlacement="auto", previewTitles="shown", previewDelay=400, previewHideDelay=200,
                floatingPreviewSizing="free", floatingPreviewScale="100", floatingPreviewUpdate="hover",
                floatingPreviewTitles="hidden", floatingPreviewFrame="hidden", floatingPreviewLock="unlocked",
                floatingPreviewInteraction="off", floatingPreviewActivation="explicit", floatingPreviewKeyboard="mouse",
                floatingPreviewInteractionFps="60", floatingPreviewControls="hover", floatingPreviewFullscreen="preview")
DEFAULTS.update(shortcuts.DEFAULT_SHORTCUTS)
DEFAULTS.update(LOCAL_SHORTCUT_DEFAULTS)
CHOICES = dict(presentation=("dock", "bubbles", "floating", "previews"), scope=("global", "workspace"),
               restoreDestination=("current", "original"), grouping=("window", "app"),
               iconShape=("auto", "circle", "square", "rounded", "squircle"),
               sizePreset=("50", "75", "100", "125", "150", "175", "200", "250", "300"),
               floatingDirection=("vertical", "horizontal"), floatingAnimation=("arc", "glide", "cascade", "spring", "swing", "matryoshka", "matryoshka-hop", "jumping"), dragMotion=("physics", "direct"), dockSide=("bottom", "top", "left", "right"), staticDockLock=("locked", "unlocked"),
               floatingPlacement=("edges", "free"), dockCorners=("theme", "custom"),
               dockCornerRadius=range(65), iconFrame=("shown", "hidden"), dockFrame=("shown", "hidden"),
               animations=("full", "reduced", "off"), animationSpeed=("slow", "relaxed", "normal", "fast", "ultrafast"), dockOpacity=range(101), iconOpacity=range(101),
               hoverPreview=("off", "still", "live"), livePreviewCompatibility=("standard", "enhanced"), previewSize=("small", "medium", "large"),
               previewPlacement=("auto", "above", "below", "left", "right"), previewTitles=("shown", "hidden"),
               previewDelay=range(1501), previewHideDelay=range(1001),
               floatingPreviewSizing=("free", "preset"),
               floatingPreviewScale=("50", "75", "100", "125", "150", "175", "200", "250", "300"),
               floatingPreviewUpdate=("still", "hover", "live"), floatingPreviewTitles=("shown", "hidden"),
               floatingPreviewFrame=("shown", "hidden"), floatingPreviewLock=("locked", "unlocked"),
               floatingPreviewInteraction=("off", "on"), floatingPreviewActivation=("explicit", "click"),
               floatingPreviewKeyboard=("mouse", "click"), floatingPreviewInteractionFps=("30", "60"),
               floatingPreviewControls=("hover", "always"), floatingPreviewFullscreen=("preview", "desktop"))


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


def window_identity_guard(record):
    """Resolve an exact toplevel before tagging or any other mutation."""
    checks = ["w", "w.pid == " + lua(record["pid"])]
    if record.get("stableId"):
        # clients JSON serializes stableId as hexadecimal; Lua exposes an integer.
        stable = record["stableId"]
        stable = int(stable, 16) if isinstance(stable, str) else stable
        checks.append("w.stable_id == " + lua(stable))
    return ("local w = hl.get_window(" + lua("address:" + record["address"]) + ")\n"
            + "if not (" + " and ".join(checks) + ") then error('Stashed window identity changed') end\n")


def owned_window_guard(record, parked=False):
    """Resolve and validate the exact owned toplevel inside one compositor call."""
    workspace = SPECIAL if parked is True else parked
    return (window_identity_guard(record)
            + ("if not (w.workspace and w.workspace.name == " + lua(workspace)
               + ") then error('Stashed window left the stash') end\n" if parked else "")
            + "local owned = false; for _, tag in ipairs(w.tags) do if tag == " + lua(record["tag"])
            + " then owned = true; break end end\n"
            + "if not owned then error('Window is no longer owned by the stash') end\n")


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


def preview_aspect(value):
    if type(value) not in (int, float) or not math.isfinite(value) or not .02 <= value <= 50:
        raise ValueError('Preview aspect must be a finite number between 0.02 and 50')
    return float(value)


def preview_fold_ids(value):
    if (not isinstance(value, (list, tuple)) or not 1 <= len(value) <= MAX_PREVIEW_FOLD_IDS
            or any(not isinstance(item, str) or not re.fullmatch(r'[0-9a-f]{32}', item) for item in value)):
        raise ValueError('Choose between 1 and 256 exact stash record IDs')
    return list(dict.fromkeys(value))


def forward_shortcut(action, hypr=None):
    """Ask the live shell to interpret one shortcut before acquiring any locks."""
    methods = {'restore-last': 'restoreLast', 'restore-oldest': 'restoreOldest'}
    arguments = ['omarchy-shell', 'window-stash']
    if action == 'minimize':
        point = (hypr or Hyprland()).read('cursorpos')
        if (not isinstance(point, dict) or any(type(point.get(axis)) not in (int, float)
                or not math.isfinite(point[axis]) or abs(point[axis]) > 1_000_000 for axis in ('x', 'y'))):
            raise RuntimeError('Could not read the current pointer position')
        arguments.extend(['minimizeAt', str(point['x']), str(point['y'])])
    elif action in methods:
        arguments.append(methods[action])
    else:
        raise ValueError('Unknown Window Stash shortcut action')
    try:
        result = subprocess.run(arguments, text=True, capture_output=True, timeout=8)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError('Window Stash could not reach its shell service; no window was minimized') from error
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()[-512:]
        raise RuntimeError('Window Stash shell shortcut failed'+(': '+detail if detail else ''))
    if result.stdout.strip():
        value = json.loads(result.stdout)
        if not isinstance(value, dict):
            raise RuntimeError('Window Stash returned an invalid shortcut response')
        return value
    return dict(ok=True, action='shortcut', command=action)


def preview_source_size(size, aspect, axis):
    aspect = preview_aspect(aspect)
    if axis not in ('width', 'height'):
        raise ValueError('Preview resize axis must be width or height')
    if (not isinstance(size, (list, tuple)) or len(size) != 2
            or any(type(value) not in (int, float) or not math.isfinite(value) or value <= 0 for value in size)):
        raise ValueError('The preview source has invalid dimensions')
    width, height = map(float, size)
    if axis == 'width':
        width = height * aspect
    else:
        height = width / aspect
    scale = min(1, PREVIEW_MAX_DIMENSION / max(width, height),
                math.sqrt(PREVIEW_MAX_PIXELS / (width * height)))
    width, height = max(1, round(width * scale)), max(1, round(height * scale))
    if width * height > PREVIEW_MAX_PIXELS:
        if width >= height:
            width = max(1, PREVIEW_MAX_PIXELS // height)
        else:
            height = max(1, PREVIEW_MAX_PIXELS // width)
    return [width, height]


def preview_geometry_owner(ident):
    return uuid.uuid5(uuid.NAMESPACE_URL, PLUGIN + ':preview-aspect:' + ident).hex


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

    def dispatch_identity(self, dispatcher, record, **args):
        fields = ["window = w"] + [k + " = " + lua(v) for k, v in args.items() if k != "window"]
        self.eval(window_identity_guard(record)
                  + "hl.dispatch(hl.dsp." + dispatcher + "({" + ", ".join(fields) + "}))")

    def dispatch_owned(self, dispatcher, record, parked=False, **args):
        fields = ["window = w"] + [k + " = " + lua(v) for k, v in args.items() if k != "window"]
        self.eval(owned_window_guard(record, parked)
                  + "hl.dispatch(hl.dsp." + dispatcher + "({" + ", ".join(fields) + "}))")

    def clear_preview_fullscreen(self, record):
        """Clear an exact override and await its client configure acknowledgements."""
        api = 'hl.plugin.window_stash_preview'
        identity = dict(id=record['id'], address=record['address'], pid=record['pid'],
                        stable_id=record['stableId'], tag=record['tag'])
        payload = '{'+','.join(key+'='+lua(value) for key, value in identity.items())+'}'
        prefix = ('local api=hl.plugin and '+api+'\n'
                  +'if not api or type(api.clear_fullscreen)~="function" then return end\n')
        capability_guard = ('local info=type(api.status)=="function" and api.status() or nil\n'
                            +'if type(info)=="table" and type(info.capabilities)=="table" '
                            +'and info.capabilities.constrainedFullscreen==true then\n'
                            +'assert(type(api.fullscreen_cleanup_pending)=="function",'
                            +lua('Reload preview support in Window Stash Settings before restoring fullscreen previews')+')\nend\n')
        self.eval(prefix+capability_guard+'local cleared,err=api.clear_fullscreen('+payload+'); assert(cleared~=nil,err)')
        Hyprland.wait_preview_fullscreen(self, record)

    def wait_preview_fullscreen(self, record):
        """Wait for an existing exit resize without changing client fullscreen."""
        identity = dict(id=record['id'], address=record['address'], pid=record['pid'],
                        stable_id=record['stableId'], tag=record['tag'])
        payload = '{'+','.join(key+'='+lua(value) for key, value in identity.items())+'}'
        prefix = ('local api=hl.plugin and hl.plugin.window_stash_preview\n'
                  +'if not api then return end\n')
        query = (prefix+'local info=type(api.status)=="function" and api.status() or nil\n'
                 +'if type(info)=="table" and type(info.capabilities)=="table" '
                 +'and info.capabilities.constrainedFullscreen==true then\n'
                 +'assert(type(api.fullscreen_cleanup_pending)=="function",'
                 +lua('Reload preview support in Window Stash Settings before resizing fullscreen previews')+')\nend\n'
                 +'if type(api.fullscreen_cleanup_pending)=="function" then\n'
                 +'local pending,err=api.fullscreen_cleanup_pending('+payload+')\n'
                 +'assert(type(pending)=="boolean",err or "Could not read preview fullscreen cleanup state")\n'
                 +'assert(not pending,'+lua(FULLSCREEN_CLEANUP_PENDING)+')\nend')
        deadline = time.monotonic()+2.5
        while True:
            try:
                self.eval(query)
                return
            except RuntimeError as error:
                if FULLSCREEN_CLEANUP_PENDING not in str(error):
                    raise
                if time.monotonic() >= deadline:
                    raise RuntimeError('Preview fullscreen is still finishing. The window remains stashed; try Restore again.') from error
                time.sleep(.05)

    def preview_geometry(self, record, size=None, expected_size=None, resizing=False):
        """Read or resize one private source in a single guarded transaction."""
        payload = '{'+','.join(key+'='+lua(value) for key, value in dict(
            id=record['id'], address=record['address'], pid=record['pid'],
            stable_id=record['stableId'], tag=record['tag']).items())+'}'
        owner = lua(preview_geometry_owner(record['id']))
        renewals = getattr(self, '_preview_lease_renewals', None)
        if renewals is None:
            renewals = self._preview_lease_renewals = {}
        renew_lease = time.monotonic() - renewals.get(record['id'], float('-inf')) >= .4
        code = (owned_window_guard(record, parked=True)
                +'assert(w.mapped==true,"The preview source is no longer mapped")\n'
                +'assert(w.floating==true,"The preview source is not parked as floating")\n'
                +'assert(w.fullscreen==0,"Restore desktop fullscreen before resizing a preview")\n'
                +'local api=hl.plugin and hl.plugin.window_stash_preview\n'
                +'local info=api and type(api.status)=="function" and api.status() or nil\n')
        if size is not None or resizing:
            code += ('assert(not (type(info)=="table" and (info.inputActive==true '
                     +'or (type(info.interaction)=="table" and info.interaction.active==true))),'
                     +'"Stop preview interaction before resizing")\n'
                     +'assert(not (type(info)=="table" and info.reloadPending==true),'
                     +'"Preview support is being reloaded; try again shortly")\n'
                     +'if api and type(api.fullscreen_cleanup_pending)=="function" then\n'
                     +'local pending,err=api.fullscreen_cleanup_pending('+payload+'); assert(type(pending)=="boolean",err)\n'
                     +'assert(not pending,'+lua(FULLSCREEN_CLEANUP_PENDING)+')\nend\n')
        if size is not None:
            if expected_size is not None:
                code += ('assert(w.size.x=='+lua(expected_size[0])+' and w.size.y=='+lua(expected_size[1])+','
                         +'"The preview source changed size; retry the resize")\n')
            code += ('if w.size.x~='+lua(size[0])+' or w.size.y~='+lua(size[1])+' then\n'
                     +'hl.dispatch(hl.dsp.window.resize({window=w,x='+lua(size[0])+',y='+lua(size[1])+',relative=false}))\nend\n'
                     +owned_window_guard(record, parked=True)
                     +'assert(w.mapped==true and w.floating==true and w.fullscreen==0,'
                     +'"The preview source changed during resizing")\n')
        code += (r'''local function quote(value) return '"'..tostring(value or ""):gsub('[%z\1-\31\\"]',function(c) return string.format('\\u%04x',string.byte(c)) end)..'"' end
local geometry=nil
if api and type(api.source_geometry)=="function" then
 local err; geometry,err=api.source_geometry('''+payload+r'''); assert(type(geometry)=="table",err or "Could not read source geometry")
elseif type(info)=="table" and type(info.capabilities)=="table" and info.capabilities.sourceGeometry==true then
 error("Reload preview support in Window Stash Settings before resizing previews")
end
local width,height=w.size.x,w.size.y
local fields={}
for _,key in ipairs({"width","height","configuredWidth","configuredHeight","surfaceWidth","surfaceHeight"}) do
 local value=geometry and geometry[key] or 0
 assert(type(value)=="number" and value==value and value>=0 and value<=1000000,"Invalid native source geometry")
 fields[#fields+1]=quote(key)..":"..tostring(value)
end
local ready=geometry and geometry.ready==true or false
local reason=geometry and tostring(geometry.reason or "") or "native-source-geometry-unavailable"
if ready and (math.abs(geometry.width-width)>.51 or math.abs(geometry.height-height)>.51) then
 ready=false; reason="source-geometry-changed"
end
local pending=reason=="configure-pending" or reason=="frame-pending" or reason=="animation-pending" or reason=="surface-unavailable"
local leaseWanted='''+lua(size is not None or resizing or record.get('previewResized') is True)+r'''
local renewed=false
if api and type(api.release)=="function" and (ready or not geometry or not pending) then
 api.release('''+owner+r''')
elseif geometry and pending and leaseWanted and '''+lua(renew_lease)+r''' then
 assert(type(api.update)=="function" and type(api.release)=="function","Reload preview support before resizing previews")
 local lease,err=api.update({owner='''+owner+r''',windows={'''+payload+r'''}})
 assert(type(lease)=="table" and lease.accepted==1,err or "The preview source changed before rendering could resume")
 renewed=true
end
return '{"size":['..tostring(width)..','..tostring(height)..'],"ready":'..tostring(ready)
 ..',"nativeRequired":'..tostring(geometry==nil)..',"reason":'..quote(reason)
 ..',"nativeAvailable":'..tostring(api~=nil)
 ..',"leaseRenewed":'..tostring(renewed)
 ..',"nativeGeometry":{'..table.concat(fields,",")..',"ready":'..tostring(ready)..',"reason":'..quote(reason)..'}}'
''')
        result = json.loads(self.call('repl', code))
        values = result.get('size')
        if (not isinstance(values, list) or len(values) != 2
                or any(type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 1_000_000 for value in values)
                or type(result.get('ready')) is not bool or type(result.get('nativeRequired')) is not bool
                or not isinstance(result.get('reason'), str) or len(result['reason']) > 512):
            raise RuntimeError('Could not read preview source geometry')
        result['aspect'] = values[0] / values[1]
        if result.pop('leaseRenewed', False):
            renewals[record['id']] = time.monotonic()
        elif result['ready'] or result['nativeRequired'] or result['reason'] not in (
                'configure-pending', 'frame-pending', 'animation-pending', 'surface-unavailable'):
            renewals.pop(record['id'], None)
        return result

    def release_preview_geometry(self, ident):
        getattr(self, '_preview_lease_renewals', {}).pop(ident, None)
        self.eval('local api=hl.plugin and hl.plugin.window_stash_preview; '
                  +'if api and type(api.release)=="function" then api.release('
                  +lua(preview_geometry_owner(ident))+') end')

    def park_owned(self, record, parked=False):
        width, height = map(lua, record["size"])
        resize = ("if w.size.x ~= " + width + " or w.size.y ~= " + height + " then\n"
                  + "hl.dispatch(hl.dsp.window.resize({window = w, x = " + width + ", y = " + height + ", relative = false}))\nend\n")
        # Keep the complete transition in one compositor transaction. Floating
        # before moving prevents the private workspace's tiler from configuring
        # this client or its already parked neighbors to a different geometry.
        # The saved floating flag remains the original restoration state.
        # Even an unchanged resize clears Hyprland's natural suspension. Avoid
        # it when geometry already matches, especially after the private move.
        self.eval(owned_window_guard(record, parked)
                  + 'if not w.floating then hl.dispatch(hl.dsp.window.float({window = w, action = "on"})) end\n'
                  + 'if not w.floating then error("The window could not be parked as floating") end\n'
                  + resize
                  + "hl.dispatch(hl.dsp.window.move({window = w, workspace = " + lua(SPECIAL) + ", follow = false}))\n"
                  + owned_window_guard(record, parked=True)
                  + 'if not w.floating then error("The private workspace refused floating parking") end\n'
                  + resize)

    def scrolling_width(self, record):
        output = self.call("repl", owned_window_guard(record)
            + 'local layout=w.layout; if layout and layout.name=="scrolling" and layout.column then return layout.column.width end; return 0')
        try:
            width = float(output)
        except (TypeError, ValueError):
            return None
        return width if math.isfinite(width) and 0 < width <= 1 else None

    def release_external(self, record, workspace, native_floating=False):
        # A user/switcher may move the client directly out of our workspace.
        # Undo only temporary parking state in its chosen destination, without
        # changing focus, geometry, pinning or fullscreen preferences there.
        guard = owned_window_guard(record, parked=workspace["name"])
        code = guard
        if not record["floating"]:
            if native_floating:
                code += 'hl.dispatch(hl.dsp.window.tag({window=w, tag="+omarchy-mode-floated"}))\n'
            desired = lua(native_floating)
            code += ('if w.floating ~= ' + desired + ' then hl.dispatch(hl.dsp.window.float({window=w, action='
                     + lua("on" if native_floating else "off") + '})) end\n'
                     + guard
                     + 'if w.floating ~= ' + desired + ' then error("A window rule prevented release of parking state") end\n')
        self.eval(code + 'hl.dispatch(hl.dsp.window.tag({window=w, tag=' + lua("-"+record["tag"]) + '}))')

    def close_stashed(self, record):
        self.dispatch_owned("window.close", record, parked=True)

    def preview_fold_ready(self, records, folding):
        # One read-only compositor transaction validates the complete group.
        # No client, fullscreen, focus, source geometry or workspace is changed.
        code = 'local accepted={}\n'
        if folding:
            wanted = '{'+','.join('['+lua(record['id'])+']=true' for record in records)+'}'
            code += ('local api=hl.plugin and hl.plugin.window_stash_preview\n'
                     +'local native=api and type(api.status)=="function" and api.status() or nil\n'
                     +'local input=native and native.interaction\n'
                     +'assert(not (input and input.active==true and ('+wanted+')[input.id]),'
                     +lua('Stop preview interaction before folding this window')+')\n')
        for record in records:
            code += ('do local valid=pcall(function()\n'+owned_window_guard(record, parked=True)
                     +'assert(w.mapped==true,"The preview source is no longer mapped")\nend)\n'
                     +'if valid then accepted[#accepted+1]='+lua(record['id'])+' end end\n')
        result = self.call('repl', code+'return table.concat(accepted,",")')
        return result.split(',') if result else []

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
        result={k: entry.get(k) if (not isinstance(CHOICES[k], range) or type(entry.get(k)) is int)
                and entry.get(k) in CHOICES[k] else v for k, v in DEFAULTS.items()
                if k not in shortcuts.DEFAULT_SHORTCUTS and k not in LOCAL_SHORTCUT_DEFAULTS}
        result.update(shortcuts.settings(entry))
        for key, default in LOCAL_SHORTCUT_DEFAULTS.items():
            try:
                result[key] = shortcuts.normalize(entry.get(key, default))
            except ValueError:
                result[key] = default
        return result

    def snapshot(self):
        return self.hypr.read("clients"), self.hypr.read("monitors"), self.hypr.read("workspaces")

    def matches(self, record, client):
        return (client and record["address"] == client["address"] and record["pid"] == client["pid"]
                and (not record.get("stableId") or record["stableId"] == client.get("stableId")))

    def _preview_record(self, ident):
        record = next((value for value in self.state['windows'] if value['id'] == ident), None)
        if record is None or record.get('phase') != 'stashed':
            raise RuntimeError('The preview window is no longer stashed')
        if record.get('previewFolded') is True:
            raise RuntimeError('Unfold this window before preparing its preview')
        current = self.hypr.client(record['address'])
        if (not self.matches(record, current) or record['tag'] not in current.get('tags', [])
                or current.get('workspace', {}).get('name') != SPECIAL or current.get('mapped') is not True):
            raise RuntimeError('The preview window identity changed or left the stash')
        if current.get('floating') is not True or current.get('fullscreen', 0) != 0:
            raise RuntimeError('The preview source must be parked floating without desktop fullscreen')
        stable = record.get('stableId') or current.get('stableId')
        if not stable:
            raise RuntimeError('The preview source has no stable window identity')
        return record, dict(record, stableId=stable)

    def preview_fold(self, identifiers, folded=True):
        identifiers = preview_fold_ids(identifiers)
        if type(folded) is not bool:
            raise ValueError('Preview folded state must be a boolean')
        with bridge_gate() if isinstance(self.hypr, Hyprland) else contextlib.nullcontext():
            with self.locked():
                return self._preview_fold_locked(identifiers, folded)

    def _preview_fold_locked(self, identifiers, folded):
        if self.settings()['presentation'] != 'previews':
            if folded:
                raise RuntimeError('Folding is available only for floating previews')
            return dict(ok=True, action='noop', ids=[], previewFolded=False)
        live = {client['address']: client for client in self.hypr.read('clients')}
        selected = []
        for ident in identifiers:
            record = next((item for item in self.state['windows'] if item['id'] == ident), None)
            current = live.get(record['address']) if record else None
            valid = (record and record.get('phase') == 'stashed' and self.matches(record, current)
                     and record['tag'] in current.get('tags', []) and current.get('mapped') is True
                     and current.get('workspace', {}).get('name') == SPECIAL)
            if not valid:
                if folded:
                    raise RuntimeError('The preview window changed or left the stash')
                continue
            stable = record.get('stableId') or current.get('stableId')
            if not isinstance(stable, str) or not re.fullmatch(r'(?:0x)?[0-9a-fA-F]+', stable):
                if folded:
                    raise RuntimeError('The preview source has no stable window identity')
                continue
            selected.append((record, dict(record, stableId=stable)))
        if not selected:
            return dict(ok=True, action='noop', ids=[], previewFolded=folded)
        ready = set(self.hypr.preview_fold_ready([identity for _, identity in selected], folded))
        if folded and ready != {record['id'] for record, _ in selected}:
            raise RuntimeError('The preview window changed or left the stash')
        changed = []
        for record, _ in selected:
            if record['id'] not in ready or (record.get('previewFolded') is True) == folded:
                continue
            record['previewFolded'] = folded
            changed.append(record['id'])
        if changed:
            self.save()
            if folded:
                for ident in changed:
                    self._release_preview_geometry(ident)
        return dict(ok=True, action=('preview-fold' if folded else 'preview-unfold') if changed else 'noop',
                    ids=changed, previewFolded=folded)

    def preview_geometry(self, ident):
        with bridge_gate() if isinstance(self.hypr, Hyprland) else contextlib.nullcontext():
            try:
                with self.locked():
                    _, identity = self._preview_record(ident)
                    return dict(self.hypr.preview_geometry(identity), ok=True, id=ident)
            except Exception:
                self._release_preview_geometry(ident)
                raise

    def _release_preview_geometry(self, ident):
        release = getattr(self.hypr, 'release_preview_geometry', None)
        if release is not None:
            try:
                release(ident)
            except (OSError, RuntimeError, subprocess.SubprocessError):
                pass  # The native 2.5-second lease still bounds cancellation.

    def preview_aspect(self, ident, aspect, axis, settle=False):
        aspect = preview_aspect(aspect)
        if axis not in ('width', 'height'):
            raise ValueError('Preview resize axis must be width or height')
        with bridge_gate() if isinstance(self.hypr, Hyprland) else contextlib.nullcontext():
            try:
                with self.locked():
                    record, identity = self._preview_record(ident)
                    self.hypr.wait_preview_fullscreen(identity)
                    before = self.hypr.preview_geometry(identity, resizing=True)
                    needs_support = isinstance(self.hypr, Hyprland) and before.get('nativeAvailable') is False
                    if not needs_support:
                        return self._resize_preview_locked(record, identity, before, aspect, axis, settle)
                # First use can build native support. Do not hold the ledger
                # during compilation; revalidate the exact source afterwards.
                native_error = ''
                try:
                    from preview import PreviewBridge
                    PreviewBridge(self.hypr).ensure()
                except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                    native_error = str(error)[-512:]
                with self.locked():
                    record, identity = self._preview_record(ident)
                    self.hypr.wait_preview_fullscreen(identity)
                    before = self.hypr.preview_geometry(identity, resizing=True)
                    result = self._resize_preview_locked(record, identity, before, aspect, axis, settle)
                    if native_error and result['nativeRequired']:
                        result['nativeError'] = native_error
                    return result
            except Exception:
                self._release_preview_geometry(ident)
                raise

    def _resize_preview_locked(self, record, identity, before, aspect, axis, settle):
        # The mutation repeats every preflight guard atomically.
        requested = preview_source_size(before['size'], aspect, axis)
        changed = requested != before['size']
        if changed:
            record['previewResized'] = True
            identity['previewResized'] = True
            self.save()
            result = self.hypr.preview_geometry(identity, requested, expected_size=before['size'])
        else:
            result = before
        if settle and not result['nativeRequired']:
            deadline = time.monotonic() + 2.5
            while not result['ready'] and time.monotonic() < deadline:
                time.sleep(.05)
                result = self.hypr.preview_geometry(identity)
        return dict(result, ok=True, id=record['id'], requestedAspect=aspect,
                    requestedSize=requested, changed=changed)

    def reconcile(self, clients):
        live = {c["address"]: c for c in clients}
        old = json.dumps(self.state, sort_keys=True)
        kept = []
        for r in self.state["windows"]:
            c = live.get(r["address"])
            if not self.matches(r, c):
                continue
            tagged = r["tag"] in c.get("tags", [])
            if tagged and c["workspace"]["name"] == LEGACY_SPECIAL:
                # Omarchy 4.5's native dock also owns special:minimized. Move
                # only ledger-backed, identity-checked windows into our own
                # workspace; native minimized windows are never adopted.
                try:
                    self.hypr.dispatch_owned("window.move", r, parked=LEGACY_SPECIAL,
                                             workspace=SPECIAL, follow=False)
                    migrated = self.hypr.client(r["address"])
                    if (not self.matches(r, migrated) or r["tag"] not in migrated.get("tags", [])
                            or migrated["workspace"]["name"] != SPECIAL):
                        raise RuntimeError("Legacy stashed window did not reach the private workspace")
                    c = migrated
                    r["phase"] = "stashed"
                except Exception as error:
                    r["phase"] = "restoring"
                    r["lastError"] = str(error)
                    self.save()
                    raise
            parked = c["workspace"]["name"] == SPECIAL
            if parked and tagged:
                if not c["floating"] and r["phase"] != "restoring":
                    try:
                        c = self.park(r, parked=True)
                    except Exception as error:
                        r["phase"] = "restoring"
                        r["lastError"] = str(error)
                        # Leave the recovery controls available. Retrying this
                        # normalization before restore would trap a client when
                        # a private-workspace rule keeps refusing the change.
                if r["phase"] != "restoring":
                    r["phase"] = "stashed"
            elif r["phase"] == "restoring" and tagged:
                pass  # Preserve metadata after a partial geometry failure for retry.
            elif r["phase"] == "stashed" and tagged:
                try:
                    self.hypr.release_external(r, c["workspace"],
                        self.native_floating_workspace(self.workspace_selector(c["workspace"])))
                    continue
                except Exception as error:
                    r["phase"] = "restoring"
                    r["lastError"] = str(error)
            else:
                continue
            r.update(title=c["title"], app=c["class"])
            kept.append(r)
        self.state["windows"] = kept
        if old != json.dumps(self.state, sort_keys=True):
            self.save()

    def park(self, record, parked=False):
        self.hypr.park_owned(record, parked=parked)
        after = self.hypr.client(record["address"])
        if not self.matches(record, after) or record["tag"] not in after.get("tags", []):
            raise RuntimeError("Window identity changed while minimizing")
        if after["workspace"]["name"] != SPECIAL:
            raise RuntimeError("The window did not reach the stash")
        if not after["floating"] or after["size"] != record["size"]:
            raise RuntimeError("The stashed window did not retain its saved size")
        return after

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
        if "omarchy-floating-workspace" in active.get("tags", []):
            return {"ok": True, "action": "noop", "reason": "Use Omarchy's dock on floating workspaces"}
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
        try:
            # Initial ownership and its first mutation share one compositor
            # call; the address alone may already belong to another window.
            self.hypr.dispatch_identity("window.tag", record, tag="+"+record["tag"])
            if record["fullscreen"] or record["fullscreenClient"]:
                self.hypr.dispatch_owned("window.fullscreen_state", record, internal=0, client=0, action="set")
                base = self.hypr.client(active["address"])
                if not self.matches(record, base) or record["tag"] not in base.get("tags", []):
                    raise RuntimeError("Window identity changed while minimizing")
                record.update(size=base["size"], relativePosition=[base["at"][0]-monitor["x"],base["at"][1]-monitor["y"]])
                self.save()
            if not record["floating"]:
                column_width = self.hypr.scrolling_width(record)
                if column_width is not None:
                    record["scrollingWidth"] = column_width
                    self.save()
            if record["pinned"]:
                self.hypr.dispatch_owned("window.pin", record, action="toggle")
            if len(active.get("grouped", [])) > 1:
                self.hypr.dispatch_owned("window.move", record, out_of_group=True)
            self.park(record)
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
        fingerprint = record.get("monitor") or ""
        if any(part.strip() for part in fingerprint.split("|")):
            origin_monitor = next((m for m in monitors if monitor_identity(m) == fingerprint), None)
        else:
            # Blank output metadata is not an identity: every headless display
            # can share it. An absent saved connector must take the slot
            # fallback even if its workspace migrated to another blank output.
            origin_name = record.get("monitorName")
            origin_monitor = next((m for m in monitors if m["name"] == origin_name), None) if origin_name else None
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

    def native_floating_workspace(self, selector):
        """Read Omarchy's generated mode declarations without evaluating Lua.

        Hyprland reports the retained tiled layout even while Omarchy floats
        a whole workspace. Only numbered workspaces participate in that mode.
        """
        selector = str(selector)
        if not re.fullmatch(r"[1-9][0-9]{0,9}", selector) or int(selector) > 2147483647:
            return False
        directory = self.positions.parent.parent / "workspace-layouts"

        def read_mode(path, fields):
            try:
                with path.open(encoding="utf-8") as stream:
                    text = stream.read(4097)
            except (OSError, UnicodeError):
                return None
            if len(text) > 4096:
                return None
            pattern = (r'\s*o\.workspace_mode\(\s*\{\s*' + fields
                       + r'"(dwindle|scrolling|floating)"\s*,?\s*\}\s*\)\s*;?\s*')
            match = re.fullmatch(pattern, text)
            return match[1] if match else None

        mode = read_mode(directory / (selector + ".lua"),
                         r'workspace\s*=\s*"' + re.escape(selector) + r'"\s*,\s*mode\s*=\s*')
        if mode is None:
            mode = read_mode(directory / "default.lua", r'default\s*=\s*')
        return mode == "floating"

    def restore(self, ident, to=None, monitor=None, workspace=None, expected=None):
        # Clearing private client fullscreen and moving the source public must
        # remain one operation relative to an exclusive native replacement.
        with bridge_gate() if isinstance(self.hypr, Hyprland) else contextlib.nullcontext():
            return self._restore(ident, to, monitor, workspace, expected)

    def _restore(self, ident, to=None, monitor=None, workspace=None, expected=None):
        clients = self.hypr.read("clients")
        self.reconcile(clients)
        record = next((r for r in self.state["windows"] if r["id"] == ident or r["address"] == ident), None)
        if not record:
            return {"ok": True, "action": "noop", "reason": "Window is no longer stashed"}
        expected = dict(expected or record)
        current = self.hypr.client(record["address"])
        if not self.matches(expected, current):
            self.reconcile(self.hypr.read("clients"))
            return {"ok": True, "action": "noop", "id": ident, "reason": "Window identity changed"}
        # A client can remain fullscreen inside a passive miniature after its
        # input lease ends. Remove that private override before interpreting
        # current fullscreen state as a real desktop restoration request.
        identity = dict(expected, stableId=expected.get('stableId') or current.get('stableId'))
        if current['workspace']['name'] == SPECIAL and identity.get('stableId'):
            self.hypr.clear_preview_fullscreen(identity)
            current = self.hypr.client(record['address'])
            if not self.matches(expected, current):
                self.reconcile(self.hypr.read('clients'))
                return {"ok": True, "action": "noop", "id": ident, "reason": "Window identity changed"}
        def dispatch(dispatcher, **args):
            if "window" in args:
                return self.hypr.dispatch_owned(dispatcher, expected, **args)
            return self.hypr.dispatch(dispatcher, **args)
        destination, dest_monitor = self.destination(record, to or self.settings()["restoreDestination"], monitor, workspace)
        native_floating = self.native_floating_workspace(destination)
        floating = record["floating"] or native_floating
        target = "address:"+record["address"]
        fullscreen = [current.get("fullscreen", 0), current.get("fullscreenClient", 0)]
        if any(fullscreen):
            # An interactive source can request fullscreen while hidden. Clear
            # it before float/resize/layout dispatchers, then honor that newer
            # request after restoring the ordinary window. Retain it separately
            # so a partial failure does not lose it or alter the original snapshot.
            record["restoreFullscreen"] = fullscreen
        desired_fullscreen = record.get("restoreFullscreen")
        if (not isinstance(desired_fullscreen, list) or len(desired_fullscreen) != 2
                or any(type(value) is not int or not 0 <= value <= 3 for value in desired_fullscreen)):
            desired_fullscreen = [record["fullscreen"], record["fullscreenClient"]]
        record["phase"] = "restoring"
        self.save()
        try:
            if any(fullscreen):
                dispatch("window.fullscreen_state", window=target, internal=0, client=0, action="set")
            dispatch("focus", monitor=dest_monitor["name"])
            dispatch("focus", workspace=destination)
            dispatch("window.move", window=target, workspace=destination, follow=False)
            if native_floating and not record["floating"]:
                # Let Omarchy tile this originally tiled window again when
                # its floating mode ends, even if its deferred move handler
                # runs after the float action below.
                dispatch("window.tag", window=target, tag="+omarchy-mode-floated")
            dispatch("window.float", window=target, action="on" if floating else "off")
            if record["floating"]:
                x, y, width, height = restored_geometry(record, dest_monitor)
                dispatch("window.resize", window=target, x=width, y=height, relative=False)
                dispatch("window.move", window=target, x=x, y=y, relative=False)
            elif not native_floating:
                self.append_scrolling(record["address"], destination, record["size"][0], expected)
            dispatch("focus", window=target)
            pin_state = self.hypr.client(record["address"])
            if not self.matches(expected, pin_state) or expected["tag"] not in pin_state.get("tags", []):
                raise RuntimeError("Window identity changed during restoration")
            if bool(pin_state.get("pinned")) != record["pinned"]:
                dispatch("window.pin", window=target, action="toggle")
            if any(desired_fullscreen):
                dispatch("window.fullscreen_state", window=target, internal=desired_fullscreen[0],
                                   client=desired_fullscreen[1], action="set")
            after = self.hypr.client(record["address"])
            if not self.matches(expected, after) or expected["tag"] not in after.get("tags", []):
                raise RuntimeError("Window identity changed during restoration")
            if self.workspace_selector(after["workspace"]) != destination:
                raise RuntimeError("The window did not reach the destination workspace")
            if after["floating"] != floating:
                raise RuntimeError("A window rule prevented restoration of floating state")
            dispatch("window.tag", window=target, tag="-"+record["tag"])
            self.state["windows"].remove(record)
            self.save()
            return {"ok": True, "action": "restored", "id": record["id"], "workspace": after["workspace"]}
        except Exception as error:
            record["lastError"] = str(error)
            self.save()
            raise

    def append_scrolling(self, address, destination, width, expected=None):
        # Query Lua layout state rather than infer order from off-screen coordinates.
        # Focus the terminal column first, then reinsert this exact window after it.
        column_width = (expected or {}).get("scrollingWidth")
        if (type(column_width) not in (int, float) or not math.isfinite(column_width)
                or not 0 < column_width <= 1):
            column_width = None
        code = '''local w = hl.get_window(%s)
local ws = hl.get_workspace(%s)
if w and ws and ws.tiled_layout == "scrolling" then
  hl.dispatch(hl.dsp.focus({window=w}))
  hl.dispatch(hl.dsp.window.float({window=w, action="on"}))
  local windows = hl.get_workspace_windows(ws)
  local last = nil
  for _, candidate in pairs(windows) do
    if candidate.address ~= w.address and not candidate.floating then
      local layout = candidate.layout
      if layout and layout.column and (not last or layout.column.index > last.layout.column.index) then
        last = candidate
      end
    end
  end
  if last then hl.dispatch(hl.dsp.focus({window=last})) end
  hl.dispatch(hl.dsp.window.float({window=w, action="off"}))
  hl.dispatch(hl.dsp.focus({window=w}))
  -- Start wide so the scrolling resize cannot clip growth at the viewport edge.
  -- Absolute client sizing then accounts for this column's gaps and borders.
  local columnWidth = w.layout.column.width
  local savedColumnWidth = %s
  local initialWidth = w.size.x
  hl.dispatch(hl.dsp.layout("colresize 1"))
  if w.size.x == initialWidth then
    -- Pixel width cannot recover a vertical tape's primary-axis fraction or
    -- the hidden fraction of a forced full-screen singleton. Keep the exact
    -- original fraction, without an ineffective resize corrupting it again.
    if savedColumnWidth then
      hl.dispatch(hl.dsp.layout("colresize " .. tostring(savedColumnWidth)))
      return
    end
    -- Older records have no fraction. A forced singleton is safely full-width;
    -- otherwise preserve the previous fallback for vertical tape layouts.
    local singleColumn = true
    for _, candidate in pairs(hl.get_workspace_windows(ws)) do
      if not candidate.floating and candidate.layout and candidate.layout.column
          and candidate.layout.column.index ~= w.layout.column.index then singleColumn = false; break end
    end
    local ok, forceSingle = pcall(hl.get_config, "scrolling.fullscreen_on_one_column")
    if singleColumn and ok and (forceSingle == true or forceSingle == 1) then return end
    hl.dispatch(hl.dsp.layout("colresize " .. tostring(columnWidth)))
  end
  hl.dispatch(hl.dsp.window.resize({window=w, x=math.min(%s, w.size.x), y=w.size.y, relative=false}))
end''' % (lua("address:"+address), lua(destination), lua(column_width), lua(width))
        self.hypr.eval((owned_window_guard(expected) if expected else "") + code)

    def listing(self):
        clients, monitors, workspaces = self.snapshot()
        self.reconcile(clients)
        return dict(ok=True, windows=sorted(self.state["windows"], key=lambda r:r["order"], reverse=True),
                    monitors=monitors, workspaces=workspaces, settings=self.settings(),
                    shortcutDefaults=dict(shortcuts.DEFAULT_SHORTCUTS, **LOCAL_SHORTCUT_DEFAULTS),
                    statePath=str(self.path), positions=read_json(self.positions, {}))

    def restore_last(self, to=None, monitor=None, workspace=None, stage=False):
        self.reconcile(self.hypr.read("clients"))
        _, current = self.invoke_context(monitor, workspace)
        choices = eligible(self.state["windows"], current, self.settings()["scope"])
        if stage and choices and choices[0].get('previewFolded') is True and self.settings()['presentation'] == 'previews':
            with bridge_gate() if isinstance(self.hypr, Hyprland) else contextlib.nullcontext():
                result = self._preview_fold_locked([choices[0]['id']], False)
            return dict(result, id=choices[0]['id'])
        return self.restore(choices[0]["id"], to, monitor, workspace) if choices else {"ok":True,"action":"noop"}

    def restore_oldest(self, to=None, monitor=None, workspace=None, stage=False):
        self.reconcile(self.hypr.read("clients"))
        _, current = self.invoke_context(monitor, workspace)
        choices = eligible(self.state["windows"], current, self.settings()["scope"])
        if stage and choices and choices[-1].get('previewFolded') is True and self.settings()['presentation'] == 'previews':
            with bridge_gate() if isinstance(self.hypr, Hyprland) else contextlib.nullcontext():
                result = self._preview_fold_locked([choices[-1]['id']], False)
            return dict(result, id=choices[-1]['id'])
        return self.restore(choices[-1]["id"], to, monitor, workspace) if choices else {"ok":True,"action":"noop"}

    def recover_focused(self):
        """Restore an owned parked window activated by an external switcher.

        Call under the ledger lock, after the activating transaction. Hyprland
        can still report a hidden parked client as active after minimizing the
        last visible window. A switcher activation also opens its special
        workspace on that client's monitor; stale focus alone is insufficient.
        """
        active = self.hypr.read("activewindow") or {}
        record = next((r for r in self.state["windows"] if self.matches(r, active)), None)
        if (not record or active.get("workspace", {}).get("name") != SPECIAL
                or record["tag"] not in active.get("tags", [])):
            return {"ok": True, "action": "noop"}
        if not any(m.get("id") == active.get("monitor")
                   and (m.get("specialWorkspace") or {}).get("name") == SPECIAL
                   for m in self.hypr.read("monitors")):
            return {"ok": True, "action": "noop"}
        return self.restore(record["id"])

    def close(self, identifiers, monitor=None, workspace=None):
        """Request normal closure, confirming disappearance before ledger removal.

        All requests share one grace period. Surviving windows are restored for
        application-owned prompts; no process signals or force-close are used.
        """
        context, current = self.invoke_context(monitor, workspace)
        self.reconcile(self.hypr.read("clients"))
        records = {r["id"]: r for r in self.state["windows"]}
        results, pending = [], {}

        def owned(record, client):
            return (self.matches(record, client) and record["tag"] in client.get("tags", [])
                    and client["workspace"]["name"] == SPECIAL)

        def outcome(record, action, **extra):
            return dict(id=record["id"], ok=action != "failed", action=action, **extra)

        def check_pending(clients):
            live = {c["address"]: c for c in clients}
            for ident, record in list(pending.items()):
                c = live.get(record["address"])
                if not self.matches(record, c):
                    results.append(outcome(record, "closed"))
                    del pending[ident]
                elif not owned(record, c):
                    results.append(outcome(record, "noop", reason="Window left the stash"))
                    del pending[ident]
            self.reconcile(clients)

        for ident in dict.fromkeys(identifiers):
            record = records.get(ident)
            if not record:
                results.append(dict(id=ident, ok=True, action="noop", reason="Window is no longer stashed"))
                continue
            try:
                c = self.hypr.client(record["address"])
                if not owned(record, c):
                    results.append(outcome(record, "noop", reason="Window is no longer stashed"))
                    self.reconcile(self.hypr.read("clients"))
                    continue
                # The Lua guard repeats identity/tag/workspace checks atomically
                # with close dispatch, protecting against address reuse after IPC.
                self.hypr.close_stashed(record)
                pending[ident] = dict(record)
            except Exception as error:
                record["lastError"] = str(error)
                self.save()
                results.append(outcome(record, "failed", error=str(error)))

        deadline = time.monotonic() + .75
        try:
            while pending:
                check_pending(self.hypr.read("clients"))
                remaining = deadline - time.monotonic()
                if not pending or remaining <= 0:
                    break
                time.sleep(min(.05, remaining))
        except Exception as error:
            # An unavailable compositor must not cause speculative restoration
            # or ledger removal. Each pending target remains recoverable.
            for record in pending.values():
                live_record = next((r for r in self.state["windows"] if r["id"] == record["id"]), None)
                if live_record: live_record["lastError"] = str(error)
                results.append(outcome(record, "failed", error=str(error)))
            self.save()
            pending.clear()

        for record in pending.values():
            try:
                c = self.hypr.client(record["address"])
                if not self.matches(record, c):
                    results.append(outcome(record, "closed"))
                    self.reconcile(self.hypr.read("clients"))
                    continue
                if not owned(record, c):
                    results.append(outcome(record, "noop", reason="Window left the stash"))
                    self.reconcile(self.hypr.read("clients"))
                    continue
                # Guard every window mutation during attention restoration too.
                result = self.restore(record["id"], "current", context["name"], current, expected=record)
                results.append(dict(result, id=record["id"]))
            except Exception as error:
                # A client may finish closing while being restored. Confirm its
                # identity before treating that race as a genuine action failure.
                try:
                    clients = self.hypr.read("clients")
                    c = next((c for c in clients if c["address"] == record["address"]), None)
                    if not self.matches(record, c):
                        self.reconcile(clients)
                        results.append(outcome(record, "closed"))
                        continue
                except Exception:
                    pass
                live_record = next((r for r in self.state["windows"] if r["id"] == record["id"]), None)
                if live_record:
                    live_record["lastError"] = str(error)
                    self.save()
                results.append(outcome(record, "failed", error=str(error)))

        failed = sum(r["action"] == "failed" for r in results)
        result = dict(ok=not failed, action="close", results=results,
                      closed=sum(r["action"] == "closed" for r in results),
                      restored=sum(r["action"] == "restored" for r in results), failed=failed)
        if failed:
            result["error"] = str(failed) + " window close action(s) failed: " + "; ".join(
                r["error"] for r in results if r["action"] == "failed")
        return result

    def close_all(self, monitor=None, workspace=None):
        context, current = self.invoke_context(monitor, workspace)
        self.reconcile(self.hypr.read("clients"))
        targets = eligible(self.state["windows"], current, self.settings()["scope"])
        return self.close([r["id"] for r in targets], context["name"], current)

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
    minimize.add_argument("--shortcut", action="store_true", help=argparse.SUPPRESS)
    for action in ("restore", "restore-last", "restore-oldest", "restore-all", "activate"):
        p = sub.add_parser(action)
        if action in ("restore", "activate"): p.add_argument("id")
        p.add_argument("--to", choices=("current","original"))
        p.add_argument("--monitor")
        p.add_argument("--workspace", type=int)
        if action in ('restore-last', 'restore-oldest'):
            p.add_argument('--stage', action='store_true', help='Unfold a folded preview before restoring its window')
            p.add_argument('--shortcut', action='store_true', help=argparse.SUPPRESS)
    for action in ("close", "close-all"):
        p = sub.add_parser(action, help="Normally close owned stashed windows")
        if action == "close": p.add_argument("ids", nargs="+")
        p.add_argument("--monitor")
        p.add_argument("--workspace", type=int)
    for action in ("list", "status"):
        sub.add_parser(action)
    sub.add_parser("recover-focused", help=argparse.SUPPRESS)
    shortcut=sub.add_parser("shortcut",help="Set or disable one managed keyboard shortcut")
    shortcut.add_argument("key",choices=tuple(shortcuts.DEFAULT_SHORTCUTS))
    shortcut.add_argument("binding")
    interaction_shortcut = sub.add_parser("interaction-exit-shortcut", help="Set or disable the interactive-preview exit shortcut")
    interaction_shortcut.add_argument("binding")
    sub.add_parser("shortcuts-sync",help="Synchronize managed shortcuts with saved settings")
    reset = sub.add_parser("reset-settings",help="Reset all plugin preferences and shortcuts")
    reset.add_argument("--confirm",action="store_true",help="Confirm resetting all Window Stash settings")
    pos = sub.add_parser("position")
    pos.add_argument("monitor")
    pos.add_argument("key")
    pos.add_argument("x", type=float)
    pos.add_argument("y", type=float)
    preview_pos = sub.add_parser("preview-position", help="Save a floating preview card's position and width")
    preview_pos.add_argument("monitor")
    preview_pos.add_argument("key")
    preview_pos.add_argument("x", type=int)
    preview_pos.add_argument("y", type=int)
    preview_pos.add_argument("width", type=int)
    preview_pos.add_argument("--aspect", type=float)
    source_aspect = sub.add_parser("preview-aspect", help="Change a private preview source's aspect ratio")
    source_aspect.add_argument("id")
    source_aspect.add_argument("aspect", type=float)
    source_aspect.add_argument("--axis", choices=("width", "height"), required=True)
    source_aspect.add_argument("--settle", action="store_true")
    source_geometry = sub.add_parser("preview-geometry", help="Read exact preview source resize readiness")
    source_geometry.add_argument("id")
    for action in ('preview-fold', 'preview-unfold'):
        p = sub.add_parser(action, help='Fold or unfold floating previews without restoring their windows')
        p.add_argument('ids', nargs='+')
    rebase = sub.add_parser("rebase")
    rebase.add_argument("old", type=int)
    rebase.add_argument("new", type=int)
    args = parser.parse_args(argv)
    try:
        if getattr(args, 'shortcut', False):
            if (getattr(args, 'address', None) is not None or getattr(args, 'to', None) is not None
                    or getattr(args, 'monitor', None) is not None or getattr(args, 'workspace', None) is not None
                    or getattr(args, 'stage', False)):
                raise ValueError('Shortcut routing cannot be combined with explicit window or restoration selectors')
            result = forward_shortcut(args.command)
            print(json.dumps(result, ensure_ascii=False))
            return 0 if result.get('ok', True) else 1
        if args.command == "reset-settings":
            if not args.confirm:
                raise ValueError("Resetting settings requires --confirm")
            result = shortcuts.reset_settings(None, DEFAULTS)
            print(json.dumps(result))
            return 0
        stash = Stash()
        if args.command == "interaction-exit-shortcut":
            from interaction import configure_exit_shortcut
            print(json.dumps(configure_exit_shortcut(stash.config, args.binding, stash.hypr)))
            return 0
        if args.command in ("shortcut","shortcuts-sync"):
            result=shortcuts.configure(stash.config,args.key,args.binding) if args.command=="shortcut" else shortcuts.sync(stash.config)
            print(json.dumps(result))
            return 0
        if args.command in ('preview-aspect', 'preview-geometry'):
            result = (stash.preview_aspect(args.id, args.aspect, args.axis, args.settle)
                      if args.command == 'preview-aspect' else stash.preview_geometry(args.id))
            print(json.dumps(result))
            return 0
        if args.command in ('preview-fold', 'preview-unfold'):
            result = stash.preview_fold(args.ids, args.command == 'preview-fold')
            print(json.dumps(result))
            return 0
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
            elif args.command == "restore-last": result=stash.restore_last(args.to,args.monitor,args.workspace,args.stage)
            elif args.command == "restore-oldest": result=stash.restore_oldest(args.to,args.monitor,args.workspace,args.stage)
            elif args.command == "recover-focused": result=stash.recover_focused()
            elif args.command == "restore-all":
                context, workspace=stash.invoke_context(args.monitor,args.workspace)
                stash.reconcile(stash.hypr.read("clients"))
                results=[]
                for r in list(stash.state["windows"]):
                    results.append(stash.restore(r["id"],args.to or "current",context["name"],workspace))
                result=dict(ok=True,results=results)
            elif args.command == "close": result=stash.close(args.ids,args.monitor,args.workspace)
            elif args.command == "close-all": result=stash.close_all(args.monitor,args.workspace)
            elif args.command == "rebase": result=stash.rebase(args.old,args.new)
            elif args.command == "position":
                positions=read_json(stash.positions,{})
                positions.setdefault(args.monitor,{})[args.key]=[args.x,args.y]
                atomic_json(stash.positions,positions)
                result=dict(ok=True)
            elif args.command == "preview-position":
                if not args.key.startswith("preview:") or not args.key.removeprefix("preview:"):
                    raise ValueError("Floating preview positions require a preview: key")
                if not (-1_000_000 <= args.x <= 1_000_000 and -1_000_000 <= args.y <= 1_000_000
                        and 1 <= args.width <= 1_000_000):
                    raise ValueError("Preview coordinates must be within ±1000000 and width within 1–1000000 pixels")
                positions=read_json(stash.positions,{})
                point = [args.x,args.y,args.width]
                if args.aspect is not None:
                    point.append(preview_aspect(args.aspect))
                positions.setdefault(args.monitor,{})[args.key]=point
                atomic_json(stash.positions,positions)
                result=dict(ok=True)
            else: result=stash.listing()
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get("ok", True) else 1
    except Exception as error:
        print(json.dumps(dict(ok=False,error=str(error))))
        return 1


if __name__ == "__main__":
    sys.exit(main())
