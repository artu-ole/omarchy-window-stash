"""Desktop cleanup remains available after the test pointer disconnects."""
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call, patch

import native_session


class NativeCleanupTests(unittest.TestCase):
    def test_disconnected_pointer_still_restores_desktop_state(self):
        for error in (BrokenPipeError('pointer disconnected'), RuntimeError('Wayland protocol error')):
            with self.subTest(error=type(error).__name__), tempfile.TemporaryDirectory(prefix='stash-cleanup-unit-') as directory:
                positions = Path(directory)/'positions.json'
                positions.write_text(json.dumps({
                    'monitor': {'existing': [999, 888], 'test:new': [7, 8], 'untouched': [4, 5]},
                    'temporary-monitor': {'test:virtual': [1, 2]},
                    'other-monitor': {'other': [3, 4]},
                }))
                pointer = Mock(spec=['button', 'close'])
                pointer.button.side_effect = error
                process = Mock(spec=['poll', 'terminate', 'wait', 'kill'])
                process.poll.return_value = None
                process.wait.return_value = 0
                exited = Mock(spec=['poll', 'terminate', 'wait', 'kill'])
                exited.poll.return_value = 0
                exited.wait.return_value = 0
                slow = Mock(spec=['poll', 'terminate', 'wait', 'kill'])
                slow.poll.return_value = None
                slow.wait.side_effect = [subprocess.TimeoutExpired('owned fixture', 3), 0]
                compositor = Mock(spec=['client', 'call', 'dispatch'])
                compositor.client.side_effect = lambda address: {'address': address} if address == '0xoriginal' else None
                shell = Mock()
                command = Mock(return_value={'windows': [{'id': 'baseline-window'}]})
                configure = Mock()
                session = native_session.NativeSession()
                session.pointer = pointer
                session.processes = [process, exited, slow]
                session.addresses = ['0xtest']
                session.outputs = ['temporary-output']
                session.settings = {'presentation': 'bubbles', 'hoverPreview': 'off', 'previewDelay': 400}
                session.snapshot = {'positions': {'monitor': {'existing': [10, 20], 'untouched': [4, 5]}}}
                session.touched = {'monitor': {'existing', 'test:new'}, 'temporary-monitor': {'test:virtual'}}
                session.original_ws = 7
                session.original = {'address': '0xoriginal'}
                session.baseline = {'baseline-window'}

                with patch.object(native_session, 'h', compositor), \
                        patch.object(native_session, 'shell', shell), \
                        patch.object(native_session, 'command', command), \
                        patch.object(native_session, 'configure', configure), \
                        patch.object(native_session, 'Stash', return_value=SimpleNamespace(positions=positions)):
                    result = session.__exit__(type(error), error, None)

                self.assertIsNone(result, 'Cleanup must not suppress the original test failure')
                pointer.button.assert_called_once_with(False)
                pointer.close.assert_called_once_with()
                process.terminate.assert_called_once_with()
                process.wait.assert_called_once_with(timeout=3)
                exited.terminate.assert_not_called()
                exited.wait.assert_called_once_with(timeout=3)
                slow.terminate.assert_called_once_with()
                slow.kill.assert_called_once_with()
                self.assertEqual(slow.wait.call_args_list, [call(timeout=3), call(timeout=3)])
                compositor.call.assert_called_once_with('output', 'remove', 'temporary-output')
                self.assertEqual(configure.call_args_list,
                                 [call('presentation', 'bubbles'), call('hoverPreview', 'off'), call('previewDelay', 400)])
                self.assertEqual(json.loads(positions.read_text()), {
                    'monitor': {'existing': [10, 20], 'untouched': [4, 5]},
                    'other-monitor': {'other': [3, 4]},
                })
                self.assertEqual(shell.call_args_list, [call('dismiss'), call('refresh')])
                self.assertEqual(compositor.dispatch.call_args_list,
                                 [call('focus', workspace='7'), call('focus', window='address:0xoriginal')])
                self.assertEqual(command.call_args_list, [call('list'), call('list')])
                compositor.client.assert_any_call('0xtest')
                compositor.client.assert_any_call('0xoriginal')
