# Validation — 5 November 2026

Implemented and installed on Omarchy 4.0.6-1 / Hyprland 0.56.2.

| Requirement | Evidence |
|---|---|
| Controller state, LIFO ordering, scope, identity reuse, partial-failure retry, geometry and state recovery | 13 passing Python unit tests |
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
| Dock and bubbles | Live icon clicks, bubble dragging, position persistence and mode changes |
| Input regions | A click outside bubbles reaches a GTK window underneath |
| App grouping and chooser | Group two windows, open chooser by mouse, search by keyboard and restore with Enter |
| Restore destination | Live original/current destination checks and original-workspace context action |
| Global/workspace scope | Live one-, two-, and three-output checks in dock and bubble modes |
| Mixed resolution/scale | Restore a floating window onto a 1280×720 output at 1.25 scale; assert work-area bounds |
| Disconnect recovery | Remove the origin output and restore its saved local workspace slot onto the laptop |
| Workspace renumbering | Observe `changeworkspaceid>>9,90`, verify origin update, then restore ID 90 to 9 and remove the test workspace |
| Shell restart | Park a window, restart the shell, recover the same record and floating state |
| Closed minimized windows | Close the parked test window and verify ledger cleanup |
| Dock overflow | Twelve entries on a 640×480 virtual output; real pointer drag scrolls without restoring a window |
| Omarchy theme and shared controls | Native buttons, dropdowns, search, and tooltips; live Tokyo Night visual check, all four dropdowns and external-setting synchronization, grouped bubble search/Enter restore, context restore and dock click |
| Safe removal and reinstall | Removal restores a parked window and removes bindings/integration; reinstall reloads successfully |

The live suites use disposable GTK windows and headless virtual outputs. The
virtual outputs supplement the laptop display; no claim of testing three
physical displays is made. Cleanup restores the original application focus,
settings and display profile, and removes the test windows and workspaces.

Commands: `python3 tools/check.py`, `python3 tests/live.py`,
`python3 tests/layouts_monitors.py`, `python3 tests/ui_lifecycle.py`, and
`python3 tests/overflow.py`, `python3 tests/themed_ui.py`, and
`python3 tests/scrolling_width.py`. Pinned restoration and workspace-ID event handling
were additionally checked directly against the live compositor.

No upgrade, external publication or packaged Omarchy-file modification was
performed. Hover thumbnails are deferred as specified. Stash metadata survives
shell restarts within a compositor session; this is not application session
restoration after logout.

## Publishing review — 5 November 2026

Reviewed against the [publishing guide](https://plugins.omarchy.org/publish.html),
[submission requirements](https://github.com/omacom/omarchy-plugin-marketplace/blob/main/SUBMISSION.md),
and [Omarchy shell contract](https://github.com/omacom/omarchy/blob/quattro/docs/omarchy-shell.md).

| Local requirement | Result |
|---|---|
| One root manifest and matching entry point | Schema 1, service kind, `Service.qml`, version `1.0.0`; installed Omarchy validator passes |
| Namespaced third-party ID | `community.window-stash` is outside reserved `omarchy.*`; no exact match in current registry data, including retired IDs; recheck before submitting |
| Author and license | `artu-ole` in the manifest and project copyright; SPDX `AGPL-3.0-only` and the full root AGPL license; integration excerpts attributed in `THIRD_PARTY_NOTICES.md` |
| Documentation | Root README covers dependencies, manual setup, updates, settings, recovery, removal, user-file changes, and local metadata |
| Consent before configuration edits | Helper displays its plan and prompts before any writes; non-interactive runs require explicit `--yes`; refusal and consent tests pass |
| File layout | No symlinks, bundled executables, credentials, or private runtime data in the source folder |
| Shared UI | Uses installed Omarchy theme tokens and UI components; icons are looked up locally rather than bundled |
| Checks after publishing preparation | 16 Python tests, model checks, publishing metadata checks, manifest validation, and Qt6 QML lint pass |

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
