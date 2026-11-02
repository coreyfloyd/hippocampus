"""#910 — pickup.py (skills/pickup/scripts/).

Two kinds of fixture, deliberately:

- tests/fixtures/pickup-session.jsonl — a REDACTED COPY of a real
  transcript (see tests/fixtures/redact_pickup_transcript.py for what
  was stripped and why). It keeps the record structure and no command,
  tool output, or thinking text, so assertions about commands and results
  (ticket operations, scraped paths) build their rows with
  ``_bash_call``, which clones a real tool_use/tool_result pair from the
  fixture and sets only the command and result text.
- a handful of small in-memory row dicts, used ONLY to reach edge-case
  branches the real session never hits (no stop_reason=="end_turn" row at
  all; a user row carrying a tool_result). These are minimal pure-function
  probes of a documented row SHAPE (see the docstrings on the functions
  under test), not a fabricated transcript standing in for a real one.

#910 eval round 1 reworked this suite for:
- F1: build_report() returns a single dict now (render_text/the report+extra
  dual shape are gone) — every call site here updated.
- F2: files_for_repo() no longer returns `reconciled`; assertions check
  membership in the three source lists directly.
- F4: commits_source / unresolved_branches, so a branch whose contribution
  could not be resolved is distinguishable from one that touched nothing.
- F6: an unreadable worktree (status_short() returning None) must classify
  as "unknown", not silently fall through to "merged".
- F7: the A1 test now uses a fixture where the last end_turn row is NOT the
  last row with any text, so it can actually fail if A1 regresses to
  "last row with any text" — asserted directly against the OLD algorithm's
  own answer, not against a description of it.
- F9: PICKUP_TRUNK env override, so a master/trunk/develop repo is not
  silently misclassified.

Run with: uv run --with pytest pytest tests/test_pickup.py -q
"""
import copy
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE_DIR = os.path.join(HERE, "..", "skills", "pickup", "scripts")
sys.path.insert(0, ENGINE_DIR)
import pickup as rw  # noqa: E402

FIXTURE = os.path.join(HERE, "fixtures", "pickup-session.jsonl")
ROOT = os.path.dirname(HERE)
HANDOFF_LIB = os.path.join(ROOT, "scripts", "lib", "handoff.sh")
HANDOFF_LINT = os.path.join(ROOT, "scripts", "lint-handoff.sh")


@pytest.fixture(autouse=True)
def sandboxed_codex_home(tmp_path, monkeypatch):
    """The wrapper reads ${CODEX_HOME:-$HOME/.codex} (#1453). Subprocess
    tests copy os.environ, so a run under Codex would otherwise hand the
    engine the live rollout store."""
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))


@pytest.fixture(scope="module")
def rows():
    return rw.load(FIXTURE)


def _bash_call(rows, call_id, command, result=""):
    """A Bash tool_use row and its paired tool_result row, cloned from the
    fixture's first real pair with only the id, command, and result text set."""
    use = next(r for r in rows if r.get("type") == "assistant" and rw.tool_use_blocks(r)
               and rw.tool_use_blocks(r)[0].get("name") == "Bash")
    use = copy.deepcopy(use)
    block = rw.tool_use_blocks(use)[0]
    use["message"]["content"] = [block]
    block["id"] = call_id
    block["input"] = {"command": command}
    paired = next(r for r in rows if r.get("type") == "user" and rw.has_tool_result(r))
    answer = copy.deepcopy(paired)
    part = next(p for p in answer["message"]["content"] if p.get("type") == "tool_result")
    answer["message"]["content"] = [part]
    part["tool_use_id"] = call_id
    part["content"] = result
    return [use, answer]


@pytest.fixture(scope="module")
def users(rows):
    return [r for r in rows if r.get("type") == "user" and rw.real(r)]


@pytest.fixture(scope="module")
def asst(rows):
    return [r for r in rows if r.get("type") == "assistant" and rw.real(r)]


# ================================================================== A1-A4 message capture

def test_fixture_loads_and_is_the_expected_shape(rows):
    assert len(rows) == 699
    assert any(r.get("type") == "assistant" for r in rows)
    assert any(r.get("type") == "user" for r in rows)


def test_a2_first_user_message_is_uncapped_and_not_noise(users):
    fu, ts = rw.first_user_message(users)
    assert fu == "[REDACTED TEXT #1]"
    assert ts == "2026-09-02T03:17:06.948Z"


def test_a3_last_user_message_is_uncapped(users):
    lu, ts = rw.last_user_message(users)
    assert lu == "[REDACTED TEXT #104]"
    assert ts == "2026-09-02T07:55:04.291Z"


def test_a1_last_assistant_selected_by_end_turn_on_real_session(rows, asst):
    la, ts = rw.last_assistant_message(asst)
    assert la == "[REDACTED TEXT #106]"
    picked = next(r for r in rows if r.get("type") == "assistant" and r.get("timestamp") == ts)
    assert rw.stop_reason(picked) == "end_turn"
    assert rw.real(picked)


def _last_any_text(seq):
    """The OLD selector A1 replaced: the last row with any text at all,
    regardless of stop_reason. Reimplemented here (not imported) so the
    regression test below compares two independently-expressed algorithms,
    not one algorithm against a restated copy of itself."""
    for r in reversed(seq):
        t = rw.text(r).strip()
        if t:
            return t, r.get("timestamp")
    return "", None


def test_a1_picks_the_end_turn_sign_off_not_the_last_texty_row():
    """#910's own bug report: the OLD logic (last row with any text) picks a
    mid-work narration turn, not the sign-off. This fixture's last row with
    ANY text is a tool_use caption (stop_reason "tool_use"); the actual
    sign-off is the end_turn row two turns earlier. Directly proves the two
    algorithms disagree on this input — F7: the old test's fixture had them
    coincide, so it could not fail if A1 were reverted; this one can."""
    synthetic = [
        {"type": "assistant", "isMeta": False, "isSidechain": False, "timestamp": "t1",
         "message": {"content": [{"type": "text", "text": "Done for the night — #123 merged."}],
                     "stop_reason": "end_turn"}},
        {"type": "assistant", "isMeta": False, "isSidechain": False, "timestamp": "t2",
         "message": {"content": [{"type": "text", "text": "Checking one more thing first..."},
                                  {"type": "tool_use", "id": "1", "name": "Bash",
                                   "input": {"command": "git status"}}],
                     "stop_reason": "tool_use"}},
    ]
    old_answer = _last_any_text(synthetic)
    new_answer = rw.last_assistant_message(synthetic)
    assert old_answer == ("Checking one more thing first...", "t2")
    assert new_answer == ("Done for the night — #123 merged.", "t1")
    assert new_answer != old_answer


