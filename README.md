# Window Stash

![Static dock, floating dock, floating icons and window previews.](preview.png)

Window minimization for **tiling layouts** in Omarchy/Hyprland. Windows stay running
in a private workspace and restore to the original or current workspace. Floating
windows retain size and position; scrolling layouts retain window width.

| Mode | Behavior |
|---|---|
| Static dock | Four edges, bar clearance and overflow scrolling. Unlock to drag along the edge; lock to retain placement. |
| Floating icons | Individual draggable icons, initially at the middle right. Edge gravity or free placement. |
| Floating dock | Draggable stack. One window restores directly; multiple windows unfold into a row or column. |
| Floating previews | Resizable window miniatures; app groups expand into individual thumbnails. Optional mouse/keyboard input and fullscreen within the preview. |

All modes follow Omarchy's theme. Visibility is global across monitors or filtered
by original workspace; icons and previews represent individual windows or application groups.
Positions persist per monitor; static dock placement also persists per edge.
An empty stash occupies no screen space.

## Installation

Works on **Omarchy 4 and 4.5**. Requires Python 3, Git, Hyprland Lua IPC
(`hyprctl eval`/`repl`) with runtime `hl.bind` handles, and the shell modules
`qs.Commons`, `qs.Ui`, `Quickshell.Widgets`, `QtQuick.Effects` and `Quickshell.Wayland`.
Install as your desktop user:

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

Setup and cleanup are automatic. Disabling or removing restores owned stashed windows
and releases shortcuts; updates and shell restarts retain the stash. Preferences
and positions survive removal. Occupied shortcuts remain inactive and report a
conflict in Settings without replacing personal bindings.

Older Git-managed helper installations migrate on load, backing up verified
legacy integrations before removing them. Run `omarchy restart shell` once after
updating if the old service remains loaded. Customized files and explicit personal
overrides are preserved.

## Controls

| Input | Action |
|---|---|
| Super+D | Stash focused window. |
| Super+Z | Restore newest eligible window: last in, first out. |
| Super+Alt+Z | Restore oldest eligible window: first in, first out. |
| Click icon | Restore; multi-window app groups open a searchable chooser. Floating stacks unfold first. |
| Click preview | Restore; app covers expand into individual window thumbnails. |
| Preview Interact control | Enter interaction; optional first-click activation consumes the activating click. |
| Interactive preview content | Application clicks, scrolling, selection and dragging; typing when click-to-focus keyboard input is enabled. |
| Ctrl+Alt+Escape / Stop | Leave preview interaction. The shortcut is configurable; plain Escape reaches the application. |
| Right-click icon/stack | Pointer-positioned window/app menu, Settings, recovery and Close all. |
| Middle-click icon/view-only thumbnail | Close represented stashed window(s). Unstashed instances are unaffected. |
| Thumbnail title × | Close the represented stashed window(s); requires a title strip. |
| Drag | Move floating items or an unlocked static dock. Resize a floating preview from a corner. Scroll overflowing lists. |
| Arrow keys / Enter | Navigate and select in choosers, unfolded docks or preview groups. |
| Escape / outside click | Dismiss menus, choosers, hover previews and expanded groups/stacks. |

Close requests wait for the client; surviving windows restore for application-owned
save prompts. Restoration preserves floating geometry, fullscreen/pinned state and
scrolling width, bounded by the destination output and layout. Tiled windows rejoin
the layout. Missing monitors use the current monitor's workspace bank and saved slot.
Windows activated through a switcher restore automatically.

Open Settings with `omarchy-shell window-stash settings`, or the recovery chooser
with `omarchy-shell window-stash all`; both work with an empty stash.

Settings scroll on smaller screens. Shortcut fields support Apply, disable and
reset to default; duplicate/occupied chords are rejected. Updates preserve saved
shortcuts, including disabled actions. Reset all requires confirmation and retains
stashed windows and positions; shortcut conflicts leave settings unchanged.

## Settings

Stored in the `community.window-stash` entry in
`$XDG_CONFIG_HOME/omarchy/shell.json`. Use Settings or IPC; changes apply immediately:

```sh
omarchy-shell window-stash configure presentation floating
omarchy-shell window-stash configure sizePreset 150
```

### General and placement

