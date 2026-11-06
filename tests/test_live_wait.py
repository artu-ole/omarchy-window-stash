"""No-input checks for bounded shell-status polling across shell restarts."""
import subprocess
import unittest
from unittest.mock import Mock, patch

import live


class LiveWaitTests(unittest.TestCase):
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
