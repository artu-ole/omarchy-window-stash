// SPDX-License-Identifier: AGPL-3.0-only
// Optional, session-local bridge for live captures of parked windows.
#include <hyprland/src/plugins/PluginAPI.hpp>
#include <hyprland/src/desktop/Workspace.hpp>
#include <hyprland/src/desktop/state/WindowState.hpp>
#include <hyprland/src/desktop/state/FocusState.hpp>
#include <hyprland/src/desktop/view/Window.hpp>
#include <hyprland/src/desktop/view/WLSurface.hpp>
#include <hyprland/src/desktop/view/Popup.hpp>
#include <hyprland/src/event/EventBus.hpp>
#include <hyprland/src/managers/SeatManager.hpp>
#include <hyprland/src/managers/KeybindManager.hpp>
#include <hyprland/src/managers/XWaylandManager.hpp>
#include <hyprland/src/managers/SessionLockManager.hpp>
#include <hyprland/src/managers/input/InputManager.hpp>
#include <hyprland/src/managers/eventLoop/EventLoopManager.hpp>
#include <hyprland/src/output/Monitor.hpp>
#include <hyprland/src/protocols/XDGShell.hpp>
#include <hyprland/src/protocols/core/Compositor.hpp>
#include <hyprland/src/state/MonitorState.hpp>
#include <xkbcommon/xkbcommon-keysyms.h>

extern "C" {
#include <lua.h>
}

#include <charconv>
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <deque>
#include <limits>
#include <optional>
#include <any>
#include <set>
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
struct Interaction {
    std::string owner;
    Identity identity;
    CBox rect;
    std::vector<CBox> excludeRects;
    PHLMONITORREF monitor;
    Clock::time_point expires;
    int fps = 60;
    WP<CWLSurfaceResource> grab;
    Vector2D grabOffset;
    Vector2D lastLocal;
    std::set<uint32_t> buttons;
    uint64_t motionEvents = 0;
    uint64_t buttonEvents = 0;
    uint64_t axisEvents = 0;
    Vector2D lastGlobal;
    double lastAxisDelta = 0;
    int32_t lastAxisDiscrete = 0;
    int lastAxisSource = 0;
    bool keyboard = false;
    bool keyboardFocused = false;
    PHLWINDOWREF previousWindow;
    WP<CWLSurfaceResource> previousSurface;
    WP<CWLSurfaceResource> keyboardSurface;
    std::set<uint32_t> keys;
    uint64_t keyEvents = 0;
    xkb_keysym_t exitSymbol = XKB_KEY_NoSymbol;
    uint32_t exitModifiers = 0;
};
struct EndedInteraction {
    std::string owner;
    std::string id;
    std::string reason;
};

HANDLE handle = nullptr;
CFunctionHook* suspendHook = nullptr;
CFunctionHook* focusWindowHook = nullptr;
CFunctionHook* focusSurfaceHook = nullptr;
CFunctionHook* keyboardSendHook = nullptr;
CFunctionHook* keybindHook = nullptr;
bool keyboardSupported = false;
bool changingKeyboardFocus = false;
std::string keyboardError;
SP<CEventLoopTimer> frameTimer;
std::unordered_map<std::string, Lease> owners;
std::unordered_map<CWindow*, Identity> active;
uint64_t frames = 0;
uint64_t preventedSuspends = 0;
auto frameInterval = FRAME_TIME;
std::optional<Interaction> interaction;
std::deque<EndedInteraction> endedInteractions;
std::set<uint32_t> releasedButtons;
CHyprSignalListener mouseMoveListener, mouseButtonListener, mouseAxisListener, lockListener, monitorListener, workspaceListener;
CHyprSignalListener keyboardFocusListener, keyboardEventListener;
struct ReleasedKey {
    Identity identity;
    WP<CWLSurfaceResource> surface;
};
std::unordered_map<uint32_t, ReleasedKey> releasedKeys;
std::optional<ReleasedKey> releaseTarget;

bool validateInteraction();
void endInteraction(const std::string& reason, bool refocus = true);
void interactionDetails(lua_State* state, const std::string& owner = "");
void restoreKeyboard(Interaction& previous, bool refocus);
void acquireKeyboard();

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

uint32_t eventTime() {
    return static_cast<uint32_t>(std::chrono::duration_cast<std::chrono::milliseconds>(Clock::now().time_since_epoch()).count());
}

PHLWINDOW keyboardWindow() {
    if (!interaction || !interaction->keyboardFocused)
        return nullptr;
    const auto window = interaction->identity.window.lock();
    return window && sameWindow(interaction->identity, window.get(), true) ? window : nullptr;
}

