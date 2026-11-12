# Validation

## v1.29.0 — interactive floating previews — 12 November 2026

Adds optional native pointer and keyboard input to one selected floating preview.
Interaction is off by default; explicit Interact preserves click-to-restore.
Keyboard focus requires a content click, and the configurable exit chord defaults
to Ctrl+Alt+Escape. Plain Escape remains available to the application. Active
capture uses its own 30/60 FPS setting without changing ordinary preview policies.

The complete non-graphical check passes **274 Python tests**, **14 Node suites**,
**ten offscreen Qt suites**, manifest validation, warning-free QML lint and syntax
checks for **96 Python files**. Native bridge **1.29.1** builds without warnings
against the running compositor's matching headers. All **42 settings** are documented.

Native acceptance in the disposable Hyprland/Omarchy desktop passes:

- Scaled left/right/middle clicks, actual wheel input, implicit content drags
  beyond the miniature, consumed first-click activation and explicit controls.
  Outside clicks reach their destination once; ended owners cannot rearm.
- Actual entry typing, UTF-8, selection, native copy/paste, application Escape,
  default/custom exit chords and matching held-key releases. Unqualified WM close
  targets the hidden source and leaves the visible control application intact.
- Exact grouped-window selection and replacement, chooser keyboard ownership,
  bounded controls on 320×240, clipped-target cancellation and context activation
  that scrolls the selected row fully into view before acquiring input.
- Real hidden GTK popup pixels and item clicks, all four focus-follow modes,
  application Escape and stopping an open grab. Mouse-only popups retain visible
  keyboard focus and cannot silently enable application typing.
- Modal dialogs at current/original destinations, fullscreen, oversized popups,
  switcher-style focus, actual client activation and application move requests.
  Exact new descendants follow their parent; pre-existing public children and
  unrelated stashes remain untouched. Independent new windows are not adopted.
  The compositor event stream records no private-workspace exposure in these flows.
- Three outputs including scale 1.5, rotation and negative coordinates; viewport
  renewal, display sleep/removal, actual session lock/unlock, source restoration,
  invalid requests, helper cancellation and lease expiry.
- Dormant and newly requested pointer lock/confinement are rejected before
  activation or cursor warping; unrelated constraints retain normal operation.
- Actual Ghostty, Chromium and Brave receive synthetic text and application
  input, show changed pixels in the miniature, and restore with their saved size.
- Existing persistent and hover previews, side-by-side groups, small-output
  overflow, scrolling-width restoration and Omarchy 4.5 dock/workspace coexistence.
  Ghostty/btop produces one distinct Standard frame versus nine Enhanced frames;
  leaving preview mode releases rendering owners and returns to idle.

All 42 settings and the local exit field remain reachable on scaled 640×480 and
400×300 work areas with reserved edges. Native tests cover local exit Apply,
Default and Disable without changing the three global actions. Settings support
wheel, drag, scrollbar and Tab navigation, bounded dropdowns and reset cancellation.
Confirmed Reset all restores all 42 canonical defaults while preserving windows,
positions and geometry. Native shortcut edits, FIFO/LIFO actions and the complete
CLI add/update/disable/source-deleted-remove/reinstall lifecycle also pass.

The sweep also caught an existing parking issue: an unnecessary resize woke the
newest hidden window. Correctly sized sources now skip that dispatcher; required
cross-monitor size correction remains. The rendering-lease test observes exact
Wayland suspension states, independent owner unions, scoped release and expiry.
Its owned active-unload/reload branch passes and restores natural suspension.

Pointer-locked applications, cross-window drag-and-drop and input-method popup
positioning require restoring the full application. Compatibility beyond the
verified clients is not inferred. Tests use a private home, runtime, D-Bus,
compositor, browser profiles and synthetic input; the real desktop is unchanged.

## v1.28.1 — stable stashed dimensions — 12 November 2026

Owned windows park floating at their saved source dimensions inside the private
stash. The ledger retains their original floating/tiled state and scrolling width
for restoration. Successive stashes no longer let the private tiling layout resize
earlier sources or change their miniature proportions when live updates begin.

