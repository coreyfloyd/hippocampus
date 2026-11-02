"""The Claude Code plugin: one install adds the nine skills and the six hooks.

The hook tests run every command `hooks/hooks.json` registers, the way Claude
Code runs it (`bash -c` with `CLAUDE_PLUGIN_ROOT` exported), in a home with
nothing configured. The payloads carry the fields Claude Code delivers for each
event; the shell result's keys (`stdout`, `stderr`, `interrupted`, `isImage`,
`noOutputExpected`, no exit code) are those of a recorded Claude Code session.

The install tests drive the real `claude plugin` commands against a sandboxed
home and are skipped when the `claude` command is not installed.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS_FILE = os.path.join(ROOT, "hooks", "hooks.json")
HANDOFF = os.path.join(ROOT, "scripts", "lib", "handoff.py")
TRANSCRIPT_FIXTURE = os.path.join(ROOT, "tests", "fixtures", "pickup-session.jsonl")
SKILLS = ["checklist", "checkpoint", "handoff-prompt", "improve-harness", "pickup", "setup", "slim-harness", "sweep", "wip"]
CLAUDE = shutil.which("claude")
needs_claude = pytest.mark.skipif(not CLAUDE, reason="the claude command is not installed")


def registrations(hooks_file=HOOKS_FILE):
    """(event, matcher, command) for every handler the plugin registers."""
    with open(hooks_file, encoding="utf-8") as handle:
        config = json.load(handle)
    rows = []
    for event, groups in config["hooks"].items():
        for group in groups:
            for handler in group["hooks"]:
                assert handler["type"] == "command"
                rows.append((event, group.get("matcher"), handler["command"]))
    return rows


@pytest.fixture
def home(tmp_path):
    """A home with nothing configured: no continuity, checklist, or tool settings."""
    path = tmp_path / "home"
    path.mkdir()
    (tmp_path / "tmp").mkdir()
    return path


def clean_env(home, **extra):
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("HANDOFF_", "CHECKLIST_", "CLAUDE_", "CODEX_", "PICKUP_", "XDG_"))
           and key != "CONTINUITY_CONFIG"}
    env.update(HOME=str(home), TMPDIR=str(home.parent / "tmp"), CLAUDE_CODE_ENTRYPOINT="cli",
               GIT_AUTHOR_NAME="Test", GIT_AUTHOR_EMAIL="test@example.com",
               GIT_COMMITTER_NAME="Test", GIT_COMMITTER_EMAIL="test@example.com",
               GIT_CONFIG_GLOBAL=os.devnull)
    env.update(extra)
    return env


def fire(event, payload, env, plugin_root=ROOT, hooks_file=HOOKS_FILE):
    """Run every handler registered for this event whose matcher accepts the payload."""
    target = payload.get("tool_name") if event in ("PreToolUse", "PostToolUse") else payload.get("source")
    outputs = []
    for registered, matcher, command in registrations(hooks_file):
        if registered != event or (matcher and not re.fullmatch(matcher, target or "")):
            continue
        result = subprocess.run(["bash", "-c", command], input=json.dumps(payload), text=True,
                                capture_output=True, env=dict(env, CLAUDE_PLUGIN_ROOT=plugin_root),
                                cwd=payload.get("cwd"))
        assert result.returncode == 0, (command, result.stderr)
        if result.stdout.strip():
            outputs.append(result.stdout.strip())
    return outputs


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, stdout=subprocess.PIPE, text=True).stdout.strip()


def new_repo(path):
    path.mkdir(parents=True)
    git(path, "init", "-q", "-b", "main")
    git(path, "commit", "-q", "--allow-empty", "-m", "init")
    return path.resolve()


def checkpoint(cwd, session_id, env, headline, plugin_root=ROOT):
    continuation = {"resume": {"headline": headline, "next_action": "Run the focused test",
                               "open_loops": []}, "spawned_processes": []}
    result = subprocess.run([sys.executable, os.path.join(plugin_root, "scripts", "lib", "handoff.py"),
                             "checkpoint", "--cwd", str(cwd), "--session-id", session_id],
                            input=json.dumps(continuation), text=True, capture_output=True, env=env)
    assert result.returncode == 0, result.stderr
    return subprocess.run([sys.executable, HANDOFF, "resolve", str(cwd), "--session-id", session_id],
                          text=True, capture_output=True, env=env, check=True).stdout.strip()


def base(event, session_id, cwd, home):
    return {"session_id": session_id, "cwd": str(cwd), "hook_event_name": event,
            "transcript_path": str(home / ".claude" / "projects" / "work" / f"{session_id}.jsonl")}


def bash_event(session_id, cwd, home, command, stdout=""):
    payload = base("PostToolUse", session_id, cwd, home)
    payload.update(permission_mode="default", tool_name="Bash", tool_use_id="toolu_test",
                   tool_input={"command": command, "description": "run it"},
                   tool_response={"stdout": stdout, "stderr": "", "interrupted": False,
                                  "isImage": False, "noOutputExpected": False})
    return payload


def write_event(session_id, cwd, home, path):
    payload = base("PostToolUse", session_id, cwd, home)
    payload.update(permission_mode="default", tool_name="Write", tool_use_id="toolu_write",
                   tool_input={"file_path": str(path), "content": "x"},
                   tool_response={"type": "create", "filePath": str(path), "content": "x"})
    return payload


def fill_context(transcript):
    """Append the recorded session's last assistant turn again, now reading 540,000 cached tokens."""
    with open(TRANSCRIPT_FIXTURE, encoding="utf-8") as handle:
        last = [json.loads(line) for line in handle if '"type":"assistant"' in line.replace(" ", "")][-1]
    last["message"]["usage"]["cache_read_input_tokens"] = 540_000
    with open(transcript, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(last) + "\n")