def test_a1_falls_back_when_no_end_turn_row_exists():
    """Edge case the real session never exercises (its last turn IS an
    end_turn) — a session interrupted mid-response can end on stop_reason
    None/max_tokens. A1 must still report that as the honest stopping
    point rather than silently returning nothing."""
    synthetic = [
        {"type": "assistant", "isMeta": False, "isSidechain": False,
         "timestamp": "t1",
         "message": {"content": [{"type": "text", "text": "still working"}],
                     "stop_reason": "tool_use"}},
        {"type": "assistant", "isMeta": False, "isSidechain": False,
         "timestamp": "t2",
         "message": {"content": [{"type": "text", "text": "cut off mid-thought"}],
                     "stop_reason": None}},
    ]
    la, ts = rw.last_assistant_message(synthetic)
    assert la == "cut off mid-thought"
    assert ts == "t2"


def test_a4_excludes_tool_result_carrying_user_rows():
    """A4: a synthetic user row carrying a tool_result must never be picked
    as a real user message, even if it also carries a text part."""
    synthetic = [
        {"type": "user", "isMeta": False, "isSidechain": False, "timestamp": "t1",
         "message": {"content": [
             {"type": "tool_result", "tool_use_id": "x", "content": "ok"},
             {"type": "text", "text": "not really Alex typing"},
         ]}},
        {"type": "user", "isMeta": False, "isSidechain": False, "timestamp": "t2",
         "message": {"content": "actually typed this"}},
    ]
    assert rw.has_tool_result(synthetic[0]) is True
    assert rw.has_tool_result(synthetic[1]) is False
    fu, ts = rw.first_user_message(synthetic)
    assert fu == "actually typed this"
    assert ts == "t2"


# ================================================================== A7 — staleness

def test_a7_staleness_zero_when_last_end_turn_is_the_last_thing(rows):
    st = rw.staleness(rows)
    assert st["last_end_turn_ts"] == "2026-09-02T07:57:24.241Z"
    assert st["tool_calls_after"] == 0
    assert st["stale"] is False


def test_a7_staleness_fires_when_tool_calls_follow_the_last_end_turn():
    synthetic = [
        {"type": "assistant", "isMeta": False, "isSidechain": False, "timestamp": "t1",
         "message": {"content": [{"type": "text", "text": "done for the night"}],
                     "stop_reason": "end_turn"}},
        {"type": "assistant", "isMeta": False, "isSidechain": False, "timestamp": "t2",
         "message": {"content": [{"type": "tool_use", "id": "1", "name": "Bash",
                                   "input": {"command": "echo still running"}}],
                     "stop_reason": "tool_use"}},
    ]
    st = rw.staleness(synthetic)
    assert st["stale"] is True
    assert st["tool_calls_after"] == 1
    assert st["last_end_turn_ts"] == "t1"


# ================================================================== A6 — transcript-scraped paths

def test_a6_extracts_paths_from_bypass_mode_bash_commands_not_just_tool_names(rows):
    """#910's own finding: bypass mode routes edits through Bash (heredocs,
    sed, python3 -c), so tool-name extraction (Write/Edit/Read file_path)
    alone misses most real paths — this asserts the Bash-command regex path
    actually contributes paths beyond what file_path fields alone would."""
    calls = _bash_call(rows, "p1", "cat > /Users/alex/Development/example-config/docs/note.md <<EOF\nx\nEOF")
    calls += _bash_call(rows, "p2", "sed -i.bak s/a/b/ /Users/alex/Development/example-config/src/app.py")
    paths = rw.extract_transcript_paths(calls)
    assert "/Users/alex/Development/example-config/docs/note.md" in paths
    assert "/Users/alex/Development/example-config/src/app.py" in paths
    # the fixture's own file_path inputs are numbered placeholders under /redacted
    assert rw.extract_transcript_paths(rows)
    assert all(p.startswith("/redacted/") for p in rw.extract_transcript_paths(rows))


# ================================================================== F6 — unreadable worktree

def test_f6_unreadable_worktree_classifies_as_unknown_not_merged():
    """#910 eval F6: status_short() returning None ("could not read", a git
    error on an existing worktree) must not fall through as falsy into
    "not dirty" and land on merged/clean_unmerged — the one classification
    path whose purpose is to raise an alarm must fail TOWARD the alarm."""
    cwd_status = {"/fake/worktree": {"exists": True, "dirty": None, "branch": "feat"}}
    path_by_branch = {"feat": "/fake/worktree"}
    rep = rw.branch_state("/irrelevant", "feat", {}, path_by_branch, cwd_status, [], "main")
    assert rep["state"] == "unknown"
    assert rw.ALARM_RANK["unknown"] <= rw.ALARM_RANK["dirty"]


def test_f6_missing_worktree_is_not_unknown():
    """A branch with NO worktree at all (dirty=None because there is
    nothing to read, not because reading it failed) must not be confused
    with the unreadable-worktree case."""
    rep = rw.branch_state("/irrelevant", "feat", {}, {}, {}, [], "main")
    assert rep["state"] != "unknown"


