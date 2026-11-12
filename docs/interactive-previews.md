# Interactive floating previews

Development plan for the optional interaction layer. Ordinary previews remain
available without the native input bridge. The default entry point is an explicit
Interact control/context action; first-click activation is optional and consumes
the activating click.

## Milestones

1. Prove surface-local pointer routing in a disposable compositor. Add bounded
   ownership-checked leases, input cleanup and a controller helper; validate
   scaled clicks, scrolling, drags, outside clicks and expiry before UI activation.
2. Integrate floating cards, app-group selection, themed active controls, settings,
   live capture, move/resize suspension and display/lifecycle cleanup.
3. Expand native input where verified: keyboard focus and modifiers, native cursors,
   popups/subsurfaces, and safe handling of dialogs. Test window-management shortcuts
   against an unrelated visible application before enabling keyboard interaction.
4. Complete compatibility, failure, small-screen, scaling and lifecycle checks;
   document the supported behavior and remaining limitations.

Each milestone is committed independently after its acceptance checks. Features
that cannot meet their focus or cleanup invariants stay unavailable with a clear
reason rather than being advertised as supported.

Completed foundation: the isolated GTK proof verifies scaled left/right/middle
clicks, wheel scrolling, implicit drags outside the miniature, unchanged source and
workspace, outside-click delivery without duplicate activation, terminal renewals
and lease expiry. Native code builds without warnings against the running headers;
253 Python tests pass, including 17 interaction-worker regressions. Axis focus
changes are framed before scroll events so GTK receives complete scroll sequences.

Completed keyboard proof: explicit content clicks acquire focus; entry typing,
selection, native copy/paste and ordinary Escape work while the source stays hidden.
Held keys are released once on exit, outside clicks restore visible keyboard focus,
and an unqualified window-manager close action targets the hidden source without
closing the visible control application. The configurable Ctrl+Alt+Escape exit
works in mouse and keyboard sessions without leaking its press or release. Local
exit preferences survive checkpoints and reset; no global binding is registered.
261 Python tests pass, including 25 interaction-worker regressions.

## Architecture

QML owns the miniature and its controls. It publishes the exact image rectangle in
global compositor logical coordinates, a verified stash record ID, the monitor and
rectangles occupied by overlay controls. `controller/interaction.py` validates the
request against the current ledger and compositor, owns the native session through
stdin lifetime and renews it periodically. Continuous input stays in Hyprland.

The native bridge owns one active interaction session. It maps the full image into
the source surface's logical coordinates, resolves the appropriate surface and
routes input without warping the desktop cursor. Overlay exclusions affect hit
testing, never the content transform. A session ending from an outside click must
not restart on the next automatic renewal.

## Invariants

- Only the exact mapped, tagged window in the private stash can receive input.
  Address, process and stable identity are verified again inside the compositor.
- Interaction never changes the source geometry, original restoration metadata or
  the active workspace. Moving/resizing the miniature ends or suspends forwarding.
- One session owns keyboard input at a time. Hover never acquires keyboard focus.
  Desktop window actions must not target an unrelated visible application.
- The application receives complete press/release sequences. Interruption releases
  held input and consumes corresponding stale physical releases safely.
- Outside clicks end forwarding and reach their normal destination exactly once.
  The application's Escape remains available; an explicit Exit control always exists.
- Restore, close, lock, display sleep/removal, hidden capture, failed identity,
  helper exit, lease expiry and plugin unload release routing and native resources.
- Native setup errors do not replace user preferences or break ordinary previews.
  Runtime data, application contents and local test artifacts are never committed.
