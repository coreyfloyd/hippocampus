"""Contract tests for the stdlib-only session-handoff module.

The fixtures are created through the module's writer so each validation probe
starts from a shape the production writer can actually produce.
"""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE = os.path.join(ROOT, "scripts", "lib", "handoff.py")
LEDGER_HOOK = os.path.join(ROOT, "hooks", "handoff-ledger.sh")
GUARD_HOOK = os.path.join(ROOT, "hooks", "handoff-staleness-guard.sh")


def load_module():
    spec = importlib.util.spec_from_file_location("handoff", MODULE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def valid_payload():
    return {
        "resume": {
            "headline": "Continue the handoff port",
            "next_action": "Run the targeted tests",
            "open_loops": [{"context": "Test module seam", "disposition": "file if needed"}],
        },
        "spawned_processes": [],
        "suggested_skills": ["pickup"],
    }


def test_resolve_prefers_override_and_canonicalizes_subject(tmp_path, monkeypatch):
    handoff = load_module()
    state = tmp_path / "state"
    subject = tmp_path / "subject"
    subject.mkdir()
    monkeypatch.setenv("HANDOFF_STATE_DIR", str(state))
    first = handoff.resolve_path(str(subject / "."), "session-one")
    assert first.startswith(str(state))
    assert first.endswith("-session-one.json")
    second = handoff.resolve_path(str(subject), "session-two")
    assert first != second
    monkeypatch.setenv("HANDOFF_PATH", str(tmp_path / "override.json"))
    assert handoff.resolve_path(str(subject), "session-two") == str(tmp_path / "override.json")
    assert handoff.resolve_subject_path(str(subject), "session-one") == first


def test_resolve_cli_requires_a_session_id(tmp_path):
    base_env = {key: value for key, value in os.environ.items()
                if key not in ("CLAUDE_SESSION_ID", "CLAUDE_CODE_SESSION_ID",
                               "CODEX_THREAD_ID", "HANDOFF_PATH")}
    result = subprocess.run(
        [sys.executable, MODULE, "resolve", str(tmp_path)],
        text=True,
        capture_output=True,
        env=base_env,
    )
    assert result.returncode == 2
    assert "session id" in result.stderr.lower()


def test_checkpoint_cli_accepts_explicit_path_without_session_id(tmp_path):
    path = tmp_path / "controller" / "handoff.json"
    env = {key: value for key, value in os.environ.items()
           if key not in ("CLAUDE_SESSION_ID", "CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID")}
    env["HANDOFF_PATH"] = str(path)
    result = subprocess.run(
        [sys.executable, MODULE, "checkpoint", "--cwd", str(tmp_path)],
        input=json.dumps(valid_payload()),
        text=True,
        capture_output=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert f"Handoff file: {path}" in result.stdout
    assert json.loads(path.read_text())["subject"]["session_id"] == ""


def test_resolve_cli_accepts_the_plain_bash_session_environment(tmp_path):
    env = {key: value for key, value in os.environ.items()
           if key not in ("CLAUDE_SESSION_ID", "CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID")}
    env.update({"CLAUDE_CODE_SESSION_ID": "ambient-session",
                "HANDOFF_STATE_DIR": str(tmp_path / "state")})
    result = subprocess.run([sys.executable, MODULE, "resolve", str(tmp_path)],
                            text=True, capture_output=True, env=env)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("-ambient-session.json")


def test_write_cli_refuses_a_subject_less_handoff(tmp_path):
    """#1411: the low-level `write` primitive must fail loud on a payload missing
    the subject/git blocks, not silently emit a handoff pickup cannot read."""
    target = tmp_path / "bad.json"
    incomplete = json.dumps(
        {"schema_version": 2, "headline": "x", "next_action": "y", "open_loops": []}
    )
    result = subprocess.run(
        [sys.executable, MODULE, "write", str(target)],
        input=incomplete, text=True, capture_output=True,
    )
    assert result.returncode == 2, result.stdout
    assert "refused" in result.stderr.lower()
    assert "checkpoint" in result.stderr.lower()
    assert not target.exists()


def test_cycle_request_handoff_path_routes_tasks_and_requires_identity(tmp_path, monkeypatch):
    handoff = load_module()
    home = tmp_path / "home"
    state = tmp_path / "state"
    monkeypatch.setenv("HANDOFF_STATE_DIR", str(state))
    config = tmp_path / "continuity-config.json"
    config.write_text(json.dumps({"cycle_sessions": {"tasks": "work/tasks"}}))
    monkeypatch.setenv("CONTINUITY_CONFIG", str(config))

    assert handoff.cycle_request_handoff_path("tasks", "session-one", str(home)) == (
        handoff.resolve_subject_path(str(home / "work" / "tasks"), "session-one")
    )
    assert handoff.cycle_request_handoff_path("obsidian", "session-one", str(home)) == ""
    with pytest.raises(ValueError, match="CLAUDE_CODE_SESSION_ID"):
        handoff.cycle_request_handoff_path("tasks", "", str(home))


def test_cycle_request_handoff_path_is_empty_with_no_cycle_sessions_configured(tmp_path, monkeypatch):
    """No personal session name is built into the module (#1709)."""
    handoff = load_module()
    monkeypatch.setenv("HANDOFF_STATE_DIR", str(tmp_path / "state"))
    assert handoff.cycle_request_handoff_path("tasks", "session-one", str(tmp_path / "home")) == ""


def test_config_get_prints_a_string_a_list_and_nothing_for_an_absent_key(tmp_path, monkeypatch):
    config = tmp_path / "continuity-config.json"
    config.write_text(json.dumps({"example_string": "someone", "checklist_surfaces": ["~/a", "~/b"]}))
    env = dict(os.environ, CONTINUITY_CONFIG=str(config))

    def get(key):
        return subprocess.run([sys.executable, MODULE, "config-get", key], text=True,
                              capture_output=True, env=env)

    assert get("example_string").stdout == "someone\n"
    assert get("checklist_surfaces").stdout == "~/a\n~/b\n"
    absent = get("missing_key")
    assert absent.returncode == 0 and absent.stdout == ""
    config.write_text(json.dumps({"example_string": ""}))
    bad = get("example_string")
    assert bad.returncode == 2 and "example_string" in bad.stderr


def test_automated_cycle_handoff_requires_one_fresh_session_for_the_subject(tmp_path, monkeypatch):
    handoff = load_module()
    state = tmp_path / "state"
    subject = tmp_path / "work" / "tasks"
    subject.mkdir(parents=True)
    monkeypatch.setenv("HANDOFF_STATE_DIR", str(state))
    now = handoff.datetime(2026, 9, 8, 4, 0, tzinfo=handoff.timezone.utc)

    first = handoff.resolve_subject_path(str(subject), "session-one")
    handoff.atomic_write(first, handoff.overlay_checkpoint(
        valid_payload(), str(subject), "session-one", "checkpoint",
    ))
    os.utime(first, (now.timestamp(), now.timestamp()))

    assert handoff.automated_cycle_handoff_path(
        str(subject), 6, now=now,
    ) == first

    second = handoff.resolve_subject_path(str(subject), "session-two")
    handoff.atomic_write(second, handoff.overlay_checkpoint(
        valid_payload(), str(subject), "session-two", "checkpoint",
    ))
    os.utime(second, (now.timestamp(), now.timestamp()))
    with pytest.raises(ValueError, match="ambiguous"):
        handoff.automated_cycle_handoff_path(str(subject), 6, now=now)

    os.utime(second, ((now.timestamp() - 7 * 3600),) * 2)
    assert handoff.automated_cycle_handoff_path(
        str(subject), 6, now=now,
    ) == first


def test_cycle_request_write_and_validate_round_trip(tmp_path):
    handoff = load_module()
    target = tmp_path / "requests" / "tasks.json"
    requested_at = handoff.datetime(2026, 9, 7, 12, 0, tzinfo=handoff.timezone.utc)

    record = handoff.write_cycle_request(
        str(target), "tasks", "handoff written", 4, "/tmp/handoff.json",
        requested_at=requested_at, requested_by_pid=123,
    )

    assert json.loads(target.read_text()) == record
    assert record == {
        "session": "tasks",
        "requested_at": "2026-09-07T12:00:00+00:00",
        "requested_by_pid": 123,
        "reason": "handoff written",
        "handoff_path": "/tmp/handoff.json",
        "handoff_age_min": 4,
    }
    assert handoff.validate_cycle_request(
        str(target), 900, ["tasks"], now=requested_at,
    ) == ("tasks", "/tmp/handoff.json")

    target.write_text(json.dumps(record | {"handoff_path": 7}))
    with pytest.raises(ValueError, match="malformed 'handoff_path'"):
        handoff.validate_cycle_request(str(target), 900, ["tasks"], now=requested_at)


def test_dispatch_cycle_request_owns_handoff_argument_routing(tmp_path, monkeypatch):
    handoff = load_module()
    request = tmp_path / "tasks.json"
    request.write_text(json.dumps({
        "session": "tasks",
        "handoff_path": "/tmp/session-handoff.json",
    }))
    calls = tmp_path / "calls"
    cycler = tmp_path / "cycle-stub.sh"
    cycler.write_text(
        "#!/bin/bash\n"
        "printf '%s\\n' \"$*\" >\"$CYCLE_CALLS\"\n"
        "exit 7\n"
    )
    cycler.chmod(0o755)
    monkeypatch.setenv("CYCLE_CALLS", str(calls))

    assert handoff.dispatch_cycle_request(str(request), str(cycler)) == 7
    assert calls.read_text() == "tasks --state-file /tmp/session-handoff.json\n"

    request.write_text(json.dumps({"session": "tasks"}))
    assert handoff.dispatch_cycle_request(str(request), str(cycler)) == 7
    assert calls.read_text() == "tasks --automated-handoff\n"


def test_repository_root_uses_linked_worktree_common_dir(tmp_path):
    handoff = load_module()
    repo = tmp_path / "repo"
    linked = tmp_path / "linked"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@x", "commit", "-qm", "init", "--allow-empty"], check=True)
    subprocess.run(["git", "-C", str(repo), "worktree", "add", "-qb", "linked", str(linked)], check=True)
    assert handoff.repository_root(str(linked)) == str(repo.resolve())


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d.update({"tickets": []}), "banned top-level key 'tickets'"),
        (lambda d: d["subject"].pop("session_id"), "requires subject.session_id"),
        (lambda d: d["resume"]["open_loops"][0].pop("disposition"), "has no anchor"),
        (lambda d: d["resume"]["open_loops"][0].update({"context": "x" * 601}), "context is 601 chars"),
    ],
)
def test_lint_rules_reject_written_shapes(tmp_path, mutate, message):
    handoff = load_module()
    data = handoff.overlay_checkpoint(valid_payload(), str(tmp_path), "s", "checkpoint")
    mutate(data)
    path = tmp_path / "handoff.json"
    handoff.atomic_write(str(path), data)
    violations, _warnings = handoff.lint_file(str(path))
    assert any(message in violation for violation in violations)


