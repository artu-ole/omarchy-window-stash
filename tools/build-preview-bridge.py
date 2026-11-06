#!/usr/bin/env python3
"""Build the optional bridge against installed Hyprland headers; never load it."""
import argparse
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
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--expected-hash', help='Reject headers from another compositor build')
    args = parser.parse_args()
    source = ROOT / 'native/preview.cpp'
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
    version = json.loads((ROOT / 'manifest.json').read_text())['version']
    compiler = shlex.split(os.environ.get('CXX', 'c++'))
    compiler_version = subprocess.check_output([*compiler, '--version'], text=True).splitlines()[0]
    options = ['-std=c++26', '-shared', '-fPIC', '-O2', '-Wall', '-Wextra',
               '-Wno-unused-parameter', *flags, '-DSTASH_BRIDGE_VERSION=' + json.dumps(version)]
    fingerprint = hashlib.sha256(source.read_bytes() + header.read_bytes()
                                 + json.dumps([version, compiler, compiler_version, options]).encode()).hexdigest()
    output = args.output.expanduser().absolute()
    metadata = output.with_suffix(output.suffix + '.json')
    result = dict(path=str(output), hyprlandHash=hypr_hash, version=version, protocol=1, fingerprint=fingerprint)
    if output.is_file() and not output.is_symlink() and metadata.is_file():
        try:
            previous = json.loads(metadata.read_text())
            digest = hashlib.sha256(output.read_bytes()).hexdigest()
            if previous == dict(result, sha256=digest) and output.read_bytes()[:4] == b'\x7fELF':
                print(json.dumps(result))
                return
        except (ValueError, OSError):
            pass
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.preview-build-', dir=output.parent) as directory:
        temporary = Path(directory) / output.name
        subprocess.run([*compiler, *options, str(source), '-o', str(temporary)], check=True, stdout=sys.stderr)
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
