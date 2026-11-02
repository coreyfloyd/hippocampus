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


def run(env, *args, check=True):
    result = subprocess.run(list(map(str, args)), env=env, capture_output=True, text=True, timeout=180)
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


@pytest.mark.parametrize('damage', ['plugin-root', 'missing-link', 'retargeted-link', 'manifest', 'no-clients'])
def test_verify_rejects_broken_release(installed, damage):
    home, env, current = installed
    run(env, sys.executable, current / 'scripts/install-claude.py')
    if damage == 'plugin-root':
        registry = home / '.claude/plugins/installed_plugins.json'
        value = json.loads(registry.read_text())
        value['plugins']['hippocampus@hippocampus'][0]['installPath'] = str(home / 'other')
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
