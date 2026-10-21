#!/usr/bin/env python3
"""Create a separate, version-checked gbot runtime with clean chat labels."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile


def digest(data):
    return hashlib.sha256(data).hexdigest()


def install(source, destination):
    source, destination = source.resolve(), destination.expanduser().resolve()
    if destination.exists() or source == destination or source in destination.parents:
        raise ValueError('Destination must be a new directory outside the source runtime')
    patches = json.loads(Path(__file__).with_name('patches.json').read_text())
    updated = {}
    for patch in patches:
        data = (source / patch['path']).read_bytes()
        if digest(data) != patch['before_sha256']:
            raise ValueError('Unsupported or modified source file: ' + patch['path'])
        text = data.decode('utf-8')
        for edit in patch['edits']:
            if text.count(edit['old']) != 1:
                raise ValueError('Patch match is not unique: ' + patch['path'])
            text = text.replace(edit['old'], edit['new'], 1)
        data = text.encode('utf-8')
        if digest(data) != patch['after_sha256']:
            raise ValueError('Unexpected patched hash: ' + patch['path'])
        updated[patch['path']] = data
    manifest = json.loads((source / 'agent-bundle.manifest.json').read_text())
    if manifest['application']['version'] != '0.12.4':
        raise ValueError('Only gbot 0.12.4 is supported')
    found = set()
    def refresh(obj):
        if isinstance(obj, dict):
            name = obj.get('path')
            if isinstance(name, str) and name in updated and 'sha256' in obj:
                obj.update(sha256=digest(updated[name]), bytes=len(updated[name]))
                found.add(name)
            for value in obj.values():
                refresh(value)
        elif isinstance(obj, list):
            for value in obj:
                refresh(value)
    refresh(manifest)
    if found != set(updated):
        raise ValueError('Manifest does not cover every changed file')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.grok-bridge-', dir=destination.parent) as temp:
        staged = Path(temp) / 'runtime'
        shutil.copytree(source, staged, symlinks=True)
        for name, data in updated.items():
            target = staged / name
            if target.is_symlink():
                raise ValueError('Refusing to patch a symlink')
            target.write_bytes(data)
            subprocess.run(['node', '--check', str(target)], check=True, capture_output=True)
        target = staged / 'agent-bundle.manifest.json'
        if target.is_symlink():
            raise ValueError('Refusing a symlink manifest')
        target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
        staged.rename(destination)
    print('Created:', destination)
    print('Original runtime and host configuration were not changed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True, help='Original installed gbot 0.12.4 directory')
    parser.add_argument('--destination', type=Path, default=Path.home() / '.codex/tools/grok-clean-bridge/0.12.4')
    args = parser.parse_args()
    try:
        install(args.source, args.destination)
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError) as error:
        parser.exit(1, 'Installation stopped: ' + str(error) + '\n')