def test_f5r2_gone_session_repo_cwd_is_marked_not_silently_cascaded(tmp_path):
    """#910 eval round 2 F5: a session whose LAST cwd no longer exists on
    disk makes every git call fail, cascading every branch to
    deleted_no_merge (the highest alarm) with nothing saying git itself was
    unreadable. session_repo_readable distinguishes that from a real,
    resolved all-red report."""
    gone = str(tmp_path / "this-directory-does-not-exist")
    rows = [
        {"type": "assistant", "isMeta": False, "isSidechain": False, "timestamp": "t1",
         "cwd": gone, "gitBranch": "feature",
         "message": {"content": [{"type": "text", "text": "working"}],
                     "stop_reason": "end_turn"}},
    ]
    fixture_path = tmp_path / "session.jsonl"
    fixture_path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")

    report = rw.build_report([str(fixture_path)])
    assert report["session_repo_cwd"] == gone
    assert report["session_repo_readable"] is False


def test_f5r2_readable_session_repo_cwd_is_marked_true(merged_repo, tmp_path):
    rows = [
        {"type": "assistant", "isMeta": False, "isSidechain": False, "timestamp": "t1",
         "cwd": merged_repo, "gitBranch": "main",
         "message": {"content": [{"type": "text", "text": "working"}],
                     "stop_reason": "end_turn"}},
    ]
    fixture_file = tmp_path / "session2.jsonl"
    fixture_file.write_text("\n".join(json.dumps(r) for r in rows) + "\n")

    report = rw.build_report([str(fixture_file)])
    assert report["session_repo_readable"] is True


# ================================================================== A5b / A6 — git-backed (hermetic fixture repo)

def _git(repo, *args):
    subprocess.run(["git", "-C", repo] + list(args), check=True,
                    capture_output=True, text=True)


@pytest.fixture
def merged_repo(tmp_path):
    """A minimal repo with one branch merged --no-ff into main, then its
    worktree AND branch removed — exactly the "merged, ref gone" shape
    #909's find_merge()/state=="landed" already classifies. #910 adds: can
    branch_commits/files_for_repo recover the branch's OWN commit subjects
    and files via that same merge commit, for a branch whose LOCAL REF
    STILL EXISTS post-merge (main..branch is empty in that case — the
    direct log approach reports nothing, which is the gap #910 must
    close)."""
    repo = str(tmp_path / "repo")
    subprocess.run(["git", "init", "-q", "-b", "main", repo], check=True)
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "init")
    _git(repo, "checkout", "-q", "-b", "feature")
    (tmp_path / "repo" / "feature.txt").write_text("hello\n")
    _git(repo, "add", "feature.txt")
    _git(repo, "commit", "-q", "-m", "add feature.txt")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--no-ff", "feature", "-m", "merge: #123 feature landed")
    return repo


def test_a5b_branch_commits_falls_back_to_merge_evidence_when_already_merged(merged_repo):
    merge_log_rows = rw.merge_log(merged_repo, "main")
    rep = {"branch": "feature", "ref": "local", "on_main": True, "merge_evidence": None}
    commits, source = rw.branch_commits(merged_repo, rep, merge_log_rows, "main")
    assert source == "merge_evidence"
    assert len(commits) == 1
    assert "#123 feature landed" in commits[0]


def test_f4_unresolved_when_merged_branch_has_no_findable_merge_commit(merged_repo):
    """#910 eval F4: a branch that IS merged (ref present, on_main True) but
    whose merge commit cannot be found by name (a squash-merge or a merge
    subject that never named the branch) must be marked "unresolved", not
    silently reported identically to a branch that changed nothing."""
    rep = {"branch": "no-such-branch-name-in-any-merge-subject",
           "ref": "local", "on_main": True, "merge_evidence": None}
    commits, source = rw.branch_commits(merged_repo, rep, [], "main")
    assert commits == []
    assert source == "unresolved"


def test_a5b_unmerged_branch_with_genuinely_zero_commits_is_not_unresolved(merged_repo):
    """The direct trunk..branch range IS authoritative for an unmerged
    branch — an empty range there is a TRUE empty (e.g. a branch that only
    has uncommitted work), not an unresolved unknown."""
    _git(merged_repo, "branch", "empty-branch", "main")
    rep = {"branch": "empty-branch", "ref": "local", "on_main": False, "merge_evidence": None}
    commits, source = rw.branch_commits(merged_repo, rep, [], "main")
    assert commits == []
    assert source == "direct"


def test_a6_files_for_repo_finds_merged_branch_files_via_merge_diff(merged_repo):
    merge_log_rows = rw.merge_log(merged_repo, "main")
    rep = {"branch": "feature", "ref": "local", "on_main": True, "merge_evidence": None,
           "worktree_path": None}
    result = rw.files_for_repo(merged_repo, [merged_repo], [rep], set(), merge_log_rows, "main", [])
    assert "feature.txt" in result["committed"]
    assert result["unresolved_branches"] == []


def test_a6_files_for_repo_names_unresolved_branches(merged_repo):
    """#910 eval F4/F2: files_for_repo no longer returns a `reconciled`
    per-path map (dropped — pure restatement of the three sibling lists,
    measured at 48% of the entire JSON payload); the file list is instead
    self-describing via `unresolved_branches`."""
    result = rw.files_for_repo(merged_repo, [merged_repo], [], set(), [], "main",
                                ["some-branch"])
    assert result["unresolved_branches"] == ["some-branch"]
    assert "reconciled" not in result


def test_a6_files_for_repo_reconciles_uncommitted_and_transcript_scraped_paths(tmp_path):
    repo = str(tmp_path / "repo2")
    subprocess.run(["git", "init", "-q", "-b", "main", repo], check=True)
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "init")
    (tmp_path / "repo2" / "dirty.md").write_text("uncommitted\n")

    scraped = {os.path.join(repo, "dirty.md"), os.path.join(repo, "referenced-only.md")}
    result = rw.files_for_repo(repo, [repo], [], scraped, [], "main", [])
    assert "dirty.md" in result["uncommitted"]
    assert "referenced-only.md" in result["transcript_scraped"]
    # dirty.md is named by BOTH sources -- reconciliation is verifiable by
    # simple membership across the two lists, without a redundant per-path map.
    assert "dirty.md" in result["uncommitted"] and "dirty.md" in result["transcript_scraped"]


# ================================================================== F9 — trunk is not hardcoded

