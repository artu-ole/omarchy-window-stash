# Interactive floating previews

Optional input routing for floating preview cards. Interaction is disabled by
default. Explicit Interact preserves ordinary click-to-restore; optional first-click
activation consumes its activating click. App groups require selecting one window.
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

## Input and controls

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