def test_lint_accepts_v1_and_v2_and_ignores_unknown_keys(tmp_path):
    handoff = load_module()
    v1 = {"schema_version": 1, "resume": {"headline": "v1", "open_loops": []}, "spawned_processes": []}
    v2 = handoff.overlay_checkpoint(valid_payload(), str(tmp_path), "s", "checkpoint")
    v2["unknown"] = {"accepted": True}
    for name, data in (("v1", v1), ("v2", v2)):
        path = tmp_path / (name + ".json")
        handoff.atomic_write(str(path), data)
        assert handoff.lint_file(str(path))[0] == []


def test_atomic_write_leaves_prior_file_when_serialization_fails(tmp_path):
    handoff = load_module()
    path = tmp_path / "handoff.json"
    handoff.atomic_write(str(path), {"old": True})
    with pytest.raises(TypeError):
        handoff.atomic_write(str(path), {"not_json": {1, 2}})
    assert json.loads(path.read_text()) == {"old": True}


def test_atomic_write_leaves_prior_file_when_interrupted_before_replace(tmp_path, monkeypatch):
    handoff = load_module()
    path = tmp_path / "handoff.json"
    handoff.atomic_write(str(path), {"old": True})
    with pytest.raises(InterruptedError):
        handoff.atomic_write(str(path), {"new": True}, before_replace=lambda: (_ for _ in ()).throw(InterruptedError()))
    assert json.loads(path.read_text()) == {"old": True}
    assert list(tmp_path.glob(".operator-handoff.*.tmp")) == []


def test_checkpoint_writes_then_lints_and_preserves_banned_payload(tmp_path, monkeypatch):
    handoff = load_module()
    monkeypatch.setenv("HANDOFF_STATE_DIR", str(tmp_path / "state"))
    result = handoff.checkpoint(valid_payload() | {"tickets": ["example-owner/example-repo#1001"]}, str(tmp_path), "s", "wrap")
    assert result.exit_code == 1
    stored = json.loads(open(result.path).read())
    assert stored["tickets"] == ["example-owner/example-repo#1001"]


def test_two_sessions_in_one_cwd_write_distinct_files(tmp_path, monkeypatch):
    handoff = load_module()
    monkeypatch.setenv("HANDOFF_STATE_DIR", str(tmp_path / "state"))
    first = handoff.checkpoint(valid_payload(), str(tmp_path), "session-one", "checkpoint")
    second = handoff.checkpoint(valid_payload(), str(tmp_path), "session-two", "checkpoint")
    assert first.exit_code == 0
    assert second.exit_code == 0
    assert first.path != second.path
    assert json.loads(open(first.path).read())["subject"]["session_id"] == "session-one"
    assert json.loads(open(second.path).read())["subject"]["session_id"] == "session-two"


def test_migrate_legacy_handoffs_renames_valid_and_leaves_idless(tmp_path, monkeypatch):
    handoff = load_module()
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setenv("HANDOFF_STATE_DIR", str(state))
    valid = handoff.overlay_checkpoint(valid_payload(), str(tmp_path / "subject"),
                                       "session-one", "checkpoint")
    legacy = state / "legacy-cwd-hash.json"
    idless = state / "idless.json"
    legacy.write_text(json.dumps(valid))
    idless.write_text(json.dumps({"schema_version": 1, "resume": {"open_loops": []}}))

    result = handoff.migrate_legacy_handoffs()

    expected = handoff.resolve_subject_path(str(tmp_path / "subject"), "session-one")
    assert result["moved"] == [{"from": str(legacy), "to": expected}]
    assert result["left"] == [{"path": str(idless), "reason": "missing_valid_session_id"}]
    assert not legacy.exists()
    assert os.path.isfile(expected)
    assert idless.exists()
    assert handoff.migrate_legacy_handoffs()["moved"] == []


