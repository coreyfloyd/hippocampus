"""A failed install or uninstall keeps what the user had (issue 151)."""
import errno
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / 'scripts/install-claude.py'
OPERATIONS = pytest.mark.parametrize('operation', [[], ['--uninstall']], ids=['install', 'uninstall'])


def load(name):
    sys.path.insert(0, str(ROOT / 'scripts'))
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), ROOT / f'scripts/{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def tree(path):
    return {str(p.relative_to(path)): p.read_bytes() for p in path.rglob('*') if p.is_file()}


class ClaudeHome:
    """A temporary home holding another plugin, settings and one owned skill link."""

    def __init__(self, base):
        self.home = base
        self.config = base / '.claude'
        self.plugins = self.config / 'plugins'
        for name, text in (('installed_plugins.json', '{"plugins":{"other@market":[]}}'),
                           ('cache/market/other/1.0.0/skill.md', 'other plugin'),
                           ('marketplaces/market/marketplace.json', '{}')):
            path = self.plugins / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        self.settings = self.config / 'settings.json'
        self.settings.write_text('{"enabledPlugins":{"other@market":true}}')
        self.link = self.config / 'skills/checkpoint'
        self.link.parent.mkdir()
        self.target = base / '.local/share/hippocampus/current/skills/checkpoint'
        self.link.symlink_to(self.target)
        self.before = tree(self.plugins)
        self.called = base / 'cli-called'

    def stub(self, body):
        cli = self.home / 'claude-stub'
        cli.write_text(f'#!/bin/sh\ntouch "{self.called}"\ncd "$HOME/.claude/plugins" || exit 9\n{body}\n')
        cli.chmod(0o755)
        return cli

    def env(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith(('CLAUDE_', 'CODEX_'))}
        return dict(env, HOME=str(self.home))

    def run(self, cli, *operation):
        return subprocess.run([sys.executable, str(HELPER), '--claude', str(cli), *operation],
                              env=self.env(), capture_output=True, text=True)

    def backups(self):
        return sorted(self.config.glob('hippocampus-install-backup-*'))

    def assert_restored(self):
        assert tree(self.plugins) == self.before
        assert self.settings.read_text() == '{"enabledPlugins":{"other@market":true}}'
        assert os.readlink(self.link) == str(self.target)


@pytest.fixture
def claude(tmp_path):
    return ClaudeHome(tmp_path)


WIPE = 'rm -rf cache marketplaces installed_plugins.json\necho partial > "$HOME/.claude/settings.json"\nexit 1'


@OPERATIONS
def test_failed_command_restores_every_plugin_file(claude, operation):
    result = claude.run(claude.stub(WIPE), *operation)
    assert result.returncode != 0
    assert 'hippocampus Claude install' in result.stderr
    claude.assert_restored()
    assert not claude.backups()
    assert not (claude.config / '.hippocampus-install-lock').exists()


@OPERATIONS
def test_delete_failing_partway_loses_nothing(claude, operation, monkeypatch, capsys):
    """Any delete during rollback removes one file and then fails, as on a live directory."""
    module = load('install-claude')
    cli = claude.stub(WIPE.removesuffix('exit 1') + 'mkdir -p cache/hippocampus/hippocampus/0.99.0\n'
                      'touch cache/hippocampus/hippocampus/0.99.0/one cache/hippocampus/hippocampus/0.99.0/two\nexit 1')
    real_rmtree = shutil.rmtree

    def fails_partway(path, *args, **kwargs):
        if Path(path).is_relative_to(claude.plugins):
            next(p for p in Path(path).rglob('*') if p.is_file()).unlink()
            raise OSError(errno.ENOTEMPTY, os.strerror(errno.ENOTEMPTY), str(path))
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(shutil, 'rmtree', fails_partway)
    monkeypatch.setenv('HOME', str(claude.home))
    monkeypatch.delenv('CLAUDE_CONFIG_DIR', raising=False)
    monkeypatch.setattr(sys, 'argv', ['install', '--claude', str(cli), *operation])
    with pytest.raises(subprocess.CalledProcessError):
        module.main()
    new = claude.plugins / 'cache/hippocampus/hippocampus/0.99.0'
    assert len(list(new.iterdir())) == 1
    real_rmtree(claude.plugins / 'cache/hippocampus')
    claude.assert_restored()
    assert 'left in place' in capsys.readouterr().err


def test_undeletable_new_entry_does_not_stop_the_restore(claude):
    new = claude.plugins / 'cache/hippocampus/hippocampus/0.99.0'
    cli = claude.stub(WIPE.removesuffix('exit 1') + f'mkdir -p "{new}"\ntouch "{new}/file"\nchmod 555 "{new}"\nexit 1')
    result = claude.run(cli)
    new.chmod(0o755)
    assert result.returncode != 0
    assert 'left in place' in result.stderr
    shutil.rmtree(claude.plugins / 'cache/hippocampus')
    claude.assert_restored()
    assert not claude.backups()