def test_f9_trunk_is_env_overridable(tmp_path, monkeypatch):
    """#910 eval F9: six new call sites hardcoded "main". A repo whose trunk
    is "trunk" must not silently classify every branch as unmerged."""
    repo = str(tmp_path / "repo")
    subprocess.run(["git", "init", "-q", "-b", "trunk", repo], check=True)
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "init")
    _git(repo, "checkout", "-q", "-b", "feature")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "feature work")
    _git(repo, "checkout", "-q", "trunk")
    _git(repo, "merge", "-q", "--ff-only", "feature")

    monkeypatch.setenv("PICKUP_TRUNK", "trunk")
    assert rw.default_trunk() == "trunk"

    rep = rw.branch_state(repo, "feature", {}, {}, {}, [], "trunk")
    assert rep["on_main"] is True
    assert rep["state"] == "merged"


def test_f9_default_trunk_is_main_without_override_or_repo(monkeypatch):
    monkeypatch.delenv("PICKUP_TRUNK", raising=False)
    assert rw.default_trunk() == "main"


def test_f9_auto_detects_trunk_via_origin_head_when_unset(tmp_path, monkeypatch):
    """#910 eval round 2 correction: round 1's docstring rejected
    auto-detection as equivalent to guessing among main/master/trunk/develop.
    `git symbolic-ref refs/remotes/origin/HEAD` is deterministic, not a
    guess — it names the one branch the remote itself designates default.
    A bare remote (no actual push target) still lets `git remote set-head`
    configure this ref, so no real remote server is needed to test it."""
    monkeypatch.delenv("PICKUP_TRUNK", raising=False)
    bare = str(tmp_path / "bare.git")
    subprocess.run(["git", "init", "-q", "--bare", "-b", "trunk", bare], check=True)
    repo = str(tmp_path / "repo")
    subprocess.run(["git", "clone", "-q", bare, repo], check=True,
                    capture_output=True)
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "init")
    _git(repo, "push", "-q", "origin", "trunk")
    _git(repo, "remote", "set-head", "origin", "trunk")

    assert rw.default_trunk(repo) == "trunk"


def test_f9_env_override_wins_over_origin_head(tmp_path, monkeypatch):
    bare = str(tmp_path / "bare.git")
    subprocess.run(["git", "init", "-q", "--bare", "-b", "trunk", bare], check=True)
    repo = str(tmp_path / "repo")
    subprocess.run(["git", "clone", "-q", bare, repo], check=True,
                    capture_output=True)
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "init")
    _git(repo, "push", "-q", "origin", "trunk")
    _git(repo, "remote", "set-head", "origin", "trunk")

    monkeypatch.setenv("PICKUP_TRUNK", "some-other-name")
    assert rw.default_trunk(repo) == "some-other-name"


# ================================================================== F1 round 2 — repo attribution when the session ends in a worktree

def test_f1r2_committed_files_survive_a_session_ending_in_a_worktree(tmp_path):
    """#910 eval round 2, decisive finding: build_report's repo-attribution
    predicate compared a repo ROOT to the session's last CWD
    (`root == session_repo_cwd`), true only when the session happened to
    end AT the repo root — reproduced on a real transcript whose last cwd
    was a worktree, where 15 resolvable files from a found merge commit
    were silently dropped with no marker (round 1's F4 defect class one
    layer up). The fix compares against repo_root_for(session_repo_cwd)
    instead, since every branch in branch_reports is resolved against that
    ONE repo regardless of which of its worktrees the session ended in.

    Deliberately hermetic (a constructed repo + constructed rows), NOT the
    real committed fixture whose rows carry the live checkout's path — the
    same eval round separately requires the a8 tests below to STOP taking
    the live checkout as an input (F7); reusing it here would add an eighth
    such test while claiming to fix the seventh."""
    repo = str(tmp_path / "repo")
    subprocess.run(["git", "init", "-q", "-b", "main", repo], check=True)
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "init")
    _git(repo, "checkout", "-q", "-b", "feature")
    (tmp_path / "repo" / "feature.txt").write_text("hello\n")
    _git(repo, "add", "feature.txt")
    _git(repo, "commit", "-q", "-m", "add feature.txt")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--no-ff", "feature", "-m", "merge: #123 feature landed")
    # a real worktree of the SAME repo -- this is the shape that broke:
    # the session's LAST recorded cwd is a worktree, not the repo root.
    # main is already checked out in the primary working dir, so the
    # worktree needs its own branch (git refuses to check out a branch
    # that's already checked out elsewhere).
    worktree = str(tmp_path / "repo" / ".worktrees" / "wt1")
    _git(repo, "worktree", "add", "-q", "-b", "wt1-branch", worktree, "main")

    def _row(cwd, branch, ts):
        return {"type": "assistant", "isMeta": False, "isSidechain": False,
                "timestamp": ts, "cwd": cwd, "gitBranch": branch,
                "message": {"content": [{"type": "text", "text": "working"}],
                            "stop_reason": "end_turn"}}

    rows = [
        _row(repo, "main", "t1"),
        _row(repo, "feature", "t2"),
        _row(worktree, "wt1-branch", "t3"),  # session ends in a worktree, not the root
    ]
    fixture_path = tmp_path / "session.jsonl"
    fixture_path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")

    report = rw.build_report([str(fixture_path)])
    fr = report["files_by_repo"][repo]
    assert "feature.txt" in fr["committed"], (
        "committed files silently vanished for a session whose last cwd was a worktree: %r" % fr
    )
    b = next(b for b in report["branches"] if b["branch"] == "feature")
    assert b["branch"] not in fr["unresolved_branches"]


# ================================================================== A8 — JSON v2, additive

V1_KEYS = {"session", "messages", "first_ts", "last_ts", "first_user", "last_user",
           "last_assistant", "git", "branches"}
V1_GIT_KEYS = {"branch", "head", "exists", "on_main", "unmerged", "ahead_behind"}