The complete non-graphical suite passes **236 Python tests**, **13 Node suites**,
**seven offscreen Qt suites**, manifest validation, warning-free QML lint and syntax
checks for **78 Python files**. Controller regressions execute the guarded Lua
transactions, including old-record normalization, rejected parking and recovery,
external moves, identity replacement and saved scrolling-column fractions.

Native checks in the disposable Hyprland/Omarchy profile pass:

- Two full-width scrolling windows stashed sequentially: Standard and Enhanced
  previews retain source/card proportions and placement through repeated
  three-second hovers, re-entry, always-live updates, restoration and re-stashing.
- Dwindle sources and app groups retain independent captured proportions; resizing
  miniatures preserves source dimensions and tiled restoration metadata.
- Narrow/wide scrolling columns in both directions retain their widths and append
  last. Restoring a full-width singleton retains its logical column width when a
  second window returns; fullscreen/maximized restoration also passes.
- Existing floating-preview controls, capture policies, grouping, exact restore,
  context menus and closure; side-by-side hover previews and capture cleanup.
- Native floating-workspace/dock coexistence, legacy migration, and the complete
  CLI add/update/disable/source-deleted-remove/reinstall lifecycle with preserved
  preferences, shortcuts and floating geometry.

Enhanced support loads before temporary layout rules because native plugin loading
refreshes compositor configuration. The tests measure scrolling widths in the same
column topology, accounting for Hyprland's singleton gap change without weakening
the pixel, captured-aspect or logical-column-width checks.

## v1.28.0 — floating previews — 11 November 2026

Adds persistent, borderless window miniatures with direct aspect-preserving resize,
independent size presets, saved placement, locks, physics and application groups.
Snapshot, live-on-hover and always-live policies are independent of hover previews.
Verified captured proportions drive presentation without changing restoration
geometry. Cover and expanded Still snapshots retain their own pixels and shape.
Workspace filtering uses compositor snapshots to avoid stale native monitor state
after hotplugging; capture ownership survives display sleep and resumes cleanly.

The complete non-graphical suite passes **217 Python tests**, **13 Node suites**,
**seven offscreen Qt suites**, manifest validation, warning-free QML lint and syntax
checks for **77 Python files**. The README covers all **36 settings**.

Native acceptance in a disposable Hyprland/Omarchy desktop passes:

- All nine presets, direct resizing, original-window geometry, independent saved
  free size, placement locking, workspace filtering and exact restore/close actions.
- Tiled source frame fitting, independent grouped snapshots, and narrow/wide scrolling
  restoration with the original column width and final-column placement.
- Three virtual outputs, separate positions and widths, direct dragging, flick
  momentum, monitor removal and preservation of every stashed window.
- Actual Ghostty/btop rendering: one distinct Standard frame versus nine Enhanced
  frames, scoped leases, hover resume and complete rendering cleanup.
- Oversized previews and grouped overflow on a 320×240 output, targeted display
  sleep/wake, and all 36 settings on scaled displays with reserved screen edges.
- Existing hover previews, UI routing, default shortcuts and the complete CLI
  install/update/disable/source-deleted-removal/reinstall lifecycle.

The native profile uses a private home, runtime, D-Bus, compositor and synthetic
input. Test clients, settings, positions, focus and outputs are cleaned up; the
real desktop is not used for input automation.

## v1.27.1 — retire manual installation — 9 November 2026

The retired manual installer and its unused configuration-writing helpers are
removed. Installation/removal use the Omarchy CLI; conservative automatic legacy
migration and its private backups remain available. Obsolete installer tests are
retired, with seven focused legacy-recognition regressions retained alongside
migration, runtime-shortcut and lifecycle coverage.

The complete non-graphical suite passes **210 Python tests**, **11 Node suites**,
**four offscreen Qt suites**, manifest validation, warning-free QML lint and syntax
checks for **68 Python files**. Native checks in a disposable desktop pass the
complete CLI add/update/disable/source-deleted-remove/reinstall lifecycle, default
FIFO/LIFO actions and floating geometry. The modernized UI routing suite also
passes bubble click-through, grouped chooser search/Enter and icon-specific
original-workspace restoration, with preserving fixture cleanup.

