"""Detection-only refusal of a still-installed standalone continuity package."""
import json
import os
import shlex
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def snapshot(root):
    return {str(p.relative_to(root)): ('link', os.readlink(p)) if p.is_symlink() else
            ('directory',) if p.is_dir() else ('file', p.read_bytes())
            for p in root.rglob('*')}


@pytest.mark.parametrize('tool', ['claude', 'codex'])
@pytest.mark.parametrize('evidence', ['claude-runtime', 'claude-registry', 'claude-settings', 'claude-hook', 'claude-link',
                                     'codex-runtime', 'codex-manifest', 'codex-hooks', 'codex-link'])
def test_refuses_before_writes_and_proceeds_after_removal(tmp_path, tool, evidence):
    home = tmp_path / 'home'
    claude = home / 'custom claude'
    codex = home / 'custom codex'
    claude.mkdir(parents=True)
    codex.mkdir()
    old = 'continuity'
    if evidence == 'claude-runtime':
        marker = claude / old
        marker.mkdir()
    elif evidence == 'claude-registry':
        marker = claude / 'plugins/installed_plugins.json'
        marker.parent.mkdir()
        marker.write_text(json.dumps({'version': 2, 'plugins': {old+'@example': [{'scope': 'user'}]}}))
    elif evidence == 'claude-settings':
        marker = claude / 'settings.json'
        marker.write_text(json.dumps({'enabledPlugins': {old+'@example': False}}))
    elif evidence == 'claude-hook':
        marker = claude / 'settings.json'
        marker.write_text(json.dumps({'hooks': {'Stop': [{'hooks': [{'type': 'command',
            'command': 'bash '+shlex.quote(str(claude/old/'hooks/handoff-staleness-guard.sh')), 'timeout': 10}]}]}}))
    elif evidence == 'claude-link':
        marker = claude / 'skills/checkpoint'
        marker.parent.mkdir()
        marker.symlink_to(claude / old / 'skills/checkpoint')
    elif evidence == 'codex-runtime':
        marker = codex / old
        marker.mkdir()
    elif evidence == 'codex-manifest':
        marker = codex / (old+'-install.json')
        marker.write_text('{}')
    elif evidence == 'codex-hooks':
        marker = codex / 'hooks.json'
        marker.write_text(json.dumps({'hooks': {'Stop': [{'hooks': [{'type': 'command',
            'command': 'python3 '+shlex.quote(str(codex/old/'scripts/codex-hook.py'))+' guard-decide', 'timeout': 10}]}]}}))
    else:
        marker = codex / 'skills/checkpoint'
        marker.parent.mkdir()
        marker.symlink_to(codex / old / 'skills/checkpoint')
    cli = tmp_path / 'agent'
    cli.write_text('#!/bin/sh\ntouch "$TEST_CLI_MARKER"\necho CLI_CALLED >&2\nexit 1\n')
    cli.chmod(0o755)
    env = dict(os.environ, HOME=str(home), CLAUDE_CONFIG_DIR=str(claude), CODEX_HOME=str(codex),
               TEST_CLI_MARKER=str(tmp_path/'cli-called'))
    command = [sys.executable, str(ROOT / f'scripts/install-{tool}.py'), '--'+tool, str(cli)]
    before = snapshot(home)
    result = subprocess.run(command, env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert 'continuity' in result.stderr
    assert 'uninstall' in result.stderr
    assert str(marker) in result.stderr
    assert not (tmp_path/'cli-called').exists()
    assert snapshot(home) == before
    if marker.is_dir():
        marker.rmdir()
    else:
        marker.unlink()
    result = subprocess.run(command, env=env, capture_output=True, text=True)
    # The deliberately failing CLI is now reached; the old installation is gone.
    assert (tmp_path/'cli-called').exists(), result.stderr


def test_uninstall_is_allowed_with_old_package_present(tmp_path, monkeypatch):
    sys.path.insert(0, str(ROOT/'scripts'))
    import importlib.util
    spec = importlib.util.spec_from_file_location('conflict_codex', ROOT/'scripts/install-codex.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv('HOME', str(tmp_path))
    home = tmp_path/'.codex'
    (home/'continuity').mkdir(parents=True)
    monkeypatch.setattr(sys, 'argv', ['install', '--codex-home', str(home), '--uninstall'])
    assert module.main() == 0
    assert (home/'continuity').is_dir()


@pytest.mark.parametrize('tool', ['claude', 'codex'])
def test_foreign_mentions_and_unregistered_cache_do_not_block(tmp_path, tool):
    home = tmp_path / 'home'
    claude = home / '.claude'
    codex = home / '.codex'
    (claude/'plugins/cache/continuity/stale-version').mkdir(parents=True)
    (claude/'plugins/installed_plugins.json').write_text(json.dumps({'version': 2, 'plugins': {'foreign@continuity': []}}))
    (claude/'settings.json').write_text(json.dumps({'enabledPlugins': {'foreign@continuity': True}}))
    codex.mkdir()
    (codex/'hooks.json').write_text(json.dumps({'hooks': {'Stop': [{'hooks': [{'type': 'command',
        'command': "echo continuity # don't treat a foreign mention as an install", 'timeout': 1}]}]}}))
    cli = tmp_path/'agent'
    cli.write_text('#!/bin/sh\ntouch "$TEST_CLI_MARKER"\nexit 1\n')
    cli.chmod(0o755)
    result = subprocess.run([sys.executable, str(ROOT/f'scripts/install-{tool}.py'), '--'+tool, str(cli)],
                            env=dict(os.environ, HOME=str(home), CLAUDE_CONFIG_DIR=str(claude),
                                     CODEX_HOME=str(codex), TEST_CLI_MARKER=str(tmp_path/'called')),
                            capture_output=True, text=True)
    assert (tmp_path/'called').exists(), result.stderr


def test_claude_uninstall_is_allowed_with_old_package_present(tmp_path):
    home = tmp_path/'home'
    old = home/'.claude/continuity'
    old.mkdir(parents=True)
    cli = tmp_path/'agent'
    cli.write_text('#!/bin/sh\nexit 0\n')
    cli.chmod(0o755)
    result = subprocess.run([sys.executable, str(ROOT/'scripts/install-claude.py'), '--claude', str(cli), '--uninstall'],
                            env=dict(os.environ, HOME=str(home), CLAUDE_CONFIG_DIR=str(home/'.claude')),
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert old.is_dir()
