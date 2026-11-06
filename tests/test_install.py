"""Check that installer consent precedes all user-file changes."""
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('stash_installer', ROOT / 'tools/install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallerConsentTests(unittest.TestCase):
    def test_noninteractive_install_and_removal_do_not_write_without_consent(self):
        for arguments in ([], ['--uninstall']):
            with self.subTest(arguments=arguments), tempfile.TemporaryDirectory() as directory:
                home = Path(directory)
                env = dict(os.environ, HOME=directory, XDG_CONFIG_HOME=str(home / '.config'),
                           XDG_STATE_HOME=str(home / '.local/state'), PYTHONDONTWRITEBYTECODE='1')
                result = subprocess.run([sys.executable, str(ROOT / 'tools/install.py'), *arguments],
                                        cwd=directory, env=env, stdin=subprocess.DEVNULL,
                                        capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('pass --yes', result.stderr)
                self.assertEqual(list(home.iterdir()), [])

    def test_declining_confirmation_aborts(self):
        paths = [Path('unused') for _ in range(5)]
        with patch.object(sys, 'stdin') as stdin, patch('builtins.input', return_value='n'), \
                patch.object(sys, 'stderr', io.StringIO()):
            stdin.isatty.return_value = True
            with self.assertRaisesRegex(RuntimeError, 'Cancelled; no files changed'):
                installer.confirm_changes(*paths, False, False)

    def test_explicit_yes_does_not_require_terminal_or_prompt(self):
        paths = [Path('unused') for _ in range(5)]
        with patch('builtins.input', side_effect=AssertionError('Unexpected prompt')), \
                patch.object(sys, 'stderr', io.StringIO()):
            installer.confirm_changes(*paths, False, True)


class InstallerShortcutTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.home=Path(self.temp.name)
        self.config=self.home/'.config'
        self.bindings=self.config/'hypr/bindings.lua'
        self.shell=self.config/'omarchy/shell.json'
        self.target=self.config/'omarchy/plugins'/installer.PLUGIN
        self.binary=self.home/'.local/bin/window-stash'
        self.bindings.parent.mkdir(parents=True)
        self.shell.parent.mkdir(parents=True)
        self.bindings.write_text('-- Unrelated configuration\n')
        self.data={'plugins':[{'id':installer.PLUGIN,'presentation':'bubbles','customValue':'keep'},
                              {'id':'community.other','value':'untouched'}],'other':{'keep':True}}
        self.write_config()
        self.source=self.home/'source'
        self.source.mkdir()
        for name in ('manifest.json','Service.qml','window-stash','README.md','LICENSE','THIRD_PARTY_NOTICES.md','VALIDATION.md'):
            (self.source/name).write_text('fixture')
        for name in ('ui','controller','assets'):
            (self.source/name).mkdir()
            (self.source/name/'fixture').write_text('fixture')
        self.monitor=dict(name='TEST-1',width=1920,height=1080,refreshRate=60,x=-300,y=20,scale=1.25,transform=0)
        self.calls=[]
        self.disabled=[]

    def tearDown(self):self.temp.cleanup()

    def write_config(self):self.shell.write_text(json.dumps(self.data))

    def fake_run(self,*args):
        self.calls.append(args)
        if args==('hyprctl','monitors','-j'):return json.dumps([self.monitor])
        if args==('hyprctl','configerrors'):return ''
        return 'ok'

    def disable(self,*args,**kwargs):
        # Runtime handles must be disabled while the installed module and
        # wrapper still exist; disabled history must not require chord unbinds.
        self.assertTrue(self.target.exists())
        self.assertTrue(self.binary.exists())
        self.disabled.append((args,kwargs))
        return {'ok':True}

    def invoke(self,uninstall=False,live=(),owned=()):
        event=Mock()
        event.recv.return_value=b'configreloaded>>\n'
        env=dict(HOME=str(self.home),XDG_CONFIG_HOME=str(self.config),
                 XDG_STATE_HOME=str(self.home/'.local/state'),XDG_RUNTIME_DIR=str(self.home/'run'),
                 HYPRLAND_INSTANCE_SIGNATURE='test')
        with patch.dict(os.environ,env),patch.object(installer,'SOURCE',self.source), \
             patch.object(sys,'argv',['install.py','--yes']+(['--uninstall'] if uninstall else [])), \
             patch.object(installer,'run',side_effect=self.fake_run), \
             patch.object(installer.socket,'socket',return_value=event), \
             patch.object(installer.shortcuts,'runtime_state',return_value=(list(live),list(owned))), \
             patch.object(installer.shortcuts,'disable',side_effect=self.disable), \
             patch.object(sys,'stdout',io.StringIO()),patch.object(sys,'stderr',io.StringIO()):
            installer.main()

    def legacy(self,chords=None,newline='\n'):
        chords=chords if chords is not None else {'minimizeShortcut':'SUPER + A','restoreLastShortcut':'SUPER + Z'}
        lines=[installer.BEGIN]
        for key,chord in chords.items():
            action,label=installer.shortcuts.ACTIONS[key]
            lines.append('o.bind('+','.join(installer.lua(value) for value in
                                           (chord,label,str(self.binary)+' '+action))+')')
        lines.append(installer.END)
        return newline.join(lines)+newline

    def live(self,key,chord=None,reference='1'):
        chord=installer.shortcuts.normalize(chord or installer.shortcuts.DEFAULT_SHORTCUTS[key])
        parts=chord.split(' + ')
        return dict(dispatcher='__lua',arg=reference,description=installer.shortcuts.ACTIONS[key][1],
                    modmask=sum(installer.shortcuts.MODIFIERS[modifier] for modifier in parts[:-1]),
                    key=parts[-1],submap='')

    def assert_unchanged(self,binding_bytes,config_bytes):
        self.assertEqual(self.bindings.read_bytes(),binding_bytes)
        self.assertEqual(self.shell.read_bytes(),config_bytes)
        self.assertFalse(self.target.exists())
        self.assertFalse(self.binary.exists())

    def test_update_imports_literal_legacy_chords_and_preserves_outside_bytes(self):
        prefix='-- Keep owner code\r\no.bind("SUPER + B","Other","other")\r\n\r\n'
        suffix='\r\n-- Keep owner tail\r\n'
        chords={'minimizeShortcut':'super + shift + a','restoreLastShortcut':'CTRL + Z'}
        self.data['plugins'][0]['minimizeShortcut']='CTRL + F8'
        self.write_config()
        self.bindings.write_bytes((prefix+self.legacy(chords,'\r\n')+suffix).encode())
        self.invoke(live=[self.live(key,chord,reference=str(index)) for index,(key,chord) in enumerate(chords.items(),1)])
        expected=prefix+installer.BEGIN+'\r\ndofile('+installer.lua(str(self.target/'controller/shortcuts.lua'))+')\r\n'+installer.END+'\r\n'+suffix
        self.assertEqual(self.bindings.read_bytes(),expected.encode())
        saved=json.loads(self.shell.read_text())
        entry=saved['plugins'][0]
        self.assertEqual(entry['minimizeShortcut'],'CTRL + F8')
        self.assertEqual(entry['restoreLastShortcut'],'CTRL + Z')
        self.assertEqual(entry['restoreOldestShortcut'],'')
        self.assertEqual(entry['presentation'],'bubbles')
        self.assertEqual(entry['customValue'],'keep')
        self.assertEqual(saved['plugins'][1],self.data['plugins'][1])
        self.assertEqual(saved['other'],self.data['other'])

    def test_switcher_integration_upgrades_legacy_workspace_and_uninstalls_cleanly(self):
        switcher = self.config/'omarchy/plugins/community.window-switcher'
        originals = {}
        for name, patches in installer.integration_patches().items():
            path = switcher/name
            path.parent.mkdir(parents=True, exist_ok=True)
            original = '\n'.join(before for before, _ in patches)
            originals[name] = original
            legacy = original
            for before, after in patches:
                legacy = legacy.replace(before, after)
            path.write_text(legacy.replace('special:window-stash', 'special:minimized'))
        self.invoke()
        records = (switcher/'components/WindowRecords.qml').read_text()
        self.assertIn('stashManaged: workspaceName === "special:window-stash"', records)
        self.assertNotIn('special:minimized', records)
        self.assertEqual(installer.upgrade_integration(records), records)
        self.invoke(uninstall=True)
        for name, original in originals.items():
            self.assertEqual((switcher/name).read_text(), original)

    def test_switcher_upgrade_handles_old_tag_filtered_workspace_patch(self):
        legacy = '''      stashManaged: workspaceName === "special:minimized" && Array.isArray(ipc.tags)
        && ipc.tags.some(function(tag) { return String(tag).indexOf("window-stash-") === 0 }),'''
        updated = installer.upgrade_integration(legacy)
        self.assertIn('stashManaged: workspaceName === "special:window-stash",', updated)
        self.assertNotIn('special:minimized', updated)
        self.assertNotIn('Array.isArray', updated)

    def test_deleted_legacy_action_stays_disabled(self):
        self.bindings.write_text(self.legacy({'minimizeShortcut':'SUPER + A'}))
        self.invoke(live=[self.live('minimizeShortcut')])
        entry=json.loads(self.shell.read_text())['plugins'][0]
        self.assertEqual(entry['minimizeShortcut'],'SUPER + A')
        self.assertEqual(entry['restoreLastShortcut'],'')
        self.assertEqual(entry['restoreOldestShortcut'],'')

    def test_explicit_legacy_override_survives_migration_and_later_rebinding(self):
        prefix='-- Owner prefix\n\n'
        suffix='\n-- Owner suffix\n'
        comment='-- Override Omarchy 4.5 default: Select all'
        override='hl.unbind("SUPER + A")'
        legacy=self.legacy().replace(installer.BEGIN+'\n',installer.BEGIN+'\n'+comment+'\n'+override+'\n',1)
        self.bindings.write_text(prefix+legacy+suffix)
        self.invoke(live=[self.live('minimizeShortcut'),self.live('restoreLastShortcut',reference='2')])
        migrated=self.bindings.read_text()
        expected=prefix+installer.BEGIN+'\n'+comment+'\n'+override+'\ndofile('+installer.lua(str(self.target/'controller/shortcuts.lua'))+')\n'+installer.END+'\n'+suffix
        self.assertEqual(migrated,expected)
        saved=json.loads(self.shell.read_text())
        saved['plugins'][0]['minimizeShortcut']='CTRL + F8'
        self.shell.write_text(json.dumps(saved))
        runtime=[self.live('minimizeShortcut','CTRL + F8',reference='10'),self.live('restoreLastShortcut',reference='11')]
        self.invoke(live=runtime,owned=runtime)
        self.assertEqual(self.bindings.read_text(),migrated)
        self.assertEqual(json.loads(self.shell.read_text())['plugins'][0]['minimizeShortcut'],'CTRL + F8')
        self.invoke(uninstall=True)
        self.assertEqual(self.bindings.read_text(),prefix+suffix)

    def test_unpaired_legacy_override_is_refused(self):
        text=self.legacy().replace(installer.BEGIN+'\n',installer.BEGIN+'\nhl.unbind("CTRL + F8")\n',1)
        self.bindings.write_text(text)
        before=self.bindings.read_bytes(),self.shell.read_bytes()
        with self.assertRaisesRegex(RuntimeError,'custom code'):
            self.invoke()
        self.assert_unchanged(*before)

    def test_legacy_migration_also_applies_when_plugin_entry_is_missing(self):
        self.data['plugins']=[self.data['plugins'][1]]
        self.write_config()
        chords={'minimizeShortcut':'CTRL + F8','restoreLastShortcut':'ALT + Z'}
        self.bindings.write_text(self.legacy(chords))
        self.invoke(live=[self.live(key,chord,str(index)) for index,(key,chord) in enumerate(chords.items(),1)])
        entry=next(p for p in json.loads(self.shell.read_text())['plugins'] if p['id']==installer.PLUGIN)
        for key,chord in chords.items():self.assertEqual(entry[key],chord)
        self.assertEqual(entry['restoreOldestShortcut'],'')

    def test_legacy_lookalike_duplicate_remains_a_conflict(self):
        self.bindings.write_text(self.legacy())
        before=self.bindings.read_bytes(),self.shell.read_bytes()
        live=[self.live('minimizeShortcut',reference='1'),self.live('minimizeShortcut',reference='2'),
              self.live('restoreLastShortcut',reference='3')]
        with self.assertRaisesRegex(RuntimeError,'already assigned'):
            self.invoke(live=live)
        self.assert_unchanged(*before)

    def test_window_stash_description_without_marked_proof_is_foreign(self):
        before=self.bindings.read_bytes(),self.shell.read_bytes()
        with self.assertRaisesRegex(RuntimeError,'already assigned'):
            self.invoke(live=[self.live('minimizeShortcut')])
        self.assert_unchanged(*before)

    def test_custom_code_and_malformed_markers_are_refused_before_user_file_changes(self):
        for text in (installer.BEGIN+'\nhl.unbind("SUPER + A")\n'+installer.END+'\n',
                     installer.BEGIN+'\n',self.legacy()+self.legacy()):
            with self.subTest(text=text):
                self.bindings.write_text(text)
                before=self.bindings.read_bytes(),self.shell.read_bytes()
                with self.assertRaisesRegex(RuntimeError,'custom code|Malformed'):
                    self.invoke()
                self.assert_unchanged(*before)

    def test_conflict_check_uses_configured_optional_chord(self):
        self.data['plugins'][0].update(minimizeShortcut='',restoreLastShortcut='',restoreOldestShortcut='CTRL + F9')
        self.write_config()
        before=self.bindings.read_bytes(),self.shell.read_bytes()
        foreign=self.live('restoreOldestShortcut','CTRL + F9')
        foreign['description']='Another action'
        with self.assertRaisesRegex(RuntimeError,'CTRL \\+ F9 is already assigned to Another action'):
            self.invoke(live=[foreign])
        self.assert_unchanged(*before)

    def test_disabled_shortcuts_do_not_reserve_default_chords(self):
        self.data['plugins'][0].update({key:'' for key in installer.shortcuts.DEFAULT_SHORTCUTS})
        self.write_config()
        self.invoke(live=[self.live('minimizeShortcut'),self.live('restoreLastShortcut')])
        entry=json.loads(self.shell.read_text())['plugins'][0]
        self.assertTrue(all(entry[key]=='' for key in installer.shortcuts.DEFAULT_SHORTCUTS))

    def test_owned_runtime_handles_and_existing_loader_survive_update(self):
        self.data['plugins'][0].update(installer.shortcuts.DEFAULT_SHORTCUTS)
        self.write_config()
        text='-- Before\n'+installer.replace_binding_block('',None,self.target)+'\n-- After\n'
        self.bindings.write_text(text)
        live=[self.live('minimizeShortcut'),self.live('restoreLastShortcut',reference='2')]
        self.invoke(live=live,owned=live)
        self.assertEqual(self.bindings.read_text(),text)

    def test_cached_runtime_handles_are_not_mistaken_for_legacy_handles(self):
        self.bindings.write_text(self.legacy())
        owned=[self.live('minimizeShortcut',reference='10'),self.live('restoreLastShortcut',reference='11')]
        legacy=[self.live('minimizeShortcut',reference='1'),self.live('restoreLastShortcut',reference='2')]
        self.invoke(live=owned+legacy,owned=owned)
        self.assertIn('dofile(',self.bindings.read_text())

    def test_legacy_custom_submap_is_not_silently_moved_to_global(self):
        self.bindings.write_text(self.legacy())
        before=self.bindings.read_bytes(),self.shell.read_bytes()
        binding=self.live('minimizeShortcut')
        binding['submap']='custom'
        with self.assertRaisesRegex(RuntimeError,'custom submap'):
            self.invoke(live=[binding,self.live('restoreLastShortcut',reference='2')])
        self.assert_unchanged(*before)

    def test_uninstall_disables_handles_before_deleting_and_preserves_outside_block(self):
        prefix='-- Owner prefix\n\n'
        suffix='\n-- Owner suffix\n'
        self.bindings.write_text(prefix+installer.replace_binding_block('',None,self.target)+suffix)
        self.target.mkdir(parents=True)
        self.binary.parent.mkdir(parents=True)
        self.binary.write_text('fixture')
        self.invoke(uninstall=True)
        self.assertEqual(self.bindings.read_text(),prefix+suffix)
        self.assertEqual(len(self.disabled),1)
        self.assertEqual(self.disabled[0][0],(self.shell,))
        self.assertFalse(self.target.exists())
        self.assertFalse(self.binary.exists())
        self.assertEqual(json.loads(self.shell.read_text())['plugins'],[self.data['plugins'][1]])
        self.assertIn((str(self.binary),'restore-all','--to','current'),self.calls)


if __name__ == '__main__':
    unittest.main()