| Key | Default | Values / meaning |
|---|---|---|
| `presentation` | `floating` | `dock`, `bubbles`, `floating`, `previews` |
| `scope` | `global` | `global`: shared stash on all monitors; `workspace`: filter icons, newest/oldest restore and Close all by original workspace |
| `restoreDestination` | `current` | `current`, `original` |
| `grouping` | `window` | `window`, `app`; groups show a count badge |
| `dockSide` | `bottom` | `bottom`, `top`, `left`, `right` |
| `staticDockLock` | `locked` | `locked`, `unlocked`; static dock edge dragging |
| `floatingDirection` | `vertical` | `vertical`, `horizontal`; floating dock |
| `floatingPlacement` | `edges` | `edges`, `free`; floating icons, dock and previews |

### Appearance

| Key | Default | Values / meaning |
|---|---|---|
| `iconShape` | `auto` | `auto`, `circle`, `square`, `rounded`, `squircle` |
| `sizePreset` | `"100"` | String percent: 50, 75, 100, 125, 150, 175, 200, 250, 300; icon/dock modes, bounded by usable screen area |
| `iconFrame` | `hidden` | `shown`, `hidden`; hiding removes background/border and enlarges artwork |
| `dockFrame` | `hidden` | `shown`, `hidden`; static and floating docks |
| `iconOpacity` | `100` | 0–100%; icons or floating previews at rest |
| `dockOpacity` | `100` | 0–100%; dock background/border at rest |
| `dockCorners` | `theme` | `theme`, `custom`; independent of icon shape |
| `dockCornerRadius` | `12` | 0–64 px in custom mode; clamped without cutting icons |

Default backgrounds are hidden; artwork remains opaque. Hover tints icons and
restores full opacity. Active interactive previews remain opaque. Zero-opacity
elements retain their input regions.

### Motion

| Key | Default | Values / meaning |
|---|---|---|
| `dragMotion` | `physics` | `physics`: flicks, coasting, collisions and trailing stack icons; `direct`: direct placement |
| `floatingAnimation` | `arc` | `arc`, `glide`, `cascade`, `spring`, `swing`, `matryoshka`, `matryoshka-hop`, `jumping` |
| `animations` | `full` | `full`: motion/feedback; `reduced`: fades/color; `off`: immediate |
| `animationSpeed` | `normal` | `slow` 0.5×, `relaxed` 0.75×, `normal` 1×, `fast` 1.5×, `ultrafast` 2.5× |

The floating dock unfolds with the newest icon at the pointer and its front anchor
fixed. Horizontal arches travel upward; the background grows along the unfolding
axis. Pointer leave folds after an 800 ms grace; outside clicks fold immediately
and reach the underlying window. Speed scales transitions and stack follow, not
hover delays or coasting momentum.

### Previews

Floating previews are borderless and untitled by default. Corner dragging preserves
the captured window's proportions and changes only the miniature; saved restoration
geometry stays unchanged. Position and width persist separately from floating icons.
Lock placement to prevent movement and resizing. Free sizing hides the scale dropdown.

Sources retain their saved dimensions while hidden. Tiled windows float inside the
private stash and rejoin the tiling layout on restore, preserving scrolling width.
Stashing another window or starting live updates does not reshape existing sources.

| Key | Default | Values / meaning |
|---|---|---|
| `floatingPreviewSizing` | `free` | `free`: resize directly; `preset`: use the scale dropdown |
| `floatingPreviewScale` | `"100"` | Same nine percentage presets; 100% is 280 logical px wide, bounded by screen area |
| `floatingPreviewUpdate` | `hover` | `still`: snapshot; `hover`: live on hover; `live`: always live |
| `floatingPreviewTitles` | `hidden` | `hidden`, `shown`; optional title strip and close button |
| `floatingPreviewFrame` | `hidden` | `hidden`, `shown`; optional background and border |
| `floatingPreviewLock` | `unlocked` | `unlocked`, `locked`; retain placement and dimensions |

Click restores; dragging moves; middle-click closes; right-click opens the window
menu. Grouped cards expand into a bounded grid for exact-window selection.

Optional interaction is configured under **Preview interaction**:

