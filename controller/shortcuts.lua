-- Owned keybind handles survive shell restarts and are reset by Hyprland reload.
-- Never remove/unbind by chord: that can remove an unrelated user's binding.
local mode = ...
local manager = _community_window_stash_shortcuts
if not manager then
  manager = { version = 3, cache = {} }
  _community_window_stash_shortcuts = manager
elseif manager.version ~= 3 then
  -- Keep exact historical handles visible to conflict checking: bind JSON
  -- omits their enabled state, so discarding the cache makes them look foreign.
  for _, record in pairs(manager.cache or {}) do record.handle:set_enabled(false) end
  manager.version = 3
  manager.owner = nil
end

local actions = {
  minimizeShortcut = { "minimize", "Window Stash: minimize focused window" },
  restoreLastShortcut = { "restore-last", "Window Stash: restore last minimized" },
  restoreOldestShortcut = { "restore-oldest", "Window Stash: restore oldest minimized" },
}
local order = { "minimizeShortcut", "restoreLastShortcut", "restoreOldestShortcut" }
local function shell_quote(value)
  return "'" .. value:gsub("'", "'\\''") .. "'"
end
local function json_quote(value)
  return '"' .. tostring(value):gsub('[%z\1-\31\\"]', function(character)
    if character == '\\' then return '\\\\' end
    if character == '"' then return '\\"' end
    return string.format('\\u%04x', string.byte(character))
  end) .. '"'
end

function manager.claim(owner)
  assert(type(owner) == 'string' and owner ~= '', 'Missing shortcut owner')
  manager.owner = owner
end

function manager.disable(owner)
  if owner ~= nil and manager.owner ~= owner then return false end
  for _, record in pairs(manager.cache) do record.handle:set_enabled(false) end
  return true
end

function manager.inspect()
  local result = {}
  for _, record in pairs(manager.cache) do
    local handle = record.handle
    local enabled = handle:is_enabled()
    if enabled ~= nil then
      result[#result + 1] = '{"dispatcher":' .. json_quote(handle.handler)
        .. ',"arg":' .. json_quote(handle.arg) .. ',"description":' .. json_quote(handle.description)
        .. ',"modmask":' .. tostring(handle.modmask) .. ',"key":' .. json_quote(handle.key)
        .. ',"submap":' .. json_quote(handle.submap) .. ',"enabled":' .. tostring(enabled) .. '}'
    end
  end
  return '[' .. table.concat(result, ',') .. ']'
end

function manager.apply(values, command, owner)
  if owner ~= nil and manager.owner ~= owner then return false end
  -- A string remains supported for old managed loaders; new callers pass the
  -- interpreter and bundled script as separately quoted argv elements.
  if type(command) == 'string' then command = { command } end
  assert(type(command) == 'table' and #command > 0, 'Missing controller command')
  local quoted = {}
  for _, argument in ipairs(command) do
    assert(type(argument) == 'string' and argument ~= '', 'Invalid controller argument')
    quoted[#quoted + 1] = shell_quote(argument)
  end
  local executable = table.concat(quoted, ' ')
  local chosen, created = {}, {}
  local ok, message = pcall(function()
    for _, key in ipairs(order) do
      local chord = values[key]
      assert(type(chord) == 'string', 'Missing shortcut value')
      if chord ~= '' then
        local action = actions[key]
        local route = action[1] .. ' --shortcut'
        local identity = key .. '\n' .. chord .. '\n' .. executable .. '\n' .. route
        local record = manager.cache[identity]
        if not record or record.handle:is_enabled() == nil then
          local handle = assert(hl.bind(chord, hl.dsp.exec_cmd(executable .. ' ' .. route),
                                        { description = action[2] }), 'Could not create shortcut')
          handle:set_enabled(false)
          record = { handle = handle }
          manager.cache[identity] = record
          created[#created + 1] = record
        end
        chosen[#chosen + 1] = record
      end
    end
  end)
  if not ok then
    for _, record in ipairs(created) do record.handle:set_enabled(false) end
    error(message)
  end
  manager.disable()
  for _, record in ipairs(chosen) do record.handle:set_enabled(true) end
  return true
end

if mode ~= 'runtime' then
  -- Querying hyprctl while the compositor is parsing config would deadlock.
  -- A deferred external helper checks conflicts before creating any handles.
  local source = assert(debug.getinfo(1, 'S').source:match('^@(.+)$'))
  local helper = source:gsub('%.lua$', '.py')
  local config_home = os.getenv('XDG_CONFIG_HOME')
  if not config_home or config_home == '' then config_home = (os.getenv('HOME') or '') .. '/.config' end
  local command = 'python3 ' .. shell_quote(helper) .. ' sync ' .. shell_quote(config_home .. '/omarchy/shell.json')
  hl.timer(function() hl.exec_cmd(command) end, { timeout = 50, type = 'oneshot' })
end

return manager