def test_count_groups_sibling_handoffs_by_repository(tmp_path, monkeypatch):
    handoff = load_module()
    state = tmp_path / "state"
    monkeypatch.setenv("HANDOFF_STATE_DIR", str(state))
    repo = tmp_path / "repo"
    repo.mkdir()
    first = handoff.overlay_checkpoint(valid_payload(), str(tmp_path / "one"), "", "checkpoint", repository_root=str(repo), branch="one")
    second = handoff.overlay_checkpoint(valid_payload(), str(tmp_path / "two"), "", "checkpoint", repository_root=str(repo), branch="two")
    handoff.atomic_write(str(state / "one.json"), first)
    handoff.atomic_write(str(state / "two.json"), second)
    monkeypatch.setattr(handoff, "repository_root", lambda _cwd: str(repo))
    assert handoff.count_for_repository(str(tmp_path / "one")) == 2


@pytest.mark.parametrize(
    ("entrypoint", "agent_id", "expected"),
    [("cli", "", True), ("sdk-cli", "", False), ("future-ide", "", True), ("cli", "child", False)],
)
def test_interactive_gate(entrypoint, agent_id, expected):
    handoff = load_module()
    assert handoff.is_interactive({"agent_id": agent_id}, entrypoint) is expected


def test_guard_uses_recorded_commit_ownership_in_linked_worktree(tmp_path):
    handoff = load_module()
    repo = tmp_path / "repo"
    linked = tmp_path / "linked"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@x", "commit", "-qm", "init", "--allow-empty"], check=True)
    subprocess.run(["git", "-C", str(repo), "worktree", "add", "-qb", "linked", str(linked)], check=True)
    baseline = subprocess.check_output(["git", "-C", str(linked), "rev-parse", "HEAD"], text=True).strip()
    data = handoff.overlay_checkpoint(valid_payload(), str(linked), "s", "checkpoint", repository_root=str(repo), branch="linked", head=baseline)
    path = tmp_path / "handoff.json"
    handoff.atomic_write(str(path), data)
    (linked / "work").write_text("x")
    subprocess.run(["git", "-C", str(linked), "add", "work"], check=True)
    subprocess.run(["git", "-C", str(linked), "-c", "user.name=t", "-c", "user.email=t@x", "commit", "-qm", "work"], check=True)
    head = subprocess.check_output(["git", "-C", str(linked), "rev-parse", "HEAD"], text=True).strip()
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(json.dumps({"repo_root": str(repo), "commit": head}) + "\n")
    assert handoff.guard_decide(str(path), str(ledger))["decision"] == "block"


def test_cli_is_stdlib_only_when_common_third_party_names_are_poisoned(tmp_path):
    code = "import sys; sys.modules.update({n: None for n in ('pydantic','dotenv','factory')}); import importlib.util; s=importlib.util.spec_from_file_location('handoff', sys.argv[1]); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); print(m.__name__)"
    result = subprocess.run([sys.executable, "-c", code, MODULE], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "handoff"


def test_every_cli_subcommand_is_registered():
    result = subprocess.run([sys.executable, MODULE, "--help"], text=True, capture_output=True)
    assert result.returncode == 0
    for command in (
        "resolve", "repository-root", "lint", "write", "count", "checkpoint",
        "ledger-record", "guard-decide", "is-interactive", "cycle-request-path",
        "cycle-request-write", "cycle-request-validate", "cycle-request-dispatch",
    ):
        assert command in result.stdout


def test_each_cli_subcommand_executes(tmp_path):
    """Exercise the executable seam, not only the imported functions."""
    def invoke(*args, stdin="", env=None):
        merged = os.environ.copy()
        merged.update(env or {})
        return subprocess.run([sys.executable, MODULE, *args], input=stdin, text=True, capture_output=True, env=merged)

    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    state = tmp_path / "state"
    resolved = invoke("resolve", str(repo), "--session-id", "session",
                      env={"HANDOFF_STATE_DIR": str(state)})
    assert resolved.returncode == 0
    path = resolved.stdout.strip()
    assert invoke("repository-root", str(repo)).stdout.strip() == str(repo.resolve())
    assert invoke("write", path, stdin=json.dumps({"schema_version": 1, "resume": {"headline": "v1", "open_loops": []}, "spawned_processes": []})).returncode == 0
    assert invoke("lint", path).returncode == 0
    assert invoke("count", str(repo), env={"HANDOFF_STATE_DIR": str(state)}).returncode == 0
    assert invoke("checkpoint", "--cwd", str(repo), "--session-id", "session",
                  stdin=json.dumps(valid_payload()), env={"HANDOFF_STATE_DIR": str(state)}).returncode == 0
    assert invoke("ledger-record", stdin="{}", env={"HANDOFF_LEDGER_DIR": str(tmp_path / "ledger")}).returncode == 0
    assert invoke("guard-decide", "--path", path, "--ledger", str(tmp_path / "absent.jsonl"), stdin="{}").returncode == 0
    assert invoke("is-interactive", json.dumps({"agent_id": ""}), env={"CLAUDE_CODE_ENTRYPOINT": "cli"}).returncode == 0


def test_guard_cli_resolves_only_the_calling_sessions_handoff(tmp_path, monkeypatch):
    handoff = load_module()
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    _configure_repo(repo)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "initial", "--allow-empty"], check=True)
    old_head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    (repo / "owned").write_text("owned")
    subprocess.run(["git", "-C", str(repo), "add", "owned"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "owned"], check=True)
    new_head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setenv("HANDOFF_STATE_DIR", str(state))
    for session_id, baseline in (("session-a", new_head), ("session-b", old_head)):
        data = handoff.overlay_checkpoint(valid_payload(), str(repo), session_id, "checkpoint",
                                          repository_root=str(repo), branch="master", head=baseline)
        handoff.atomic_write(handoff.resolve_path(str(repo), session_id, use_override=False), data)
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(json.dumps({"repo_root": str(repo), "commit": new_head}) + "\n")
    env = os.environ | {
        "CLAUDE_CODE_ENTRYPOINT": "cli",
        "HANDOFF_STATE_DIR": str(state),
        "HANDOFF_GUARD_OVERRIDE_LEDGER": str(ledger),
    }
    session_a = _run_hook(GUARD_HOOK, {"session_id": "session-a", "cwd": str(repo)}, env)
    session_b = _run_hook(GUARD_HOOK, {"session_id": "session-b", "cwd": str(repo)}, env)
    assert session_a.stdout == ""
    assert json.loads(session_b.stdout)["decision"] == "block"


