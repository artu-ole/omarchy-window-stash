# Interactive floating previews

Optional input routing for floating preview cards. Interaction is disabled by
default. Explicit Interact preserves ordinary click-to-restore; optional first-click
activation consumes its activating click. Super+left click on preview content also
enters interaction without restoring the window. App groups require selecting one window.
See [README.md](../README.md) for settings and [VALIDATION.md](../VALIDATION.md) for
acceptance evidence; this document describes the implementation contract.

## Components

QML publishes one selected record ID, an activation serial, the monitor, the full
image rectangle and up to 16 control-exclusion rectangles. Coordinates are global
compositor logical units, including negative output positions. The controller
requires the image and exclusions to fit the target output; a partially clipped
group member must scroll into view before activation.

`controller/interaction.py` validates the bounded JSON-lines request against the
locked ledger, fresh clients, monitor state and workspace scope. It pins the exact
source identity and creates a fresh owner for each activation. The helper's stdin
lifetime owns the lease; it renews every 500 ms and releases on EOF, cancellation
or failure. Configuration, pixels and application events do not pass through a
per-event helper process.

The native API owns one input session and expires it after 2.5 seconds without a
renewal. Address, PID, stable ID, ownership tag, mapped state and private workspace
membership are checked inside the compositor. Input and rendering leases are
separate: interaction automatically acquires live rendering at the chosen 30/60 FPS
without changing Standard/Enhanced or Still/Hover/Live preferences. Other enhanced
live sources retain their 15 FPS budget.

## Folding previews

Floating previews have a second minimized stage: a floating application icon.
The minimize shortcut queries fresh compositor pointer coordinates and folds the
frontmost hovered preview. It consumes hits on an already folded icon or busy
preview; a hover miss retains focused-window minimization. App covers fold their
visible members together, while an expanded thumbnail selects its exact window.

`previewFolded` is a strict per-record boolean in the runtime ledger. Folding
waits for acknowledged input release, then validates the exact private source
before changing that flag. It preserves phase, order, original restoration data,
working source geometry and contained fullscreen. Folded views stop capture,
render requests and geometry polling; authoritative helpers reject stale requests
under the same ledger lock as their final native acquisition.

The controller exposes `preview-fold ID [ID ...]` and
`preview-unfold ID [ID ...]`. Managed minimize/newest/FIFO bindings use
`--shortcut` to forward intent through shell IPC before taking any ledger lock;
minimize includes freshly queried cursor coordinates. IPC failure never falls
back to minimizing an unrelated focused window.

Icon activation clears the flag and returns the preview at its remembered size,
position and aspect ratio. Newest/FIFO shortcut restoration uses `--stage`, so
the first action unfolds and the next fully restores the same ordered record.
Plain CLI restoration, explicit context restoration, native handoff, removal and
recovery remain full restoration. Other presentation modes ignore folded state.

Folded icon positions use separate `folded-preview:` keys and inherit existing
icon appearance, size, placement and physics. Their initial placement waits for
the layer's configured dimensions, preserving saved positions across restarts.
Fold/unfold motion follows the global animation settings, and input waits until
an unfolding miniature has settled. No additional preferences are introduced.

## Resize responsiveness

`floatingPreviewResizeRate` controls source reflow during side dragging:
`realtime` (Responsive, default), `balanced`, or `release` (On release).
Responsive and Balanced use a non-restarting throttle with target intervals of
16 and 60 ms. Each source retains only its latest draft and queued resize;
continuous pointer events cannot postpone dispatch indefinitely. Actual updates
depend on client/compositor response rather than a promised frame rate.

On release defers the source change until that source's final gesture. Finalizing
one source never flushes another source's held draft. Release flushes immediately
and uses asynchronous committed-geometry polling and fresh capture before input
is re-enabled; it does not block the action worker waiting for the client.
The direct CLI `--settle` remains available for callers needing a bounded wait.

Responsive/Balanced side drags temporarily request live capture even with Snapshot
selected, then restore the saved update policy. Corners retain ordinary proportional
scaling. Only the initial transition to `previewResized` writes the ledger; changing
working dimensions does not repeatedly rewrite unchanged restoration metadata.

## Entering interaction

Enabling interaction prepares native shortcut support when previews are visible,
including Standard/Still previews. `controller/interaction.py --prepare` loads
support if absent, checks `capabilities.superClickActivation` and takes no input or
rendering lease. An older loaded module is preserved and reports the update requirement.

