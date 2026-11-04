"""Standing state: one never-consumed working set per named agent.

Every probe goes through the module's command line, the entry point a session,
a checkpoint, and a scheduled run call, and asserts what they see: the printed
state, the refusal, or the exit status.
"""
import json
import os
import subprocess
import sys

import pytest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE = os.path.join(ROOT, "scripts", "lib", "standing.py")
RESTORE = os.path.join(ROOT, "scripts", "post-compact-restore.sh")
CODEX_HOOK = os.path.join(ROOT, "scripts", "codex-hook.py")
STAMP = "2026-11-04T08:00:00Z"


@pytest.fixture
def env(tmp_path):
    base = {key: value for key, value in os.environ.items()
            if not key.startswith(("CLAUDE", "CODEX", "HANDOFF", "HIPPOCAMPUS", "STANDING"))}
    base.update(HOME=str(tmp_path), STANDING_STATE_DIR=str(tmp_path / "standing"),
                HANDOFF_STATE_DIR=str(tmp_path / "handoffs"), HANDOFF_LEDGER_DIR=str(tmp_path / "ledger"),
                HIPPOCAMPUS_CONFIG=str(tmp_path / "config.json"))
    return base


def run(env, *args, payload=None, **extra):
    return subprocess.run([sys.executable, MODULE, *args], text=True, capture_output=True,
                          input=json.dumps(payload) if payload is not None else "",
                          env=dict(env, **extra))


def first_write():
    return {
        "resume": {
            "headline": "Watching the release train",
            "next_action": "Brief the owner when the build lands",
            "open_loops": [{"type": "commitment", "context": "Send the weekly digest",
                            "disposition": "file as a ticket", "session_id": "s1",
                            "produced_at": STAMP}],
        },
        "standing": {
            "watching": [{"context": "Nightly build status", "since": STAMP}],
            "waiting_on": [{"who": "release owner", "context": "Approval for the tag"}],
            "proposed_briefings": [{"context": "Monday status brief"}],
            "timers": [{"when": "2026-11-05T09:00:00Z", "reason": "Re-check the build after the retry"}],
        },
    }


def test_write_then_read_shows_every_standing_field(env, tmp_path):
    written = run(env, "write", "--agent", "aide", "--trigger", "checkpoint",
                  "--session-id", "s1", "--cwd", str(tmp_path), payload=first_write())
    assert written.returncode == 0, written.stderr
    assert "Next action: Brief the owner when the build lands" in written.stdout
    shown = run(env, "read", "--agent", "aide")
    assert shown.returncode == 0
    assert "STANDING STATE" in shown.stdout and "agent aide" in shown.stdout
    for text in ("Nightly build status", "release owner", "Monday status brief",
                 "Re-check the build after the retry", "Send the weekly digest"):
        assert text in shown.stdout
    assert (tmp_path / "standing" / "aide.json").is_file()


def test_reading_never_consumes_the_state(env, tmp_path):
    run(env, "write", "--agent", "aide", "--session-id", "s1", "--cwd", str(tmp_path), payload=first_write())
    first = run(env, "read", "--agent", "aide", "--json").stdout
    second = run(env, "read", "--agent", "aide", "--json").stdout
    assert first == second and json.loads(first)["kind"] == "standing"


def test_a_scheduled_run_end_keeps_fields_it_did_not_supply(env, tmp_path):
    run(env, "write", "--agent", "aide", "--session-id", "s1", "--cwd", str(tmp_path), payload=first_write())
    update = {"resume": {"next_action": "Wait for the retry"},
              "standing": {"timers": []}}
    result = run(env, "write", "--trigger", "run-end", "--session-id", "run-7", "--cwd", str(tmp_path),
                 payload=update, HIPPOCAMPUS_AGENT="aide", CLAUDE_CODE_ENTRYPOINT="sdk-cli")
    assert result.returncode == 0, result.stderr
    state = json.loads(run(env, "read", "--agent", "aide", "--json").stdout)
    assert state["trigger"] == "run-end" and state["writer"]["session_id"] == "run-7"
    assert state["resume"]["headline"] == "Watching the release train"
    assert state["resume"]["next_action"] == "Wait for the retry"
    assert state["standing"]["timers"] == []
    assert state["standing"]["waiting_on"][0]["who"] == "release owner"
    assert len(state["resume"]["open_loops"]) == 1