def test_guard_cli_visibly_allows_a_captured_stop_payload_without_session_id(tmp_path):
    # Preserve the current captured Stop event fields while deliberately
    # omitting session_id to reproduce the malformed event.
    payload = {
        "transcript_path": str(tmp_path / "session.jsonl"),
        "cwd": str(tmp_path),
        "permission_mode": "default",
        "hook_event_name": "Stop",
        "stop_hook_active": False,
        "last_assistant_message": "Work is complete.",
    }
    env = {
        key: value for key, value in os.environ.items()
        if key not in ("CLAUDE_SESSION_ID", "CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID")
    }
    env.update({
        "CLAUDE_CODE_ENTRYPOINT": "cli",
        "HOME": str(tmp_path / "home"),
        "HANDOFF_STATE_DIR": str(tmp_path / "handoffs"),
        "HANDOFF_LEDGER_DIR": str(tmp_path / "ledger"),
    })

    result = _run_hook(GUARD_HOOK, payload, env)

    assert result.returncode == 0
    decision = json.loads(result.stdout)
    assert decision["decision"] == "allow"
    assert "missing session_id" in decision["reason"]
    assert "missing session_id" in result.stderr


def _run_hook(path, payload, env):
    return subprocess.run(["bash", path], input=json.dumps(payload), text=True, capture_output=True, env=env)


def _configure_repo(repo):
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "test"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.invalid"], check=True)


def test_pull_event_through_ledger_hook_is_not_owned_or_blocked(tmp_path):
    """A real pull moves HEAD but the remote already owns its commit."""
    remote = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    work = tmp_path / "work"
    other = tmp_path / "other"
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
    subprocess.run(["git", "clone", "-q", str(remote), str(seed)], check=True)
    _configure_repo(seed)
    (seed / "initial").write_text("initial")
    subprocess.run(["git", "-C", str(seed), "add", "initial"], check=True)
    subprocess.run(["git", "-C", str(seed), "commit", "-qm", "initial"], check=True)
    subprocess.run(["git", "-C", str(seed), "push", "-q", "origin", "HEAD"], check=True)
    subprocess.run(["git", "clone", "-q", str(remote), str(work)], check=True)
    subprocess.run(["git", "clone", "-q", str(remote), str(other)], check=True)
    _configure_repo(other)
    baseline = subprocess.check_output(["git", "-C", str(work), "rev-parse", "HEAD"], text=True).strip()
    handoff = load_module().overlay_checkpoint(valid_payload(), str(work), "session", "checkpoint", repository_root=str(work), branch="main", head=baseline)
    handoff_path = tmp_path / "handoff.json"
    load_module().atomic_write(str(handoff_path), handoff)
    env = os.environ | {"HOME": str(tmp_path / "home"), "HANDOFF_LEDGER_DIR": str(tmp_path / "ledger"), "CLAUDE_CODE_ENTRYPOINT": "cli"}
    payload = {"session_id": "session", "cwd": str(work), "tool_input": {"command": "git pull --ff-only"}, "tool_response": {"exit_code": 0}}
    assert _run_hook(LEDGER_HOOK, payload, env).returncode == 0
    (other / "remote-change").write_text("remote")
    subprocess.run(["git", "-C", str(other), "add", "remote-change"], check=True)
    subprocess.run(["git", "-C", str(other), "commit", "-qm", "remote"], check=True)
    subprocess.run(["git", "-C", str(other), "push", "-q"], check=True)
    subprocess.run(["git", "-C", str(work), "pull", "--ff-only"], check=True)
    assert _run_hook(LEDGER_HOOK, payload, env).returncode == 0
    ledger = tmp_path / "ledger" / "session-touched-paths.session.jsonl"
    guard_env = env | {"HANDOFF_GUARD_OVERRIDE_PATH": str(handoff_path), "HANDOFF_GUARD_OVERRIDE_LEDGER": str(ledger)}
    result = _run_hook(GUARD_HOOK, {"session_id": "session", "cwd": str(work)}, guard_env)
    assert result.returncode == 0
    assert result.stdout == ""


def test_dirty_linked_worktree_subject_blocks_once(tmp_path):
    """Session-owned work in the linked subject checkout must block stopping."""
    main = tmp_path / "main"
    linked = tmp_path / "linked"
    subprocess.run(["git", "init", "-q", str(main)], check=True)
    _configure_repo(main)
    subprocess.run(["git", "-C", str(main), "commit", "-qm", "initial", "--allow-empty"], check=True)
    subprocess.run(["git", "-C", str(main), "worktree", "add", "-qb", "linked", str(linked)], check=True)
    baseline = subprocess.check_output(["git", "-C", str(linked), "rev-parse", "HEAD"], text=True).strip()
    module = load_module()
    handoff = module.overlay_checkpoint(valid_payload(), str(linked), "session", "checkpoint", repository_root=str(main), branch="linked", head=baseline)
    handoff_path = tmp_path / "handoff.json"
    module.atomic_write(str(handoff_path), handoff)
    (linked / "dirty").write_text("dirty")
    dirty_mtime = handoff_path.stat().st_mtime + 10
    os.utime(linked / "dirty", (dirty_mtime, dirty_mtime))
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(json.dumps({"repo_root": str(main), "head": baseline}) + "\n")
    with ledger.open("a") as stream:
        stream.write(json.dumps({"kind": "file", "session_id": "session", "checkout": str(linked), "path": str(linked / "dirty")}) + "\n")
    env = os.environ | {"CLAUDE_CODE_ENTRYPOINT": "cli", "HANDOFF_GUARD_OVERRIDE_PATH": str(handoff_path), "HANDOFF_GUARD_OVERRIDE_LEDGER": str(ledger)}
    result = _run_hook(GUARD_HOOK, {"session_id": "session", "cwd": str(linked)}, env)
    assert result.returncode == 0
    assert json.loads(result.stdout)["decision"] == "block"


def test_all_handoff_hook_adapters_fail_open_on_malformed_json(tmp_path):
    adapters = [
        os.path.join(ROOT, "scripts", "context-guard.sh"),
        os.path.join(ROOT, "scripts", "pre-compact.sh"),
        os.path.join(ROOT, "scripts", "post-compact-restore.sh"),
        LEDGER_HOOK,
        GUARD_HOOK,
    ]
    env = os.environ | {"HOME": str(tmp_path / "home"), "HANDOFF_LEDGER_DIR": str(tmp_path / "ledger"), "HANDOFF_COMPACT_STATE_DIR": str(tmp_path / "compact")}
    for adapter in adapters:
        result = subprocess.run(["bash", adapter], input="{", text=True, capture_output=True, env=env)
        assert result.returncode == 0, adapter
        assert result.stdout == "", adapter


