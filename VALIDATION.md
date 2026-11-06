# Validation — 6 November 2026

Implemented and installed on Omarchy 4.0.6-1 / Hyprland 0.56.2.

| Requirement | Evidence |
|---|---|
| Controller state, settings, FIFO/LIFO ordering, scope, identity reuse, partial-failure retry, geometry and state recovery | 47 passing Python controller tests |
| Grouping, filtering, ordering and bubble placement | Passing Node model checks |
| Valid plugin and QML | Omarchy manifest validator and Qt6 qmllint pass without warnings |
| Exact floating size and position | Live native Wayland GTK test |
| Maximized/fullscreen restoration | Live GTK tests for both states |
| XWayland windows | Live GTK test using the X11 backend |
| Pinned windows | Live pin/minimize/restore check |
| Tiled restoration | Live dwindle insertion and scrolling end-column assertion |
| Scrolling width restoration | Live narrow/wide columns, repeated restores, original/current destinations, per-workspace right/left direction, another scrolling workspace, and underlying width after maximized/fullscreen restoration; exact saved client width within one logical pixel |
| Individual Hyprland group members | Live two-member group, stash one member and restore separately |
| Repeated/concurrent requests | Two concurrent minimize processes create one record |
| Existing window switcher | Search for the parked client, commit selection, verify workspace restoration |
| Icons-only docks | Static and floating docks contain app icons only; shared length checks exclude menu slots and trailing gaps; native right-click Settings access, all four sides, both floating directions, rounded end clearance, scrolling and final-icon exit remain covered |
| Dock and bubbles | Live icon clicks, bubble dragging, position persistence and mode changes |
| Confirmed normal closure | Native isolated-ledger immediate/delayed close, shared grace, native Save/Cancel prompt, unstashed same-app preservation, workspace/global close-all; unit tests cover atomic identity guards, hexadecimal stable IDs, address reuse, partial failure and polling outages |
| Pointer context menus | Native actual click coordinates, four edges, icon/group/front-stack and chooser-row targeting, separated global section, keyboard navigation, click-through outside dismissal, scope-aware close-all, focus return to chooser, prompt accessibility and secondary scaled monitor |
| Middle-click closure | Native static dock, bubbles, collapsed front icon, both expanded axes, pending icon retention/frozen body, duplicate coalescing, grouped stash-only close and Save/Cancel handling |
| Animation speed presets | Native selection of Slow, Relaxed, Normal, Fast and Ultrafast; measured Arc and Matryoshka unfold/fold timing, stable actors/origin, speed change during unfolding, Slow-safe 800 ms leave grace and immediate outside click, Reduced/Off overrides, actual feedback timings across all presentations, and preview/thumbnail fades with unchanged hover delays. Node simulation preserves physical trajectories while scaling Direct/fallback tweens; offscreen Qt covers both speed-change directions during icon retirement and eventual cleanup |
| Hover window previews | Native Off/Still/Live dropdown, exact red/green client pixels while parked, changing content held in Still and updated in Live, unchanged client geometry/focus, opening delay/cancellation, card hover grace and buffer unload, all three presentations and chooser rows, selected-window restore/menu/confirmed close, expanded-fan keepalive and dismissal, four-sided placement, and large previews at every corner of a temporary 320×240 output; pure geometry/identity checks include fractional scales, rounded input, stale metadata and address reuse |
| Side-by-side app previews | Native three-window red/green/blue strip with aligned, non-overlapping thumbnails, per-window restore/menu/middle-close/close button, Still frames and delegate identity preserved across metadata refreshes, and Live capture for every visible tile. A temporary 320×240 output covers horizontal wheel scrolling, all windows retained in the strip, newly visible capture, offscreen stream release and restoring only the chosen window. Model checks cover even resizing, readable minimum widths, bounded overflow and tiny/fractional outputs |
| Preview title close button | Live grouped previews show a bounded, centered × in each visible title strip; clicking it confirms closure of only that window. Hidden titles remove the button, while middle-click still closes and confirms the represented window; preferences, existing stash, focus and display geometry preserved |
| Physical floating dragging | Pure simulation at 30/60/120/144 Hz and native offscreen Qt clock; real pointer flicks, stale-velocity rejection, catching, gentle collisions and neighbor saving, constrained edges, Direct/Reduced/Off, frozen menu/fan origin, held-dock mode switch without ghost input, and restart without saved velocity |
| Trailing floating stack | Native direct lead tracking, cascaded two-axis spring lag through turns and flicks, independent exact catch-up, all five speed presets, click-through trailing artwork, continuous Arc/Matryoshka unfold and interrupted fold, held-drag mode changes, grouping resets and work-area bounds. Pure checks cover bursty pointer input at 30/60/120/144 Hz without velocity injection; offscreen Qt verifies live speed changes, identity resets, rigid idle placement and the sleeping frame clock |
| Fixed floating stack origin | Full native animation samples keep the original icon at its pre-click coordinates throughout unfolding and folding for all seven styles and both orientations, including off-center clicks; geometry tests include fractional anchors and subtle bounded front-icon effects |
| Fixed floating background thickness | Native all-seven-style unfold/fold samples in both axes retain cross-axis position, thickness and corner radius, with gradual bounded length and unchanged jumping icons; interrupted reversal, negative expansion, large corners, interactive airborne-icon restore and Reduced/Off/hidden backgrounds pass. A temporary 320×240 output covers overflow paging, stable edge corners and source removal. Pure geometry checks include fractional anchors, edge reservations, elastic overshoot and exact icon input shapes |
| Floating fan styles | Native dropdown selection for Arc, Glide, Cascade, Spring and Swing; each style in both orientations, distinct motion, persistent actors and complete restacking; non-default choice survives restart; Reduced/Off override all five profiles. Pure geometry checks cover distinct paths, exact endpoints, rotated-corner bounds and capped staggering |
| Matryoshka unfolding | Native straight/hopping choices, shared stack travel and successive deposits, fixed original icon, both axes and free/edge placement, reversible collection, source-removal holding, smooth front replacement, app grouping, Reduced/Off and nonzero-page reversal on a temporary 320×240 output; pure checks cover all work-area edges, fractional anchors, paging, exact endpoints and bounded durations |
| Floating fan dismissal | Native tests cover the 800 ms pointer-leave grace, cancellation on re-entry, immediate click dismissal on apps, empty desktop and transparent rounded corners, and delivery of the same click to the underlying GTK app in both orientations; non-consuming observers are enabled only while a fan is open, and pre-existing mouse/key bindings remain unchanged |
| Cursor-first floating fan | Persistent icon actors unfold from the stack to the pointer, newest first, and fold back to the saved position; native tests cover all expansion directions, curved intermediate motion, identity across cycles, spatial keys, newest restore, one-click outside interaction, focus/workspace dismissal, grouping, Reduced/Off, hidden frames, and both-axis overflow on a small monitor; pure geometry checks verify cursor coverage, work-area bounds and rounded-border clearance |
| Floating dock | Live single-window direct restore, stacked multi-window expansion, per-app chooser, outside/Escape dismissal, icon selection, drag and restart persistence, upward edge placement, workspace/global scope, vertical overflow on a small virtual output, and two-monitor global stacks |
| Animation modes | Native Full/Reduced/Off selector; live intermediate icon arrival/exit frames, final-icon cleanup, stable refreshes and bubble neighbours, preserved floating stack actors, fan reflow and keyboard selection, Reduced fades without scaling, interrupted transitions, immediate Off and saved mode after restart; offscreen native Qt test verifies delegate identity, rapid revival/reordering, timed cleanup, and Off disposal |
| Dock/icon transparency | Native independent 0–100% numeric settings; pixel captures verify alpha compositing, hover restores full opacity including from 0%, separate chrome and artwork, unchanged input, framed/frameless bubbles, floating stack and both dock directions, keyboard selection, Reduced/Off behavior, and restart persistence |
| Whole-icon/button feedback | Live RGB capture confirms app artwork and button glyphs tint; framed/frameless hover and press include intermediate animation frames, preserve transparent corners and clickable geometry, and still restore/open menus; floating stack pressure and one shared mouse/keyboard highlight verified, plus existing themed UI and frame-visibility suites |
| Independent icon/dock frames | Native visibility selectors, larger centered artwork, no frame during hover, unchanged static/floating positions, frameless bubble corner input, retained app badges/chooser, both floating orientations, keyboard restore, saved settings after restart and retained shape/corner choices; model checks verify size, pixel alignment and hover bounds |
| Rounded end clearance | Geometry checks place full square tiles inside the inner border arc; live all-four-side and both-floating-direction checks cover maximum radius, framed/frameless icons, unchanged dock thickness, corner click-through, restore input, and scrolling on a small scaled output |
| Independent dock corners | Native Follow desktop/Custom selector and numeric radius entry; all static sides and both floating directions with 0/7/64-pixel settings, rounded content clipping, corner click-through, icon restore, numeric storage, restart persistence and retained custom value when returning to theme; model checks clamp to panel dimensions |
| Floating edge placement | Native Snap to edges/Free placement selector; live direct dragging, intermediate snap positions on four edges, bar clearance, separate bubble slots, interrupted motion, app grouping, dock expansion in both orientations, saved resting positions and settings after restart, first click at the restored edge, and drags across background refreshes; model checks cover portrait/small screens and crowded edge packing |
| Static dock sides | Live native Bottom/Top/Left/Right selector, centered icons, restore/menu clicks on all four edges, saved side after restart, top bar appearance/removal, and horizontal/vertical overflow scrolling across background reserve refreshes on a 1.25-scale virtual output; model checks cover asymmetric reserved edges and portrait screens |
| Floating dock direction | Live native Vertical/Horizontal selector, cursor alignment and complete borders, spatial Left/Right keyboard selection, app grouping, left/right edge placement, collapse before changing axes at the same anchor, restart persistence, and horizontal scrolling on a 320×240 virtual output |
| Dock motion and alignment | Live curved expansion/collapse frames, unchanged delegate count across cycles and refreshes, centered artwork, bounded count badges, and whole-icon overflow slots for fully visible borders; pixel-grid centering checks at 1×, 1.25×, 1.5× and 2× |
| Compact dock spacing | Live horizontal/vertical floating docks and bottom-dock restore with reduced panel padding and icon gaps; enlarged artwork has shape-aware corner clearance and pixel-grid centering checks at 1×, 1.25×, 1.5× and 2× |
| Input regions | A click outside bubbles reaches a GTK window underneath |
| Icon shapes | Live native dropdown, all five bubble shapes, corner input, squircle dragging, dock restore and saved choice after shell restart; model checks cover exact squircle input pixels and legacy setting defaults |
| Desktop test notice | All desktop suites notify before a five-second countdown; unit checks verify ordering, refusal without a notification, and completion on failure |
| Configurable shortcuts and FIFO restoration | Native Settings Apply/Return normalization, Clear/Default, duplicate/foreign conflict rejection with unchanged settings and active handles, retained failed drafts and error recovery; actual configured minimize, newest and oldest key presses restore only eligible owned fixtures in LIFO/FIFO order with exact floating geometry; rebinding disables the prior chord and empty oldest disables FIFO. A non-default shortcut survives both shell restart and compositor configuration reload |
| Shortcut migration and ownership | 12 isolated backend tests cover canonical chords, exact owned-handle identities, conflicts, serialization, atomic persistence/rollback, and Lua bootstrap/handle reuse. 17 installer tests cover consent, recognized legacy calls/paired overrides, byte-preserved outside configuration, duplicate lookalikes, customized blocks, loader updates and uninstall; live migration retains the existing Super+A override and A/Z defaults |
| App grouping and chooser | Group two windows, open chooser by mouse, search by keyboard and restore with Enter |
| Restore destination | Live original/current destination checks and original-workspace context action |
| Global/workspace scope | Live one-, two-, and three-output checks in dock and bubble modes |
| Mixed resolution/scale | Restore a floating window onto a 1280×720 output at 1.25 scale; assert work-area bounds |
| Disconnect recovery | Remove the origin output and restore its saved local workspace slot onto the laptop |
| Workspace renumbering | Observe `changeworkspaceid>>9,90`, verify origin update, then restore ID 90 to 9 and remove the test workspace |
| Shell restart | Park a window, restart the shell, recover the same record and floating state |
| Closed minimized windows | Close the parked test window and verify ledger cleanup |
| Dock overflow | Fourteen entries on a 640×480 virtual output; real pointer drag scrolls without restoring a window |
| Omarchy theme and shared controls | Native buttons, dropdowns, search, and tooltips; live Tokyo Night visual check, all four dropdowns and external-setting synchronization, grouped bubble search/Enter restore, context restore and dock click |
| Organized settings | Six native Omarchy header groups: General, Placement, Appearance, Motion, Previews and Keyboard shortcuts. Live checks cover all 19 dropdowns, section order, preserved values, conditional controls across static/bubble/floating modes, numeric placement, native dropdown editing and access to the final shortcut field; original preferences, stash, focus and monitor geometry restored |
| Safe removal and reinstall | Removal restores a parked window and removes bindings/integration; reinstall reloads successfully |

