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


def test_failed_first_install_keeps_the_directory_and_other_sessions_state(tmp_path):
    claude = ClaudeHome(tmp_path)
    shutil.rmtree(claude.plugins)
    cli = claude.home / 'claude-stub'
    cli.write_text("""#!/bin/sh
mkdir -p "$HOME/.claude/plugins/data/other" "$HOME/.claude/plugins/cache/hippocampus"
touch "$HOME/.claude/plugins/data/other/session.json" "$HOME/.claude/plugins/cache/hippocampus/partial"
exit 1
""")
    cli.chmod(0o755)
    assert claude.run(cli).returncode != 0
    assert (claude.plugins / 'data/other/session.json').is_file()
    assert not (claude.plugins / 'cache/hippocampus').exists()
    assert os.readlink(claude.link) == str(claude.target)


def test_failed_first_install_with_nothing_else_leaves_no_directory(tmp_path):
    claude = ClaudeHome(tmp_path)
    shutil.rmtree(claude.plugins)
    cli = claude.home / 'claude-stub'
    cli.write_text('#!/bin/sh\nmkdir -p "$HOME/.claude/plugins/cache/hippocampus"\nexit 1\n')
    cli.chmod(0o755)
    assert claude.run(cli).returncode != 0
    assert not claude.plugins.exists()


HIPPOCAMPUS_ONLY = """cat > known_marketplaces.json <<'J'
{"hippocampus": {"source": {"source": "directory", "path": "/somewhere"}}}
J
cat > installed_plugins.json <<'J'
{"version": 2, "plugins": {"hippocampus@hippocampus": [{"scope": "user"}]}}
J
exit 1"""


def test_failed_install_leaves_no_registration_in_registries_it_created(claude):
    (claude.plugins / 'installed_plugins.json').unlink()
    claude.before = tree(claude.plugins)
    assert claude.run(claude.stub(HIPPOCAMPUS_ONLY)).returncode != 0
    assert tree(claude.plugins) == claude.before


def test_new_registry_keeps_entries_another_tool_added(claude):
    (claude.plugins / 'installed_plugins.json').unlink()
    stub = """cat > known_marketplaces.json <<'J'
{"hippocampus": {"source": {}}, "market": {"source": {"source": "github", "repo": "someone/market"}}}
J
cat > installed_plugins.json <<'J'
{"version": 2, "plugins": {"hippocampus@hippocampus": [], "other@market": [{"scope": "user"}]}}
J
exit 1"""
    assert claude.run(claude.stub(stub)).returncode != 0
    assert list(json.loads((claude.plugins / 'known_marketplaces.json').read_text())) == ['market']
    assert list(json.loads((claude.plugins / 'installed_plugins.json').read_text())['plugins']) == ['other@market']


def test_failed_install_restores_registries_that_existed(claude):
    registry = claude.plugins / 'known_marketplaces.json'
    registry.write_text('{"market": {"source": {"source": "github", "repo": "someone/market"}}}')
    claude.before = tree(claude.plugins)
    assert claude.run(claude.stub(HIPPOCAMPUS_ONLY)).returncode != 0
    assert tree(claude.plugins) == claude.before


def test_failed_install_removes_only_its_entries_from_new_settings(claude):
    claude.settings.unlink()
    body = """cat > "$HOME/.claude/settings.json" <<'J'
{"enabledPlugins": {"hippocampus@hippocampus": true, "other@market": true},
 "extraKnownMarketplaces": {"hippocampus": {"source": {}}}}
J
exit 1"""
    assert claude.run(claude.stub(body)).returncode != 0
    assert json.loads(claude.settings.read_text()) == {'enabledPlugins': {'other@market': True}}


