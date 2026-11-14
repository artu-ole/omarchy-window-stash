"""Production Desktop fullscreen deferral and cleanup under AddressSanitizer."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from test_fullscreen_native_memory import production_function

PRELUDE = r'''
#include <algorithm>
#include <cassert>
#include <chrono>
#include <deque>
#include <memory>
#include <optional>
#include <string>
#include <unordered_map>
#include <vector>
using Clock = std::chrono::steady_clock;
namespace Fullscreen { enum eFullscreenMode { FSMODE_NONE, FSMODE_MAXIMIZED, FSMODE_FULLSCREEN }; }
using Mode = Fullscreen::eFullscreenMode;
struct Toplevel { struct { bool requestsMaximize = false; } m_state; };
struct Surface { std::shared_ptr<Toplevel> m_toplevel = std::make_shared<Toplevel>(); };
struct Window {
 Mode client = Fullscreen::FSMODE_NONE, internal = Fullscreen::FSMODE_NONE;
 bool owned = true, parked = true;
 std::shared_ptr<Surface> m_xdgSurface = std::make_shared<Surface>();
};
using PHLWINDOW = std::shared_ptr<Window>;
struct Identity { std::string id; std::weak_ptr<Window> window; };
struct DesktopFullscreenRequest {
 std::optional<Mode> internal, client;
 std::optional<bool> layoutAware;
 Mode originalClient = Fullscreen::FSMODE_NONE;
};
struct Interaction { Identity identity; bool constrainFullscreen = false; std::optional<DesktopFullscreenRequest> desktopFullscreen; };
struct EndedInteraction {
 std::string owner = "owned", id;
 Identity source;
 bool restoreRequested = true, handedOff = false;
 std::optional<DesktopFullscreenRequest> desktopFullscreen;
 Clock::time_point handoffDeadline = Clock::now()+std::chrono::seconds(1);
};
struct ConstrainedFullscreen { Identity identity; Mode originalClient, client; };
struct Transition {
 Identity identity;
 Mode client = Fullscreen::FSMODE_NONE;
 bool maximizeFollowupHandled = false, waitingAck = false;
 Clock::time_point expires{};
 enum class Resize { None } resize = Resize::None;
 unsigned activationAllowance = 0;
};
using FullscreenResize = Transition::Resize;
std::optional<Interaction> interaction;
std::deque<EndedInteraction> endedInteractions;
std::unordered_map<std::string,ConstrainedFullscreen> fullscreenWindows;
std::unordered_map<std::string,Transition> fullscreenTransitions;
bool endingInteraction = false, reloadPending = false;
unsigned forwards = 0, cleanupAcks = 0;
std::vector<Mode> clientConfigures;
bool sameWindow(const Identity& identity, Window* window, bool parked) {
 return window && window->owned && identity.window.lock().get() == window && (!parked || window->parked);
}
namespace Fullscreen {
struct Modes { Mode internal, client; };
struct CFullscreenController {
 Modes getFullscreenModes(const PHLWINDOW& window) { return {window->internal,window->client}; }
};
CFullscreenController* controller() { static CFullscreenController value; return &value; }
}
void setClientFullscreen(const PHLWINDOW& window, Mode mode) { window->client=mode;clientConfigures.push_back(mode); }
void requestRestore(const std::string&) {
 EndedInteraction ended;
 ended.source=interaction->identity;ended.id=ended.source.id;ended.desktopFullscreen=interaction->desktopFullscreen;
 endedInteractions.push_back(ended);interaction.reset();
}
bool clearConstrainedFullscreen(std::string id) {
 const auto value=fullscreenWindows.at(id);fullscreenWindows.erase(id);
 setClientFullscreen(value.identity.window.lock(),value.originalClient);++cleanupAcks;return true;
}
bool consumePassiveMaximizeEcho(const PHLWINDOW&) { return false; }
bool fullscreenTarget(const PHLWINDOW&) { return false; }
bool applyConstrainedFullscreen(const PHLWINDOW&,Mode) { assert(false);return false; }
void endInteraction(const std::string&) { assert(false); }
void cancelFullscreenResize(const PHLWINDOW&) {}
void originalSetter(Fullscreen::CFullscreenController*,PHLWINDOW window,std::optional<Mode> internal,std::optional<Mode> client,std::optional<bool>) {
 ++forwards;
 if(internal)window->internal=*internal;
 if(client)setClientFullscreen(window,*client);
}
struct Hook { void* m_original = reinterpret_cast<void*>(&originalSetter); } hook;
Hook* fullscreenModeHook = &hook;
'''

CALLER = r'''
int main() {
 auto source=std::make_shared<Window>(), other=std::make_shared<Window>();
 const Identity identity{"exact-source",source};
 interaction=Interaction{identity};
 setFullscreenMode(Fullscreen::controller(),source,std::nullopt,Fullscreen::FSMODE_FULLSCREEN,std::nullopt);
 assert(!interaction && endedInteractions.size()==1);
 assert(source->internal==Fullscreen::FSMODE_NONE && source->client==Fullscreen::FSMODE_FULLSCREEN);
 assert(forwards==0 && clientConfigures==std::vector<Mode>{Fullscreen::FSMODE_FULLSCREEN});
 auto& ended=endedInteractions.front();
 assert(ended.desktopFullscreen->originalClient==Fullscreen::FSMODE_NONE && pendingDesktopFullscreen(ended));
 // Restoration's explicit layout/client maintenance cannot cancel the ACK.
 setFullscreenMode(Fullscreen::controller(),source,Fullscreen::FSMODE_NONE,Fullscreen::FSMODE_NONE,std::nullopt);
 setFullscreenMode(Fullscreen::controller(),source,Fullscreen::FSMODE_MAXIMIZED,Fullscreen::FSMODE_MAXIMIZED,std::nullopt);
 assert(forwards==0 && source->internal==Fullscreen::FSMODE_NONE && source->client==Fullscreen::FSMODE_FULLSCREEN);
 // A repeated real application request retains the original cleanup mode.
 setFullscreenMode(Fullscreen::controller(),source,std::nullopt,Fullscreen::FSMODE_FULLSCREEN,std::nullopt);
 assert(ended.desktopFullscreen->originalClient==Fullscreen::FSMODE_NONE);
 // An unrelated window keeps its ordinary compositor path.
 setFullscreenMode(Fullscreen::controller(),other,Fullscreen::FSMODE_MAXIMIZED,Fullscreen::FSMODE_MAXIMIZED,std::nullopt);
 assert(forwards==1 && other->internal==Fullscreen::FSMODE_MAXIMIZED);
 // Reload/manual cancellation/expiry share the same acknowledged cleanup.
 ended.handoffDeadline=Clock::now()-std::chrono::seconds(1);
 assert(!pendingDesktopFullscreen(ended));
 clearDesktopFullscreen(ended);
 assert(!ended.desktopFullscreen && !ended.restoreRequested && ended.handedOff);
 assert(cleanupAcks==1 && source->client==Fullscreen::FSMODE_NONE && fullscreenWindows.empty());
 // A later public fullscreen owner must never be overwritten by old cleanup.
 ended.restoreRequested=true;ended.handedOff=false;ended.desktopFullscreen=DesktopFullscreenRequest{std::nullopt,Fullscreen::FSMODE_FULLSCREEN,std::nullopt};
 source->internal=Fullscreen::FSMODE_FULLSCREEN;source->client=Fullscreen::FSMODE_FULLSCREEN;
 clearDesktopFullscreen(ended);
 assert(source->internal==Fullscreen::FSMODE_FULLSCREEN && source->client==Fullscreen::FSMODE_FULLSCREEN && cleanupAcks==1);
 // Revoked/replaced identity cannot receive the old request's cleanup.
 ended.desktopFullscreen=DesktopFullscreenRequest{std::nullopt,Fullscreen::FSMODE_FULLSCREEN,std::nullopt};
 source->internal=Fullscreen::FSMODE_NONE;source->owned=false;
 clearDesktopFullscreen(ended);
 assert(source->client==Fullscreen::FSMODE_FULLSCREEN && cleanupAcks==1);
 source->owned=true;source->client=Fullscreen::FSMODE_NONE;
 // App-origin cancellation is acknowledged and lets saved normal/maximized
 // restoration proceed; it must not resurrect the deferred fullscreen intent.
 endedInteractions.clear();interaction=Interaction{identity};
 setFullscreenMode(Fullscreen::controller(),source,std::nullopt,Fullscreen::FSMODE_FULLSCREEN,std::nullopt);
 setFullscreenMode(Fullscreen::controller(),source,std::nullopt,Fullscreen::FSMODE_NONE,std::nullopt);
 assert(source->client==Fullscreen::FSMODE_NONE && source->internal==Fullscreen::FSMODE_NONE);
 setFullscreenMode(Fullscreen::controller(),source,Fullscreen::FSMODE_MAXIMIZED,Fullscreen::FSMODE_MAXIMIZED,std::nullopt);
 assert(source->internal==Fullscreen::FSMODE_MAXIMIZED && source->client==Fullscreen::FSMODE_MAXIMIZED);
}
'''

@unittest.skipUnless(shutil.which('c++'), 'Desktop fullscreen regression requires a C++ compiler')
class DesktopFullscreenNativeTests(unittest.TestCase):
    def test_client_ack_precedes_handoff_and_cleanup_preserves_exact_identity_and_newer_owners(self):
        functions='\n'.join(production_function(result,name) for result,name in (
            ('bool','pendingDesktopFullscreen'),('void','clearDesktopFullscreen'),('void','setFullscreenMode')))
        with tempfile.TemporaryDirectory(prefix='stash-desktop-fullscreen-') as temporary:
            source,binary=Path(temporary)/'test.cpp',Path(temporary)/'test'
            source.write_text(PRELUDE+functions+CALLER)
            compiled=subprocess.run(['c++','-std=c++20','-O1','-g','-fsanitize=address',
                                     '-fno-omit-frame-pointer','-fno-pie','-no-pie',str(source),'-o',str(binary)],
                                    capture_output=True,text=True,timeout=30)
            self.assertEqual(compiled.returncode,0,compiled.stderr)
            result=subprocess.run([str(binary)],capture_output=True,text=True,timeout=10,
                                  env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0:halt_on_error=1'))
            self.assertEqual(result.returncode,0,result.stderr)
