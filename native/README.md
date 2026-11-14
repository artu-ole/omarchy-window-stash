# Optional preview bridge

`preview.cpp` is compiled locally for the exact installed Hyprland build; no binary
is shipped. Enhanced live previews use scoped rendering leases. Interactive
floating previews additionally use one input-routing lease. Ordinary previews work
without native support. Both features require x86-64, a C++26 compiler, `pkg-config`
and headers matching the running compositor.

Build without loading:

```sh
python3 tools/build-preview-bridge.py --cache-dir /tmp/window-stash-preview-cache
```

The builder prints JSON with the binary path, build hash, version, fingerprint and protocol.
`--expected-hash HASH` checks headers against the running compositor. Loading also
checks the full Hyprland and dependency ABI. Rebuild after compositor updates.

`native/version.txt` identifies the native implementation independently of the
manifest. Bump it when native code changes; UI-only releases retain it. The builder
includes it in the cache fingerprint, and helpers require an exact version match.
Explicit compatibility pairs retain ordinary render/input support during a deferred
upgrade. New capabilities are checked separately: contained fullscreen requires
`capabilities.constrainedFullscreen`, and never falls back to desktop fullscreen.
Upgrade detection and the early interactive bridge's unsafe-unload refusal remain active.
Automatic artifacts use immutable `<Hyprland hash>/<version>-<fingerprint>/`
directories. The explicit developer `--output FILE` option remains replaceable.

## Updating a loaded bridge

`controller/bridge.py status` probes without building or changing the compositor.
The shell detects a mismatch at startup, in Settings and every 30 seconds. The
notification and Settings offer **Reload preview support / Later**; detection never
interrupts input. `controller/bridge.py reload` performs the explicit replacement:

1. Build and verify a new immutable artifact before changing the loaded module.
2. Pause capture helpers and finish acknowledged interaction. A session-scoped
   file lock excludes new acquisitions, including restoration handoffs.
3. Call `prepare_reload()`, which stops rendering/input, exits contained fullscreen,
   refuses new leases and cancels pending restoration handoffs. Wait for
   `reloadReady`, including held physical key/button release filters, client
   configure acknowledgements and bounded fullscreen activation cleanup.
   Timeout/cancellation calls `cancel_reload()` and retains the old module.
4. Unload only the verified Window Stash module in its owned cache. Load the new
   pathname and verify its protocol, version, compositor hash and fingerprint.
5. Resume rendering. Input requires a new explicit activation. Windows, geometry,
   preferences, positions and shortcuts remain unchanged.

`status()` exposes `reloadProtocol`, `reloadPending`, `reloadReady`, `pendingKeys`,
`pendingButtons`, `modulePath` and `fingerprint`. Reload has no global compositor
restart action. Failed loads can roll back only a digest-verified old artifact;
an overwritten legacy cache entry is never guessed at. Cancellation before unload
preserves the old bridge; after unload replacement completes even if the shell
closes its pipe. `--watch-stdin` binds pre-unload cancellation to that pipe.

`capabilities.superClickActivation` enables Super+left-click entry from a preview;
`capabilities.superCornerResize` adds free-aspect Super+corner dragging. The existing
mouse listener consumes a press only on the exact focused preview layer root,
then reports `press`, `move` and a terminal `release`, `drag-release` or `cancel`
over compositor IPC. QML pins and validates the selected source and corner. Motion
can leave the original input region while its layer remains mapped and visible;
focus loss still invalidates click activation, and movement beyond six logical
pixels always produces a drag release. Lock, reload, workspace/monitor changes,
other buttons or source-layer destruction cancel the gesture. Desktop mouse
bindings remain unchanged and no activating click reaches an app.
`pendingSuperClick` tracks the held physical pair; it contributes to
`pendingButtons` and blocks `reloadReady` until released.

The original render-only bridge drains through its lease timeout. The first
experimental interactive bridge cannot expose pending physical-release filters;
it requires one logout/login before adopting this upgrade protocol. Unknown
bridges, ambiguous ownership, a locked session or mismatched compositor headers
are refused. Ordinary stash actions and Standard previews remain available.

Builds disable GNU-unique module pinning and hide inline implementation symbols
while preserving compositor singleton visibility. New paths and exact native
identity checks prevent a successful `dlopen` from being mistaken for new code.

## Rendering

The Lua namespace is `hl.plugin.window_stash_preview`. A rendering owner supplies
its complete set of visible live sources:

```lua
local api = hl.plugin.window_stash_preview
local owner = "0123456789abcdef0123456789abcdef"
local source = {
  id = "abcdef0123456789abcdef0123456789ab",
  tag = "window-stash-abcdef0123456789abcdef0123456789ab",
  address = "0x12345678", pid = 1234,
  stable_id = "18000001", -- hexadecimal, as in clients JSON
}
local result, err = api.update({ owner = owner, windows = { source } })
assert(result, err) -- result.accepted / result.requested
api.release(owner)
local details = api.status()
```

Renew every 500 ms; leases expire after 2.5 seconds. Owners are independent, and
release is idempotent. PID, stable ID, weak window handle, exact ownership tag and
`special:window-stash` membership are checked before acquisition and during use.
Closed, restored, retagged or replaced windows immediately lose eligibility.

Rendering leases hook suspension only for eligible sources and provide frame
feedback at up to 15 FPS. Only the active interactive source receives its 30/60 FPS
budget; other live sources retain theirs. Releasing restores natural suspension.
The render-only API leaves focus, source geometry, workspace visibility and window
rules unchanged.

## Input routing

```lua
local session, err = api.interaction_update({
  owner = owner, window = source, monitor = "DP-1",
  rect = { x = 1200, y = 180, width = 400, height = 280 },
  excludeRects = {}, -- at most 16 overlay-control rectangles
  keyboard = true, -- permit keyboard focus on a content click
  fullscreen = "preview", -- default; "desktop" retains restoration handoff
  fps = 60, -- 30 or 60
  exitShortcut = { modmask = 12, key = "Escape" }, -- nil disables
})
assert(session, err)
local current = api.interaction_status(owner)
api.interaction_release(owner)
```

One owner receives input at a time. Requests use global logical desktop coordinates,
including negative monitor positions; texture pixels and output scaling are not
input coordinates. The full image rectangle defines the transform into source-local
coordinates. Exclusions affect hit testing without altering that transform.
Surface hit testing handles native subsurfaces and application popups.

Continuous events stay inside the compositor. Cancellable pointer hooks forward
movement, buttons and axes through the seat; implicit grabs preserve complete drag
sequences beyond the image boundary. The physical cursor stays at the miniature.
Application cursor shapes follow pointer focus; capture does not paint another
cursor.

Keyboard permission does not acquire focus until a content click. Focus/keyboard
hooks keep application input and ordinary window-manager commands targeting the
same exact source while its workspace remains hidden. Plain Escape reaches the
app; the optional exit chord is matched only during interaction. No global binding
is registered. The controller rejects conflicting desktop chords before activation
and whenever that preference changes. `status().capabilities` reports pointer,
keyboard, popup and exit-shortcut support. Unavailable keyboard or exit-shortcut
requests fail with the native setup reason.

Interaction rejects `no_screen_share` sources; keyboard routing also respects
`no_focus`. Enabling either applicable rule during a session ends its input lease.

Non-forced activation of the exact source that already owns keyboard focus is
acknowledged in place, including browser tab creation. This grants no new focus.
Explicit desktop focus and forced activation still restore the source; once seat
focus leaves the miniature, ordinary external activation can restore it as well.
Pointer-only activation retains its existing bounded input acknowledgements.

## Source geometry

`source_geometry(identity)` is a read-only query for exact owned, floating private
windows. It compares committed logical client geometry and configured size with
the current resize goal, with `ready` false while configure, drawing, animation or
fullscreen cleanup is pending. It respects `no_screen_share` and preserves client
fullscreen. Wayland checks committed configure and surface state; XWayland sizes
are normalized by its surface scale before comparison.

Edge resizing uses the ordinary guarded resize dispatcher. A short, independently
owned rendering lease lets the hidden client finish drawing even with Standard or
Still previews; readiness/error releases it, and its timeout bounds cancellation.
Original restoration geometry is never overwritten. Resized records require this
native readiness check in the same Lua transaction as input acquisition, and the
UI obtains a fresh capture before enabling Interact. Legacy natural previews keep
their existing input path.

## Contained fullscreen

The `preview` policy intercepts fullscreen requests for the exact owned source
before compositor layout or monitor geometry changes. It sends real client
fullscreen state while the internal mode remains None, including when the user's
fullscreen binding invokes the ordinary window dispatcher. No shortcut is
overwritten. Super+F targets the miniature only after it owns keyboard focus.

The bounded identity registry retains fullscreen after input ends, allowing a
passive picture-in-picture card without retaining keyboard or pointer ownership.
Capture still follows its configured update policy. Application Escape/toggle
exits fullscreen; `desktop` restores the ordinary fullscreen handoff.
Desktop requests are applied after the exact source is restored and verified
public, preserving browser video fullscreen through the handoff.

