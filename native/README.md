# Optional preview bridge

`preview.cpp` is compiled locally for the exact installed Hyprland build; no binary
is shipped. Enhanced live previews use scoped rendering leases. Interactive
floating previews additionally use one input-routing lease. Ordinary previews work
without native support. Both features require x86-64, a C++26 compiler, `pkg-config`
and headers matching the running compositor.

Build without loading:

```sh
python3 tools/build-preview-bridge.py --output /tmp/window-stash-preview.so
```

The builder prints JSON with the binary path, build hash, version and protocol.
`--expected-hash HASH` checks headers against the running compositor. Loading also
checks the full Hyprland and dependency ABI. Rebuild after compositor updates.

`native/version.txt` identifies the native implementation independently of the
manifest. Bump it when native code changes; UI-only releases retain it. The builder
includes it in the cache fingerprint, and helpers require an exact version match.
Replacing loaded native code requires restarting Hyprland.

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

See [../VALIDATION.md](../VALIDATION.md) for final native acceptance and the supported
boundaries around dialogs, fullscreen and popup overflow.
