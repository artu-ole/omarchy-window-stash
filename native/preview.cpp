// SPDX-License-Identifier: AGPL-3.0-only
// Optional, session-local bridge for live captures of parked windows.
#include <hyprland/src/plugins/PluginAPI.hpp>
#include <hyprland/src/config/shared/actions/ConfigActions.hpp>
#include <hyprland/src/desktop/Workspace.hpp>
#include <hyprland/src/desktop/state/WindowState.hpp>
#include <hyprland/src/desktop/state/FocusState.hpp>
#include <hyprland/src/desktop/state/GlobalWindowController.hpp>
#include <hyprland/src/desktop/view/Window.hpp>
#include <hyprland/src/desktop/view/WLSurface.hpp>
#include <hyprland/src/desktop/view/Popup.hpp>
#include <hyprland/src/event/EventBus.hpp>
#include <hyprland/src/managers/SeatManager.hpp>
#include <hyprland/src/managers/KeybindManager.hpp>
#include <hyprland/src/managers/EventManager.hpp>
#include <hyprland/src/managers/XWaylandManager.hpp>
#include <hyprland/src/managers/fullscreen/FullscreenController.hpp>
#include <hyprland/src/layout/LayoutManager.hpp>
#include <hyprland/src/managers/SessionLockManager.hpp>
#include <hyprland/src/managers/input/InputManager.hpp>
#include <hyprland/src/managers/eventLoop/EventLoopManager.hpp>
#include <hyprland/src/output/Monitor.hpp>
#include <hyprland/src/protocols/XDGShell.hpp>
#include <hyprland/src/protocols/PointerConstraints.hpp>
#include <hyprland/src/protocols/core/Compositor.hpp>
#include <hyprland/src/render/Renderer.hpp>
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
#include <dlfcn.h>
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
#ifndef STASH_BRIDGE_FINGERPRINT
#define STASH_BRIDGE_FINGERPRINT "development"
#endif