PHLWINDOW focusedWindow(Desktop::CFocusState* state) {
    // Normal focusWindow would expose the hidden workspace. Keep compositor
    // window commands aligned with the real keyboard target using the public
    // focus getters, while the normal visible workspace remains untouched.
    if (releaseTarget) {
        const auto window = releaseTarget->identity.window.lock();
        return window && sameWindow(releaseTarget->identity, window.get(), false) ? window : nullptr;
    }
    if (const auto window = keyboardWindow())
        return window;
    using Original = PHLWINDOW (*)(Desktop::CFocusState*);
    return reinterpret_cast<Original>(focusWindowHook->m_original)(state);
}

SP<CWLSurfaceResource> focusedSurface(Desktop::CFocusState* state) {
    if (releaseTarget)
        return releaseTarget->surface.lock();
    if (const auto window = keyboardWindow()) {
        const auto focused = g_pSeatManager->m_state.keyboardFocus.lock();
        const auto root = window->wlSurface()->resource();
        return focused && focused->client() == root->client() ? focused : root;
    }
    using Original = SP<CWLSurfaceResource> (*)(Desktop::CFocusState*);
    return reinterpret_cast<Original>(focusSurfaceHook->m_original)(state);
}

void keyboardSend(CSeatManager* seat, uint32_t time, uint32_t key, wl_keyboard_key_state state) {
    using Original = void (*)(CSeatManager*, uint32_t, uint32_t, wl_keyboard_key_state);
    if (state == WL_KEYBOARD_KEY_STATE_RELEASED && releasedKeys.erase(key))
        return; // InputManager has still consumed its matching physical release.
    if (const auto window = keyboardWindow()) {
        const auto focus = seat->m_state.keyboardFocus.lock();
        if (focus && focus->client() == window->wlSurface()->resource()->client()) {
            if (state == WL_KEYBOARD_KEY_STATE_PRESSED)
                interaction->keys.insert(key);
            else
                interaction->keys.erase(key);
            ++interaction->keyEvents;
        }
    }
    reinterpret_cast<Original>(keyboardSendHook->m_original)(seat, time, key, state);
}

bool keybindEvent(CKeybindManager* manager, std::any data, SP<IKeyboard> keyboard) {
    // A deferred physical release belongs to the same original application,
    // even if an exit already restored ordinary keyboard focus. This also keeps
    // release-triggered WM bindings from acting on an unrelated visible app.
    const auto event = std::any_cast<IKeyboard::SKeyEvent>(&data);
    if (event && event->state == WL_KEYBOARD_KEY_STATE_PRESSED && interaction && validateInteraction()
        && interaction->exitSymbol != XKB_KEY_NoSymbol && keyboard && keyboard->m_xkbState) {
        const auto symbol = xkb_state_key_get_one_sym(keyboard->m_xkbState, event->keycode + 8);
        const auto modifiers = g_pInputManager->getModsFromAllKBs() & 77U;
        if (xkb_keysym_to_lower(symbol) == xkb_keysym_to_lower(interaction->exitSymbol) && modifiers == interaction->exitModifiers) {
            // Consume only this session's explicit exit press. InputManager did
            // not record it, so its later release cannot leak to another app.
            endInteraction("shortcut");
            return false;
        }
    }
    if (event && event->state == WL_KEYBOARD_KEY_STATE_RELEASED) {
        const auto previous = releasedKeys.find(event->keycode);
        if (previous != releasedKeys.end())
            releaseTarget = previous->second;
    }
    using Original = bool (*)(CKeybindManager*, std::any, SP<IKeyboard>);
    const bool result = reinterpret_cast<Original>(keybindHook->m_original)(manager, std::move(data), keyboard);
    releaseTarget.reset();
    return result;
}

void acquireKeyboard() {
    if (!interaction || !interaction->keyboard || interaction->keyboardFocused || !keyboardSupported)
        return;
    const auto window = interaction->identity.window.lock();
    if (!window || !sameWindow(interaction->identity, window.get(), true) || !g_pSeatManager->m_keyboard)
        return;
    if (g_pSessionLockManager->isSessionLocked() || !g_pInputManager->m_exclusiveLSes.empty())
        return;
    const auto root = window->wlSurface()->resource();
    interaction->previousWindow = Desktop::focusState()->window();
    interaction->previousSurface = g_pSeatManager->m_state.keyboardFocus;
    interaction->keyboardSurface = root;
    interaction->keyboardFocused = true;
    changingKeyboardFocus = true;
    if (const auto previous = interaction->previousWindow.lock(); previous && previous != window && previous->wlSurface())
        g_pXWaylandManager->activateSurface(previous->wlSurface()->resource(), false);
    Desktop::focusState()->rawSurfaceFocus(root, window);
    changingKeyboardFocus = false;
    if (g_pSeatManager->m_state.keyboardFocus != root)
        interaction->keyboardFocused = false;
}