def context_of(output):
    return json.loads(output)["hookSpecificOutput"]["additionalContext"]


# ------------------------------------------------------------------ fixture isolation

def test_fixture_commits_have_a_test_identity(tmp_path):
    repo = new_repo(tmp_path / "work")
    assert git(repo, "log", "-1", "--format=%an <%ae>%n%cn <%ce>") == (
        "Test <test@example.com>\nTest <test@example.com>"
    )


def test_fixture_git_failure_exposes_gits_stderr(tmp_path, capfd):
    with pytest.raises(subprocess.CalledProcessError):
        git(tmp_path, "rev-parse", "--verify", "HEAD")
    assert "fatal:" in capfd.readouterr().err


# ------------------------------------------------------------------ registration

def test_six_hooks_on_the_five_moments():
    rows = registrations()
    assert len(rows) == 6
    assert sorted({event for event, _, _ in rows}) == [
        "PostToolUse", "PreCompact", "SessionStart", "Stop", "UserPromptSubmit"]
    assert sum(1 for event, _, _ in rows if event == "PostToolUse") == 2


def test_every_hook_command_runs_a_script_inside_the_plugin():
    for _, _, command in registrations():
        paths = re.findall(r'"\$\{CLAUDE_PLUGIN_ROOT\}/([^"]+)"', command)
        assert len(paths) == 1, command
        assert os.path.isfile(os.path.join(ROOT, paths[0])), command


def test_the_manifest_and_marketplace_name_the_same_plugin():
    with open(os.path.join(ROOT, ".claude-plugin", "plugin.json"), encoding="utf-8") as handle:
        manifest = json.load(handle)
    with open(os.path.join(ROOT, ".claude-plugin", "marketplace.json"), encoding="utf-8") as handle:
        marketplace = json.load(handle)
    assert manifest["name"] == "continuity"
    assert [(entry["name"], entry["source"]) for entry in marketplace["plugins"]] == [("continuity", "./")]
    assert sorted(os.listdir(os.path.join(ROOT, "skills"))) == SKILLS