def test_commit_and_push_event_retains_ownership_from_prior_remote_snapshot(tmp_path):
    remote = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    work = tmp_path / "work"
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
    subprocess.run(["git", "clone", "-q", str(remote), str(seed)], check=True)
    _configure_repo(seed)
    (seed / "initial").write_text("initial")
    subprocess.run(["git", "-C", str(seed), "add", "initial"], check=True)
    subprocess.run(["git", "-C", str(seed), "commit", "-qm", "initial"], check=True)
    subprocess.run(["git", "-C", str(seed), "push", "-q", "origin", "HEAD"], check=True)
    subprocess.run(["git", "clone", "-q", str(remote), str(work)], check=True)
    _configure_repo(work)
    env = os.environ | {"HOME": str(tmp_path / "home"), "HANDOFF_LEDGER_DIR": str(tmp_path / "ledger"), "CLAUDE_CODE_ENTRYPOINT": "cli"}
    first = {"session_id": "session", "cwd": str(work), "tool_input": {"command": "git status"}, "tool_response": {"exit_code": 0}}
    assert _run_hook(LEDGER_HOOK, first, env).returncode == 0
    (work / "local").write_text("local")
    subprocess.run(["git", "-C", str(work), "add", "local"], check=True)
    subprocess.run(["git", "-C", str(work), "commit", "-qm", "local"], check=True)
    owned = subprocess.check_output(["git", "-C", str(work), "rev-parse", "HEAD"], text=True).strip()
    subprocess.run(["git", "-C", str(work), "push", "-q"], check=True)
    event = first | {"tool_input": {"command": "git commit -m local && git push"}}
    assert _run_hook(LEDGER_HOOK, event, env).returncode == 0
    rows = [json.loads(line) for line in (tmp_path / "ledger" / "session-touched-paths.session.jsonl").read_text().splitlines()]
    assert rows[-1]["commit"] == owned


def test_dirty_secondary_ledger_repository_blocks(tmp_path):
    subject = tmp_path / "subject"
    secondary = tmp_path / "secondary"
    for repo in (subject, secondary):
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        _configure_repo(repo)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "initial", "--allow-empty"], check=True)
    module = load_module()
    baseline = subprocess.check_output(["git", "-C", str(subject), "rev-parse", "HEAD"], text=True).strip()
    handoff = module.overlay_checkpoint(valid_payload(), str(subject), "session", "checkpoint", repository_root=str(subject), branch="main", head=baseline)
    handoff_path = tmp_path / "handoff.json"
    module.atomic_write(str(handoff_path), handoff)
    (secondary / "dirty").write_text("dirty")
    dirty_mtime = handoff_path.stat().st_mtime + 10
    os.utime(secondary / "dirty", (dirty_mtime, dirty_mtime))
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text("\n".join(json.dumps({"repo_root": str(repo)}) for repo in (subject, secondary)) + "\n")
    with ledger.open("a") as stream:
        stream.write(json.dumps({"kind": "file", "session_id": "session", "checkout": str(secondary), "path": str(secondary / "dirty")}) + "\n")
    env = os.environ | {"CLAUDE_CODE_ENTRYPOINT": "cli", "HANDOFF_GUARD_OVERRIDE_PATH": str(handoff_path), "HANDOFF_GUARD_OVERRIDE_LEDGER": str(ledger)}
    result = _run_hook(GUARD_HOOK, {"session_id": "session", "cwd": str(subject)}, env)
    assert json.loads(result.stdout)["decision"] == "block"


def test_git_failure_during_ownership_record_keeps_owned_list_unchanged(tmp_path, monkeypatch, capsys):
    module = load_module()
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    _configure_repo(repo)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "initial", "--allow-empty"], check=True)
    ledger_dir = tmp_path / "ledger"
    monkeypatch.setenv("HANDOFF_LEDGER_DIR", str(ledger_dir))
    payload = {"session_id": "session", "cwd": str(repo), "tool_input": {"command": "git commit -m local"}, "tool_response": {"exit_code": 0}}
    module.ledger_record(payload)
    (repo / "local").write_text("local")
    subprocess.run(["git", "-C", str(repo), "add", "local"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "local"], check=True)
    real_run_git = module._run_git
    monkeypatch.setattr(module, "_run_git", lambda cwd, *args: None if args and args[0] == "rev-list" else real_run_git(cwd, *args))
    module.ledger_record(payload)
    rows = [json.loads(line) for line in (ledger_dir / "session-touched-paths.session.jsonl").read_text().splitlines()]
    assert all("commit" not in row for row in rows)
    assert "could not determine ownership" in capsys.readouterr().err


def test_checkpoint_carries_only_owned_dirty_paths_without_git_mutation(tmp_path, monkeypatch):
    module = load_module()
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    _configure_repo(repo)
    for name in ("mine space.txt", "deleted", "committed", "foreign"):
        (repo / name).write_text("baseline")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "baseline"], check=True)
    monkeypatch.setenv("HANDOFF_LEDGER_DIR", str(tmp_path / "ledger"))
    monkeypatch.setenv("HANDOFF_STATE_DIR", str(tmp_path / "handoffs"))
    monkeypatch.delenv("HANDOFF_PATH", raising=False)
    for name in ("mine space.txt", "deleted", "committed", "new\nfile"):
        path = repo / name
        if name == "deleted":
            path.unlink()
        else:
            path.write_text("session edit")
        module.ledger_record({"session_id": "owner", "cwd": str(repo), "tool_name": "Write",
                              "tool_input": {"file_path": str(path)}})
    (repo / "foreign").write_text("someone else's edit")
    subprocess.run(["git", "-C", str(repo), "add", "committed"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "one file"], check=True)
    before = subprocess.check_output(["git", "-C", str(repo), "status", "--porcelain=v1", "-z"])
    head = module._run_git(str(repo), "rev-parse", "HEAD")
    result = module.checkpoint(valid_payload(), str(repo), "owner", "checkpoint")
    data = module.read_json(result.path)
    assert data["uncommitted_files"] == sorted(str(repo / n) for n in ("mine space.txt", "deleted", "new\nfile"))
    assert module.checkpoint(valid_payload(), str(repo), "other", "checkpoint").exit_code == 0
    assert module.read_json(module.resolve_path(str(repo), "other"))["uncommitted_files"] == []
    assert subprocess.check_output(["git", "-C", str(repo), "status", "--porcelain=v1", "-z"]) == before
    assert module._run_git(str(repo), "rev-parse", "HEAD") == head


def test_carried_items_preserve_producer_and_decision_and_summary(tmp_path, monkeypatch):
    module = load_module()
    monkeypatch.setenv("HANDOFF_LEDGER_DIR", str(tmp_path / "ledger"))
    monkeypatch.setenv("HANDOFF_STATE_DIR", str(tmp_path / "handoffs"))
    monkeypatch.delenv("HANDOFF_PATH", raising=False)
    payload = valid_payload()
    payload["resume"]["session_summary"] = "Implemented continuity capture."
    items = [{"type": kind, "context": "Actual lesson text" if kind == "lesson" else kind,
              "session_id": "earlier", "produced_at": "2026-10-02T12:00:00Z",
              "disposition": "record", **({"author": "user", "location": "chat turn 5"} if kind == "decision" else {})}
             for kind in ("progress", "commitment", "decision", "knowledge", "lesson")]
    payload["session_items"] = items + [dict(items[0], recorded=True)]
    first = module.checkpoint(payload, str(tmp_path), "current", "checkpoint")
    assert first.exit_code == 0, first.errors
    data = module.read_json(first.path)
    assert data["resume"]["open_loops"][1:] == items
    assert "session_items" not in data
    assert data["resume"]["session_summary"] == "Implemented continuity capture."
    again = module.checkpoint(data, str(tmp_path), "successor", "checkpoint")
    assert module.read_json(again.path)["resume"]["open_loops"][1:] == items


