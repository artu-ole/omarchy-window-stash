"""Preparing Super-click support must never acquire hidden-window input."""
import contextlib
import io
import json
import re
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'controller'))
from interaction import CORNER_RESIZE_REQUIRED, InteractionBridge, SHORTCUT_REQUIRED, main
from stash import lua

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('lua'), 'Standalone Lua interpreter unavailable')
class ShortcutBridgeTests(unittest.TestCase):
    def native(self, capability, version=None, resize='true', interactive_resize='true'):
        version = version or (ROOT/'native/version.txt').read_text().strip()
        class Native:
            def eval(self, code):
                self.call('repl', code)

            def call(self, method, code):
                if method != 'repl':
                    raise AssertionError('Preparing support attempted '+method)
                prelude = ('local function forbidden() error("UNEXPECTED_INPUT_OR_RENDER_LEASE") end\n'
                    'hl={plugin={window_stash_preview={status=function() return {protocol=1,version='
                    + lua(version)+',capabilities={superClickActivation='+capability+',superCornerResize='+resize+',interactiveResize='+interactive_resize+'}} end,'
                    'update=forbidden,release=forbidden,interaction_update=forbidden,'
                    'interaction_release=forbidden,interaction_status=forbidden}}}\n')
                result = subprocess.run(['lua', '-'], input=prelude+'local value=(function()\n'+code
                                        +'\nend)();if value~=nil then print(value) end',
                                        text=True, capture_output=True, check=False)
                if result.returncode:
                    raise RuntimeError(result.stderr)
                return result.stdout.strip()

            def read(self, subject):
                raise AssertionError('Preparing an installed bridge attempted '+subject)
        return Native()

    def test_prepare_only_checks_the_loaded_capability_without_acquiring_input_or_rendering(self):
        bridge = InteractionBridge(self.native('true'))
        self.assertEqual(bridge.prepare_shortcut(), dict(state='ready'))
        self.assertEqual(bridge.prepare_shortcut(), dict(state='ready'))
        self.assertEqual(bridge.prepare_shortcut(resize=True), dict(state='ready', cornerResize=True, interactiveResize=True))

    def test_missing_or_non_boolean_capability_does_not_claim_shortcut_support(self):
        for capability in ('nil', 'false', '1', '"true"', '{}'):
            with self.subTest(capability=capability), self.assertRaisesRegex(RuntimeError, re.escape(SHORTCUT_REQUIRED)):
                InteractionBridge(self.native(capability)).prepare_shortcut()

    def test_legacy_bridge_is_preserved_and_reports_an_explicit_update_requirement(self):
        for version in ('1.29.1', '1.29.5', '1.29.6'):
            with self.subTest(version=version), self.assertRaisesRegex(RuntimeError, re.escape(SHORTCUT_REQUIRED)):
                InteractionBridge(self.native('nil', version)).prepare_shortcut()

    def test_free_corner_resize_requires_its_own_boolean_capability_without_breaking_old_clicks(self):
        for capability in ('nil', 'false', '1', '"true"', '{}'):
            with self.subTest(capability=capability):
                bridge = InteractionBridge(self.native('true', version='1.29.6', resize=capability))
                self.assertEqual(bridge.prepare_shortcut(), dict(state='ready'))
                with self.assertRaisesRegex(RuntimeError, re.escape(CORNER_RESIZE_REQUIRED)):
                    bridge.prepare_shortcut(resize=True)


    def test_active_resize_capability_is_strict_and_does_not_disable_ordinary_super_corners(self):
        for capability in ('nil', 'false', '1', '"true"', '{}', 'true'):
            with self.subTest(capability=capability):
                bridge = InteractionBridge(self.native('true', version='1.29.7', interactive_resize=capability))
                self.assertEqual(bridge.prepare_shortcut(resize=True),
                                 dict(state='ready', cornerResize=True, interactiveResize=capability == 'true'))
                self.assertEqual(bridge.prepare_shortcut(), dict(state='ready'))


class ShortcutPrepareCliTests(unittest.TestCase):
    def test_disabled_or_non_preview_settings_never_load_native_code(self):
        for presentation, enabled, sizing, lock in (('dock', 'on', 'free', 'unlocked'),
                ('floating', 'off', 'free', 'unlocked'), ('previews', 'off', 'preset', 'unlocked'),
                ('previews', 'off', 'free', 'locked')):
            with self.subTest(presentation=presentation, enabled=enabled, sizing=sizing, lock=lock), \
                    patch('sys.argv', ['interaction.py', '--prepare']), \
                    patch('interaction.signal.signal'), patch('interaction.Stash') as stash, \
                    patch('interaction.InteractionBridge') as bridge, \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                stash.return_value.settings.return_value = dict(presentation=presentation, floatingPreviewInteraction=enabled,
                                                                floatingPreviewSizing=sizing, floatingPreviewLock=lock)
                self.assertEqual(main(), 0)
                self.assertEqual(json.loads(output.getvalue()), dict(state='disabled'))
                bridge.assert_not_called()

    def test_free_unlocked_previews_prepare_resize_even_without_interactivity(self):
        for settings, resize in ((dict(floatingPreviewInteraction='off'), True),
                (dict(floatingPreviewInteraction='on', floatingPreviewSizing='preset'), False),
                (dict(floatingPreviewInteraction='on', floatingPreviewLock='locked'), False)):
            with self.subTest(settings=settings), patch('sys.argv', ['interaction.py', '--prepare']), \
                    patch('interaction.signal.signal'), patch('interaction.Stash') as stash, \
                    patch('interaction.InteractionBridge') as bridge, patch('interaction.run_loop') as loop, \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                stash.return_value.settings.return_value = dict(presentation='previews', **settings)
                ready = dict(state='ready', cornerResize=True, interactiveResize=True) if resize else dict(state='ready')
                bridge.return_value.prepare_shortcut.return_value = ready
                self.assertEqual(main(), 0)
                self.assertEqual(json.loads(output.getvalue()), ready)
                bridge.return_value.prepare_shortcut.assert_called_once_with(resize=resize)
                loop.assert_not_called()

    def test_prepare_uses_no_stdin_worker_and_reports_a_bridge_failure_without_input(self):
        for failure in (None, RuntimeError(SHORTCUT_REQUIRED)):
            with self.subTest(failure=failure), patch('sys.argv', ['interaction.py', '--prepare']), \
                    patch('interaction.signal.signal'), patch('interaction.Stash') as stash, \
                    patch('interaction.InteractionBridge') as bridge, patch('interaction.run_loop') as loop, \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                stash.return_value.settings.return_value = dict(presentation='previews', floatingPreviewInteraction='on')
                bridge.return_value.prepare_shortcut.return_value = dict(state='ready', cornerResize=True, interactiveResize=True)
                bridge.return_value.prepare_shortcut.side_effect = failure
                self.assertEqual(main(), 1 if failure else 0)
                self.assertEqual(json.loads(output.getvalue()),
                                 dict(state='unavailable', error=SHORTCUT_REQUIRED) if failure else dict(state='ready', cornerResize=True, interactiveResize=True))
                bridge.return_value.prepare_shortcut.assert_called_once_with(resize=True)
                loop.assert_not_called()