## v1.27.0 — one-handed defaults and FIFO shortcut — 9 November 2026

Defaults are Super+D to stash, Super+Z to restore newest, and Super+Alt+Z to
restore oldest. Saved custom shortcuts and explicitly disabled actions survive
updates. The native fresh-install CLI suite verifies all three active bindings,
actual minimize/newest/oldest key presses, FIFO selection with two parked windows,
exact floating geometry, and the complete update/disable/remove/reinstall lifecycle.
The complete non-graphical check passes **231 Python tests**, **11 Node suites**,
**four offscreen Qt suites**, manifest validation, QML lint and Python syntax checks.

## v1.26.1 — shortcut reset defaults — 9 November 2026

Per-field shortcut reset buttons read the same controller defaults as Reset all;
legacy and custom saved bindings remain separate. Native clicks on all three
reset buttons verify the displayed default, persisted preference and runtime
binding, followed by restored original preferences. The complete non-graphical
check passes **231 Python tests**, **11 Node suites**, **four offscreen Qt suites**,
manifest validation, warning-free QML lint and Python syntax checks.

## v1.26.0 — automatic CLI lifecycle — 9 November 2026

Fresh installation uses only `omarchy plugin add <GitHub URL> --enable`.
A clean public GitHub clone initialized the service and runtime shortcuts without
running the legacy setup helper, creating a command wrapper, or editing Hyprland
or switcher source. Native icon restoration preserved floating position and size.

The complete non-graphical check passes **230 Python tests**, **11 Node suites**,
**four offscreen Qt suites**, manifest validation, warning-free QML lint and syntax
checks for **69 Python files**.

A disposable Hyprland/Omarchy desktop, with a private home, runtime, D-Bus and
virtual input devices, passes the full new CLI acceptance suite:

- Add and enable, native icon interaction and actual default keyboard actions;
  stock Super+A remains available.
- External switcher activation restores only the selected owned window, with
  exact floating geometry, and closes the private workspace overlay. Stale focus
  without a visible stash workspace does not undo minimization.
- Compositor reload reclaims shortcuts; a real fast-forward CLI update hands
  service ownership to the new generation without restoring the stash.
- Disable restores owned windows to original workspaces and releases exact
  shortcut handles. Reenable preserves preferences.
- Removal deletes the source checkout while windows are stashed; the preloaded
  guardian still restores them. Reinstall restores preferences and remains free
  of legacy wrappers and config patches.

Small-screen settings reachability also passes at 640×480 and 400×300, both at
1.25 scale, including all sections, keyboard navigation, scrolling, popup bounds
and reset cancellation. The full reset suite verifies cancellation paths,
unapplied shortcut drafts, one atomic confirmed reset and preserved stash,
positions and client geometry. The full middle-click suite covers all three
presentations, both fan directions, grouped windows and save-prompt cancellation.
Native preview checks verify actual still/live pixels, unchanged client geometry
and focus, pointer transfer and capture release.

## Legacy helper-backed CLI installation — 9 November 2026

The README uses the installed `omarchy plugin add`, `enable`, `update` and
`remove` commands. Installer regressions use temporary files and mocked desktop
IPC to verify repeatable setup within a Git checkout, unchanged source/local
files, preserved preferences and positions, and cleanup before CLI removal.
Failed restoration or unconfirmed shell disablement prevents successful cleanup;
delayed shortcut synchronization respects the disabled-plugin setting.

The non-graphical suite passes **181 Python tests**, **11 Node suites**, **four
offscreen Qt suites**, manifest validation, warning-free QML lint and syntax
checks for **63 Python files**. All three lifecycle command examples also pass
shell syntax checks. No desktop input or installed configuration was changed
for these checks.

On the working desktop, the previous manual installation was removed through
cleanup and `omarchy plugin remove`, then cloned from public GitHub with
`omarchy plugin add`. Setup from that checkout, CLI enablement and a shell
restart succeeded. The user's existing explicit shortcut override was preserved
before setup. Native checks passed for Settings, all three presentations,
click restoration with exact floating geometry, configurable keyboard actions,
thumbnail capture and release, and five distinct Enhanced Ghostty/btop frames
with unchanged focus/geometry and released rendering leases. Preferences, saved
positions, personal bindings and the monitor profile were verified afterwards.

