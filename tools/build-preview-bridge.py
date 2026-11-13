#!/usr/bin/env python3
"""Build the optional bridge against installed Hyprland headers; never load it."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    destination = parser.add_mutually_exclusive_group(required=True)
    destination.add_argument('--output', type=Path, help='Explicit destination, replaced atomically when stale')
    destination.add_argument('--cache-dir', type=Path, help='Immutable cache, keyed by compositor, version and build fingerprint')
    parser.add_argument('--expected-hash', help='Reject headers from another compositor build')
    args = parser.parse_args()
    source = ROOT / 'native/preview.cpp'
    version = (ROOT / 'native/version.txt').read_text().strip()
    if not re.fullmatch(r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)', version):
        raise RuntimeError('Invalid native preview bridge version in native/version.txt')
    flags = shlex.split(subprocess.check_output(['pkg-config', '--cflags', 'hyprland'], text=True))
    include_roots = [Path(value[2:]) for value in flags if value.startswith('-I')]
    header = next((p / 'src/version.h' for p in include_roots if (p / 'src/version.h').is_file()), None)
    if header is None:
        raise RuntimeError('Install the development headers for the running Hyprland version')
    match = re.search(r'^#define\s+GIT_COMMIT_HASH\s+"([0-9a-f]{40})"', header.read_text(), re.M)
    if not match:
        raise RuntimeError('The installed Hyprland headers do not identify their build')
    hypr_hash = match.group(1)
    if args.expected_hash and args.expected_hash != hypr_hash:
        raise RuntimeError('Installed Hyprland headers do not match the running compositor; update or restart Hyprland first')
    compiler = shlex.split(os.environ.get('CXX', 'c++'))
    compiler_version = subprocess.check_output([*compiler, '--version'], text=True).splitlines()[0]
    # Header-defined Hyprland singleton globals must keep their normal ELF
    # visibility so they resolve to the running compositor's objects. Only inline
    # functions are hidden; our mutable implementation state has internal linkage.
    # GNU-unique symbols otherwise make dlclose retain a plugin's static state.
    unloading = [] if 'clang' in compiler_version.lower() else ['-fno-gnu-unique']
    options = ['-std=c++26', '-shared', '-fPIC', '-O2', '-Wall', '-Wextra',
               '-Wno-unused-parameter', '-fvisibility-inlines-hidden', *unloading,
               *flags, '-DSTASH_BRIDGE_VERSION=' + json.dumps(version)]
    fingerprint = hashlib.sha256(source.read_bytes() + header.read_bytes()
                                 + json.dumps([version, compiler, compiler_version, options]).encode()).hexdigest()
    output = (args.output.expanduser().absolute() if args.output else
              args.cache_dir.expanduser().absolute()/hypr_hash/(version+'-'+fingerprint)/'window-stash-preview.so')
    metadata = output.with_suffix(output.suffix + '.json')
    result = dict(path=str(output), hyprlandHash=hypr_hash, version=version, protocol=1, fingerprint=fingerprint)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Concurrent render/input helpers can request the same first-use build. Keep
    # the artifact and its metadata one transaction, without replacing an existing
    # automatic-cache pathname that the loader may still have mapped.
    with (output.parent/'.build.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if output.is_file() and not output.is_symlink() and metadata.is_file() and not metadata.is_symlink():
            try:
                previous = json.loads(metadata.read_text())
                binary = output.read_bytes()
                digest = hashlib.sha256(binary).hexdigest()
                if previous == dict(result, sha256=digest) and binary[:4] == b'\x7fELF':
                    print(json.dumps(result))
                    return
            except (ValueError, OSError):
                pass
        if args.cache_dir and (output.exists() or output.is_symlink() or metadata.exists() or metadata.is_symlink()):
            raise RuntimeError('The immutable preview bridge cache entry is damaged; remove its versioned directory and retry')
        with tempfile.TemporaryDirectory(prefix='.preview-build-', dir=output.parent) as directory:
            temporary = Path(directory) / output.name
            compile_options = [*options, '-DSTASH_BRIDGE_FINGERPRINT=' + json.dumps(fingerprint)]
            subprocess.run([*compiler, *compile_options, str(source), '-o', str(temporary)], check=True, stdout=sys.stderr)
            result_metadata = dict(result, sha256=hashlib.sha256(temporary.read_bytes()).hexdigest())
            temporary.replace(output)
            private_metadata = Path(directory) / 'metadata.json'
            private_metadata.write_text(json.dumps(result_metadata) + '\n')
            private_metadata.replace(metadata)
    print(json.dumps(result))


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print('Preview bridge build failed: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
