#!/usr/bin/env python3
"""Transactionally install the Claude plugin from a checkout or extracted release."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent


def owned_link(path, home):
    if not path.is_symlink():
        return False
    target = Path(os.readlink(path))
    root = home / '.local/share/hippocampus'
    return (target == root / 'current/skills' / path.name or
            target.parent.name == 'skills' and target.name == path.name and
            target.parent.parent.parent == root / 'releases')


def remove(path):
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--claude', default=shutil.which('claude'))
    parser.add_argument('--uninstall', action='store_true')
    args = parser.parse_args()
    if not args.claude:
        parser.error('claude executable is required')
    home = Path.home()
    config = Path(os.environ.get('CLAUDE_CONFIG_DIR', home / '.claude')).expanduser().resolve()
    config.mkdir(parents=True, exist_ok=True)
    lock = config / '.hippocampus-install-lock'
    lock.mkdir()  # Refuse overlapping cutovers rather than snapshotting a partial state.
    try:
        with tempfile.TemporaryDirectory(prefix='hippocampus-install-') as directory:
            backup = Path(directory)
            paths = [config / 'plugins', config / 'settings.json']
            links = {p: os.readlink(p) for p in (config / 'skills').glob('*') if owned_link(p, home)}
            for index, path in enumerate(paths):
                if path.is_symlink():
                    raise ValueError(f'cannot transactionally replace symlinked plugin settings: {path}')
                if path.is_dir():
                    shutil.copytree(path, backup / str(index), symlinks=True)
                elif path.exists():
                    shutil.copy2(path, backup / str(index))
            try:
                for path in links:
                    path.unlink()
                command = (['uninstall', 'hippocampus@hippocampus'] if args.uninstall else
                           ['install', 'hippocampus', '--marketplace', str(ROOT)])
                subprocess.run([args.claude, 'plugin', *command], check=True)
            except BaseException:
                for index, path in enumerate(paths):
                    remove(path)
                    saved = backup / str(index)
                    if saved.is_dir():
                        shutil.copytree(saved, path, symlinks=True)
                    elif saved.exists():
                        shutil.copy2(saved, path)
                for path, target in links.items():
                    path.symlink_to(target)
                raise
    finally:
        lock.rmdir()
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        raise SystemExit('hippocampus Claude install: ' + str(error))