## v1.25.0 — 7 November 2026

Static dock placement passes the complete new native suite and six related
regression suites: dock sides, small-screen settings, reset, floating fans, hover
previews and middle-click closure. Checks ran in a disposable nested compositor;
existing windows and configuration on the working desktop were not used as fixtures.

The non-graphical suite passes **170 Python tests**, **11 Node suites**, **four
offscreen Qt suites**, manifest validation, warning-free QML lint and syntax
checks for **63 Python files**. The update is installed on the working desktop;
a preserving native check verifies icon dragging, persisted placement, the actual
Placement relock control and locked gesture refusal. Existing windows, stash,
preferences, positions, focus and runtime monitor geometry remain unchanged.
The already loaded Enhanced preview implementation remains compatible without
restarting Hyprland.

| Requirement | Evidence |
|---|---|
| Unlock and relock | Native Placement dropdown; icon and background drags on all four edges; fixed cross-axis position; ordinary clicks restore in both states; locked/outside releases preserve the stash |
| Persistent placement | Each completed drag saves a normalized position per monitor and edge; all four positions and lock state survive shell restart, scope changes and icon-size reflow |
| Interrupted gestures | Native end-stop clamps and lock/edge/presentation changes during an active drag; no unintended restore or close; compact single-icon locked docks reject left/middle drag gestures |
| Overflow and reserved areas | Locked/unlocked axis-wheel scrolling on every edge at 320×240 logical pixels and 1.25 scale; temporary bar appearance/removal preserves placement |
| Independent monitors | A real second virtual-output drag preserves every saved first-output edge position; anonymous displays use output names without changing older floating-position keys |
| Drag state races | Actual QML offscreen checks cover resizing into overflow, acknowledgements received while held, one-time cancellation/save, and correct edge/monitor ownership; negative controls reproduce the two races |
| Native preview updates | Independent native implementation version accepts the unchanged loaded 1.24 bridge across UI-only 1.25 upgrades; 35 builder/helper checks retain strict protocol, implementation-version and compositor ABI guards |

```sh
python3 tools/check.py
python3 tests/static_dock_drag.py --small-output
```

## v1.24.0 baseline — 6 November 2026

Validated against Omarchy **4.5.0-3**, Hyprland **0.56.2-4** (build
`efb5099`), Quickshell **0.3.2.r7.g2b4501a-1**, Qt **6.12** and Ghostty
**1.4.0**.

The completed v1.24.0 regression matrix passed **36 native suites**, including their
small-output variants, **164 Python tests**, **11 Node suites**, **three
offscreen Qt suites**, manifest validation and warning-free QML lint. Python
syntax checks cover all **61 source and test files**. Native suites ran in a
disposable Bubblewrap home and runtime with a nested Hyprland compositor, real
GTK, terminal and browser buffers, XWayland and virtual outputs. Installation,
removal, configuration reload and layout tests used that isolated profile.
The update was also installed on the working desktop. A preserving acceptance
check verified seven distinct btop/Ghostty frames, two simultaneously updating
grouped terminal thumbnails, release on hiding, and no idle rendering. Existing
windows, stash entries, preferences, focus and runtime monitor geometry were
restored; Enhanced compatibility is enabled. Configuration-reload recovery was
verified in the isolated compositor; working-desktop reloads can reposition the
cursor and dismiss a hover preview.

Standard Live previews remain dependent on application buffer production.
Enhanced compatibility uses the optional native bridge for only the windows
represented by visible Live thumbnails. Actual btop/Ghostty, Chromium and Brave
captures were verified with changing pixels, unchanged focus and geometry, and
lease cleanup after hiding or restoring their windows. No compositor-wide
hidden-rendering setting is required.