| Key | Default | Values / meaning |
|---|---|---|
| `floatingPreviewInteraction` | `off` | `off`, `on`; floating previews only |
| `floatingPreviewActivation` | `explicit` | `explicit`: Interact control/context action; `click`: first click enters interaction without forwarding that click |
| `floatingPreviewKeyboard` | `mouse` | `mouse`: pointer only; `click`: content click also acquires keyboard focus; hover never does |
| `floatingPreviewFullscreen` | `preview` | `preview`: fullscreen stays inside the miniature; `desktop`: restore the window for fullscreen |
| `floatingPreviewInteractionFps` | `"60"` | `"30"`, `"60"`; active preview rendering limit |
| `floatingPreviewControls` | `hover` | `hover`, `always`; controls stay visible during interaction |
| `floatingPreviewExitShortcut` | `CTRL + ALT + Escape` | Session-only exit chord; empty disables it. Occupied desktop shortcuts are rejected. |

Interact makes one window receive normal left/right/middle clicks, wheel input and
content dragging. App groups require choosing an individual window. Keyboard mode
supports typing, selection, native copy/paste and application shortcuts. In-bounds
application popups are rendered and receive input at the miniature's scale.
Opening or switching browser tabs keeps the window inside the preview.

**Fullscreen → Inside preview** is the default. A video's fullscreen button fills
the miniature with the player; F11 or Super+F uses application fullscreen while
the preview has keyboard focus. The window stays stashed at its saved dimensions.
Fullscreen content remains expanded after Stop or an outside click. Restore clears
this temporary state and reapplies the original window geometry/fullscreen state.
For continuous picture-in-picture, choose **Preview updates → Always live** and
**Live preview support → Enhanced**. Player controls and aspect ratio remain
application-controlled. **Fullscreen → On desktop** retains normal restoration.

An active miniature has a themed outline and Stop/Restore/Manage controls. The
toolbar sits outside the image when space permits; its inline fallback excludes
those buttons from application input. Stop waits for native input release before
moving or resizing becomes available. Movement/physics pauses during interaction;
the source geometry remains unchanged. Outside clicks stop interaction and reach
their destination once; moving the pointer away alone keeps it active.

Interaction loads native support automatically and uses live capture independently
of the ordinary snapshot/hover and Standard/Enhanced preferences. Its setup
requirements are the same as Enhanced previews below. Pointer-locked applications,
cross-window drag-and-drop and input-method popup positioning require the restored
window. Interaction respects `no_screen_share`; keyboard input also respects
`no_focus` window rules.

Modal dialogs, desktop fullscreen requests and out-of-bounds popups restore the full
window using the configured destination. New dialogs follow their parent; pre-existing
windows remain in place. External application activation and window-management
requests also leave miniature interaction. See [VALIDATION.md](VALIDATION.md) for acceptance checks.

Hover previews for the other three display modes:

| Key | Default | Values / meaning |
|---|---|---|
| `hoverPreview` | `off` | `off`, `still`, `live` |
| `livePreviewCompatibility` | `standard` | `standard`: client-supplied frames; `enhanced`: optional native rendering support |
| `previewSize` | `medium` | `small`, `medium`, `large`: maximum widths 200/280/380 logical px, bounded by screen area |
| `previewPlacement` | `auto` | `auto`, `above`, `below`, `left`, `right`; adjusts to available space |
| `previewTitles` | `shown` | `shown`, `hidden`; title strips include the close button |
| `previewDelay` | `400` | 0–1500 ms before opening |
| `previewHideDelay` | `200` | 0–1000 ms pointer-transfer grace |

Still captures once per opening; Live refreshes supplied frames. Application groups
show windows side by side with overflow scrolling. Thumbnails support restore,
context menus and closure without focusing or restoring windows on hover.

**Live Ghostty/btop previews:** in Settings → Previews, set **Hover preview**
to **Live** and **Live preview support** to **Enhanced**. Standard can freeze when a
hidden client stops drawing. Enhanced builds and loads a local Hyprland bridge on
first use; it requires x86-64, a C++26 compiler, `pkg-config` and development headers
matching the running compositor. Build/load failures appear in Settings; standard
previews remain available.

Floating previews use the same Standard/Enhanced support independently of the hover
preview setting. Hidden cards release capture resources. Capture pauses while the
session is locked or its display sleeps; live cards resume when available.

