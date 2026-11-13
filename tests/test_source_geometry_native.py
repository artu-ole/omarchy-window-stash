"""Check the production source-readiness query without a compositor session."""
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
#include <limits>
#include <memory>
#include <string>
#include <unordered_map>
struct Vector2D {
 double x = 0, y = 0;
 Vector2D& operator/=(double value) { x /= value; y /= value; return *this; }
 bool operator==(const Vector2D&) const = default;
};
namespace Desktop::View {
 struct IGeometric { enum { GEOMETRIC_GOAL, GEOMETRIC_CURRENT }; };
}
struct Box {
 Vector2D dimensions{800,600};
 Vector2D size() const { return dimensions; }
 Vector2D pos() const { return {}; }
};
struct Root {
 bool m_mapped = true;
 struct State {
  Vector2D size{800,600}, ackedSize{800,600};
  std::shared_ptr<int> texture = std::make_shared<int>(1);
 } m_current;
 Box extends() const { return {m_current.size}; }
};
struct WLSurface {
 std::shared_ptr<Root> root = std::make_shared<Root>();
 std::shared_ptr<Root> resource() const { return root; }
};
struct XDG { struct { Box geometry; } m_current; };
struct Rule {
 bool noShare = false;
 struct Value { bool value; bool valueOrDefault() const { return value; } };
 Value noScreenShare() const { return {noShare}; }
 struct Tags {
  std::string tag = "window-stash-owned";
  bool isTagged(const std::string& requested, bool) const { return requested == tag; }
 } m_tagKeeper;
};
struct Workspace { std::string m_name = "special:window-stash"; };
struct CWindow {
 bool m_isMapped = true, m_isFloating = true, m_isX11 = false;
 uint64_t m_stableID = 77;
 int pid = 31, internal = 0, client = 2;
 double m_X11SurfaceScaledBy = 1;
 Vector2D goal{800,600}, current{800,600}, reported{800,600};
 std::shared_ptr<Rule> m_ruleApplicator = std::make_shared<Rule>();
 std::shared_ptr<Workspace> m_workspace = std::make_shared<Workspace>();
 std::shared_ptr<XDG> m_xdgSurface = std::make_shared<XDG>();
 std::shared_ptr<WLSurface> surface = std::make_shared<WLSurface>();
 int getPID() const { return pid; }
 std::shared_ptr<WLSurface> wlSurface() const { return surface; }
 Vector2D size(int mode) const { return mode == Desktop::View::IGeometric::GEOMETRIC_GOAL ? goal : current; }
 Vector2D getReportedSize() const { return m_isX11 ? reported : surface->root->m_current.ackedSize; }
};
using PHLWINDOW = std::shared_ptr<CWindow>;
using PHLWINDOWREF = std::weak_ptr<CWindow>;
using pid_t = int;
constexpr auto WORKSPACE = "special:window-stash";
namespace Fullscreen {
 enum { FSMODE_NONE, FSMODE_MAXIMIZED, FSMODE_FULLSCREEN };
 struct Modes { int internal, client; };
 struct Controller { Modes getFullscreenModes(const PHLWINDOW& window) const { return {window->internal,window->client}; } };
 Controller* controller() { static Controller result; return &result; }
}
bool reloadPending = false;
enum class FullscreenResize { None, Exit, Nudge, Restore };
'''

CALLER = r'''
int main() {
 auto window = std::make_shared<CWindow>();
 Identity identity{"owned","window-stash-owned",reinterpret_cast<uintptr_t>(window.get()),31,77,window};
 auto& committed = window->surface->root->m_current;
 auto original = sourceGeometryDetails(identity);
 assert(original.ready && original.reason.empty());
 assert(original.size == (Vector2D{800,600}));
 assert(window->client == Fullscreen::FSMODE_FULLSCREEN && window->internal == Fullscreen::FSMODE_NONE);
 // A changed compositor goal and a fresh capture at that goal cannot prove
 // the client has processed its configure or supplied matching frame geometry.
 window->goal = {1200,600};
 assert(sourceGeometryDetails(identity).reason == "configure-pending");
 window->current = window->goal;
 assert(sourceGeometryDetails(identity).reason == "configure-pending");
 committed.ackedSize = window->goal;
 assert(sourceGeometryDetails(identity).reason == "frame-pending");
 window->m_xdgSurface->m_current.geometry.dimensions = window->goal;
 assert(sourceGeometryDetails(identity).reason == "frame-pending");
 committed.size = window->goal;
 assert(sourceGeometryDetails(identity).ready);
 // A configure acknowledged in an earlier surface commit cannot stand in
 // for a new target size, even when its aspect happens to be identical.
 window->goal = {600,300};
 window->current = window->goal;
 assert(sourceGeometryDetails(identity).reason == "configure-pending");
 committed.ackedSize = window->goal;
 window->m_xdgSurface->m_current.geometry.dimensions = window->goal;
 committed.size = {620,340}; // Committed CSD can extend outside window geometry.
 assert(sourceGeometryDetails(identity).ready);
 window->current = {601,300};
 assert(sourceGeometryDetails(identity).reason == "animation-pending");
 window->current = window->goal;
 // Clients that do not set XDG window geometry use committed logical surface
 // size; raw buffer pixels are deliberately absent from this readiness path.
 window->m_xdgSurface->m_current.geometry.dimensions = {};
 assert(sourceGeometryDetails(identity).reason == "frame-pending");
 committed.size = window->goal;
 assert(sourceGeometryDetails(identity).ready);
 committed.texture.reset();
 assert(sourceGeometryDetails(identity).reason == "surface-unavailable");
 committed.texture = std::make_shared<int>(1);
 // Ownership, privacy and a fullscreen cleanup transaction fail closed.
 window->m_workspace->m_name = "1";
 assert(sourceGeometryDetails(identity).reason == "window-unavailable");
 window->m_workspace->m_name = WORKSPACE;
 window->m_ruleApplicator->m_tagKeeper.tag.clear();
 assert(sourceGeometryDetails(identity).reason == "window-unavailable");
 window->m_ruleApplicator->m_tagKeeper.tag = identity.tag;
 window->pid++;
 assert(!sourceGeometryDetails(identity).ready);
 window->pid--;
 window->m_stableID++;
 assert(!sourceGeometryDetails(identity).ready);
 window->m_stableID--;
 window->m_ruleApplicator->noShare = true;
 assert(sourceGeometryDetails(identity).reason == "capture-unavailable");
 window->m_ruleApplicator->noShare = false;
 window->m_isFloating = false;
 assert(sourceGeometryDetails(identity).reason == "source-not-floating");
 window->m_isFloating = true;
 window->internal = Fullscreen::FSMODE_FULLSCREEN;
 assert(sourceGeometryDetails(identity).reason == "source-fullscreen");
 window->internal = Fullscreen::FSMODE_NONE;
 fullscreenTransitions.emplace(identity.id,Transition{identity,FullscreenResize::Nudge});
 assert(sourceGeometryDetails(identity).reason == "fullscreen-cleanup");
 fullscreenTransitions.clear();
 reloadPending = true;
 assert(sourceGeometryDetails(identity).reason == "support-reloading");
 reloadPending = false;
 // XWayland cannot use reported/configured size alone. Its committed logical
 // surface must match too, with force-zero-scaling normalized exactly once.
 window->m_isX11 = true;
 window->m_xdgSurface.reset();
 window->m_X11SurfaceScaledBy = 2;
 window->reported = {1200,600};
 committed.size = {800,600};
 assert(sourceGeometryDetails(identity).reason == "frame-pending");
 committed.size = {1200,600};
 const auto x11 = sourceGeometryDetails(identity);
 assert(x11.ready && x11.xwayland && x11.surface == window->goal && x11.configured == window->goal);
 window->reported = {800,600};
 assert(sourceGeometryDetails(identity).reason == "configure-pending");
 window->m_X11SurfaceScaledBy = std::numeric_limits<double>::quiet_NaN();
 assert(sourceGeometryDetails(identity).reason == "invalid-source-scale");
 window->m_X11SurfaceScaledBy = 0;
 assert(sourceGeometryDetails(identity).reason == "invalid-source-scale");
 // The query never clears client fullscreen or changes the source geometry.
 assert(window->goal == (Vector2D{600,300}));
 assert(window->client == Fullscreen::FSMODE_FULLSCREEN && window->internal == Fullscreen::FSMODE_NONE);
}
'''


@unittest.skipUnless(shutil.which('c++'), 'Native source readiness requires a C++ compiler')
class SourceGeometryNativeTests(unittest.TestCase):
    def test_committed_geometry_guards_input_without_mutating_source(self):
        source = (ROOT/'native/preview.cpp').read_text()
        structures = ''.join(re.search(r'^struct '+name+r' \{.*?^\};', source, re.M | re.S)[0]+'\n'
                             for name in ('Identity', 'SourceGeometry'))
        boundary = ('struct Transition { Identity identity; FullscreenResize resize; };\n'
                    'std::unordered_map<std::string,Transition> fullscreenTransitions;\n')
        implementation = production_function('bool', 'sameWindow')+production_function('SourceGeometry', 'sourceGeometryDetails')
        with tempfile.TemporaryDirectory(prefix='stash-source-geometry-') as temporary:
            folder = Path(temporary)
            test_source, binary = folder/'test.cpp', folder/'test'
            test_source.write_text(PRELUDE+structures+boundary+implementation+CALLER)
            compiled = subprocess.run(['c++', '-std=c++20', '-O1', '-Wall', '-Wextra', '-Werror',
                                       str(test_source), '-o', str(binary)], capture_output=True, text=True, timeout=30)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