| Requirement | Evidence |
|---|---|
| Controller state, settings, FIFO/LIFO ordering, scope, identity reuse, partial-failure retry, geometry and state recovery | 76 passing Python controller tests |
| Atomic window identity | Initial tagging and every minimize/restore mutation validate PID and stable window ID inside the compositor; ownership and final geometry reads are checked. Nine regression tests cover address reuse, closure, fullscreen snapshots, scrolling and retryable partial operations |
| Blank monitor metadata | Four regression tests and native disconnected-monitor recovery verify that unrelated blank output fingerprints cannot capture the origin; saved output names and local workspace-slot fallback retain physical reconnect behavior |
| Native test safety | All four empty-desktop legacy runners refuse existing stash entries before arming cleanup; regression tests confirm no restore/close/configuration mutation. Snapshot readiness uses exact record IDs, and status polling tolerates bounded shell restart gaps |
| Grouping, filtering, ordering and bubble placement | Passing Node model checks |
| Valid plugin and QML | Omarchy manifest validator and Qt6 qmllint pass without warnings |
| Publication metadata and licensing | Project copyright belongs to artu-ole; manifest v1.24.0 names author artu-ole and SPDX license AGPL-3.0-only. The full AGPL license is included, and upstream MIT/BSD notices remain in THIRD_PARTY_NOTICES.md |
| Omarchy 4.5 native dock coexistence | Plugin windows use `special:window-stash`; native minimized windows stay on `special:minimized`. Native tests migrate only ledger-backed windows with matching PID, stable ID and ownership tag, preserve saved metadata and exact floating geometry, and verify the installed native dock model excludes private stashed windows while retaining its own minimized windows |
| Native floating workspace mode | New plugin minimize requests defer to Omarchy's dock on floating workspaces; individual floating windows on tiled workspaces remain supported. Native tests restore a tiled window into floating mode over an underlying scrolling layout, verify native minimize stays independent, and confirm the window returns to tiling and plugin stashing when the mode ends. Pure checks cover generated explicit/default mode files, bounded parsing and saved floating geometry |
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
| Icon and dock size presets | Nine native choices from 50% to 300% across static docks, bubbles and floating docks; centered growing artwork, bounded app badges, scaled stack tails, edge-bubble packing, restore input and both-axis overflow on a temporary 320×240 output. Open/held resizing safely folds or defers; pressed-resize guards prevent accidental restoration. Pure checks cover all presets, shapes, reserved/fractional work areas, hit bounds and every fan style |
| Confirmed normal closure | Native isolated-ledger immediate/delayed close, shared grace, native Save/Cancel prompt, unstashed same-app preservation, workspace/global close-all; unit tests cover atomic identity guards, hexadecimal stable IDs, address reuse, partial failure and polling outages |
| Pointer context menus | Native actual click coordinates, four edges, icon/group/front-stack and chooser-row targeting, separated global section, keyboard navigation, click-through outside dismissal, scope-aware close-all, focus return to chooser, prompt accessibility and secondary scaled monitor |
| Middle-click closure | Native static dock, bubbles, collapsed front icon, both expanded axes, pending icon retention/frozen body, duplicate coalescing, grouped stash-only close and Save/Cancel handling |
| Animation speed presets | Native selection of Slow, Relaxed, Normal, Fast and Ultrafast; measured Arc and Matryoshka unfold/fold timing, stable actors/origin, speed change during unfolding, Slow-safe 800 ms leave grace and immediate outside click, Reduced/Off overrides, actual feedback timings across all presentations, and preview/thumbnail fades with unchanged hover delays. Node simulation preserves physical trajectories while scaling Direct/fallback tweens; offscreen Qt covers both speed-change directions during icon retirement and eventual cleanup |
| Hover window previews | Native Off/Still/Live dropdown, exact red/green client pixels while parked, changing content held in Still and updated in Live, unchanged client geometry/focus, opening delay/cancellation, card hover grace and buffer unload, all three presentations and chooser rows, selected-window restore/menu/confirmed close, expanded-fan keepalive and dismissal, four-sided placement, and large previews at every corner of a temporary 320×240 output; pure geometry/identity checks include fractional scales, rounded input, stale metadata and address reuse |
| Enhanced live-preview compatibility | Nine sampled Enhanced frames were distinct for each app: Standard-to-Enhanced distinct-frame counts were btop/Ghostty 1→9, Chromium 6→9 and Brave 5→9. Native tests also cover two simultaneous grouped Ghostty thumbnails, per-window restore, active configuration reload, scoped leases, unchanged focus/geometry and an idle renderer after preview dismissal |
| Native bridge lifecycle and isolation | Native checks reject malformed or mismatched PID/stable-ID/tag/workspace identities without changing foreign windows; independent owners, overlapping sets and idempotent release work. Renewals every 500 ms survive beyond a lease period; abandoned leases expire and resuspend windows. Restored/closed sources are rejected, active unload restores suspension, and reloading safely reacquires while the compositor remains responsive |
| Physical preview hover | One shared 32 ms compositor cursor timer runs only while a preview is pending/open, a floating fan is open or a context menu is active. Global logical coordinates are converted per monitor to validate source/card bounds, clear stale Qt hover after grouped restoration, and preserve configured opening/grace delays. Native full-app and standard-preview tests pass; model checks cover stale Qt state, negative monitor offsets, rounded card corners and unknown-position fallback |
| Unfolded front-icon previews | Native stationary-pointer and older-to-front hovering in horizontal Cascade docks opening left/right at Normal speed, 400 ms delay, vertical grouped Live captures at Fast speed, exact actor source rectangles, unchanged parked geometry, and collapsed hover/main-click chooser restoration |
| Side-by-side app previews | Native three-window red/green/blue strip with aligned, non-overlapping thumbnails, per-window restore/menu/middle-close/close button, Still frames and delegate identity preserved across metadata refreshes, and Live capture for every visible tile. A temporary 320×240 output covers horizontal wheel scrolling, all windows retained in the strip, newly visible capture, offscreen stream release and restoring only the chosen window. Model checks cover even resizing, readable minimum widths, bounded overflow and tiny/fractional outputs |
| Preview title close button | Live grouped previews show a bounded, centered × in each visible title strip; clicking it confirms closure of only that window. Hidden titles remove the button, while middle-click still closes and confirms the represented window; preferences, existing stash, focus and display geometry preserved |
| Physical floating dragging | Pure simulation at 30/60/120/144 Hz and native offscreen Qt clock; real pointer flicks, stale-velocity rejection, catching, gentle collisions and neighbor saving, constrained edges, Direct/Reduced/Off, frozen menu/fan origin, held-dock mode switch without ghost input, and restart without saved velocity |
| Trailing floating stack | Native direct lead tracking, cascaded two-axis spring lag through turns and flicks, independent exact catch-up, all five speed presets, click-through trailing artwork, continuous Arc/Matryoshka unfold and interrupted fold, held-drag mode changes, grouping resets and work-area bounds. Pure checks cover bursty pointer input at 30/60/120/144 Hz without velocity injection; offscreen Qt verifies live speed changes, identity resets, rigid idle placement and the sleeping frame clock |
| Fixed floating stack origin | Full native animation samples keep the original icon at its pre-click coordinates throughout unfolding and folding for all eight styles and both orientations, including off-center clicks; geometry tests include fractional anchors and subtle bounded front-icon effects |
| Upward horizontal arches | Native Arc, Spring, Swing and Matryoshka hops unfold/fold left and right with upward-only curves, reduced lift near the reserved top edge, fixed front, stable panel thickness and exact stacked endpoints. Model checks cover fractional/top-edge anchors, stale downward preferences and coherent group paths; vertical layouts and poses remain unchanged |
| Jumping unfold style | Native settings selection, launch squash, airborne stretch and landing compression in both axes/directions; upward-only near-top jumps, fixed front and panel thickness, in-flight fold/reopen, Ultrafast and Reduced/Off, with original desktop state restored. Pure checks sample 352,107 bounded frames, two diminishing landing rebounds, continuous phase boundaries, fractional/reserved edges, exact endpoints, reverse paths and all speed presets |
| Fixed floating background thickness | Native all-eight-style unfold/fold samples in both axes retain cross-axis position, thickness and corner radius, with gradual bounded length and unchanged jumping icons; interrupted reversal, negative expansion, large corners, interactive airborne-icon restore and Reduced/Off/hidden backgrounds pass. A temporary 320×240 output covers overflow paging, stable edge corners and source removal. Pure geometry checks include fractional anchors, edge reservations, elastic overshoot and exact icon input shapes |
| Floating fan styles | Native dropdown selection for Arc, Glide, Cascade, Spring and Swing; each style in both orientations, distinct motion, persistent actors and complete restacking; non-default choice survives restart; Reduced/Off override all five profiles. Pure geometry checks cover distinct paths, exact endpoints, rotated-corner bounds and capped staggering |
| Matryoshka unfolding | Native straight/hopping choices, shared stack travel and successive deposits, fixed original icon, both axes and free/edge placement, reversible collection, source-removal holding, smooth front replacement, app grouping, Reduced/Off and nonzero-page reversal on a temporary 320×240 output; pure checks cover all work-area edges, fractional anchors, paging, exact endpoints and bounded durations |
| Quicker Matryoshka baseline | Historical timing checks verify 1.5× faster straight/hopping unfold and fold clocks, including one-icon minimums and long-list caps, across all five speed presets. Reduced/Off and other styles retain their previous timings |
| Floating fan dismissal | Native tests cover the 800 ms pointer-leave grace, cancellation on re-entry, immediate click dismissal on apps, empty desktop and transparent rounded corners, and delivery of the same click to the underlying GTK app in both orientations. Non-consuming press/release observers retain layer focus only until physical release; tests verify exactly one GTK press, release and click with both follow-mouse policies, a 3.3-second outside hold, and Escape recovery from a retained hidden layer. Existing mouse/key bindings remain unchanged |
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
| Input regions | Coalesced Region changes request a window update so Quickshell's queued polish reaches the Wayland input mask in static scenes on Qt 6.12. Native bubble click-through, grouped-icon reflow, hover/restore/middle-close input, dragging and small-output overflow pass |
| Icon shapes | Live native dropdown, all five bubble shapes, corner input, squircle dragging, dock restore and saved choice after shell restart; model checks cover exact squircle input pixels and legacy setting defaults |
| Desktop test notice | All desktop suites notify before a five-second countdown; unit checks verify ordering, refusal without a notification, and completion on failure |
| Configurable shortcuts and FIFO restoration | Native Settings Apply/Return normalization, Clear/Default, duplicate/foreign conflict rejection with unchanged settings and active handles, retained failed drafts and error recovery; actual configured minimize, newest and oldest key presses restore only eligible owned fixtures in LIFO/FIFO order with exact floating geometry; rebinding disables the prior chord and empty oldest disables FIFO. A non-default shortcut survives both shell restart and compositor configuration reload |
| Shortcut migration and ownership | 13 isolated backend tests cover canonical chords, exact owned-handle identities, conflicts, serialization, atomic persistence/rollback, and Lua bootstrap/handle reuse. 20 installer tests cover consent, recognized legacy calls/paired overrides, byte-preserved outside configuration, duplicate lookalikes, customized blocks, loader updates, workspace integration upgrades, bridge-source installation and uninstall; live migration retains the existing Super+A override and A/Z defaults |
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
| Organized settings | Six native Omarchy header groups: General, Placement, Appearance, Motion, Previews and Keyboard shortcuts. Live checks cover all 21 dropdowns, section order, preserved values, conditional controls across static/bubble/floating modes, numeric placement, native dropdown editing and access to the final shortcut field; original preferences, stash, focus and monitor geometry restored |
| Small-screen settings | The complete settings page, errors and reset confirmation scroll within the usable work area; narrow labels/controls and shortcut actions wrap. Native checks cover all 29 preferences and six sections, wheel/drag/scrollbar navigation, whole-control Tab focus, bounded nine-option dropdowns and reset cancellation behind reserved bars. Tested modes include 640×480 at 1.25 scale (512×384 logical) and 400×300 at 1.25 scale (320×240 logical) |
| Confirmed settings reset | Native Cancel/default Enter/Escape/outside dismissal, fresh confirmation on reopen, one-shot confirmation, all canonical preferences and active managed shortcuts restored, with stash, positions and client geometry preserved. Twelve Python checks cover mandatory CLI confirmation, default binding conflicts, persistence rollback, concurrent edits, host metadata and file permissions |
| Floating defaults | Canonical defaults, initial shell snapshot, fallback rendering, fresh installs and reset use a floating dock with edge gravity, transparent dock chrome, frameless icons and Normal speed. Existing explicit preferences remain valid; the requested presentation/appearance/motion fields are applied locally without resetting unrelated choices |
| Safe removal and reinstall | Removal restores a parked window and removes bindings/integration; reinstall reloads successfully |