The live suites use disposable GTK windows and headless virtual outputs. The
virtual outputs supplement the laptop display; no claim of testing three
physical displays is made. Cleanup restores the original application focus,
settings and display profile, and removes the test windows and workspaces.

Commands: `python3 tools/check.py`, `python3 tests/live.py`,
`python3 tests/layouts_monitors.py`, `python3 tests/ui_lifecycle.py`, and
`python3 tests/overflow.py`, `python3 tests/themed_ui.py`, and
`python3 tests/scrolling_width.py`, `python3 tests/icon_shapes.py`, and
`python3 tests/floating_dock.py`, and `python3 tests/floating_direction.py`, `python3 tests/dock_sides.py`, `python3 tests/floating_placement.py`, `python3 tests/dock_corners.py`, `python3 tests/frame_visibility.py`, `python3 tests/hover_feedback.py`, `python3 tests/animation_modes.py`, `python3 tests/transparency.py`, `python3 tests/floating_fan.py`, `python3 tests/close_actions.py`, `python3 tests/context_actions.py`, `python3 tests/middle_close.py`, `python3 tests/drag_physics.py`, `python3 tests/matryoshka.py --small-output`, and `python3 tests/hover_previews.py --small-output`, and `python3 tests/animation_speed.py`, and `python3 tests/stack_follow.py`, and `python3 tests/floating_panel.py --small-output`, and `python3 tests/shortcuts.py`. Pinned restoration and workspace-ID event handling
were additionally checked directly against the live compositor.

