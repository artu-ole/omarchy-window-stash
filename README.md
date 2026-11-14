# Window Stash

![Window Stash: static dock, floating dock, floating icons and floating previews.](preview.png)

Window minimization for **tiling layouts** in Omarchy/Hyprland. Stash running windows
in a private workspace and restore them to the current or original workspace.
Floating windows retain size and position; scrolling layouts retain window width.

| Mode | Behavior |
|---|---|
| Static dock | Any screen edge, bar clearance and overflow scrolling. Unlock to drag along the edge; lock to retain placement. |
| Floating dock | Draggable stack; one window restores directly, multiple windows unfold into a row or column. |
| Floating icons | Independent icons with edge gravity or free placement; called **Floating bubbles** in Settings. |
| Floating previews | Resizable miniatures with snapshot/live updates, optional app interaction and fullscreen inside the preview. |

All modes follow Omarchy's theme, support individual windows or app groups, and
show the global stash or only the current workspace's entries. Positions persist
per monitor; static dock placement also persists per edge. An empty stash occupies
no space. The default is a floating dock with edge gravity and hidden backgrounds.
Omarchy's floating workspace mode uses its native dock; individual floating windows
on tiled workspaces remain supported.

| Static dock with grouping and hover previews | Floating previews |
|---|---|
| ![Grouped Ghostty windows and a live Brave hover preview.](docs/media/static-dock.png) | ![Borderless Brave, Ghostty, PDF and Files previews.](docs/media/floating-previews.png) |

## Installation

Works on **Omarchy 4 and 4.5**. Requires Python 3, Git, Hyprland Lua IPC
(`hyprctl eval`/`repl`) with runtime `hl.bind`/`hl.on`, and the shell modules
`qs.Commons`, `qs.Ui`, `Quickshell.Widgets`, `QtQuick.Effects` and `Quickshell.Wayland`.
Run as your desktop user:

```sh
omarchy plugin add https://github.com/artu-ole/omarchy-window-stash --enable
```

Update:

```sh
omarchy plugin update community.window-stash
```

Remove:

```sh
omarchy plugin remove community.window-stash
```

Setup and cleanup are automatic. Disabling/removing restores owned stashed windows
and releases shortcuts. Updates and shell restarts retain the stash; preferences
and positions survive removal. Occupied shortcuts stay inactive and report a
conflict in Settings without replacing personal bindings.

Older helper installations migrate automatically, backing up recognized legacy
integrations and preserving customized files and personal overrides. If an old
service remains loaded after an update, run `omarchy restart shell` once.

## Controls

| Input | Action |
|---|---|
| Super+D | Minimize the focused window; over a floating preview, fold it into an icon. |
| Super+Z / Super+Alt+Z | Restore newest / oldest eligible window. Folded previews unfold first. |
| Click | Restore a window; groups/stacks expand for selection. Preview interaction can optionally use first-click activation. |
| Right-click | Window/app menu, Settings, recovery and Close all. During interaction, use **Manage**. |
| Middle-click / title × | Close represented stashed windows; title × requires titles enabled. Interactive content receives application input. |
| Drag | Move floating items or an unlocked static dock. Preview sides change proportions; corners scale proportionally; Super+corners reshape freely. |
| Scroll / arrows / Enter | Scroll overflowing collections; navigate and select in choosers, unfolded docks and preview groups. |
| Escape / outside click | Dismiss menus and expanded views. During interaction, plain Escape reaches the app. |

Close requests wait for the client; windows with save prompts restore. Unstashed
instances are unaffected. Restoration
preserves floating geometry, fullscreen/pinned state and scrolling width within
the destination's bounds; tiled windows rejoin the layout. Missing monitors fall
back to the current monitor's workspace bank and saved slot. Switcher activation
restores the selected window automatically.

Open Settings or the recovery chooser even with an empty stash:

```sh
omarchy-shell window-stash settings
omarchy-shell window-stash all
```

## Settings

Settings apply immediately and live under `community.window-stash` in
`$XDG_CONFIG_HOME/omarchy/shell.json`. Shortcut fields support Apply, disable and
reset; duplicate/occupied chords are rejected. **Reset all** requires confirmation
and retains stashed windows and positions. IPC accepts the keys below:

```sh
omarchy-shell window-stash configure presentation floating
omarchy-shell window-stash configure sizePreset 150
```

### Placement and appearance

