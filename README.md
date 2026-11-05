# Window Stash for Omarchy

Minimize running windows into a static edge dock, draggable bubbles, or an expandable
floating dock. Restore to
your current workspace or the original one, preserving floating size and
position. Works with the Omarchy 4.0 shell and Hyprland 0.56.2 Lua API.

Copyright © 2026 **artu-ole**. Licensed under [AGPL-3.0-only](LICENSE).
See [third-party notices](THIRD_PARTY_NOTICES.md) for integration excerpts.
Source: [artu-ole/omarchy-window-stash](https://github.com/artu-ole/omarchy-window-stash).

## Requirements

- Omarchy 4.0 with its Quickshell shell, Qt6.7 or newer, shared `qs.Commons` /
  `qs.Ui` components, and `Quickshell.Widgets`. Tested on Omarchy 4.0.6-1; older shells are not supported.
- Hyprland 0.56.2 with the Lua `hl.dispatch` API and `hyprctl` on `PATH`.
- Python 3.9 or newer, using only the standard library.
- For setup: `omarchy`, `omarchy-shell`, and `hyprctl` on `PATH`, plus an
  existing user `~/.config/hypr/bindings.lua` and Omarchy `shell.json`.
- Optional: `community.window-switcher` for switcher restoration integration.
  The helper supports the integration anchors in its 1.0.0 release and stops
  if an installed switcher's code is incompatible.

No dependency installation, compilation, network access, root privileges,
system service, or separate background daemon is required by this plugin.
Development-only dependencies are listed under Development and verification.

## Use

| Action | Shortcut / interaction |
|---|---|
| Minimize focused window | **Super+A** |
| Restore most recently minimized eligible window | **Super+Z** |
| Restore a window | Click its dock icon or bubble |
| Choose between windows grouped by app | Click the icon with a count badge |
| Choose restore destination, open settings or show every stashed window | Right-click an icon; the dock also has a **⋯** button |
| Move a bubble | Drag it; it snaps to an edge by default, with free placement available |
| Expand/collapse the floating dock | Click its stacked handle; Escape or an outside click also collapses it |
| Move the floating dock | Drag its handle; one shared position is remembered per monitor |
| Search the window chooser | Type; use Up/Down and Enter to select; Escape closes |

Default settings: **static dock at the bottom**, **global visibility**,
**restore here**, **one icon per window**. The UI appears on every connected monitor. Global mode repeats
the same stash on each screen; workspace mode filters by that screen's active
workspace. Floating items default to **Snap to edges**. Grouping by app is optional and uses a window chooser when needed.

Open settings or the full recovery chooser even when no dock is visible:

```sh
omarchy-shell window-stash settings
omarchy-shell window-stash all
```

Choose **Appearance → Static dock**, then **Dock side → Bottom, Top, Left, or
Right**. Bottom is the default. The dock centers along the selected edge without
reserving tiling space. Top/bottom docks arrange icons horizontally; left/right
docks arrange them vertically. Long lists scroll along that edge. Each monitor's
reserved bar space is respected, so a top dock sits below an existing top bar.
While the static dock is visible, it checks for reserved-area changes every
1.5 seconds, including bars appearing or disappearing. Empty stashes take no
space or input. Bubbles start in a vertically centered column along the right
edge and only their icon regions intercept input; the rest of the desktop is click-through.
Tooltips show titles. Hover thumbnail previews are outside version one's scope.

Choose **Appearance → Floating dock** for the compact stack presentation. One
stashed window behaves like a floating icon and restores on click. With multiple
windows, layered icons and a count badge form one draggable handle. Clicking it
opens a dock beside the handle, growing toward available screen space. Long
lists scroll. Selecting an icon restores its window and collapses
the dock; app-grouped icons open the existing window chooser. Even when several
windows belong to one app, the collapsed handle expands first so grouping keeps
the same behavior as the static dock.

This presentation uses the same stash visibility, restore destination, grouping,
and icon shape settings. The single handle starts at the middle right, remembers
its own position separately from individual bubbles, and remains anchored while
the dock expands. Right-clicking it opens restore actions, all windows, and
settings. Up/Down and Enter can choose from the expanded dock.

With Floating dock selected, **Floating dock direction** offers **Vertical**
(the default) and **Horizontal**. Vertical docks expand upward or downward;
horizontal docks expand left or right and also support Left/Right keys.
Scrolling follows the chosen axis. Changing direction first collapses the dock
smoothly, preserving its anchor and existing grouping and icon-shape choices.

For Floating bubbles and Floating dock, **Floating placement** offers **Snap to
edges** (the default) and **Free placement**. Edge mode glides to the nearest of
the four screen edges after you release a drag, staying clear of reserved bar
space. Separate bubbles choose nearby open slots; crowded edges repack before
using another edge. If the entire perimeter fills, bubbles can share slots; the
floating dock handles long lists with scrolling. Dragging follows the pointer
directly, and grabbing an item during its glide stops the animation. Switching to Free placement lets you leave
items anywhere. Dragged resting positions are remembered per monitor. The
setting also applies to older configurations, which default to edge snapping.

Opening and closing use eased reveal/fade motion while icons stay at their
natural size. Changes to the list animate without recreating unchanged icons
or resetting scroll position. Artwork is centered on the display's pixel grid;
borders and count badges stay inside their tiles. Counts above 99 show `99+`.
Both docks use compact outer padding and tight icon spacing. App artwork fills
more of each tile while keeping clearance from rounded and circular borders.

The UI follows the active Omarchy theme, including popup colors, typography,
spacing, borders, and corner rounding. Settings, menus, search, and tooltips use
Omarchy's shared UI components; window rows use its standard selection styling.

**Dock corners** offers **Follow desktop** (the default) or **Custom** for the
static dock and expanded floating dock. Follow desktop uses Omarchy's shared
radius, which mirrors Hyprland's `decoration:rounding`. Custom reveals a native
**Corner radius (px)** field accepting whole numbers from 0 to 64. Zero gives
square corners; larger values are limited to half the dock's shorter dimension.
The dock clips its contents to the rounded border. Your custom value is retained
when you switch back to Follow desktop. App icon shapes and other Omarchy
controls keep their own styling.

**Icon shape** in settings offers Automatic, Circle, Square, Rounded square,
and Squircle. It changes the frame around each app icon in all presentations.
Automatic preserves circular bubbles and theme-shaped dock controls. Explicit
choices also give dock icons a themed background and border. Squircle uses a
continuous superellipse curve. Changing shape preserves bubble positions and
the app's original icon artwork.

## Install / update / remove

**Manual setup is required.** Omarchy's generic plugin installer clones and
enables QML; it does not run this helper. The service currently expects the
controller at `~/.local/bin/window-stash`, which the helper creates. Adding
the plugin through the marketplace alone is therefore insufficient.

From a separate local checkout of this source folder, in an unlocked Omarchy
session, review the helper and run it as your normal user:

```sh
git clone https://github.com/artu-ole/omarchy-window-stash.git
cd omarchy-window-stash
python3 tools/install.py
```

The installer validates the manifest, checks live shortcut conflicts, backs up
affected user files, copies the plugin and controller into the user's home,
adds two bindings, enables the plugin, and patches the installed
`community.window-switcher` when present. Re-running updates the installation
without resetting settings. A kept-loaded service needs a shell restart to
load changed QML:

```sh
omarchy restart shell
```

The helper displays its file changes and asks for confirmation before writing
anything. For automation after reviewing those changes, pass `--yes` explicitly.
It does not install dependencies or fetch or execute remote code.

Installation does not change packaged Omarchy files, themes, or the existing
scratchpad. Backups are under `$XDG_STATE_HOME/omarchy/window-stash/backups`
(default `~/.local/state/omarchy/window-stash/backups`).

Remove with the helper so parked windows are restored first:

```sh
python3 tools/install.py --uninstall
```

For non-interactive removal, use `python3 tools/install.py --uninstall --yes`.
Use the same separate source checkout for updates and removal. Keep it until
removal is complete; the helper is not copied into the installed plugin folder.

The helper removes only its binding block and known switcher integration
edits, preserving unrelated configuration changes. Durable bubble positions
remain available for reinstall. Using Omarchy's generic plugin-disable command
alone hides the UI; the controller remains available to recover windows.
Before using `omarchy plugin remove community.window-stash`, run the helper's
uninstall command. Generic removal does not run cleanup hooks and would leave
the controller wrapper, shortcuts, and switcher edits behind.

## Configuration changes and local data

Installation and removal operate as your user. After confirmation, the helper
copies/removes the plugin under `~/.config/omarchy/plugins/community.window-stash`,
creates/removes `~/.local/bin/window-stash`, adds/removes its marked shortcut
block in `~/.config/hypr/bindings.lua`, and adds/removes its entry in
`~/.config/omarchy/shell.json`. It patches only `Switcher.qml`,
`components/WindowRecords.qml`, and `model/WindowSnapshot.js` in the optional
user-installed switcher. It backs up affected files, reloads Hyprland while
preserving runtime monitor geometry, and rescans shell plugins. Unrelated
settings and packaged files are preserved.

The UI saves only this plugin's settings through Omarchy's scoped settings API.
Its controller reads window titles, app identifiers, workspaces, monitor
identity (including serial where available), and geometry from Hyprland.
The session ledger stores the metadata needed for restoration; monitor identity
and bubble positions also persist locally. These files can contain private
window titles or hardware identifiers. Their locations are described below;
they are not part of the source tree. The plugin sends no telemetry and makes
no network requests. Icons come from installed desktop entries and icon themes;
no third-party icon assets are bundled.

## Restore behavior

- **Floating:** saved logical size and monitor-relative position are reapplied.
  Different screen dimensions clamp the restored window into the work area;
  application-imposed size limits still apply.
- **Tiled:** a new tile is inserted. In scrolling layouts it becomes the final
  column in the configured direction and restores its saved visible width,
  accounting for gaps and borders. Destination layout and application size
  limits still apply, including scrolling's single-column fullscreen policy.
  Dwindle uses normal new-window insertion.
- **Fullscreen / maximized / pinned:** the recorded state is restored after
  the underlying geometry. Restoring a normal window does not maximize it.
- **Hyprland groups:** only the selected group member is stashed. Restoration
  inserts it as a separate window rather than reconstructing the old group.
- **Original workspace:** an empty original workspace can be recreated. If its
  monitor is disconnected, its local slot maps to the invoking screen's bank.
  The existing `hypr/monitor-workspaces.lua` bank map is honored. Arbitrary
  external window merges cannot be automatically reversed.
- **Workspace renumbering:** compositor ID-change events update saved origins.
- **Closed windows:** disappear from the stash automatically. Other programs'
  minimized windows and the scratchpad are not managed by this plugin.

## Commands and settings

`window-stash` is a standalone controller; it needs Hyprland but does not need
the dock or Quickshell service to be running. Commands emit JSON with `ok` and
an action/result or error; failures return a nonzero exit code.

```sh
window-stash minimize
window-stash restore-last
window-stash list
window-stash restore WINDOW_ID --to current
window-stash restore WINDOW_ID --to original
window-stash restore-all --to current
window-stash status
```

`restore` also accepts a live window address. `activate ADDRESS` restores a
plugin-owned stashed window or normally focuses an unmanaged window, for
window-switcher integration without relying on cached tags.
Restore commands accept `--monitor OUTPUT --workspace ID` to capture a
destination before a chooser takes focus. `minimize --address ADDRESS` targets
one exact window. `restore-last` obeys the configured visibility scope and
uses newest-first order; `restore-all` is a global recovery action.

Settings live on the plugin's entry in `~/.config/omarchy/shell.json`:

```json
{
  "id": "community.window-stash",
  "presentation": "dock",
  "scope": "global",
  "restoreDestination": "current",
  "grouping": "window",
  "iconShape": "auto",
  "floatingDirection": "vertical",
  "dockSide": "bottom",
  "floatingPlacement": "edges",
  "dockCorners": "theme",
  "dockCornerRadius": 12
}
```

`presentation` accepts `dock`, `bubbles`, or `floating`. Alternatives for scope,
restore destination, and grouping are `workspace`, `original`, and `app`,
respectively. `iconShape` accepts `auto`, `circle`, `square`,
`rounded`, or `squircle`; older configurations default to `auto`.
`floatingDirection` accepts `vertical` or `horizontal` and only affects the
floating dock. Older configurations retain the vertical layout.
`dockSide` accepts `bottom`, `top`, `left`, or `right` and only affects the static
dock. Older configurations retain the bottom position.
`floatingPlacement` accepts `edges` (default) or `free`, shared by bubbles and the
floating dock. The static dock keeps its separate side setting.
`dockCorners` accepts `theme` (default) or `custom`; `dockCornerRadius` stores an
integer from 0 to 64 (default 12), applied in custom mode.
The settings panel writes through the shell's plugin-scoped settings API.
For automation, the same API is exposed through:

```sh
omarchy-shell window-stash configure presentation bubbles
omarchy-shell window-stash configure presentation floating
omarchy-shell window-stash configure floatingDirection horizontal
omarchy-shell window-stash configure dockSide top
omarchy-shell window-stash configure floatingPlacement free
omarchy-shell window-stash configure dockCorners custom
omarchy-shell window-stash configure dockCornerRadius 12
omarchy-shell window-stash configure scope workspace
omarchy-shell window-stash configure iconShape squircle
omarchy-shell window-stash status
```

Bind any unused keys to `window-stash minimize` and `window-stash restore-last`
in your personal Hyprland bindings. Always check conflicts before replacing a
binding. The installed Super+A/Super+Z bindings do not repeat while held down.

## State and recovery

The controller writes an atomic, locked ledger before changing a window, then
parks it on `special:minimized` with a unique `window-stash-…` tag. Records also
validate the process and compositor window identity to prevent address reuse
from affecting a new client. An interrupted restore retains metadata for retry.
Session data lives under
`$XDG_RUNTIME_DIR/omarchy-window-stash/$HYPRLAND_INSTANCE_SIGNATURE/`; a fresh
compositor session starts with a separate ledger. Shell restarts do not lose it.
Bubble positions live under `$XDG_STATE_HOME/omarchy/window-stash/bubbles.json`.

Recovery without the UI:

```sh
window-stash list
window-stash restore-all --to current
```

The plugin uses compositor events and watched files rather than periodic
polling. Actions launch a small standard-library Python controller; no extra
daemon, network service, screenshots, or C++ plugin is required.

## Development and verification

```sh
python3 tools/check.py
python3 tests/live.py
python3 tests/layouts_monitors.py
python3 tests/ui_lifecycle.py
python3 tests/overflow.py
python3 tests/themed_ui.py
python3 tests/scrolling_width.py
python3 tests/icon_shapes.py
python3 tests/floating_dock.py
python3 tests/floating_direction.py
python3 tests/dock_sides.py
python3 tests/floating_placement.py
python3 tests/dock_corners.py
```

Live tests require an unlocked graphical session, `/usr/bin/python3` with GTK4
introspection (`python-gobject` and `gtk4` on Arch), `wtype`, `notify-send`
(`libnotify` on Arch), `grim` for the
themed UI screenshot, and the installed plugin. The non-graphical checks need
Node.js, Qt6 `qmllint`, and Omarchy's validator (which uses `jq`). They use disposable Wayland
and XWayland windows, temporary virtual outputs, and restore the original focus
and settings in cleanup. Run them with an empty stash. The keyboard test
temporarily enables keysym matching for wtype's synthetic keymap and restores
the original setting afterward; installation leaves input matching unchanged.
The scrolling-width, floating-dock, static-dock-side, floating-placement, and dock-corner
regressions use isolated workspaces and temporary virtual outputs and preserve existing stash entries. The dock-side
test also uses `qs` to create a temporary bar on its virtual output. The width test
checks the source controller by default;
pass `--installed` to check the installed copy.

Every desktop test sends a notification asking you to pause input, waits five
seconds before taking focus or injecting input, and notifies you after cleanup.
The shared `tests/desktop_test.py` wrapper aborts before desktop actions if the
initial notification cannot be sent. Unit tests and linting do not take over
the desktop and run without the countdown.

For QML linting, use Qt6's `/usr/lib/qt6/bin/qmllint`, with an import directory
mapping `qs/Commons` and `qs/Ui` to their directories under
`/usr/share/omarchy/shell/`. Omarchy also loads
these imports through its own shell scanner at runtime.
