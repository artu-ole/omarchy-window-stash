// SPDX-License-Identifier: AGPL-3.0-only
// Optional, session-local bridge for live captures of parked windows.
#include <hyprland/src/plugins/PluginAPI.hpp>
#include <hyprland/src/desktop/Workspace.hpp>
#include <hyprland/src/desktop/state/WindowState.hpp>
#include <hyprland/src/desktop/view/Window.hpp>
#include <hyprland/src/desktop/view/WLSurface.hpp>
#include <hyprland/src/managers/eventLoop/EventLoopManager.hpp>
#include <hyprland/src/protocols/core/Compositor.hpp>

extern "C" {
#include <lua.h>
}

#include <charconv>
#include <chrono>
#include <cstdint>
#include <limits>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

#ifndef STASH_BRIDGE_VERSION
#define STASH_BRIDGE_VERSION "development"
#endif

namespace {
using Desktop::View::CWindow;
using Clock = std::chrono::steady_clock;
constexpr auto LEASE_TIME = std::chrono::milliseconds(2500);
constexpr auto FRAME_TIME = std::chrono::milliseconds(66);
constexpr auto WORKSPACE = "special:window-stash";
constexpr auto LUA_NAMESPACE = "window_stash_preview";
constexpr size_t MAX_OWNERS = 32;
constexpr size_t MAX_WINDOWS = 256;

struct Identity {
    std::string id;
    std::string tag;
    uintptr_t address = 0;
    pid_t pid = 0;
    uint64_t stable = 0;
    PHLWINDOWREF window;
};
struct Lease {
    Clock::time_point expires;
    std::vector<Identity> windows;
};

HANDLE handle = nullptr;
CFunctionHook* suspendHook = nullptr;
SP<CEventLoopTimer> frameTimer;
std::unordered_map<std::string, Lease> owners;
std::unordered_map<CWindow*, Identity> active;
uint64_t frames = 0;
uint64_t preventedSuspends = 0;

bool hexadecimal(const std::string& text, size_t length) {
    return text.size() == length && text.find_first_not_of("0123456789abcdefABCDEF") == std::string::npos;
}

uint64_t integerHex(const std::string& text) {
    auto value = text.starts_with("0x") ? text.substr(2) : text;
    if (value.empty() || value.size() > 16 || !hexadecimal(value, value.size()))
        throw std::invalid_argument("Invalid hexadecimal identity");
    uint64_t result = 0;
    const auto parsed = std::from_chars(value.data(), value.data() + value.size(), result, 16);
    if (parsed.ec != std::errc{} || !result)
        throw std::invalid_argument("Invalid hexadecimal identity");
    return result;
}

std::string stringAt(lua_State* state, int index) {
    if (lua_type(state, index) != LUA_TSTRING)
        throw std::invalid_argument("Expected an identity string");
    size_t size = 0;
    const char* data = lua_tolstring(state, index, &size);
    if (size > 128)
        throw std::invalid_argument("Identity string is too long");
    return std::string(data, size);
}

std::string stringField(lua_State* state, int table, const char* field) {
    const int index = lua_absindex(state, table);
    lua_pushstring(state, field);
    lua_rawget(state, index);
    auto result = stringAt(state, -1);
    lua_pop(state, 1);
    return result;
}

bool sameWindow(const Identity& identity, CWindow* window, bool parked) {
    if (!window || !window->m_isMapped || reinterpret_cast<uintptr_t>(window) != identity.address
        || window->getPID() != identity.pid || window->m_stableID != identity.stable)
        return false;
    if (!parked)
        return true;
    return window->m_workspace && window->m_workspace->m_name == WORKSPACE
        && window->m_ruleApplicator->m_tagKeeper.isTagged(identity.tag, true);
}

bool leased(CWindow* window) {
    const auto it = active.find(window);
    return it != active.end() && it->second.window.lock().get() == window && sameWindow(it->second, window, true);
}

void suspend(CWindow* window, bool requested) {
    if (requested && leased(window)) {
        requested = false;
        ++preventedSuspends;
    }
    using Original = void (*)(CWindow*, bool);
    reinterpret_cast<Original>(suspendHook->m_original)(window, requested);
}

void naturalSuspension(const Identity& identity) {
    const auto window = identity.window.lock();
    // A weak handle plus PID and stable ID prevents address reuse from ever
    // changing a replacement window, including during release or unload.
    if (window && sameWindow(identity, window.get(), false))
        window->setSuspended(window->isHidden() || !window->m_workspace || !window->m_workspace->isVisible());
}

void synchronize() {
    auto previous = std::move(active);
    active.clear();
    const auto now = Clock::now();
    for (auto it = owners.begin(); it != owners.end();) {
        if (it->second.expires <= now) {
            it = owners.erase(it);
            continue;
        }
        for (const auto& identity : it->second.windows) {
            const auto window = identity.window.lock();
            if (window && sameWindow(identity, window.get(), true))
                active.emplace(window.get(), identity);
        }
        ++it;
    }
    for (const auto& [window, identity] : previous)
        if (!active.contains(window))
            naturalSuspension(identity);
    for (const auto& [window, identity] : active)
        window->setSuspended(false);
    if (frameTimer) {
        if (owners.empty())
            frameTimer->updateTimeout(std::nullopt);
        else if (!frameTimer->armed() || frameTimer->passed())
            frameTimer->updateTimeout(FRAME_TIME);
    }
}

void frame() {
    synchronize();
    // Protocol callbacks can be reentrant. Keep independent identities and
    // strong window handles while servicing their surface trees.
    std::vector<Identity> snapshot;
    snapshot.reserve(active.size());
    for (const auto& [window, identity] : active)
        snapshot.emplace_back(identity);
    for (const auto& identity : snapshot) {
        const auto window = identity.window.lock();
        if (!window || !leased(window.get()))
            continue;
        if (!window->wlSurface() || !window->wlSurface()->resource())
            continue;
        const auto monitor = window->m_monitor.lock();
        if (!monitor)
            continue;
        // Same bounded frame-feedback path as Hyprland's render_unfocused,
        // without installing or overriding the user's rendering properties.
        window->wlSurface()->resource()->breadthfirst(
            [&monitor, &window](SP<CWLSurfaceResource> surface, const Vector2D&, void*) {
                if (!leased(window.get()))
                    return;
                surface->m_stateQueue.unlockFirst(LOCK_REASON_FENCE | LOCK_REASON_FIFO | LOCK_REASON_TIMER);
                surface->presentFeedback(Time::steadyNow(), monitor, true);
            }, nullptr);
        ++frames;
    }
}

void field(lua_State* state, const char* name, lua_Integer value) {
    lua_pushinteger(state, value);
    lua_setfield(state, -2, name);
}
void field(lua_State* state, const char* name, const std::string& value) {
    lua_pushlstring(state, value.data(), value.size());
    lua_setfield(state, -2, name);
}

int status(lua_State* state) {
    synchronize();
    lua_newtable(state);
    field(state, "protocol", 1);
    field(state, "version", STASH_BRIDGE_VERSION);
    field(state, "hyprlandHash", GIT_COMMIT_HASH);
    field(state, "owners", owners.size());
    field(state, "windows", active.size());
    field(state, "leaseTimeout", LEASE_TIME.count());
    field(state, "frameInterval", FRAME_TIME.count());
    field(state, "frames", frames);
    field(state, "preventedSuspends", preventedSuspends);
    lua_newtable(state);
    int ordinal = 1;
    for (const auto& [window, identity] : active) {
        lua_pushlstring(state, identity.id.data(), identity.id.size());
        lua_rawseti(state, -2, ordinal++);
    }
    lua_setfield(state, -2, "windowIds");
    return 1;
}

int update(lua_State* state) {
    try {
        if (lua_type(state, 1) != LUA_TTABLE)
            throw std::invalid_argument("Expected a preview lease table");
        const auto owner = stringField(state, 1, "owner");
        if (!hexadecimal(owner, 32))
            throw std::invalid_argument("Invalid preview owner");
        lua_pushliteral(state, "windows");
        lua_rawget(state, 1);
        if (lua_type(state, -1) != LUA_TTABLE || lua_rawlen(state, -1) > MAX_WINDOWS)
            throw std::invalid_argument("Invalid preview windows");
        const auto count = lua_rawlen(state, -1);
        std::vector<Identity> requested;
        requested.reserve(count);
        for (size_t i = 1; i <= count; ++i) {
            lua_rawgeti(state, -1, i);
            if (lua_type(state, -1) != LUA_TTABLE)
                throw std::invalid_argument("Expected a window identity table");
            const int table = lua_gettop(state);
            Identity identity;
            identity.id = stringField(state, table, "id");
            identity.tag = stringField(state, table, "tag");
            identity.address = integerHex(stringField(state, table, "address"));
            identity.stable = integerHex(stringField(state, table, "stable_id"));
            if (!hexadecimal(identity.id, 32) || identity.tag != "window-stash-" + identity.id)
                throw std::invalid_argument("Invalid stash ownership identity");
            lua_pushliteral(state, "pid");
            lua_rawget(state, table);
            if (!lua_isinteger(state, -1) || lua_tointeger(state, -1) < 1
                || lua_tointeger(state, -1) > std::numeric_limits<pid_t>::max())
                throw std::invalid_argument("Invalid window PID");
            identity.pid = lua_tointeger(state, -1);
            lua_pop(state, 2);
            requested.emplace_back(std::move(identity));
        }
        lua_pop(state, 1);
        synchronize();
        if (!owners.contains(owner) && owners.size() >= MAX_OWNERS)
            throw std::invalid_argument("Too many preview owners");
        Lease lease{Clock::now() + LEASE_TIME, {}};
        for (auto& identity : requested) {
            for (const auto& window : Desktop::windowState()->windows()) {
                if (sameWindow(identity, window.get(), true)) {
                    identity.window = window;
                    lease.windows.emplace_back(std::move(identity));
                    break;
                }
            }
        }
        const size_t accepted = lease.windows.size();
        if (accepted)
            owners[owner] = std::move(lease);
        else
            owners.erase(owner);
        synchronize();
        lua_newtable(state);
        field(state, "accepted", accepted);
        field(state, "requested", requested.size());
        return 1;
    } catch (const std::exception& error) {
        lua_pushnil(state);
        lua_pushstring(state, error.what());
        return 2;
    }
}

int release(lua_State* state) {
    try {
        const auto owner = stringAt(state, 1);
        if (!hexadecimal(owner, 32))
            throw std::invalid_argument("Invalid preview owner");
        owners.erase(owner);
        synchronize();
        lua_pushboolean(state, true);
        return 1;
    } catch (const std::exception& error) {
        lua_pushnil(state);
        lua_pushstring(state, error.what());
        return 2;
    }
}
}

