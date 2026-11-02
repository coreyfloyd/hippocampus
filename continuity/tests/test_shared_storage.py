"""Shared storage: one location for both tools, outside either tool's own data area.

A tool's data area (``~/.claude``, ``~/.codex``, a plugin's data directory) is
removed or rewritten when that tool's adapter is uninstalled. Handoffs, their
ledger, and the pre-compaction backups must survive that, and a handoff written
under one tool must be found from the other.
"""
import importlib.util
import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE = os.path.join(ROOT, "scripts", "lib", "handoff.py")
TOOL_AREAS = (".claude", ".codex", ".config/claude", ".config/codex")


def load_module():
    spec = importlib.util.spec_from_file_location("handoff", MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def clean_home(tmp_path, monkeypatch):
    for key in ("HANDOFF_STATE_DIR", "HANDOFF_LEDGER_DIR", "HANDOFF_COMPACT_STATE_DIR", "XDG_CONFIG_HOME",
                "CLAUDE_SESSION_ID", "CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CONTINUITY_CONFIG", str(tmp_path / "absent.json"))
    return tmp_path


def under(path, directory):
    path, directory = os.path.realpath(path), os.path.realpath(directory)
    return path == directory or path.startswith(directory + os.sep)


def test_defaults_sit_beside_each_other_outside_every_tool_area(clean_home):
    handoff = load_module()
    locations = {
        "handoffs": handoff.state_dir(),
        "ledger": os.path.dirname(handoff.ledger_path("s1")),
        "compact backups": os.path.expanduser(handoff.COMPACT_STATE_DIR),
    }
    for name, location in locations.items():
        for area in TOOL_AREAS:
            assert not under(location, clean_home / area), (name, location)
        assert under(location, clean_home / ".local" / "state" / "continuity"), (name, location)


def test_one_configured_value_moves_handoffs_and_ledger_together(clean_home, monkeypatch):
    config = clean_home / "config.json"
    config.write_text(json.dumps({"handoff_dir": str(clean_home / "shared" / "handoffs")}))
    monkeypatch.setenv("CONTINUITY_CONFIG", str(config))
    handoff = load_module()
    assert handoff.state_dir() == str(clean_home / "shared" / "handoffs")
    assert os.path.dirname(handoff.ledger_path("s1")) == str(clean_home / "shared")


def test_pre_compaction_backups_follow_the_default_outside_the_tool_area(clean_home):
    result = subprocess.run([sys.executable, MODULE, "pre-compact"], input='{"session_id": "s1"}', text=True,
                            capture_output=True, env=dict(os.environ))
    assert result.returncode == 0, result.stderr
    backups = list((clean_home / ".local" / "state" / "continuity" / "compact-state").glob("pre-compact-*.json"))
    assert len(backups) == 1
    assert not (clean_home / ".claude").exists()


@pytest.mark.parametrize("writer, reader", [("CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID"),
                                            ("CODEX_THREAD_ID", "CLAUDE_CODE_SESSION_ID")])
def test_a_handoff_written_under_one_tool_is_found_from_the_other(clean_home, tmp_path, writer, reader):
    work = tmp_path / "work"
    work.mkdir()
    subprocess.run(["git", "init", "-q", str(work)], check=True)
    payload = {"resume": {"headline": "left off here", "next_action": "carry on", "open_loops": []},
               "spawned_processes": []}
    write = subprocess.run([sys.executable, MODULE, "checkpoint", "--cwd", str(work), "--session-id", "written-session"],
                           input=json.dumps(payload), text=True, capture_output=True, env=dict(os.environ, **{writer: "written-session"}))
    assert write.returncode == 0, write.stdout + write.stderr
    handoff = load_module()
    files = sorted(os.listdir(handoff.state_dir()))
    assert len(files) == 1
    # The reading tool lists the same directory: the location does not depend on which tool asks.
    state = subprocess.run([sys.executable, MODULE, "state-dir"], text=True, capture_output=True,
                           env=dict(os.environ, **{reader: "reading-session"}))
    assert state.stdout.strip() == handoff.state_dir()
    count = subprocess.run([sys.executable, MODULE, "count", str(work)], text=True, capture_output=True,
                           env=dict(os.environ, **{reader: "reading-session"}))
    assert count.stdout.strip() == "1"
