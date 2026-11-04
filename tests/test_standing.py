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


def test_default_directory_and_environment_override(env, tmp_path):
    default_env = {key: value for key, value in env.items() if key != "STANDING_STATE_DIR"}
    result = run(default_env, "dir")
    assert result.returncode == 0
    assert result.stdout.strip() == str(tmp_path / ".local/state/hippocampus/standing")
    (tmp_path / "config.json").write_text(json.dumps({"standing_dir": "~/configured"}))
    assert run(default_env, "dir").stdout.strip() == str(tmp_path / "configured")
    assert run(env, "dir").stdout.strip() == env["STANDING_STATE_DIR"]


@pytest.mark.parametrize("name", ["a", "a" * 32, "a0_-"])
def test_valid_agent_names_and_explicit_identity_wins(env, tmp_path, name):
    result = run(env, "path", "--agent", name, HIPPOCAMPUS_AGENT="other")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(tmp_path / "standing" / f"{name}.json")


@pytest.mark.parametrize("name", ["", "Aide", "1aide", "a" * 33, "a/b", "a\nb"])
def test_invalid_agent_names_are_refused(env, name):
    result = run(env, "write", "--agent", name, payload=first_write())
    assert result.returncode == 2 and "agent name" in result.stderr


@pytest.mark.parametrize("field", ["when", "reason"])
@pytest.mark.parametrize("value", [None, "", "  ", 123])
def test_each_timer_field_is_required_and_refusal_preserves_bytes(env, tmp_path, field, value):
    assert run(env, "write", "--agent", "aide", payload=first_write()).returncode == 0
    path = tmp_path / "standing" / "aide.json"
    before = path.read_bytes()
    timer = {"when": "every Monday", "reason": "Prepare the weekly briefing"}
    timer[field] = value
    result = run(env, "write", "--agent", "aide", payload={"standing": {"timers": [timer]}})
    assert result.returncode == 1
    assert f"standing.timers[0].{field} must be a non-empty string" in result.stderr
    assert path.read_bytes() == before


@pytest.mark.parametrize("item_type", ["progress", "commitment", "decision", "knowledge",
                                       "lesson", "artifact", "open_loop"])
def test_all_handoff_item_types_and_lint_are_shared(env, tmp_path, item_type):
    item = {"type": item_type, "context": "An item to file", "session_id": "run-1",
            "produced_at": STAMP, "disposition": "keep", "author": "owner", "location": "chat"}
    result = run(env, "write", "--agent", "aide", payload={"session_items": [item]})
    assert result.returncode == 0, result.stderr
    shown = json.loads(run(env, "read", "--agent", "aide", "--json").stdout)
    assert shown["resume"]["open_loops"] == [item]
    assert run(env, "lint", "--agent", "aide").returncode == 0
    del item["produced_at"]
    refused = run(env, "write", "--agent", "aide", payload={"session_items": [item]})
    assert refused.returncode == 1
    assert "produced_at must be" in refused.stderr


def test_recorded_session_items_are_removed_without_history(env):
    payload = first_write()
    item = dict(payload["resume"]["open_loops"][0], recorded=True)
    payload["resume"]["open_loops"] = [item]
    payload["session_items"] = [item]
    assert run(env, "write", "--agent", "aide", payload=payload).returncode == 0
    for trigger in ("checkpoint", "stop", "run-end"):
        assert run(env, "write", "--agent", "aide", "--trigger", trigger).returncode == 0
        state = json.loads(run(env, "read", "--agent", "aide", "--json").stdout)
        assert state["trigger"] == trigger
        assert state["resume"]["open_loops"] == []
        assert state["standing"] == payload["standing"]
        assert "session_history" not in state and "session_history" not in state["resume"]


@pytest.mark.parametrize("adapter", ["claude", "codex"])
@pytest.mark.parametrize("headless", [False, True])
def test_start_and_scheduled_runs_read_latest_state_without_reading_headless_handoffs(
        env, tmp_path, adapter, headless):
    repository = subprocess.run(["git", "init", "-q", str(tmp_path)], text=True,
                                capture_output=True, env=env)
    assert repository.returncode == 0, repository.stderr
    handoff = os.path.join(ROOT, "scripts", "lib", "handoff.py")
    handoff_payload = {"resume": {"headline": "Release work", "session_summary": "Checked the build."}}
    seed = subprocess.run([sys.executable, handoff, "checkpoint", "--session-id", "s1",
                           "--cwd", str(tmp_path)], input=json.dumps(handoff_payload),
                          text=True, capture_output=True, env=env)
    assert seed.returncode == 0, seed.stderr
    assert run(env, "write", "--agent", "aide", payload=first_write()).returncode == 0
    command = ["bash", RESTORE] if adapter == "claude" else [sys.executable, CODEX_HOOK, "post-compact"]
    hook_env = dict(env, HIPPOCAMPUS_AGENT="aide", CODEX_HOME=str(tmp_path / "codex"))
    if adapter == "codex":
        sessions = tmp_path / "codex" / "sessions"
        sessions.mkdir(parents=True)
        (sessions / "rollout-s1.jsonl").write_text(json.dumps({
            "type": "session_meta", "payload": {"id": "s1", "source": "exec" if headless else "cli"}
        }) + "\n")
    if headless:
        hook_env["CLAUDE_CODE_ENTRYPOINT"] = "headless"
    payload = json.dumps({"session_id": "s1", "cwd": str(tmp_path), "source": "startup"})
    for next_action in ("Read the latest build", "Send the updated briefing"):
        assert run(env, "write", "--agent", "aide",
                   payload={"resume": {"next_action": next_action}}).returncode == 0
        before = (tmp_path / "standing" / "aide.json").read_bytes()
        result = subprocess.run(command, input=payload, text=True, capture_output=True, env=hook_env)
        assert result.returncode == 0, result.stderr
        context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        assert next_action in context
        assert ("handoff exists" in context) is not headless
        assert (tmp_path / "standing" / "aide.json").read_bytes() == before


def test_concurrent_session_and_run_updates_keep_both_fields(env):
    assert run(env, "write", "--agent", "aide", payload=first_write()).returncode == 0
    updates = [({"resume": {"headline": "Session update"}}, "checkpoint"),
               ({"standing": {"waiting_on": [{"who": "build owner", "context": "Retry"}]}}, "run-end")]
    processes = []
    for payload, trigger in updates:
        process = subprocess.Popen([sys.executable, MODULE, "write", "--agent", "aide",
                                    "--trigger", trigger], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        processes.append((process, payload))
    for process, payload in processes:
        process.stdin.write(json.dumps(payload))
        process.stdin.close()
        process.stdin = None
    for process, _ in processes:
        _, stderr = process.communicate(timeout=15)
        assert process.returncode == 0, stderr
    state = json.loads(run(env, "read", "--agent", "aide", "--json").stdout)
    assert state["resume"]["headline"] == "Session update"
    assert state["standing"]["waiting_on"] == [{"who": "build owner", "context": "Retry"}]