The native suites use disposable GTK, terminal and browser windows inside the
isolated compositor, with headless outputs for monitor/scale tests. No claim of
testing three physical displays is made. Cleanup restores fixture preferences,
positions and focus, removes test windows/workspaces and restores saved mode
files. Input automation announces itself before a full five-second countdown.

Commands: `python3 tools/check.py`, `python3 tests/live.py`,
`python3 tests/layouts_monitors.py`, `python3 tests/ui_lifecycle.py`, and
`python3 tests/overflow.py`, `python3 tests/themed_ui.py`, and
`python3 tests/scrolling_width.py`, `python3 tests/icon_shapes.py`, and
`python3 tests/floating_dock.py`, and `python3 tests/floating_direction.py`, `python3 tests/dock_sides.py`, `python3 tests/floating_placement.py`, `python3 tests/dock_corners.py`, `python3 tests/frame_visibility.py`, `python3 tests/hover_feedback.py`, `python3 tests/animation_modes.py`, `python3 tests/transparency.py`, `python3 tests/floating_fan.py`, `python3 tests/close_actions.py`, `python3 tests/context_actions.py`, `python3 tests/middle_close.py`, `python3 tests/drag_physics.py`, `python3 tests/matryoshka.py --small-output`, and `python3 tests/hover_previews.py --small-output`, `python3 tests/floating_main_preview.py`, and `python3 tests/animation_speed.py`, and `python3 tests/stack_follow.py`, and `python3 tests/floating_panel.py --small-output`, and `python3 tests/shortcuts.py`, and `python3 tests/jumping.py`, and `python3 tests/sizing.py`, and `python3 tests/reset_settings.py`, and `python3 tests/settings_fit.py`, `python3 tests/omarchy45.py`, `python3 tests/live_compatibility.py`, `python3 tests/preview_bridge_native.py`, and `python3 tests/outside_input.py`. Pinned restoration and workspace-ID event handling
were additionally checked directly against the live compositor.