class Releases:
    """Two real release folders under one runtime root, driven through their helpers."""

    def __init__(self, base, cli):
        self.base = base
        self.home = base / 'home'
        self.home.mkdir()
        self.runtime = self.home / '.local/share/hippocampus'
        self.current = self.runtime / 'current'
        self.config = self.home / '.claude'
        self.cli = cli
        path = os.environ['PATH'] if cli == 'claude' else str(ROOT / 'tests/fixtures/install-route') + os.pathsep + os.environ['PATH']
        env = {k: v for k, v in os.environ.items() if not k.startswith(('CLAUDE_', 'CODEX_', 'XDG_'))}
        self.env = dict(env, HOME=str(self.home), PATH=path, CODEX_HOME=str(self.home / '.codex'),
                        XDG_CONFIG_HOME=str(self.home / '.config'), XDG_DATA_HOME=str(self.home / '.local/share'),
                        CLAUDE_CODE_ENTRYPOINT='cli')

    def activate(self, version):
        tree_root = self.base / f'source-{version}'
        shutil.copytree(ROOT, tree_root, ignore=shutil.ignore_patterns('.git', '.build', '__pycache__', '.pytest_cache'))
        (tree_root / 'VERSION').write_text(version + '\n')
        manifest = tree_root / '.claude-plugin/plugin.json'
        manifest.write_text(json.dumps(dict(json.loads(manifest.read_text()), version=version)))
        self.run('bash', tree_root / 'install.sh')
        knowledge = self.home / 'knowledge'
        if not knowledge.exists():
            for folder in ('raw', 'wiki', 'output', 'docs'):
                (knowledge / folder).mkdir(parents=True)
            for name in ('wiki/hot.md', 'docs/log.md', 'docs/DECISIONS.md'):
                (knowledge / name).touch()
            (self.home / '.config/hippocampus/profile.md').write_text(
                (ROOT / 'profiles/karpathy-wiki.example.md').read_text().replace('/absolute/path/to/knowledge', str(knowledge)))

    def run(self, *command, check=True):
        result = subprocess.run([str(part) for part in command], env=self.env, cwd=self.home,
                                capture_output=True, text=True, timeout=180)
        assert not check or result.returncode == 0, result.stdout + result.stderr
        return result

    def helper(self, cli=None, check=True):
        return self.run(sys.executable, self.current / 'scripts/install-claude.py', '--claude', cli or self.cli, check=check)

    def register_old_style(self, version):
        """What 0.14.0 helpers left behind: the marketplace on the release folder."""
        self.run(self.cli, 'plugin', 'install', 'hippocampus', '--marketplace', self.runtime / 'releases' / version)
        links = self.config / 'skills'
        shutil.rmtree(links)
        links.mkdir()

    def add_state(self):
        data = self.config / 'plugins/data/hippocampus-hippocampus/state'
        data.parent.mkdir(parents=True)
        data.write_text('kept')
        settings = self.config / 'settings.json'
        value = json.loads(settings.read_text())
        value['pluginConfigs'] = {'hippocampus@hippocampus': {'options': {'retention': 'long'}}}
        settings.write_text(json.dumps(value))

    def assert_state(self):
        assert (self.config / 'plugins/data/hippocampus-hippocampus/state').read_text() == 'kept'
        value = json.loads((self.config / 'settings.json').read_text())
        assert value['pluginConfigs']['hippocampus@hippocampus'] == {'options': {'retention': 'long'}}

    def plugin(self):
        rows = json.loads(self.run(self.cli, 'plugin', 'list', '--json').stdout)
        return next(row for row in rows if row['id'] == 'hippocampus@hippocampus')


CLIS = pytest.mark.parametrize('cli', ['stub', 'claude'])


def releases_for(tmp_path, cli):
    if cli == 'claude' and not shutil.which('claude'):
        pytest.skip('claude command unavailable')
    return Releases(tmp_path, 'claude') if cli == 'claude' else Releases(tmp_path, str(ROOT / 'tests/fixtures/install-route/claude'))