def test_rollback_keeps_what_another_tool_added_during_the_run(claude):
    cli = claude.stub('mkdir -p data/other cache/hippocampus\ntouch data/other/session.json cache/hippocampus/partial\n'
                      'rm installed_plugins.json\nexit 1')
    assert claude.run(cli).returncode != 0
    assert (claude.plugins / 'data/other/session.json').is_file()
    assert not (claude.plugins / 'cache/hippocampus').exists()
    assert (claude.plugins / 'installed_plugins.json').is_file()


def test_rollback_keeps_a_recreated_private_directory_private(claude):
    private = claude.plugins / 'store'
    private.mkdir()
    private.chmod(0o700)
    (private / 'secret').write_text('value')
    assert claude.run(claude.stub('rm -rf store\nexit 1')).returncode != 0
    assert private.stat().st_mode & 0o777 == 0o700
    assert (private / 'secret').read_text() == 'value'


@OPERATIONS
def test_incomplete_restore_keeps_and_prints_the_backup(claude, operation):
    cli = claude.stub('rm -f installed_plugins.json\nchmod 555 .\nexit 1')
    result = claude.run(cli, *operation)
    claude.plugins.chmod(0o755)
    assert result.returncode != 0
    [backup] = claude.backups()
    assert f'The backup is kept at {backup}' in result.stderr
    assert 'installed_plugins.json' in result.stderr
    assert tree(backup / 'plugins') == claude.before
    assert (backup / 'settings.json').is_file()
    # The links do not depend on the plugin directory.
    assert os.readlink(claude.link) == str(claude.target)
    claude.called.unlink()
    again = claude.run(claude.stub('exit 0'), *operation)
    assert again.returncode != 0
    assert str(backup) in again.stderr
    assert not claude.called.exists()
    assert tree(backup / 'plugins') == claude.before


def test_stopped_snapshot_changes_nothing_and_leaves_no_backup(claude):
    os.mkfifo(claude.plugins / 'pipe')
    result = claude.run(claude.stub('exit 0'))
    assert result.returncode != 0
    assert not claude.called.exists()
    (claude.plugins / 'pipe').unlink()
    claude.assert_restored()
    assert not claude.backups()


@pytest.mark.parametrize('source,shown', [
    ({'source': 'directory', 'path': '/elsewhere/checkout'}, 'dir:/elsewhere/checkout'),
    ({'source': 'github', 'repo': 'someone/fork'}, 'github:someone/fork'),
])
def test_foreign_marketplace_is_reported_before_any_change(claude, source, shown):
    registry = claude.plugins / 'known_marketplaces.json'
    registry.write_text(json.dumps({'hippocampus': {'source': source}}))
    claude.before = tree(claude.plugins)
    result = claude.run(claude.stub(WIPE))
    assert result.returncode != 0
    assert shown in result.stderr
    assert 'claude plugin marketplace remove hippocampus' in result.stderr
    assert not claude.called.exists()
    claude.assert_restored()
    assert sorted(p.name for p in claude.config.iterdir()) == ['plugins', 'settings.json', 'skills']


def test_same_source_marketplace_and_other_names_proceed(claude):
    registry = claude.plugins / 'known_marketplaces.json'
    registry.write_text(json.dumps({'hippocampus': {'source': {'source': 'directory', 'path': str(ROOT)}},
                                    'market': {'source': {'source': 'github', 'repo': 'someone/market'}}}))
    result = claude.run(claude.stub('exit 0'))
    assert result.returncode == 0, result.stderr
    assert claude.called.exists()
    assert not claude.link.is_symlink()
    assert not claude.backups()


def test_uninstall_is_not_blocked_by_another_source(claude):
    registry = claude.plugins / 'known_marketplaces.json'
    registry.write_text(json.dumps({'hippocampus': {'source': {'source': 'directory', 'path': '/elsewhere'}}}))
    assert claude.run(claude.stub('exit 0'), '--uninstall').returncode == 0
    assert claude.called.exists()


def test_real_claude_conflict_is_caught_and_the_printed_command_resolves_it(tmp_path):
    cli = shutil.which('claude')
    if not cli:
        pytest.skip('claude command unavailable')
    source = tmp_path / 'other-release'
    shutil.copytree(ROOT, source, ignore=shutil.ignore_patterns('.git', '.build', '__pycache__', '.pytest_cache'))
    home = tmp_path / 'home'
    home.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith(('CLAUDE_', 'CODEX_'))}
    env.update(HOME=str(home), CLAUDE_CODE_ENTRYPOINT='cli')

    def helper(tree_root):
        return subprocess.run([sys.executable, str(tree_root / 'scripts/install-claude.py'), '--claude', cli],
                              env=env, capture_output=True, text=True, timeout=180)

    first = helper(ROOT)
    assert first.returncode == 0, first.stdout + first.stderr
    plugins = home / '.claude/plugins'
    before = tree(plugins)
    refused = helper(source.resolve())
    assert refused.returncode != 0
    assert f'dir:{ROOT}' in refused.stderr
    assert tree(plugins) == before
    subprocess.run([cli, 'plugin', 'marketplace', 'remove', 'hippocampus'], env=env, check=True,
                   capture_output=True, timeout=60)
    second = helper(source.resolve())
    assert second.returncode == 0, second.stdout + second.stderr


