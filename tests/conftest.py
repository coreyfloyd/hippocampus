"""Keep hippocampus tests independent of the caller's live handoff ledger."""
import os
import shutil

import pytest


@pytest.fixture
def requires_codex_cli():
    if not shutil.which('codex'):
        if os.environ.get('CI'):
            pytest.fail('codex command required in CI', pytrace=False)
        pytest.skip('codex command unavailable')


@pytest.fixture(autouse=True)
def isolate_handoff_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("HANDOFF_LEDGER_DIR", str(tmp_path / "handoff-ledger"))


@pytest.fixture(autouse=True)
def isolate_hippocampus_config(tmp_path, monkeypatch):
    """The live ~/.config/hippocampus/config.json names where handoffs are stored (#1572)."""
    monkeypatch.setenv("HIPPOCAMPUS_CONFIG", str(tmp_path / "hippocampus-config.json"))


@pytest.fixture(autouse=True)
def isolate_user_profile(tmp_path, monkeypatch):
    """Record reads start unbound; tests may opt into their own profile."""
    monkeypatch.delenv("CHECKLIST_USER_PROFILE", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))


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
def isolate_timed_checkpoints(tmp_path, monkeypatch):
    """Test timers cannot survive as future queues into the caller's sessions."""
    directory = tmp_path / 'timed-checkpoints'
    monkeypatch.setenv('HANDOFF_TIMER_DIR', str(directory))
    yield
    # Workers observe removal under their schedule lock and then exit.
    for path in directory.glob('*.pending.json'):
        path.unlink(missing_ok=True)
