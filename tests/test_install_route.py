"""A signed archive remains usable after the release bootstrap deletes extraction."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
STUB = ROOT / 'tests/fixtures/install-route/claude'


def run(env, *args, check=True, cwd=None):
    result = subprocess.run(list(map(str, args)), env=env, cwd=cwd, capture_output=True, text=True, timeout=180)
    if check:
        assert result.returncode == 0, result.stdout + result.stderr
    return result


@pytest.fixture(scope='module')
def signed():
    # Unix-domain socket paths used by gpg-agent must fit on macOS too.
    temporary = tempfile.TemporaryDirectory(prefix='hc-sign-', dir='/tmp')
    directory = Path(temporary.name)
    env = dict(os.environ, GNUPGHOME=str(directory / 'gnupg'))
    Path(env['GNUPGHOME']).mkdir(mode=0o700)
    run(env, 'gpg', '--batch', '--passphrase', '', '--quick-generate-key',
        'Installer test <test@example.invalid>', 'ed25519', 'sign', '0')
    keys = run(env, 'gpg', '--batch', '--with-colons', '--list-secret-keys').stdout
    fingerprint = next(row.split(':')[9] for row in keys.splitlines() if row.startswith('fpr:'))
    key = directory / 'public.asc'
    key.write_text(run(env, 'gpg', '--armor', '--export', fingerprint).stdout)
    archive = directory / 'hippocampus-test.tar.gz'
    files = run(env, 'git', '-C', ROOT, 'ls-files', '-z', '--cached', '--others', '--exclude-standard').stdout.split('\0')
    with tarfile.open(archive, 'w:gz') as tar:
        for name in filter(None, files):
            tar.add(ROOT / name, arcname='hippocampus/' + name, recursive=False)
    checksum = Path(str(archive) + '.sha256')
    checksum.write_text(run(env, 'shasum', '-a', '256', archive).stdout)
    run(env, 'gpg', '--batch', '--yes', '--armor', '--output', str(archive) + '.asc', '--detach-sign', checksum)
    yield archive, key, fingerprint
    run(env, 'gpgconf', '--kill', 'gpg-agent')
    temporary.cleanup()


@pytest.fixture
def installed(tmp_path, signed, request):
    if getattr(request, 'param', False):
        real_home = tmp_path / 'real-home'
        real_home.mkdir()
        alias = tmp_path / 'home-alias'
        alias.symlink_to(real_home, target_is_directory=True)
        tmp_path = alias
    env = {k: v for k, v in os.environ.items() if not k.startswith(('CLAUDE_', 'CODEX_', 'XDG_'))}
    env.update(HOME=str(tmp_path), CODEX_HOME=str(tmp_path / '.codex'),
               XDG_CONFIG_HOME=str(tmp_path / '.config'), XDG_DATA_HOME=str(tmp_path / '.local/share'),
               PATH=str(STUB.parent) + os.pathsep + os.environ['PATH'])
    run(env, 'bash', ROOT / 'scripts/install-release.sh', *signed)
    knowledge = tmp_path / 'knowledge'
    for folder in ('raw', 'wiki', 'output', 'docs'):
        (knowledge / folder).mkdir(parents=True)
    for name in ('wiki/hot.md', 'docs/log.md', 'docs/DECISIONS.md'):
        (knowledge / name).touch()
    profile = tmp_path / '.config/hippocampus/profile.md'
    profile.write_text((ROOT / 'profiles/karpathy-wiki.example.md').read_text().replace(
        '/absolute/path/to/knowledge', str(knowledge)))
    current = tmp_path / '.local/share/hippocampus/current'
    return tmp_path, env, current


@pytest.mark.parametrize('route', ['plain', 'plugin', 'codex', 'both'])
def test_signed_release_tool_routes(installed, route):
    home, env, current = installed
    if route in ('plugin', 'both'):
        run(env, sys.executable, current / 'scripts/install-claude.py')
        assert not list((home / '.claude/skills').iterdir())
    if route == 'plugin':
        shutil.rmtree(home / '.codex/skills')
    if route == 'codex':
        shutil.rmtree(home / '.claude/skills')
    if route in ('codex', 'both'):
        for _ in range(2):
            run(env, sys.executable, current / 'scripts/install-codex.py')
            assert current.is_symlink()
    run(env, 'bash', current / 'install.sh', '--verify')
    if route == 'both':
        # Removing Codex registrations must not replace Claude's runtime.
        run(env, sys.executable, current / 'scripts/install-codex.py', '--uninstall')
        assert current.is_symlink()
        run(env, 'bash', current / 'install.sh', '--verify')


@pytest.mark.parametrize('damage', [
    'plugin-root', 'cache-only', 'source-release', 'plugin-version',
    'missing-link', 'retargeted-link', 'manifest', 'no-clients'])
def test_verify_rejects_broken_release(installed, damage):
    home, env, current = installed
    run(env, sys.executable, current / 'scripts/install-claude.py')
    if damage in ('plugin-root', 'cache-only', 'source-release', 'plugin-version'):
        registry = home / '.claude/plugins/installed_plugins.json'
        value = json.loads(registry.read_text())
        entry = value['plugins']['hippocampus@hippocampus'][0]
        if damage == 'plugin-version':
            entry['version'] = '0.0.0'
        else:
            sources = home / '.claude/plugins/known_marketplaces.json'
            if damage in ('plugin-root', 'cache-only'):
                # Without source metadata, only a direct release root is valid.
                sources.unlink()
                if damage == 'plugin-root':
                    entry['installPath'] = str(home / 'other')
            else:
                other = home / '.local/share/hippocampus/releases/other'
                other.mkdir()
                value_sources = json.loads(sources.read_text())
                value_sources['hippocampus']['source']['path'] = str(other)
                value_sources['hippocampus']['installLocation'] = str(other)
                sources.write_text(json.dumps(value_sources))
        registry.write_text(json.dumps(value))
    elif damage in ('missing-link', 'retargeted-link'):
        link = home / '.codex/skills/checkpoint'
        link.unlink()
        if damage == 'retargeted-link':
            link.symlink_to(home / 'other')
    elif damage == 'manifest':
        (current / 'manifest').write_text('tampered\n')
    else:
        (home / '.claude/plugins/installed_plugins.json').unlink()
        shutil.rmtree(home / '.codex/skills')
    assert run(env, 'bash', ROOT / 'install.sh', '--verify', check=False).returncode != 0


def test_failed_codex_adoption_keeps_shared_runtime(installed):
    home, env, current = installed
    before = os.readlink(current)
    failing = home / 'codex-refuse'
    failing.write_text('#!/bin/sh\nexit 1\n')
    failing.chmod(0o755)
    result = run(env, sys.executable, current / 'scripts/install-codex.py',
                 '--codex', failing, check=False)
    assert result.returncode != 0
    assert os.readlink(current) == before
    assert not (home / '.codex/hippocampus-install.json').exists()
    assert not (home / '.codex/hooks.json').exists()
    run(env, 'bash', current / 'install.sh', '--verify')


def test_plugin_verification_preserves_foreign_plain_skills(installed):
    home, env, current = installed
    foreign = home / '.claude/skills/checkpoint'
    foreign.unlink()
    foreign.symlink_to(home / 'personal/checkpoint')
    run(env, sys.executable, current / 'scripts/install-claude.py')
    assert os.readlink(foreign) == str(home / 'personal/checkpoint')
    run(env, 'bash', current / 'install.sh', '--verify')


def test_shared_codex_update_refuses_a_different_source_tree(installed):
    home, env, current = installed
    run(env, sys.executable, current / 'scripts/install-codex.py')
    before = (home / '.codex/hippocampus-install.json').read_bytes()
    result = run(env, sys.executable, ROOT / 'scripts/install-codex.py', check=False)
    assert result.returncode != 0
    assert 'run the helper from current' in result.stderr
    assert (home / '.codex/hippocampus-install.json').read_bytes() == before
    run(env, 'bash', current / 'install.sh', '--verify')


@pytest.mark.parametrize('installed', [True], indirect=True)
def test_signed_route_accepts_a_symlinked_home(installed):
    _, env, current = installed
    run(env, sys.executable, current / 'scripts/install-codex.py')
    assert current.is_symlink()
    run(env, 'bash', current / 'install.sh', '--verify')


@pytest.mark.parametrize('user,project,local,scope,enabled', [
    (False, None, None, 'user', False),
    (None, None, None, 'user', False),
    ('missing-file', None, None, 'user', False),
    (True, None, None, 'user', True),
    (False, True, None, 'user', True),
    (True, False, None, 'user', False),
    (True, True, False, 'user', False),
    (False, False, True, 'user', True),
    (None, True, None, 'project', True),
    (None, None, None, 'project', False),
    (None, True, False, 'local', False),
    (None, None, True, 'local', True),
    (True, None, None, 'other-project', False),
])
def test_verify_uses_effective_plugin_enablement(installed, user, project, local, scope, enabled):
    home, env, current = installed
    work = home / 'project'
    work.mkdir()
    run(env, 'git', 'init', '-q', work)
    run(env, sys.executable, current / 'scripts/install-claude.py')
    shutil.rmtree(home / '.codex/skills')
    registry = home / '.claude/plugins/installed_plugins.json'
    value = json.loads(registry.read_text())
    entry = value['plugins']['hippocampus@hippocampus'][0]
    entry['scope'] = 'project' if scope == 'other-project' else scope
    if scope != 'user':
        entry['projectPath'] = str(home / 'elsewhere' if scope == 'other-project' else work)
    registry.write_text(json.dumps(value))
    for path, state in [(home / '.claude/settings.json', user),
                        (work / '.claude/settings.json', project),
                        (work / '.claude/settings.local.json', local)]:
        path.parent.mkdir(parents=True, exist_ok=True)
        if state == 'missing-file':
            path.unlink()
        else:
            path.write_text(json.dumps({'enabledPlugins': {'hippocampus@hippocampus': state}}
                                       if state is not None else {}))
    result = run(env, 'bash', current / 'install.sh', '--verify', check=False, cwd=work)
    assert (result.returncode == 0) is enabled, result.stdout + result.stderr


@pytest.mark.parametrize('fallback', ['plain', 'codex'])
def test_disabled_plugin_falls_back_to_available_client(installed, fallback):
    home, env, current = installed
    if fallback == 'plain':
        # Register without the cutover so installer-owned plain links survive.
        run(env, 'claude', 'plugin', 'install', 'hippocampus', '--marketplace', current)
        shutil.rmtree(home / '.codex/skills')
    else:
        run(env, sys.executable, current / 'scripts/install-claude.py')
    settings = home / '.claude/settings.json'
    settings.write_text(json.dumps({'enabledPlugins': {'hippocampus@hippocampus': False}}))
    # A disabled registration is absent, including its stale install root.
    registry = home / '.claude/plugins/installed_plugins.json'
    value = json.loads(registry.read_text())
    value['plugins']['hippocampus@hippocampus'][0]['installPath'] = str(home / 'stale')
    registry.write_text(json.dumps(value))
    (home / '.claude/plugins/known_marketplaces.json').unlink()
    run(env, 'bash', current / 'install.sh', '--verify')


def test_legacy_direct_folder_registration(installed):
    home, env, current = installed
    run(env, sys.executable, current / 'scripts/install-claude.py')
    registry = home / '.claude/plugins/installed_plugins.json'
    value = json.loads(registry.read_text())
    value['plugins']['hippocampus@hippocampus'][0] = {
        'installPath': str(current), 'scope': 'user'}
    registry.write_text(json.dumps(value))
    (home / '.claude/plugins/known_marketplaces.json').unlink()
    run(env, 'bash', current / 'install.sh', '--verify')


@pytest.mark.skipif(not shutil.which('claude'), reason='the claude command is not installed')
def test_real_claude_signed_release_verification(installed):
    home, env, current = installed
    # Remove the offline stub from PATH; all client state remains in this home.
    env['PATH'] = os.environ['PATH']
    env['CLAUDE_CONFIG_DIR'] = str(home / '.claude')
    run(env, sys.executable, current / 'scripts/install-claude.py', cwd=home)
    shutil.rmtree(home / '.codex/skills')
    run(env, 'bash', current / 'install.sh', '--verify', cwd=home)
    # The cached plugin survives, but its source is no longer the active release.
    marketplaces = home / '.claude/plugins/known_marketplaces.json'
    value = json.loads(marketplaces.read_text())
    other = home / '.local/share/hippocampus/releases/other'
    shutil.copytree(current.resolve(), other)
    value['hippocampus']['source']['path'] = str(other)
    value['hippocampus']['installLocation'] = str(other)
    marketplaces.write_text(json.dumps(value))
    result = run(env, 'bash', current / 'install.sh', '--verify', check=False, cwd=home)
    assert result.returncode != 0
    assert 'claude plugin root is not the current release' in result.stderr
