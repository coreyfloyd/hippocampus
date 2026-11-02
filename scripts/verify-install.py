#!/usr/bin/env python3
"""Verify each registered client against the active, manifest-checked release."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import subprocess


def verify(current: Path, claude: Path, codex: Path) -> None:
    names = sorted(p.name for p in (current / 'skills').iterdir() if (p / 'SKILL.md').is_file())
    registry = claude.parent / 'plugins/installed_plugins.json'
    entries = json.loads(registry.read_text()).get('plugins', {}) if registry.exists() else {}
    plugin = entries.get('hippocampus@hippocampus')
    if plugin is not None:
        if not isinstance(plugin, list) or not plugin:
            raise ValueError(f'claude plugin registration invalid: {registry}')
        # Let Claude resolve user/project/local and managed settings in this
        # invocation's directory, including missing enablement entries.
        result = subprocess.run(['claude', 'plugin', 'list', '--json'],
                                env=dict(os.environ, CLAUDE_CONFIG_DIR=str(claude.parent)),
                                capture_output=True, text=True, check=True, timeout=30)
        plugin = [entry for entry in json.loads(result.stdout)
                  if entry.get('id') == 'hippocampus@hippocampus' and entry.get('enabled') is True
                  and (entry.get('scope') not in ('project', 'local') or
                       entry.get('projectPath') and
                       Path(entry['projectPath']).resolve() == Path.cwd().resolve())] or None
    if plugin is not None:
        for entry in plugin:
            root = entry.get('installPath')
            if not root or Path(root).resolve() != current.resolve():
                raise ValueError(f'claude plugin root is not the current release: {registry}')
    clients = 1 if plugin is not None else 0
    for label, directory in (('claude', claude), ('codex', codex)):
        if label == 'claude' and plugin is not None:
            # The plugin supplies package skills; foreign plain names are user-owned.
            continue
        present = any(os.path.lexists(directory / name) for name in names)
        # A manifest still identifies an installed Codex client if all links vanish.
        if label == 'codex':
            present = present or (directory.parent / 'hippocampus-install.json').exists()
        if not present:
            continue
        clients += 1
        for name in names:
            link = directory / name
            if not link.is_symlink():
                raise ValueError(f'{label} skill link missing: {link}')
            if os.readlink(link) != str(current / 'skills' / name):
                raise ValueError(f'{label} skill target differs: {link}')
    if not clients:
        raise ValueError('no Claude skill links, registered plugin, or Codex skill links')


if __name__ == '__main__':
    try:
        verify(*(Path(argument) for argument in sys.argv[1:]))
    except (OSError, ValueError, TypeError, AttributeError, subprocess.SubprocessError) as error:
        raise SystemExit(f'verify failed: {error}')
