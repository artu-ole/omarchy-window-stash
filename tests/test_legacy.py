"""Recognize legacy integration conservatively before automatic retirement."""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"controller"))
from legacy import BEGIN, END, binding_block, integration_patches
from migration import _reverse_switcher


class LegacyRecognitionTests(unittest.TestCase):
    target = Path("/tmp/legacy plugin")
    binary = Path("/tmp/legacy command/window-stash")

    def marked(self, *lines):
        return "\n".join((BEGIN, *lines, END))+"\n"

    def call(self, chord="SUPER + A", description="Window Stash: minimize focused window", command=None):
        values = (chord, description, str(self.binary)+" minimize" if command is None else command)
        return "o.bind("+",".join(json.dumps(value) for value in values)+")"

    def parse(self, text):
        return binding_block(text, self.binary, self.target)

    def test_removed_legacy_actions_remain_explicitly_disabled(self):
        block = self.parse(self.marked(self.call(chord="super + shift + a")))
        self.assertEqual(block["legacy"], {"minimizeShortcut":"SUPER + SHIFT + A",
                                         "restoreLastShortcut":"", "restoreOldestShortcut":""})

    def test_literal_override_requires_its_following_owned_action(self):
        paired = self.marked('hl.unbind("SUPER + A");', self.call())
        self.assertEqual(self.parse(paired)["overrides"][0]["chord"], "SUPER + A")
        for text in (self.marked('hl.unbind("CTRL + F8")', self.call()),
                     self.marked(self.call(), 'hl.unbind("SUPER + A")'),
                     self.marked('hl.unbind("SUPER + A")', 'hl.unbind("super + a")', self.call())):
            with self.subTest(text=text), self.assertRaisesRegex(RuntimeError, "custom code"):
                self.parse(text)

    def test_similar_descriptions_and_commands_are_not_ownership_proof(self):
        for call in (self.call(description="Window Stash: another action"),
                     self.call(command=str(self.binary)+" minimize --extra"),
                     self.call(command="/tmp/other/window-stash minimize"),
                     self.call()+"; user_configuration()",
                     self.call()+"\n"+self.call()):
            with self.subTest(call=call), self.assertRaisesRegex(RuntimeError, "custom code"):
                self.parse(self.marked(call))

    def test_malformed_or_repeated_marker_sections_are_rejected(self):
        for text in (BEGIN+"\n", END+"\n", END+"\n"+BEGIN+"\n",
                     self.marked(self.call())+self.marked(self.call())):
            with self.subTest(text=text), self.assertRaisesRegex(RuntimeError, "Malformed"):
                self.parse(text)

    def test_loader_requires_exact_literal_path_and_no_mixed_binding_code(self):
        loader = 'dofile("/tmp/legacy plugin/controller/shortcuts.lua")'
        block = self.parse(self.marked('hl.unbind("SUPER + A")', loader))
        self.assertEqual(block["legacy"], {})  # Existing preferences remain authoritative.
        for lines in (('dofile("/tmp/other/controller/shortcuts.lua")',),
                      ('dofile(os.getenv("UNTRUSTED_LOADER"))',),
                      (loader, self.call()), (self.call(), loader), (loader, loader)):
            with self.subTest(lines=lines), self.assertRaisesRegex(RuntimeError, "custom code"):
                self.parse(self.marked(*lines))

    def test_generated_decimal_utf8_path_escapes_are_understood_without_execution(self):
        text = self.marked(r'dofile("/tmp/legacy \226\156\147/controller/shortcuts.lua")')
        block = binding_block(text, self.binary, Path("/tmp/legacy ✓"))
        self.assertEqual(block["legacy"], {})
        for invalid in (r'dofile("/tmp/legacy \999/controller/shortcuts.lua")',
                        r'dofile("/tmp/legacy \u2713/controller/shortcuts.lua")'):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(RuntimeError, "custom code"):
                self.parse(self.marked(invalid))

    def test_old_tag_filtered_switcher_patch_restores_its_original_code(self):
        original = '''// Unrelated code before
      minimized: toplevel && toplevel.minimized === true
// Unrelated code after
'''
        patched = '''// Unrelated code before
      stashManaged: workspaceName === "special:minimized" && Array.isArray(ipc.tags)
        && ipc.tags.some(function(tag) { return String(tag).indexOf("window-stash-") === 0 }),
      minimized: toplevel && toplevel.minimized === true
// Unrelated code after
'''
        changes = integration_patches()["components/WindowRecords.qml"]
        self.assertEqual(_reverse_switcher(patched.encode(), changes), original.encode())


if __name__ == "__main__":
    unittest.main()
