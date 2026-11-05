"""No-input unit checks for the desktop test notification/countdown boundary."""
import contextlib
import io
import subprocess
import unittest
from unittest.mock import patch

from desktop_test import desktop_test


class DesktopTestCountdownTests(unittest.TestCase):
    def test_notice_and_full_countdown_precede_desktop_actions(self):
        events = []
        def notify(command, **kwargs):
            events.append('notice' if kwargs['check'] else 'finished')
        with patch('desktop_test.subprocess.run', side_effect=notify), \
                patch('desktop_test.time.sleep', side_effect=lambda seconds: events.append(seconds)), \
                contextlib.redirect_stdout(io.StringIO()):
            with desktop_test('Test'):
                events.append('desktop input')
        self.assertEqual(events, ['notice', 1, 1, 1, 1, 1, 'desktop input', 'finished'])

    def test_missing_notification_aborts_before_desktop_actions(self):
        with patch('desktop_test.subprocess.run', side_effect=subprocess.CalledProcessError(1, 'notify-send')), \
                patch('desktop_test.time.sleep') as sleep:
            with self.assertRaises(subprocess.CalledProcessError):
                with desktop_test('Test'):
                    self.fail('Desktop input must not run without the notice')
            sleep.assert_not_called()

    def test_completion_notice_is_sent_after_test_failure(self):
        with patch('desktop_test.subprocess.run') as notify, patch('desktop_test.time.sleep'), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, 'test failed'):
                with desktop_test('Test'):
                    raise RuntimeError('test failed')
        self.assertIn('Desktop test ended with an error', notify.call_args.args[0])
