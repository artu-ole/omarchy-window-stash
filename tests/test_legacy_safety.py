"""Legacy-suite refusal must not arm cleanup against existing stash entries."""
from contextlib import ExitStack
import importlib
import unittest
from unittest.mock import Mock, patch

import live


class LegacySafetyTests(unittest.TestCase):
    def test_existing_stash_refusal_never_mutates_or_runs_cleanup(self):
        snapshot={'windows':[{'id':'existing-user-window'}],'settings':{}}
        reads={'activewindow':{'address':'0xexisting'},'activeworkspace':{'id':1},
               'monitors':[{'name':'HEADLESS-1','focused':True}]}
        for name,entrypoint in (('live','run'),('layouts_monitors','main'),
                                ('ui_lifecycle','main'),('overflow','main')):
            with self.subTest(suite=name), ExitStack() as stack:
                module=importlib.import_module(name)
                compositor=Mock()
                compositor.read.side_effect=lambda subject:reads[subject]
                command=stack.enter_context(patch.object(module,'command',return_value=snapshot))
                stack.enter_context(patch.object(module,'h',compositor))
                mutation=stack.enter_context(patch.object(module,'configure'))
                fixture=stack.enter_context(patch.object(module,'fixture_settings'))
                shell=stack.enter_context(patch.object(module,'shell'))
                subprocess=stack.enter_context(patch.object(module.subprocess,'run'))
                pointer=stack.enter_context(patch.object(module,'Pointer',create=True))
                # Exercise the actual guarded body without sending notices or
                # waiting: this is a no-input unit test, not desktop automation.
                function=getattr(module,entrypoint).__wrapped__
                with self.assertRaisesRegex(RuntimeError,'isolated desktop with an empty stash'):
                    function()
                self.assertEqual(command.call_args_list,[(('list',),{})])
                mutation.assert_not_called();fixture.assert_not_called();shell.assert_not_called()
                subprocess.assert_not_called();pointer.assert_not_called()
                compositor.dispatch.assert_not_called();compositor.call.assert_not_called()
                compositor.eval.assert_not_called()

    def test_empty_snapshot_is_accepted_without_actions(self):
        live.require_empty_stash({'windows':[]})
