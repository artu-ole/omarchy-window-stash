"""Folded previews are display state; private sources and restore snapshots stay intact."""
import copy
import fcntl
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'controller'))
from stash import Hyprland, PLUGIN, SPECIAL, Stash, atomic_json, forward_shortcut, lua, main, preview_fold_ids
from bridge_runtime import BUSY, bridge_gate
from test_controller import FakeHypr, client


class FoldHypr(FakeHypr):
    def __init__(self):
        super().__init__()
        self.input_id = None
        self.on_validate = None
        self.validation_calls = 0
        self.released = []

    def preview_fold_ready(self, records, folding):
        self.validation_calls += 1
        if self.on_validate:
            self.on_validate(records)
        if folding and any(record['id'] == self.input_id for record in records):
            raise RuntimeError('Stop preview interaction before folding this window')
        return [record['id'] for record in records if (current := self.client(record['address']))
                and current['pid'] == record['pid'] and current['stableId'] == record['stableId']
                and record['tag'] in current['tags'] and current['workspace']['name'] == SPECIAL
                and current['mapped'] is True]

    def release_preview_geometry(self, ident):
        self.released.append(ident)


class PreviewFoldTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.hypr = FoldHypr()
        self.hypr.clients[0]['floating'] = True
        self.stash = Stash(self.hypr, self.root/'runtime', self.root/'shell.json', self.root/'state')
        self.settings()
        with self.stash.locked():
            self.first = self.stash.minimize('0x1')['id']
        self.original = copy.deepcopy(self.stash.state['windows'])
        self.hypr.commands.clear()

    def settings(self, **values):
        atomic_json(self.stash.config, dict(plugins=[dict(dict(id=PLUGIN, presentation='previews'), **values)]))

    def second(self, workspace=1):
        self.hypr.clients.append(client('0x2', workspace=workspace, pid=200))
        with self.stash.locked():
            return self.stash.minimize('0x2')['id']

    def invoke(self, arguments):
        with patch('stash.Stash', return_value=self.stash), patch('sys.stdout', new_callable=io.StringIO) as output:
            code = main(arguments)
        return code, json.loads(output.getvalue())

    def test_fold_and_unfold_only_change_strict_boolean_and_keep_client_fullscreen_and_restore_metadata(self):
        self.hypr.clients[0]['fullscreenClient'] = 2
        source = copy.deepcopy(self.hypr.clients)
        result = self.stash.preview_fold([self.first])
        self.assertEqual(result, dict(ok=True, action='preview-fold', ids=[self.first], previewFolded=True))
        self.assertEqual(self.stash.state['windows'], [dict(self.original[0], previewFolded=True)])
        self.assertEqual(self.hypr.clients, source)
        self.assertEqual(self.hypr.commands, [])
        self.assertEqual(self.hypr.released, [self.first])
        result = self.stash.preview_fold([self.first], False)
        self.assertEqual(result['action'], 'preview-unfold')
        self.assertEqual(self.stash.state['windows'], [dict(self.original[0], previewFolded=False)])
        self.assertEqual(self.hypr.clients, source)

    def test_persistence_and_idempotence_do_not_reorder_or_rewrite_saved_positions(self):
        second = self.second()
        original = copy.deepcopy(self.stash.state['windows'])
        atomic_json(self.stash.positions, {'output': {'preview:window:stable': [25, 50, 450, 1.8]}})
        positions = self.stash.positions.read_bytes()
        self.assertEqual(self.stash.preview_fold([second, self.first, second])['ids'], [second, self.first])
        saved = self.stash.path.read_bytes()
        self.assertEqual(self.stash.preview_fold([self.first, second])['action'], 'noop')
        self.assertEqual(self.stash.path.read_bytes(), saved)
        self.assertEqual(self.stash.positions.read_bytes(), positions)
        reloaded = Stash(self.hypr, self.stash.directory, self.stash.config, self.root/'state')
        with reloaded.locked():
            self.assertEqual(reloaded.state['windows'], [dict(record, previewFolded=True) for record in original])

    def test_group_fold_is_atomic_if_a_source_changes_between_snapshot_and_compositor_guard(self):
        second = self.second()
        before = self.stash.path.read_bytes()
        self.hypr.on_validate = lambda _: self.hypr.client('0x2')['tags'].clear()
        with self.assertRaisesRegex(RuntimeError, 'changed or left'):
            self.stash.preview_fold([self.first, second])
        self.assertEqual(self.stash.path.read_bytes(), before)
        self.assertFalse(any(record.get('previewFolded') is True for record in self.stash.state['windows']))
        self.assertEqual(self.hypr.validation_calls, 1)

    def test_wrong_identity_phase_private_workspace_or_mapped_state_never_folds(self):
        for mutation in ('pid', 'stableId', 'tag', 'workspace', 'mapped', 'phase', 'missing'):
            with self.subTest(mutation=mutation):
                self.hypr = FoldHypr();self.hypr.clients[0]['floating'] = True;self.stash.hypr = self.hypr
                self.hypr.clients[0].update(tags=[self.original[0]['tag']], workspace=dict(name=SPECIAL))
                atomic_json(self.stash.path, dict(version=1, windows=copy.deepcopy(self.original)))
                current = self.hypr.clients[0]
                ident = self.first
                if mutation == 'pid': current['pid'] += 1
                elif mutation == 'stableId': current['stableId'] = 'deadbeef'
                elif mutation == 'tag': current['tags'] = []
                elif mutation == 'workspace': current['workspace'] = dict(name='1')
                elif mutation == 'mapped': current['mapped'] = False
                elif mutation == 'phase':
                    data = json.loads(self.stash.path.read_text());data['windows'][0]['phase'] = 'restoring';atomic_json(self.stash.path, data)
                else: ident = 'f'*32
                before = self.stash.path.read_bytes()
                with self.assertRaisesRegex(RuntimeError, 'changed or left'):
                    self.stash.preview_fold([ident])
                self.assertEqual(self.stash.path.read_bytes(), before)

    def test_matching_native_input_blocks_fold_but_another_sources_input_is_not_touched(self):
        before = self.stash.path.read_bytes()
        self.hypr.input_id = self.first
        with self.assertRaisesRegex(RuntimeError, 'Stop preview interaction'):
            self.stash.preview_fold([self.first])
        self.assertEqual(self.stash.path.read_bytes(), before)
        self.hypr.input_id = 'f'*32
        self.assertEqual(self.stash.preview_fold([self.first])['action'], 'preview-fold')
        self.assertEqual(self.hypr.input_id, 'f'*32)

    def test_unfold_missing_closed_or_replaced_records_is_a_safe_noop(self):
        self.stash.preview_fold([self.first])
        before = self.stash.path.read_bytes()
        self.assertEqual(self.stash.preview_fold(['f'*32], False)['action'], 'noop')
        self.hypr.clients.clear()
        self.assertEqual(self.stash.preview_fold([self.first], False)['action'], 'noop')
        self.assertEqual(self.stash.path.read_bytes(), before)
        self.assertEqual(self.hypr.commands, [])

    def test_preview_mode_is_required_without_clearing_remembered_flags(self):
        self.stash.preview_fold([self.first])
        self.settings(presentation='dock')
        before = self.stash.path.read_bytes()
        with self.assertRaisesRegex(RuntimeError, 'only for floating previews'):
            self.stash.preview_fold([self.first])
        self.assertEqual(self.stash.preview_fold([self.first], False)['action'], 'noop')
        self.assertEqual(self.stash.path.read_bytes(), before)

    def test_folded_sources_cannot_start_or_poll_aspect_preparation(self):
        self.stash.preview_fold([self.first])
        before = self.stash.path.read_bytes()
        for action in (lambda: self.stash.preview_geometry(self.first),
                       lambda: self.stash.preview_aspect(self.first, 2, 'width')):
            with self.assertRaisesRegex(RuntimeError, 'Unfold this window'):
                action()
        self.assertEqual(self.stash.path.read_bytes(), before)
        self.assertEqual(self.hypr.commands, [])

    def test_bounds_duplicates_and_types_are_validated_before_any_client_read(self):
        self.assertEqual(preview_fold_ids([self.first, self.first]), [self.first])
        for values in (None, '', [], [True], [1], ['../'+self.first], ['A'*32], ['a'*31], [self.first]*257):
            with self.subTest(values=str(values)[:60]), self.assertRaises(ValueError):
                self.stash.preview_fold(values)
        for value in (None, 0, 1, 'true', [], {}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.stash.preview_fold([self.first], value)
        self.assertEqual(self.hypr.validation_calls, 0)

    def test_staged_newest_and_fifo_unfold_then_restore_same_window_in_original_order(self):
        for action in ('restore-last', 'restore-oldest'):
            with self.subTest(action=action):
                if action == 'restore-oldest':
                    self.setUp()
                second = self.second()
                self.stash.preview_fold([self.first, second])
                expected = second if action == 'restore-last' else self.first
                before = copy.deepcopy(self.hypr.clients)
                order = [(record['id'], record['order']) for record in self.stash.state['windows']]
                code, result = self.invoke([action, '--stage'])
                self.assertEqual((code, result['action'], result['id']), (0, 'preview-unfold', expected))
                self.assertEqual(self.hypr.clients, before)
                self.assertEqual([(record['id'], record['order']) for record in self.stash.state['windows']], order)
                self.assertEqual(self.invoke([action, '--stage'])[1]['id'], expected)
                self.assertNotEqual(self.hypr.client('0x2' if expected == second else '0x1')['workspace']['name'], SPECIAL)

    def test_plain_cli_restore_and_recovery_stay_full_even_when_folded(self):
        second = self.second()
        self.stash.preview_fold([self.first, second])
        self.assertEqual(self.invoke(['restore-last'])[1]['action'], 'restored')
        self.assertEqual(self.invoke(['restore-all'])[1]['results'][0]['action'], 'restored')
        self.assertEqual(self.stash.state['windows'], [])

    def test_stage_in_other_modes_is_a_full_restore(self):
        self.stash.preview_fold([self.first])
        self.settings(presentation='bubbles')
        self.assertEqual(self.invoke(['restore-oldest', '--stage'])[1]['action'], 'restored')

    def test_fold_uses_bridge_then_ledger_lock_and_releases_them_on_failure(self):
        class GatedHypr(FoldHypr, Hyprland): pass
        gated = GatedHypr();gated.clients = copy.deepcopy(self.hypr.clients);self.stash.hypr = gated
        environment = dict(XDG_RUNTIME_DIR=str(self.root/'bridge-runtime'), HYPRLAND_INSTANCE_SIGNATURE='fold-test')
        def verify(_):
            with self.assertRaisesRegex(RuntimeError, BUSY), bridge_gate(exclusive=True):
                self.fail('Native replacement overlapped a fold commit')
            with (self.stash.directory/'lock').open('a') as lock:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        gated.on_validate = verify
        with patch.dict(os.environ, environment):
            self.stash.preview_fold([self.first])
            with bridge_gate(exclusive=True):
                with self.assertRaisesRegex(RuntimeError, BUSY):
                    self.stash.preview_fold([self.first], False)
            gated.on_validate = lambda _: (_ for _ in ()).throw(RuntimeError('Source changed'))
            with self.assertRaisesRegex(RuntimeError, 'Source changed'):
                self.stash.preview_fold([self.first], False)
            with bridge_gate(exclusive=True):
                pass


class ShortcutForwardingTests(unittest.TestCase):
    def run_cli(self, arguments):
        with patch('sys.stdout', new_callable=io.StringIO) as output:
            code = main(arguments)
        return code, json.loads(output.getvalue())

    def test_managed_shortcuts_forward_before_constructing_or_locking_stash(self):
        for action, method in (('minimize', 'minimizeAt'), ('restore-last', 'restoreLast'), ('restore-oldest', 'restoreOldest')):
            with self.subTest(action=action), patch('stash.Stash') as stash, patch('stash.Hyprland') as hypr, \
                    patch('stash.subprocess.run', return_value=subprocess.CompletedProcess([], 0, '', '')) as invoke:
                hypr.return_value.read.return_value = dict(x=-1500.25, y=400.5)
                self.assertEqual(self.run_cli([action, '--shortcut'])[0], 0)
                expected = ['omarchy-shell', 'window-stash', method]+(['-1500.25', '400.5'] if action == 'minimize' else [])
                self.assertEqual(invoke.call_args.args[0], expected)
                self.assertNotIn('shell', invoke.call_args.kwargs)
                stash.assert_not_called()

    def test_explicit_selectors_are_never_silently_discarded_by_shortcut_routing(self):
        for arguments in (['minimize', '--address', '0x1'], ['restore-last', '--to', 'original'],
                          ['restore-last', '--monitor', 'test'], ['restore-oldest', '--workspace', '2'],
                          ['restore-last', '--stage']):
            with self.subTest(arguments=arguments), patch('stash.forward_shortcut') as forward, patch('stash.Stash') as stash:
                self.assertEqual(self.run_cli([*arguments, '--shortcut'])[0], 1)
                forward.assert_not_called();stash.assert_not_called()

    def test_missing_or_failed_shell_never_falls_back_to_minimizing_a_real_window(self):
        for failure in (FileNotFoundError('absent'), subprocess.TimeoutExpired([], 8),
                        subprocess.CompletedProcess([], 1, '', 'shell unavailable')):
            with self.subTest(failure=failure), patch('stash.Stash') as stash, patch('stash.Hyprland') as hypr, \
                    patch('stash.subprocess.run', side_effect=failure if isinstance(failure, BaseException) else None,
                          return_value=failure):
                hypr.return_value.read.return_value = dict(x=10, y=20)
                code, result = self.run_cli(['minimize', '--shortcut'])
                self.assertEqual(code, 1);self.assertFalse(result['ok']);stash.assert_not_called()

    def test_malformed_cursor_and_invalid_shell_responses_fail_without_dispatch(self):
        for point in (None, {}, dict(x=True, y=1), dict(x=float('nan'), y=1), dict(x=1_000_001, y=1), dict(x='$(cmd)', y=2)):
            with self.subTest(point=point), patch('stash.Hyprland') as hypr, patch('stash.subprocess.run') as invoke:
                hypr.return_value.read.return_value = point
                self.assertEqual(self.run_cli(['minimize', '--shortcut'])[0], 1);invoke.assert_not_called()
        for payload in ('[]', 'not json'):
            with self.subTest(payload=payload), patch('stash.subprocess.run', return_value=subprocess.CompletedProcess([], 0, payload, '')):
                with self.assertRaises((RuntimeError, ValueError)):
                    forward_shortcut('restore-last')


@unittest.skipUnless(shutil.which('lua'), 'Standalone Lua interpreter unavailable')
class FoldAdapterTests(unittest.TestCase):
    def native(self, active=None, changed=None):
        records = [dict(id=letter*32, address='0x'+str(index), pid=100+index,
                        stableId='a'+str(index), tag='window-stash-'+letter*32)
                   for index, letter in enumerate(('a', 'b'), 1)]
        sources = []
        for record in records:
            fields = ('pid='+str(record['pid'])+',stable_id='+str(int(record['stableId'], 16))
                      +',mapped=true,workspace={name='+lua(SPECIAL)+'},tags={'+lua(record['tag'])+'},fullscreen=0,fullscreenClient=2')
            sources.append('['+lua('address:'+record['address'])+']={'+fields+'}')
        prelude = ('local windows={'+','.join(sources)+'}\n'
                   +'hl={get_window=function(address) return windows[address] end,'
                   +'dispatch=function() error("UNEXPECTED_CLIENT_MUTATION") end,'
                   +'plugin={window_stash_preview={status=function() return {interaction={active='
                   +lua(active is not None)+',id='+lua(active)+'}} end}}}\n')
        if changed:
            prelude += changed+'\n'
        class Native(Hyprland):
            def __init__(self): self.calls = []
            def call(self, method, code):
                self.calls.append((method, code))
                if method != 'repl':
                    raise AssertionError('Unexpected compositor operation')
                result = subprocess.run(['lua', '-'], input=prelude+'local accepted=(function()\n'+code
                                        +'\nend)();print(accepted)', text=True, capture_output=True)
                if result.returncode:
                    raise RuntimeError(result.stderr)
                return result.stdout.strip()
        return Native(), records

    def test_batch_guard_is_one_readonly_lua_call_and_keeps_contained_fullscreen(self):
        native, records = self.native()
        self.assertEqual(native.preview_fold_ready(records, True), [record['id'] for record in records])
        self.assertEqual(len(native.calls), 1)
        self.assertNotIn('UNEXPECTED_CLIENT_MUTATION', native.calls[0][1])

    def test_matching_native_input_rejects_before_any_fold_while_other_input_is_untouched(self):
        native, records = self.native('a'*32)
        with self.assertRaisesRegex(RuntimeError, 'Stop preview interaction'):
            native.preview_fold_ready(records, True)
        self.assertEqual(native.preview_fold_ready(records, False), [record['id'] for record in records])
        native, records = self.native('c'*32)
        self.assertEqual(native.preview_fold_ready(records, True), [record['id'] for record in records])

    def test_atomic_guard_rejects_pid_stable_tag_unmapped_and_private_workspace_changes(self):
        for mutation in ('pid=999', 'stable_id=999', 'tags={}', 'mapped=false', 'workspace={name="1"}'):
            field, value = mutation.split('=', 1)
            with self.subTest(mutation=mutation):
                native, records = self.native(changed='windows["address:0x2"].'+field+'='+value)
                self.assertEqual(native.preview_fold_ready(records, True), [records[0]['id']])