Validation did not upgrade system packages or modify packaged Omarchy files.
Stash metadata survives
shell restarts within a compositor session; this is not application session
restoration after logout.

## Publishing review — 5 November 2026

Reviewed against the [publishing guide](https://plugins.omarchy.org/publish.html),
[submission requirements](https://github.com/omacom/omarchy-plugin-marketplace/blob/main/SUBMISSION.md),
and [Omarchy shell contract](https://github.com/omacom/omarchy/blob/quattro/docs/omarchy-shell.md).

| Local requirement | Result |
|---|---|
| One root manifest and matching entry point | Schema 1, service kind, `Service.qml`, version `1.20.2`; installed Omarchy validator passes |
| Namespaced third-party ID | `community.window-stash` is outside reserved `omarchy.*`; no exact match in current registry data, including retired IDs; recheck before submitting |
| Author and license | `artu-ole` in the manifest and project copyright; SPDX `AGPL-3.0-only` and the full root AGPL license; integration excerpts attributed in `THIRD_PARTY_NOTICES.md` |
| Documentation | Root README covers dependencies, manual setup, updates, settings, recovery, removal, user-file changes, and local metadata |
| Consent before configuration edits | Helper displays its plan and prompts before any writes; non-interactive runs require explicit `--yes`; refusal and consent tests pass |
| File layout | No symlinks, bundled executables, credentials, or private runtime data in the source folder |
| Shared UI | Uses installed Omarchy theme tokens and UI components; icons are looked up locally rather than bundled |
| Checks after publishing preparation | 80 Python tests, model checks, publishing metadata checks, manifest validation, and Qt6 QML lint pass |

The current installation path requires manual setup. Generic `omarchy plugin
add` does not install the controller wrapper or shortcuts, and generic removal
does not undo them. The README explains the helper and cleanup order. Disclose
this to marketplace maintainers and request the `manual-setup` label when
submitting; the marketplace does not execute installer hooks.

Marketplace submission remains separate: recheck ID availability, select the
exact release commit, and submit it for compatibility, security-baseline, and
maintainer review. Suggested category: `Desktop`; tags:
`hyprland`, `quickshell`, `workspaces`. A root preview image is optional and has
not been added. No marketplace submission or listing has been requested by this
review, and marketplace approval and security-baseline verification remain
pending.
