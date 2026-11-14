-- A hidden active window can leave a stale focus cache behind a shell layer.
-- Closing it makes Hyprland focus another private window and open the stash.
-- Observe that exact unmap transaction, never arbitrary special-workspace focus.
local current = _community_window_stash_focus
if current and current.version == 1 then return current end
if current and current.stop then current.stop() end

local guard = { version = 1, records = {}, subscriptions = {}, epoch = 0, cleared = 0 }
_community_window_stash_focus = guard
local special = 'special:window-stash'

local function same(record, other)
  return record and other and record.address == other.address and record.pid == other.pid
    and record.stable_id == other.stable_id and record.tag == other.tag
end

local function matches(window, record)
  if not window or not record or window.address ~= record.address or window.pid ~= record.pid
      or window.stable_id ~= record.stable_id or window.mapped ~= true
      or not window.workspace or window.workspace.name ~= special then return false end
  for _, tag in ipairs(window.tags or {}) do if tag == record.tag then return true end end
  return false
end

local function cancel()
  guard.pending = nil
  if guard.timer then guard.timer:set_enabled(false); guard.timer = nil end
end

local function expire(expected)
  if guard.pending ~= expected then return end
  guard.pending = nil
  guard.timer = nil
  if not expected.candidate or expected.epoch ~= guard.epoch then return end
  local active = hl.get_active_window()
  if not matches(active, expected.candidate) then return end
  local closed = hl.get_window('address:' .. expected.closed.address)
  if closed and (closed.pid ~= expected.closed.pid or closed.stable_id ~= expected.closed.stable_id
      or closed.mapped) then return end
  local monitor = active.monitor
  if not monitor or monitor.name ~= expected.monitor or monitor.id ~= expected.monitor_id
      or not monitor.active_workspace or monitor.active_workspace.id ~= expected.workspace_id
      or not monitor.active_special_workspace or monitor.active_special_workspace.name ~= special
      or monitor.active_special_workspace.id ~= active.workspace.id then return end
  -- The window remains stashed; only the unintended overlay is closed. The
  -- normal switcher recovery sees no visible private workspace to restore from.
  monitor:set_special_workspace({})
  guard.cleared = guard.cleared + 1
end

local function owned(window)
  local record = window and guard.records[window.address]
  return matches(window, record) and record or nil
end

local function exact_record(record)
  if type(record) ~= 'table' or type(record.address) ~= 'string'
      or type(record.pid) ~= 'number' or type(record.tag) ~= 'string' then return nil end
  local window = hl.get_window('address:' .. record.address)
  local identity = { address = record.address, pid = record.pid,
    stable_id = record.stable_id or (window and window.stable_id), tag = record.tag }
  if type(identity.stable_id) ~= 'number' or not matches(window, identity) then return nil end
  return identity
end

function guard.register(record)
  for address, existing in pairs(guard.records) do
    if not matches(hl.get_window('address:' .. address), existing) then guard.records[address] = nil end
  end
  local identity = exact_record(record)
  if identity then guard.records[identity.address] = identity; return true end
  return false
end

function guard.unregister(record)
  if same(guard.records[record.address], record) then guard.records[record.address] = nil end
  if guard.pending and (same(guard.pending.closed, record) or same(guard.pending.candidate, record)) then cancel() end
end

function guard.sync(records)
  cancel()
  guard.records = {}
  for _, record in ipairs(records) do
    local identity = exact_record(record)
    if identity then guard.records[identity.address] = identity end
  end
end

function guard.stop()
  cancel()
  for _, subscription in ipairs(guard.subscriptions) do subscription:remove() end
  guard.subscriptions = {}
  guard.records = {}
  if _community_window_stash_focus == guard then _community_window_stash_focus = nil end
end

guard.subscriptions[1] = hl.on('window.close', function(window)
  local record = owned(window)
  if not record then return end
  guard.records[record.address] = nil
  if not matches(hl.get_active_window(), record) then return end
  -- Hidden-workspace focus opens on the currently focused output, which can
  -- differ from the closed source's saved/private monitor.
  local monitor = hl.get_active_monitor()
  if not monitor or not monitor.active_workspace
      or (monitor.active_special_workspace and monitor.active_special_workspace.name == special) then return end
  cancel()
  local pending = { closed = record, monitor = monitor.name, monitor_id = monitor.id,
    workspace_id = monitor.active_workspace.id }
  guard.pending = pending
  -- An expired one-shot is no longer scheduled by Hyprland. Each close needs
  -- a fresh timer, and its captured transaction cannot act on a newer close.
  guard.timer = hl.timer(function() expire(pending) end, { type = 'oneshot', timeout = 1 })
end)

guard.subscriptions[2] = hl.on('window.active', function(window, reason)
  guard.epoch = guard.epoch + 1
  local pending = guard.pending
  if not pending then return end
  local record = owned(window)
  -- Invisible-window focus enters its workspace first; that nested call emits
  -- TOGGLE_SPECIAL_WORKSPACE (12), masking the original unmap focus reason.
  -- The close witness and one-turn lifetime distinguish this from activation.
  if reason == 12 and record and not pending.candidate and record.address ~= pending.closed.address then
    pending.candidate = record
    pending.epoch = guard.epoch
  else
    cancel()
  end
end)

return guard