void restoreKeyboard(Interaction& previous, bool refocus) {
    if (!previous.keyboardFocused || !g_pSeatManager)
        return;
    changingKeyboardFocus = true;
    const auto root = previous.keyboardSurface.lock();
    const auto focused = g_pSeatManager->m_state.keyboardFocus.lock();
    const bool ownsFocus = root && focused && focused->client() == root->client();
    if (ownsFocus && keyboardSendHook) {
        using Original = void (*)(CSeatManager*, uint32_t, uint32_t, wl_keyboard_key_state);
        for (const auto key : previous.keys) {
            reinterpret_cast<Original>(keyboardSendHook->m_original)(g_pSeatManager.get(), eventTime(), key, WL_KEYBOARD_KEY_STATE_RELEASED);
            releasedKeys[key] = {previous.identity, root};
        }
        g_pSeatManager->sendKeyboardMods(0, 0, 0, 0);
    }
    if (root)
        g_pXWaylandManager->activateSurface(root, false);
    if (ownsFocus) {
        if (g_pSessionLockManager->isSessionLocked()) {
            // Leave an already focused lock surface untouched; never enter a
            // hidden application in order to clean up its input while locked.
            g_pSeatManager->setKeyboardFocus(nullptr);
        } else if (refocus) {
            const auto original = previous.previousWindow.lock();
            const auto surface = previous.previousSurface.lock();
            if (original && original->m_isMapped && original->m_workspace && original->m_workspace->isVisible())
                Desktop::focusState()->rawWindowFocus(original, Desktop::FOCUS_REASON_OTHER, surface);
            else if (surface && surface->m_hlSurface && surface->m_hlSurface->view() && surface->m_hlSurface->view()->visible())
                Desktop::focusState()->rawSurfaceFocus(surface);
            else
                Desktop::focusState()->rawWindowFocus(nullptr, Desktop::FOCUS_REASON_OTHER);
        }
    }
    changingKeyboardFocus = false;
}

void keyboardFocusChanged() {
    if (changingKeyboardFocus || !interaction || !interaction->keyboardFocused)
        return;
    const auto root = interaction->keyboardSurface.lock();
    const auto focus = g_pSeatManager->m_state.keyboardFocus.lock();
    if (root && focus && root->client() == focus->client())
        return;
    // An external focus change owns the seat now. It already received Wayland's
    // enter/held-key state; keep normal release bookkeeping for that transition.
    interaction->keyboardFocused = false;
    interaction->keys.clear();
    if (root)
        g_pXWaylandManager->activateSurface(root, false);
}

void keyboardEvent(const IKeyboard::SKeyEvent& event, Event::SCallbackInfo&) {
    if (event.state == WL_KEYBOARD_KEY_STATE_PRESSED)
        releasedKeys.erase(event.keycode);
    if (interaction)
        validateInteraction();
}

void rememberEnd(const std::string& owner, const std::string& id, const std::string& reason) {
    std::erase_if(endedInteractions, [&](const auto& ended) { return ended.owner == owner; });
    endedInteractions.push_back({owner, id, reason});
    while (endedInteractions.size() > 64)
        endedInteractions.pop_front();
}

void endInteraction(const std::string& reason, bool refocus) {
    if (!interaction)
        return;
    auto previous = std::move(*interaction);
    interaction.reset();
    rememberEnd(previous.owner, previous.identity.id, reason);
    restoreKeyboard(previous, refocus);
    if (g_pSeatManager) {
        const auto grabbed = previous.grab.lock();
        if (grabbed && !previous.buttons.empty()) {
            // Release to the exact grab surface, never to a replacement client.
            // A lockscreen that already owns focus must never be displaced.
            if (!g_pSessionLockManager->isSessionLocked())
                g_pSeatManager->setPointerFocus(grabbed, previous.lastLocal);
            if (g_pSeatManager->m_state.pointerFocus == grabbed) {
                for (const auto button : previous.buttons)
                    g_pSeatManager->sendPointerButton(eventTime(), button, WL_POINTER_BUTTON_STATE_RELEASED);
                g_pSeatManager->sendPointerFrame();
            }
        }
    }
    releasedButtons.insert(previous.buttons.begin(), previous.buttons.end());
    if (refocus && g_pInputManager && g_pSessionLockManager && !g_pSessionLockManager->isSessionLocked())
        g_pInputManager->refocus();
}