def test_artifact_command_is_ledger_backed_and_retired_explicitly(tmp_path, monkeypatch):
    module = load_module()
    ledger = tmp_path / "ledger"
    monkeypatch.setenv("HANDOFF_LEDGER_DIR", str(ledger))
    monkeypatch.setenv("HANDOFF_STATE_DIR", str(tmp_path / "handoffs"))
    monkeypatch.delenv("HANDOFF_PATH", raising=False)
    def publish(status="pending"):
        return subprocess.run([sys.executable, MODULE, "ledger-artifact", "--session-id", "publisher",
                               "--cwd", str(tmp_path), "--location", "https://example.test/page",
                               "--disposition", "keep", "--status", status], capture_output=True, text=True)
    assert publish().returncode == 0
    assert publish().returncode == 0
    first = module.checkpoint(valid_payload(), str(tmp_path), "publisher", "checkpoint")
    loops = module.read_json(first.path)["resume"]["open_loops"]
    artifacts = [loop for loop in loops if loop.get("type") == "artifact"]
    assert len(artifacts) == 1
    assert artifacts[0]["location"] == "https://example.test/page"
    assert artifacts[0]["session_id"] == "publisher"
    assert artifacts[0]["produced_at"] and artifacts[0]["disposition"] == "keep"
    successor = module.checkpoint(module.read_json(first.path), str(tmp_path), "successor", "checkpoint")
    assert artifacts[0] in module.read_json(successor.path)["resume"]["open_loops"]
    assert publish("recorded").returncode == 0
    retired = module.checkpoint(module.read_json(successor.path), str(tmp_path), "successor", "checkpoint")
    assert not any(loop.get("type") == "artifact" for loop in module.read_json(retired.path)["resume"]["open_loops"])


@pytest.mark.parametrize("change, fragment", [
    ({"type": "unknown"}, "type"), ({"session_id": ""}, "session_id"),
    ({"produced_at": "yesterday"}, "produced_at"), ({"author": ""}, "author"),
    ({"location": ""}, "location"), ({"context": ""}, "context"),
    ({"disposition": ""}, "disposition"),
])
def test_typed_carried_item_lint_writes_invalid_checkpoint(tmp_path, monkeypatch, change, fragment):
    module = load_module()
    monkeypatch.setenv("HANDOFF_PATH", str(tmp_path / "handoff.json"))
    monkeypatch.setenv("HANDOFF_LEDGER_DIR", str(tmp_path / "ledger"))
    payload = valid_payload()
    payload["session_items"] = [dict(type="decision", context="Approved scope", session_id="producer",
                                      produced_at="2026-10-02T12:00:00Z", author="user", location="chat",
                                      disposition="record", **{}) | change]
    result = module.checkpoint(payload, str(tmp_path), "s", "checkpoint")
    assert result.exit_code == 1
    assert fragment in " ".join(result.errors)
    assert os.path.isfile(result.path)
    assert result.path in result.output


def test_carried_summary_keeps_original_session_identity(tmp_path, monkeypatch):
    module = load_module()
    monkeypatch.setenv("HANDOFF_LEDGER_DIR", str(tmp_path / "ledger"))
    payload = valid_payload()
    first = module.overlay_checkpoint(payload, str(tmp_path), "producer", "checkpoint")
    summary = first["resume"]["session_history"][0]
    assert summary["session_id"] == "producer"
    assert summary["summary"] == payload["resume"]["headline"]
    assert summary["produced_at"]
    second = module.overlay_checkpoint(first, str(tmp_path), "successor", "checkpoint")
    assert summary in second["resume"]["session_history"]