@CLIS
@pytest.mark.parametrize('start', ['stable-source', 'release-folder'])
def test_upgrade_completes_unattended_and_keeps_options_and_data(tmp_path, cli, start):
    releases = releases_for(tmp_path, cli)
    releases.activate('9.0.0')
    if start == 'stable-source':
        releases.helper()
    else:
        releases.register_old_style('9.0.0')
    releases.add_state()
    releases.activate('9.0.1')
    releases.helper()
    releases.assert_state()
    row = releases.plugin()
    assert row['version'] == '9.0.1' and row['enabled'] is True
    assert row['readFromFolder'] == str(releases.current)
    registered = json.loads((releases.config / 'plugins/known_marketplaces.json').read_text())
    assert registered['hippocampus']['source']['path'] == str(releases.current)
    releases.run('bash', releases.current / 'install.sh', '--verify')
    assert not list(releases.config.glob('hippocampus-install-backup-*'))
    # The next upgrade runs from the stable source.
    releases.activate('9.0.2')
    releases.helper()
    releases.assert_state()
    assert releases.plugin()['version'] == '9.0.2'
    releases.run('bash', releases.current / 'install.sh', '--verify')


@CLIS
def test_move_to_the_stable_source_keeps_a_disabled_plugin_disabled(tmp_path, cli):
    releases = releases_for(tmp_path, cli)
    releases.activate('9.0.0')
    releases.register_old_style('9.0.0')
    releases.run(releases.cli, 'plugin', 'disable', 'hippocampus@hippocampus')
    releases.activate('9.0.1')
    releases.helper()
    assert releases.plugin()['enabled'] is False


@pytest.mark.parametrize('failing', ['install', 'update'])
@pytest.mark.parametrize('start', ['stable-source', 'release-folder'])
def test_failed_upgrade_restores_the_registration(tmp_path, start, failing):
    releases = releases_for(tmp_path, 'stub')
    releases.activate('9.0.0')
    if start == 'stable-source':
        releases.helper()
    else:
        releases.register_old_style('9.0.0')
    releases.add_state()
    plugins = releases.config / 'plugins'
    before = {name: (plugins / name).read_text() for name in ('known_marketplaces.json', 'installed_plugins.json')}
    settings = (releases.config / 'settings.json').read_text()
    releases.activate('9.0.1')
    wrapper = tmp_path / 'failing-claude'
    # The move from a release folder has no update step, so its last step fails instead.
    step = failing if start == 'stable-source' else 'install'
    wrapper.write_text(f'#!/bin/sh\n[ "$2" = {step} ] && exit 1\nexec "{releases.cli}" "$@"\n')
    wrapper.chmod(0o755)
    result = releases.helper(wrapper, check=False)
    assert result.returncode != 0
    assert {name: (plugins / name).read_text() for name in before} == before
    assert (releases.config / 'settings.json').read_text() == settings
    releases.assert_state()
    assert not (plugins / 'cache/hippocampus/hippocampus/9.0.1').exists()
    assert (plugins / 'cache/hippocampus/hippocampus/9.0.0').is_dir()


def test_inactive_release_is_refused_before_any_change(tmp_path):
    releases = releases_for(tmp_path, 'stub')
    releases.activate('9.0.0')
    releases.activate('9.0.1')
    result = releases.run(sys.executable, releases.runtime / 'releases/9.0.0/scripts/install-claude.py',
                          '--claude', releases.cli, check=False)
    assert result.returncode != 0
    assert 'run the helper from' in result.stderr
    assert not (releases.config / 'plugins').exists()


def test_project_scope_install_is_reported_before_the_move(tmp_path):
    releases = releases_for(tmp_path, 'stub')
    releases.activate('9.0.0')
    releases.register_old_style('9.0.0')
    registry = releases.config / 'plugins/installed_plugins.json'
    value = json.loads(registry.read_text())
    value['plugins']['hippocampus@hippocampus'][0]['scope'] = 'project'
    registry.write_text(json.dumps(value))
    releases.activate('9.0.1')
    result = releases.helper(check=False)
    assert result.returncode != 0
    assert '--keep-data --scope project' in result.stderr
    assert json.loads(registry.read_text()) == value


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