bool validateInteraction() {
    if (!interaction)
        return false;
    auto& current = *interaction;
    const auto window = current.identity.window.lock();
    const auto monitor = current.monitor.lock();
    const char* reason = nullptr;
    if (current.expires <= Clock::now())
        reason = "expired";
    else if (!window || !sameWindow(current.identity, window.get(), true))
        reason = "window-unavailable";
    else if (!window->wlSurface() || !window->wlSurface()->resource() || !window->wlSurface()->resource()->m_mapped)
        reason = "surface-unavailable";
    else if (g_pSessionLockManager->isSessionLocked())
        reason = "locked";
    else if (!g_pInputManager->m_exclusiveLSes.empty())
        reason = "exclusive-overlay";
    else if (!monitor || !State::monitorState()->contains(monitor) || !monitor->m_dpmsStatus)
        reason = "display-unavailable";
    else if (g_pInputManager->isConstrained())
        reason = "pointer-constrained";
    if (reason) {
        endInteraction(reason);
        return false;
    }
    return true;
}

bool managementHit(const Vector2D& global) {
    if (!interaction)
        return false;
    for (const auto& excluded : interaction->excludeRects)
        if (excluded.containsPoint(global))
            return true;
    return false;
}

bool contentHit(const Vector2D& global) {
    return interaction && interaction->rect.containsPoint(global) && !managementHit(global);
}

struct InputPoint {
    SP<CWLSurfaceResource> surface;
    Vector2D local;
    Vector2D root;
};

InputPoint inputPoint(const Vector2D& global) {
    if (!interaction)
        return {};
    const auto window = interaction->identity.window.lock();
    if (!window || !window->wlSurface() || !window->wlSurface()->resource())
        return {};
    const auto root = window->wlSurface()->resource();
    const auto size = window->size(Desktop::View::IGeometric::GEOMETRIC_CURRENT);
    if (size.x <= 0 || size.y <= 0)
        return {};
    Vector2D point = {(global.x - interaction->rect.x) * size.x / interaction->rect.w,
                      (global.y - interaction->rect.y) * size.y / interaction->rect.h};
    Vector2D rootPoint = point;
    if (window->m_xdgSurface)
        rootPoint += window->m_xdgSurface->m_current.geometry.pos();
    // The implicit grab keeps its exact surface until every button is released,
    // including when a text selection or slider leaves the miniature's bounds.
    if (!interaction->buttons.empty()) {
        const auto grabbed = interaction->grab.lock();
        return {grabbed, rootPoint - interaction->grabOffset, rootPoint};
    }
    if (window->m_popupHead) {
        const auto sourceGlobal = window->position(Desktop::View::IGeometric::GEOMETRIC_CURRENT) + point;
        if (const auto popup = window->m_popupHead->at(sourceGlobal, true)) {
            if (const auto surface = popup->resource()) {
                const auto found = surface->at(sourceGlobal - popup->coordsGlobal(), true);
                if (found.first)
                    return {found.first, found.second, rootPoint};
            }
        }
    }
    const auto found = root->at(rootPoint, true);
    return {found.first, found.second, rootPoint};
}

bool focusPoint(const Vector2D& global, uint32_t time) {
    const auto point = inputPoint(global);
    if (!point.surface)
        return false;
    g_pSeatManager->setPointerFocus(point.surface, point.local);
    g_pSeatManager->sendPointerMotion(time, point.local);
    interaction->lastLocal = point.local;
    interaction->lastGlobal = global;
    return true;
}

void mouseMove(const Vector2D& global, Event::SCallbackInfo& info) {
    if (!validateInteraction() || (!contentHit(global) && interaction->buttons.empty()))
        return;
    if (!focusPoint(global, eventTime())) {
        endInteraction("surface-unavailable");
        return;
    }
    g_pSeatManager->sendPointerFrame();
    ++interaction->motionEvents;
    info.cancelled = true;
}

void mouseButton(const IPointer::SButtonEvent& event, Event::SCallbackInfo& info) {
    if (event.state == WL_POINTER_BUTTON_STATE_RELEASED && releasedButtons.erase(event.button)) {
        info.cancelled = true;
        return;
    }
    if (!validateInteraction())
        return;
    const auto position = g_pInputManager->getMouseCoordsInternal();
    if (!contentHit(position) && interaction->buttons.empty()) {
        // These rectangles belong to our own management controls. Their Qt
        // press/release sequence must complete before the selected action ends
        // interaction; ending on press would change the button under the click.
        if (event.state == WL_POINTER_BUTTON_STATE_PRESSED && !managementHit(position))
            endInteraction("outside-click");
        return;
    }
    auto point = inputPoint(position);
    if (!point.surface) {
        endInteraction("surface-unavailable");
        return;
    }
    if (event.state == WL_POINTER_BUTTON_STATE_PRESSED) {
        if (interaction->buttons.size() >= 16)
            return;
        if (interaction->buttons.empty()) {
            interaction->grab = point.surface;
            interaction->grabOffset = point.root - point.local;
        }
        interaction->buttons.insert(event.button);
        if (interaction->keyboard && !interaction->keyboardFocused)
            acquireKeyboard();
    } else if (!interaction->buttons.contains(event.button)) {
        // A press that entered through another surface cannot be retargeted.
        return;
    }
    g_pSeatManager->setPointerFocus(point.surface, point.local);
    g_pSeatManager->sendPointerMotion(event.timeMs, point.local);
    interaction->lastLocal = point.local;
    interaction->lastGlobal = position;
    g_pSeatManager->sendPointerButton(event.timeMs, event.button, event.state);
    g_pSeatManager->sendPointerFrame();
    if (event.state == WL_POINTER_BUTTON_STATE_RELEASED) {
        interaction->buttons.erase(event.button);
        if (interaction->buttons.empty())
            interaction->grab.reset();
    }
    ++interaction->buttonEvents;
    info.cancelled = true;
}