@pytest.fixture
def stub_git(monkeypatch):
    """#910 eval round 2 F7: build_report() on the committed fixture (whose
    rows carry cwd: /Users/alex/Development/example-config) was making
    all 44 of its git invocations against the developer's LIVE checkout,
    with no seam to redirect them — a hidden test input even though no
    assertion depended on the result. Stubs every git-calling primitive so
    the a8 tests below exercise the transcript/JSON-shape logic they
    actually assert on without touching the filesystem's real git state."""
    monkeypatch.setattr(rw, "git", lambda cwd, *a: "")
    monkeypatch.setattr(rw, "git_ok", lambda cwd, *a: False)
    monkeypatch.setattr(rw, "status_short", lambda path: None)
    monkeypatch.setattr(rw, "worktree_map", lambda cwd: {})
    monkeypatch.setattr(rw, "repo_root_for", lambda cwd: None)


@pytest.fixture
def no_git_env(tmp_path):
    """Same seam as stub_git, for the subprocess/CLI tests below: a PATH
    whose only `git` always fails, so the CLI invocation cannot reach the
    live checkout either. pickup.py's git()/git_ok() already degrade
    gracefully on a failing git call (that is the whole point of #909's
    fail-toward-the-alarm design), so this exercises real failure-handling
    rather than bypassing it."""
    stub_dir = tmp_path / "no-git-bin"
    stub_dir.mkdir()
    stub = stub_dir / "git"
    stub.write_text("#!/bin/sh\nexit 1\n")
    stub.chmod(0o755)
    return {"PATH": str(stub_dir) + os.pathsep + "/usr/bin:/bin"}


def test_a8_build_report_returns_a_single_dict_not_a_pair(stub_git):
    """#910 eval F1/Architecture: build_report() used to return (report,
    extra) — two overlapping shapes for one record, existing only to feed
    the now-removed text renderer. It returns one dict."""
    report = rw.build_report([FIXTURE])
    assert isinstance(report, dict)


def test_a8_json_v2_preserves_every_v1_key(stub_git):
    report = rw.build_report([FIXTURE])
    assert report["version"] == 2
    assert V1_KEYS.issubset(report.keys())
    assert V1_GIT_KEYS.issubset(report["git"].keys())
    # additive-only: nothing from v1 was removed or renamed
    assert report["session"] == "pickup-session"
    assert isinstance(report["branches"], list)
    for b in report["branches"]:
        # #909's original branch-report keys, still all present
        assert {"branch", "worktree_path", "worktree_exists", "dirty", "ref",
                "on_main", "merge_evidence", "state"}.issubset(b.keys())
    # #910 additions are present and are new keys, not replacements
    for key in ("files_by_repo", "staleness"):
        assert key in report


def test_a8_error_shape_is_always_an_object_never_an_array():
    """#910 eval F1 (shape hole): a caller must never see a shape that
    depends on whether a transcript was found."""
    report = rw.build_report(["/no/such/file.jsonl"])
    assert isinstance(report, dict)
    assert report["version"] == 2
    assert report["error"] == "no_substantive_transcript"


def test_a8_json_is_well_formed_via_cli(no_git_env):
    out = subprocess.run(
        [sys.executable, os.path.join(ENGINE_DIR, "pickup.py"),
         FIXTURE],
        capture_output=True, text=True, env=no_git_env,
    )
    assert out.returncode == 0, out.stderr
    parsed = json.loads(out.stdout)
    assert parsed["version"] == 2
    assert isinstance(parsed, dict)


def test_a8_json_flag_is_accepted_as_a_no_op_for_backward_compatibility(no_git_env):
    out = subprocess.run(
        [sys.executable, os.path.join(ENGINE_DIR, "pickup.py"),
         "--json", FIXTURE],
        capture_output=True, text=True, env=no_git_env,
    )
    assert out.returncode == 0, out.stderr
    parsed = json.loads(out.stdout)
    assert parsed["version"] == 2


def test_main_reports_usage_error_on_missing_flag_value_instead_of_crashing():
    """Cross-Seam Contract Fidelity nitpick from #910 eval round 1: main()'s
    argv parser indexed argv[i+1] with no bounds check, so a trailing flag
    raised IndexError rather than a legible usage error."""
    out = subprocess.run(
        [sys.executable, os.path.join(ENGINE_DIR, "pickup.py"), "--sid-out"],
        capture_output=True, text=True,
    )
    assert out.returncode == 2
    parsed = json.loads(out.stdout)
    assert parsed["error"] == "usage"


# ================================================================== handoff-first resume (#1024)

def _write_handoff(path, payload):
    """Use T1's real atomic writer, then lint the real v2 fixture.

    Candidate discovery must consume the same files that hooks and skills
    write, rather than a hand-invented near-schema dictionary.
    """
    encoded = json.dumps(payload)
    writer = subprocess.run(
        ["bash", "-c", '. "$1"; printf %s "$2" | handoff_atomic_write "$3"',
         "bash", HANDOFF_LIB, encoded, str(path)],
        capture_output=True, text=True,
    )
    assert writer.returncode == 0, writer.stderr
    lint = subprocess.run(["bash", HANDOFF_LINT, str(path)],
                          capture_output=True, text=True)
    assert lint.returncode == 0, lint.stdout + lint.stderr


def _handoff(subject, repo, branch, headline, next_action, written_at,
             session_id="session-123"):
    return {
        "schema_version": 2,
        "written_at": written_at,
        "trigger": "checkpoint",
        "subject": {"working_directory": subject, "session_id": session_id},
        "git": {"repository_root": repo, "branch": branch},
        "resume": {
            "headline": headline,
            "next_action": next_action,
            "open_loops": [{"context": "Read the durable record.",
                            "anchor": {"ticket": "alexrivera/#1024"}}],
        },
        "spawned_processes": [],
        "suggested_skills": ["pickup"],
    }


