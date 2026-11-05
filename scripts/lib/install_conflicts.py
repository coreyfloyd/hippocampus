"""Read-only preflight for incompatible standalone-package installations."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shlex

OLD_PACKAGE = 'continuity'
MARKETPLACE = 'hippocampus'


def read_object(path):
    if not path.exists():
        return {}
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f'expected configuration object: {path}')
    return value


def uses_runtime(command, runtime):
    """Match a shell argument inside the old runtime, including quoted paths."""
    for argument in shlex.split(command, comments=True):
        path = Path(os.path.expandvars(argument)).expanduser()
        if path.is_absolute() and path.is_relative_to(runtime):
            return True
    return False


def registration_markers(home, runtime, hooks_path):
    markers = []
    for path in (home/'skills').glob('*'):
        if path.is_symlink():
            destination = Path(os.readlink(path))
            if not destination.is_absolute():
                destination = path.parent/destination
            if Path(os.path.abspath(destination)).is_relative_to(runtime):
                markers.append(path)
    hooks = read_object(hooks_path).get('hooks', {})
    if not isinstance(hooks, dict):
        raise ValueError(f'expected hooks object: {hooks_path}')
    if any(uses_runtime(handler.get('command', ''), runtime)
           for groups in hooks.values() for group in groups for handler in group.get('hooks', [])
           if handler.get('type') == 'command'):
        markers.append(hooks_path)
    return markers


def refuse_standalone(*, claude_home=None, codex_home=None):
    """Refuse installation only; never uninstall, migrate, or alter old state."""
    claude = Path(claude_home or os.environ.get('CLAUDE_CONFIG_DIR') or Path.home()/'.claude').expanduser().resolve()
    codex = Path(codex_home or os.environ.get('CODEX_HOME') or Path.home()/'.codex').expanduser().resolve()
    blockers = []
    runtime = claude/OLD_PACKAGE
    if os.path.lexists(runtime):
        blockers.append(f'{runtime}: uninstall the old Claude package and remove its runtime at this path')
    for path in registration_markers(claude, runtime, claude/'settings.json'):
        blockers.append(f'{path}: uninstall the old Claude package and remove its stale hook/skill registration')
    for path, field in ((claude/'plugins/installed_plugins.json', 'plugins'),
                        (claude/'settings.json', 'enabledPlugins')):
        entries = read_object(path).get(field, {})
        if not isinstance(entries, dict):
            raise ValueError(f'expected {field} object: {path}')
        for name in entries:
            if name.split('@', 1)[0] == OLD_PACKAGE:
                blockers.append(f'{path}: run claude plugin uninstall {shlex.quote(name)}')
    runtime = codex/OLD_PACKAGE
    manifest = codex/(OLD_PACKAGE+'-install.json')
    markers = [path for path in (runtime, manifest) if os.path.lexists(path)]
    markers.extend(registration_markers(codex, runtime, codex/'hooks.json'))
    uninstall = f'python3 {shlex.quote(str(runtime/"scripts/install-codex.py"))} --uninstall'
    for path in markers:
        blockers.append(f'{path}: uninstall the old Codex package with {uninstall}; remove stale registrations/links if its runtime is missing')
    if blockers:
        raise ValueError(f'old standalone {OLD_PACKAGE} package is installed; remove it before installing hippocampus:\n' + '\n'.join(blockers))


def describe_source(source):
    if isinstance(source, dict):
        kind = source.get('source')
        if kind == 'directory' and source.get('path'):
            return 'dir:' + str(source['path'])
        if kind == 'github' and source.get('repo'):
            return 'github:' + str(source['repo'])
    return json.dumps(source)


def refuse_foreign_marketplace(claude_home, root):
    """Report a same-named marketplace from another source before any change.

    Claude Code compares a directory source as written, so this does too: the
    same folder through a different path also fails its add step.
    """
    entry = read_object(claude_home/'plugins/known_marketplaces.json').get(MARKETPLACE)
    if entry is None:
        return
    source = entry.get('source') if isinstance(entry, dict) else entry
    if source == {'source': 'directory', 'path': str(root)}:
        return
    raise ValueError(
        f'a {MARKETPLACE} marketplace is already registered from another source '
        f'({describe_source(source)}); nothing was changed.\n'
        f'To install from {root}, run: claude plugin marketplace remove {MARKETPLACE}\n'
        'That also uninstalls the hippocampus plugin and can delete its saved options '
        'and data. Then run this helper again.')
