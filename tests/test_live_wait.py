"""No-input checks for bounded shell-status polling across shell restarts."""
import subprocess
import unittest
from unittest.mock import Mock, patch

import live


class LiveWaitTests(unittest.TestCase):
    def test_surface_pointer_coordinates_include_other_outputs_and_scale(self):
        monitors=[dict(name='left',x=-1280,y=-100,width=1600,height=900,scale=1.25),
                  dict(name='main',x=0,y=0,width=1920,height=1080,scale=1)]
        with patch.object(live.h,'read',return_value=monitors):
            self.assertEqual(live.monitor_point({'name':'main'},120,180),(1400,280,3200,1180))
            self.assertEqual(live.monitor_point({'name':'left'},120,180),(120,180,3200,1180))

    def test_xwayland_uses_nested_compositor_display_and_authority(self):
        for authority in ('/run/user/1000/private-Xauthority','__window_stash_unset__'):
            with self.subTest(authority=authority), \
                    patch.dict(live.os.environ,{'DISPLAY':':1','XAUTHORITY':'/parent/authority'}), \
                    patch.object(live.h,'call',side_effect=[':7',authority]):
                environment=live.fixture_environment(True)
            self.assertEqual(environment['GDK_BACKEND'],'x11')
            self.assertEqual(environment['DISPLAY'],':7')
            if authority=='__window_stash_unset__':self.assertNotIn('XAUTHORITY',environment)
            else:self.assertEqual(environment['XAUTHORITY'],authority)

    def test_missing_xwayland_display_aborts_before_starting_client(self):
        with patch.object(live.h,'call',return_value='__window_stash_unset__'), \
                patch.object(live.subprocess,'Popen') as start:
            with self.assertRaisesRegex(AssertionError,'no XWayland display'):
                live.spawn('Owned XWayland fixture',True)
        start.assert_not_called()

    def test_wayland_fixture_does_not_query_or_replace_x11_environment(self):
        with patch.dict(live.os.environ,{'DISPLAY':':1','XAUTHORITY':'/parent/authority'}), \
                patch.object(live.h,'call') as compositor:
            environment=live.fixture_environment()
        self.assertEqual(environment['GDK_BACKEND'],'wayland')
        compositor.assert_not_called()

    def test_transient_shell_status_failure_retries_within_deadline(self):
        for command in (['omarchy-shell','window-stash','status'],
                        ('omarchy-shell','window-stash','status'),
                        ['/usr/bin/omarchy-shell','shell','call','community.window-switcher','status','']):
            with self.subTest(command=command):
                predicate=Mock(side_effect=[subprocess.CalledProcessError(1,command,output='Target not found.'),
                                            False,{'loaded':True}])
                with patch.object(live.time,'monotonic',side_effect=[0,0,.01,.02]), \
                        patch.object(live.time,'sleep') as sleep:
                    self.assertEqual(live.wait(predicate,'Not loaded',timeout=.1),{'loaded':True})
                self.assertEqual(predicate.call_count,3)
                self.assertEqual(sleep.call_count,2)

    def test_deadline_reports_last_shell_status_failure(self):
        error=subprocess.CalledProcessError(1,['omarchy-shell','window-stash','status'],stderr='Target not found.')
        with patch.object(live.time,'monotonic',side_effect=[0,0,.1]), patch.object(live.time,'sleep'):
            with self.assertRaisesRegex(AssertionError,'Not loaded; last shell status error: Target not found'):
                live.wait(Mock(side_effect=error),'Not loaded',timeout=.1)

    def test_non_polling_command_failures_are_not_retried(self):
        for command in (['hyprctl','clients','-j'], ['window-stash','list'],
                        ['omarchy-shell','window-stash','configure','sizePreset','100']):
            with self.subTest(command=command):
                error=subprocess.CalledProcessError(1,command)
                with patch.object(live.time,'monotonic',side_effect=[0,0]), \
                        patch.object(live.time,'sleep') as sleep:
                    with self.assertRaises(subprocess.CalledProcessError):
                        live.wait(Mock(side_effect=error),'Failed')
                sleep.assert_not_called()

    def test_unrelated_predicate_errors_are_not_retried(self):
        with patch.object(live.time,'monotonic',side_effect=[0,0]), patch.object(live.time,'sleep') as sleep:
            with self.assertRaisesRegex(ValueError,'Malformed status'):
                live.wait(Mock(side_effect=ValueError('Malformed status')),'Failed')
        sleep.assert_not_called()