def test_handoff_candidates_group_current_siblings_then_elsewhere(tmp_path):
    state = tmp_path / "state"
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo_path)], check=True)
    _git(str(repo_path), "config", "user.email", "test@example.com")
    _git(str(repo_path), "config", "user.name", "Test")
    _git(str(repo_path), "commit", "-q", "--allow-empty", "-m", "init")
    current = repo_path
    sibling = tmp_path / "sibling-worktree"
    _git(str(repo_path), "worktree", "add", "-q", "-b", "sibling", str(sibling), "main")
    elsewhere = tmp_path / "elsewhere"
    for d in (elsewhere,):
        d.mkdir(parents=True)
    repo = str(repo_path)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    _write_handoff(state / "current.json", _handoff(str(current), repo, "current",
                   "Resume current", "Run its focused test", now))
    _write_handoff(state / "sibling.json", _handoff(str(sibling), repo, "sibling",
                   "Resume sibling", "Read its ticket", now))
    _write_handoff(state / "elsewhere.json", _handoff(str(elsewhere), str(elsewhere), "main",
                   "Resume elsewhere", "Inspect state", now))

    candidates = rw.handoff_candidates(str(state), str(current))

    assert [c["group"] for c in candidates] == [
        "this_directory", "sibling_worktrees", "elsewhere",
    ]
    assert [(c["headline"], c["next_action"], c["branch"]) for c in candidates] == [
        ("Resume current", "Run its focused test", "current"),
        ("Resume sibling", "Read its ticket", "sibling"),
        ("Resume elsewhere", "Inspect state", "main"),
    ]
    assert all(c["age"] for c in candidates)


def test_two_sessions_in_one_directory_are_listed_newest_first(tmp_path):
    state = tmp_path / "state"
    current = tmp_path / "repo"
    current.mkdir()
    _write_handoff(state / "older.json", _handoff(
        str(current), str(current), "one", "Older", "Resume one",
        "2026-09-06T00:00:00Z", session_id="session-one"))
    _write_handoff(state / "newer.json", _handoff(
        str(current), str(current), "two", "Newer", "Resume two",
        "2026-09-06T00:00:01Z", session_id="session-two"))

    candidates = rw.handoff_candidates(str(state), str(current))

    assert [row["session_id"] for row in candidates] == ["session-two", "session-one"]
    assert [row["group"] for row in candidates] == ["this_directory", "this_directory"]


def test_prune_candidates_classifies_live_missing_and_stale_transcripts(tmp_path):
    state = tmp_path / "state"
    home = tmp_path / "home"
    cwd = tmp_path / "project.with-dot"
    cwd.mkdir()
    written_at = "2026-09-01T00:00:00Z"
    for session_id in ("live", "missing", "stale"):
        _write_handoff(state / (session_id + ".json"), _handoff(
            str(cwd), str(cwd), "main", session_id, "Resume", written_at,
            session_id=session_id))
    transcript_dir = home / ".claude" / "projects" / str(cwd).replace("/", "-").replace(".", "-")
    transcript_dir.mkdir(parents=True)
    live = transcript_dir / "live.jsonl"
    stale = transcript_dir / "stale.jsonl"
    live.write_text("{}\n")
    stale.write_text("{}\n")
    now = datetime(2026, 9, 10, tzinfo=timezone.utc)
    os.utime(live, (now.timestamp(), now.timestamp()))
    old = datetime(2026, 9, 1, tzinfo=timezone.utc).timestamp()
    os.utime(stale, (old, old))

    candidates = rw.prune_candidates(str(state), str(home), prune_days=7, now=now)

    assert [(row["session_id"], row["reason"]) for row in candidates] == [
        ("missing", "missing_transcript"),
        ("stale", "stale_transcript"),
    ]
    assert all(set(row) == {"path", "session_id", "reason", "age"}
               for row in candidates)
    assert str(transcript_dir).endswith("project-with-dot")


def test_pickup_prune_archives_candidates_without_deleting_them(tmp_path):
    state = tmp_path / "state"
    home = tmp_path / "home"
    current = tmp_path / "repo"
    current.mkdir()
    source = state / "dead.json"
    _write_handoff(source, _handoff(
        str(current), str(current), "main", "Dead", "Archive", "2026-09-01T00:00:00Z",
        session_id="dead-session"))
    env = dict(os.environ)
    env.update({"HOME": str(home), "HANDOFF_STATE_DIR": str(state)})

    result = subprocess.run(
        ["bash", os.path.join(ROOT, "scripts", "pickup.sh"), "--prune"],
        cwd=current, capture_output=True, text=True, env=env)

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["source"] == "handoff_prune"
    assert [{key: row[key] for key in ("from", "to", "session_id", "reason")}
            for row in report["moved"]] == [{
                "from": str(source),
                "to": str(state / "archive" / "dead.json"),
                "session_id": "dead-session",
                "reason": "missing_transcript",
            }]
    assert report["moved"][0]["age"] != "unknown"
    assert not source.exists()
    assert (state / "archive" / "dead.json").is_file()


def test_handoff_briefing_is_handoff_sourced_and_git_cross_checked(tmp_path, monkeypatch):
    state = tmp_path / "state"
    worktree = tmp_path / "repo"
    worktree.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(worktree)], check=True)
    _git(str(worktree), "config", "user.email", "test@example.com")
    _git(str(worktree), "config", "user.name", "Test")
    _git(str(worktree), "commit", "-q", "--allow-empty", "-m", "init")
    path = state / "current.json"
    _write_handoff(path, _handoff(str(worktree), str(worktree), "main",
                   "Continue handoff", "Run the focused test", "2026-09-06T00:00:00Z"))


    briefing = rw.handoff_briefing(str(path))

    assert briefing["version"] == 2
    assert briefing["source"] == "handoff"
    assert briefing["resume"]["headline"] == "Continue handoff"
    assert briefing["git"]["branch"] == "main"
    assert briefing["git"]["exists"] is True
    assert briefing["provenance"] == "validated_or_inferred_required"
    assert all(item["provenance"].startswith(("validated:", "inferred:"))
               for item in briefing["briefing"])