Validation did not upgrade system packages or modify packaged Omarchy files.
Stash metadata survives
shell restarts within a compositor session; this is not application session
restoration after logout.

## Publishing review — 5 November 2026

Reviewed against the [publishing guide](https://plugins.omarchy.org/publish.html),
[submission requirements](https://github.com/omacom/omarchy-plugin-marketplace/blob/main/SUBMISSION.md),
and [Omarchy shell contract](https://github.com/omacom/omarchy/blob/quattro/docs/omarchy-shell.md).
The guide review retains its original date; the local artifact results below
reflect v1.24.0 and the 6 November regression sweep.

| Local requirement | Result |
|---|---|
| One root manifest and matching entry point | Schema 1, service kind, `Service.qml`, version `1.24.0`; installed Omarchy validator passes |
| Namespaced third-party ID | `community.window-stash` is outside reserved `omarchy.*`; registry availability was checked for the earlier review and must be rechecked before submitting |
| Author and license | `artu-ole` in the manifest and project copyright in README; SPDX `AGPL-3.0-only` and the full root AGPL license; upstream MIT/BSD notices retained in `THIRD_PARTY_NOTICES.md` |
| Documentation | Root README covers dependencies, manual setup, updates, settings, recovery, removal, user-file changes, and local metadata |
| Consent before configuration edits | Helper displays its plan and prompts before any writes; non-interactive runs require explicit `--yes`; refusal and consent tests pass |
| File layout | No symlinks, bundled executables, credentials, or private runtime data in the source folder |
| Shared UI | Uses installed Omarchy theme tokens and UI components; icons are looked up locally rather than bundled |
| Checks after publishing preparation | 164 Python tests, 11 Node suites, three offscreen Qt suites, syntax checks for 61 Python files, publishing metadata checks, manifest validation, and Qt6 QML lint pass |

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
