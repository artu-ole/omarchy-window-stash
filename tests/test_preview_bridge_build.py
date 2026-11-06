"""Build/cache compatibility checks use fake headers and a disposable compiler."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('preview_bridge_build', ROOT/'tools/build-preview-bridge.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
COMMIT = 'a'*40


class PreviewBridgeBuildTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root/'native').mkdir()
        self.source = self.root/'native/preview.cpp'
        self.source.write_text('// fake bridge source\n')
        (self.root/'manifest.json').write_text(json.dumps(dict(version='1.0.0')))
        self.headers = self.root/'include/hyprland'
        (self.headers/'src').mkdir(parents=True)
        self.header = self.headers/'src/version.h'
        self.header.write_text('#define GIT_COMMIT_HASH "'+COMMIT+'"\n')
        self.output = self.root/'cache/bridge.so'
        self.compiles = []
        self.fail = False
        self.flags = '-I'+shlex.quote(str(self.headers))

    def tearDown(self):
        self.temporary.cleanup()

    def metadata(self):
        return self.output.with_suffix('.so.json')

    def query(self, args, **kwargs):
        return self.flags if args[0] == 'pkg-config' else 'Fake C++ compiler 1.0\n'

    def compiler(self, args, **kwargs):
        self.compiles.append(args)
        Path(args[args.index('-o')+1]).write_bytes(b'\x7fELFcompiled-'+str(len(self.compiles)).encode())
        if self.fail:
            raise subprocess.CalledProcessError(1, args)
        return subprocess.CompletedProcess(args, 0)

    def build(self, expected=COMMIT):
        output = io.StringIO()
        with patch.object(builder, 'ROOT', self.root), \
                patch.object(builder.subprocess, 'check_output', side_effect=self.query), \
                patch.object(builder.subprocess, 'run', side_effect=self.compiler), \
                patch.object(builder.sys, 'argv', ['build-preview-bridge.py', '--output', str(self.output), '--expected-hash', expected]), \
                contextlib.redirect_stdout(output):
            builder.main()
        return json.loads(output.getvalue())

    def test_matching_build_is_cached_without_touching_binary(self):
        result = self.build()
        before = self.output.stat().st_mtime_ns
        self.assertEqual((result['path'], result['hyprlandHash'], result['protocol']), (str(self.output), COMMIT, 1))
        self.assertEqual(self.build(), result)
        self.assertEqual(self.output.stat().st_mtime_ns, before)
        self.assertEqual(len(self.compiles), 1)

    def test_wrong_runtime_hash_refuses_without_creating_binary(self):
        with self.assertRaisesRegex(RuntimeError, 'do not match'):
            self.build('b'*40)
        self.assertFalse(self.output.exists())
        self.assertFalse(self.metadata().exists())
        self.assertEqual(self.compiles, [])

    def test_missing_or_unidentified_headers_refuse_without_compiling(self):
        self.header.write_text('// no version\n')
        with self.assertRaisesRegex(RuntimeError, 'do not identify'):
            self.build()
        self.header.unlink()
        with self.assertRaisesRegex(RuntimeError, 'development headers'):
            self.build()
        self.assertFalse(self.output.exists())
        self.assertEqual(self.compiles, [])

    def test_changed_source_headers_version_or_flags_invalidates_cache(self):
        self.build()
        changes = [lambda: self.source.write_text('// changed bridge\n'),
                   lambda: self.header.write_text(self.header.read_text()+'// changed headers\n'),
                   lambda: (self.root/'manifest.json').write_text(json.dumps(dict(version='1.0.1'))),
                   lambda: setattr(self, 'flags', self.flags+' -DCHANGED_OPTION=1')]
        for index, change in enumerate(changes, 2):
            change()
            self.build()
            self.assertEqual(len(self.compiles), index)

    def test_corrupt_binary_or_metadata_rebuilds(self):
        self.build()
        self.output.write_bytes(b'not an ELF binary')
        self.build()
        self.assertEqual(len(self.compiles), 2)
        self.metadata().write_text('{broken metadata')
        self.build()
        self.assertEqual(len(self.compiles), 3)
        self.assertTrue(self.output.read_bytes().startswith(b'\x7fELF'))

    def test_symlink_cache_entry_is_replaced_without_modifying_target(self):
        self.build()
        unrelated = self.root/'unrelated.so'
        unrelated.write_bytes(self.output.read_bytes())
        self.output.unlink()
        self.output.symlink_to(unrelated)
        before = unrelated.read_bytes()
        self.build()
        self.assertEqual(unrelated.read_bytes(), before)
        self.assertFalse(self.output.is_symlink())
        self.assertEqual(len(self.compiles), 2)

    def test_failed_compile_preserves_previous_binary_and_metadata(self):
        self.build()
        binary, metadata = self.output.read_bytes(), self.metadata().read_bytes()
        self.source.write_text('// changed source\n')
        self.fail = True
        with self.assertRaises(subprocess.CalledProcessError):
            self.build()
        self.assertEqual(self.output.read_bytes(), binary)
        self.assertEqual(self.metadata().read_bytes(), metadata)
        self.assertEqual(list(self.output.parent.glob('.preview-build-*')), [])


if __name__ == '__main__':
    unittest.main()
