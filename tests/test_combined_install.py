"""Combined-package installation ownership and rollback contracts."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def install_home(monkeypatch):
    """Route each fixture's installer and CLI to the same test-owned home."""
    def bind(home):
        for key, path in (("HOME", home), ("CLAUDE_CONFIG_DIR", home / ".claude"),
                          ("CODEX_HOME", home / ".codex")):
            monkeypatch.setenv(key, str(path))
        return dict(os.environ)
    return bind


@pytest.mark.parametrize('ci', [False, True])
def test_codex_cli_checks_skip_without_the_codex_command(tmp_path, ci):
    path = tmp_path / 'bin'
    path.mkdir()
    git = shutil.which('git')
    assert git
    (path / 'git').symlink_to(git)
    env = dict(os.environ, PATH=str(path), HOME=str(tmp_path / 'home'),
               CODEX_HOME=str(tmp_path / 'home/.codex'), PYTHONDONTWRITEBYTECODE='1')
    env.pop('CI', None)
    env.pop('GITHUB_ACTIONS', None)
    if ci:
        env.update(CI='true', GITHUB_ACTIONS='true')
    checks = {
        'tests/test_codex_adapter.py::test_one_install_registers_six_hooks_and_guard_preserves_other_entries_and_uninstalls': ('1 skipped', 'codex command unavailable'),
        'tests/test_codex_adapter.py::test_install_collision_and_verification_failure_do_not_change_user_files': ('1 passed',),
        'tests/test_codex_adapter.py::test_remove_trust_preserves_adjacent_comments_and_blank_lines': ('1 passed',),
        'tests/test_record_writes.py::test_mid_session_then_checkpoint_and_wrap_in_both_tools': ('1 passed',),
        'tests/test_record_writes.py::test_record_skill_is_shipped_in_both_installations': ('1 skipped', 'codex command unavailable'),
        'tests/test_combined_install.py::test_codex_install_from_extracted_tree_verifies_native_trust': ('1 skipped', 'codex command unavailable'),
    }
    for node, expected in checks.items():
        result = subprocess.run([sys.executable, '-m', 'pytest', '-q', '-rs', node], cwd=ROOT,
                                env=env, capture_output=True, text=True)
        if ci and '1 skipped' in expected:
            assert result.returncode != 0, result.stdout + result.stderr
            assert 'codex command required in CI' in result.stdout
        else:
            assert result.returncode == 0, result.stdout + result.stderr
            assert all(value in result.stdout for value in expected)


