#!/usr/bin/env python3
"""Transactionally install the Claude plugin from a checkout or extracted release."""
from __future__ import annotations

import argparse
import contextlib
import os
from pathlib import Path
import shutil
import subprocess
import sys

from lib import install_recovery as recovery
from lib.install_conflicts import PLUGIN, marketplace_plan, read_object, refuse_standalone

ROOT = Path(__file__).resolve().parent.parent


def owned_link(path, home):
    if not path.is_symlink():
        return False
    target = Path(os.readlink(path))
    root = home / '.local/share/hippocampus'
    return (target == root / 'current/skills' / path.name or
            target.parent.name == 'skills' and target.name == path.name and
            target.parent.parent.parent == root / 'releases')


def marketplace_source(runtime):
    """Register releases through `current`, so an upgrade keeps the same source."""
    if ROOT.parent != (runtime / 'releases').resolve():
        return ROOT
    current = runtime / 'current'
    if current.resolve() != ROOT:
        raise ValueError(f'this release is not active; run the helper from {current}')
    return current


def install(claude, plan, source, config):
    def cli(*command):
        subprocess.run([claude, 'plugin', *command], check=True)

    add = ('install', 'hippocampus', '--marketplace', str(source))
    if plan == 'registered':
        # A moved `current` is the same source: install is a no-op, update records it.
        cli(*add)
        cli('marketplace', 'update', 'hippocampus')
        cli('update', PLUGIN)
    elif plan == 'earlier-release':
        # The CLI cannot change a marketplace's source, and uninstalling clears
        # the plugin's options and enablement, so those are carried across.
        settings = config / 'settings.json'
        value = read_object(settings)
        options = value.get('pluginConfigs', {}).get(PLUGIN)
        disabled = value.get('enabledPlugins', {}).get(PLUGIN) is False
        if PLUGIN in read_object(config / 'plugins/installed_plugins.json').get('plugins', {}):
            cli('uninstall', PLUGIN, '--keep-data')
        cli('marketplace', 'remove', 'hippocampus')
        cli(*add)
        if options is not None:
            recovery.write_plugin_options(settings, options)
        if disabled:
            cli('disable', PLUGIN)
    else:
        cli(*add)


def rollback(paths, links, backup):
    """Restore every path and link it can; return what it could not restore."""
    problems, leftovers = [], []
    for path, target in links.items():
        if not os.path.lexists(path):
            recovery.attempt(problems, f'skill link {path} -> {target}', path.symlink_to, target)
    plugins, settings = paths
    saved = backup / plugins.name
    existed = os.path.lexists(saved)
    if existed:
        recovery.restore(saved, plugins, problems)
    if plugins.is_dir():
        recovery.prune(saved, plugins, leftovers)
    for name in recovery.REGISTRIES:
        if not os.path.lexists(saved / name):
            recovery.attempt(problems, str(plugins / name), recovery.forget_registrations, plugins / name)
    if not existed:
        with contextlib.suppress(OSError):  # Another tool's files keep it in place.
            plugins.rmdir()
    if os.path.lexists(backup / settings.name):
        recovery.restore(backup / settings.name, settings, problems)
    else:
        recovery.attempt(problems, str(settings), recovery.forget_registrations, settings)
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
    runtime = home / '.local/share/hippocampus'
    if not args.uninstall:
        source = marketplace_source(runtime)
        plan = marketplace_plan(config, source, runtime)
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
            if args.uninstall:
                subprocess.run([args.claude, 'plugin', 'uninstall', PLUGIN], check=True)
            else:
                install(args.claude, plan, source, config)
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