@pytest.fixture
def codex(tmp_path, monkeypatch):
    """An installed Codex copy, with hooks, trust, links and a runtime to protect."""
    home = tmp_path / '.codex'
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setenv('CODEX_HOME', str(home))
    module = load('install-codex')
    monkeypatch.setattr(module.trust, 'verify_with_hooks_list', lambda *args: None)
    monkeypatch.setattr(sys, 'argv', ['install', '--codex-home', str(home), '--codex', 'codex'])
    assert module.main() == 0
    package = tmp_path / '.local/share/hippocampus/current'
    (package / 'previous-runtime-marker').write_text('original runtime')
    return module, home, package


def codex_state(home):
    return ({name: (home / name).read_bytes() for name in ('hooks.json', 'config.toml', 'hippocampus-install.json')},
            {p.name: os.readlink(p) for p in (home / 'skills').iterdir()})


def fail_the_run(module, monkeypatch, home, operation):
    """Fail after the first changes: at trust verification, or at manifest removal."""
    if operation:
        real_unlink = Path.unlink

        def refuse(path, *args, **kwargs):
            if path == home / 'hippocampus-install.json':
                raise OSError('manifest removal refused')
            return real_unlink(path, *args, **kwargs)
        monkeypatch.setattr(Path, 'unlink', refuse)
    else:
        def refuse(*args):
            raise RuntimeError('trust refused')
        monkeypatch.setattr(module.trust, 'verify_with_hooks_list', refuse)
    monkeypatch.setattr(sys, 'argv', ['install', '--codex-home', str(home), '--codex', 'codex', *operation])


@OPERATIONS
def test_codex_failed_file_restore_still_restores_links_and_runtime(codex, operation, monkeypatch, capsys):
    module, home, package = codex
    before = codex_state(home)
    fail_the_run(module, monkeypatch, home, operation)
    real_restore = module.trust.restore_file

    def refuse_hooks(path, content):
        if path == home / 'hooks.json':
            raise OSError('hooks restore refused')
        return real_restore(path, content)

    monkeypatch.setattr(module.trust, 'restore_file', refuse_hooks)
    with pytest.raises((OSError, RuntimeError), match='refused'):
        module.main()
    error = capsys.readouterr().err
    [backup] = home.glob('hippocampus-install-backup-*')
    assert f'The backup is kept at {backup}' in error
    assert 'hooks restore refused' in error
    assert (backup / 'hooks.json').read_bytes() == before[0]['hooks.json']
    assert (backup / 'config.toml').read_bytes() == before[0]['config.toml']
    assert codex_state(home)[1] == before[1]
    assert (package / 'previous-runtime-marker').read_text() == 'original runtime'
    monkeypatch.setattr(module.trust, 'restore_file', real_restore)
    monkeypatch.setattr(sys, 'argv', ['install', '--codex-home', str(home), '--codex', 'codex'])
    with pytest.raises(ValueError, match=str(backup.name)):
        module.main()
    assert backup.is_dir()


def test_codex_partial_delete_keeps_the_runtime_backup_and_links(codex, monkeypatch, capsys):
    module, home, package = codex
    before = codex_state(home)
    fail_the_run(module, monkeypatch, home, [])
    real_rmtree = shutil.rmtree

    def fails_partway(path, *args, **kwargs):
        if Path(path) == package:
            raise OSError(errno.ENOTEMPTY, os.strerror(errno.ENOTEMPTY), str(path))
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(shutil, 'rmtree', fails_partway)
    with pytest.raises(RuntimeError, match='trust refused'):
        module.main()
    runtime = package.parent / 'hippocampus-install-backup'
    error = capsys.readouterr().err
    assert f'The backup is kept at {runtime}' in error
    assert (runtime / 'previous-runtime-marker').read_text() == 'original runtime'
    assert codex_state(home) == before
    monkeypatch.setattr(sys, 'argv', ['install', '--codex-home', str(home), '--codex', 'codex'])
    with pytest.raises(ValueError, match='hippocampus-install-backup'):
        module.main()


@OPERATIONS
def test_codex_completed_restore_leaves_no_backup(codex, operation, monkeypatch):
    module, home, package = codex
    before = codex_state(home)
    fail_the_run(module, monkeypatch, home, operation)
    with pytest.raises((OSError, RuntimeError), match='refused'):
        module.main()
    assert codex_state(home) == before
    assert not list(home.glob('hippocampus-install-backup-*'))
    assert not (package.parent / 'hippocampus-install-backup').exists()
    assert (package / 'previous-runtime-marker').read_text() == 'original runtime'
