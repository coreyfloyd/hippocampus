#!/usr/bin/env python3
"""Transactionally install the Claude plugin from a checkout or extracted release."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

from lib import install_recovery as recovery
from lib.install_conflicts import refuse_foreign_marketplace, refuse_standalone

ROOT = Path(__file__).resolve().parent.parent


def owned_link(path, home):
    if not path.is_symlink():
        return False
    target = Path(os.readlink(path))
    root = home / '.local/share/hippocampus'
    return (target == root / 'current/skills' / path.name or
            target.parent.name == 'skills' and target.name == path.name and
            target.parent.parent.parent == root / 'releases')


def rollback(paths, links, backup):
    """Restore every path and link it can; return what it could not restore."""
    problems, leftovers = [], []
    for path, target in links.items():
        if not os.path.lexists(path):
            recovery.attempt(problems, f'skill link {path} -> {target}', path.symlink_to, target)
    for path in paths:
        saved = backup / path.name
        if not os.path.lexists(saved):
            recovery.attempt(leftovers, str(path), recovery.remove, path)
            continue
        recovery.restore(saved, path, problems)
        if saved.is_dir() and path.is_dir():
            recovery.prune(saved, path, leftovers)
    for leftover in leftovers:
        print(f'hippocampus install: left in place: {leftover}', file=sys.stderr)
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--claude', default=shutil.which('claude'))
    parser.add_argument('--uninstall', action='store_true')
    args = parser.parse_args()
    if not args.uninstall:
        refuse_standalone()
    if not args.claude:
        parser.error('claude executable is required')
    home = Path.home()
    config = Path(os.environ.get('CLAUDE_CONFIG_DIR', home / '.claude')).expanduser().resolve()
    if not args.uninstall:
        refuse_foreign_marketplace(config, ROOT)
    config.mkdir(parents=True, exist_ok=True)
    lock = config / '.hippocampus-install-lock'
    lock.mkdir()  # Refuse overlapping cutovers rather than snapshotting a partial state.
    try:
        recovery.refuse_pending(config)
        paths = [config / 'plugins', config / 'settings.json']
        links = {p: os.readlink(p) for p in (config / 'skills').glob('*') if owned_link(p, home)}
        for path in paths:
            if path.is_symlink():
                raise ValueError(f'cannot transactionally replace symlinked plugin settings: {path}')
        backup = recovery.create(config)
        try:
            for path in paths:
                recovery.snapshot(path, backup / path.name)
        except BaseException:
            recovery.discard(backup)  # Nothing has changed yet.
            raise
        try:
            for path in links:
                path.unlink()
            command = (['uninstall', 'hippocampus@hippocampus'] if args.uninstall else
                       ['install', 'hippocampus', '--marketplace', str(ROOT)])
            subprocess.run([args.claude, 'plugin', *command], check=True)
        except BaseException:
            problems = ['the restore was interrupted']
            try:
                problems = rollback(paths, links, backup)
            finally:
                recovery.close(backup, problems)
            raise
        recovery.discard(backup)
    finally:
        lock.rmdir()
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        raise SystemExit('hippocampus Claude install: ' + str(error))
