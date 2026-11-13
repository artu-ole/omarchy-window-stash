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
        self.version = self.root/'native/version.txt'
        self.version.write_text('1.0.0\n')
        (self.root/'manifest.json').write_text(json.dumps(dict(version='9.0.0')))
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

    def build(self, expected=COMMIT, cached=False):
        output = io.StringIO()
        destination = ['--cache-dir', str(self.root/'immutable')] if cached else ['--output', str(self.output)]
        with patch.object(builder, 'ROOT', self.root), \
                patch.object(builder.subprocess, 'check_output', side_effect=self.query), \
                patch.object(builder.subprocess, 'run', side_effect=self.compiler), \
                patch.object(builder.sys, 'argv', ['build-preview-bridge.py', *destination, '--expected-hash', expected]), \
                contextlib.redirect_stdout(output):
            builder.main()
        return json.loads(output.getvalue())

    def test_matching_build_is_cached_without_touching_binary(self):
        result = self.build()
        before = self.output.stat().st_mtime_ns
        self.assertEqual((result['path'], result['hyprlandHash'], result['protocol'], result['version']),
                         (str(self.output), COMMIT, 1, '1.0.0'))
        self.assertEqual(self.build(), result)
        self.assertEqual(self.output.stat().st_mtime_ns, before)
        self.assertEqual(len(self.compiles), 1)

    def test_automatic_cache_uses_distinct_immutable_build_paths(self):
        first = self.build(cached=True)
        first_binary = Path(first['path']).read_bytes()
        self.assertEqual(Path(first['path']).parts[-3:],
                         (COMMIT, '1.0.0-'+first['fingerprint'], 'window-stash-preview.so'))
        self.assertEqual(self.build(cached=True), first)
        self.version.write_text('1.0.1\n')
        second = self.build(cached=True)
        self.assertNotEqual(second['path'], first['path'])
        self.assertEqual(Path(first['path']).read_bytes(), first_binary)
        self.source.write_text('// same version, different native code\n')
        third = self.build(cached=True)
        self.assertNotEqual(third['path'], second['path'])
        self.assertEqual(len(self.compiles), 3)

    def test_corrupt_automatic_cache_is_never_overwritten(self):
        result = self.build(cached=True)
        artifact = Path(result['path'])
        artifact.write_bytes(b'damaged')
        with self.assertRaisesRegex(RuntimeError, 'immutable.*damaged'):
            self.build(cached=True)
        self.assertEqual(artifact.read_bytes(), b'damaged')
        self.assertEqual(len(self.compiles), 1)

    def test_cache_symlink_is_never_replaced(self):
        result = self.build(cached=True)
        artifact = Path(result['path'])
        unrelated = self.root/'unrelated.so'
        artifact.rename(unrelated)
        artifact.symlink_to(unrelated)
        before = unrelated.read_bytes()
        with self.assertRaisesRegex(RuntimeError, 'immutable.*damaged'):
            self.build(cached=True)
        self.assertTrue(artifact.is_symlink())
        self.assertEqual(unrelated.read_bytes(), before)

    def test_build_embeds_fingerprint_and_allows_module_unloading(self):
        result = self.build()
        command = self.compiles[0]
        self.assertIn('-fno-gnu-unique', command)
        self.assertIn('-fvisibility-inlines-hidden', command)
        self.assertNotIn('-fvisibility=hidden', command)
        self.assertIn('-DSTASH_BRIDGE_FINGERPRINT="'+result['fingerprint']+'"', command)

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
                   lambda: self.version.write_text('1.0.1\n'),
                   lambda: setattr(self, 'flags', self.flags+' -DCHANGED_OPTION=1')]
        for index, change in enumerate(changes, 2):
            change()
            self.build()
            self.assertEqual(len(self.compiles), index)

    def test_shell_manifest_update_does_not_rebuild_or_change_native_version(self):
        result = self.build()
        before = self.output.read_bytes(), self.metadata().read_bytes(), self.output.stat().st_mtime_ns
        (self.root/'manifest.json').write_text(json.dumps(dict(version='9.1.0')))
        self.assertEqual(self.build(), result)
        (self.root/'manifest.json').unlink()
        self.assertEqual(self.build(), result)
        self.assertEqual((self.output.read_bytes(), self.metadata().read_bytes(), self.output.stat().st_mtime_ns), before)
        self.assertEqual(len(self.compiles), 1)
        self.assertIn('-DSTASH_BRIDGE_VERSION="1.0.0"', self.compiles[0])

    def test_missing_or_invalid_native_version_refuses_without_compiling(self):
        for version in ('', 'development', '1.2', '01.2.3', '1.2.3-extra', '1.2.3\n4.5.6'):
            with self.subTest(version=version):
                self.version.write_text(version)
                with self.assertRaisesRegex(RuntimeError, 'Invalid native preview bridge version'):
                    self.build()
        self.version.unlink()
        with self.assertRaises(FileNotFoundError):
            self.build()
        self.assertFalse(self.output.exists())
        self.assertFalse(self.metadata().exists())
        self.assertEqual(self.compiles, [])

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