APICALL EXPORT std::string PLUGIN_API_VERSION() {
    return HYPRLAND_API_VERSION;
}

APICALL EXPORT PLUGIN_DESCRIPTION_INFO PLUGIN_INIT(HANDLE plugin) {
    handle = plugin;
    // Match both the commit and dependency ABI before touching any compositor
    // objects or hooking functions. The bridge is always compiled locally.
    if (std::string(__hyprland_api_get_hash()) != __hyprland_api_get_client_hash()
        || HyprlandAPI::getHyprlandVersion(handle).hash != GIT_COMMIT_HASH)
        throw std::runtime_error("Window Stash preview bridge must be rebuilt for this Hyprland version");
    const auto functions = HyprlandAPI::findFunctionsByName(handle, "setSuspended");
    const SFunctionMatch* target = nullptr;
    for (const auto& function : functions)
        if (function.demangled == "Desktop::View::CWindow::setSuspended(bool)") {
            if (target)
                throw std::runtime_error("Ambiguous Hyprland suspend function");
            target = &function;
        }
    if (!target)
        throw std::runtime_error("This Hyprland version does not expose the required suspend function");
    suspendHook = HyprlandAPI::createFunctionHook(handle, target->address, reinterpret_cast<void*>(&suspend));
    if (!suspendHook || !suspendHook->hook())
        throw std::runtime_error("Could not install the scoped preview suspend hook");
    if (!HyprlandAPI::addLuaFunction(handle, LUA_NAMESPACE, "update", update)
        || !HyprlandAPI::addLuaFunction(handle, LUA_NAMESPACE, "release", release)
        || !HyprlandAPI::addLuaFunction(handle, LUA_NAMESPACE, "status", status))
        throw std::runtime_error("Could not register the preview lease API");
    frameTimer = makeShared<CEventLoopTimer>(std::nullopt,
        [](SP<CEventLoopTimer>, void*) { frame(); }, nullptr);
    g_pEventLoopManager->addTimer(frameTimer);
    return {"window-stash-preview", "Scoped rendering for visible Window Stash live previews", "artu-ole", STASH_BRIDGE_VERSION};
}

APICALL EXPORT void PLUGIN_EXIT() {
    owners.clear();
    synchronize();
    if (frameTimer) {
        frameTimer->cancel();
        g_pEventLoopManager->removeTimer(frameTimer);
        frameTimer.reset();
    }
    // Hyprland removes the hook and Lua callbacks after this function returns.
}
