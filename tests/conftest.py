"""Keep hippocampus tests independent of the caller's live handoff ledger."""
import os
import json
import sys
import shutil
from pathlib import Path

import pytest


# Capture only path identities, never read the caller's state or backups.
_STATE_GUARD_DIR = Path(__file__).parent / "state_guard"
sys.path.insert(0, str(_STATE_GUARD_DIR))
from state_write_guard import install_write_guard

_PROTECTED_STATE = json.loads(os.environ["HIPPOCAMPUS_TEST_PROTECTED_STATE"]) if os.environ.get(
    "HIPPOCAMPUS_TEST_PROTECTED_STATE") else [str(Path.home() / path) for path in (
        ".local/state/hippocampus", ".config/hippocampus", ".claude", ".codex")]
_PROTECTED_STATE += [os.environ[key] for key in (
    "HANDOFF_STATE_DIR", "HANDOFF_LEDGER_DIR", "HANDOFF_TIMER_DIR", "HANDOFF_COMPACT_STATE_DIR",
    "CHECKLIST_STATE_DIR", "HIPPOCAMPUS_CONFIG", "CODEX_HOME", "CLAUDE_CONFIG_DIR",
    "HANDOFF_PATH", "HANDOFF_GUARD_OVERRIDE_PATH", "HANDOFF_GUARD_OVERRIDE_LEDGER")
    if os.environ.get(key) and not os.environ.get("HIPPOCAMPUS_TEST_PROTECTED_STATE")]
_PROTECTED_STATE = [str(Path(root).expanduser().resolve()) for root in _PROTECTED_STATE]
install_write_guard(_PROTECTED_STATE)


@pytest.fixture(autouse=True)
def isolate_all_state(tmp_path, tmp_path_factory, monkeypatch):
    """Subprocesses inherit isolation; omitted overrides trip a fake-home guard.

    Never inspect the caller's state. The fake home models its default layout,
    with sentinels that must survive every test and all its fixture teardowns.
    Explicit state/config/tool paths live outside those guarded defaults.
    """
    monkeypatch.setenv("HIPPOCAMPUS_TEST_PROTECTED_STATE", json.dumps(_PROTECTED_STATE))
    monkeypatch.setenv("PYTHONPATH", str(_STATE_GUARD_DIR) + os.pathsep + os.environ.get("PYTHONPATH", ""))
    home = tmp_path_factory.mktemp("isolated-home")
    roots = [home / name for name in (".local", ".config", ".cache", ".claude", ".codex")]
    for root in roots:
        root.mkdir(parents=True)
        (root / "sentinel").write_text("default state must remain untouched")

    def contents():
        return {str(path.relative_to(home)): ("symlink:" + os.readlink(path) if path.is_symlink() else
                    "missing" if not path.exists() else "directory" if path.is_dir() else path.read_bytes())
                for root in roots for path in [root, *root.rglob("*")]}

    before = contents()
    surfaces = {
        "HOME": home,
        "XDG_CONFIG_HOME": tmp_path / "xdg-config",
        "XDG_STATE_HOME": tmp_path / "xdg-state",
        "XDG_CACHE_HOME": tmp_path / "xdg-cache",
        "XDG_DATA_HOME": tmp_path / "xdg-data",
        "CODEX_HOME": tmp_path / "codex-home",
        "CLAUDE_CONFIG_DIR": tmp_path / "claude-config",
        "HIPPOCAMPUS_CONFIG": tmp_path / "hippocampus-config.json",
        "HANDOFF_STATE_DIR": tmp_path / "handoffs",
        "HANDOFF_LEDGER_DIR": tmp_path / "handoff-ledger",
        "HANDOFF_TIMER_DIR": tmp_path / "timed-checkpoints",
        "HANDOFF_COMPACT_STATE_DIR": tmp_path / "compact-state",
        "CHECKLIST_STATE_DIR": tmp_path / "checklist-state",
    }
    for key, path in surfaces.items():
        monkeypatch.setenv(key, str(path))
    for key in ("HANDOFF_PATH", "HANDOFF_GUARD_OVERRIDE_PATH", "HANDOFF_GUARD_OVERRIDE_LEDGER",
                "CHECKLIST_USER_PROFILE"):
        monkeypatch.delenv(key, raising=False)
    yield
    assert contents() == before, "unisolated state write: a fixture used a default home path; set its override"


@pytest.fixture
def codex_cli():
    """Resolve the installed CLI before timer isolation adds its queue-only stub."""
    return shutil.which('codex')


@pytest.fixture
def requires_codex_cli(codex_cli):
    if not codex_cli:
        if os.environ.get('CI'):
            pytest.fail('codex command required in CI', pytrace=False)
        pytest.skip('codex command unavailable')


@pytest.fixture(autouse=True)
def isolate_session_identity(monkeypatch):
    """No test takes its invoking worker's session as a pickup successor."""
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    monkeypatch.delenv("HIPPOCAMPUS_HARNESS", raising=False)


@pytest.fixture(autouse=True)
def isolate_git_configuration(monkeypatch):
    """Fixture repositories never use the caller's git identity or configuration."""
    for key in os.environ:
        if key.startswith("GIT_"):
            monkeypatch.delenv(key)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "Test")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "test@example.com")


@pytest.fixture(autouse=True)
def isolate_timed_checkpoints(tmp_path, tmp_path_factory, monkeypatch, codex_cli):
    """Test timers cannot survive as future queues into the caller's sessions."""
    directory = tmp_path / 'timed-checkpoints'
    monkeypatch.setenv('HANDOFF_TIMER_DIR', str(directory))
    if not codex_cli:
        # Timer scheduling only needs queue. Keep native verification unavailable,
        # and put the stub outside tmp_path so fixture git repositories stay clean.
        commands = tmp_path_factory.mktemp('codex-timer-bin')
        stub = commands / 'codex'
        stub.write_text('#!/bin/sh\n[ "$1" = queue ] && exit 0\n'
                        'echo "codex timer stub only supports queue" >&2\nexit 1\n')
        stub.chmod(0o755)
        monkeypatch.setenv('PATH', str(commands), prepend=os.pathsep)
    yield
    # Workers observe removal under their schedule lock and then exit.
    for path in directory.glob('*.pending.json'):
        path.unlink(missing_ok=True)