The native mouse listener intercepts pure Super+left only on the actual focused
root of `omarchy-window-stash-interactive-previews`, before compositor mouse bindings.
It consumes the whole pair and emits `window-stash-super-click` with
`serial,press|release|cancel,x,y` in global logical coordinates. Moving more than
six logical pixels, losing focus or changing desktop state cancels activation.
The release is consumed even if Super is released first; reload waits for it.
No application receives the activating press or an unmatched release.

QML pins the frontmost content's identity and geometry on press and revalidates
both on release. Controls, unavailable frames and partially clipped tiles cannot
activate or fall through to restore. A group cover expands for exact selection;
another eligible preview uses the existing acknowledged replacement path.
Dialogs and menus use the ordinary layer namespace. Global mouse bindings are
preserved; ordinary Super+drag outside previews still moves windows.

The native bridge maps the full image rectangle to source-local coordinates,
resolves subsurfaces/popups, and routes pointer movement, buttons and axes through
the seat. Exclusions change hit testing without changing the image transform.
Implicit grabs preserve drags beyond the card; the physical cursor stays at the
miniature and follows application cursor requests.

Mouse-only is the default. Optional keyboard mode acquires focus on a content click,
never on hover or activation. Typing, selection, native clipboard operations and
application shortcuts use the normal keyboard pipeline. Focused-window commands
target the same hidden source. Plain Escape reaches the application; the configurable
Ctrl+Alt+Escape default ends only an active session and registers no global binding.
The controller rejects occupied chords, including bindings in other submaps.

An active card is opaque, retains a themed outline and exposes Stop/Restore/Manage.
Controls sit outside the image when space permits; inline controls are excluded
from source input. Movement, resizing and physics wait for native release
acknowledgement. A replacement activation also waits for release. If the helper
cannot acknowledge cleanup, management stays blocked until the lease expires.

Outside clicks end routing and continue to their normal destination once; pointer
leave alone does not stop interaction. Interruption releases held buttons/keys and
consumes stale corresponding physical releases. Native ended-owner tokens prevent
automatic renewals from reactivating a session; explicit activation uses a new owner.

## Restoration fallback

The implementation requests restoration for modal dialogs, fullscreen, overflowing
popups, explicit application activation and application move/resize requests.
Native acceptance covers dialogs at both destinations, fullscreen, oversized
popups and independent new windows without exposing unrelated stashes.

Only an ended status with `restoreRequested=true` and an allowlisted reason may
start fallback. The helper revalidates its original owner/source and fresh scope
under the ledger lock, then uses normal `Stash.restore` and the configured
destination. A fullscreen request is temporarily cleared for geometry restoration
and reapplied afterward; partial failures retain the request and original snapshot
for retry.

After successful restoration, `interaction_handoff(owner)` validates the now-visible
public parent and exact new transient descendants. Native weak identities and the
initial mapped-window snapshot exclude pre-existing or independently owned windows,
including unrelated same-app windows. A new descendant provisionally mapped on the
invoking workspace may follow its parent to the chosen destination. A new unparented
window is handled separately by native code and never becomes a stash record.

Failed restoration retains the normal retryable ledger. A later handoff failure
can leave a dialog on its current workspace after its parent has restored; it does
not reacquire input or adopt another window. Pending private-focus/warp suppression
expires after five seconds independently of the bounded ended-owner history.

## Boundaries

Routing ends on restore/close, source identity or ownership loss, workspace/display
changes, DPMS, screen lock, exclusive overlays, pointer constraints, hidden capture,
helper exit, expiry or unload. `no_screen_share` sources are rejected; keyboard
interaction also respects `no_focus`. Enabling either rule mid-session ends the
affected routing. Ordinary previews remain available when native setup fails.

Interaction preserves source geometry and original restoration metadata. A fallback
deliberately restores the full window when its requested UI needs that environment.
Pointer-locked applications, cross-window drag-and-drop and input-method popup
positioning require the restored application; broader compatibility is not inferred
from the GTK, browser or terminal fixtures.

Tests use disposable compositor sessions and unrelated visible control windows.
Desktop suites enforce the shared five-second notification/countdown and cleanup
contract. Runtime identities, application contents and local artifacts stay outside
the source tree.