def installer():
    sys.path.insert(0, str(ROOT / 'scripts'))
    spec = importlib.util.spec_from_file_location('combined_codex', ROOT / 'scripts/install-codex.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_codex_adopts_old_installer_and_uninstall_keeps_replaced_link(tmp_path, monkeypatch):
    monkeypatch.setenv('HOME', str(tmp_path))
    home = tmp_path / '.codex'
    env = dict(os.environ, CODEX_HOME=str(home))
    subprocess.run(['bash', str(ROOT / 'install.sh')], env=env, check=True, capture_output=True)
    assert (tmp_path / '.local/share/hippocampus/current/VERSION').read_text() == (ROOT / 'VERSION').read_text()
    module = installer()
    monkeypatch.setattr(module.trust, 'verify_with_hooks_list', lambda *args: None)
    monkeypatch.setattr(sys, 'argv', ['install', '--codex-home', str(home), '--codex', 'codex'])
    assert module.main() == 0
    manifest = json.loads((home / 'hippocampus-install.json').read_text())
    assert set(manifest['skill_links']) == set(module.SKILLS)
    assert manifest['version'] == (ROOT / 'VERSION').read_text().strip()
    assert (tmp_path / '.local/share/hippocampus/current/VERSION').read_text() == (ROOT / 'VERSION').read_text()
    link = home / 'skills' / module.SKILLS[0]
    link.unlink()
    link.symlink_to(tmp_path / 'foreign')
    monkeypatch.setattr(sys, 'argv', ['install', '--codex-home', str(home), '--uninstall'])
    assert module.main() == 0
    assert os.readlink(link) == str(tmp_path / 'foreign')


def test_codex_failed_adoption_restores_old_runtime_and_links(tmp_path, monkeypatch):
    monkeypatch.setenv('HOME', str(tmp_path))
    home = tmp_path / '.codex'
    subprocess.run(['bash', str(ROOT / 'install.sh')], env=dict(os.environ, CODEX_HOME=str(home)),
                   check=True, capture_output=True)
    package = tmp_path / '.local/share/hippocampus/current'
    before = os.readlink(package)
    module = installer()
    def fail(*args):
        raise RuntimeError('trust refused')
    monkeypatch.setattr(module.trust, 'verify_with_hooks_list', fail)
    monkeypatch.setattr(sys, 'argv', ['install', '--codex-home', str(home), '--codex', 'codex'])
    import pytest
    with pytest.raises(RuntimeError, match='trust refused'):
        module.main()
    assert os.readlink(package) == before
    assert not (home / 'hooks.json').exists()
    assert not (home / 'hippocampus-install.json').exists()


def test_claude_cutover_and_failure_restore(tmp_path, install_home):
    import pytest
    for fail in (False, True):
        home = tmp_path / str(fail)
        env = install_home(home)
        skills = home / '.claude/skills'
        skills.mkdir(parents=True)
        owned = skills / 'checkpoint'
        owned.symlink_to(home / '.local/share/hippocampus/current/skills/checkpoint')
        foreign = skills / 'pickup'
        foreign.symlink_to(home / 'personal/pickup')
        cli = home / 'claude'
        cli.write_text('#!/bin/sh\nmkdir -p "$HOME/.claude/plugins"\necho changed > "$HOME/.claude/plugins/test"\nexit '+('1' if fail else '0')+'\n')
        cli.chmod(0o755)
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/install-claude.py'), '--claude', str(cli)],
                                env=env, capture_output=True, text=True)
        if fail:
            assert result.returncode != 0
            assert owned.is_symlink()
            # Only installer-owned entries go; this file may be another session's.
            assert (home / '.claude/plugins/test').is_file()
        else:
            assert result.returncode == 0, result.stderr
            assert not owned.is_symlink()
        assert foreign.is_symlink()


def test_codex_uninstall_after_adoption_keeps_claude_release(tmp_path, monkeypatch, install_home):
    install_home(tmp_path)
    home = tmp_path / '.codex'
    subprocess.run(['bash', str(ROOT / 'install.sh')], env=dict(os.environ, CODEX_HOME=str(home)),
                   check=True, capture_output=True)
    module = installer()
    monkeypatch.setattr(module.trust, 'verify_with_hooks_list', lambda *args: None)
    monkeypatch.setattr(sys, 'argv', ['install', '--codex-home', str(home), '--codex', 'codex'])
    module.main()
    monkeypatch.setattr(sys, 'argv', ['install', '--codex-home', str(home), '--uninstall'])
    module.main()
    assert (tmp_path / '.claude/skills/checkpoint/SKILL.md').is_file()


def test_codex_failed_uninstall_restores_files(tmp_path, monkeypatch):
    import pytest
    monkeypatch.setenv('HOME', str(tmp_path))
    home = tmp_path / '.codex'
    module = installer()
    monkeypatch.setattr(module.trust, 'verify_with_hooks_list', lambda *args: None)
    monkeypatch.setattr(sys, 'argv', ['install', '--codex-home', str(home), '--codex', 'codex'])
    module.main()
    before = (home / 'hooks.json').read_bytes()
    original = module.trust.atomic_write
    def fail(path, text):
        if path == home / 'config.toml' and 'trusted_hash' not in text:
            raise OSError('write refused')
        return original(path, text)
    monkeypatch.setattr(module.trust, 'atomic_write', fail)
    monkeypatch.setattr(sys, 'argv', ['install', '--codex-home', str(home), '--uninstall'])
    with pytest.raises(OSError, match='write refused'):
        module.main()
    assert (home / 'hooks.json').read_bytes() == before


