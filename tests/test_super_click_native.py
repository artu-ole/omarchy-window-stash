"""Run the production Super-click routing against a compositor boundary stub."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from test_fullscreen_native_memory import production_function


ROOT = Path(__file__).resolve().parents[1]

PRELUDE = r'''
#include <algorithm>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <functional>
#include <memory>
#include <optional>
#include <set>
#include <string>
#include <vector>
template<class T> using SP = std::shared_ptr<T>;
template<class T> using WP = std::weak_ptr<T>;
struct Vector2D { double x = 0, y = 0; };
struct CWLSurfaceResource { bool m_mapped = true; };
namespace Desktop::View {
struct View { virtual ~View() = default; };
struct CWLSurface {
 SP<CWLSurfaceResource> root;
 SP<View> owner;
 static SP<CWLSurface> current;
 static SP<CWLSurface> fromResource(SP<CWLSurfaceResource> resource) {
  return current && current->root == resource ? current : nullptr;
 }
 SP<View> view() const { return owner; }
 SP<CWLSurfaceResource> resource() const { return root; }
};
SP<CWLSurface> CWLSurface::current;
struct CLayerSurface : View {
 bool m_mapped = true, visible = true;
 std::string m_namespace = "omarchy-window-stash-interactive-previews";
 SP<CWLSurface> root;
 bool aliveAndVisible() const { return visible; }
 SP<CWLSurface> wlSurface() const { return root; }
 static SP<CLayerSurface> fromView(SP<View> view) { return std::dynamic_pointer_cast<CLayerSurface>(view); }
};
}
struct Input {
 bool constrained = false;
 std::vector<int> m_exclusiveLSes;
 uint32_t modifiers = 64;
 Vector2D position{300,200};
 bool isConstrained() const { return constrained; }
 uint32_t getModsFromAllKBs() const { return modifiers; }
 Vector2D getMouseCoordsInternal() const { return position; }
};
struct SeatGrab { bool m_pointer = true; };
struct Seat { struct { WP<CWLSurfaceResource> pointerFocus; } m_state; SP<SeatGrab> m_seatGrab; };
struct Lock { bool locked = false; bool isSessionLocked() const { return locked; } };
struct Drag { bool dragging = false; void* target() const { return dragging ? (void*)this : nullptr; } };
struct Layout { Drag drag; Drag* dragController() { return &drag; } };
struct IPCEvent { std::string name, payload; };
struct EventManager {
 std::vector<IPCEvent> events;
 std::function<void()> onPost;
 void postEvent(IPCEvent event) { events.push_back(event); if (onPost) onPost(); }
};
auto g_pInputManager = std::make_unique<Input>();
auto g_pSeatManager = std::make_unique<Seat>();
auto g_pSessionLockManager = std::make_unique<Lock>();
auto g_layoutManager = std::make_unique<Layout>();
auto g_pEventManager = std::make_unique<EventManager>();
struct PressedKey { std::string keyName; };
struct KeybindManager { std::vector<PressedKey> m_pressedKeys; };
auto g_pKeybindManager = std::make_unique<KeybindManager>();
struct Interaction { std::set<uint32_t> buttons; };
std::optional<Interaction> interaction;
std::set<uint32_t> releasedButtons;
bool endingInteraction = false, reloadPending = false, activeContentHit = false;
bool contentHit(const Vector2D&) { return activeContentHit; }
constexpr uint32_t WL_POINTER_BUTTON_STATE_RELEASED = 0, WL_POINTER_BUTTON_STATE_PRESSED = 1;
struct IPointer { struct SButtonEvent { uint32_t button, state; }; };
namespace Event { struct SCallbackInfo { bool cancelled = false; }; }
'''

CALLER = r'''
int main() {
 using namespace Desktop::View;
 auto source = std::make_shared<CWLSurfaceResource>();
 auto wrapper = std::make_shared<CWLSurface>();
 auto layer = std::make_shared<CLayerSurface>();
 wrapper->root = source; wrapper->owner = layer; layer->root = wrapper;
 CWLSurface::current = wrapper; g_pSeatManager->m_state.pointerFocus = source;
 auto press = [] { Event::SCallbackInfo info; bool result = superClickButton({272,1},info); assert(result == info.cancelled); return result; };
 auto release = [] { Event::SCallbackInfo info; bool result = superClickButton({272,0},info); assert(result == info.cancelled); return result; };
 auto lastPhase = [] { auto& event = g_pEventManager->events.back(); assert(event.name == "window-stash-super-click"); return event.payload.substr(event.payload.find(',')+1).substr(0,event.payload.substr(event.payload.find(',')+1).find(',')); };
 assert(superClickSurface() == source);
 assert(press() && superClickGesture && superClickGesture->serial == 1 && lastPhase() == "press");
 g_pInputManager->modifiers = 0; // Super may be released before the mouse.
 assert(release() && !superClickGesture && lastPhase() == "release");
 assert(!release() && g_pEventManager->events.size() == 2);
 // The compositor's real modifier mask, not a Qt/focused-client flag, decides.
 for (uint32_t modifiers : {0U,1U,4U,8U,65U,68U,72U,77U}) {
  g_pInputManager->modifiers = modifiers; assert(!press() && !superClickGesture);
 }
 g_pInputManager->modifiers = 64 | 2 | 16; // Lock modifiers do not change chord.
 assert(press()); assert(release() && lastPhase() == "release");
 g_pInputManager->modifiers = 64;
 // Motion belongs to the same serial. A drag never turns back into click
 // activation after returning to its starting point.
 assert(press()); auto dragSerial = superClickGesture->serial;
 superClickMotion({307,200},true); assert(lastPhase() == "move" && superClickGesture->serial == dragSerial);
 superClickMotion({300,200},true); assert(lastPhase() == "move");
 assert(release() && lastPhase() == "drag-release");
 assert(press()); superClickMotion({303,204},true); assert(lastPhase() == "move");
 assert(release() && lastPhase() == "release");
 // Another physical button can follow its normal route but cancels activation.
 assert(press()); Event::SCallbackInfo other;
 assert(!superClickButton({273,1},other) && !other.cancelled);
 assert(release() && lastPhase() == "cancel");
 // Only a real mapped root of the dedicated layer participates; a similarly
 // named popup, ordinary layer/window or stale pointer surface never arms it.
 layer->m_namespace = "omarchy-window-stash"; assert(!press());
 layer->m_namespace = "omarchy-window-stash-interactive-previews";
 auto alternate = std::make_shared<CWLSurfaceResource>();
 layer->root = std::make_shared<CWLSurface>(); layer->root->root = alternate;
 assert(!press()); layer->root = wrapper;
 source->m_mapped = false; assert(!press()); source->m_mapped = true;
 layer->m_mapped = false; assert(!press()); layer->m_mapped = true;
 layer->visible = false; assert(!press()); layer->visible = true;
 wrapper->owner = std::make_shared<View>(); assert(!press()); wrapper->owner = layer;
 g_pSeatManager->m_state.pointerFocus = alternate; assert(!press());
 g_pSeatManager->m_state.pointerFocus = source;
 // A fast resize can outrun the previous frame's input region. The scoped
 // stream continues while the original layer remains valid, without allowing
 // focus loss to replay click activation if the pointer returns.
 assert(press()); g_pSeatManager->m_state.pointerFocus = alternate; superClickMotion({340,240},true);
 assert(lastPhase() == "move" && !superClickGesture->cancelled && superClickGesture->clickCancelled);
 g_pSeatManager->m_state.pointerFocus = source; assert(release() && lastPhase() == "drag-release");
 assert(press()); g_pSeatManager->m_state.pointerFocus = alternate; superClickMotion({300,200},true);
 g_pSeatManager->m_state.pointerFocus = source; assert(release() && lastPhase() == "cancel");
 assert(press()); cancelSuperClick(); assert(superClickGesture);
 auto cancelledCount = g_pEventManager->events.size(); superClickMotion({350,250},true);
 assert(g_pEventManager->events.size() == cancelledCount);
 assert(release() && lastPhase() == "cancel");
 // Losing mapping, namespace or the exact root cancels a held drag even if
 // ordinary pointer focus has already left it.
 for (int change = 0; change < 3; ++change) {
  assert(press()); g_pSeatManager->m_state.pointerFocus = alternate;
  if (change == 0) source->m_mapped = false;
  if (change == 1) layer->m_namespace = "other";
  if (change == 2) layer->root->root = alternate;
  superClickMotion({350,250},true); assert(superClickGesture->cancelled && lastPhase() == "press");
  assert(release() && lastPhase() == "cancel");
  source->m_mapped = true; layer->m_namespace = "omarchy-window-stash-interactive-previews";
  layer->root->root = source; g_pSeatManager->m_state.pointerFocus = source;
 }
 // Native reload/lock/exclusive/constraint/drag are fail-closed. A reload that
 // is cancelled while held must not replay the previously invalidated click.
 auto blocked = [&](bool& flag) { flag = true; assert(!press()); flag = false; };
 blocked(endingInteraction); blocked(reloadPending);
 blocked(g_pSessionLockManager->locked); blocked(g_pInputManager->constrained);
 blocked(g_layoutManager->drag.dragging);
 g_pInputManager->m_exclusiveLSes.push_back(1); assert(!press()); g_pInputManager->m_exclusiveLSes.clear();
 g_pSeatManager->m_seatGrab = std::make_shared<SeatGrab>(); assert(!press()); g_pSeatManager->m_seatGrab.reset();
 // Selecting B while A remains interactive is valid only outside A's content
 // and implicit grab, with no other ordinary or synthesized button held. The
 // existing lease is not ended early: frontend replacement owns that handoff.
 interaction.emplace(); assert(press() && interaction);
 assert(release() && lastPhase() == "release" && interaction);
 interaction->buttons.insert(272); assert(!press()); interaction->buttons.clear();
 activeContentHit = true; assert(!press()); activeContentHit = false;
 interaction.reset();
 g_pKeybindManager->m_pressedKeys.push_back({"mouse:274"}); assert(!press());
 g_pKeybindManager->m_pressedKeys.clear();
 releasedButtons.insert(272); assert(!press()); releasedButtons.clear();
 g_pKeybindManager->m_pressedKeys.push_back({"A"}); assert(press());
 assert(release() && lastPhase() == "release"); g_pKeybindManager->m_pressedKeys.clear();
 assert(press()); reloadPending = true; cancelSuperClick(); reloadPending = false;
 assert(superClickGesture && release() && lastPhase() == "cancel");
 assert(press()); superClickMotion({350,250},true); assert(lastPhase() == "move");
 reloadPending = true; superClickMotion({360,260},true);
 assert(superClickGesture->cancelled && release() && lastPhase() == "cancel"); reloadPending = false;
 assert(press()); g_pSessionLockManager->locked = true;
 assert(release() && lastPhase() == "cancel"); g_pSessionLockManager->locked = false;
 // Even an expired weak surface cannot compare equal to an absent focus and
 // accidentally validate a click. No source or replacement is ever targeted.
 assert(press()); wrapper->root.reset(); source.reset();
 assert(release() && lastPhase() == "cancel");
 source = std::make_shared<CWLSurfaceResource>(); wrapper->root = source;
 g_pSeatManager->m_state.pointerFocus = source;
 // Reserved zero serial is skipped at wraparound; duplicate left presses do
 // not replace the original pair or emit another activation request.
 superClickSerial = UINT32_MAX;
 assert(press() && superClickGesture->serial == 1);
 auto count = g_pEventManager->events.size(); assert(press());
 assert(g_pEventManager->events.size() == count && release() && lastPhase() == "cancel");
 // Other plugin cancellation is respected. IPC cancellation is safe even if
 // an event callback replaces native gesture state after it is serialized.
 Event::SCallbackInfo cancelled{true};
 assert(!superClickButton({272,1},cancelled) && !superClickGesture);
 assert(press()); g_pEventManager->onPost = [] { superClickGesture.reset(); };
 assert(release() && !superClickGesture && lastPhase() == "release");
 g_pEventManager->onPost = {};
 layer->root.reset(); wrapper->owner.reset(); CWLSurface::current.reset();
}
'''


@unittest.skipUnless(shutil.which('c++'), 'Native Super-click routing requires a C++ compiler')
class SuperClickNativeTests(unittest.TestCase):
    def test_exact_layer_chord_pairing_cancellation_and_lifecycle(self):
        source = (ROOT/'native/preview.cpp').read_text()
        structure = re.search(r'^struct SuperClickGesture \{.*?^\};', source, re.M | re.S)[0]
        state = '\nstd::optional<SuperClickGesture> superClickGesture;\nuint32_t superClickSerial = 0;\n'
        functions = ''.join(production_function(result, name)+'\n' for result, name in (
            ('bool', 'superClickBlocked'), ('bool', 'superClickSurfaceValid'),
            ('SP<CWLSurfaceResource>', 'superClickSurface'), ('void', 'emitSuperClick'),
            ('void', 'cancelSuperClick'), ('void', 'superClickMotion'), ('bool', 'superClickButton')))
        with tempfile.TemporaryDirectory(prefix='stash-super-click-native-') as temporary:
            test_source, binary = Path(temporary)/'test.cpp', Path(temporary)/'test'
            test_source.write_text(PRELUDE+structure+state+functions+CALLER)
            compiled = subprocess.run(['c++', '-std=c++20', '-O1', '-g', '-fsanitize=address',
                                       '-fno-omit-frame-pointer', '-Wall', '-Wextra', '-Werror',
                                       str(test_source), '-o', str(binary)], capture_output=True, text=True, timeout=30)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10,
                                    env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0:halt_on_error=1'))
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
