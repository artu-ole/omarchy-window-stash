"""Retire only known installer artifacts; keep user code and recovery bytes."""
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"controller"))
import migration
from legacy import BEGIN, END, integration_patches
from stash import lua
import shortcuts


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.config = self.home/"config"
        self.state = self.home/"state"
        self.target = self.config/"omarchy/plugins/community.window-stash"
        self.target.mkdir(parents=True)
        self.bindings = self.config/"hypr/bindings.lua"
        self.bindings.parent.mkdir()
        self.shell = self.config/"omarchy/shell.json"
        self.shell.write_text(json.dumps({"plugins":[{"id":migration.PLUGIN,"scope":"workspace"}],"other":{"keep":True}}))
        self.binary = self.home/".local/bin/window-stash"
        self.binary.parent.mkdir(parents=True)
        self.switcher = self.target.parent/"community.window-switcher"
        self.original = b'-- Owner prefix\r\n\r\n'
        self.suffix = b'\r\n-- Owner suffix\r\n'
        self.bindings.write_bytes(self.original+self.suffix)

    def tearDown(self):
        self.temp.cleanup()

    def invoke(self):
        return migration.migrate(self.target, self.home, self.config, self.state)

    def wrapper(self, extra=""):
        value = '#!/usr/bin/env python3\nimport runpy\nrunpy.run_path('+repr(str(self.target/"controller/stash.py"))+', run_name="__main__")\n'+extra
        self.binary.write_text(value)
        self.binary.chmod(0o755)

    def loader(self, overrides=True, newline="\r\n"):
        lines=[BEGIN]
        if overrides:
            lines += ['  -- Keep the operator\'s explicit override','  hl.unbind("SUPER + A");']
        lines += ['dofile('+lua(str(self.target/"controller/shortcuts.lua"))+')',END]
        self.bindings.write_bytes(self.original+(newline.join(lines)+newline).encode()+self.suffix)

    def switcher_files(self, newline="\n", legacy=False):
        originals={}
        for name, changes in integration_patches().items():
            path=self.switcher/name
            path.parent.mkdir(parents=True,exist_ok=True)
            text="\n".join(before for before,_ in changes)
            originals[name]=text.replace("\n",newline).encode()
            for before,after in changes:text=text.replace(before,after)
            if legacy:text=text.replace("special:window-stash","special:minimized").replace('"activate", address]','"restore", address]')
            path.write_bytes(text.replace("\n",newline).encode())
        return originals

    def test_fresh_cli_install_does_not_write_integrations_or_state(self):
        self.binary.write_text("#!/bin/sh\n# A separate user's command\n")
        before={path:path.read_bytes() for path in (self.bindings,self.shell,self.binary)}
        result=self.invoke()
        self.assertFalse(result["migrated"])
        self.assertFalse(self.state.exists())
        for path,data in before.items():self.assertEqual(path.read_bytes(),data)

    def test_known_loader_wrapper_and_switcher_retire_with_private_backups(self):
        self.loader();self.wrapper();originals=self.switcher_files()
        self.bindings.chmod(0o640)
        before=self.bindings.read_bytes()
        result=self.invoke()
        self.assertTrue(result["migrated"])
        self.assertTrue(result["bindingsChanged"])
        self.assertTrue(result["requiresShortcutSync"])
        self.assertEqual(result["preservedOverrides"],["SUPER + A"])
        expected=self.original+b'  -- Keep the operator\'s explicit override\r\n  hl.unbind("SUPER + A");\r\n'+self.suffix
        self.assertEqual(self.bindings.read_bytes(),expected)
        self.assertEqual(stat.S_IMODE(self.bindings.stat().st_mode),0o640)
        self.assertFalse(self.binary.exists())
        for name,data in originals.items():self.assertEqual((self.switcher/name).read_bytes(),data)
        backup=Path(result["backup"])
        self.assertEqual((backup/"bindings.lua").read_bytes(),before)
        self.assertEqual(stat.S_IMODE(backup.stat().st_mode),0o700)
        self.assertTrue(all(stat.S_IMODE(path.stat().st_mode)==0o600 for path in backup.iterdir()))
        self.assertEqual(result["warnings"],[])
        second=self.invoke()
        self.assertFalse(second["migrated"])
        self.assertIsNone(second["backup"])

    def test_legacy_literal_chords_merge_only_missing_preferences(self):
        data=json.loads(self.shell.read_text());data["plugins"][0]["minimizeShortcut"]="CTRL + F8"
        self.shell.write_text(json.dumps(data))
        lines=[BEGIN]
        for key,chord in (("minimizeShortcut","ALT + F1"),("restoreLastShortcut","CTRL + Z")):
            action,label=shortcuts.ACTIONS[key]
            lines.append('o.bind('+','.join(lua(value) for value in (chord,label,str(self.binary)+" "+action))+')')
        lines.append(END)
        self.bindings.write_bytes(self.original+("\n".join(lines)+"\n").encode()+self.suffix)
        self.wrapper()
        result=self.invoke()
        saved=json.loads(self.shell.read_text())
        entry=saved["plugins"][0]
        self.assertEqual(entry["minimizeShortcut"],"CTRL + F8")
        self.assertEqual(entry["restoreLastShortcut"],"CTRL + Z")
        self.assertEqual(entry["restoreOldestShortcut"],"")
        self.assertEqual(entry["scope"],"workspace")
        self.assertEqual(saved["other"],{"keep":True})
        self.assertIn("shell.json",result["changed"])
        self.assertEqual(self.bindings.read_bytes(),self.original+self.suffix)

    def test_legacy_switcher_workspace_command_and_crlf_are_restored(self):
        self.wrapper();self.loader(overrides=False)
        originals=self.switcher_files(newline="\r\n",legacy=True)
        result=self.invoke()
        self.assertEqual(result["warnings"],[])
        for name,data in originals.items():self.assertEqual((self.switcher/name).read_bytes(),data)

    def test_custom_shortcut_block_and_wrapper_are_retained_with_warning(self):
        self.loader();self.wrapper()
        self.bindings.write_bytes(self.bindings.read_bytes().replace(b'dofile(',b'custom_setup(); dofile('))
        before=self.bindings.read_bytes();wrapper=self.binary.read_bytes()
        result=self.invoke()
        self.assertEqual(self.bindings.read_bytes(),before)
        self.assertEqual(self.binary.read_bytes(),wrapper)
        self.assertTrue(result["warnings"])
        self.assertFalse(result["migrated"])

    def test_marker_text_inside_an_unrelated_comment_is_not_an_owned_block(self):
        self.bindings.write_text('-- Example marker: '+BEGIN+'\n')
        self.wrapper()
        before=self.bindings.read_bytes()
        result=self.invoke()
        self.assertEqual(self.bindings.read_bytes(),before)
        self.assertEqual(result["warnings"],[])
        self.assertEqual(result["changed"],["window-stash"])

    def test_symlinked_bindings_keep_the_compatibility_wrapper_and_target(self):
        self.loader();self.wrapper()
        owner=self.home/"owner-bindings.lua"
        self.bindings.rename(owner)
        self.bindings.symlink_to(owner)
        before=owner.read_bytes()
        result=self.invoke()
        self.assertTrue(self.bindings.is_symlink())
        self.assertEqual(owner.read_bytes(),before)
        self.assertTrue(self.binary.exists())
        self.assertTrue(result["warnings"])
        self.assertFalse(result["bindingsChanged"])

    def test_custom_switcher_is_not_partially_reverted_and_keeps_wrapper(self):
        self.loader();self.wrapper();self.switcher_files()
        path=self.switcher/"Switcher.qml"
        path.write_bytes(path.read_bytes().replace(b'var stashAddress =',b'let stashAddress ='))
        before={name:(self.switcher/name).read_bytes() for name in integration_patches()}
        result=self.invoke()
        self.assertNotIn(BEGIN.encode(),self.bindings.read_bytes())
        self.assertTrue(self.binary.exists())
        self.assertTrue(result["warnings"])
        for name,data in before.items():self.assertEqual((self.switcher/name).read_bytes(),data)

    def test_unrelated_wrapper_and_symlinked_files_are_not_removed(self):
        self.loader();self.wrapper("print('owner customization')\n")
        customized=self.binary.read_bytes()
        self.invoke()
        self.assertEqual(self.binary.read_bytes(),customized)
        self.loader();self.binary.unlink()
        other=self.home/"owner-script";other.write_text("original data")
        self.binary.symlink_to(other)
        result=self.invoke()
        self.assertTrue(self.binary.is_symlink())
        self.assertEqual(other.read_text(),"original data")
        self.assertNotIn("window-stash",result["changed"])

    def test_concurrent_user_file_edit_is_not_overwritten(self):
        self.loader();self.wrapper()
        original_replace=migration._replace
        def user_edit(path,before,after):
            if path==self.bindings:path.write_bytes(b"operator changed the file\n")
            return original_replace(path,before,after)
        with patch.object(migration,"_replace",side_effect=user_edit):
            with self.assertRaisesRegex(RuntimeError,"changed during migration"):
                self.invoke()
        self.assertEqual(self.bindings.read_bytes(),b"operator changed the file\n")
        self.assertTrue(self.binary.exists())


if __name__=="__main__":
    unittest.main()
