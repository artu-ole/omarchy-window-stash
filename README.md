# Window Stash

![Diagram of Window Stash's static dock, floating bubbles, and expandable floating dock, with icon-shape and opacity samples.](assets/title.png)

Window minimization for Omarchy. Park live Hyprland windows, then restore them to
the current or original workspace. A QML frontend and standard-library Python
controller; no compiled compositor plugin or additional daemon.

| Presentation | Behavior |
|---|---|
| **Static dock** | A slim dock on any screen edge. Respects bar reservations; long lists scroll. |
| **Floating bubbles** | Separate draggable icons, starting at the middle right. Snap to edges or place freely. |
| **Floating dock** | One draggable stack. A single window restores directly; multiple windows fan into a row or column, newest under the pointer. |

Click the floating stack to fan out the same icons. The front icon stays at its
original position, with only a small pulse or tilt depending on the style; the
other icons follow the configured axis toward available screen space. Choose an unfold style in Settings: Arc
(the original curved motion), Glide (a synchronized straight slide), Cascade
(staggered icons, folding from the far end), Spring (a weighted overshoot), or
Swing (a wider arc with a small tilt). Dismissal folds the icons back to their saved
stack position. Leaving the fan starts an 800 ms grace period; returning cancels
it. Outside clicks fold it immediately and reach the underlying window. Workspace
changes also collapse the fan. Scroll or drag along the fan to reach overflow;
arrow keys follow its physical direction. Reduced uses fades; Off is immediate.
Outside-click detection uses non-consuming runtime mouse bindings while a fan is
open. They are disabled on close/removal and reused until the next Hyprland config
reload; existing mouse bindings are preserved.

Uses Omarchy's theme and shared controls. Configure grouping, visibility, icon
shapes, frames, corners, placement, and motion. Empty stashes occupy no screen
space or input; floating surfaces leave the surrounding desktop click-through.

## Setup

Requires **Omarchy 4.0**, **Hyprland 0.56.2 with its Lua API**, and **Python 3.9+**.
Tested on Omarchy 4.0.6-1. The shell must provide Quickshell, Qt 6.7+,
`qs.Commons`, `qs.Ui`, `Quickshell.Widgets`, and `QtQuick.Effects`.
Hover previews use the shell's `Quickshell.Wayland` module; no additional capture
package is needed.
Have `omarchy`, `omarchy-shell`, and `hyprctl` on `PATH`, with existing
`~/.config/hypr/bindings.lua` and `~/.config/omarchy/shell.json`.

Run as your normal user in an unlocked desktop session:

```sh
git clone https://github.com/artu-ole/omarchy-window-stash.git
cd omarchy-window-stash
python3 tools/install.py
omarchy restart shell
```

**Use the helper: generic Omarchy plugin installation does not install the
controller or shortcuts.** Keep this separate checkout for updates and removal;
the helper itself is not installed.

The helper previews changes and asks for confirmation (`--yes` for automation).
It installs `community.window-stash` under `~/.config/omarchy/plugins/`, creates
`~/.local/bin/window-stash`, adds a marked binding block to `bindings.lua`, and
enables the plugin in `shell.json`. It checks shortcut conflicts, backs up
configuration, reloads Hyprland while preserving runtime monitor geometry, and
rescans shell plugins. It uses no root privileges, downloads, or packaged-file
edits. If installed, `community.window-switcher` is patched for restoration;
incompatible integration anchors abort installation. Tested with switcher 1.0.0.

Update with `git pull`, rerun the helper, then restart the shell. Settings persist.
Remove from this checkout:

```sh
python3 tools/install.py --uninstall
```

Removal restores parked windows and removes the plugin, wrapper, binding block,
and known switcher edits; saved positions remain. Run this **before** generic
`omarchy plugin remove`, which does not run cleanup hooks. Configuration backups
live in `$XDG_STATE_HOME/omarchy/window-stash/backups` (default
`~/.local/state/omarchy/window-stash/backups`).

## Controls

| Action | Input |
|---|---|
| Stash focused window | **Super+A** |
| Restore last eligible window | **Super+Z**; newest first, obeys visibility scope |
| Restore / choose a grouped window | Click an icon; app groups open a searchable chooser |
| Restore destination, close, settings, all windows | Right-click an icon or floating stack |
| Close represented stashed window(s) | Middle-click an icon; collapsed stacks target their front icon |
| Move bubbles / floating dock | Drag the icon / stack handle; positions persist per monitor |
| Navigate chooser / expanded dock | Up/Down, Enter; horizontal docks also support Left/Right |
| Collapse floating dock | Click outside, switch focus/workspace, or press Escape |
| Preview a window | Hover an icon, floating stack, or chooser row; enable previews in Settings |
| Use a preview | Click to restore, middle-click to close, right-click for its window menu; wheel or arrow buttons browse app groups, **All windows** opens their chooser |

Shortcuts are ordinary Hyprland bindings to `window-stash minimize` and
`window-stash restore-last`; change them in your personal bindings as needed.
Open settings or the global recovery chooser even when the stash is empty:

```sh
omarchy-shell window-stash settings
omarchy-shell window-stash all
```

## Configuration

Settings belong to the `community.window-stash` entry in
`~/.config/omarchy/shell.json`. Use the UI or the shell's plugin-scoped API:

```sh
omarchy-shell window-stash configure presentation floating
omarchy-shell window-stash configure iconShape squircle
omarchy-shell window-stash configure animations reduced
omarchy-shell window-stash configure animationSpeed fast
omarchy-shell window-stash configure dockOpacity 60
omarchy-shell window-stash configure iconOpacity 75
omarchy-shell window-stash configure hoverPreview live
```

| Key | Default | Values / meaning |
|---|---|---|
| `presentation` | `dock` | `dock`, `bubbles`, `floating` |
| `scope` | `global` | `global`: repeat the stash on every monitor; `workspace`: filter by each screen's active workspace |
| `restoreDestination` | `current` | `current`, `original` |
| `grouping` | `window` | `window`, `app` (count badge and window chooser) |
| `iconShape` | `auto` | `auto`, `circle`, `square`, `rounded`, `squircle` |
| `dockSide` | `bottom` | `bottom`, `top`, `left`, `right`; static dock only |
| `floatingDirection` | `vertical` | `vertical`, `horizontal`; floating dock only |
| `floatingAnimation` | `arc` | `arc`, `glide`, `cascade`, `spring`, `swing`, `matryoshka`, `matryoshka-hop`; unfold/fold style, overridden by Reduced/Off |
| `floatingPlacement` | `edges` | `edges`, `free`; both floating presentations |
| `dragMotion` | `physics` | `physics`: momentum and gentle collisions; `direct`: direct placement with the existing edge glide |
| `iconFrame` | `shown` | `shown`, `hidden`; hidden removes border/background and enlarges artwork |
| `dockFrame` | `shown` | `shown`, `hidden`; static and expanded floating docks |
| `dockOpacity` | `100` | Integer `0`–`100`%; dock background and border at rest |
| `iconOpacity` | `100` | Integer `0`–`100`%; icons, frames and badges at rest, across all presentations |
| `dockCorners` | `theme` | `theme`, `custom`; independent of icon shape |
| `dockCornerRadius` | `12` | Integer `0`–`64` pixels in custom mode, clamped to panel dimensions |
| `animations` | `full` | `full`: fades, settling, reflow, resizing, artwork crossfades, hover/press; `reduced`: fades/color without movement or scaling; `off`: immediate |
| `animationSpeed` | `normal` | `slow` (0.5×), `relaxed` (0.75×), `normal` (1×), `fast` (1.5×), `ultrafast` (2.5×) playback speed |
| `hoverPreview` | `off` | `off`, `still`, `live`; still captures once when opening or choosing another window, live updates while the card is open |
| `previewSize` | `medium` | `small`, `medium`, `large`; maximum image widths of 200, 280, or 380 logical pixels, reduced to fit the work area |
| `previewPlacement` | `auto` | `auto`, `above`, `below`, `left`, `right`; flips or shrinks when the requested side has insufficient room |
| `previewTitles` | `shown` | `shown`, `hidden` |
| `previewDelay` | `400` | Integer `0`–`1500` ms before showing a preview |
| `previewHideDelay` | `200` | Integer `0`–`1000` ms grace period when moving between the source icon and its card |

Preview cards follow the Omarchy popup theme and work across all presentations
and chooser rows. A collapsed stack previews its front window or app group;
app groups use one card with a window counter and navigation. Hovering never
focuses, moves, or restores a window. Pressing or dragging an icon, source motion,
context menus, settings, and workspace changes dismiss previews. Settings scroll
on shorter displays.

Hover smoothly restores full opacity; pressed and keyboard-selected icons stay
opaque. Dock and icon opacity are independent. Transparent elements retain their
normal input regions, including at 0%; menus and settings keep their theme opacity.
Fades follow the animation setting.

Animation speed scales transitions and staggering across all fan styles, icon
arrivals/exits, reflow, artwork, previews, hover/button feedback, Direct edge
glides, and final settling. Easing and destinations stay the same. Preview hover
delays, capture timeouts, and physical momentum use real time. The fan's 800 ms
pointer-leave grace starts after unfolding finishes; outside clicks still dismiss
immediately. Reduced continues to suppress spatial motion; Off stays immediate
at every speed.

Matryoshka moves the remaining stack together to each next slot, leaving one
icon behind at every stop. Matryoshka hops uses the same sequence with an arch
between stops. The original front icon stays fixed; folding collects the icons
in reverse. Both follow the floating direction and keep movement inside the
work area. Reduced/Off use immediate positions instead.

With Physics and Full animations, floating icons and the collapsed stack track
the pointer directly, then coast after a flick. Icons gently nudge one another;
edge mode docks near the predicted stopping point and free mode coasts to rest.
Grabbing, opening a menu, or unfolding stops momentum immediately. Only resting
positions are saved, including nudged neighbors. Motion stays inside the current
monitor's usable area. Reduced/Off suppress inertia and collisions.

Frames can be hidden independently. Automatic shapes and theme corners follow
the desktop; custom choices persist when their frames are hidden. Rounded docks
reserve space at their ends so large radii keep icons intact without increasing
dock thickness. Placement
still applies with animations off. Changes take effect without a shell restart.

## Restoration contract

- **Floating:** restore logical size and monitor-relative position, clamped to
  the destination work area and application size limits.
- **Tiled:** insert a new tile. Scrolling layouts append a column in the
  configured direction and restore the saved visible width, subject to layout
  policy and application limits. Dwindle uses normal insertion.
- **State:** restore maximized, fullscreen, and pinned state after geometry.
  Stashing one Hyprland group member restores it as a separate window.
- **Workspaces:** recreate an empty original workspace when needed. If its
  monitor is missing, map its local slot to the invoking screen's workspace bank,
  honoring `hypr/monitor-workspaces.lua`. Workspace-ID changes update origins;
  arbitrary external workspace merges cannot be reversed automatically.
- **Lifetime:** closed windows leave the stash. Shell restarts preserve it;
  logout/compositor restart does not restore application sessions. Existing
  scratchpads and windows minimized by other tools are outside plugin ownership.

Right-click opens a pointer-positioned context menu. Restore and close actions
above the separator target that icon's window or app group; a collapsed stack
targets its front icon. Global actions below the separator include Settings,
the recovery chooser, and Close all (following Stash visibility). Outside clicks
dismiss the menu and reach the underlying window.

## Controller API and recovery

The controller works without the QML frontend. Commands return JSON (`ok` plus
result/error); failures exit nonzero.

```sh
window-stash minimize                          # optional: --address ADDRESS
window-stash restore-last                      # optional: --to current|original
window-stash restore ID --to original          # ID or live window address
window-stash restore-all --to current          # global recovery, ignores scope
window-stash close ID [ID ...]                 # only owned stashed windows
window-stash close-all                         # follows global/workspace scope
window-stash list                              # reconciled windows/settings/positions
window-stash status                            # alias of list
```

Close commands send normal window-close requests and confirm disappearance. A
batch shares a 750 ms grace period; remaining windows restore to the invoking
workspace for save prompts. Unstashed windows are untouched; failures return
per-window results and leave recoverable records.

Restore and close commands accept `--monitor OUTPUT --workspace ID` to pin invocation
context before a chooser takes focus. `activate ADDRESS` restores an owned
window or focuses an unmanaged one. Internal helpers: `position MONITOR KEY X Y`
and `rebase OLD_ID NEW_ID`. Frontend IPC also exposes `status`, `refresh`, and
`dismiss` through `omarchy-shell window-stash`.

## Internals and local data

[Service.qml](Service.qml) serializes controller requests and watches compositor
events and state/config files. Visible edge surfaces refresh bar reservations
every 1.5 seconds. [ui/](ui/) contains the themed surfaces, placement model,
feedback, and keyed animation lifecycles. The shared drag world uses a
frame-driven fixed-step simulation with bounded momentum and soft collisions. [controller/stash.py](controller/stash.py)
parks windows on `special:minimized` with ownership tags, validates client
identity, and writes an atomic, locked ledger before moving windows. Interrupted
restores retain records for retry.

| Data | Location |
|---|---|
| Session ledger | `$XDG_RUNTIME_DIR/omarchy-window-stash/<sanitized compositor signature>/state.json` |
| Persistent bubble / stack positions | `$XDG_STATE_HOME/omarchy/window-stash/bubbles.json` |
| Plugin settings | `$XDG_CONFIG_HOME/omarchy/shell.json` |

XDG config/state fall back to `~/.config` and `~/.local/state`. Runtime records
include window titles, application IDs, monitor identity, and geometry; persistent
positions can include monitor identifiers. These stay local. No telemetry or
network requests. App icons resolve from installed desktop entries and themes.

Previews use native [ScreencopyView](https://quickshell.org/docs/v0.3.0/types/Quickshell.Wayland/ScreencopyView/)
with one selected window captured at a time. Sources must match the stash's exact
window identity and ownership; hidden windows stay in their special workspace.
Frames remain in memory and are released when the card closes; no thumbnail files
are saved. Background applications may stop drawing, so a live card can retain
its last frame. Capture failures or timeouts show the app icon, and compositor
capture restrictions are respected.

## Development

```sh
python3 tools/check.py             # unit/model checks, offscreen Qt, manifest, qmllint
python3 tests/live.py              # controller + desktop integration
python3 tests/animation_modes.py   # native Full / Reduced / Off lifecycles
python3 tests/animation_speed.py   # speed presets, duration scaling and live changes
python3 tests/transparency.py      # rendered alpha, hover, keyboard and persistence
python3 tests/floating_fan.py      # pointer alignment, persistent actors, curves and dismissal
python3 tests/matryoshka.py --small-output # nested-stack stages, inverse folding, both axes and overflow
python3 tests/hover_previews.py --small-output # native captures, hover lifecycle, grouping and bounded placement
python3 tests/close_actions.py     # isolated ledger: closure, scope and native save prompts
python3 tests/context_actions.py   # pointer menu, targets, keyboard, click-through and scaled output
python3 tests/middle_close.py      # pending icons, grouped close and cancellation
python3 tests/drag_physics.py      # real flicks, collisions, catching, edges and saved positions
```

Non-graphical checks require Node.js, `qs`, Qt6 `qmllint`, and Omarchy's validator
(with `jq`). Desktop suites also require an unlocked session, the installed
plugin, `/usr/bin/python3` with GTK4 introspection, `wtype`, `notify-send`, and
`grim`. Start with an empty stash. Suites use disposable windows/virtual outputs,
notify **five seconds before taking input**, and restore desktop state in cleanup.
See [tests/](tests/) and [VALIDATION.md](VALIDATION.md) for coverage and commands.

Copyright © 2026 **artu-ole** · [AGPL-3.0-only](LICENSE) · [Third-party notices](THIRD_PARTY_NOTICES.md).
Header diagram: [generation prompt](assets/title-prompt.txt).
