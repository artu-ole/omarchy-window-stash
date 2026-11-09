"""Check that installer consent precedes all user-file changes."""
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
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
        for arguments in ([], ['--uninstall'], ['--prepare-remove']):
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

    def test_removal_modes_are_mutually_exclusive_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            env = dict(os.environ, HOME=directory, XDG_CONFIG_HOME=str(home / '.config'),
                       XDG_STATE_HOME=str(home / '.local/state'), PYTHONDONTWRITEBYTECODE='1')
            result = subprocess.run([sys.executable, str(ROOT / 'tools/install.py'),
                                     '--uninstall', '--prepare-remove', '--yes'],
                                    cwd=directory, env=env, stdin=subprocess.DEVNULL,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn('not allowed with argument', result.stderr)
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
        for name in ('manifest.json','Service.qml','window-stash','README.md','preview.png','LICENSE','THIRD_PARTY_NOTICES.md','VALIDATION.md'):
            (self.source/name).write_text('fixture')
        for name in ('ui','controller','native','tools'):
            (self.source/name).mkdir()
            (self.source/name/'fixture').write_text('fixture')
        (self.source/'tools/build-preview-bridge.py').write_text('fixture builder')
        (self.source/'tools/install.py').write_text('fixture setup helper')
        self.monitor=dict(name='TEST-1',width=1920,height=1080,refreshRate=60,x=-300,y=20,scale=1.25,transform=0)
        self.calls=[]
        self.disabled=[]

    def tearDown(self):self.temp.cleanup()

    def write_config(self):self.shell.write_text(json.dumps(self.data))

    def fake_run(self,*args):
        self.calls.append(args)
        if args==('hyprctl','monitors','-j'):return json.dumps([self.monitor])
        if args==('hyprctl','configerrors'):return ''
        if args==('omarchy-shell','shell','listPlugins'):
            return json.dumps([{'id':installer.PLUGIN,'enabled':False}])
        return 'ok'

    def disable(self,*args,**kwargs):
        # Runtime handles must be disabled while the installed module and
        # wrapper still exist; disabled history must not require chord unbinds.
        self.assertTrue(self.target.exists())
        self.assertTrue(self.binary.exists())
        self.disabled.append((args,kwargs))
        return {'ok':True}

    def invoke(self,uninstall=False,live=(),owned=(),prepare_remove=False):
        event=Mock()
        event.recv.return_value=b'configreloaded>>\n'
        env=dict(HOME=str(self.home),XDG_CONFIG_HOME=str(self.config),
                 XDG_STATE_HOME=str(self.home/'.local/state'),XDG_RUNTIME_DIR=str(self.home/'run'),
                 HYPRLAND_INSTANCE_SIGNATURE='test')
        arguments=['install.py','--yes']+(['--uninstall'] if uninstall else [])+(['--prepare-remove'] if prepare_remove else [])
        with patch.dict(os.environ,env),patch.object(installer,'SOURCE',self.source), \
             patch.object(sys,'argv',arguments), \
             patch.object(installer,'run',side_effect=self.fake_run), \
             patch.object(installer.socket,'socket',return_value=event), \
             patch.object(installer.shortcuts,'runtime_state',return_value=(list(live),list(owned))), \
             patch.object(installer.shortcuts,'disable',side_effect=self.disable), \
             patch.object(sys,'stdout',io.StringIO()) as output,patch.object(sys,'stderr',io.StringIO()):
            installer.main()
            return json.loads(output.getvalue())

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

    def test_install_includes_optional_native_bridge_source_builder_and_setup_helper(self):
        self.invoke()
        self.assertEqual((self.target/'native/fixture').read_text(), 'fixture')
        self.assertEqual((self.target/'tools/build-preview-bridge.py').read_text(), 'fixture builder')
        self.assertEqual((self.target/'tools/install.py').read_text(), 'fixture setup helper')
        self.assertFalse((self.target/'tools/fixture').exists(), 'Unrelated developer tools must not be copied')

    def test_in_place_setup_preserves_git_checkout_and_local_changes(self):
        shutil.copytree(self.source,self.target)
        (self.target/'.git/objects').mkdir(parents=True)
        (self.target/'.git/HEAD').write_bytes(b'ref: refs/heads/main\n')
        (self.target/'.git/index').write_bytes(b'\x00git fixture\xff')
        (self.target/'Service.qml').write_text('locally modified tracked source\n')
        (self.target/'untracked.txt').write_text('local untracked file\n')
        before={str(path.relative_to(self.target)):(path.read_bytes(),path.stat().st_mode)
                for path in self.target.rglob('*') if path.is_file()}
        self.source=self.target/'..'/self.target.name
        self.invoke()
        self.invoke()
        after={str(path.relative_to(self.target)):(path.read_bytes(),path.stat().st_mode)
               for path in self.target.rglob('*') if path.is_file()}
        self.assertEqual(after,before)
        self.assertTrue(self.binary.is_file())
        self.assertIn('dofile(',self.bindings.read_text())
        saved=json.loads(self.shell.read_text())
        self.assertEqual(saved['plugins'][0]['customValue'],'keep')

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
        live=[self.live('minimizeShortcut','SUPER + A',reference='1'),self.live('minimizeShortcut','SUPER + A',reference='2'),
              self.live('restoreLastShortcut','SUPER + Z',reference='3')]
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
        owned=[self.live('minimizeShortcut','SUPER + A',reference='10'),self.live('restoreLastShortcut','SUPER + Z',reference='11')]
        legacy=[self.live('minimizeShortcut','SUPER + A',reference='1'),self.live('restoreLastShortcut','SUPER + Z',reference='2')]
        self.invoke(live=owned+legacy,owned=owned)
        self.assertIn('dofile(',self.bindings.read_text())

    def test_legacy_custom_submap_is_not_silently_moved_to_global(self):
        self.bindings.write_text(self.legacy())
        before=self.bindings.read_bytes(),self.shell.read_bytes()
        binding=self.live('minimizeShortcut','SUPER + A')
        binding['submap']='custom'
        with self.assertRaisesRegex(RuntimeError,'custom submap'):
            self.invoke(live=[binding,self.live('restoreLastShortcut','SUPER + Z',reference='2')])
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

    def test_prepare_remove_cleans_integration_but_retains_checkout_and_preferences(self):
        self.invoke()
        (self.target/'.git').mkdir()
        (self.target/'.git/HEAD').write_text('ref: refs/heads/main\n')
        (self.target/'local.txt').write_text('untracked owner data\n')
        positions=self.home/'.local/state/omarchy/window-stash/bubbles.json'
        positions.write_bytes(b'{"monitor":{"dock:static:bottom":[7500,0]}}\n')
        self.data=json.loads(self.shell.read_text())
        self.data['disabledPlugins']=['community.other-disabled']
        self.write_config()
        before={str(path.relative_to(self.target)):path.read_bytes()
                for path in self.target.rglob('*') if path.is_file()}
        prefix='-- Owner prefix\r\n\r\n'
        suffix='\r\n-- Owner suffix\r\n'
        self.bindings.write_bytes((prefix+installer.replace_binding_block('',None,self.target)+suffix).encode())
        switcher=self.config/'omarchy/plugins/community.window-switcher'
        originals={}
        for name,patches in installer.integration_patches().items():
            path=switcher/name
            path.parent.mkdir(parents=True,exist_ok=True)
            original='\n'.join(before for before,_ in patches)
            originals[name]=original
            modified=original
            for initial,replacement in patches:modified=modified.replace(initial,replacement)
            path.write_text(modified)
        self.calls.clear()
        self.source=self.target
        result=self.invoke(prepare_remove=True)
        self.assertEqual(self.calls[1],(str(self.binary),'restore-all','--to','current'))
        self.assertEqual(len(self.disabled),2)
        self.assertFalse(self.binary.exists())
        self.assertEqual(self.bindings.read_bytes(),(prefix+suffix).encode())
        saved=json.loads(self.shell.read_text())
        self.assertEqual(saved['plugins'],self.data['plugins'])
        self.assertEqual(saved['other'],self.data['other'])
        self.assertEqual(saved['disabledPlugins'],['community.other-disabled',installer.PLUGIN])
        after={str(path.relative_to(self.target)):path.read_bytes()
               for path in self.target.rglob('*') if path.is_file()}
        self.assertEqual(after,before)
        self.assertEqual(positions.read_bytes(),b'{"monitor":{"dock:static:bottom":[7500,0]}}\n')
        for name,original in originals.items():self.assertEqual((switcher/name).read_text(),original)
        self.assertTrue(result['installed'])
        self.assertTrue(result['preparedRemoval'])
        self.assertFalse(result['enabled'])

    def test_prepare_remove_retains_wrapper_when_host_disable_is_not_confirmed(self):
        self.invoke()
        self.source=self.target
        before={str(path.relative_to(self.target)):path.read_bytes()
                for path in self.target.rglob('*') if path.is_file()}
        before_settings=json.loads(self.shell.read_text())['plugins']
        original_run=self.fake_run
        def stale_host(*arguments):
            if arguments==('omarchy-shell','shell','listPlugins'):
                return json.dumps([{'id':installer.PLUGIN,'enabled':True}])
            return original_run(*arguments)
        with patch.object(self,'fake_run',side_effect=stale_host), \
                patch.object(installer.time,'monotonic',side_effect=[0,6]):
            with self.assertRaisesRegex(RuntimeError,'still enabled.*retained'):
                self.invoke(prepare_remove=True)
        self.assertTrue(self.binary.is_file())
        self.assertEqual(len(self.disabled),1)
        saved=json.loads(self.shell.read_text())
        self.assertEqual(saved['plugins'],before_settings)
        self.assertIn(installer.PLUGIN,saved['disabledPlugins'])
        after={str(path.relative_to(self.target)):path.read_bytes()
               for path in self.target.rglob('*') if path.is_file()}
        self.assertEqual(after,before)

    def test_failed_restore_aborts_prepare_remove_before_cleanup(self):
        self.invoke()
        self.source=self.target
        original_run=self.fake_run
        def fail_restore(*arguments):
            if arguments==(str(self.binary),'restore-all','--to','current'):
                self.assertTrue(self.target.is_dir())
                self.assertTrue(self.binary.is_file())
                self.assertIn(installer.BEGIN,self.bindings.read_text())
                raise RuntimeError('Restoration failed')
            return original_run(*arguments)
        before_bindings=self.bindings.read_bytes()
        before_shell=self.shell.read_bytes()
        with patch.object(self,'fake_run',side_effect=fail_restore):
            with self.assertRaisesRegex(RuntimeError,'Restoration failed'):
                self.invoke(prepare_remove=True)
        self.assertEqual(self.bindings.read_bytes(),before_bindings)
        self.assertEqual(self.shell.read_bytes(),before_shell)
        self.assertEqual(self.disabled,[])
        self.assertTrue(self.target.is_dir())
        self.assertTrue(self.binary.is_file())


class InstallerHostDisableTests(unittest.TestCase):
    def test_waits_for_stale_host_to_observe_disabled_state(self):
        state=lambda enabled:json.dumps([{'id':installer.PLUGIN,'enabled':enabled}])
        with patch.object(installer,'run',side_effect=['ok',state(True),state(False)]) as run, \
                patch.object(installer.time,'sleep') as sleep:
            installer.wait_for_disabled()
        self.assertEqual(run.call_args_list[0].args,('omarchy-shell','shell','reloadConfig'))
        self.assertEqual(run.call_count,3)
        sleep.assert_called_once_with(0.05)

    def test_times_out_when_plugin_is_not_known_without_deleting_files(self):
        with patch.object(installer,'run',side_effect=['ok','[]']), \
                patch.object(installer.time,'monotonic',side_effect=[0,6]):
            with self.assertRaisesRegex(RuntimeError,'not known.*retained'):
                installer.wait_for_disabled()

    def test_refuses_unreadable_host_state(self):
        for state in ('broken json','{}','[null]'):
            with self.subTest(state=state), \
                    patch.object(installer,'run',side_effect=['ok',state]):
                with self.assertRaisesRegex(RuntimeError,'Could not read shell plugin state'):
                    installer.wait_for_disabled()


if __name__ == '__main__':
    unittest.main()
