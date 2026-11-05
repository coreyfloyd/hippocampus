"""Durable install backups, and a rollback that survives its own failed steps.

Claude Code sessions write into the plugin directory while an install runs, so
that directory is never deleted and replaced: only what differs from the backup
is copied back. A backup stays on disk until the restore has finished.
"""
from __future__ import annotations

import contextlib
import filecmp
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile

from lib.codex_trust import atomic_write

PREFIX = 'hippocampus-install-backup-'
OWNED_NAME = 'hippocampus'
PLUGIN = 'hippocampus@hippocampus'
REGISTRIES = ('known_marketplaces.json', 'installed_plugins.json')
REGISTRY_FIELDS = ('plugins', 'enabledPlugins', 'extraKnownMarketplaces', 'pluginConfigs')


def refuse_pending(directory):
    """Refuse a new run while an earlier failed restore still needs the user."""
    pending = sorted(directory.glob(PREFIX + '*'))
    if pending:
        raise ValueError('an earlier install backup needs recovery before installing: ' +
                         ', '.join(map(str, pending)))


def create(directory):
    return Path(tempfile.mkdtemp(prefix=PREFIX, dir=directory))


def snapshot(path, saved):
    if path.is_dir():
        shutil.copytree(path, saved, symlinks=True)
    elif path.exists():
        shutil.copy2(path, saved)


def remove(path):
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def attempt(problems, label, action, *arguments):
    """Run one rollback step; a failure is recorded so later steps still run."""
    try:
        action(*arguments)
    except (OSError, ValueError) as error:
        problems.append(f'{label}: {error}')


def identical(saved, live):
    if not os.path.lexists(live):
        return False
    first, second = saved.lstat(), live.lstat()
    if first.st_mode != second.st_mode:
        return False
    if stat.S_ISLNK(first.st_mode):
        return os.readlink(saved) == os.readlink(live)
    return filecmp.cmp(saved, live, shallow=False)


def put_file(saved, live):
    if identical(saved, live):
        return
    if live.is_dir() and not live.is_symlink():
        shutil.rmtree(live)
    temporary = live.with_name(f'.{live.name}.restore-{os.getpid()}')
    try:
        shutil.copy2(saved, temporary, follow_symlinks=False)
        os.replace(temporary, live)
    finally:
        if os.path.lexists(temporary):
            temporary.unlink()


def enter_directory(live):
    if live.is_symlink() or live.is_file():
        live.unlink()
    live.mkdir(exist_ok=True)


def restore(saved, live, problems):
    """Copy back whatever is missing or changed, one entry at a time."""
    if saved.is_symlink() or not saved.is_dir():
        attempt(problems, str(live), put_file, saved, live)
        return
    created = not live.is_dir()
    attempt(problems, str(live), enter_directory, live)
    if live.is_dir():
        for child in sorted(saved.iterdir()):
            restore(child, live / child.name, problems)
        if created:  # A recreated private directory must not come back wider.
            attempt(problems, str(live), shutil.copystat, saved, live)


def prune(saved, live, leftovers, parents=()):
    """Remove new entries the failed command owns; other tools' entries stay."""
    try:
        entries = sorted(live.iterdir())
    except OSError as error:
        leftovers.append(f'{live}: {error}')
        return
    for entry in entries:
        names = (*parents, entry.name)
        kept = saved / entry.name
        new = not os.path.lexists(kept)
        if new and any(OWNED_NAME in name for name in names):
            attempt(leftovers, str(entry), remove, entry)
        elif entry.is_dir() and not entry.is_symlink():
            prune(kept, entry, leftovers, names)
            if new:  # A folder made only for owned entries goes with them.
                with contextlib.suppress(OSError):
                    entry.rmdir()


def forget_registrations(path):
    """Remove exactly the hippocampus entries from a file the run created."""
    if not path.exists():
        return
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f'expected configuration object: {path}')
    fields = [field for field in REGISTRY_FIELDS if isinstance(value.get(field), dict)]
    for container in (value, *(value[field] for field in fields)):
        container.pop(OWNED_NAME, None)
        container.pop(PLUGIN, None)
    for field in fields:
        if not value[field]:
            del value[field]
    if set(value) <= {'version'}:
        path.unlink()
    else:
        atomic_write(path, json.dumps(value, indent=2) + '\n')


def write_plugin_options(path, options):
    value = json.loads(path.read_text())
    value.setdefault('pluginConfigs', {})[PLUGIN] = options
    atomic_write(path, json.dumps(value, indent=2) + '\n')


def discard(backup):
    try:
        shutil.rmtree(backup)
    except OSError as error:
        print(f'hippocampus install: could not delete the backup at {backup}: {error}\n'
              'Delete that folder before the next install.', file=sys.stderr)


def close(backup, problems, kept=()):
    """Delete a backup whose restore finished; otherwise keep it and say where."""
    if not problems:
        discard(backup)
        return
    paths = [backup, *kept]
    print('hippocampus install: the restore did not finish.\n' +
          ''.join(f'  {problem}\n' for problem in problems) +
          ''.join(f'The backup is kept at {path}\n' for path in paths) +
          'Copy back what is missing, then delete the backup; '
          'the next install refuses until then.', file=sys.stderr)