void mouseAxis(const IPointer::SAxisEvent& event, Event::SCallbackInfo& info) {
    if (!validateInteraction())
        return;
    const auto position = g_pInputManager->getMouseCoordsInternal();
    if (!contentHit(position) && interaction->buttons.empty())
        return;
    const auto point = inputPoint(position);
    if (!point.surface)
        return;
    // A wheel frame is an axis frame, not a newly synthesized mouse movement.
    // Flush a changed focus before delivering its first axis; stable focus must
    // retain the same event ordering as the compositor's ordinary wheel path.
    if (g_pSeatManager->m_state.pointerFocus != point.surface) {
        g_pSeatManager->setPointerFocus(point.surface, point.local);
        g_pSeatManager->sendPointerMotion(event.timeMs, point.local);
        g_pSeatManager->sendPointerFrame();
    }
    interaction->lastLocal = point.local;
    interaction->lastGlobal = position;
    const auto discrete = event.deltaDiscrete == 0 ? 0 : (event.deltaDiscrete > 0 ? 1 : -1);
    interaction->lastAxisDelta = event.delta;
    interaction->lastAxisDiscrete = event.deltaDiscrete;
    interaction->lastAxisSource = event.source;
    g_pSeatManager->sendPointerAxis(event.timeMs, event.axis, event.delta, discrete, event.deltaDiscrete,
                                  event.source, event.relativeDirection);
    g_pSeatManager->sendPointerFrame();
    ++interaction->axisEvents;
    info.cancelled = true;
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
    if (validateInteraction()) {
        const auto window = interaction->identity.window.lock();
        active.emplace(window.get(), interaction->identity);
    }
    for (const auto& [window, identity] : previous)
        if (!active.contains(window))
            naturalSuspension(identity);
    for (const auto& [window, identity] : active)
        window->setSuspended(false);
    if (frameTimer) {
        const auto desired = interaction ? std::chrono::milliseconds((1000 + interaction->fps - 1) / interaction->fps) : FRAME_TIME;
        if (owners.empty() && !interaction)
            frameTimer->updateTimeout(std::nullopt);
        else if (!frameTimer->armed() || frameTimer->passed() || desired != frameInterval)
            frameTimer->updateTimeout(desired);
        frameInterval = desired;
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
void booleanField(lua_State* state, const char* name, bool value) {
    lua_pushboolean(state, value);
    lua_setfield(state, -2, name);
}
void numberField(lua_State* state, const char* name, double value) {
    lua_pushnumber(state, value);
    lua_setfield(state, -2, name);
}
double readNumber(lua_State* state, int table, const char* name) {
    lua_getfield(state, table, name);
    if (lua_type(state, -1) != LUA_TNUMBER)
        throw std::invalid_argument("Expected a numeric rectangle field");
    const auto value = lua_tonumber(state, -1);
    lua_pop(state, 1);
    if (!std::isfinite(value) || std::abs(value) > 1000000)
        throw std::invalid_argument("Invalid rectangle field");
    return value;
}
CBox readRect(lua_State* state, int table) {
    const int index = lua_absindex(state, table);
    if (lua_type(state, index) != LUA_TTABLE)
        throw std::invalid_argument("Expected a rectangle table");
    CBox rect{readNumber(state, index, "x"), readNumber(state, index, "y"),
              readNumber(state, index, "width"), readNumber(state, index, "height")};
    if (rect.w <= 0 || rect.h <= 0 || rect.w > 32768 || rect.h > 32768)
        throw std::invalid_argument("Invalid rectangle dimensions");
    return rect;
}
Identity readIdentity(lua_State* state, int table) {
    const int index = lua_absindex(state, table);
    if (lua_type(state, index) != LUA_TTABLE)
        throw std::invalid_argument("Expected a window identity table");
    Identity identity;
    identity.id = stringField(state, index, "id");
    identity.tag = stringField(state, index, "tag");
    identity.address = integerHex(stringField(state, index, "address"));
    identity.stable = integerHex(stringField(state, index, "stable_id"));
    if (!hexadecimal(identity.id, 32) || identity.tag != "window-stash-" + identity.id)
        throw std::invalid_argument("Invalid stash ownership identity");
    lua_getfield(state, index, "pid");
    if (!lua_isinteger(state, -1) || lua_tointeger(state, -1) < 1
        || lua_tointeger(state, -1) > std::numeric_limits<pid_t>::max())
        throw std::invalid_argument("Invalid window PID");
    identity.pid = lua_tointeger(state, -1);
    lua_pop(state, 1);
    for (const auto& window : Desktop::windowState()->windows()) {
        if (sameWindow(identity, window.get(), true)) {
            identity.window = window;
            return identity;
        }
    }
    throw std::invalid_argument("The interaction window is no longer owned and stashed");
}

void interactionDetails(lua_State* state, const std::string& owner) {
    lua_newtable(state);
    const bool matches = interaction && (owner.empty() || interaction->owner == owner);
    booleanField(state, "active", matches);
    booleanField(state, "keyboard", matches && interaction->keyboard);
    booleanField(state, "keyboardFocused", matches && interaction->keyboardFocused);
    field(state, "heldKeys", matches ? interaction->keys.size() : 0);
    field(state, "keyEvents", matches ? interaction->keyEvents : 0);
    if (matches) {
        field(state, "owner", interaction->owner);
        field(state, "id", interaction->identity.id);
        field(state, "reason", "active");
        field(state, "fps", interaction->fps);
        field(state, "heldButtons", interaction->buttons.size());
        field(state, "motionEvents", interaction->motionEvents);
        field(state, "buttonEvents", interaction->buttonEvents);
        field(state, "axisEvents", interaction->axisEvents);
        numberField(state, "lastAxisDelta", interaction->lastAxisDelta);
        field(state, "lastAxisDiscrete", interaction->lastAxisDiscrete);
        field(state, "lastAxisSource", interaction->lastAxisSource);
        lua_newtable(state);
        numberField(state, "x", interaction->lastLocal.x);
        numberField(state, "y", interaction->lastLocal.y);
        lua_setfield(state, -2, "lastLocal");
        lua_newtable(state);
        numberField(state, "x", interaction->lastGlobal.x);
        numberField(state, "y", interaction->lastGlobal.y);
        lua_setfield(state, -2, "lastGlobal");
        lua_newtable(state);
        numberField(state, "x", interaction->rect.x);
        numberField(state, "y", interaction->rect.y);
        numberField(state, "width", interaction->rect.w);
        numberField(state, "height", interaction->rect.h);
        lua_setfield(state, -2, "rect");
    } else {
        field(state, "owner", owner);
        field(state, "id", "");
        field(state, "reason", "inactive");
        field(state, "heldButtons", 0);
        for (auto it = endedInteractions.rbegin(); it != endedInteractions.rend(); ++it) {
            if ((!owner.empty() && it->owner == owner) || (owner.empty() && it == endedInteractions.rbegin())) {
                field(state, "owner", it->owner);
                field(state, "id", it->id);
                field(state, "reason", it->reason);
                break;
            }
        }
    }
}

int interactionStatus(lua_State* state) {
    try {
        const auto owner = lua_isnoneornil(state, 1) ? std::string{} : stringAt(state, 1);
        if (!owner.empty() && !hexadecimal(owner, 32))
            throw std::invalid_argument("Invalid interaction owner");
        synchronize();
        interactionDetails(state, owner);
        return 1;
    } catch (const std::exception& error) {
        lua_pushnil(state);
        lua_pushstring(state, error.what());
        return 2;
    }
}

int interactionUpdate(lua_State* state) {
    try {
        if (lua_type(state, 1) != LUA_TTABLE)
            throw std::invalid_argument("Expected an interaction lease table");
        const auto owner = stringField(state, 1, "owner");
        if (!hexadecimal(owner, 32))
            throw std::invalid_argument("Invalid interaction owner");
        synchronize();
        for (const auto& ended : endedInteractions) {
            if (ended.owner == owner) {
                interactionDetails(state, owner);
                return 1;
            }
        }
        if (interaction && interaction->owner != owner)
            throw std::invalid_argument("Another preview is already receiving input");
        lua_getfield(state, 1, "keyboard");
        if (!lua_isnil(state, -1) && lua_type(state, -1) != LUA_TBOOLEAN)
            throw std::invalid_argument("Expected a keyboard flag");
        const bool keyboard = lua_toboolean(state, -1);
        lua_pop(state, 1);
        if (keyboard && !keyboardSupported)
            throw std::invalid_argument("Keyboard interaction is unavailable: " + keyboardError);
        lua_getfield(state, 1, "window");
        auto identity = readIdentity(state, -1);
        lua_pop(state, 1);
        if (interaction && interaction->identity.id != identity.id)
            throw std::invalid_argument("Release the current window before switching interaction targets");
        if (interaction && interaction->keyboard != keyboard)
            throw std::invalid_argument("Release the current interaction before changing keyboard mode");
        const auto name = stringField(state, 1, "monitor");
        PHLMONITOR monitor;
        for (const auto& candidate : State::monitorState()->monitors())
            if (candidate->m_name == name)
                monitor = candidate;
        if (!monitor || !monitor->m_dpmsStatus || g_pSessionLockManager->isSessionLocked())
            throw std::invalid_argument("The interaction display is unavailable");
        lua_getfield(state, 1, "rect");
        const auto rect = readRect(state, -1);
        lua_pop(state, 1);
        if (rect.intersection(CBox{monitor->m_position, monitor->m_size}).empty())
            throw std::invalid_argument("The interaction rectangle is outside its display");
        std::vector<CBox> excluded;
        lua_getfield(state, 1, "excludeRects");
        if (!lua_isnil(state, -1)) {
            if (lua_type(state, -1) != LUA_TTABLE || lua_rawlen(state, -1) > 16)
                throw std::invalid_argument("Invalid interaction exclusions");
            for (size_t i = 1; i <= lua_rawlen(state, -1); ++i) {
                lua_rawgeti(state, -1, i);
                excluded.push_back(readRect(state, -1));
                lua_pop(state, 1);
            }
        }
        lua_pop(state, 1);
        lua_getfield(state, 1, "fps");
        if (!lua_isinteger(state, -1) || (lua_tointeger(state, -1) != 30 && lua_tointeger(state, -1) != 60))
            throw std::invalid_argument("Interaction FPS must be 30 or 60");
        const int fps = lua_tointeger(state, -1);
        lua_pop(state, 1);
        xkb_keysym_t exitSymbol = XKB_KEY_NoSymbol;
        uint32_t exitModifiers = 0;
        lua_getfield(state, 1, "exitShortcut");
        if (!lua_isnil(state, -1)) {
            if (!keybindHook)
                throw std::invalid_argument("The native exit shortcut is unavailable: " + keyboardError);
            if (lua_type(state, -1) != LUA_TTABLE)
                throw std::invalid_argument("Expected an exit shortcut table");
            const auto key = stringField(state, -1, "key");
            exitSymbol = xkb_keysym_from_name(key.c_str(), XKB_KEYSYM_CASE_INSENSITIVE);
            if (exitSymbol == XKB_KEY_NoSymbol || (exitSymbol >= XKB_KEY_Shift_L && exitSymbol <= XKB_KEY_Hyper_R))
                throw std::invalid_argument("Invalid exit shortcut key");
            lua_getfield(state, -1, "modmask");
            if (!lua_isinteger(state, -1) || lua_tointeger(state, -1) < 0 || (lua_tointeger(state, -1) & ~77LL))
                throw std::invalid_argument("Invalid exit shortcut modifiers");
            exitModifiers = lua_tointeger(state, -1);
            lua_pop(state, 1);
        }
        lua_pop(state, 1);
        if (!interaction)
            interaction.emplace();
        interaction->owner = owner;
        interaction->identity = std::move(identity);
        interaction->rect = rect;
        interaction->excludeRects = std::move(excluded);
        interaction->monitor = monitor;
        interaction->fps = fps;
        interaction->keyboard = keyboard;
        interaction->exitSymbol = exitSymbol;
        interaction->exitModifiers = exitModifiers;
        interaction->expires = Clock::now() + LEASE_TIME;
        synchronize();
        interactionDetails(state, owner);
        return 1;
    } catch (const std::exception& error) {
        lua_pushnil(state);
        lua_pushstring(state, error.what());
        return 2;
    }
}

int interactionRelease(lua_State* state) {
    try {
        const auto owner = stringAt(state, 1);
        if (!hexadecimal(owner, 32))
            throw std::invalid_argument("Invalid interaction owner");
        if (interaction && interaction->owner == owner)
            endInteraction("released");
        else if (std::none_of(endedInteractions.begin(), endedInteractions.end(), [&](const auto& ended) { return ended.owner == owner; }))
            rememberEnd(owner, "", "released");
        synchronize();
        lua_pushboolean(state, true);
        return 1;
    } catch (const std::exception& error) {
        lua_pushnil(state);
        lua_pushstring(state, error.what());
        return 2;
    }
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
    field(state, "frameInterval", frameInterval.count());
    field(state, "frames", frames);
    field(state, "preventedSuspends", preventedSuspends);
    lua_newtable(state);
    int ordinal = 1;
    for (const auto& [window, identity] : active) {
        lua_pushlstring(state, identity.id.data(), identity.id.size());
        lua_rawseti(state, -2, ordinal++);
    }
    lua_setfield(state, -2, "windowIds");
    interactionDetails(state);
    lua_setfield(state, -2, "interaction");
    lua_newtable(state);
    booleanField(state, "pointer", true);
    booleanField(state, "keyboard", keyboardSupported);
    booleanField(state, "exitShortcut", keybindHook != nullptr);
    field(state, "keyboardError", keyboardError);
    field(state, "interactionProtocol", 1);
    lua_setfield(state, -2, "capabilities");
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

CFunctionHook* optionalHook(const std::string& name, const std::string& demangledPrefix, const void* replacement) {
    const auto functions = HyprlandAPI::findFunctionsByName(handle, name);
    const SFunctionMatch* target = nullptr;
    for (const auto& function : functions) {
        if (function.demangled.starts_with(demangledPrefix)) {
            if (target)
                throw std::runtime_error("Ambiguous keyboard focus function: " + name);
            target = &function;
        }
    }
    if (!target)
        throw std::runtime_error("Missing keyboard focus function: " + name);
    auto* hook = HyprlandAPI::createFunctionHook(handle, target->address, replacement);
    if (!hook || !hook->hook())
        throw std::runtime_error("Could not install keyboard focus function: " + name);
    return hook;
}

void setupKeyboard() {
    try {
        // The active-session exit chord is useful in mouse-only mode too.
        keybindHook = optionalHook("onKeyEvent", "CKeybindManager::onKeyEvent(", reinterpret_cast<const void*>(&keybindEvent));
    } catch (const std::exception& error) {
        keyboardError = error.what();
        return;
    }
    try {
        focusWindowHook = optionalHook("window", "Desktop::CFocusState::window()", reinterpret_cast<const void*>(&focusedWindow));
        focusSurfaceHook = optionalHook("surface", "Desktop::CFocusState::surface()", reinterpret_cast<const void*>(&focusedSurface));
        keyboardSendHook = optionalHook("sendKeyboardKey", "CSeatManager::sendKeyboardKey(", reinterpret_cast<const void*>(&keyboardSend));
        keyboardSupported = true;
    } catch (const std::exception& error) {
        keyboardError = error.what();
        for (auto** hook : {&keyboardSendHook, &focusSurfaceHook, &focusWindowHook}) {
            if (*hook)
                HyprlandAPI::removeFunctionHook(handle, *hook);
            *hook = nullptr;
        }
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
        || !HyprlandAPI::addLuaFunction(handle, LUA_NAMESPACE, "status", status)
        || !HyprlandAPI::addLuaFunction(handle, LUA_NAMESPACE, "interaction_update", interactionUpdate)
        || !HyprlandAPI::addLuaFunction(handle, LUA_NAMESPACE, "interaction_release", interactionRelease)
        || !HyprlandAPI::addLuaFunction(handle, LUA_NAMESPACE, "interaction_status", interactionStatus))
        throw std::runtime_error("Could not register the preview lease API");
    mouseMoveListener = Event::bus()->m_events.input.mouse.move.listen(mouseMove);
    mouseButtonListener = Event::bus()->m_events.input.mouse.button.listen(mouseButton);
    mouseAxisListener = Event::bus()->m_events.input.mouse.axis.listen(mouseAxis);
    setupKeyboard();
    keyboardFocusListener = g_pSeatManager->m_events.keyboardFocusChange.listen(keyboardFocusChanged);
    keyboardEventListener = Event::bus()->m_events.input.keyboard.key.listen(keyboardEvent);
    lockListener = g_pSessionLockManager->m_events.lock.listen([] { endInteraction("locked", false); });
    monitorListener = Event::bus()->m_events.monitor.layoutChanged.listen([] { endInteraction("display-changed"); });
    workspaceListener = Event::bus()->m_events.workspace.active.listen([](PHLWORKSPACE) { endInteraction("workspace-changed"); });
    frameTimer = makeShared<CEventLoopTimer>(std::nullopt,
        [](SP<CEventLoopTimer>, void*) { frame(); }, nullptr);
    g_pEventLoopManager->addTimer(frameTimer);
    return {"window-stash-preview", "Scoped rendering for visible Window Stash live previews", "artu-ole", STASH_BRIDGE_VERSION};
}

APICALL EXPORT void PLUGIN_EXIT() {
    endInteraction("unloaded");
    mouseMoveListener.reset();
    mouseButtonListener.reset();
    mouseAxisListener.reset();
    keyboardFocusListener.reset();
    keyboardEventListener.reset();
    lockListener.reset();
    monitorListener.reset();
    workspaceListener.reset();
    owners.clear();
    synchronize();
    if (frameTimer) {
        frameTimer->cancel();
        g_pEventLoopManager->removeTimer(frameTimer);
        frameTimer.reset();
    }
    // Hyprland removes the hook and Lua callbacks after this function returns.
}