namespace {
using Desktop::View::CWindow;
using Clock = std::chrono::steady_clock;
constexpr auto LEASE_TIME = std::chrono::milliseconds(2500);
constexpr auto HANDOFF_TIME = std::chrono::seconds(5);
constexpr auto FRAME_TIME = std::chrono::milliseconds(66);
constexpr auto WORKSPACE = "special:window-stash";
constexpr auto LUA_NAMESPACE = "window_stash_preview";
constexpr size_t MAX_OWNERS = 32;
constexpr size_t MAX_WINDOWS = 256;
constexpr unsigned POINTER_ACTIVATION_CREDITS = 2;

struct Identity {
    std::string id;
    std::string tag;
    uintptr_t address = 0;
    pid_t pid = 0;
    uint64_t stable = 0;
    PHLWINDOWREF window;
};
struct SourceGeometry {
    bool ready = false;
    bool xwayland = false;
    Vector2D size{};
    Vector2D configured{};
    Vector2D surface{};
    std::string reason;
};
struct Lease {
    Clock::time_point expires;
    std::vector<Identity> windows;
};
struct DesktopFullscreenRequest {
    std::optional<Fullscreen::eFullscreenMode> internal;
    std::optional<Fullscreen::eFullscreenMode> client;
    std::optional<bool> layoutAware;
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
    std::vector<Identity> pendingChildren;
    std::set<uint64_t> initialWindows;
    bool constrainFullscreen = true;
    Clock::time_point pointerActivationDeadline{};
    unsigned pointerActivationAllowance = 0;
    std::string activationOrigin;
    uint64_t clientActivationEvents = 0;
    uint64_t keyboardActivationAcknowledgements = 0;
    uint64_t pointerActivationAcknowledgements = 0;
    uint64_t fullscreenActivationAcknowledgements = 0;
    std::optional<DesktopFullscreenRequest> desktopFullscreen;
};
struct ConstrainedFullscreen {
    Identity identity;
    Fullscreen::eFullscreenMode originalClient = Fullscreen::FSMODE_NONE;
    Fullscreen::eFullscreenMode client = Fullscreen::FSMODE_NONE;
    Clock::time_point restoreRequested{};
};
enum class FullscreenResize { None, Exit, Nudge, Restore };
struct FullscreenTransition {
    Identity identity;
    Fullscreen::eFullscreenMode client = Fullscreen::FSMODE_NONE;
    Clock::time_point expires;
    Clock::time_point restoreRequested;
    unsigned activationAllowance = 1;
    bool waitingAck = false;
    uint32_t configureSerial = 0;
    bool maximizeFollowupHandled = false;
    CHyprSignalListener ackListener{};
    FullscreenResize resize = FullscreenResize::None;
    Vector2D clientSize{};
    Vector2D windowSize{};
};
struct EndedInteraction {
    std::string owner;
    std::string id;
    std::string reason;
    Identity source;
    std::vector<Identity> children;
    std::set<uint64_t> initialWindows;
    PHLWINDOWREF previousWindow;
    WP<CWLSurfaceResource> previousSurface;
    bool restoreRequested = false;
    bool handedOff = false;
    bool constrainFullscreen = true;
    std::string activationOrigin;
    unsigned pointerActivationAllowance = 0;
    int64_t pointerActivationRemainingMs = 0;
    uint64_t clientActivationEvents = 0;
    uint64_t keyboardActivationAcknowledgements = 0;
    uint64_t pointerActivationAcknowledgements = 0;
    uint64_t fullscreenActivationAcknowledgements = 0;
    std::optional<DesktopFullscreenRequest> desktopFullscreen;
    Clock::time_point handoffDeadline;
};

HANDLE handle = nullptr;
CFunctionHook* suspendHook = nullptr;
CFunctionHook* focusWindowHook = nullptr;
CFunctionHook* focusSurfaceHook = nullptr;
CFunctionHook* keyboardSendHook = nullptr;
CFunctionHook* keybindHook = nullptr;
CFunctionHook* renderWindowHook = nullptr;
CFunctionHook* popupVisibleHook = nullptr;
CFunctionHook* rawFocusHook = nullptr;
CFunctionHook* dispatchFocusHook = nullptr;
CFunctionHook* windowActivateHook = nullptr;
CFunctionHook* warpCursorHook = nullptr;
CFunctionHook* constraintActivateHook = nullptr;
CFunctionHook* fullscreenModeHook = nullptr;
CFunctionHook* fullscreenActionHook = nullptr;
CFunctionHook* moveWorkspaceHook = nullptr;
void* clientFullscreenFunction = nullptr;
bool constrainedFullscreenSupported = false;
std::string fullscreenError;
std::unordered_map<std::string, ConstrainedFullscreen> fullscreenWindows;
std::unordered_map<std::string, FullscreenTransition> fullscreenTransitions;
bool handoffSupported = false;
bool endingInteraction = false;
bool reloadPending = false;
std::string modulePath;
bool popupsSupported = false;
CWindow* captureWindow = nullptr;
uint64_t popupFrames = 0;
std::unordered_map<CWindow*, Clock::time_point> lastFeedback;
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
CHyprSignalListener windowOpenListener, fullscreenListener;
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
bool restoreReason(const std::string& reason);
void dismissPopups(const Identity& identity);
void restoreVisibleFocus(const PHLWINDOWREF& previousWindow, const WP<CWLSurfaceResource>& previousSurface);
void requestRestore(const std::string& reason, const PHLWINDOW& child = nullptr);
bool grabbedPopupOutside(const PHLWINDOW& window);
bool sourceHasConstraint(const Identity& identity);
PHLWINDOW keyboardWindow();
bool contentHit(const Vector2D& global);
bool clearConstrainedFullscreen(std::string id);
void clearAllConstrainedFullscreen();
void synchronizeConstrainedFullscreen();

bool currentOwner(const std::string& owner) {
    return interaction && interaction->owner == owner && !endingInteraction;
}

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

bool fullscreenTarget(const PHLWINDOW& window) {
    if (!constrainedFullscreenSupported || reloadPending || !window)
        return false;
    if (interaction && !endingInteraction && interaction->constrainFullscreen
        && sameWindow(interaction->identity, window.get(), true)
        && !window->m_ruleApplicator->noScreenShare().valueOrDefault())
        return true;
    return std::any_of(fullscreenWindows.begin(), fullscreenWindows.end(), [&](const auto& item) {
        return sameWindow(item.second.identity, window.get(), true)
            && !window->m_ruleApplicator->noScreenShare().valueOrDefault();
    });
}

void trackFullscreenConfigure(const std::string& id, const PHLWINDOW& window) {
    const auto found = fullscreenTransitions.find(id);
    if (found == fullscreenTransitions.end() || !window->m_xdgSurface)
        return;
    const auto identity = found->second.identity;
    const auto serial = window->m_xdgSurface->scheduleConfigure();
    found->second.waitingAck = true;
    found->second.configureSerial = serial;
    found->second.ackListener = window->m_xdgSurface->m_events.ack.listen([id, identity, serial](uint32_t acknowledged) {
        const auto current = fullscreenTransitions.find(id);
        if (current == fullscreenTransitions.end() || !current->second.waitingAck || current->second.configureSerial != serial
            || current->second.identity.stable != identity.stable || current->second.identity.address != identity.address
            || static_cast<int32_t>(acknowledged - serial) < 0)
            return;
        current->second.waitingAck = false;
        current->second.expires = Clock::now() + std::chrono::seconds(1);
    });
}

void cancelFullscreenResize(const PHLWINDOW& window) {
    const auto found = std::find_if(fullscreenTransitions.begin(), fullscreenTransitions.end(), [&](const auto& item) {
        return item.second.resize != FullscreenResize::None && sameWindow(item.second.identity, window.get(), false);
    });
    if (found == fullscreenTransitions.end())
        return;
    const auto id = found->first;
    found->second.resize = FullscreenResize::None;
    // Public workspace moves or a new fullscreen request own the next size.
    // Reassert the compositor's ordinary size before relinquishing our nudge.
    window->sendWindowSize(true);
    trackFullscreenConfigure(id, window);
}

void synchronizeFullscreenResizes() {
    std::vector<std::string> ids;
    for (const auto& [id, value] : fullscreenTransitions)
        if (value.resize != FullscreenResize::None)
            ids.push_back(id);
    for (const auto& id : ids) {
        const auto found = fullscreenTransitions.find(id);
        if (found == fullscreenTransitions.end())
            continue;
        const auto identity = found->second.identity;
        const auto windowSize = found->second.windowSize;
        const auto clientSize = found->second.clientSize;
        const auto phase = found->second.resize;
        const auto window = identity.window.lock();
        if (!window || !sameWindow(identity, window.get(), false))
            continue;
        if (!sameWindow(identity, window.get(), true)) {
            // A removed stash tag relinquishes ownership, but this exact
            // original window must not retain our temporary client height.
            cancelFullscreenResize(window);
            continue;
        }
        if (found->second.waitingAck || !window->m_xdgSurface || !window->m_xdgSurface->m_toplevel)
            continue;
        if (window->sizeAnimation()->goal() != windowSize) {
            cancelFullscreenResize(window);
            continue;
        }
        if (phase == FullscreenResize::Restore) {
            found->second.resize = FullscreenResize::None;
            continue;
        }
        const bool nudge = phase == FullscreenResize::Exit;
        found->second.resize = nudge ? FullscreenResize::Nudge : FullscreenResize::Restore;
        // Chromium expects a content resize when leaving tab fullscreen and
        // otherwise defers its renderer's exit indefinitely at identical bounds.
        // A single acknowledged client-only height step supplies that resize;
        // compositor geometry, source width and the miniature remain unchanged.
        window->m_xdgSurface->m_toplevel->setSize(clientSize + Vector2D{0.0, nudge ? 1.0 : 0.0});
        trackFullscreenConfigure(id, window);
    }
}

void setClientFullscreen(const PHLWINDOW& window, Fullscreen::eFullscreenMode mode) {
    using Original = void (*)(Fullscreen::CFullscreenController*, PHLWINDOW, Fullscreen::eFullscreenMode, bool);
    const auto previous = Fullscreen::controller()->getFullscreenModes(window).client;
    if (mode == Fullscreen::FSMODE_FULLSCREEN)
        cancelFullscreenResize(window);
    if (previous != mode && previous != Fullscreen::FSMODE_FULLSCREEN && mode == Fullscreen::FSMODE_MAXIMIZED) {
        const auto found = std::find_if(fullscreenTransitions.begin(), fullscreenTransitions.end(), [&](const auto& item) {
            return item.second.client != Fullscreen::FSMODE_FULLSCREEN && !item.second.maximizeFollowupHandled
                && (item.second.waitingAck || item.second.expires > Clock::now())
                && sameWindow(item.second.identity, window.get(), true);
        });
        if (found != fullscreenTransitions.end()) {
            // Chromium restores its pre-fullscreen maximized client state in
            // a following request. Track that one configure as the same exit,
            // without letting further state traffic renew this grace forever.
            found->second.client = mode;
            found->second.maximizeFollowupHandled = true;
            found->second.activationAllowance = 1;
        }
    }
    if (previous != mode && (previous == Fullscreen::FSMODE_FULLSCREEN || mode == Fullscreen::FSMODE_FULLSCREEN)
        && interaction && !endingInteraction && !reloadPending && interaction->constrainFullscreen
        && sameWindow(interaction->identity, window.get(), true)
        && (keyboardWindow() == window || contentHit(g_pInputManager->getMouseCoordsInternal()))) {
        // Browser fullscreen entry/exit can issue a new xdg-activation token.
        // Attribute one acknowledgement to this exact, recent input transition;
        // never grant a lasting activation exemption to a passive miniature.
        std::erase_if(fullscreenTransitions, [](const auto& item) {
            return !item.second.waitingAck && item.second.resize == FullscreenResize::None && item.second.expires <= Clock::now();
        });
        if (fullscreenTransitions.size() < MAX_WINDOWS || fullscreenTransitions.contains(interaction->identity.id))
            fullscreenTransitions[interaction->identity.id] = {interaction->identity, mode, Clock::now() + std::chrono::seconds(1), {}, 1};
    }
    // Call only the client-state setter. The public setter synchronizes client
    // and internal modes by default, resizing/recentering even when given NONE.
    reinterpret_cast<Original>(clientFullscreenFunction)(Fullscreen::controller().get(), window, mode, false);
    if (previous != mode)
        window->m_ruleApplicator->propertiesChanged(Desktop::Rule::RULE_PROP_FULLSCREENSTATE_CLIENT);
    window->sendWindowSize(true);
    if (window->m_xdgSurface && window->m_xdgSurface->m_toplevel)
        window->m_xdgSurface->m_toplevel->setMaximized(mode == Fullscreen::FSMODE_MAXIMIZED);
    if (previous != mode && window->m_xdgSurface) {
        const auto found = std::find_if(fullscreenTransitions.begin(), fullscreenTransitions.end(), [&](const auto& item) {
            return item.second.client == mode && sameWindow(item.second.identity, window.get(), true);
        });
        if (found != fullscreenTransitions.end()) {
            const auto id = found->first;
            if (previous == Fullscreen::FSMODE_FULLSCREEN && mode != Fullscreen::FSMODE_FULLSCREEN
                && window->m_xdgSurface->m_toplevel) {
                const auto size = window->m_xdgSurface->m_toplevel->m_pendingApply.size;
                if (size.x >= 1 && size.y >= 1 && size.y < 32768) {
                    found->second.resize = FullscreenResize::Exit;
                    found->second.clientSize = size;
                    found->second.windowSize = window->sizeAnimation()->goal();
                }
            }
            trackFullscreenConfigure(id, window);
        }
    }
    g_pHyprRenderer->damageWindow(window, true);
}

bool clearConstrainedFullscreen(std::string id) {
    const auto found = fullscreenWindows.find(id);
    if (found == fullscreenWindows.end())
        return false;
    const auto previous = found->second;
    fullscreenWindows.erase(found);
    const auto window = previous.identity.window.lock();
    if (clientFullscreenFunction && window && sameWindow(previous.identity, window.get(), false)) {
        const auto modes = Fullscreen::controller()->getFullscreenModes(window);
        if (modes.internal == Fullscreen::FSMODE_NONE && modes.client == previous.client) {
            if (previous.client == Fullscreen::FSMODE_FULLSCREEN && sameWindow(previous.identity, window.get(), true)) {
                std::erase_if(fullscreenTransitions, [](const auto& item) {
                    return !item.second.waitingAck && item.second.resize == FullscreenResize::None && item.second.expires <= Clock::now();
                });
                if (fullscreenTransitions.size() < MAX_WINDOWS)
                    fullscreenTransitions[id] = {previous.identity, previous.originalClient, Clock::now() + std::chrono::seconds(1), {}, 1};
            } else if (const auto transition = fullscreenTransitions.find(id); transition != fullscreenTransitions.end()
                       && (transition->second.waitingAck || transition->second.expires > Clock::now())) {
                transition->second.client = previous.originalClient;
            }
            setClientFullscreen(window, previous.originalClient);
        }
    }
    return true;
}

void clearAllConstrainedFullscreen() {
    std::vector<std::string> ids;
    ids.reserve(fullscreenWindows.size());
    for (const auto& [id, value] : fullscreenWindows)
        ids.push_back(id);
    for (const auto& id : ids)
        clearConstrainedFullscreen(id);
}

void synchronizeConstrainedFullscreen() {
    std::vector<std::string> stale;
    for (const auto& [id, value] : fullscreenWindows) {
        const auto window = value.identity.window.lock();
        if (!window || !sameWindow(value.identity, window.get(), true)
            || window->m_ruleApplicator->noScreenShare().valueOrDefault())
            stale.push_back(id);
    }
    for (const auto& id : stale)
        clearConstrainedFullscreen(id);
    synchronizeFullscreenResizes();
    std::erase_if(fullscreenTransitions, [](const auto& item) {
        const auto window = item.second.identity.window.lock();
        return (!item.second.waitingAck && item.second.resize == FullscreenResize::None && item.second.expires <= Clock::now())
            || !window || !sameWindow(item.second.identity, window.get(), true);
    });
}

bool applyConstrainedFullscreen(const PHLWINDOW& window, Fullscreen::eFullscreenMode mode) {
    if (!fullscreenTarget(window))
        return false;
    mode = std::clamp(mode, Fullscreen::FSMODE_NONE, Fullscreen::FSMODE_FULLSCREEN);
    const auto modes = Fullscreen::controller()->getFullscreenModes(window);
    auto found = std::find_if(fullscreenWindows.begin(), fullscreenWindows.end(), [&](const auto& item) {
        return sameWindow(item.second.identity, window.get(), true);
    });
    if (modes.internal != Fullscreen::FSMODE_NONE)
        return false;
    if (mode == Fullscreen::FSMODE_NONE && found != fullscreenWindows.end()) {
        clearConstrainedFullscreen(found->first);
        return true;
    }
    if (found == fullscreenWindows.end()) {
        if (mode == modes.client) {
            setClientFullscreen(window, mode);
            return true;
        }
        if (!interaction || !sameWindow(interaction->identity, window.get(), true) || fullscreenWindows.size() >= MAX_WINDOWS)
            return false;
        ConstrainedFullscreen value{interaction->identity, modes.client, mode};
        const auto id = value.identity.id;
        found = fullscreenWindows.emplace(id, std::move(value)).first;
    } else
        found->second.client = mode;
    setClientFullscreen(window, mode);
    return true;
}

bool consumePassiveMaximizeEcho(const PHLWINDOW& window) {
    const auto found = std::find_if(fullscreenTransitions.begin(), fullscreenTransitions.end(), [&](const auto& item) {
        return item.second.client == Fullscreen::FSMODE_NONE && !item.second.maximizeFollowupHandled
            && (item.second.waitingAck || item.second.resize != FullscreenResize::None || item.second.expires > Clock::now())
            && sameWindow(item.second.identity, window.get(), true);
    });
    if (found == fullscreenTransitions.end())
        return false;
    // The app can leave passive picture-in-picture without an input helper.
    // Keep its one following restore-maximized echo out of the real layout,
    // just as the compositor suppresses that echo when leaving tiled fullscreen.
    found->second.maximizeFollowupHandled = true;
    return true;
}

void setFullscreenMode(Fullscreen::CFullscreenController* controller, PHLWINDOW window,
                       std::optional<Fullscreen::eFullscreenMode> internal,
                       std::optional<Fullscreen::eFullscreenMode> client, std::optional<bool> layoutAware) {
    if (reloadPending && window && std::any_of(fullscreenTransitions.begin(), fullscreenTransitions.end(), [&](const auto& item) {
        return sameWindow(item.second.identity, window.get(), true);
    }))
        return; // Do not turn an application's cleanup echo into real fullscreen.
    if (window && interaction && !endingInteraction && !interaction->constrainFullscreen
        && sameWindow(interaction->identity, window.get(), true)
        && client.value_or(internal.value_or(Fullscreen::FSMODE_NONE)) != Fullscreen::FSMODE_NONE) {
        // Restoring an already-fullscreen hidden browser would briefly send
        // fullscreen=false for geometry, which cancels video DOM fullscreen.
        // Restore its ordinary window first, then apply this exact request once
        // the existing controller handoff verifies a public destination.
        interaction->desktopFullscreen = DesktopFullscreenRequest{internal, client, layoutAware};
        requestRestore("source-fullscreen");
        return;
    }
    if (window) {
        const auto pending = std::find_if(endedInteractions.begin(), endedInteractions.end(), [&](const auto& item) {
            return item.restoreRequested && !item.handedOff && item.desktopFullscreen && item.handoffDeadline > Clock::now()
                && sameWindow(item.source, window.get(), false);
        });
        if (pending != endedInteractions.end()) {
            // Coalesce duplicate requests (including an app cancelling its own
            // request) without exposing or resizing the private source. Explicit
            // internal/client pairs belong to restoration/layout maintenance;
            // they must not replace the app's saved fullscreen intent.
            if (!internal.has_value() && client.has_value())
                pending->desktopFullscreen = DesktopFullscreenRequest{internal, client, layoutAware};
            return;
        }
    }
    if (window && !internal.has_value() && client == Fullscreen::FSMODE_MAXIMIZED && window->m_xdgSurface
        && window->m_xdgSurface->m_toplevel && window->m_xdgSurface->m_toplevel->m_state.requestsMaximize == true
        && (!interaction || !interaction->constrainFullscreen || !sameWindow(interaction->identity, window.get(), true))
        && consumePassiveMaximizeEcho(window))
        return;
    if (window && !internal.has_value() && client == Fullscreen::FSMODE_NONE && window->m_xdgSurface
        && window->m_xdgSurface->m_toplevel && window->m_xdgSurface->m_toplevel->m_state.requestsMaximize == true
        && controller->getFullscreenModes(window).client == Fullscreen::FSMODE_MAXIMIZED) {
        const auto found = std::find_if(fullscreenTransitions.begin(), fullscreenTransitions.end(), [&](const auto& item) {
            return item.second.client == Fullscreen::FSMODE_MAXIMIZED && !item.second.maximizeFollowupHandled
                && (item.second.waitingAck || item.second.expires > Clock::now())
                && sameWindow(item.second.identity, window.get(), true);
        });
        if (found != fullscreenTransitions.end()) {
            // onUpdateState treats a set_maximized echo as a toggle when the
            // saved client state was already maximized. Acknowledge that one
            // restore request instead of incorrectly configuring it normal.
            found->second.maximizeFollowupHandled = true;
            found->second.activationAllowance = 1;
            setClientFullscreen(window, Fullscreen::FSMODE_MAXIMIZED);
            return;
        }
    }
    if (fullscreenTarget(window)) {
        const auto modes = controller->getFullscreenModes(window);
        if (!applyConstrainedFullscreen(window, client.value_or(internal.value_or(modes.client))))
            endInteraction("fullscreen-unavailable");
        // Containment failure must not fall through to the real compositor
        // fullscreen path and expose or resize an owned hidden source.
        return;
    }
    if (window && !(interaction && !interaction->constrainFullscreen && sameWindow(interaction->identity, window.get(), true))
        && std::any_of(fullscreenTransitions.begin(), fullscreenTransitions.end(), [&](const auto& item) {
            return item.second.resize != FullscreenResize::None && sameWindow(item.second.identity, window.get(), true);
        }))
        return; // A passive cleanup request must not acquire real layout fullscreen.
    using Original = void (*)(Fullscreen::CFullscreenController*, PHLWINDOW, std::optional<Fullscreen::eFullscreenMode>,
                              std::optional<Fullscreen::eFullscreenMode>, std::optional<bool>);
    if (window)
        cancelFullscreenResize(window);
    reinterpret_cast<Original>(fullscreenModeHook->m_original)(controller, window, internal, client, layoutAware);
}

Config::Actions::ActionResult fullscreenWindow(Fullscreen::eFullscreenMode mode, bool layoutAware, std::optional<PHLWINDOW> requested) {
    const auto window = requested.value_or(Desktop::focusState()->window());
    if (fullscreenTarget(window)) {
        // Stock fullscreen bindings toggle against the internal mode. It stays
        // NONE here, so use the client mode for this one exact hidden source.
        const auto current = Fullscreen::controller()->getFullscreenModes(window).client;
        if (!applyConstrainedFullscreen(window, current == mode ? Fullscreen::FSMODE_NONE : mode))
            endInteraction("fullscreen-unavailable");
        return {};
    }
    using Original = Config::Actions::ActionResult (*)(Fullscreen::eFullscreenMode, bool, std::optional<PHLWINDOW>);
    return reinterpret_cast<Original>(fullscreenActionHook->m_original)(mode, layoutAware, requested);
}

void moveWindowToWorkspace(const Desktop::CGlobalWindowController* controller, PHLWINDOW window, PHLWORKSPACE workspace) {
    if (window && workspace && workspace->m_name != WORKSPACE) {
        cancelFullscreenResize(window);
        const auto found = std::find_if(fullscreenWindows.begin(), fullscreenWindows.end(), [&](const auto& item) {
            return sameWindow(item.second.identity, window.get(), false);
        });
        if (found != fullscreenWindows.end())
            clearConstrainedFullscreen(found->first);
        cancelFullscreenResize(window);
    }
    using Original = void (*)(const Desktop::CGlobalWindowController*, PHLWINDOW, PHLWORKSPACE);
    reinterpret_cast<Original>(moveWorkspaceHook->m_original)(controller, window, workspace);
}

bool leased(CWindow* window) {
    const auto it = active.find(window);
    return it != active.end() && it->second.window.lock().get() == window && sameWindow(it->second, window, true);
}

uint32_t eventTime() {
    return static_cast<uint32_t>(std::chrono::duration_cast<std::chrono::milliseconds>(Clock::now().time_since_epoch()).count());
}

bool surfaceOwnedBy(const Identity& identity, const SP<CWLSurfaceResource>& surface) {
    const auto window = identity.window.lock();
    if (!surface || !window || !sameWindow(identity, window.get(), false) || !window->wlSurface())
        return false;
    const auto root = window->wlSurface()->resource();
    if (!root)
        return false;
    if (surface == root)
        return true;
    bool found = false;
    root->breadthfirst([&](SP<CWLSurfaceResource> candidate, const Vector2D&, void*) {
        found = found || candidate == surface;
    }, nullptr);
    if (!found && window->m_popupHead) {
        window->m_popupHead->breadthfirst([&](SP<Desktop::View::CPopup> popup, void*) {
            if (found || !popup || !popup->wlSurface() || !popup->wlSurface()->resource())
                return;
            popup->wlSurface()->resource()->breadthfirst([&](SP<CWLSurfaceResource> candidate, const Vector2D&, void*) {
                found = found || candidate == surface;
            }, nullptr);
        }, nullptr);
    }
    return found;
}

bool sourceHasConstraint(const Identity& identity) {
    // InputManager removes spent one-shot constraints from this list. Checking
    // the live list avoids mistaking their surviving protocol objects for a
    // pointer lock that could activate when the source receives keyboard focus.
    for (const auto& weak : g_pInputManager->m_constraints) {
        const auto constraint = weak.lock();
        const auto owner = constraint ? constraint->owner() : nullptr;
        if (owner && surfaceOwnedBy(identity, owner->resource()))
            return true;
    }
    return false;
}

PHLWINDOW keyboardWindow() {
    if (!interaction || !interaction->keyboardFocused)
        return nullptr;
    const auto window = interaction->identity.window.lock();
    return window && sameWindow(interaction->identity, window.get(), true)
        && surfaceOwnedBy(interaction->identity, g_pSeatManager->m_state.keyboardFocus.lock()) ? window : nullptr;
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
        return surfaceOwnedBy(interaction->identity, focused) ? focused : root;
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
        if (surfaceOwnedBy(interaction->identity, focus)) {
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
    struct ReleaseScope {
        std::optional<ReleasedKey> previous;
        ~ReleaseScope() { releaseTarget = std::move(previous); }
    } releaseScope{releaseTarget};
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
    return reinterpret_cast<Original>(keybindHook->m_original)(manager, std::move(data), keyboard);
}

void acquireKeyboard() {
    if (!interaction || !interaction->keyboard || interaction->keyboardFocused || !keyboardSupported)
        return;
    const auto window = interaction->identity.window.lock();
    if (!window || !sameWindow(interaction->identity, window.get(), true) || !g_pSeatManager->m_keyboard)
        return;
    if (sourceHasConstraint(interaction->identity)) {
        endInteraction("pointer-constrained");
        return;
    }
    if (g_pSessionLockManager->isSessionLocked() || !g_pInputManager->m_exclusiveLSes.empty())
        return;
    const auto owner = interaction->owner;
    const auto root = window->wlSurface()->resource();
    if (!surfaceOwnedBy(interaction->identity, g_pSeatManager->m_state.keyboardFocus.lock())) {
        interaction->previousWindow = Desktop::focusState()->window();
        interaction->previousSurface = g_pSeatManager->m_state.keyboardFocus;
    }
    interaction->keyboardSurface = root;
    interaction->keyboardFocused = true;
    changingKeyboardFocus = true;
    if (const auto previous = interaction->previousWindow.lock(); previous && previous != window && previous->wlSurface())
        g_pXWaylandManager->activateSurface(previous->wlSurface()->resource(), false);
    Desktop::focusState()->rawSurfaceFocus(root, window);
    changingKeyboardFocus = false;
    if (currentOwner(owner) && g_pSeatManager->m_state.keyboardFocus != root)
        interaction->keyboardFocused = false;
}

void restoreKeyboard(Interaction& previous, bool refocus) {
    if (!g_pSeatManager)
        return;
    changingKeyboardFocus = true;
    const auto root = previous.keyboardSurface.lock();
    const auto focused = g_pSeatManager->m_state.keyboardFocus.lock();
    const bool ownsFocus = surfaceOwnedBy(previous.identity, focused);
    if (!previous.keyboardFocused && !ownsFocus) {
        changingKeyboardFocus = false;
        return;
    }
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
        } else if (refocus)
            restoreVisibleFocus(previous.previousWindow, previous.previousSurface);
    }
    changingKeyboardFocus = false;
}