def test_claude_failed_update_restores_existing_settings_and_plugin(tmp_path, install_home):
    home = tmp_path
    env = install_home(home)
    config = home / '.claude'
    (config / 'plugins').mkdir(parents=True)
    (config / 'plugins/installed_plugins.json').write_text('previous plugin registry')
    (config / 'settings.json').write_text('{"enabledPlugins":{"other":true}}')
    cli = home / 'claude'
    cli.write_text('#!/bin/sh\necho partial > "$HOME/.claude/settings.json"\nrm "$HOME/.claude/plugins/installed_plugins.json"\nexit 1\n')
    cli.chmod(0o755)
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/install-claude.py'), '--claude', str(cli)],
                            env=env, capture_output=True)
    assert result.returncode != 0
    assert (config / 'plugins/installed_plugins.json').read_text() == 'previous plugin registry'
    assert (config / 'settings.json').read_text() == '{"enabledPlugins":{"other":true}}'


def test_claude_native_cli_cutover_from_checkout_and_release_tree(tmp_path):
    import shutil
    import pytest
    cli = shutil.which('claude')
    if not cli:
        pytest.skip('claude command unavailable')
    source = tmp_path / 'extracted-release'
    shutil.copytree(ROOT, source, ignore=shutil.ignore_patterns('.git', '.build', '__pycache__', '.pytest_cache'))
    for index, tree in enumerate((ROOT, source)):
        home = tmp_path / f'home-{index}'
        links = home / '.claude/skills'
        links.mkdir(parents=True)
        link = links / 'checkpoint'
        link.symlink_to(home / '.local/share/hippocampus/current/skills/checkpoint')
        env = {k: v for k, v in os.environ.items() if not k.startswith(('CLAUDE_', 'CODEX_'))}
        env.update(HOME=str(home), CLAUDE_CODE_ENTRYPOINT='cli')
        for operation in ([], [], ['--uninstall']):
            result = subprocess.run([sys.executable, str(tree / 'scripts/install-claude.py'), '--claude', cli, *operation],
                                    env=env, capture_output=True, text=True, timeout=180)
            assert result.returncode == 0, result.stdout + result.stderr
            assert not link.is_symlink()
            listing = subprocess.run([cli, 'plugin', 'list', '--json'], env=env, capture_output=True, text=True, check=True)
            plugins = [p for p in json.loads(listing.stdout) if p['id'] == 'hippocampus@hippocampus']
            assert len(plugins) == (0 if operation else 1)
            if plugins:
                installed = Path(plugins[0]['installPath'])
                assert {p.name for p in (installed / 'skills').iterdir()} == set(installer().SKILLS)
                hooks = json.loads((installed / 'hooks/hooks.json').read_text())['hooks']
                commands = [h['command'] for groups in hooks.values() for g in groups for h in g['hooks']]
                assert len(commands) == len(set(commands))


def test_codex_install_from_extracted_tree_verifies_native_trust(tmp_path, requires_codex_cli):
    import shutil
    codex = shutil.which('codex')
    source = tmp_path / 'extracted-release'
    shutil.copytree(ROOT, source, ignore=shutil.ignore_patterns('.git', '.build', '__pycache__', '.pytest_cache'))
    home = tmp_path / 'home'
    home.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith(('CLAUDE_', 'CODEX_'))}
    env.update(HOME=str(home), CODEX_HOME=str(home / '.codex'))
    for operation in ([], [], ['--uninstall']):
        result = subprocess.run([sys.executable, str(source / 'scripts/install-codex.py'), '--codex', codex, *operation],
                                env=env, capture_output=True, text=True, timeout=180)
        assert result.returncode == 0, result.stdout + result.stderr
        if not operation:
            manifest = json.loads((home / '.codex/hippocampus-install.json').read_text())
            assert set(manifest['skill_links']) == set(installer().SKILLS)
        else:
            assert not (home / '.codex/hippocampus-install.json').exists()