@pytest.mark.parametrize("args,expected_error", [
    (["--handoff"], "usage"),
    (["--handoff", "/definitely/not/a/handoff.json"], "invalid_handoff"),
])
def test_pickup_wrapper_handoff_errors_are_one_json_object_and_nonzero(args, expected_error):
    result = subprocess.run(["bash", os.path.join(ROOT, "scripts", "pickup.sh")] + args,
                            capture_output=True, text=True)
    assert result.returncode != 0
    report = json.loads(result.stdout)
    assert isinstance(report, dict)
    assert report["error"] == expected_error


@pytest.mark.parametrize("args,option", [
    (["--bogus"], "--bogus"),
    (["--session"], "--session"),
    (["--machine", "--session", "requested"], "--machine"),
    (["--handoff", "/tmp/example.json", "--prune"], "--prune"),
])
def test_pickup_wrapper_rejects_unknown_and_conflicting_lens_options(args, option):
    result = subprocess.run(["bash", os.path.join(ROOT, "scripts", "pickup.sh")] + args,
                            capture_output=True, text=True)
    assert result.returncode != 0
    report = json.loads(result.stdout)
    assert report["error"] == "usage"
    assert option in report["message"]


def test_pickup_wrapper_no_other_session_is_one_json_object(tmp_path):
    current = tmp_path / "repo"
    current.mkdir()
    slug = str(current).replace("/", "-").replace(".", "-")
    transcript_dir = tmp_path / "home" / ".claude" / "projects" / slug
    transcript_dir.mkdir(parents=True)
    (transcript_dir / "current.jsonl").write_text("{}\\n")
    env = dict(os.environ)
    env["HOME"] = str(tmp_path / "home")
    env["CLAUDE_CODE_SESSION_ID"] = "current"
    env["HANDOFF_STATE_DIR"] = str(tmp_path / "state")
    result = subprocess.run(["bash", os.path.join(ROOT, "scripts", "pickup.sh")],
                            cwd=current, capture_output=True, text=True, env=env)
    assert result.returncode == 0
    report = json.loads(result.stdout)
    assert report["error"] == "no_other_session"


def test_pickup_wrapper_explicit_session_bypasses_handoff_listing(tmp_path):
    current = tmp_path / "repo"
    current.mkdir()
    state = tmp_path / "state"
    _write_handoff(state / "current.json", _handoff(
        str(current), str(current), "main", "Do not list", "Use requested transcript",
        "2026-09-06T00:00:00Z"))
    slug = str(current).replace("/", "-").replace(".", "-")
    transcript_dir = tmp_path / "home" / ".claude" / "projects" / slug
    transcript_dir.mkdir(parents=True)
    (transcript_dir / "requested.jsonl").write_text(open(FIXTURE).read())
    env = dict(os.environ)
    env["HOME"] = str(tmp_path / "home")
    env["HANDOFF_STATE_DIR"] = str(state)
    result = subprocess.run(
        ["bash", os.path.join(ROOT, "scripts", "pickup.sh"), "--session", "requested",
         ],
        cwd=current, capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["session"] == "requested"
    assert "candidates" not in report


def test_pickup_wrapper_empty_explicit_session_fails_closed(tmp_path):
    """An empty --session value is an invalid explicit selection, not auto mode.

    The otherwise-eligible fallback transcript makes this an end-to-end
    regression: accepting the empty value must not quietly restore it.
    """
    current = tmp_path / "repo"
    current.mkdir()
    slug = str(current).replace("/", "-").replace(".", "-")
    transcript_dir = tmp_path / "home" / ".claude" / "projects" / slug
    transcript_dir.mkdir(parents=True)
    (transcript_dir / "fallback.jsonl").write_text(open(FIXTURE).read())
    env = dict(os.environ)
    env["HOME"] = str(tmp_path / "home")
    env["HANDOFF_STATE_DIR"] = str(tmp_path / "state")
    result = subprocess.run(
        ["bash", os.path.join(ROOT, "scripts", "pickup.sh"), "--session", "",
         ],
        cwd=current, capture_output=True, text=True, env=env)

    assert result.returncode != 0
    report = json.loads(result.stdout)
    assert report["error"] == "usage"
    assert "session id" in report["message"]
    assert "session" not in report


def test_pickup_engine_empty_transcript_session_rejects_usage(tmp_path):
    """Internal callers cannot reinterpret an empty explicit selection as auto."""
    current = tmp_path / "repo"
    current.mkdir()
    result = subprocess.run(
        [sys.executable, os.path.join(ENGINE_DIR, "pickup.py"),
         "--directory-resume", str(tmp_path / "state"), str(current), str(tmp_path / "home"),
         "--transcript-session", ""],
        capture_output=True, text=True)

    assert result.returncode != 0
    report = json.loads(result.stdout)
    assert report["error"] == "usage"
    assert "session id" in report["message"]
    assert "session" not in report


def test_handoff_candidate_cli_and_transcript_fallback_contract(tmp_path, no_git_env):
    """The engine seam exposes candidates without an index, while a missing
    handoff state preserves the existing transcript report and adds only the
    fallback notice on successful mining."""
    state = tmp_path / "state"
    current = tmp_path / "current"
    current.mkdir()
    _write_handoff(state / "current.json", _handoff(
        str(current), str(current), "main", "Resume current", "Run test",
        "2026-09-06T00:00:00Z"))
    engine = os.path.join(ENGINE_DIR, "pickup.py")
    candidates = subprocess.run(
        [sys.executable, engine, "--handoff-candidates", str(state), str(current)],
        capture_output=True, text=True, env=no_git_env,
    )
    assert candidates.returncode == 0, candidates.stderr
    parsed_candidates = json.loads(candidates.stdout)
    assert parsed_candidates["source"] == "handoff_candidates"
    assert parsed_candidates["candidates"][0]["group"] == "this_directory"

    fallback = subprocess.run(
        [sys.executable, engine, "--transcript-fallback", FIXTURE],
        capture_output=True, text=True, env=no_git_env,
    )
    assert fallback.returncode == 0, fallback.stderr
    parsed_fallback = json.loads(fallback.stdout)
    assert parsed_fallback["source"] == "transcript_fallback"
    assert "No handoff was found" in parsed_fallback["notice"]


def test_handoff_candidates_are_newest_first_and_normalize_common_git_dir(tmp_path, monkeypatch):
    state = tmp_path / "state"
    current = tmp_path / "repo" / "current"
    sibling_old = tmp_path / "repo" / "old"
    sibling_new = tmp_path / "repo" / "new"
    for d in (current, sibling_old, sibling_new):
        d.mkdir(parents=True)
    repo = str(tmp_path / "repo")
    _write_handoff(state / "current.json", _handoff(str(current), repo, "current",
                   "Current", "Resume", "2026-09-06T00:00:00+00:00"))
    _write_handoff(state / "old.json", _handoff(str(sibling_old), repo, "old",
                   "Old", "Resume", "2026-09-06T00:00:00Z"))
    _write_handoff(state / "new.json", _handoff(str(sibling_new), repo, "new",
                   "New", "Resume", "2026-09-06T00:00:01.500Z"))

    candidates = rw.handoff_candidates(str(state), str(current))
    assert [c["headline"] for c in candidates] == ["Current", "New", "Old"]
    assert all(c["age"] != "unknown" for c in candidates)

    monkeypatch.setattr(rw, "git", lambda cwd, *args: str(tmp_path / "repo" / ".git"))
    assert rw._repository_root(str(current)) == os.path.realpath(str(tmp_path / "repo"))


def test_handoff_candidate_listing_reports_skipped_corrupt_and_stale_files(tmp_path):
    state = tmp_path / "state"
    current = tmp_path / "current"
    current.mkdir()
    _write_handoff(state / "valid.json", _handoff(
        str(current), str(current), "main", "Valid", "Resume", "2026-09-06T00:00:00Z"))
    (state / "corrupt.json").write_text("not json")
    (state / "stale.json").write_text(json.dumps({"schema_version": 1}))

    candidates, skipped = rw.handoff_candidates(str(state), str(current), include_skipped=True)

    assert [candidate["headline"] for candidate in candidates] == ["Valid"]
    assert {item["reason"] for item in skipped} == {"invalid_json", "unsupported_schema"}
    assert all("path" in item for item in skipped)


def test_handoff_loader_rejects_empty_subject_and_null_open_loops(tmp_path, monkeypatch):
    invalid = _handoff(str(tmp_path), str(tmp_path), "main", "Invalid", "Stop",
                       "2026-09-06T00:00:00Z")
    invalid["subject"]["working_directory"] = ""
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(invalid))
    assert rw._load_handoff(str(path)) is None

    valid = _handoff(str(tmp_path), str(tmp_path), "main", "Null loops", "Resume",
                     "2026-09-06T00:00:00Z")
    valid["resume"]["open_loops"] = None
    valid_path = tmp_path / "null-loops.json"
    valid_path.write_text(json.dumps(valid))
    assert rw.handoff_briefing(str(valid_path))["resume"]["open_loops"] is None


