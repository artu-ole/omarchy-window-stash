"""Exercise the production fullscreen clear function under AddressSanitizer."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def production_clear():
    return production_function('bool', 'clearConstrainedFullscreen')


def production_function(result, name):
    source = (ROOT/'native/preview.cpp').read_text()
    match = re.search(r'^'+result+' '+name+r'\([^;\n]*\) \{', source, re.M)
    if match is None:
        raise AssertionError('Production fullscreen cleanup function was not found')
    level = 1
    cursor = match.end()
    while level:
        if source[cursor] == '{':
            level += 1
        elif source[cursor] == '}':
            level -= 1
        cursor += 1
    return source[match.start():cursor]


# Only the compositor boundary is replaced. The actual production cleanup
# function and its map-key caller execute unchanged; no desktop is accessed.
PRELUDE = r'''
#include <algorithm>
#include <cassert>
#include <chrono>
#include <cstdio>
#include <memory>
#include <string>
#include <unordered_map>
using Clock = std::chrono::steady_clock;
constexpr size_t MAX_WINDOWS = 256;
namespace Fullscreen {
enum eFullscreenMode { FSMODE_NONE, FSMODE_MAXIMIZED, FSMODE_FULLSCREEN };
}
struct Window { Fullscreen::eFullscreenMode client = Fullscreen::FSMODE_FULLSCREEN; };
struct Identity { std::string id; std::weak_ptr<Window> window; };
struct ConstrainedFullscreen {
 Identity identity;
 Fullscreen::eFullscreenMode originalClient;
 Fullscreen::eFullscreenMode client;
};
enum class FullscreenResize { None, Exit, Nudge, Restore };
struct FullscreenTransition {
 Identity identity;
 Fullscreen::eFullscreenMode client;
 Clock::time_point expires;
 Clock::time_point restoreRequested{};
 unsigned activationAllowance = 1;
 bool waitingAck = false;
 FullscreenResize resize = FullscreenResize::None;
 bool maximizeFollowupHandled = false;
};
using PHLWINDOW = std::shared_ptr<Window>;
std::unordered_map<std::string,ConstrainedFullscreen> fullscreenWindows;
std::unordered_map<std::string,FullscreenTransition> fullscreenTransitions;
void* clientFullscreenFunction = reinterpret_cast<void*>(1);
bool sameWindow(const Identity& identity, Window* window, bool) {
 return identity.window.lock().get() == window;
}
namespace Fullscreen {
struct Modes { eFullscreenMode internal; eFullscreenMode client; };
struct Controller {
 Modes getFullscreenModes(const std::shared_ptr<Window>& window) {
  return {FSMODE_NONE,window->client};
 }
};
Controller* controller() { static Controller result; return &result; }
}
void setClientFullscreen(const std::shared_ptr<Window>& window, Fullscreen::eFullscreenMode mode) {
 window->client = mode;
}
'''

RESIZE_PRELUDE = r'''
#include <algorithm>
#include <cassert>
#include <functional>
#include <memory>
#include <string>
#include <unordered_map>
#include <vector>
struct Vector2D {
 double x = 0, y = 0;
 bool operator==(const Vector2D&) const = default;
 Vector2D operator+(const Vector2D& other) const { return {x+other.x,y+other.y}; }
};
struct Animation { Vector2D size{1000,700}; Vector2D goal() const { return size; } };
std::function<void()> onSize;
struct Toplevel {
 std::vector<Vector2D> sizes;
 void setSize(Vector2D size) { sizes.push_back(size); if (onSize) onSize(); }
};
struct Surface { std::shared_ptr<Toplevel> m_toplevel = std::make_shared<Toplevel>(); };
struct Window {
 std::shared_ptr<Surface> m_xdgSurface = std::make_shared<Surface>();
 Animation animation;
 bool parked = true;
 Animation* sizeAnimation() { return &animation; }
};
using PHLWINDOW = std::shared_ptr<Window>;
struct Identity { std::string id; std::weak_ptr<Window> window; };
enum class FullscreenResize { None, Exit, Nudge, Restore };
struct FullscreenTransition {
 Identity identity;
 bool waitingAck = true;
 FullscreenResize resize = FullscreenResize::Exit;
 Vector2D clientSize{1000,700};
 Vector2D windowSize{1000,700};
};
std::unordered_map<std::string,FullscreenTransition> fullscreenTransitions;
bool sameWindow(const Identity& identity, Window* window, bool parked) {
 return identity.window.lock().get() == window && (!parked || window->parked);
}
void trackFullscreenConfigure(const std::string& id, const PHLWINDOW&) {
 if (const auto found = fullscreenTransitions.find(id); found != fullscreenTransitions.end())
  found->second.waitingAck = true;
}
void cancelFullscreenResize(const PHLWINDOW& window) {
 auto& value = fullscreenTransitions.at("owned");
 value.resize = FullscreenResize::None;
 window->m_xdgSurface->m_toplevel->setSize(window->animation.goal());
}
'''

RESIZE_CALLER = r'''
int main() {
 auto window = std::make_shared<Window>();
 auto& sizes = window->m_xdgSurface->m_toplevel->sizes;
 fullscreenTransitions.emplace("owned",FullscreenTransition{Identity{"owned",window}});
 // A stalled client must not be repeatedly resized or mistaken for completion.
 for (int i = 0; i < 100; ++i) synchronizeFullscreenResizes();
 assert(sizes.empty());
 fullscreenTransitions.at("owned").waitingAck = false;
 synchronizeFullscreenResizes();
 assert(sizes.size() == 1 && sizes.back() == (Vector2D{1000,701}));
 assert(window->animation.goal() == (Vector2D{1000,700}));
 for (int i = 0; i < 100; ++i) synchronizeFullscreenResizes();
 assert(sizes.size() == 1);
 fullscreenTransitions.at("owned").waitingAck = false;
 synchronizeFullscreenResizes();
 assert(sizes.size() == 2 && sizes.back() == (Vector2D{1000,700}));
 assert(fullscreenTransitions.at("owned").resize == FullscreenResize::Restore);
 fullscreenTransitions.at("owned").waitingAck = false;
 synchronizeFullscreenResizes();
 assert(fullscreenTransitions.at("owned").resize == FullscreenResize::None);
 synchronizeFullscreenResizes();
 assert(sizes.size() == 2);
 // An independent geometry change cancels the old transaction and configures
 // the new ordinary size; it must not restore the obsolete size afterwards.
 fullscreenTransitions.at("owned").resize = FullscreenResize::Exit;
 window->animation.size = {1000,800};
 synchronizeFullscreenResizes();
 assert(sizes.size() == 3 && sizes.back() == (Vector2D{1000,800}));
 assert(fullscreenTransitions.at("owned").resize == FullscreenResize::None);
 window->animation.size = {1000,700};
 // Relinquishing a stash tag must restore the original client's height even
 // when the last nudge configure has not yet been acknowledged.
 fullscreenTransitions.at("owned").resize = FullscreenResize::Nudge;
 fullscreenTransitions.at("owned").waitingAck = true;
 window->parked = false;
 synchronizeFullscreenResizes();
 assert(sizes.size() == 4 && sizes.back() == (Vector2D{1000,700}));
 assert(fullscreenTransitions.at("owned").resize == FullscreenResize::None);
 window->parked = true;
 // A configure callback may release ownership reentrantly.
 fullscreenTransitions.at("owned").resize = FullscreenResize::Exit;
 fullscreenTransitions.at("owned").waitingAck = false;
 onSize = [] { fullscreenTransitions.clear(); };
 synchronizeFullscreenResizes();
 assert(fullscreenTransitions.empty());
}
'''

CALLER = r'''
int main() {
 for (size_t index = 0; index < 10000; ++index) {
  fullscreenTransitions.clear();
  char buffer[33];
  std::snprintf(buffer,sizeof(buffer),"%032zx",index);
  const std::string id(buffer);
  auto window = std::make_shared<Window>();
  fullscreenWindows.emplace(id,ConstrainedFullscreen{Identity{id,window},Fullscreen::FSMODE_NONE,Fullscreen::FSMODE_FULLSCREEN});
  auto found = fullscreenWindows.find(id);
  assert(clearConstrainedFullscreen(found->first));
  assert(fullscreenWindows.empty());
  assert(window->client == Fullscreen::FSMODE_NONE);
  assert(fullscreenTransitions.contains(id));
 }
}
'''


@unittest.skipUnless(shutil.which('c++'), 'Native memory regression requires a C++ compiler')
class FullscreenNativeMemoryTests(unittest.TestCase):
    def test_passive_exit_consumes_one_owned_maximize_echo_without_changing_client_state(self):
        function = production_function('bool', 'consumePassiveMaximizeEcho')
        caller = r'''
int main() {
 auto window = std::make_shared<Window>();
 const std::string id = "owned";
 fullscreenTransitions.emplace(id,FullscreenTransition{Identity{id,window},Fullscreen::FSMODE_NONE,Clock::now()+std::chrono::seconds(1)});
 assert(!consumePassiveMaximizeEcho(std::make_shared<Window>()));
 assert(consumePassiveMaximizeEcho(window));
 assert(!consumePassiveMaximizeEcho(window));
 assert(fullscreenTransitions.at(id).client == Fullscreen::FSMODE_NONE);
 assert(window->client == Fullscreen::FSMODE_FULLSCREEN);
 auto& value = fullscreenTransitions.at(id);
 value.maximizeFollowupHandled = false;
 value.expires = Clock::now()-std::chrono::seconds(1);
 assert(!consumePassiveMaximizeEcho(window));
 value.waitingAck = true;
 assert(consumePassiveMaximizeEcho(window));
}
'''
        with tempfile.TemporaryDirectory(prefix='stash-fullscreen-echo-') as temporary:
            source, binary = Path(temporary)/'test.cpp', Path(temporary)/'test'
            source.write_text(PRELUDE+function+caller)
            compiled = subprocess.run(['c++', '-std=c++20', '-O1', '-g', '-fsanitize=address',
                                       '-fno-omit-frame-pointer', '-fno-pie', '-no-pie',
                                       str(source), '-o', str(binary)], capture_output=True, text=True, timeout=30)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10,
                                    env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0:halt_on_error=1'))
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_client_height_cleanup_waits_for_each_ack_without_changing_window_geometry(self):
        function = production_function('void', 'synchronizeFullscreenResizes')
        with tempfile.TemporaryDirectory(prefix='stash-fullscreen-resize-') as temporary:
            source, binary = Path(temporary)/'test.cpp', Path(temporary)/'test'
            source.write_text(RESIZE_PRELUDE+function+RESIZE_CALLER)
            compiled = subprocess.run(['c++', '-std=c++20', '-O1', '-g', '-fsanitize=address',
                                       '-fno-omit-frame-pointer', '-fno-pie', '-no-pie',
                                       str(source), '-o', str(binary)], capture_output=True, text=True, timeout=30)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10,
                                    env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0:halt_on_error=1'))
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_cleanup_owns_map_key_before_erasing_its_node(self):
        function = production_clear()
        with tempfile.TemporaryDirectory(prefix='stash-fullscreen-memory-') as temporary:
            folder = Path(temporary)
            for name, implementation, expected_success in (
                    ('production', function, True),
                    ('former-reference', function.replace('(std::string id)', '(const std::string& id)', 1), False)):
                with self.subTest(implementation=name):
                    source = folder/(name+'.cpp')
                    binary = folder/name
                    source.write_text(PRELUDE+implementation+CALLER)
                    compiled = subprocess.run(['c++', '-std=c++20', '-O1', '-g', '-fsanitize=address',
                                               '-fno-omit-frame-pointer', '-fno-pie', '-no-pie',
                                               str(source), '-o', str(binary)], capture_output=True, text=True, timeout=30)
                    self.assertEqual(compiled.returncode, 0, compiled.stderr)
                    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10,
                                            env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0:halt_on_error=1'))
                    if expected_success:
                        self.assertEqual(result.returncode, 0, result.stderr)
                    else:
                        self.assertNotEqual(result.returncode, 0, 'The fixture did not exercise the former dangling map key')
                        self.assertIn('heap-use-after-free', result.stderr)


if __name__ == '__main__':
    unittest.main()