@pytest.mark.parametrize('operation', ['update', 'failed-update', 'uninstall', 'failed-uninstall'])
def test_codex_runtime_transaction_with_cross_device_home(tmp_path, monkeypatch, operation):
    import errno
    home = tmp_path / 'user-home'
    codex = tmp_path / 'other-device/codex'
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setenv('CODEX_HOME', str(codex))
    module = installer()
    monkeypatch.setattr(module.trust, 'verify_with_hooks_list', lambda *args: None)
    install_args = ['install', '--codex-home', str(codex), '--codex', 'codex']
    monkeypatch.setattr(sys, 'argv', install_args)
    assert module.main() == 0
    package = home / '.local/share/hippocampus/current'
    marker = package / 'previous-runtime-marker'
    marker.write_text('original runtime')
    before = {name: (codex/name).read_bytes() for name in
              ('hooks.json', 'config.toml', 'hippocampus-install.json')}
    links = {p.name: os.readlink(p) for p in (codex/'skills').iterdir()}
    rename = Path.rename
    moves = []

    def cross_device_rename(source, destination):
        destination = Path(destination)
        # Model CODEX_HOME as a mount distinct from the shared runtime's mount.
        if source.is_relative_to(codex) != destination.is_relative_to(codex):
            raise OSError(errno.EXDEV, os.strerror(errno.EXDEV), str(source), str(destination))
        moves.append((source, destination))
        return rename(source, destination)

    monkeypatch.setattr(Path, 'rename', cross_device_rename)
    if operation == 'failed-update':
        def refuse_trust(*args):
            raise RuntimeError('trust refused after runtime replacement')
        monkeypatch.setattr(module.trust, 'verify_with_hooks_list', refuse_trust)
    if operation == 'failed-uninstall':
        unlink = Path.unlink
        def refuse_manifest_removal(path, *args, **kwargs):
            if path == codex/'hippocampus-install.json':
                raise OSError('manifest removal refused after runtime backup')
            return unlink(path, *args, **kwargs)
        monkeypatch.setattr(Path, 'unlink', refuse_manifest_removal)
    if 'uninstall' in operation:
        monkeypatch.setattr(sys, 'argv', install_args+['--uninstall'])
    if operation.startswith('failed-'):
        with pytest.raises((OSError, RuntimeError), match='refused'):
            module.main()
        assert marker.read_text() == 'original runtime'
        assert {name: (codex/name).read_bytes() for name in before} == before
        assert {p.name: os.readlink(p) for p in (codex/'skills').iterdir()} == links
    else:
        assert module.main() == 0
        if operation == 'update':
            assert (package/'scripts/codex-hook.py').is_file()
            assert not marker.exists()
        else:
            assert not package.exists()
            assert not (codex/'hippocampus-install.json').exists()
            assert not list((codex/'skills').iterdir())
    assert moves
    assert all(source.parent == destination.parent == package.parent for source, destination in moves)
    assert not (package.parent/'hippocampus-install-backup').exists()


@pytest.mark.parametrize('damage', ['modified', 'deleted', 'other-content'])
def test_installed_version_integrity_and_narrow_repair(tmp_path, damage):
    home = tmp_path / 'home'
    knowledge = home / 'knowledge'
    for name in ('raw', 'wiki', 'output', 'docs'):
        (knowledge / name).mkdir(parents=True)
    for name in ('wiki/hot.md', 'docs/log.md', 'docs/DECISIONS.md'):
        (knowledge / name).touch()
    profile = home / '.config/hippocampus/profile.md'
    profile.parent.mkdir(parents=True)
    profile.write_text((ROOT / 'profiles/karpathy-wiki.example.md').read_text().replace(
        '/absolute/path/to/knowledge', str(knowledge)))
    env = dict(os.environ, HOME=str(home), CODEX_HOME=str(home / '.codex'))
    command = ['bash', str(ROOT / 'install.sh')]
    def run(*args):
        return subprocess.run(command + list(args), env=env, capture_output=True, text=True)
    assert run().returncode == 0
    assert run('--verify').returncode == 0
    release = home / '.local/share/hippocampus/current'
    version = release / 'VERSION'
    manifest = (release / 'manifest').read_bytes()
    if damage == 'deleted':
        version.unlink()
    else:
        version.write_text(version.read_text() + 'tampered\n')
    if damage == 'other-content':
        skill = release / 'skills/research-topic/SKILL.md'
        skill.write_text(skill.read_text() + '\ntampered\n')
    verification = run('--verify')
    assert verification.returncode != 0, 'tampered VERSION passed verification'
    assert 'current manifest hash' in verification.stderr
    repair = run()
    if damage == 'other-content':
        assert repair.returncode != 0
        assert 'tampered' in version.read_text()
    else:
        assert repair.returncode == 0, repair.stdout + repair.stderr
        assert version.read_bytes() == (ROOT / 'VERSION').read_bytes()
        assert (release / 'manifest').read_bytes() == manifest
        assert run('--verify').returncode == 0