void keyboardFocusChanged() {
    if (changingKeyboardFocus || !interaction)
        return;
    const auto root = interaction->keyboardSurface.lock();
    const auto focus = g_pSeatManager->m_state.keyboardFocus.lock();
    if (!interaction->keyboard || !interaction->keyboardFocused) {
        // An application popup grab must not silently opt a mouse-only card in
        // to keyboard input. Its pointer events remain scoped to the popup tree.
        if (surfaceOwnedBy(interaction->identity, focus)) {
            changingKeyboardFocus = true;
            if (const auto previous = interaction->previousSurface.lock())
                g_pSeatManager->setKeyboardFocus(previous);
            else
                g_pSeatManager->setKeyboardFocus(nullptr);
            changingKeyboardFocus = false;
        }
        return;
    }
    if (surfaceOwnedBy(interaction->identity, focus))
        return;
    if (!focus && root && !g_pSessionLockManager->isSessionLocked() && g_pInputManager->m_exclusiveLSes.empty()) {
        changingKeyboardFocus = true;
        g_pSeatManager->setKeyboardFocus(root);
        Event::bus()->m_events.input.keyboard.focus.emit(root);
        changingKeyboardFocus = false;
        return;
    }
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

void rememberEnd(const std::string& owner, const std::string& id, const std::string& reason, const Interaction* previous = nullptr) {
    std::erase_if(endedInteractions, [&](const auto& ended) { return ended.owner == owner; });
    EndedInteraction ended;
    ended.owner = owner;
    ended.id = id;
    ended.reason = reason;
    if (previous) {
        ended.source = previous->identity;
        ended.children = previous->pendingChildren;
        ended.initialWindows = previous->initialWindows;
        ended.previousWindow = previous->previousWindow;
        ended.previousSurface = previous->previousSurface;
        ended.constrainFullscreen = previous->constrainFullscreen;
        ended.activationOrigin = previous->activationOrigin;
        ended.pointerActivationAllowance = previous->pointerActivationAllowance;
        ended.pointerActivationRemainingMs = std::max<int64_t>(0, std::chrono::duration_cast<std::chrono::milliseconds>(previous->pointerActivationDeadline - Clock::now()).count());
        ended.clientActivationEvents = previous->clientActivationEvents;
        ended.keyboardActivationAcknowledgements = previous->keyboardActivationAcknowledgements;
        ended.pointerActivationAcknowledgements = previous->pointerActivationAcknowledgements;
        ended.fullscreenActivationAcknowledgements = previous->fullscreenActivationAcknowledgements;
        ended.desktopFullscreen = previous->desktopFullscreen;
        ended.restoreRequested = restoreReason(reason);
        ended.handoffDeadline = Clock::now() + HANDOFF_TIME;
    }
    endedInteractions.push_back(std::move(ended));
    while (endedInteractions.size() > 64)
        endedInteractions.pop_front();
}

void endInteraction(const std::string& reason, bool refocus) {
    if (!interaction || endingInteraction)
        return;
    endingInteraction = true;
    changingKeyboardFocus = true;
    dismissPopups(interaction->identity);
    if (const auto window = interaction->identity.window.lock(); window && g_layoutManager->dragController()->target() == window->layoutTarget())
        g_layoutManager->endDragTarget();
    auto previous = std::move(*interaction);
    interaction.reset();
    if (reason == "capture-unavailable" || reason == "keyboard-unavailable" || reason == "window-unavailable"
        || reason == "surface-unavailable")
        clearConstrainedFullscreen(previous.identity.id);
    rememberEnd(previous.owner, previous.identity.id, reason, &previous);
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
    changingKeyboardFocus = false;
    endingInteraction = false;
}

bool restoreReason(const std::string& reason) {
    return reason == "modal-dialog" || reason == "source-fullscreen" || reason == "popup-outside"
        || reason == "source-activation" || reason == "window-management";
}

bool privateWindow(const PHLWINDOW& window) {
    return window && window->m_isMapped && window->m_workspace && window->m_workspace->m_name == WORKSPACE;
}

bool stashTagged(const PHLWINDOW& window) {
    if (!window)
        return false;
    const auto& tags = window->m_ruleApplicator->m_tagKeeper.getTags();
    return std::any_of(tags.begin(), tags.end(), [](const auto& tag) { return tag.starts_with("window-stash-"); });
}

Identity windowIdentity(const PHLWINDOW& window) {
    Identity identity;
    identity.address = reinterpret_cast<uintptr_t>(window.get());
    identity.pid = window->getPID();
    identity.stable = window->m_stableID;
    identity.window = window;
    return identity;
}

bool descendantOf(const PHLWINDOW& window, const PHLWINDOW& parent) {
    if (!window || !parent || window == parent)
        return false;
    auto current = window->parent();
    for (int depth = 0; current && depth < 32; ++depth) {
        if (current == parent)
            return true;
        current = current->parent();
    }
    return false;
}

bool pendingHandoff(const EndedInteraction& ended) {
    return ended.restoreRequested && !ended.handedOff && ended.handoffDeadline > Clock::now();
}

bool pendingRelative(EndedInteraction& ended, const PHLWINDOW& candidate) {
    if (!pendingHandoff(ended) || !candidate)
        return false;
    const auto source = ended.source.window.lock();
    if (!source || !sameWindow(ended.source, source.get(), false))
        return false;
    if (candidate == source)
        return true;
    if (stashTagged(candidate) || !descendantOf(candidate, source))
        return false;
    if (!ended.initialWindows.contains(candidate->m_stableID) && ended.children.size() < 16
        && std::none_of(ended.children.begin(), ended.children.end(), [&](const auto& child) {
        return sameWindow(child, candidate.get(), false);
    }))
        ended.children.push_back(windowIdentity(candidate));
    return true;
}

bool ownsPopupGrab(const PHLWINDOW& window) {
    const auto grab = g_pSeatManager->m_seatGrab;
    if (!grab || !window || !window->wlSurface())
        return false;
    if (grab->accepts(window->wlSurface()->resource()))
        return true;
    bool found = false;
    if (window->m_popupHead) {
        window->m_popupHead->breadthfirst([&](SP<Desktop::View::CPopup> popup, void*) {
            if (popup && popup->wlSurface() && popup->wlSurface()->resource() && grab->accepts(popup->wlSurface()->resource()))
                found = true;
        }, nullptr);
    }
    return found;
}

void dismissPopups(const Identity& identity) {
    const auto window = identity.window.lock();
    if (!window || !sameWindow(identity, window.get(), true))
        return;
    if (ownsPopupGrab(window))
        g_pSeatManager->setGrab(nullptr);
    if (!window->m_popupHead)
        return;
    std::vector<SP<CXDGPopupResource>> resources;
    window->m_popupHead->breadthfirst([&](SP<Desktop::View::CPopup> popup, void*) {
        if (!popup || !popup->m_mapped || !popup->wlSurface() || !popup->wlSurface()->resource())
            return;
        const auto role = dynamicPointerCast<CXDGSurfaceRole>(popup->wlSurface()->resource()->m_role);
        if (role && role->m_xdgSurface && role->m_xdgSurface->m_popup)
            resources.push_back(role->m_xdgSurface->m_popup.lock());
    }, nullptr);
    for (const auto& popup : resources)
        popup->done();
}

void restoreVisibleFocus(const PHLWINDOWREF& previousWindow, const WP<CWLSurfaceResource>& previousSurface) {
    if (g_pSessionLockManager->isSessionLocked() || !g_pInputManager->m_exclusiveLSes.empty())
        return;
    const auto window = previousWindow.lock();
    const auto surface = previousSurface.lock();
    if (window && window->m_isMapped && window->m_workspace && window->m_workspace->isVisible())
        Desktop::focusState()->rawWindowFocus(window, Desktop::FOCUS_REASON_OTHER, surface);
    else if (surface && surface->m_hlSurface && surface->m_hlSurface->view() && surface->m_hlSurface->view()->visible())
        Desktop::focusState()->rawSurfaceFocus(surface);
    else
        Desktop::focusState()->rawWindowFocus(nullptr, Desktop::FOCUS_REASON_OTHER);
}

void requestRestore(const std::string& reason, const PHLWINDOW& child) {
    if (!interaction || endingInteraction)
        return;
    const auto source = interaction->identity.window.lock();
    if (!source || !sameWindow(interaction->identity, source.get(), true))
        return;
    if (child && !stashTagged(child) && descendantOf(child, source)
        && !interaction->initialWindows.contains(child->m_stableID) && interaction->pendingChildren.size() < 16)
        interaction->pendingChildren.push_back(windowIdentity(child));
    endInteraction(reason);
}

bool consumeFullscreenTransition(const PHLWINDOW& candidate) {
    const auto found = std::find_if(fullscreenTransitions.begin(), fullscreenTransitions.end(), [&](const auto& item) {
        return (item.second.waitingAck || item.second.expires > Clock::now()) && item.second.activationAllowance
            && sameWindow(item.second.identity, candidate.get(), true);
    });
    if (found == fullscreenTransitions.end())
        return false;
    const auto identity = found->second.identity;
    const auto expected = found->second.client;
    const auto modes = Fullscreen::controller()->getFullscreenModes(candidate);
    if (modes.internal != Fullscreen::FSMODE_NONE || modes.client != expected)
        return false;
    const auto current = fullscreenTransitions.find(identity.id);
    if (current == fullscreenTransitions.end() || (!current->second.waitingAck && current->second.expires <= Clock::now())
        || !current->second.activationAllowance || !sameWindow(current->second.identity, candidate.get(), true))
        return false;
    --current->second.activationAllowance;
    return true;
}

bool guardPassiveFullscreenActivation(const PHLWINDOW& candidate, bool explicitFocus) {
    if (!candidate || (interaction && sameWindow(interaction->identity, candidate.get(), true)))
        return false;
    if (!explicitFocus && consumeFullscreenTransition(candidate))
        return true;
    const auto fullscreen = std::find_if(fullscreenWindows.begin(), fullscreenWindows.end(), [&](const auto& item) {
        return sameWindow(item.second.identity, candidate.get(), true);
    });
    const auto transition = std::find_if(fullscreenTransitions.begin(), fullscreenTransitions.end(), [&](const auto& item) {
        return (item.second.waitingAck || item.second.expires > Clock::now()) && sameWindow(item.second.identity, candidate.get(), true);
    });
    if (fullscreen == fullscreenWindows.end() && transition == fullscreenTransitions.end())
        return false;
    const auto identity = fullscreen != fullscreenWindows.end() ? fullscreen->second.identity : transition->second.identity;
    const auto requested = fullscreen != fullscreenWindows.end() ? fullscreen->second.restoreRequested : transition->second.restoreRequested;
    // The source has no input helper after Stop. Ask the ordinary controller to
    // restore only its UUID; never open the private workspace as a shortcut.
    if (interaction)
        endInteraction("replaced");
    if (sameWindow(identity, candidate.get(), true) && Clock::now() - requested >= std::chrono::seconds(1)) {
        // Update before emitting, and keep no map iterators across callbacks.
        if (const auto found = fullscreenWindows.find(identity.id); found != fullscreenWindows.end())
            found->second.restoreRequested = Clock::now();
        if (const auto found = fullscreenTransitions.find(identity.id); found != fullscreenTransitions.end())
            found->second.restoreRequested = Clock::now();
        if (g_pEventManager)
            g_pEventManager->postEvent({"window-stash-restore", identity.id});
    }
    return true;
}

bool guardActivation(const PHLWINDOW& candidate, bool explicitFocus = false, const std::string& origin = "") {
    if (privateWindow(candidate)) {
        if (interaction) {
            const auto source = interaction->identity.window.lock();
            if (source && sameWindow(interaction->identity, source.get(), true)) {
                if (candidate == source) {
                    interaction->activationOrigin = origin;
                    requestRestore("source-activation");
                    return true;
                }
                if (!stashTagged(candidate) && descendantOf(candidate, source)) {
                    requestRestore("modal-dialog", candidate);
                    return true;
                }
            }
        }
        for (auto& ended : endedInteractions)
            if (pendingRelative(ended, candidate))
                return true;
        if (guardPassiveFullscreenActivation(candidate, explicitFocus))
            return true;
    }
    return false;
}

Config::Actions::ActionResult dispatchFocus(PHLWINDOW candidate) {
    if (guardActivation(candidate, true, "dispatcher-focus"))
        return {};
    // The focus dispatcher changes workspaces before rawWindowFocus. Guarding
    // here prevents even a transient exposure of every other stashed window.
    using Original = Config::Actions::ActionResult (*)(PHLWINDOW);
    return reinterpret_cast<Original>(dispatchFocusHook->m_original)(candidate);
}

void activateWindow(CWindow* window, bool force) {
    if (window) {
        const auto candidate = window->m_self.lock();
        if (!force && interaction && !endingInteraction && sameWindow(interaction->identity, window, true)) {
            ++interaction->clientActivationEvents;
            interaction->activationOrigin = "client-activate";
            if (keyboardWindow() == candidate) {
                // Browser tab commands request activation even though this
                // exact source already owns keyboard focus. Match ordinary
                // activation's already-focused no-op; explicit dispatcher or
                // forced activation still takes the normal restoration path.
                ++interaction->keyboardActivationAcknowledgements;
                return;
            }
            if (consumeFullscreenTransition(candidate)) {
                ++interaction->fullscreenActivationAcknowledgements;
                return;
            }
            if (!interaction->keyboard && interaction->pointerActivationAllowance
                && interaction->pointerActivationDeadline > Clock::now()) {
                // Mouse-only browser controls can request activation before
                // their following fullscreen request. Chromium emits two
                // tokens for one press; bound acknowledgements per routed
                // press/release without granting keyboard focus or promotion.
                --interaction->pointerActivationAllowance;
                ++interaction->pointerActivationAcknowledgements;
                return;
            }
        }
        if (guardActivation(candidate, force, force ? "forced-client-activate" : "client-activate"))
            return;
    }
    // Forced activation retains its explicit restoration behavior even when
    // the virtual keyboard target is this source.
    using Original = void (*)(CWindow*, bool);
    reinterpret_cast<Original>(windowActivateHook->m_original)(window, force);
}

void rawWindowFocus(Desktop::CFocusState* state, PHLWINDOW candidate, Desktop::eFocusReason reason, SP<CWLSurfaceResource> surface) {
    using Original = void (*)(Desktop::CFocusState*, PHLWINDOW, Desktop::eFocusReason, SP<CWLSurfaceResource>);
    if (interaction && !endingInteraction && candidate && candidate->m_isMapped && candidate->m_workspace
        && !candidate->m_workspace->m_isSpecialWorkspace && reason == Desktop::FOCUS_REASON_NEW_WINDOW
        && !interaction->initialWindows.contains(candidate->m_stableID) && !stashTagged(candidate)) {
        const auto identity = windowIdentity(candidate);
        // A new public window already has a legitimate destination. End the
        // old route without restoring its source or stealing the incoming
        // focus. Existing mapped siblings continue to follow normal policy.
        endInteraction("new-window", false);
        if (!sameWindow(identity, candidate.get(), false) || !candidate->m_workspace || candidate->m_workspace->m_isSpecialWorkspace)
            return;
    }
    if (privateWindow(candidate)) {
        if (interaction) {
            const auto source = interaction->identity.window.lock();
            if (source && sameWindow(interaction->identity, source.get(), true)) {
                const bool related = candidate == source || descendantOf(candidate, source);
                if (related && endingInteraction)
                    return;
                if (candidate == source) {
                    if (reason == Desktop::FOCUS_REASON_FFM) {
                        // Popup-grab teardown wants its parent again. Keep the
                        // miniature's input focus; do not expose its workspace.
                        if (interaction->keyboard && interaction->keyboardFocused) {
                            changingKeyboardFocus = true;
                            g_pSeatManager->setKeyboardFocus(source->wlSurface()->resource());
                            Event::bus()->m_events.input.keyboard.focus.emit(source->wlSurface()->resource());
                            changingKeyboardFocus = false;
                        } else if (surfaceOwnedBy(interaction->identity, g_pSeatManager->m_state.keyboardFocus.lock()))
                            restoreVisibleFocus(interaction->previousWindow, interaction->previousSurface);
                        return;
                    }
                    interaction->activationOrigin = "raw-focus-" + std::to_string(reason);
                    requestRestore("source-activation");
                    return;
                }
                if (related && !stashTagged(candidate)) {
                    requestRestore("modal-dialog", candidate);
                    return;
                }
                if (reason == Desktop::FOCUS_REASON_NEW_WINDOW && !stashTagged(candidate)
                    && !interaction->initialWindows.contains(candidate->m_stableID)) {
                    const auto monitor = interaction->monitor.lock();
                    const auto destination = monitor ? monitor->m_activeWorkspace : nullptr;
                    if (destination && !destination->m_isSpecialWorkspace && destination->isVisible()) {
                        Desktop::globalWindowController()->moveWindowToWorkspace(candidate, destination);
                        endInteraction("new-window");
                    } else
                        return;
                }
            }
        }
        // A dismissed popup can finish its grab after the input lease ended.
        // Its old parent still must not open SPECIAL or steal keyboard focus.
        for (auto it = endedInteractions.rbegin(); it != endedInteractions.rend(); ++it) {
            if (pendingRelative(*it, candidate))
                return;
            if (sameWindow(it->source, candidate.get(), true)) {
                if (reason == Desktop::FOCUS_REASON_FFM) {
                    if (!endingInteraction)
                        restoreVisibleFocus(it->previousWindow, it->previousSurface);
                    return;
                }
            }
        }
        if (reason == Desktop::FOCUS_REASON_FFM) {
            if (std::any_of(fullscreenWindows.begin(), fullscreenWindows.end(), [&](const auto& item) {
                return sameWindow(item.second.identity, candidate.get(), true);
            }) || std::any_of(fullscreenTransitions.begin(), fullscreenTransitions.end(), [&](const auto& item) {
                return (item.second.waitingAck || item.second.expires > Clock::now()) && sameWindow(item.second.identity, candidate.get(), true);
            }))
                return;
        } else if (guardPassiveFullscreenActivation(candidate, true))
            return;
    }
    reinterpret_cast<Original>(rawFocusHook->m_original)(state, candidate, reason, surface);
}

void warpCursor(CWindow* window, bool force) {
    if (window && window->m_workspace && window->m_workspace->m_name == WORKSPACE) {
        if (interaction) {
            const auto source = interaction->identity.window.lock();
            if (source && sameWindow(interaction->identity, source.get(), true)
                && (window == source.get() || descendantOf(window->m_self.lock(), source)))
                return;
        }
        for (auto& ended : endedInteractions)
            if (pendingRelative(ended, window->m_self.lock()))
                return;
    }
    using Original = void (*)(CWindow*, bool);
    reinterpret_cast<Original>(warpCursorHook->m_original)(window, force);
}

void activateConstraint(CPointerConstraint* constraint) {
    const auto owner = constraint->owner();
    if (interaction && owner && surfaceOwnedBy(interaction->identity, owner->resource())) {
        // A lock request can activate immediately inside the protocol handler,
        // before the next timer/input validation. Do not let that activation
        // confine or warp the physical cursor out of the miniature.
        endInteraction("pointer-constrained");
        return;
    }
    using Original = void (*)(CPointerConstraint*);
    reinterpret_cast<Original>(constraintActivateHook->m_original)(constraint);
}

bool validateInteraction() {
    if (!interaction || endingInteraction)
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
    else if (window->m_ruleApplicator->noScreenShare().valueOrDefault())
        reason = "capture-unavailable";
    else if (current.keyboard && window->m_ruleApplicator->noFocus().valueOrDefault())
        reason = "keyboard-unavailable";
    else if (g_pSessionLockManager->isSessionLocked())
        reason = "locked";
    else if (!g_pInputManager->m_exclusiveLSes.empty())
        reason = "exclusive-overlay";
    else if (!monitor || !State::monitorState()->contains(monitor) || !monitor->m_dpmsStatus)
        reason = "display-unavailable";
    else if (g_pInputManager->isConstrained() || sourceHasConstraint(current.identity))
        reason = "pointer-constrained";
    else if (g_layoutManager->dragController()->target() == window->layoutTarget())
        reason = "window-management";
    else if (grabbedPopupOutside(window))
        reason = "popup-outside";
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

bool grabbedPopupOutside(const PHLWINDOW& window) {
    // Hover tooltips do not change window placement. Only an application's
    // grabbed menu/popover needs the full-window fallback when it is clipped.
    if (!window || !window->m_popupHead || !ownsPopupGrab(window))
        return false;
    const CBox source{window->position(Desktop::View::IGeometric::GEOMETRIC_CURRENT), window->size(Desktop::View::IGeometric::GEOMETRIC_CURRENT)};
    bool outside = false;
    window->m_popupHead->breadthfirst([&](SP<Desktop::View::CPopup> popup, void*) {
        if (!popup || !popup->m_mapped || !popup->wlSurface() || !popup->wlSurface()->resource())
            return;
        const auto resource = popup->wlSurface()->resource();
        const auto role = dynamicPointerCast<CXDGSurfaceRole>(resource->m_role);
        CBox box{popup->coordsGlobal(), resource->m_current.size};
        if (role && role->m_xdgSurface && role->m_xdgSurface->m_current.geometry.size() > Vector2D{})
            box = role->m_xdgSurface->m_current.geometry.copy().translate(popup->coordsGlobal());
        if (box.w > 0 && box.h > 0 && (box.x < source.x - 1 || box.y < source.y - 1
            || box.x + box.w > source.x + source.w + 1 || box.y + box.h > source.y + source.h + 1))
            outside = true;
    }, nullptr);
    return outside;
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
    else if (window->m_isX11)
        rootPoint *= window->m_X11SurfaceScaledBy;
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
    if (!interaction)
        return false;
    const auto owner = interaction->owner;
    const auto point = inputPoint(global);
    if (!point.surface)
        return false;
    g_pSeatManager->setPointerFocus(point.surface, point.local);
    if (!currentOwner(owner))
        return false;
    g_pSeatManager->sendPointerMotion(time, point.local);
    interaction->lastLocal = point.local;
    interaction->lastGlobal = global;
    return true;
}

void mouseMove(const Vector2D& global, Event::SCallbackInfo& info) {
    if (!validateInteraction() || (!contentHit(global) && interaction->buttons.empty()))
        return;
    const auto owner = interaction->owner;
    info.cancelled = true;
    if (!focusPoint(global, eventTime())) {
        if (currentOwner(owner))
            endInteraction("surface-unavailable");
        return;
    }
    g_pSeatManager->sendPointerFrame();
    ++interaction->motionEvents;
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
    const auto owner = interaction->owner;
    const bool pressed = event.state == WL_POINTER_BUTTON_STATE_PRESSED;
    if (!pressed && !interaction->buttons.contains(event.button))
        return; // Never retarget a press delivered through another surface.
    info.cancelled = true;
    const auto undelivered = [&] {
        if (pressed)
            releasedButtons.insert(event.button);
        else
            releasedButtons.erase(event.button);
    };
    auto point = inputPoint(position);
    if (!point.surface) {
        endInteraction("surface-unavailable");
        undelivered();
        return;
    }
    if (pressed) {
        if (interaction->buttons.size() >= 16) {
            undelivered();
            return;
        }
        if (const auto monitor = interaction->monitor.lock())
            Desktop::focusState()->rawMonitorFocus(monitor);
        if (!currentOwner(owner)) {
            undelivered();
            return;
        }
        if (interaction->keyboard && !interaction->keyboardFocused)
            acquireKeyboard();
        if (!currentOwner(owner)) {
            undelivered();
            return;
        }
    }
    g_pSeatManager->setPointerFocus(point.surface, point.local);
    if (!currentOwner(owner)) {
        undelivered();
        return;
    }
    g_pSeatManager->sendPointerMotion(event.timeMs, point.local);
    interaction->lastLocal = point.local;
    interaction->lastGlobal = position;
    if (pressed) {
        if (interaction->buttons.empty()) {
            interaction->grab = point.surface;
            interaction->grabOffset = point.root - point.local;
        }
        const bool newPress = interaction->buttons.insert(event.button).second;
        if (newPress && !interaction->keyboard) {
            interaction->pointerActivationAllowance = POINTER_ACTIVATION_CREDITS;
            interaction->pointerActivationDeadline = Clock::now() + std::chrono::milliseconds(500);
        }
    }
    g_pSeatManager->sendPointerButton(event.timeMs, event.button, event.state);
    g_pSeatManager->sendPointerFrame();
    if (event.state == WL_POINTER_BUTTON_STATE_RELEASED) {
        const bool matchingRelease = interaction->buttons.erase(event.button) != 0;
        if (matchingRelease && !interaction->keyboard) {
            interaction->pointerActivationAllowance = POINTER_ACTIVATION_CREDITS;
            interaction->pointerActivationDeadline = Clock::now() + std::chrono::milliseconds(500);
        }
        if (interaction->buttons.empty())
            interaction->grab.reset();
    }
    ++interaction->buttonEvents;
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
    const auto owner = interaction->owner;
    info.cancelled = true;
    // A wheel frame is an axis frame, not a newly synthesized mouse movement.
    // Flush a changed focus before delivering its first axis; stable focus must
    // retain the same event ordering as the compositor's ordinary wheel path.
    if (g_pSeatManager->m_state.pointerFocus != point.surface) {
        g_pSeatManager->setPointerFocus(point.surface, point.local);
        if (!currentOwner(owner))
            return;
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
    synchronizeConstrainedFullscreen();
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
    // A hidden client must be allowed to process the configure acknowledging
    // fullscreen cleanup before native hooks can be removed. This is scoped to
    // verified sources and ends at ACK, independently of capture/input leases.
    for (const auto& [id, transition] : fullscreenTransitions) {
        const auto window = transition.identity.window.lock();
        if (transition.waitingAck && window && sameWindow(transition.identity, window.get(), true))
            active.emplace(window.get(), transition.identity);
    }
    if (validateInteraction()) {
        const auto window = interaction->identity.window.lock();
        active.emplace(window.get(), interaction->identity);
    }
    for (const auto& [window, identity] : previous)
        if (!active.contains(window))
            naturalSuspension(identity);
    std::erase_if(lastFeedback, [](const auto& entry) { return !active.contains(entry.first); });
    for (const auto& [window, identity] : active)
        window->setSuspended(false);
    if (frameTimer) {
        const auto desired = interaction ? std::chrono::milliseconds((1000 + interaction->fps - 1) / interaction->fps)
            : active.empty() && (!fullscreenWindows.empty() || !fullscreenTransitions.empty()) ? std::chrono::milliseconds(500) : FRAME_TIME;
        if (owners.empty() && !interaction && fullscreenWindows.empty() && fullscreenTransitions.empty())
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
        const auto now = Clock::now();
        const auto interval = interaction && interaction->identity.id == identity.id
            ? std::chrono::milliseconds((1000 + interaction->fps - 1) / interaction->fps) : FRAME_TIME;
        const auto previous = lastFeedback.find(window.get());
        if (previous != lastFeedback.end() && now - previous->second < interval)
            continue;
        lastFeedback[window.get()] = now;
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
        // XDG popups are independent surface trees, not wl_subsurfaces of the
        // source. They need their own feedback while an interactive capture is
        // rendering them, even though their real workspace stays hidden.
        if (interaction && interaction->identity.id == identity.id && window->m_popupHead) {
            window->m_popupHead->breadthfirst([&window, &monitor](SP<Desktop::View::CPopup> popup, void*) {
                if (!popup || !popup->m_mapped || !popup->wlSurface() || !popup->wlSurface()->resource())
                    return;
                popup->wlSurface()->resource()->breadthfirst([&window, &monitor](SP<CWLSurfaceResource> surface, const Vector2D&, void*) {
                    if (!leased(window.get()))
                        return;
                    surface->m_stateQueue.unlockFirst(LOCK_REASON_FENCE | LOCK_REASON_FIFO | LOCK_REASON_TIMER);
                    surface->presentFeedback(Time::steadyNow(), monitor, true);
                }, nullptr);
                ++popupFrames;
            }, nullptr);
        }
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

SourceGeometry sourceGeometryDetails(const Identity& identity) {
    SourceGeometry result;
    const auto window = identity.window.lock();
    if (!window || !sameWindow(identity, window.get(), true)) {
        result.reason = "window-unavailable";
        return result;
    }
    result.xwayland = window->m_isX11;
    if (reloadPending)
        result.reason = "support-reloading";
    else if (window->m_ruleApplicator->noScreenShare().valueOrDefault())
        result.reason = "capture-unavailable";
    else if (!window->m_isFloating)
        result.reason = "source-not-floating";
    else if (Fullscreen::controller()->getFullscreenModes(window).internal != Fullscreen::FSMODE_NONE)
        result.reason = "source-fullscreen";
    else if (std::any_of(fullscreenTransitions.begin(), fullscreenTransitions.end(), [&](const auto& item) {
        return item.second.resize != FullscreenResize::None && sameWindow(item.second.identity, window.get(), true);
    }))
        result.reason = "fullscreen-cleanup";
    if (!result.reason.empty())
        return result;

    const auto root = window->wlSurface() ? window->wlSurface()->resource() : nullptr;
    if (!root || !root->m_mapped || !root->m_current.texture) {
        result.reason = "surface-unavailable";
        return result;
    }
    const auto validSize = [](const Vector2D& size) {
        return std::isfinite(size.x) && std::isfinite(size.y)
            && size.x >= 1 && size.y >= 1 && size.x <= 32768 && size.y <= 32768;
    };
    const auto matches = [](const Vector2D& first, const Vector2D& second) {
        return std::abs(first.x - second.x) < 0.01 && std::abs(first.y - second.y) < 0.01;
    };
    const auto goal = window->size(Desktop::View::IGeometric::GEOMETRIC_GOAL);
    result.surface = root->m_current.size;
    result.configured = window->getReportedSize();
    if (result.xwayland) {
        // XWayland has no XDG configure acknowledgements. Its committed buffer
        // geometry must independently agree with the requested logical size;
        // m_reportedSize alone is updated even by an old-size surface commit.
        const auto scale = window->m_X11SurfaceScaledBy;
        if (!std::isfinite(scale) || scale <= 0) {
            result.reason = "invalid-source-scale";
            return result;
        }
        result.surface /= scale;
        result.configured /= scale;
        result.size = result.surface;
    } else if (window->m_xdgSurface) {
        // onAck updates pending surface state. getReportedSize() reads the
        // acknowledged size only after that state has passed commit/fence
        // processing, alongside XDG's committed window geometry.
        const auto geometry = window->m_xdgSurface->m_current.geometry;
        result.size = geometry.size() == Vector2D{} ? result.surface : geometry.size();
        if (validSize(result.size) && geometry.size() != Vector2D{}) {
            const auto bounds = root->extends();
            const auto position = geometry.pos(), extent = bounds.pos();
            const auto extentSize = bounds.size();
            if (position.x < extent.x - 0.01 || position.y < extent.y - 0.01
                || position.x + result.size.x > extent.x + extentSize.x + 0.01
                || position.y + result.size.y > extent.y + extentSize.y + 0.01) {
                result.reason = "frame-pending";
                return result;
            }
        }
    } else {
        result.reason = "unsupported-source";
        return result;
    }
    if (!validSize(goal) || !validSize(result.size) || !validSize(result.surface) || !validSize(result.configured))
        result.reason = "invalid-source-geometry";
    else if (!matches(result.configured, goal))
        result.reason = "configure-pending";
    else if (!matches(result.size, goal))
        result.reason = "frame-pending";
    else if (!matches(window->size(Desktop::View::IGeometric::GEOMETRIC_CURRENT), goal))
        result.reason = "animation-pending";
    else
        result.ready = true;
    return result;
}

int sourceGeometry(lua_State* state) {
    try {
        const auto geometry = sourceGeometryDetails(readIdentity(state, 1));
        lua_newtable(state);
        booleanField(state, "ready", geometry.ready);
        booleanField(state, "xwayland", geometry.xwayland);
        numberField(state, "width", geometry.size.x);
        numberField(state, "height", geometry.size.y);
        numberField(state, "configuredWidth", geometry.configured.x);
        numberField(state, "configuredHeight", geometry.configured.y);
        numberField(state, "surfaceWidth", geometry.surface.x);
        numberField(state, "surfaceHeight", geometry.surface.y);
        field(state, "reason", geometry.reason);
        return 1;
    } catch (const std::exception& error) {
        lua_pushnil(state);
        lua_pushstring(state, error.what());
        return 2;
    }
}

void interactionDetails(lua_State* state, const std::string& owner) {
    lua_newtable(state);
    const bool matches = interaction && (owner.empty() || interaction->owner == owner);
    booleanField(state, "active", matches);
    booleanField(state, "keyboard", matches && interaction->keyboard);
    booleanField(state, "keyboardFocused", matches && interaction->keyboardFocused);
    booleanField(state, "restoreRequested", false);
    field(state, "fullscreen", matches ? interaction->constrainFullscreen ? "preview" : "desktop" : "");
    booleanField(state, "previewFullscreen", matches && fullscreenWindows.contains(interaction->identity.id)
                 && fullscreenWindows.at(interaction->identity.id).client == Fullscreen::FSMODE_FULLSCREEN);
    field(state, "activationOrigin", matches ? interaction->activationOrigin : "");
    field(state, "pointerActivationAllowance", matches ? interaction->pointerActivationAllowance : 0);
    field(state, "pointerActivationRemainingMs", matches ? std::max<int64_t>(0,
          std::chrono::duration_cast<std::chrono::milliseconds>(interaction->pointerActivationDeadline - Clock::now()).count()) : 0);
    field(state, "clientActivationEvents", matches ? interaction->clientActivationEvents : 0);
    field(state, "keyboardActivationAcknowledgements", matches ? interaction->keyboardActivationAcknowledgements : 0);
    field(state, "pointerActivationAcknowledgements", matches ? interaction->pointerActivationAcknowledgements : 0);
    field(state, "fullscreenActivationAcknowledgements", matches ? interaction->fullscreenActivationAcknowledgements : 0);
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
                booleanField(state, "restoreRequested", it->restoreRequested && !it->handedOff);
                field(state, "fullscreen", it->constrainFullscreen ? "preview" : "desktop");
                booleanField(state, "previewFullscreen", fullscreenWindows.contains(it->id)
                             && fullscreenWindows.at(it->id).client == Fullscreen::FSMODE_FULLSCREEN);
                field(state, "activationOrigin", it->activationOrigin);
                field(state, "pointerActivationAllowance", it->pointerActivationAllowance);
                field(state, "pointerActivationRemainingMs", it->pointerActivationRemainingMs);
                field(state, "clientActivationEvents", it->clientActivationEvents);
                field(state, "keyboardActivationAcknowledgements", it->keyboardActivationAcknowledgements);
                field(state, "pointerActivationAcknowledgements", it->pointerActivationAcknowledgements);
                field(state, "fullscreenActivationAcknowledgements", it->fullscreenActivationAcknowledgements);
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
        if (reloadPending)
            throw std::invalid_argument("Preview support is being reloaded");
        if (lua_type(state, 1) != LUA_TTABLE)
            throw std::invalid_argument("Expected an interaction lease table");
        if (endingInteraction)
            throw std::invalid_argument("The previous interaction is still releasing its input");
        if (!handoffSupported)
            throw std::invalid_argument("This compositor does not expose the required private-window focus guard");
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
        lua_getfield(state, 1, "fullscreen");
        const auto fullscreen = lua_isnil(state, -1) ? std::string("preview") : stringAt(state, -1);
        lua_pop(state, 1);
        if (fullscreen != "preview" && fullscreen != "desktop")
            throw std::invalid_argument("Fullscreen policy must be preview or desktop");
        const bool constrainFullscreen = fullscreen == "preview";
        if (constrainFullscreen && !constrainedFullscreenSupported)
            throw std::invalid_argument("Constrained fullscreen is unavailable: " + fullscreenError);
        lua_getfield(state, 1, "window");
        auto identity = readIdentity(state, -1);
        lua_pop(state, 1);
        if (identity.window->m_ruleApplicator->noScreenShare().valueOrDefault())
            throw std::invalid_argument("This window disallows screen capture");
        if (sourceHasConstraint(identity))
            throw std::invalid_argument("Pointer-locked or pointer-confined windows cannot receive miniature input");
        if (keyboard && identity.window->m_ruleApplicator->noFocus().valueOrDefault())
            throw std::invalid_argument("This window disallows keyboard focus");
        if (interaction && interaction->identity.id != identity.id)
            throw std::invalid_argument("Release the current window before switching interaction targets");
        if (interaction && interaction->keyboard != keyboard)
            throw std::invalid_argument("Release the current interaction before changing keyboard mode");
        if (interaction && interaction->constrainFullscreen != constrainFullscreen)
            throw std::invalid_argument("Release the current interaction before changing fullscreen policy");
        if (constrainFullscreen && Fullscreen::controller()->getFullscreenModes(identity.window.lock()).internal != Fullscreen::FSMODE_NONE)
            throw std::invalid_argument("Restore this window before entering preview-constrained fullscreen");
        if (constrainFullscreen && fullscreenWindows.size() >= MAX_WINDOWS && !fullscreenWindows.contains(identity.id))
            throw std::invalid_argument("Too many fullscreen previews; leave fullscreen in another preview before interacting");
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
        if (!interaction) {
            if (!constrainFullscreen)
                clearConstrainedFullscreen(identity.id);
            interaction.emplace();
            interaction->previousWindow = Desktop::focusState()->window();
            interaction->previousSurface = g_pSeatManager->m_state.keyboardFocus;
            interaction->keyboardSurface = identity.window->wlSurface()->resource();
            for (const auto& window : Desktop::windowState()->windows())
                if (window->m_isMapped)
                    interaction->initialWindows.insert(window->m_stableID);
        }
        interaction->owner = owner;
        interaction->identity = std::move(identity);
        interaction->rect = rect;
        interaction->excludeRects = std::move(excluded);
        interaction->monitor = monitor;
        interaction->fps = fps;
        interaction->keyboard = keyboard;
        interaction->constrainFullscreen = constrainFullscreen;
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

int clearFullscreen(lua_State* state) {
    try {
        const auto identity = readIdentity(state, 1);
        const auto found = fullscreenWindows.find(identity.id);
        if (found != fullscreenWindows.end() && (found->second.identity.address != identity.address
            || found->second.identity.pid != identity.pid || found->second.identity.stable != identity.stable
            || found->second.identity.tag != identity.tag))
            throw std::invalid_argument("The fullscreen preview identity changed");
        lua_pushboolean(state, clearConstrainedFullscreen(identity.id));
        synchronize();
        return 1;
    } catch (const std::exception& error) {
        lua_pushnil(state);
        lua_pushstring(state, error.what());
        return 2;
    }
}

int fullscreenCleanupPending(lua_State* state) {
    try {
        const auto identity = readIdentity(state, 1);
        const auto found = fullscreenTransitions.find(identity.id);
        if (found != fullscreenTransitions.end() && (found->second.identity.address != identity.address
            || found->second.identity.pid != identity.pid || found->second.identity.stable != identity.stable
            || found->second.identity.tag != identity.tag))
            throw std::invalid_argument("The fullscreen preview identity changed");
        synchronize();
        const auto current = fullscreenTransitions.find(identity.id);
        lua_pushboolean(state, current != fullscreenTransitions.end() && current->second.resize != FullscreenResize::None);
        return 1;
    } catch (const std::exception& error) {
        lua_pushnil(state);
        lua_pushstring(state, error.what());
        return 2;
    }
}

int interactionHandoff(lua_State* state) {
    try {
        if (reloadPending)
            throw std::invalid_argument("Preview support is being reloaded");
        const auto owner = stringAt(state, 1);
        if (!hexadecimal(owner, 32))
            throw std::invalid_argument("Invalid interaction owner");
        auto ended = std::find_if(endedInteractions.begin(), endedInteractions.end(), [&](const auto& item) { return item.owner == owner; });
        if (ended == endedInteractions.end() || !ended->restoreRequested)
            throw std::invalid_argument("This interaction did not request a window handoff");
        const auto source = ended->source.window.lock();
        if (!source || !sameWindow(ended->source, source.get(), false))
            throw std::invalid_argument("The original handoff window is no longer available");
        const auto destination = source->m_workspace;
        if (!destination || destination->m_isSpecialWorkspace || !destination->isVisible())
            throw std::invalid_argument("Restore the original window before completing its handoff");
        const auto sourceIdentity = ended->source;
        const auto children = ended->children;
        size_t moved = 0;
        PHLWINDOW focused;
        for (const auto& identity : children) {
            const auto child = identity.window.lock();
            if (!child || !sameWindow(identity, child.get(), false))
                continue;
            if (stashTagged(child) || !descendantOf(child, source))
                continue;
            // A new transient can map provisionally on the visible invoking
            // workspace. Its exact parent still determines the final restore
            // destination. Pre-existing mapped windows are never captured here.
            if (child->m_workspace != destination) {
                Desktop::globalWindowController()->moveWindowToWorkspace(child, destination);
                ++moved;
            }
            if (child->m_workspace == destination)
                focused = child;
        }
        // Workspace moves emit callbacks; find the owner again rather than
        // retaining an iterator across a reentrant release or new session.
        ended = std::find_if(endedInteractions.begin(), endedInteractions.end(), [&](const auto& item) { return item.owner == owner; });
        std::optional<DesktopFullscreenRequest> desktopFullscreen;
        if (ended != endedInteractions.end() && !ended->handedOff) {
            if (ended->handoffDeadline > Clock::now())
                desktopFullscreen = std::move(ended->desktopFullscreen);
            ended->desktopFullscreen.reset();
            ended->handedOff = true;
        }
        if (desktopFullscreen && sameWindow(sourceIdentity, source.get(), false)
            && source->m_workspace && !source->m_workspace->m_isSpecialWorkspace && source->m_workspace->isVisible()
            && desktopFullscreen->client.value_or(desktopFullscreen->internal.value_or(Fullscreen::FSMODE_NONE)) != Fullscreen::FSMODE_NONE)
            Fullscreen::controller()->setFullscreenMode(source, desktopFullscreen->internal, desktopFullscreen->client, desktopFullscreen->layoutAware);
        if (focused)
            Desktop::focusState()->fullWindowFocus(focused, Desktop::FOCUS_REASON_OTHER);
        lua_newtable(state);
        field(state, "moved", moved);
        booleanField(state, "focused", focused != nullptr);
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
    field(state, "fingerprint", STASH_BRIDGE_FINGERPRINT);
    field(state, "modulePath", modulePath);
    field(state, "hyprlandHash", GIT_COMMIT_HASH);
    field(state, "reloadProtocol", 1);
    booleanField(state, "reloadPending", reloadPending);
    field(state, "pendingButtons", releasedButtons.size());
    field(state, "pendingKeys", releasedKeys.size());
    // Keep filtering synthetic cleanup's later physical releases until they
    // arrive. Removing hooks earlier could leak a release to another window or
    // trigger an unrelated release-bound window-manager action.
    booleanField(state, "reloadReady", reloadPending && !interaction && !endingInteraction
                 && owners.empty() && active.empty() && releasedButtons.empty() && releasedKeys.empty()
                 && fullscreenTransitions.empty());
    field(state, "pendingFullscreen", fullscreenTransitions.size());
    const auto pendingResizes = std::count_if(fullscreenTransitions.begin(), fullscreenTransitions.end(), [](const auto& item) {
        return item.second.resize != FullscreenResize::None;
    });
    field(state, "pendingFullscreenResizes", pendingResizes);
    lua_newtable(state);
    int cleanupOrdinal = 1;
    for (const auto& [id, value] : fullscreenTransitions) {
        if (value.resize == FullscreenResize::None)
            continue;
        lua_pushlstring(state, id.data(), id.size());
        lua_rawseti(state, -2, cleanupOrdinal++);
    }
    lua_setfield(state, -2, "fullscreenCleanups");
    field(state, "owners", owners.size());
    field(state, "windows", active.size());
    field(state, "leaseTimeout", LEASE_TIME.count());
    field(state, "frameInterval", frameInterval.count());
    field(state, "frames", frames);
    field(state, "preventedSuspends", preventedSuspends);
    field(state, "popupFrames", popupFrames);
    field(state, "constrainedFullscreenWindows", fullscreenWindows.size());
    lua_newtable(state);
    int fullscreenOrdinal = 1;
    for (const auto& [id, value] : fullscreenWindows) {
        lua_newtable(state);
        field(state, "id", id);
        field(state, "client", value.client);
        field(state, "originalClient", value.originalClient);
        lua_rawseti(state, -2, fullscreenOrdinal++);
    }
    lua_setfield(state, -2, "fullscreenWindows");
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
    booleanField(state, "pointer", handoffSupported);
    booleanField(state, "keyboard", keyboardSupported);
    booleanField(state, "exitShortcut", keybindHook != nullptr);
    booleanField(state, "popups", popupsSupported);
    booleanField(state, "handoff", handoffSupported);
    booleanField(state, "constrainedFullscreen", constrainedFullscreenSupported);
    booleanField(state, "sourceGeometry", true);
    field(state, "fullscreenError", fullscreenError);
    field(state, "fullscreenProtocol", 1);
    field(state, "keyboardError", keyboardError);
    field(state, "interactionProtocol", 1);
    lua_setfield(state, -2, "capabilities");
    return 1;
}

int prepareReload(lua_State* state) {
    reloadPending = true;
    endInteraction("bridge-reload");
    clearAllConstrainedFullscreen();
    owners.clear();
    for (auto& ended : endedInteractions) {
        ended.restoreRequested = false;
        ended.handedOff = true;
    }
    synchronize();
    return status(state);
}

int cancelReload(lua_State* state) {
    reloadPending = false;
    return status(state);
}

int update(lua_State* state) {
    try {
        if (reloadPending)
            throw std::invalid_argument("Preview support is being reloaded");
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

bool popupVisible(const Desktop::View::CPopup* popup) {
    if (captureWindow && popupsSupported && leased(captureWindow) && popup->m_mapped && popup->getMonitor()
        && popup->getT1Owner() == captureWindow->wlSurface())
        return true;
    using Original = bool (*)(const Desktop::View::CPopup*);
    return reinterpret_cast<Original>(popupVisibleHook->m_original)(popup);
}

void renderWindow(Render::IHyprRenderer* renderer, PHLWINDOW window, PHLMONITOR monitor, const Time::steady_tp& time,
                  bool decorate, Render::eRenderPassMode mode, bool ignorePosition, bool standalone) {
    struct CaptureScope {
        CWindow* previous;
        ~CaptureScope() { captureWindow = previous; }
    } scope{captureWindow};
    if (standalone && popupsSupported && interaction && sameWindow(interaction->identity, window.get(), true))
        captureWindow = window.get();
    using Original = void (*)(Render::IHyprRenderer*, PHLWINDOW, PHLMONITOR, const Time::steady_tp&, bool, Render::eRenderPassMode, bool, bool);
    reinterpret_cast<Original>(renderWindowHook->m_original)(renderer, window, monitor, time, decorate, mode, ignorePosition, standalone);
}

void setupPopups() {
    try {
        popupVisibleHook = optionalHook("visible", "Desktop::View::CPopup::visible() const", reinterpret_cast<const void*>(&popupVisible));
        renderWindowHook = optionalHook("renderWindow", "Render::IHyprRenderer::renderWindow(", reinterpret_cast<const void*>(&renderWindow));
        popupsSupported = true;
    } catch (const std::exception&) {
        for (auto** hook : {&renderWindowHook, &popupVisibleHook}) {
            if (*hook)
                HyprlandAPI::removeFunctionHook(handle, *hook);
            *hook = nullptr;
        }
    }
}

void windowOpened(PHLWINDOW candidate) {
    if (!candidate || stashTagged(candidate))
        return;
    if (interaction && !endingInteraction) {
        const auto source = interaction->identity.window.lock();
        if (source && sameWindow(interaction->identity, source.get(), true) && descendantOf(candidate, source))
            requestRestore("modal-dialog", candidate);
    }
    for (auto& ended : endedInteractions)
        pendingRelative(ended, candidate);
}

void fullscreenChanged(PHLWINDOW candidate) {
    if (!interaction || endingInteraction || !candidate || !sameWindow(interaction->identity, candidate.get(), true))
        return;
    const auto modes = Fullscreen::controller()->getFullscreenModes(candidate);
    if (interaction->constrainFullscreen && constrainedFullscreenSupported && modes.internal == Fullscreen::FSMODE_NONE)
        return;
    if (modes.internal != Fullscreen::FSMODE_NONE || modes.client != Fullscreen::FSMODE_NONE)
        requestRestore("source-fullscreen");
}

void setupFullscreen() {
    try {
        const auto functions = HyprlandAPI::findFunctionsByName(handle, "setWindowFullscreenModeClient");
        const SFunctionMatch* target = nullptr;
        for (const auto& function : functions) {
            if (!function.demangled.starts_with("Fullscreen::CFullscreenController::setWindowFullscreenModeClient("))
                continue;
            if (target)
                throw std::runtime_error("Ambiguous client fullscreen function");
            target = &function;
        }
        if (!target)
            throw std::runtime_error("Missing client fullscreen function");
        clientFullscreenFunction = target->address;
        fullscreenModeHook = optionalHook("setFullscreenMode", "Fullscreen::CFullscreenController::setFullscreenMode(",
                                          reinterpret_cast<const void*>(&setFullscreenMode));
        fullscreenActionHook = optionalHook("fullscreenWindow", "Config::Actions::fullscreenWindow(Fullscreen::eFullscreenMode, bool,",
                                            reinterpret_cast<const void*>(&fullscreenWindow));
        moveWorkspaceHook = optionalHook("moveWindowToWorkspace", "Desktop::CGlobalWindowController::moveWindowToWorkspace(",
                                         reinterpret_cast<const void*>(&moveWindowToWorkspace));
        constrainedFullscreenSupported = true;
    } catch (const std::exception& error) {
        fullscreenError = error.what();
        for (auto** hook : {&moveWorkspaceHook, &fullscreenActionHook, &fullscreenModeHook}) {
            if (*hook)
                HyprlandAPI::removeFunctionHook(handle, *hook);
            *hook = nullptr;
        }
        clientFullscreenFunction = nullptr;
    }
}

void setupHandoff() {
    try {
        rawFocusHook = optionalHook("rawWindowFocus", "Desktop::CFocusState::rawWindowFocus(", reinterpret_cast<const void*>(&rawWindowFocus));
        dispatchFocusHook = optionalHook("focus", "Config::Actions::focus(", reinterpret_cast<const void*>(&dispatchFocus));
        windowActivateHook = optionalHook("activate", "Desktop::View::CWindow::activate(", reinterpret_cast<const void*>(&activateWindow));
        warpCursorHook = optionalHook("warpCursor", "Desktop::View::CWindow::warpCursor(", reinterpret_cast<const void*>(&warpCursor));
        constraintActivateHook = optionalHook("activate", "CPointerConstraint::activate(", reinterpret_cast<const void*>(&activateConstraint));
        handoffSupported = true;
    } catch (const std::exception&) {
        for (auto** hook : {&constraintActivateHook, &warpCursorHook, &windowActivateHook, &dispatchFocusHook, &rawFocusHook}) {
            if (*hook)
                HyprlandAPI::removeFunctionHook(handle, *hook);
            *hook = nullptr;
        }
    }
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
    Dl_info module{};
    if (!dladdr(reinterpret_cast<const void*>(&status), &module) || !module.dli_fname)
        throw std::runtime_error("Cannot identify the preview bridge module path");
    modulePath = module.dli_fname;
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
        || !HyprlandAPI::addLuaFunction(handle, LUA_NAMESPACE, "prepare_reload", prepareReload)
        || !HyprlandAPI::addLuaFunction(handle, LUA_NAMESPACE, "cancel_reload", cancelReload)
        || !HyprlandAPI::addLuaFunction(handle, LUA_NAMESPACE, "interaction_update", interactionUpdate)
        || !HyprlandAPI::addLuaFunction(handle, LUA_NAMESPACE, "interaction_release", interactionRelease)
        || !HyprlandAPI::addLuaFunction(handle, LUA_NAMESPACE, "clear_fullscreen", clearFullscreen)
        || !HyprlandAPI::addLuaFunction(handle, LUA_NAMESPACE, "source_geometry", sourceGeometry)
        || !HyprlandAPI::addLuaFunction(handle, LUA_NAMESPACE, "fullscreen_cleanup_pending", fullscreenCleanupPending)
        || !HyprlandAPI::addLuaFunction(handle, LUA_NAMESPACE, "interaction_status", interactionStatus)
        || !HyprlandAPI::addLuaFunction(handle, LUA_NAMESPACE, "interaction_handoff", interactionHandoff))
        throw std::runtime_error("Could not register the preview lease API");
    mouseMoveListener = Event::bus()->m_events.input.mouse.move.listen(mouseMove);
    mouseButtonListener = Event::bus()->m_events.input.mouse.button.listen(mouseButton);
    mouseAxisListener = Event::bus()->m_events.input.mouse.axis.listen(mouseAxis);
    setupKeyboard();
    setupPopups();
    setupHandoff();
    setupFullscreen();
    keyboardFocusListener = g_pSeatManager->m_events.keyboardFocusChange.listen(keyboardFocusChanged);
    keyboardEventListener = Event::bus()->m_events.input.keyboard.key.listen(keyboardEvent);
    windowOpenListener = Event::bus()->m_events.window.openEarly.listen(windowOpened);
    fullscreenListener = Event::bus()->m_events.window.fullscreen.listen(fullscreenChanged);
    lockListener = g_pSessionLockManager->m_events.lock.listen([] { endInteraction("locked", false); });
    monitorListener = Event::bus()->m_events.monitor.layoutChanged.listen([] { endInteraction("display-changed"); });
    workspaceListener = Event::bus()->m_events.workspace.active.listen([](PHLWORKSPACE) { endInteraction("workspace-changed"); });
    frameTimer = makeShared<CEventLoopTimer>(std::nullopt,
        [](SP<CEventLoopTimer>, void*) { frame(); }, nullptr);
    g_pEventLoopManager->addTimer(frameTimer);
    return {"window-stash-preview", "Scoped rendering for visible Window Stash live previews", "artu-ole", STASH_BRIDGE_VERSION};
}

APICALL EXPORT void PLUGIN_EXIT() {
    reloadPending = true;
    endInteraction("unloaded");
    clearAllConstrainedFullscreen();
    std::vector<PHLWINDOW> resizing;
    for (const auto& [id, value] : fullscreenTransitions)
        if (const auto window = value.identity.window.lock(); window && value.resize != FullscreenResize::None)
            resizing.push_back(window);
    for (const auto& window : resizing)
        cancelFullscreenResize(window);
    fullscreenTransitions.clear();
    mouseMoveListener.reset();
    mouseButtonListener.reset();
    mouseAxisListener.reset();
    keyboardFocusListener.reset();
    keyboardEventListener.reset();
    windowOpenListener.reset();
    fullscreenListener.reset();
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
