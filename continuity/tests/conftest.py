"""Keep continuity tests independent of the caller's live handoff ledger."""
import os

import pytest


@pytest.fixture(autouse=True)
def isolate_handoff_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("HANDOFF_LEDGER_DIR", str(tmp_path / "handoff-ledger"))


@pytest.fixture(autouse=True)
def isolate_continuity_config(tmp_path, monkeypatch):
    """The live ~/.config/continuity/config.json names where handoffs are stored (#1572)."""
    monkeypatch.setenv("CONTINUITY_CONFIG", str(tmp_path / "continuity-config.json"))


@pytest.fixture(autouse=True)
def isolate_user_profile(tmp_path, monkeypatch):
    """Record reads start unbound; tests may opt into their own profile."""
    monkeypatch.delenv("CHECKLIST_USER_PROFILE", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))


@pytest.fixture(autouse=True)
def isolate_codex_identity(monkeypatch):
    """No test takes its invoking worker's Codex session as an input."""
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    monkeypatch.delenv("CONTINUITY_HARNESS", raising=False)


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