@needs_claude
def test_claude_validates_the_plugin_and_its_marketplace_strictly():
    result = subprocess.run([CLAUDE, "plugin", "validate", "--strict", ROOT], capture_output=True, text=True,
                            stdin=subprocess.DEVNULL, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr


# ------------------------------------------------------------------ behavior with nothing configured

def test_a_checkpointed_session_is_offered_to_a_new_session_in_the_same_directory(tmp_path, home):
    env = clean_env(home)
    repo = new_repo(tmp_path / "work")
    path = checkpoint(repo, "session-one", env, "Left off at the parser")
    assert path.startswith(str(home / ".local" / "state" / "continuity" / "handoffs"))

    start = fire("SessionStart", dict(base("SessionStart", "session-two", repo, home), source="startup"), env)
    assert start and "1 handoff exists for this repository" in context_of(start[0])

    report = json.loads(subprocess.run(["bash", os.path.join(ROOT, "scripts", "pickup.sh"), "--no-commitments"],
                                       cwd=repo, capture_output=True, text=True, env=env).stdout)
    assert [(row["session_id"], row["headline"]) for row in report["candidates"]] == [
        ("session-one", "Left off at the parser")]


def test_a_session_that_compacts_gets_its_handoff_back(tmp_path, home):
    env = clean_env(home)
    repo = new_repo(tmp_path / "work")
    checkpoint(repo, "session-one", env, "Halfway through the migration")
    session = base("PreCompact", "session-one", repo, home)
    before = fire("PreCompact", dict(session, trigger="auto", custom_instructions=""), env)
    assert before and before[0].startswith("COMPACTION IMMINENT")
    after = fire("SessionStart", dict(base("SessionStart", "session-one", repo, home), source="compact"), env)
    assert after and "Halfway through the migration" in context_of(after[0])
    assert "Re-validate before acting" in context_of(after[0])


def test_a_new_session_hears_nothing_when_the_repository_has_no_handoff(tmp_path, home):
    env = clean_env(home)
    repo = new_repo(tmp_path / "work")
    assert fire("SessionStart", dict(base("SessionStart", "session-two", repo, home), source="startup"), env) == []


def test_the_startup_count_names_pickup_for_one_handoff_and_for_several(tmp_path, home):
    env = clean_env(home)
    repo = new_repo(tmp_path / "work")
    start = dict(base("SessionStart", "session-three", repo, home), source="startup")
    checkpoint(repo, "session-one", env, "First thread")
    assert [context_of(out) for out in fire("SessionStart", start, env)] == [
        "1 handoff exists for this repository; pickup lists it."]
    checkpoint(repo, "session-two", env, "Second thread")
    assert [context_of(out) for out in fire("SessionStart", start, env)] == [
        "2 handoffs exist for this repository; pickup lists them."]


def test_a_session_at_half_its_context_window_is_told_to_checkpoint(tmp_path, home):
    env = clean_env(home)
    repo = new_repo(tmp_path / "work")
    transcript = tmp_path / "session.jsonl"
    shutil.copy(TRANSCRIPT_FIXTURE, transcript)
    payload = dict(base("UserPromptSubmit", "session-one", repo, home), transcript_path=str(transcript),
                   permission_mode="default", prompt="carry on")
    # The recorded session peaked at 46% of the window: no warning yet.
    assert fire("UserPromptSubmit", payload, env) == []

    fill_context(transcript)
    warned = fire("UserPromptSubmit", payload, env)
    assert warned and warned[0].startswith("CONTEXT USAGE: 54% of context window")
    assert "handoff_checkpoint" in warned[0]
    assert warned[0].index("save durable progress to your record") < warned[0].index("handoff_checkpoint")


def test_a_session_that_stops_with_work_newer_than_its_handoff_is_told_it_is_stale(tmp_path, home):
    env = clean_env(home)
    repo = new_repo(tmp_path / "work")
    stop = dict(base("Stop", "session-one", repo, home), permission_mode="default", stop_hook_active=False)
    checkpoint(repo, "session-one", env, "Before the commit")
    fire("PostToolUse", write_event("session-one", repo, home, repo / "notes.txt"), env)
    assert fire("Stop", stop, env) == []

    (repo / "notes.txt").write_text("done\n")
    git(repo, "add", "notes.txt")
    git(repo, "commit", "-q", "-m", "notes")
    fire("PostToolUse", bash_event("session-one", repo, home, "git commit -m notes",
                                   "[main 1a2b3c4] notes\n 1 file changed"), env)
    blocked = fire("Stop", stop, env)
    assert blocked and json.loads(blocked[0])["decision"] == "block"
    assert "HANDOFF STALE" in json.loads(blocked[0])["reason"]


def test_a_dirty_file_newer_than_the_handoff_is_stale(tmp_path, home):
    env = clean_env(home)
    repo = new_repo(tmp_path / "work")
    checkpoint(repo, "session-one", env, "Before the edit")
    edited = repo / "draft.txt"
    edited.write_text("draft\n")
    future = os.path.getmtime(edited) + 5
    os.utime(edited, (future, future))
    fire("PostToolUse", write_event("session-one", repo, home, edited), env)
    stop = dict(base("Stop", "session-one", repo, home), permission_mode="default", stop_hook_active=False)
    blocked = fire("Stop", stop, env)
    assert blocked and json.loads(blocked[0])["decision"] == "block"



def test_an_interrupted_commit_call_is_not_owned(tmp_path, home):
    env = clean_env(home)
    repo = new_repo(tmp_path / "work")
    checkpoint(repo, "session-one", env, "Before the commit")
    fire("PostToolUse", write_event("session-one", repo, home, repo / "notes.txt"), env)
    git(repo, "commit", "-q", "--allow-empty", "-m", "moved by another process")
    interrupted = bash_event("session-one", repo, home, "git commit -m notes")
    interrupted["tool_response"]["interrupted"] = True
    fire("PostToolUse", interrupted, env)
    stop = dict(base("Stop", "session-one", repo, home), permission_mode="default", stop_hook_active=False)
    assert fire("Stop", stop, env) == []

@pytest.mark.parametrize("command, stdout, signal", [
    ("git commit -m notes", "[main 1a2b3c4] notes\n 1 file changed", "git commit"),
    ("git push origin main", "", "git push"),
    ("python3 -m pytest -q", "....\n4 passed in 0.12s\n", "passing tests"),
])
def test_completion_signals_remind_once_to_run_the_plugin_checklist(tmp_path, home, command, stdout, signal):
    env = clean_env(home)
    repo = new_repo(tmp_path / "work")
    first = fire("PostToolUse", bash_event("session-one", repo, home, command, stdout), env)
    reminders = [context_of(out) for out in first if "hookSpecificOutput" in out]
    assert len(reminders) == 1
    assert reminders[0].startswith(signal) and "run /continuity:checklist before moving on" in reminders[0]
    again = fire("PostToolUse", bash_event("session-one", repo, home, command, stdout), env)
    assert [out for out in again if "hookSpecificOutput" in out] == []


def test_a_failing_test_run_gets_no_reminder(tmp_path, home):
    env = clean_env(home)
    repo = new_repo(tmp_path / "work")
    out = fire("PostToolUse", bash_event("session-one", repo, home, "python3 -m pytest -q",
                                         "..F\n1 failed, 2 passed in 0.12s\n"), env)
    assert out == []


def test_a_subagent_gets_no_hook_output(tmp_path, home):
    env = clean_env(home)
    repo = new_repo(tmp_path / "work")
    checkpoint(repo, "session-one", env, "Parent work")
    start = dict(base("SessionStart", "session-one", repo, home), source="compact", agent_id="agent-1")
    assert fire("SessionStart", start, env) == []
    commit = dict(bash_event("session-one", repo, home, "git commit -m x", "[main 1] x"), agent_id="agent-1")
    assert fire("PostToolUse", commit, env) == []


@pytest.mark.parametrize(("entrypoint", "agent_id"), [("sdk-cli", None), ("cli", "agent-1")],
                         ids=["headless-worker", "subagent"])
def test_pre_compact_context_guard_and_ledger_stay_silent_outside_an_interactive_session(
        tmp_path, home, entrypoint, agent_id):
    env = clean_env(home)
    repo = new_repo(tmp_path / "work")
    checkpoint(repo, "session-one", env, "Parent work")
    transcript = tmp_path / "session.jsonl"
    shutil.copy(TRANSCRIPT_FIXTURE, transcript)
    fill_context(transcript)
    events = [
        ("PreCompact", dict(base("PreCompact", "session-one", repo, home), trigger="auto", custom_instructions="")),
        ("UserPromptSubmit", dict(base("UserPromptSubmit", "session-one", repo, home), transcript_path=str(transcript),
                                  permission_mode="default", prompt="carry on")),
        ("PostToolUse", write_event("session-one", repo, home, repo / "notes.txt")),
    ]
    # The interactive session hears the two warnings, so silence below is the gate.
    assert [event for event, payload in events if fire(event, payload, env)] == ["PreCompact", "UserPromptSubmit"]
    gated = clean_env(home, CLAUDE_CODE_ENTRYPOINT=entrypoint)
    for event, payload in events:
        if agent_id:
            payload = dict(payload, agent_id=agent_id)
        assert fire(event, payload, gated) == [], event


def test_a_subagent_edit_is_recorded_in_the_parent_sessions_ledger(tmp_path, home):
    env = clean_env(home)
    repo = new_repo(tmp_path / "work")
    edited = repo / "subagent-edit.txt"
    assert fire("PostToolUse", dict(write_event("session-one", repo, home, edited), agent_id="agent-1"), env) == []
    ledger = home / ".local" / "state" / "continuity" / "session-touched-paths.session-one.jsonl"
    rows = [json.loads(line) for line in ledger.read_text().splitlines()]
    assert {"kind": "file", "path": str(edited), "checkout": str(repo), "session_id": "session-one"}.items() <= next(
        row for row in rows if row.get("kind") == "file").items()


# ------------------------------------------------------------------ resume

def test_resume_lists_this_directory_newest_first_and_marks_siblings(tmp_path, home):
    env = clean_env(home)
    repo = new_repo(tmp_path / "work")
    sibling = tmp_path / "work-sibling"
    git(repo, "worktree", "add", "-q", "-b", "sibling", str(sibling), "main")
    checkpoint(repo, "older", env, "Older here")
    checkpoint(sibling, "beside", env, "In the sibling")
    time.sleep(1.1)  # handoffs record their write time to the second
    checkpoint(repo, "newer", env, "Newer here")

    result = subprocess.run(["bash", os.path.join(ROOT, "scripts", "pickup.sh"), "--no-commitments"],
                            cwd=repo, capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    rows = [(row["session_id"], row["group"]) for row in json.loads(result.stdout)["candidates"]]
    assert rows == [("newer", "this_directory"), ("older", "this_directory"), ("beside", "sibling_worktrees")]


def test_resume_without_a_handoff_falls_back_to_the_tools_session_history(tmp_path, home):
    env = clean_env(home)
    repo = new_repo(tmp_path / "work")
    project = home / ".claude" / "projects" / str(repo).replace("/", "-").replace(".", "-")
    project.mkdir(parents=True)
    shutil.copy(TRANSCRIPT_FIXTURE, project / "earlier-session.jsonl")
    result = subprocess.run(["bash", os.path.join(ROOT, "scripts", "pickup.sh"), "--no-commitments"],
                            cwd=repo, capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["source"] == "transcript_fallback"
    assert "No handoff was found" in report["notice"]


# ------------------------------------------------------------------ install and uninstall

def claude_cli(home, *args):
    result = subprocess.run([CLAUDE, "plugin", *args], cwd=str(home), capture_output=True, text=True,
                            stdin=subprocess.DEVNULL, env=clean_env(home), timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


@pytest.fixture
def installed(tmp_path, home):
    """Install from a clean copy of the tracked tree, the files a clone delivers."""
    source = tmp_path / "source"
    source.mkdir()
    archive = subprocess.run(["git", "-C", ROOT, "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                             capture_output=True, check=True).stdout.split(b"\0")
    for name in filter(None, (item.decode() for item in archive)):
        if not os.path.exists(os.path.join(ROOT, name)):
            continue
        os.makedirs(source / os.path.dirname(name), exist_ok=True)
        shutil.copy2(os.path.join(ROOT, name), source / name)
    out = json.loads(claude_cli(home, "install", "continuity", "--marketplace", str(source), "--json"))
    assert out["outcome"] == "ok", out
    plugins = json.loads(claude_cli(home, "list", "--json"))
    (entry,) = [row for row in plugins if row["id"] == "continuity@continuity"]
    assert entry["enabled"] is True
    return entry["installPath"]


@needs_claude
def test_one_install_adds_the_six_skills_and_six_hooks(home, installed):
    details = claude_cli(home, "details", "continuity")
    assert "Skills (9)  " + ", ".join(SKILLS) in details
    assert "Hooks (5)  SessionStart, PreCompact, UserPromptSubmit, PostToolUse, Stop" in details
    assert len(registrations(os.path.join(installed, "hooks", "hooks.json"))) == 6


@needs_claude
def test_the_installed_hooks_restore_a_handoff_after_compaction(tmp_path, home, installed):
    env = clean_env(home)
    repo = new_repo(tmp_path / "work")
    checkpoint(repo, "session-one", env, "Written through the installed plugin", plugin_root=installed)
    after = fire("SessionStart", dict(base("SessionStart", "session-one", repo, home), source="compact"), env,
                 plugin_root=installed, hooks_file=os.path.join(installed, "hooks", "hooks.json"))
    assert after and "Written through the installed plugin" in context_of(after[0])


@needs_claude
def test_uninstalling_leaves_every_handoff_in_place(tmp_path, home, installed):
    env = clean_env(home)
    repo = new_repo(tmp_path / "work")
    path = checkpoint(repo, "session-one", env, "Survives the uninstall", plugin_root=installed)
    data_dir = home / ".claude" / "plugins" / "data" / "continuity-continuity"
    data_dir.mkdir(parents=True, exist_ok=True)

    out = json.loads(claude_cli(home, "uninstall", "continuity@continuity", "--json"))
    assert out["outcome"] == "ok" and out["keptData"] is False, out
    assert not data_dir.exists()
    assert "continuity@continuity" not in claude_cli(home, "list", "--json")
    with open(path, encoding="utf-8") as handle:
        assert json.load(handle)["resume"]["headline"] == "Survives the uninstall"