`clear_fullscreen({id,address,pid,stable_id,tag})` removes only an exact owned
override. The controller calls it and rechecks identity before snapshotting current
fullscreen during restoration. Saved pre-stash fullscreen and scrolling geometry
are preserved. Moving a source public, identity/rule loss, bridge preparation and
unload clear temporary client state. Status exposes `constrainedFullscreenWindows`,
`fullscreenWindows`, `interaction.fullscreen` and `interaction.previewFullscreen`.

Some Wayland browsers wait for a content resize before completing fullscreen exit.
An acknowledged, height-only client configure sequence unblocks that path, then
returns to the original client dimensions. Compositor window geometry, preview
geometry and saved restoration width remain fixed. The controller waits for exact
source cleanup through `fullscreen_cleanup_pending(identity)` before restoring;
an unresponsive client remains stashed rather than interrupting the sequence.
Pending cleanup cannot promote the source to desktop fullscreen. Tag loss cancels
the client-size override before relinquishing the exact verified window.

Browsers can request activation while entering or leaving fullscreen. A bounded
transition guard consumes that request for the exact interacting source; explicit
desktop focus still restores it. Passive activation emits `window-stash-restore`
with only the verified record ID. The shell validates that intent and uses normal
controller restoration, keeping the private workspace hidden throughout.

The stdin-owned helper `controller/interaction.py` validates every requested record
against the locked ledger and fresh compositor state, including current workspace
scope and monitor bounds. Only identity, geometry, policies and status counters
cross the helper channel; application pixels and keystrokes do not.

Status includes `active`, `id`, `owner`, `reason`, `keyboard`, `keyboardFocused`,
`heldButtons`, `heldKeys`, viewport geometry and input counters. `hyprctl repl`
pretty-prints Lua tables; the helper explicitly marshals these fields to JSON.

## Ending a session

Outside clicks terminate routing and continue to their ordinary destination once.
Management exclusions remain usable while a session is active. Stop/Restore/Manage
controls retain their active state until release is acknowledged; a missing helper
acknowledgement keeps management frozen until the native lease expires.

Active resize handles use the same exclusions. A press on the verified preview
layer starts a Qt management grab: native application motion, buttons and wheel
routing stay suspended until every physical management button is released,
including across input-owner cleanup. Source application implicit grabs retain
precedence. An owned Super gesture likewise keeps its motion stream when it
crosses the active image before the helper acknowledges stopping. New application
input cannot be acquired while management buttons remain held. Reload readiness
includes `pendingManagementButtons`; `interactiveResize` advertises this handoff
support independently of ordinary Super corner resizing.

Input-owner cleanup preserves pointer focus while a management or scoped Super
gesture remains held. Keyboard cleanup still runs during the pause; ordinary
stops retain pointer refocusing.

Restore, close, identity loss, workspace/display changes, DPMS, screen lock,
exclusive overlays, pointer constraints, stdin closure, expiry and unload release
input. Held buttons/keys receive matching cleanup; stale physical releases are
consumed safely. Ended owner tokens cannot be renewed into a new interaction; an
explicit new activation uses a fresh owner. Ordinary rendering owners remain
independent.

## Restoration handoff

An inactive status may set `restoreRequested=true` only for `modal-dialog`, `source-fullscreen`,
`popup-outside`, `source-activation` or `window-management`. These flows restore the
full application when a miniature cannot represent its requested UI correctly.

The worker revalidates the original source identity, ownership, monitor and scope
under the ledger lock, then calls normal `Stash.restore` with the user's destination.
Only after success does it call `api.interaction_handoff(owner)`. The native owner
record retains weak exact parent/transient identities and the initial mapped-window
snapshot. It verifies the parent is now public and visible before moving/focusing
new, unowned descendants. A new transient provisionally public on the invoking
workspace may follow its parent's destination; pre-existing public children are
excluded. App names and PIDs alone never adopt windows. Ordinary close, expiry,
outside-click and scope-change reasons do not request restoration. Failed parent
restoration retains normal retryable ledger metadata; a failed later handoff can
leave a dialog on its current workspace without reacquiring input. Pending private
focus/warp suppression expires after five seconds independently of owner tombstones.
Every path releases its input lease.

Desktop fullscreen acknowledges client state immediately while keeping layout
fullscreen disabled until the verified public handoff. `desktopFullscreenPending`
identifies this temporary acknowledgment. Only its exact owner may preserve it
through `clear_fullscreen(identity, owner)`; ordinary restore, expiry, lock and
bridge preparation cancel it through the acknowledged cleanup path. Temporary
client state never replaces saved restoration metadata.

See [../VALIDATION.md](../VALIDATION.md) for final native acceptance and the supported
boundaries around dialogs, fullscreen and popup overflow.