def test_unrelated_handoff_does_not_suppress_current_directory_transcript_fallback(tmp_path):
    """A machine-global unrelated continuation must not replace this
    directory's transcript/error path; only current and sibling rows do."""
    state = tmp_path / "state"
    current = tmp_path / "current"
    elsewhere = tmp_path / "elsewhere"
    current.mkdir()
    elsewhere.mkdir()
    _write_handoff(state / "elsewhere.json", _handoff(
        str(elsewhere), str(elsewhere), "main", "Elsewhere", "Do not resume",
        "2026-09-06T00:00:00Z"))
    env = dict(os.environ)
    env["HOME"] = str(tmp_path / "home")
    env["HANDOFF_STATE_DIR"] = str(state)
    result = subprocess.run(["bash", os.path.join(ROOT, "scripts", "pickup.sh")],
                            cwd=current, capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["error"] == "no_transcript_directory"


def test_handoff_briefing_shows_owned_files_and_carried_items(tmp_path, monkeypatch):
    data = {"schema_version": 2, "subject": {"working_directory": str(tmp_path), "session_id": "prior"},
            "git": {"repository_root": "", "branch": ""},
            "uncommitted_files": [str(tmp_path / "mine")],
            "resume": {"headline": "Continue", "session_summary": "Implemented capture",
                       "open_loops": [{"type": "lesson", "context": "Keep the original author", "session_id": "prior",
                                       "produced_at": "2026-10-02T12:00:00Z", "disposition": "fold into rules"}]}}
    path = tmp_path / "handoff.json"
    path.write_text(json.dumps(data))
    result = rw.handoff_briefing(str(path))
    assert result["uncommitted_files"] == data["uncommitted_files"]
    lines = "\n".join(row["line"] for row in result["briefing"])
    assert str(tmp_path / "mine") in lines
    assert "Keep the original author" in lines and "prior" in lines
    assert "Implemented capture" in lines


def test_pickup_wrapper_lists_handoffs_from_the_configured_location(tmp_path):
    """#1572: with no HANDOFF_STATE_DIR, the wrapper reads where the
    continuity configuration says handoffs are stored."""
    current = tmp_path / "repo"
    current.mkdir()
    configured = tmp_path / "configured-handoffs"
    _write_handoff(configured / "one.json", _handoff(
        str(current), str(current), "main", "Configured", "Resume it",
        "2026-09-06T00:00:00Z", session_id="configured-session"))
    config = tmp_path / "continuity.json"
    config.write_text(json.dumps({"handoff_dir": str(configured)}))
    env = {key: value for key, value in os.environ.items() if key != "HANDOFF_STATE_DIR"}
    env.update({"HOME": str(tmp_path / "home"), "CONTINUITY_CONFIG": str(config)})
    result = subprocess.run(
        ["bash", os.path.join(ROOT, "scripts", "pickup.sh")],
        cwd=current, capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert [row["session_id"] for row in report["candidates"]] == ["configured-session"]

    config.write_text("{broken")
    result = subprocess.run(
        ["bash", os.path.join(ROOT, "scripts", "pickup.sh")],
        cwd=current, capture_output=True, text=True, env=env)
    assert result.returncode != 0
    assert json.loads(result.stdout)["error"] == "handoff_config_error"