Enhanced keeps only verified windows with visible live thumbnails drawing at up to
15 FPS; the active interactive source has its separate 30/60 FPS limit. Hiding
previews releases rendering leases; no global rendering rules or app profiles
change. Application-level throttling can still limit updates. Updating an already
loaded native bridge shows **Reload preview support / Later** in a notification
and Settings. Reload replaces only the bridge, preserving applications and the
stash; interaction and temporary preview fullscreen end and can be entered again.
Fresh installs load support on demand. Older experimental bridges without safe reload support,
or headers from a newer compositor than the running session, require logout/login.
See [native/README.md](native/README.md) for the bridge implementation and build API.

### Shortcuts

| Key | Default | Meaning |
|---|---|---|
| `minimizeShortcut` | `SUPER + D` | Stash focused window |
| `restoreLastShortcut` | `SUPER + Z` | Restore newest eligible window |
| `restoreOldestShortcut` | `SUPER + ALT + Z` | Restore oldest eligible window |

Empty strings disable an action. Restore actions follow visibility scope and the
configured destination. Per-field reset and Reset all use the same defaults.
The interactive exit chord above is active only during interaction and does not
register another global binding.

## API and implementation

Shell IPC exposes `settings`, `all`, `minimize`, `restoreLast`, `restoreOldest`,
`configure KEY VALUE`, `status`, `refresh` and `dismiss` through
`omarchy-shell window-stash`.

The Python controller returns JSON and exits nonzero on failure:

```sh
controller="$HOME/.config/omarchy/plugins/community.window-stash/controller/stash.py"
python3 "$controller" --help
```

Commands: `minimize [--address ADDRESS]`, `restore ID`, `restore-last`,
`restore-oldest`, `restore-all`, `close ID [ID ...]`, `close-all`, `activate ADDRESS`,
`shortcut KEY BINDING`, `shortcuts-sync`, `interaction-exit-shortcut BINDING`,
`reset-settings --confirm`, `list`, `status`.
Restore/activate accept `--to current|original`; restore/activate/close accept
`--monitor OUTPUT --workspace ID`. `restore-all` ignores visibility scope.
Internal helpers: `position MONITOR KEY X Y`, `preview-position MONITOR KEY X Y WIDTH`,
`rebase OLD_ID NEW_ID`.

[Service.qml](Service.qml) and [ui/](ui/) provide the QML frontend.
[controller/](controller/) manages the locked ledger, runtime shortcuts and cleanup
guardian; preloaded cleanup survives checkout removal. Only owned/tagged windows
on `special:window-stash` are managed. Shell restarts retain records; logout or a
compositor restart does not restore application sessions.
`controller/interaction.py` owns one native input lease through its stdin lifetime;
continuous input is routed inside Hyprland. See [native/README.md](native/README.md)
for the lease protocol and focus/cleanup invariants.

| Local data | Location |
|---|---|
| Settings | `$XDG_CONFIG_HOME/omarchy/shell.json` |
| Session ledger and locks | `$XDG_RUNTIME_DIR/omarchy-window-stash/<compositor signature>/` |
| Positions, preference checkpoint, recovery errors and migration backups | `$XDG_STATE_HOME/omarchy/window-stash/` |
| Optional bridge cache | `$XDG_CACHE_HOME/omarchy/window-stash/preview-bridge/` |

XDG config/state default to `~/.config` and `~/.local/state`. Records contain window
titles, app IDs, monitor identifiers and geometry. Runtime data stays local; no
telemetry or network requests. Icons use local themes; preview frames stay in
memory and are discarded on close. Keep runtime data out of commits.

## Development

```sh
python3 tools/check.py
```

Checks require Python, Node.js, `qs`, Qt6 `qmllint` and Omarchy's validator with `jq`;
standalone Lua enables handle tests. Native suites additionally use GTK4
introspection, `wtype`, `notify-send` and `grim`. See [tests/](tests/) and
[VALIDATION.md](VALIDATION.md), including `tests/live_compatibility.py` for actual
Ghostty/btop and browser pixels. Follow [AGENTS.md](AGENTS.md): announce input
automation five seconds ahead and preserve the desktop. Legacy live suites require
an empty, isolated session.

Copyright © 2026 **artu-ole**. [AGPL-3.0-only](LICENSE).
[Third-party notices](THIRD_PARTY_NOTICES.md).

OpenAI Codex assisted extensively with implementation, tests, documentation and
debugging; the header image was generated with OpenAI image generation. The plugin
makes no AI service calls at runtime.
