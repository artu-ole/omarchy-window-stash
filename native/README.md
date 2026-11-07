# Optional live preview bridge

`preview.cpp` is compiled locally for the exact installed Hyprland build. No
binary is shipped. The shell plugin works without it; enhanced Live previews
use it to let hidden clients such as Ghostty continue producing frames.

The bridge hooks `CWindow::setSuspended` only for identities currently leased
by visible previews. A 15 FPS feedback timer also services those surfaces.
It never changes focus, geometry, workspace visibility or window rendering
rules. Releasing a lease restores the compositor's natural suspension state.

Build without loading:

```sh
python3 tools/build-preview-bridge.py --output /tmp/window-stash-preview.so
```

The builder prints JSON with the binary path, build hash, version and protocol.
`--expected-hash HASH` additionally checks that installed headers match the
running compositor. Loading also checks the full Hyprland and dependency ABI.
The source uses Hyprland internals; rebuild after compositor updates.

`native/version.txt` identifies the native implementation independently of the
shell plugin's manifest version. Bump it whenever `preview.cpp` changes; UI-only
releases keep it unchanged so an already loaded, compatible bridge remains usable.
The builder embeds this version and includes it in the cache fingerprint. The
helper requires an exact match alongside protocol and compositor ABI checks;
changing native versions requires restarting Hyprland to replace loaded code.

The Lua API lives under `hl.plugin.window_stash_preview`:

```lua
local result, err = hl.plugin.window_stash_preview.update({
  owner = "0123456789abcdef0123456789abcdef", -- random per-helper 32 hex token
  windows = {{
    id = "abcdef0123456789abcdef0123456789",
    tag = "window-stash-abcdef0123456789abcdef0123456789",
    address = "0x12345678",
    pid = 1234,
    stable_id = "18000001", -- hexadecimal, as in clients JSON
  }},
})
-- result.accepted/result.requested; nil, error on invalid input

hl.plugin.window_stash_preview.release("0123456789abcdef0123456789abcdef")
local details = hl.plugin.window_stash_preview.status()
```

Each update replaces one owner's complete set. Renew every 500 ms; leases
expire after 2.5 seconds without renewal. Other owners remain independent.
Empty updates and release calls are idempotent. PID, stable ID, exact ownership
tag and `special:window-stash` membership are checked before accepting a
record and on every timer/hook invocation. Closed, restored, retagged and
replaced windows lose eligibility immediately. Unload releases every lease.