| Key | Default | Options / meaning |
|---|---|---|
| `presentation` | `floating` | `dock`, `floating`, `bubbles`, `previews` |
| `scope` | `global` | `global`: shared across monitors; `workspace`: filter by original workspace, including restore shortcuts and Close all |
| `restoreDestination` | `current` | `current`, `original` |
| `grouping` | `window` | `window`, `app`; groups show a count badge |
| `dockSide` | `bottom` | `bottom`, `top`, `left`, `right` |
| `staticDockLock` | `locked` | `locked`, `unlocked`; edge dragging |
| `floatingDirection` | `vertical` | `vertical`, `horizontal`; floating dock |
| `floatingPlacement` | `edges` | `edges`, `free`; floating icons, dock and previews |
| `iconShape` | `auto` | `auto`, `circle`, `square`, `rounded`, `squircle` |
| `sizePreset` | `100` | Percent: 50, 75, 100, 125, 150, 175, 200, 250, 300; bounded by screen area |
| `iconFrame` / `dockFrame` | `hidden` | `shown`, `hidden`; hiding icon frames enlarges artwork |
| `iconOpacity` / `dockOpacity` | `100` | 0–100%; icon/preview opacity and dock background opacity |
| `dockCorners` | `theme` | `theme`, `custom`; independent of icon shape |
| `dockCornerRadius` | `12` | 0–64 px; custom corners, without clipping icons |

Hover restores full opacity and tints icons. Active interactive previews remain
opaque. Zero-opacity elements still accept input.

### Motion

| Key | Default | Options / meaning |
|---|---|---|
| `dragMotion` | `physics` | `physics`: flicks, coasting, collisions and trailing stack icons; `direct` |
| `floatingAnimation` | `arc` | `arc`, `glide`, `cascade`, `spring`, `swing`, `matryoshka`, `matryoshka-hop`, `jumping` |
| `animations` | `full` | `full`, `reduced` (fades/color), `off` |
| `animationSpeed` | `normal` | `slow` 0.5×, `relaxed` 0.75×, `normal` 1×, `fast` 1.5×, `ultrafast` 2.5× |

The floating dock unfolds from its fixed front icon and folds 800 ms after pointer
leave. Outside clicks fold it immediately and reach the underlying window. Speed
controls transitions and stack following; hover delays and coasting are independent.

| Horizontal floating dock | Floating icons with edge gravity |
|---|---|
| ![Floating stack unfolding into a row and folding back.](docs/media/floating-dock.gif) | ![Floating icon snapping back to the edge after dragging.](docs/media/floating-icons-gravity.gif) |

### Floating previews

Previews start borderless and untitled. Sides reshape and reflow the hidden app;
ordinary corners preserve proportions, Super+corners change both dimensions.
Original restoration geometry stays intact. Position, size and proportions persist
per monitor, separately from icon positions. Right-click **Reset preview proportions**
to restore the original ratio. Locked placement or preset sizing disables resizing.

| Key | Default | Options / meaning |
|---|---|---|
| `floatingPreviewSizing` | `free` | `free`: drag to resize; `preset`: scale dropdown |
| `floatingPreviewScale` | `100` | Same nine percentage presets; 100% is 280 logical px wide, bounded by screen area |
| `floatingPreviewUpdate` | `hover` | `still`: snapshot; `hover`: live on hover; `live`: always live |
| `floatingPreviewResizeRate` | `realtime` | `realtime`: Responsive; `balanced`: fewer app updates; `release`: reflow on release |
| `floatingPreviewTitles` / `floatingPreviewFrame` | `hidden` | `hidden`, `shown`; title/close strip and background/border |
| `floatingPreviewLock` | `unlocked` | `unlocked`, `locked`; movement and resizing |

Responsive/Balanced reshape drags temporarily update snapshots live, then resume
the saved policy. Minimize over a preview to fold it into an icon. Clicking the
icon or using newest/FIFO unfolds it first; the next action restores the window
without changing stash order. Context-menu and CLI restore skip folding stages.
App covers fold together; expanded thumbnails fold individually. Folded icons
inherit icon appearance and placement settings.

### Preview interaction

Enable **Preview interaction → Interactive previews** in Floating previews mode.
Use **Interact** or **Super+left click** on content; activation does not click the
app. Group covers expand first for exact-window selection. Optional keyboard input
acquires focus on a content click, never on hover.

![Using, resizing and scrolling a stashed Brave preview; optional interactive resize handles enabled.](docs/media/interactive-preview.gif)

| Key | Default | Options / meaning |
|---|---|---|
| `floatingPreviewInteraction` | `off` | `off`, `on` |
| `floatingPreviewActivation` | `explicit` | `explicit`: Interact; `click`: first click activates; Super+left click works with either |
| `floatingPreviewKeyboard` | `mouse` | `mouse`: pointer only; `click`: mouse and click-to-focus keyboard |
| `floatingPreviewFullscreen` | `preview` | `preview`: fullscreen inside miniature; `desktop`: restore for fullscreen |
| `floatingPreviewInteractionFps` | `60` | `30`, `60`; active rendering limit |
| `floatingPreviewControls` | `hover` | `hover`, `always`; controls when inactive, always visible during interaction |
| `floatingPreviewInteractionResize` | `off` | `off`, `on`; resize handles during interaction |
| `floatingPreviewExitShortcut` | `CTRL + ALT + Escape` | Session-only exit chord; empty disables; occupied bindings rejected |

One preview receives app input at a time and renders live independently of the
saved update policy. It supports clicks, scrolling, dragging and, when enabled,
typing, selection, clipboard and app shortcuts. Browser tabs stay inside the preview.
With the default fullscreen policy, a video's fullscreen button, F11 or Super+F
fills the miniature; keyboard commands require keyboard focus. Fullscreen remains
after stopping input. For continuous picture-in-picture, choose **Always live**
and **Enhanced** support.