def test_promoted_items_leave_open_loops_and_standing_fields_stay(env, tmp_path):
    run(env, "write", "--agent", "aide", "--session-id", "s1", "--cwd", str(tmp_path), payload=first_write())
    loops = json.loads(run(env, "read", "--agent", "aide", "--json").stdout)["resume"]["open_loops"]
    filed = [dict(loops[0], recorded=True)]
    new_item = {"type": "decision", "context": "Ship on Friday", "disposition": "comment on the ticket",
                "session_id": "s2", "produced_at": STAMP, "author": "owner", "location": "chat"}
    result = run(env, "write", "--agent", "aide", "--trigger", "stop", "--session-id", "s2",
                 "--cwd", str(tmp_path),
                 payload={"resume": {"open_loops": filed}, "session_items": [new_item]})
    assert result.returncode == 0, result.stderr
    state = json.loads(run(env, "read", "--agent", "aide", "--json").stdout)
    assert [loop["context"] for loop in state["resume"]["open_loops"]] == ["Ship on Friday"]
    assert state["standing"]["watching"][0]["context"] == "Nightly build status"


def test_an_invalid_write_is_refused_and_leaves_the_state_unchanged(env, tmp_path):
    run(env, "write", "--agent", "aide", "--session-id", "s1", "--cwd", str(tmp_path), payload=first_write())
    before = (tmp_path / "standing" / "aide.json").read_text()
    bad = {"standing": {"timers": [{"when": "tomorrow"}]},
           "session_items": [{"type": "decision", "context": "x", "disposition": "ask",
                              "session_id": "s2", "produced_at": STAMP}]}
    result = run(env, "write", "--agent", "aide", "--session-id", "s2", "--cwd", str(tmp_path), payload=bad)
    assert result.returncode == 1
    assert "refused" in result.stderr
    assert "standing.timers[0].reason must be a non-empty string" in result.stderr
    assert "open_loops[1].author is required for a decision" in result.stderr
    assert (tmp_path / "standing" / "aide.json").read_text() == before


def test_banned_and_unknown_fields_fail_lint(env, tmp_path):
    payload = dict(first_write(), tickets=["#1"])
    payload["standing"] = dict(payload["standing"], inbox=[])
    result = run(env, "write", "--agent", "aide", "--session-id", "s1", "--cwd", str(tmp_path), payload=payload)
    assert result.returncode == 1
    assert "banned top-level key 'tickets'" in result.stderr
    assert "standing.inbox is not a standing field" in result.stderr


def test_agent_name_is_required_and_bounded(env, tmp_path):
    missing = run(env, "read")
    assert missing.returncode == 2 and "agent name" in missing.stderr
    escaping = run(env, "read", "--agent", "../etc")
    assert escaping.returncode == 2


def test_absent_state_reads_cleanly(env):
    result = run(env, "read", "--agent", "aide")
    assert result.returncode == 0 and "No standing state for agent aide yet" in result.stdout


def test_configured_standing_dir_places_the_state(env, tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"standing_dir": str(tmp_path / "agent-home")}))
    without_override = {k: v for k, v in env.items() if k != "STANDING_STATE_DIR"}
    result = run(without_override, "path", "--agent", "aide")
    assert result.stdout.strip() == str(tmp_path / "agent-home" / "aide.json")


def test_session_start_serves_the_state_to_headless_runs_in_both_tools(env, tmp_path):
    run(env, "write", "--agent", "aide", "--session-id", "s1", "--cwd", str(tmp_path), payload=first_write())
    payload = json.dumps({"session_id": "run-8", "cwd": str(tmp_path), "source": "startup"})
    claude = subprocess.run(["bash", RESTORE], input=payload, text=True, capture_output=True,
                            env=dict(env, HIPPOCAMPUS_AGENT="aide", CLAUDE_CODE_ENTRYPOINT="sdk-cli"))
    codex = subprocess.run([sys.executable, CODEX_HOOK, "post-compact"], input=payload, text=True,
                           capture_output=True, env=dict(env, HIPPOCAMPUS_AGENT="aide",
                                                         CODEX_HOME=str(tmp_path / "codex")))
    for result in (claude, codex):
        assert result.returncode == 0, result.stderr
        context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        assert "STANDING STATE" in context and "Nightly build status" in context


def test_session_start_without_an_agent_adds_nothing(env, tmp_path):
    payload = json.dumps({"session_id": "s1", "cwd": str(tmp_path), "source": "startup"})
    result = subprocess.run(["bash", RESTORE], input=payload, text=True, capture_output=True, env=env)
    assert result.returncode == 0 and result.stdout == ""
