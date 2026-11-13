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
    @staticmethod
    def idle_status():
        return {'previewInteraction':{},'previewCompatibility':{},'surfaces':[]}

    def test_equal_window_counts_do_not_acknowledge_a_stale_snapshot(self):
        session=native_session.NativeSession()
        with patch.object(native_session,'shell',return_value={'windows':1,'windowIds':['old']}), \
                patch.object(native_session,'command',return_value={'windows':[{'id':'new'}]}):
            self.assertEqual(session.surface_records(),[])

    def test_only_acknowledged_record_ids_are_ready(self):
        session=native_session.NativeSession()
        records=[{'id':'first'},{'id':'new'},{'id':'last'}]
        with patch.object(native_session,'shell',return_value={'windows':2,'windowIds':['last','first']}), \
                patch.object(native_session,'command',return_value={'windows':records}):
            self.assertEqual(session.surface_records(),[records[0],records[2]])

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
                shell = Mock(return_value=self.idle_status())
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
                        patch.object(native_session, 'BridgeManager') as manager, \
                        patch.object(native_session, 'Stash', return_value=SimpleNamespace(positions=positions)):
                    manager.return_value.native.return_value={'available':False}
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
                                 [call('hoverPreview', 'off'), call('presentation', 'dock'),
                                  call('presentation', 'bubbles'), call('hoverPreview', 'off'), call('previewDelay', 400)])
                self.assertEqual(json.loads(positions.read_text()), {
                    'monitor': {'existing': [10, 20], 'untouched': [4, 5]},
                    'other-monitor': {'other': [3, 4]},
                })
                self.assertEqual(shell.call_args_list, [call('dismiss'), call('status'), call('refresh')])
                self.assertEqual(compositor.dispatch.call_args_list,
                                 [call('focus', workspace='7'), call('focus', window='address:0xoriginal')])
                self.assertEqual(command.call_args_list, [call('list'), call('list')])
                compositor.client.assert_any_call('0xtest')
                compositor.client.assert_any_call('0xoriginal')

    def test_capture_teardown_waits_for_worker_images_and_native_releases(self):
        states=[
            dict(self.idle_status(),previewInteraction={'pendingRequest':{'id':'next'}}),
            dict(self.idle_status(),previewInteraction={'running':True,'stopping':True}),
            dict(self.idle_status(),previewCompatibility={'running':True,'requestedIds':['owned']}),
            dict(self.idle_status(),surfaces=[{'floatingPreviews':{'cards':[{'image':{'captureActive':True}}]}}]),
            dict(self.idle_status(),surfaces=[{'preview':{'tiles':[{'image':{'captureActive':True}}]}}]),
        ]
        events=[]
        def shell(method):
            events.append(method)
            return states.pop(0) if method=='status' and states else self.idle_status()
        native=[{'available':True,'owners':1,'windows':1},
                {'available':True,'pendingButtons':1},
                {'available':True,'pendingKeys':1},
                {'available':True,'pendingFullscreen':1},
                {'available':True,'inputActive':False}]
        def status():
            events.append('native release' if len(native)==1 else 'native pending')
            return native.pop(0)
        with patch.object(native_session,'shell',side_effect=shell), \
                patch.object(native_session,'configure',side_effect=lambda key,value:events.append((key,value))), \
                patch.object(native_session,'BridgeManager') as manager, \
                patch('live.time.sleep'):
            manager.return_value.native.side_effect=status
            native_session.NativeSession().pause_captures()
        self.assertEqual(events[:3],['dismiss',('hoverPreview','off'),('presentation','dock')])
        self.assertEqual(events[3:9],['status']*6,'Native owners cannot acknowledge still-active shell captures')
        self.assertEqual(events[-1],'native release')
        self.assertEqual(manager.return_value.native.call_count,5)
        self.assertFalse(states or native)

    def test_pending_release_timeout_keeps_source_alive_and_closes_pointer(self):
        session=native_session.NativeSession()
        session.pointer=Mock()
        session.processes=[Mock()]
        def deadline(predicate,message):
            self.assertFalse(predicate(),'Pending physical release cannot acknowledge capture teardown')
            raise AssertionError(message)
        with patch.object(native_session,'shell',return_value=self.idle_status()), \
                patch.object(native_session,'configure'), \
                patch.object(native_session,'BridgeManager') as manager, \
                patch.object(native_session,'wait',side_effect=deadline):
            manager.return_value.native.return_value={'available':True,'pendingButtons':1}
            with self.assertRaisesRegex(AssertionError,'fixtures were left alive'):
                session.__exit__(None,None,None)
        session.processes[0].terminate.assert_not_called()
        session.processes[0].kill.assert_not_called()
        session.pointer.close.assert_called_once_with()