**Stop**, the exit shortcut or an outside click ends interaction; pointer leave
does not. Use **Stop** or **Manage** before moving. Optional interactive resize
handles pause app input during a drag and resume when the new frame is ready.
Modal dialogs, overflowing popups and external activation/window-management requests
restore the full window. Pointer-locked apps, cross-window drag-and-drop and
input-method popup positioning require restoration. Interaction respects
`no_screen_share`; keyboard input also respects `no_focus`.

### Hover previews

Icon/dock modes support individual thumbnails for grouped windows, with overflow
scrolling. Click restores, middle-click closes and right-click opens the menu.

| Key | Default | Options / meaning |
|---|---|---|
| `hoverPreview` | `off` | `off`, `still`, `live` |
| `livePreviewCompatibility` | `standard` | `standard`: app-supplied frames; `enhanced`: native rendering support |
| `previewSize` | `medium` | `small`, `medium`, `large`: maximum widths 200/280/380 logical px |
| `previewPlacement` | `auto` | `auto`, `above`, `below`, `left`, `right`; adjusts to available space |
| `previewTitles` | `shown` | `shown`, `hidden`; title strips include close buttons |
| `previewDelay` | `400` | 0–1500 ms before opening |
| `previewHideDelay` | `200` | 0–1000 ms pointer-transfer grace |

### Native preview support

Standard frames can freeze when hidden apps stop drawing. Enhanced support keeps
visible live previews updating, including Ghostty/btop. Hover previews need **Live**
and **Enhanced**; floating previews use their own update policy.

Enhanced rendering, custom proportions, Super gestures and interaction use a local
Hyprland bridge, built/loaded automatically as needed. Requires x86-64, a C++26
compiler, `pkg-config` and development headers matching the running compositor.
Setup errors appear in Settings; ordinary stashing and Standard previews still work.
Enhanced rendering is limited to 15 FPS, active interaction to its selected 30/60 FPS.
Hidden previews release capture resources; capture pauses on lock/display sleep.
Apps may still throttle their own drawing.

Bridge updates offer **Reload preview support / Later**, preserving windows and the
stash while ending interaction and temporary fullscreen. The earliest experimental
interactive bridge requires one logout/login. Header mismatches require matching
headers; after a compositor upgrade, restart the session to run the matching build.

### Shortcuts

| Key | Default |
|---|---|
| `minimizeShortcut` | `SUPER + D` |
| `restoreLastShortcut` | `SUPER + Z` |
| `restoreOldestShortcut` | `SUPER + ALT + Z` |

Empty values disable an action. Restore actions follow visibility scope and the
configured destination. Updates preserve saved shortcuts, including disabled ones.

## Development

Shell IPC: `omarchy-shell window-stash` with `settings`, `all`, `minimize`,
`restoreLast`, `restoreOldest`, `configure KEY VALUE`, `status`, `refresh`, `dismiss`.
For controller commands, use `python3 controller/stash.py --help`.
[Service.qml](Service.qml) and [ui/](ui/) provide the frontend; [controller/](controller/)
manages the locked ledger, runtime shortcuts and cleanup. Only owned/tagged windows
on `special:window-stash` are managed. Logout/compositor restart does not preserve
application sessions.

| Local data | Location |
|---|---|
| Settings | `$XDG_CONFIG_HOME/omarchy/shell.json` |
| Session ledger/locks | `$XDG_RUNTIME_DIR/omarchy-window-stash/<compositor signature>/` |
| Positions, preference checkpoint, recovery errors, migration backups | `$XDG_STATE_HOME/omarchy/window-stash/` |
| Native bridge cache | `$XDG_CACHE_HOME/omarchy/window-stash/preview-bridge/` |

Data can include window titles, app IDs, monitor identifiers and geometry. It stays
local, with no telemetry or runtime network requests; preview frames remain in
memory. Keep runtime data and raw recordings out of commits.

```sh
python3 tools/check.py
# Build the optional bridge without loading it:
python3 tools/build-preview-bridge.py --cache-dir /tmp/window-stash-preview-cache
```

Checks require Python, Node.js, `qs`, Qt6 `qmllint`, Omarchy's validator and `jq`;
standalone Lua enables binding/focus tests. Native desktop suites in [tests/](tests/)
also use GTK4 introspection, `wtype`, `notify-send` and `grim`. Run them in an isolated
session. Follow [AGENTS.md](AGENTS.md): notify and wait five seconds before input
or desktop changes, preserve user state, and notify again after cleanup.
Bump [native/version.txt](native/version.txt) when native code changes.

Copyright © 2026 **artu-ole**. [AGPL-3.0-only](LICENSE).
[Third-party notices](THIRD_PARTY_NOTICES.md).

OpenAI Codex assisted extensively with implementation, tests, documentation and
debugging; the header image was AI-generated. The plugin makes no AI service calls
at runtime.
