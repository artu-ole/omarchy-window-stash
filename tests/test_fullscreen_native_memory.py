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
    source = (ROOT/'native/preview.cpp').read_text()
    match = re.search(r'^bool clearConstrainedFullscreen\([^;\n]*\) \{', source, re.M)
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
struct FullscreenTransition {
 Identity identity;
 Fullscreen::eFullscreenMode client;
 Clock::time_point expires;
 Clock::time_point restoreRequested{};
 unsigned activationAllowance = 1;
 bool waitingAck = false;
};
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