def test_explicit_shell_file_ledger_tracks_linked_and_secondary_checkouts(tmp_path, monkeypatch):
    module = load_module()
    monkeypatch.setenv("HANDOFF_LEDGER_DIR", str(tmp_path / "ledger"))
    main = tmp_path / "main"
    secondary = tmp_path / "secondary"
    linked = tmp_path / "linked"
    for repo in (main, secondary):
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        _configure_repo(repo)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "initial", "--allow-empty"], check=True)
    subprocess.run(["git", "-C", str(main), "worktree", "add", "-qb", "linked", str(linked)], check=True)
    for repo in (linked, secondary):
        (repo / "owned").write_text("owned")
        result = subprocess.run([sys.executable, MODULE, "ledger-file", "owned", "--cwd", str(repo),
                                 "--session-id", "shell-session"], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        (repo / "foreign").write_text("foreign")
    assert module.uncommitted_files("shell-session") == sorted([str(linked / "owned"), str(secondary / "owned")])
    subprocess.run(["git", "-C", str(linked), "add", "owned"], check=True)
    assert str(linked / "owned") in module.uncommitted_files("shell-session")


@pytest.mark.parametrize("item", [
    {"type": ["lesson"], "context": "text", "disposition": "record"},
    {"context": "missing type", "disposition": "record"},
    {"type": "artifact", "location": {"url": "bad"}, "disposition": "keep"},
])
def test_malformed_carried_items_are_written_and_reported(tmp_path, monkeypatch, item):
    module = load_module()
    monkeypatch.setenv("HANDOFF_PATH", str(tmp_path / "handoff.json"))
    monkeypatch.setenv("HANDOFF_LEDGER_DIR", str(tmp_path / "ledger"))
    payload = valid_payload()
    payload["session_items"] = [item]
    result = module.checkpoint(payload, str(tmp_path), "s", "checkpoint")
    assert result.exit_code == 1
    assert os.path.isfile(result.path)


def test_artifact_remove_disposition_and_removed_state(tmp_path, monkeypatch):
    module = load_module()
    monkeypatch.setenv("HANDOFF_LEDGER_DIR", str(tmp_path / "ledger"))
    module.record_artifact(str(tmp_path), "s", str(tmp_path / "page.html"), "remove")
    loops = module.carry_artifacts([], "s")
    assert loops[0]["disposition"] == "remove"
    module.record_artifact(str(tmp_path), "s", str(tmp_path / "page.html"), "remove", "removed")
    assert module.carry_artifacts(loops, "next") == []


def test_summary_updates_current_session_without_rewriting_carried_history(tmp_path, monkeypatch):
    module = load_module()
    monkeypatch.setenv("HANDOFF_LEDGER_DIR", str(tmp_path / "ledger"))
    first = module.overlay_checkpoint(valid_payload(), str(tmp_path), "s", "checkpoint")
    first["resume"]["session_history"].insert(0, {"session_id": "old", "produced_at": "2026-10-01T12:00:00Z", "summary": "Earlier work"})
    first["resume"]["session_summary"] = "Finished the implementation"
    second = module.overlay_checkpoint(first, str(tmp_path), "s", "checkpoint")
    assert second["resume"]["session_history"][0] == first["resume"]["session_history"][0]
    assert second["resume"]["session_history"][1]["summary"] == "Finished the implementation"


def test_summary_timestamp_is_validated(tmp_path, monkeypatch):
    module = load_module()
    monkeypatch.setenv("HANDOFF_LEDGER_DIR", str(tmp_path / "ledger"))
    data = module.overlay_checkpoint(valid_payload(), str(tmp_path), "s", "checkpoint")
    data["resume"]["session_history"][0]["produced_at"] = "yesterday"
    assert any("produced_at" in error for error in module.lint_data(data)[0])


def test_each_successor_summary_survives_under_its_own_identity(tmp_path):
    module = load_module()
    prior = module.overlay_checkpoint(valid_payload(), str(tmp_path), "prior", "checkpoint")
    original = dict(prior["resume"]["session_history"][0])
    prior["resume"]["session_summary"] = "Successor implemented the repair"
    successor = module.overlay_checkpoint(prior, str(tmp_path), "successor", "checkpoint")
    history = successor["resume"]["session_history"]
    assert original in history
    assert [row["summary"] for row in history if row["session_id"] == "successor"] == ["Successor implemented the repair"]
    successor_row = dict(next(row for row in history if row["session_id"] == "successor"))
    successor["resume"]["session_summary"] = "Third session verified it"
    third = module.overlay_checkpoint(successor, str(tmp_path), "third", "checkpoint")
    assert original in third["resume"]["session_history"]
    assert successor_row in third["resume"]["session_history"]
    assert next(row for row in third["resume"]["session_history"] if row["session_id"] == "third")["summary"] == "Third session verified it"


@pytest.mark.parametrize("deleted", [False, True])
def test_owned_paths_through_directory_symlink_are_carried(tmp_path, deleted):
    module = load_module()
    real = tmp_path / "real"
    alias = tmp_path / "alias"
    subprocess.run(["git", "init", "-q", str(real)], check=True)
    _configure_repo(real)
    (real / "owned").write_text("initial")
    subprocess.run(["git", "-C", str(real), "add", "."], check=True)
    subprocess.run(["git", "-C", str(real), "commit", "-qm", "initial"], check=True)
    alias.symlink_to(real, target_is_directory=True)
    if deleted:
        (alias / "owned").unlink()
    else:
        (alias / "owned").write_text("changed")
    module.record_file(str(alias), "owner", str(alias / "owned"))
    assert module.uncommitted_files("owner") == [str(real.resolve() / "owned")]
    assert module.uncommitted_files("other") == []


def test_legacy_symlink_spelling_in_file_ledger_matches_status(tmp_path):
    module = load_module()
    real = tmp_path / "real"
    alias = tmp_path / "alias"
    subprocess.run(["git", "init", "-q", str(real)], check=True)
    alias.symlink_to(real, target_is_directory=True)
    (real / "owned").write_text("new")
    module.append_ledger("owner", {"kind": "file", "session_id": "owner", "checkout": str(alias), "path": str(alias / "owned")})
    assert module.uncommitted_files("owner") == [str(real.resolve() / "owned")]


def _storage_env(tmp_path, monkeypatch):
    for key in ("HANDOFF_STATE_DIR", "HANDOFF_LEDGER_DIR", "HANDOFF_PATH", "XDG_CONFIG_HOME"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    config = tmp_path / "config.json"
    monkeypatch.setenv("CONTINUITY_CONFIG", str(config))
    return config


def test_storage_defaults_to_the_user_state_directory_when_unconfigured(tmp_path, monkeypatch):
    handoff = load_module()
    _storage_env(tmp_path, monkeypatch)
    home = tmp_path / "home"
    assert handoff.state_dir() == str(home / ".local/state/continuity/handoffs")
    assert handoff.ledger_path("s1") == str(home / ".local/state/continuity/session-touched-paths.s1.jsonl")


def test_configured_handoff_dir_places_handoffs_and_ledger(tmp_path, monkeypatch):
    handoff = load_module()
    config = _storage_env(tmp_path, monkeypatch)
    config.write_text(json.dumps({"handoff_dir": "~/state/session-handoffs"}))
    home = tmp_path / "home"
    assert handoff.state_dir() == str(home / "state/session-handoffs")
    assert handoff.resolve_path(str(tmp_path), "s1").startswith(str(home / "state/session-handoffs") + os.sep)
    assert handoff.ledger_path("s1") == str(home / "state/session-touched-paths.s1.jsonl")
    # An explicit environment override still wins over the configuration.
    monkeypatch.setenv("HANDOFF_STATE_DIR", str(tmp_path / "override"))
    assert handoff.state_dir() == str(tmp_path / "override")


def test_config_location_follows_xdg_config_home(tmp_path, monkeypatch):
    handoff = load_module()
    _storage_env(tmp_path, monkeypatch)
    monkeypatch.delenv("CONTINUITY_CONFIG")
    xdg = tmp_path / "xdg"
    (xdg / "continuity").mkdir(parents=True)
    (xdg / "continuity" / "config.json").write_text(json.dumps({"handoff_dir": str(tmp_path / "h")}))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    assert handoff.state_dir() == str(tmp_path / "h")


def test_malformed_config_is_an_error_not_a_silent_default(tmp_path, monkeypatch):
    handoff = load_module()
    config = _storage_env(tmp_path, monkeypatch)
    config.write_text("{not json")
    with pytest.raises(ValueError, match="continuity config"):
        handoff.state_dir()
    config.write_text(json.dumps({"handoff_dir": ""}))
    with pytest.raises(ValueError, match="handoff_dir"):
        handoff.state_dir()
    result = subprocess.run([sys.executable, MODULE, "state-dir"], text=True, capture_output=True,
                            env=dict(os.environ))
    assert result.returncode == 2 and "handoff_dir" in result.stderr


def test_state_dir_cli_prints_the_configured_location(tmp_path, monkeypatch):
    config = _storage_env(tmp_path, monkeypatch)
    config.write_text(json.dumps({"handoff_dir": str(tmp_path / "configured")}))
    result = subprocess.run([sys.executable, MODULE, "state-dir"], text=True, capture_output=True,
                            env=dict(os.environ))
    assert result.returncode == 0 and result.stdout.strip() == str(tmp_path / "configured")


def test_ambient_session_id_uses_codex_identity_over_inherited_claude_identity(monkeypatch):
    """The child Codex thread owns its ledger even with Claude parent variables."""
    handoff = load_module()
    for key in ("CLAUDE_SESSION_ID", "CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID"):
        monkeypatch.delenv(key, raising=False)
    assert handoff.ambient_session_id() == ""
    monkeypatch.setenv("CODEX_THREAD_ID", "codex-thread")
    assert handoff.ambient_session_id() == "codex-thread"
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "claude-session")
    assert handoff.ambient_session_id() == "codex-thread"
    monkeypatch.delenv("CODEX_THREAD_ID")
    assert handoff.ambient_session_id() == "claude-session"


def test_resolve_cli_and_shell_library_accept_the_codex_session_environment(tmp_path):
    env = {key: value for key, value in os.environ.items()
           if key not in ("CLAUDE_SESSION_ID", "CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID", "HANDOFF_PATH")}
    env.update({"CODEX_THREAD_ID": "codex-thread", "HANDOFF_STATE_DIR": str(tmp_path / "state")})
    result = subprocess.run([sys.executable, MODULE, "resolve", str(tmp_path)],
                            text=True, capture_output=True, env=env)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("-codex-thread.json")
    library = os.path.join(ROOT, "scripts", "lib", "handoff.sh")
    shell = subprocess.run(["bash", "-c", '. "$1"; resolve_handoff_path "$2"', "_", library, str(tmp_path)],
                           text=True, capture_output=True, env=env)
    assert shell.returncode == 0, shell.stderr
    assert shell.stdout.strip() == result.stdout.strip()


def _missing_handoff_repo(tmp_path):
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@x", "commit", "-qm", "init", "--allow-empty"], check=True)
    return repo.resolve(), tmp_path / "absent-handoff.json", tmp_path / "ledger.jsonl"


def _git_state_record(repo, ts="2026-01-01T00:00:00Z"):
    return json.dumps({"repo_root": str(repo), "head": "h", "remote_heads": [], "ts": ts}) + "\n"


@pytest.mark.parametrize("work", ["read-only", "file", "commit", "shell", "no-ledger"])
def test_stop_writes_lint_clean_skeleton_and_allows(tmp_path, monkeypatch, work):
    handoff = load_module()
    repo, path, ledger = _missing_handoff_repo(tmp_path)
    monkeypatch.setenv("HANDOFF_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("HANDOFF_LEDGER_DIR", str(tmp_path))
    ledger = tmp_path / "session-touched-paths.s.jsonl"
    if work == "file":
        (repo / "edited.txt").write_text("x")
        handoff.record_file(str(repo), "s", "edited.txt")
    elif work == "commit":
        ledger.write_text(json.dumps({"repo_root": str(repo), "commit": "h"}) + "\n")
    elif work == "shell":
        (repo / "shell.txt").write_text("x")
    elif work == "read-only":
        ledger.write_text(_git_state_record(repo))
    env = os.environ | {"CLAUDE_CODE_ENTRYPOINT": "cli", "CONTINUITY_HARNESS": "claude"}
    env.pop("CODEX_THREAD_ID", None)
    result = _run_hook(GUARD_HOOK, {"session_id": "s", "cwd": str(repo)}, env)
    assert result.returncode == 0 and result.stdout == "", result.stderr
    path = Path(handoff.resolve_path(str(repo), "s"))
    data = json.loads(path.read_text())
    assert data["subject"] == {"working_directory": str(repo), "session_id": "s"}
    assert data["git"]["head"] == handoff._run_git(str(repo), "rev-parse", "HEAD")
    assert data["resume"]["headline"] == ""
    assert data["resume"]["open_loops"] == []
    assert data["uncommitted_files"] == ([str(repo / "edited.txt")] if work == "file" else [])
    errors, warnings = handoff.lint_file(str(path))
    assert errors == [] and warnings == ["resume.headline empty"]
    before = path.read_bytes(), path.stat().st_mtime_ns
    assert _run_hook(GUARD_HOOK, {"session_id": "s", "cwd": str(repo)}, env).stdout == ""
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


@pytest.mark.parametrize("changes,entrypoint", [({"agent_id": "child"}, "cli"), ({}, "sdk-cli"), ({"stop_hook_active": True}, "cli")])
def test_excluded_stop_writes_nothing(tmp_path, monkeypatch, changes, entrypoint):
    monkeypatch.setenv("HANDOFF_STATE_DIR", str(tmp_path / "state"))
    env = os.environ | {"CLAUDE_CODE_ENTRYPOINT": entrypoint, "CONTINUITY_HARNESS": "claude"}
    env.pop("CODEX_THREAD_ID", None)
    result = _run_hook(GUARD_HOOK, {"session_id": "s", "cwd": str(tmp_path), **changes}, env)
    assert result.returncode == 0 and result.stdout == ""
    assert not (tmp_path / "state").exists()


@pytest.mark.parametrize("ownership,dirty,newer,expected", [
    ("own", True, True, "block"), ("other", True, True, "allow"),
    ("none", True, True, "allow"), ("own", False, True, "allow"),
    ("own", True, False, "allow"),
])
def test_stale_files_require_session_ownership_and_newer_uncommitted_file(tmp_path, ownership, dirty, newer, expected):
    handoff = load_module()
    repo, path, ledger = _missing_handoff_repo(tmp_path)
    handoff.atomic_write(str(path), handoff.overlay_checkpoint(valid_payload(), str(repo), "s", "checkpoint"))
    edited = repo / 'space " in name.txt'
    edited.write_text("x")
    if not dirty:
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@x", "commit", "-qm", "file"], check=True)
    stamp = path.stat().st_mtime + (10 if newer else -10)
    os.utime(edited, (stamp, stamp))
    records = [{"repo_root": str(repo), "head": "h"}]
    if ownership != "none":
        records.append({"kind": "file", "path": str(edited), "checkout": str(repo), "session_id": "s" if ownership == "own" else "other"})
    ledger.write_text("".join(json.dumps(row) + "\n" for row in records))
    assert handoff.guard_decide(str(path), str(ledger))["decision"] == expected


def test_atomic_create_never_replaces_a_concurrent_handoff(tmp_path):
    handoff = load_module()
    path = tmp_path / "handoff.json"
    def concurrent_checkpoint():
        handoff.atomic_write(str(path), {"existing": True})
    handoff.atomic_write(str(path), {"skeleton": True}, before_replace=concurrent_checkpoint, replace=False)
    assert json.loads(path.read_text()) == {"existing": True}
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("ownership,newer,committed,expected", [
    ("own", True, False, "block"), ("own", False, False, "allow"),
    ("other", True, False, "allow"), ("none", True, False, "allow"),
    ("own", True, True, "allow"),
])
def test_stale_renamed_file_retains_source_ownership(tmp_path, ownership, newer, committed, expected):
    handoff = load_module()
    repo, path, ledger = _missing_handoff_repo(tmp_path)
    source = repo / 'original " file.txt'
    destination = repo / 'renamed " file.txt'
    source.write_text("unchanged line\n" * 100)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@x", "commit", "-qm", "tracked file"], check=True)
    handoff.atomic_write(str(path), handoff.overlay_checkpoint(valid_payload(), str(repo), "s", "checkpoint"))
    source.write_text(source.read_text() + "session edit\n")
    records = [] if ownership == "none" else [{"kind": "file", "path": str(source), "checkout": str(repo), "session_id": "s" if ownership == "own" else "other"}]
    ledger.write_text("".join(json.dumps(row) + "\n" for row in records))
    subprocess.run(["git", "-C", str(repo), "mv", source.name, destination.name], check=True)
    status = subprocess.run(["git", "-C", str(repo), "status", "--porcelain=v1", "-z"], capture_output=True, check=True).stdout
    assert status.split(b"\0")[:2] == [b"RM " + os.fsencode(destination.name), os.fsencode(source.name)]
    if committed:
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@x", "commit", "-qm", "rename"], check=True)
        assert subprocess.run(["git", "-C", str(repo), "status", "--porcelain=v1", "-z"], capture_output=True, check=True).stdout == b""
    stamp = path.stat().st_mtime + (10 if newer else -10)
    os.utime(destination, (stamp, stamp))
    assert not source.exists()
    assert handoff.guard_decide(str(path), str(ledger))["decision"] == expected


def test_config_get_prints_positive_integer_prune_days(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"prune_days": 14}))
    result = subprocess.run(
        [sys.executable, MODULE, "config-get", "prune_days"],
        text=True, capture_output=True,
        env=dict(os.environ, CONTINUITY_CONFIG=str(config)))
    assert result.returncode == 0, result.stderr
    assert result.stdout == "14\n"
