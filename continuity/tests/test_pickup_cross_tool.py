"""#1453 — cross-tool session reconstruction in pickup.py.

A session id from either provider's store must resolve to reconstructed
context whichever tool invokes /pickup. Every case is named by its
source store and invoking environment, never "X-from-Y":

- "Claude-source" / "Codex-source": the store that owns the transcript.
- "invoked under a Claude-like env" / "Codex-like env": the ambient
  CLAUDE_* or CODEX_* variables the wrapper sees. Both families are stripped
  first, then one is set, so no case runs under a mixed env by accident.

Fixtures are redacted real records (tests/fixtures/pickup-session.jsonl
for Claude, tests/fixtures/pickup-codex-*.jsonl for Codex, provenance in
tests/fixtures/pickup-codex-PROVENANCE.md). Each test copies them into a
sandboxed HOME and CODEX_HOME; nothing reads or writes the live stores. The
PATH carries a stub `git` binary that always fail, so no report
reaches a live checkout or the network.

Run with: uv run --with pytest pytest tests/test_pickup_cross_tool.py -q
"""
import json
import os
import re
import subprocess
import time

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WRAPPER = os.path.join(ROOT, "scripts", "pickup.sh")
FIXTURES = os.path.join(HERE, "fixtures")

CLAUDE_FIXTURE = os.path.join(FIXTURES, "pickup-session.jsonl")
CLAUDE_GUID = "72a3dfb7-a0d3-4deb-9ec5-5f55f824ebd0"

CODEX_FIXTURE = os.path.join(FIXTURES, "pickup-codex-rollout.jsonl")
CODEX_GUID = "01a078d6-8cc9-7630-9c55-b658dedb03fa"
CODEX_NAME = "rollout-2026-09-06T16-28-41-%s.jsonl" % CODEX_GUID
CODEX_CWD = "/Users/alex/Development/example-config/.worktrees/feature-a"

PAGED_GUID = "01a0c5fd-cab8-7960-8ba7-8a5c9d3e6759"
PAGED_BASE = os.path.join(FIXTURES, "pickup-codex-paginated-base.jsonl")
PAGED_BASE_NAME = "rollout-2026-09-21T16-02-19-%s.jsonl" % PAGED_GUID
PAGED_WINDOW = os.path.join(FIXTURES, "pickup-codex-paginated-window.jsonl")
PAGED_WINDOW_NAME = ("rollout-2026-09-23T15-00-25-%s_01a0d011-d843-7552-b2ab-b25f304269ed.jsonl"
                     % PAGED_GUID)

SUBAGENT_FIXTURE = os.path.join(FIXTURES, "pickup-codex-subagent.jsonl")
SUBAGENT_GUID = "01a06f48-b1f1-7013-9ffa-40bf188e242d"
SUBAGENT_PARENT = "01a06f48-b18c-7551-9ba3-6d17160c21ca"
SUBAGENT_NAME = "rollout-2026-09-04T19-57-10-%s.jsonl" % SUBAGENT_GUID

# Ids of the invoking session in each env flavor. They never name a fixture.
INVOKER_CLAUDE_ID = "00000000-0000-4000-8000-00000000c1ad"
INVOKER_CODEX_ID = "00000000-0000-7000-8000-00000000c0de"


def _slug(path):
    return path.replace("/", "-").replace(".", "-")


class Sandbox(object):
    def __init__(self, tmp_path):
        self.root = tmp_path
        self.home = tmp_path / "home"
        self.codex_home = tmp_path / "codex-home"
        self.state = tmp_path / "state"
        self.cwd = tmp_path / "invoker"
        self.bin = tmp_path / "bin"
        for d in (self.home, self.cwd, self.bin):
            d.mkdir(parents=True, exist_ok=True)
        for name in ("git",):
            stub = self.bin / name
            stub.write_text("#!/bin/sh\nexit 1\n")
            stub.chmod(0o755)

    # ---- stores
    def claude_store(self):
        path = self.home / ".claude" / "projects"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def codex_store(self):
        path = self.codex_home / "sessions"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def put_claude(self, guid, source, project_dir):
        target = self.claude_store() / _slug(str(project_dir))
        target.mkdir(parents=True, exist_ok=True)
        dest = target / (guid + ".jsonl")
        dest.write_bytes(open(source, "rb").read())
        return dest

    def put_codex(self, name, source, day="2026/09/06", archived=False, cwd=None):
        if archived:
            target = self.codex_home / "archived_sessions"
        else:
            target = self.codex_store().joinpath(*day.split("/"))
        target.mkdir(parents=True, exist_ok=True)
        dest = target / name
        data = open(source).read()
        if cwd is not None:
            data = _relocate(data, str(cwd))
        dest.write_text(data)
        return dest

    # ---- invocation
    def env(self, flavor):
        env = {k: v for k, v in os.environ.items()
               if not k.startswith("CLAUDE") and not k.startswith("CODEX")}
        env["HOME"] = str(self.home)
        env["CODEX_HOME"] = str(self.codex_home)
        env["HANDOFF_STATE_DIR"] = str(self.state)
        env["PATH"] = str(self.bin) + os.pathsep + "/usr/bin:/bin"
        if flavor == "claude":
            env["CLAUDECODE"] = "1"
            env["CLAUDE_CODE_SESSION_ID"] = INVOKER_CLAUDE_ID
        elif flavor == "codex":
            env["CODEX_THREAD_ID"] = INVOKER_CODEX_ID
            env["CODEX_SESSION_ID"] = INVOKER_CODEX_ID
        return env

    def run(self, flavor, *args, cwd=None, env_extra=None):
        env = self.env(flavor)
        env.update(env_extra or {})
        result = subprocess.run(["bash", WRAPPER] + list(args),
                                cwd=str(cwd or self.cwd), capture_output=True,
                                text=True, env=env)
        self.last_stderr = result.stderr
        try:
            report = json.loads(result.stdout)
        except ValueError:
            pytest.fail("wrapper printed non-JSON (rc %d): %r / %r"
                        % (result.returncode, result.stdout[:400], result.stderr[:400]))
        return result.returncode, report


def _relocate(data, cwd):
    """Point a copied rollout's recorded location at the sandbox directory.

    The wrapper resolves the invoking directory from $PWD, so an automatic
    listing test must run from a directory the rollout names. Only
    session_meta/turn_context cwd values change; every other field is the
    redacted real record."""
    rows = []
    for line in data.splitlines():
        row = json.loads(line)
        if row.get("type") in ("session_meta", "turn_context"):
            row["payload"]["cwd"] = cwd
        rows.append(json.dumps(row))
    return "\n".join(rows) + "\n"


def _truncated_first_line(source):
    """A real record cut mid-line: an unparseable transcript derived from a
    real one, never hand-written JSON."""
    first = open(source).readline()
    return first[: len(first) // 2]


# Rows (0-based) of the committed fixtures that the corruption tests cut.
CODEX_FINAL_ANSWER_ROW = 38   # the root rollout's one final_answer assistant message
PAGED_WINDOW_COMMAND_ROW = 40  # an interior CommandExecution in the window file
CLAUDE_INTERIOR_ROW = 350      # an interior assistant row of the Claude fixture
LAST_ROW = -1


def _with_truncated_record(data, row):
    """A real transcript with one record cut mid-line and every other record
    intact, never hand-written JSON. A cut last record has no trailing
    newline, as a crashed writer leaves it."""
    lines = data.splitlines()
    lines[row] = lines[row][: len(lines[row]) // 2]
    tail = "" if row in (LAST_ROW, len(lines) - 1) else "\n"
    return "\n".join(lines) + tail


def _with_replaced_record(data, row, value):
    """A real transcript with one record replaced by a line that decodes as
    JSON but is not an object. Only the injected value is hand-written."""
    lines = data.splitlines()
    lines[row] = value
    tail = "" if row in (LAST_ROW, len(lines) - 1) else "\n"
    return "\n".join(lines) + tail


def _make_unreadable(path):
    """chmod 000, or skip where that does not stop this process reading."""
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("root reads a chmod 000 file")
    os.chmod(str(path), 0)
    if os.access(str(path), os.R_OK):
        os.chmod(str(path), 0o644)
        pytest.skip("chmod 000 does not make the file unreadable here")


def _outcome(report):
    """Ids and error code only, so a failure message carries no fixture text."""
    return {k: report.get(k) for k in ("error", "session", "provider")}


@pytest.fixture
def sb(tmp_path):
    return Sandbox(tmp_path)


@pytest.fixture
def unlistable(request):
    """chmod 000 a store directory so this process cannot list it, or skip
    where that does not stop it (root, or a filesystem that ignores modes).
    The mode is restored at teardown so pytest can remove the tree."""
    def make(path):
        path = str(path)
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            pytest.skip("root lists a chmod 000 directory")
        os.chmod(path, 0)
        request.addfinalizer(lambda: os.chmod(path, 0o755))
        try:
            os.listdir(path)
        except PermissionError:
            return path
        os.chmod(path, 0o755)
        pytest.skip("chmod 000 does not make the directory unlistable here")
    return make


def _assert_codex_root_context(report):
    assert report.get("error") is None, report
    assert report["session"] == CODEX_GUID
    assert report["provider"] == "codex"
    assert report["first_user"] == "[REDACTED TEXT #2]"
    assert report["last_assistant"] == "[REDACTED TEXT #55]"
    assert report["git"]["branch"] == "feature-a"
    assert report["session_repo_cwd"] == CODEX_CWD
    assert report["first_ts"] == "2026-09-06T22:28:41.951Z"
    assert report["last_ts"] == "2026-09-06T22:32:47.405Z"
    assert report["staleness"]["last_end_turn_ts"] == "2026-09-06T22:32:47.259Z"


# ================================================================== explicit GUID, both directions

def test_codex_source_invoked_under_claude_like_env_restores_context(sb):
    sb.claude_store()
    sb.put_codex(CODEX_NAME, CODEX_FIXTURE)
    rc, report = sb.run("claude", "--session", CODEX_GUID)
    assert rc == 0, report
    _assert_codex_root_context(report)


def test_claude_source_invoked_under_codex_like_env_from_a_different_cwd_restores_context(sb):
    sb.codex_store()
    origin = sb.root / "where-the-session-ran"
    sb.put_claude(CLAUDE_GUID, CLAUDE_FIXTURE, origin)
    rc, report = sb.run("codex", "--session", CLAUDE_GUID)
    assert rc == 0, report
    assert report.get("error") is None, report
    assert report["session"] == CLAUDE_GUID
    assert report["provider"] == "claude"
    assert report["messages"] == 699
    assert report["first_user"] == "[REDACTED TEXT #1]"


def test_claude_source_invoked_under_codex_like_env_from_the_matching_cwd_is_unchanged(sb):
    """Regression pin for the path that already worked (2026-09-07 Codex
    runs): same report fields as before this change."""
    sb.codex_store()
    sb.put_claude(CLAUDE_GUID, CLAUDE_FIXTURE, sb.cwd)
    rc, report = sb.run("codex", "--session", CLAUDE_GUID)
    assert rc == 0, report
    assert report.get("error") is None, report
    assert report["session"] == CLAUDE_GUID
    assert report["messages"] == 699
    assert report["first_user"] == "[REDACTED TEXT #1]"


def test_archived_codex_source_invoked_under_claude_like_env_restores_context(sb):
    sb.claude_store()
    sb.put_codex(CODEX_NAME, CODEX_FIXTURE, archived=True)
    rc, report = sb.run("claude", "--session", CODEX_GUID)
    assert rc == 0, report
    _assert_codex_root_context(report)


def test_paginated_codex_source_is_one_source_in_chronological_order(sb):
    """A thread split across a dated base file and a later window file is
    read as one source: first turn from the base, last from the window."""
    sb.claude_store()
    window = sb.put_codex(PAGED_WINDOW_NAME, PAGED_WINDOW, day="2026/09/23")
    base = sb.put_codex(PAGED_BASE_NAME, PAGED_BASE, day="2026/09/21")
    rc, report = sb.run("claude", "--session", PAGED_GUID)
    assert rc == 0, report
    assert report.get("error") is None, report
    assert report["session"] == PAGED_GUID
    assert report["provider"] == "codex"
    assert report["transcript_files"] == [str(base), str(window)]
    assert report["first_ts"] == "2026-09-21T22:02:19.757Z"
    assert report["last_ts"] == "2026-09-23T21:10:17.979Z"
    assert report["last_assistant"] == "[REDACTED TEXT #140]"


def test_codex_identity_is_the_thread_id_not_the_parent_session_id(sb):
    sb.claude_store()
    sb.put_codex(SUBAGENT_NAME, SUBAGENT_FIXTURE, day="2026/09/04")
    rc, report = sb.run("claude", "--session", SUBAGENT_PARENT)
    assert rc != 0
    assert report["error"] == "no_such_session"
    rc, report = sb.run("claude", "--session", SUBAGENT_GUID)
    assert rc == 0, report
    assert report["session"] == SUBAGENT_GUID
    assert report["provider"] == "codex"


# ================================================================== fail closed

def test_same_guid_valid_in_both_stores_fails_ambiguous(sb):
    """The Claude copy sits under the invoking cwd, where the old lookup
    would silently have chosen it."""
    sb.put_claude(CODEX_GUID, CLAUDE_FIXTURE, sb.cwd)
    codex_copy = sb.put_codex(CODEX_NAME, CODEX_FIXTURE)
    rc, report = sb.run("claude", "--session", CODEX_GUID)
    assert rc != 0
    assert report["error"] == "ambiguous_session"
    assert "claude" in report["message"] and "codex" in report["message"]
    assert str(codex_copy) in report["message"]
    assert "session" not in report


def test_codex_source_with_an_unparseable_first_row_fails_closed(sb):
    """The whole file is half of the session_meta row, so this pins the
    row-0 check only. Corruption after a valid row 0 is covered by the
    interior- and final-record tests below."""
    sb.claude_store()
    target = sb.codex_store() / "2026" / "09" / "06"
    target.mkdir(parents=True)
    (target / CODEX_NAME).write_text(_truncated_first_line(CODEX_FIXTURE))
    rc, report = sb.run("claude", "--session", CODEX_GUID)
    assert rc != 0
    assert report["error"] == "invalid_session_transcript"
    assert CODEX_NAME in report["message"]


def test_claude_source_with_no_parseable_row_at_the_matching_cwd_fails_closed(sb):
    """The whole file is half of one row, so no row decodes. Old behavior:
    one candidate skipped the substance check, so this became an empty rc 0
    report. The explicit lookup is now cwd-independent. The matching cwd
    pins the removed single-candidate path, not a lookup requirement.
    Corruption after valid rows is covered by the interior- and final-record
    tests below."""
    sb.codex_store()
    target = sb.claude_store() / _slug(str(sb.cwd))
    target.mkdir(parents=True)
    (target / (CLAUDE_GUID + ".jsonl")).write_text(_truncated_first_line(CLAUDE_FIXTURE))
    rc, report = sb.run("codex", "--session", CLAUDE_GUID)
    assert rc != 0
    assert report["error"] == "invalid_session_transcript"


def test_valid_and_malformed_matches_for_one_guid_fail_closed(sb):
    """A match whose whole file is unparseable (half of one row) is not
    skipped in favor of a valid match for the same id."""
    sb.put_codex(CODEX_NAME, CODEX_FIXTURE)
    target = sb.claude_store() / _slug(str(sb.root / "elsewhere"))
    target.mkdir(parents=True)
    (target / (CODEX_GUID + ".jsonl")).write_text(_truncated_first_line(CLAUDE_FIXTURE))
    rc, report = sb.run("claude", "--session", CODEX_GUID)
    assert rc != 0
    assert report["error"] == "invalid_session_transcript"


def _assert_invalid_transcript(rc, report, name):
    assert rc != 0, _outcome(report)
    assert report.get("error") == "invalid_session_transcript", _outcome(report)
    assert name in report["message"]
    assert "session" not in report


@pytest.mark.parametrize("row", [CODEX_FINAL_ANSWER_ROW, LAST_ROW], ids=["interior", "final"])
def test_codex_source_with_a_truncated_record_after_a_valid_session_meta_fails_closed(sb, row):
    """Row 0 is intact, so this reaches past the first-row check. A partial
    reconstruction that drops the cut record is not a valid report."""
    sb.claude_store()
    source = sb.root / "codex-cut.jsonl"
    source.write_text(_with_truncated_record(open(CODEX_FIXTURE).read(), row))
    sb.put_codex(CODEX_NAME, str(source))
    rc, report = sb.run("claude", "--session", CODEX_GUID)
    _assert_invalid_transcript(rc, report, CODEX_NAME)


def test_paginated_codex_source_with_a_truncated_record_in_the_window_file_fails_closed(sb):
    """The base file is intact. Each file of a thread is validated, so a cut
    record in the later window file is not skipped."""
    sb.claude_store()
    source = sb.root / "window-cut.jsonl"
    source.write_text(_with_truncated_record(open(PAGED_WINDOW).read(),
                                             PAGED_WINDOW_COMMAND_ROW))
    sb.put_codex(PAGED_WINDOW_NAME, str(source), day="2026/09/23")
    sb.put_codex(PAGED_BASE_NAME, PAGED_BASE, day="2026/09/21")
    rc, report = sb.run("claude", "--session", PAGED_GUID)
    _assert_invalid_transcript(rc, report, PAGED_WINDOW_NAME)


@pytest.mark.parametrize("row", [CLAUDE_INTERIOR_ROW, LAST_ROW], ids=["interior", "final"])
def test_claude_source_with_a_truncated_record_after_valid_rows_fails_closed(sb, row):
    """Earlier rows decode as user and assistant turns, so this reaches past
    the no-parseable-row check."""
    sb.codex_store()
    source = sb.root / "claude-cut.jsonl"
    source.write_text(_with_truncated_record(open(CLAUDE_FIXTURE).read(), row))
    sb.put_claude(CLAUDE_GUID, str(source), sb.root / "where-the-session-ran")
    rc, report = sb.run("codex", "--session", CLAUDE_GUID)
    _assert_invalid_transcript(rc, report, CLAUDE_GUID + ".jsonl")


NON_OBJECT_RECORDS = ["[]", "7"]


@pytest.mark.parametrize("value", NON_OBJECT_RECORDS, ids=["array", "number"])
def test_codex_source_with_a_non_object_record_fails_closed(sb, value):
    """The record decodes but is not a JSON object, so it is not a rollout
    record. The source is malformed, not a traceback or a partial report."""
    sb.claude_store()
    source = sb.root / "codex-non-object.jsonl"
    source.write_text(_with_replaced_record(open(CODEX_FIXTURE).read(),
                                            CODEX_FINAL_ANSWER_ROW, value))
    sb.put_codex(CODEX_NAME, str(source))
    rc, report = sb.run("claude", "--session", CODEX_GUID)
    _assert_invalid_transcript(rc, report, CODEX_NAME)


@pytest.mark.parametrize("value", NON_OBJECT_RECORDS, ids=["array", "number"])
def test_claude_source_with_a_non_object_record_fails_closed(sb, value):
    """The record decodes but is not a JSON object, so it is not a
    transcript record. It is not silently dropped from the report."""
    sb.codex_store()
    source = sb.root / "claude-non-object.jsonl"
    source.write_text(_with_replaced_record(open(CLAUDE_FIXTURE).read(),
                                            CLAUDE_INTERIOR_ROW, value))
    sb.put_claude(CLAUDE_GUID, str(source), sb.root / "where-the-session-ran")
    rc, report = sb.run("codex", "--session", CLAUDE_GUID)
    _assert_invalid_transcript(rc, report, CLAUDE_GUID + ".jsonl")


def test_unreadable_codex_source_fails_closed(sb):
    sb.claude_store()
    rollout = sb.put_codex(CODEX_NAME, CODEX_FIXTURE)
    _make_unreadable(rollout)
    rc, report = sb.run("claude", "--session", CODEX_GUID)
    _assert_invalid_transcript(rc, report, CODEX_NAME)


def test_unreadable_claude_source_fails_closed(sb):
    sb.codex_store()
    transcript = sb.put_claude(CLAUDE_GUID, CLAUDE_FIXTURE, sb.root / "where-the-session-ran")
    _make_unreadable(transcript)
    rc, report = sb.run("codex", "--session", CLAUDE_GUID)
    _assert_invalid_transcript(rc, report, CLAUDE_GUID + ".jsonl")


def test_codex_source_with_a_read_error_after_its_first_record_fails_closed(sb, monkeypatch):
    """chmod cannot make a file readable for the session_meta check and
    unreadable afterward, so the engine's open is faulted in-process: the
    first line reads, and any read past it raises EIO. Iteration and read()
    are both faulted, so a loader that opens the file once still hits it."""
    import errno
    import sys
    sys.path.insert(0, os.path.join(ROOT, "skills", "pickup", "scripts"))
    import pickup as rw

    sb.claude_store()
    rollout = str(sb.put_codex(CODEX_NAME, CODEX_FIXTURE))
    real_open = open

    class FaultyFile(object):
        def __init__(self, f):
            self.f = f
            self.lines = 0

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.f.close()

        def _fault(self):
            raise OSError(errno.EIO, "Input/output error", rollout)

        def readline(self, *args):
            if self.lines:
                self._fault()
            self.lines += 1
            return self.f.readline(*args)

        def read(self, *args):
            self._fault()

        def readlines(self, *args):
            self._fault()

        def __iter__(self):
            return self

        def __next__(self):
            return self.readline()

        def close(self):
            self.f.close()

    def faulty_open(path, *args, **kwargs):
        f = real_open(path, *args, **kwargs)
        return FaultyFile(f) if os.fspath(path) == rollout else f

    monkeypatch.setattr(rw, "open", faulty_open, raising=False)
    # A fault that never fires must not let report building reach a live
    # checkout through the fixture's recorded cwd.
    monkeypatch.setenv("PATH", str(sb.bin) + os.pathsep + "/usr/bin:/bin")
    try:
        report = rw.directory_resume(str(sb.state), str(sb.cwd), str(sb.home), None,
                                     transcript_session=CODEX_GUID,
                                     codex_home=str(sb.codex_home))
    except OSError as exc:
        pytest.fail("directory_resume raised %s instead of returning an error report"
                    % type(exc).__name__)
    assert rw.report_exit_status(report) != 0, _outcome(report)
    assert report.get("error") == "invalid_session_transcript", _outcome(report)
    assert CODEX_NAME in report["message"]
    assert "session" not in report


def test_codex_rollout_whose_meta_id_disagrees_with_its_filename_fails_closed(sb):
    """Discovery keys on the filename; validation confirms session_meta.id."""
    sb.claude_store()
    sb.put_codex("rollout-2026-09-04T19-57-10-%s.jsonl" % SUBAGENT_PARENT, SUBAGENT_FIXTURE,
                 day="2026/09/04")
    rc, report = sb.run("claude", "--session", SUBAGENT_PARENT)
    assert rc != 0
    assert report["error"] == "invalid_session_transcript"


def test_missing_guid_with_both_stores_present_fails_with_searched_roots(sb):
    claude_root = sb.claude_store()
    codex_root = sb.codex_store()
    rc, report = sb.run("claude", "--session", CODEX_GUID)
    assert rc != 0
    assert report["error"] == "no_such_session"
    assert str(claude_root) in report["message"]
    assert str(codex_root) in report["message"]


def test_missing_guid_with_codex_store_absent_names_the_unavailable_store(sb):
    sb.claude_store()
    rc, report = sb.run("claude", "--session", CODEX_GUID)
    assert rc != 0
    assert report["error"] == "session_store_unavailable"
    assert str(sb.codex_home) in report["message"]
    assert "CODEX_HOME" in report["message"]


def test_missing_guid_with_no_store_present_fails_unavailable(sb):
    rc, report = sb.run("codex", "--session", CLAUDE_GUID)
    assert rc != 0
    assert report["error"] == "session_store_unavailable"
    assert str(sb.home / ".claude" / "projects") in report["message"]


@pytest.mark.parametrize("bad", ["*", "../x", "a/b", ".hidden"])
def test_session_id_with_path_or_glob_syntax_is_a_usage_error(sb, bad):
    sb.put_claude(CLAUDE_GUID, CLAUDE_FIXTURE, sb.cwd)
    sb.put_codex(CODEX_NAME, CODEX_FIXTURE)
    rc, report = sb.run("claude", "--session", bad)
    assert rc != 0
    assert report["error"] == "invalid_session_id"


# ================================================================== automatic directory fallback

def test_automatic_fallback_considers_codex_sessions_for_this_directory(sb):
    sb.put_codex(CODEX_NAME, CODEX_FIXTURE, cwd=sb.cwd)
    rc, report = sb.run("claude")
    assert rc == 0, report
    assert report.get("error") is None, report
    assert report["session"] == CODEX_GUID
    assert report["provider"] == "codex"
    assert report["source"] == "transcript_fallback"


def test_automatic_fallback_picks_the_newest_session_across_providers(sb):
    claude_copy = sb.put_claude(CLAUDE_GUID, CLAUDE_FIXTURE, sb.cwd)
    codex_copy = sb.put_codex(CODEX_NAME, CODEX_FIXTURE, cwd=sb.cwd)
    os.utime(str(claude_copy), (1_000_000_000, 1_000_000_000))
    os.utime(str(codex_copy), (2_000_000_000, 2_000_000_000))
    rc, report = sb.run("claude")
    assert rc == 0, report
    assert report["session"] == CODEX_GUID
    os.utime(str(claude_copy), (3_000_000_000, 3_000_000_000))
    rc, report = sb.run("claude")
    assert report["session"] == CLAUDE_GUID
    assert report["provider"] == "claude"


def test_automatic_fallback_with_only_a_malformed_claude_transcript_fails_closed(sb):
    """A lone candidate used to skip the substance check, so an unparseable
    transcript became an empty rc 0 report."""
    target = sb.claude_store() / _slug(str(sb.cwd))
    target.mkdir(parents=True)
    bad = target / (CLAUDE_GUID + ".jsonl")
    bad.write_text(_truncated_first_line(CLAUDE_FIXTURE))
    rc, report = sb.run("claude")
    assert rc != 0, report
    assert report["error"] == "no_substantive_transcript"
    assert str(bad) in report["message"]
    assert "session" not in report


def test_automatic_fallback_with_only_a_codex_thread_without_assistant_text_fails_closed(sb):
    """A real rollout prefix that stops before the first assistant message:
    the thread opened and never answered, so it is not a resume target."""
    prefix = []
    for line in open(CODEX_FIXTURE):
        row = json.loads(line)
        if row["type"] == "response_item" and row["payload"].get("role") == "assistant":
            break
        prefix.append(line)
    source = sb.root / "codex-prefix.jsonl"
    source.write_text("".join(prefix))
    rollout = sb.put_codex(CODEX_NAME, str(source), cwd=sb.cwd)
    rc, report = sb.run("claude")
    assert rc != 0, report
    assert report["error"] == "no_substantive_transcript"
    assert str(rollout) in report["message"]
    assert "session" not in report


def test_automatic_fallback_with_only_a_codex_thread_with_a_truncated_interior_record_fails_closed(sb):
    """Row 0 is intact and seven commentary assistant rows survive the cut,
    so the thread is still substantive without the cut record. It is skipped
    as malformed, never reported with that record missing."""
    source = sb.root / "codex-cut.jsonl"
    source.write_text(_with_truncated_record(
        _relocate(open(CODEX_FIXTURE).read(), str(sb.cwd)), CODEX_FINAL_ANSWER_ROW))
    rollout = sb.put_codex(CODEX_NAME, str(source))
    rc, report = sb.run("claude")
    assert rc != 0, _outcome(report)
    assert report.get("error") == "no_substantive_transcript", _outcome(report)
    assert str(rollout) in report["message"]
    assert "session" not in report


def test_automatic_fallback_with_only_a_claude_transcript_with_a_truncated_interior_record_fails_closed(sb):
    """Rows before and after the cut decode as substantive turns. The
    transcript is skipped as malformed, never reported with a record missing."""
    source = sb.root / "claude-cut.jsonl"
    source.write_text(_with_truncated_record(open(CLAUDE_FIXTURE).read(), CLAUDE_INTERIOR_ROW))
    transcript = sb.put_claude(CLAUDE_GUID, str(source), sb.cwd)
    rc, report = sb.run("claude")
    assert rc != 0, _outcome(report)
    assert report.get("error") == "no_substantive_transcript", _outcome(report)
    assert str(transcript) in report["message"]
    assert "session" not in report


def _paged_thread_here(sb, window_text):
    """The paginated thread recorded in the invoking directory: the intact
    base, and window_text under the window's real filename."""
    sb.put_codex(PAGED_BASE_NAME, PAGED_BASE, day="2026/09/21", cwd=sb.cwd)
    source = sb.root / "window-source.jsonl"
    source.write_text(window_text)
    return sb.put_codex(PAGED_WINDOW_NAME, str(source), day="2026/09/23")


def _assert_thread_skipped(rc, report, window):
    assert rc != 0, _outcome(report)
    assert report.get("error") == "no_substantive_transcript", _outcome(report)
    assert str(window) in report["message"]
    assert "session" not in report


def test_automatic_fallback_reads_every_file_of_a_paginated_codex_thread(sb):
    window = _paged_thread_here(sb, _relocate(open(PAGED_WINDOW).read(), str(sb.cwd)))
    base = sb.codex_home / "sessions" / "2026" / "09" / "21" / PAGED_BASE_NAME
    rc, report = sb.run("claude")
    assert rc == 0, _outcome(report)
    assert report.get("error") is None, _outcome(report)
    assert report["session"] == PAGED_GUID
    assert report["transcript_files"] == [str(base), str(window)]


def test_automatic_fallback_with_a_paginated_codex_thread_whose_window_first_record_is_truncated_fails_closed(sb):
    """The window belongs to the thread by its filename. Its session_meta is
    cut, so discovery cannot read it, but the thread is still selected
    through the base. It fails as the explicit lookup does, never
    reconstructed from the base alone."""
    window = _paged_thread_here(sb, _with_truncated_record(
        _relocate(open(PAGED_WINDOW).read(), str(sb.cwd)), 0))
    rc, report = sb.run("claude")
    _assert_thread_skipped(rc, report, window)


def test_automatic_fallback_with_a_paginated_codex_thread_whose_window_is_unreadable_fails_closed(sb):
    window = _paged_thread_here(sb, _relocate(open(PAGED_WINDOW).read(), str(sb.cwd)))
    _make_unreadable(window)
    rc, report = sb.run("claude")
    _assert_thread_skipped(rc, report, window)


def test_automatic_fallback_with_a_paginated_codex_thread_whose_window_names_another_thread_fails_closed(sb):
    """The window file's name puts it in this thread, but its session_meta
    names the root fixture's thread. The explicit lookup fails on that
    disagreement, and the automatic path does not drop the file instead."""
    window = _paged_thread_here(sb, _relocate(open(CODEX_FIXTURE).read(), str(sb.cwd)))
    rc, report = sb.run("claude")
    _assert_thread_skipped(rc, report, window)


@pytest.mark.parametrize("claude_first", [True, False])
def test_automatic_fallback_breaks_equal_mtime_ties_by_session_id(sb, claude_first):
    """Equal mtimes break by the lowest session id, whatever order the files
    were created or listed in. The Codex id (01a0...) sorts before the
    Claude ids (72a3..., ffff...). All three ids differ, so the provider-name
    leg of the documented tiebreak is not exercised here."""
    later_id = "ffffffff-0000-4000-8000-000000000000"
    stamp = (2_000_000_000, 2_000_000_000)
    placed = []
    steps = [lambda: placed.append(sb.put_claude(CLAUDE_GUID, CLAUDE_FIXTURE, sb.cwd)),
             lambda: placed.append(sb.put_claude(later_id, CLAUDE_FIXTURE, sb.cwd)),
             lambda: placed.append(sb.put_codex(CODEX_NAME, CODEX_FIXTURE, cwd=sb.cwd))]
    for step in (steps if claude_first else list(reversed(steps))):
        step()
    for path in placed:
        os.utime(str(path), stamp)
    rc, report = sb.run("claude")
    assert rc == 0, report
    assert report["session"] == CODEX_GUID
    assert report["provider"] == "codex"


def test_automatic_fallback_under_codex_like_env_skips_the_invoking_thread(sb):
    sb.put_codex(CODEX_NAME, CODEX_FIXTURE, cwd=sb.cwd)
    rc, report = sb.run("codex", env_extra={"CODEX_THREAD_ID": CODEX_GUID})
    assert rc == 0, report
    assert report["error"] == "no_other_session"


def test_automatic_fallback_ignores_codex_subagent_rollouts(sb):
    sb.put_codex(SUBAGENT_NAME, SUBAGENT_FIXTURE, day="2026/09/04", cwd=sb.cwd)
    rc, report = sb.run("claude")
    assert rc == 0, report
    assert report["error"] == "no_transcript_directory"


def test_automatic_fallback_keeps_handoff_first(sb):
    """A handoff for this directory still wins over any transcript."""
    import sys
    sys.path.insert(0, HERE)
    from test_pickup import _handoff, _write_handoff
    sb.put_codex(CODEX_NAME, CODEX_FIXTURE, cwd=sb.cwd)
    _write_handoff(sb.state / "current.json", _handoff(
        str(sb.cwd), str(sb.cwd), "main", "Resume current", "Run test",
        "2026-09-06T00:00:00Z"))
    rc, report = sb.run("claude")
    assert rc == 0, report
    assert report["source"] == "handoff_candidates"


# ================================================================== store enumeration
#
# A provider root that does not exist is a machine that never used that
# provider, and lookup proceeds without it. A root or traversed subdirectory
# that exists but cannot be listed is unknown state: it may hold a member of
# the thread or a second owner of the id, so neither completeness nor
# uniqueness can be proven. Both lookups fail closed on it, naming the
# directory, and never fall through to a partial thread or another session.

def _assert_store_unlistable(sb, rc, report, unlisted):
    assert rc != 0, _outcome(report)
    assert report.get("error") == "session_store_unavailable", _outcome(report)
    assert str(unlisted) in report.get("message", ""), _outcome(report)
    assert "session" not in report, _outcome(report)
    assert "transcript_files" not in report, _outcome(report)
    assert "Traceback" not in sb.last_stderr
    assert "REDACTED TEXT" not in json.dumps(report) + sb.last_stderr


def test_explicit_paginated_codex_thread_with_an_unlistable_day_directory_fails_closed(sb, unlistable):
    """The base's day is listable and the window's is not. The old walk
    skipped the day silently and reported the base alone."""
    sb.claude_store()
    window = _paged_thread_here(sb, _relocate(open(PAGED_WINDOW).read(), str(sb.cwd)))
    day = unlistable(window.parent)
    rc, report = sb.run("claude", "--session", PAGED_GUID)
    _assert_store_unlistable(sb, rc, report, day)


def test_automatic_paginated_codex_thread_with_an_unlistable_day_directory_fails_closed(sb, unlistable):
    window = _paged_thread_here(sb, _relocate(open(PAGED_WINDOW).read(), str(sb.cwd)))
    day = unlistable(window.parent)
    rc, report = sb.run("claude")
    _assert_store_unlistable(sb, rc, report, day)


def test_explicit_lookup_with_an_unlistable_codex_archive_fails_closed(sb, unlistable):
    """The id has a valid readable rollout, but the archive may hold another
    member of the thread."""
    sb.claude_store()
    sb.put_codex(CODEX_NAME, CODEX_FIXTURE)
    archive = unlistable(sb.put_codex(CODEX_NAME, CODEX_FIXTURE, archived=True).parent)
    rc, report = sb.run("claude", "--session", CODEX_GUID)
    _assert_store_unlistable(sb, rc, report, archive)


def test_automatic_fallback_with_an_unlistable_codex_archive_fails_closed(sb, unlistable):
    sb.put_codex(CODEX_NAME, CODEX_FIXTURE, cwd=sb.cwd)
    archive = unlistable(sb.put_codex(CODEX_NAME, CODEX_FIXTURE, archived=True,
                                      cwd=sb.cwd).parent)
    rc, report = sb.run("claude")
    _assert_store_unlistable(sb, rc, report, archive)


def test_explicit_lookup_with_an_unlistable_claude_projects_root_fails_closed(sb, unlistable):
    """The Codex copy is valid, but the Claude root may hold a second owner
    of the id, so the lookup cannot prove it is unambiguous."""
    sb.put_claude(CLAUDE_GUID, CLAUDE_FIXTURE, sb.cwd)
    sb.put_codex(CODEX_NAME, CODEX_FIXTURE)
    root = unlistable(sb.claude_store())
    rc, report = sb.run("claude", "--session", CODEX_GUID)
    _assert_store_unlistable(sb, rc, report, root)


def test_automatic_fallback_with_an_unlistable_claude_projects_root_fails_closed(sb, unlistable):
    """This directory's Claude sessions cannot be listed, so the Codex
    thread cannot be shown to be the newest."""
    sb.put_claude(CLAUDE_GUID, CLAUDE_FIXTURE, sb.cwd)
    sb.put_codex(CODEX_NAME, CODEX_FIXTURE, cwd=sb.cwd)
    root = unlistable(sb.claude_store())
    rc, report = sb.run("claude")
    _assert_store_unlistable(sb, rc, report, root)


def test_explicit_lookup_with_one_unlistable_claude_project_directory_fails_closed(sb, unlistable):
    """The id is valid in a listable project, but the unlistable one may
    hold a second copy of it."""
    sb.codex_store()
    sb.put_claude(CLAUDE_GUID, CLAUDE_FIXTURE, sb.root / "where-the-session-ran")
    other = sb.put_claude("ffffffff-0000-4000-8000-000000000000", CLAUDE_FIXTURE,
                          sb.root / "another-project")
    project = unlistable(other.parent)
    rc, report = sb.run("codex", "--session", CLAUDE_GUID)
    _assert_store_unlistable(sb, rc, report, project)


def test_automatic_fallback_with_this_directorys_claude_project_unlistable_fails_closed(sb, unlistable):
    """The automatic path reads only this directory's Claude project. It
    cannot be listed, so the readable Codex thread is not chosen instead."""
    transcript = sb.put_claude(CLAUDE_GUID, CLAUDE_FIXTURE, sb.cwd)
    sb.put_codex(CODEX_NAME, CODEX_FIXTURE, cwd=sb.cwd)
    project = unlistable(transcript.parent)
    rc, report = sb.run("claude")
    _assert_store_unlistable(sb, rc, report, project)


# A configured provider root may itself resolve through a symlink, as a
# relocated CODEX_HOME does. A symlinked directory inside the store is
# unknown membership: following it may leave the store, skipping it may drop
# a member of the thread. Both lookups fail closed on it, naming the link.

def _paged_thread_behind_a_symlinked_day(sb):
    """The paginated thread recorded in the invoking directory, with the base
    in a real day directory and the intact window in a real directory outside
    the store that sessions/2026/09/23 links to."""
    sb.put_codex(PAGED_BASE_NAME, PAGED_BASE, day="2026/09/21", cwd=sb.cwd)
    outside = sb.root / "window-day"
    outside.mkdir()
    (outside / PAGED_WINDOW_NAME).write_text(
        _relocate(open(PAGED_WINDOW).read(), str(sb.cwd)))
    link = sb.codex_store() / "2026" / "09" / "23"
    os.symlink(str(outside), str(link))
    return link


def test_explicit_paginated_codex_thread_with_a_symlinked_day_directory_fails_closed(sb):
    sb.claude_store()
    link = _paged_thread_behind_a_symlinked_day(sb)
    rc, report = sb.run("claude", "--session", PAGED_GUID)
    _assert_store_unlistable(sb, rc, report, link)


def test_automatic_paginated_codex_thread_with_a_symlinked_day_directory_fails_closed(sb):
    link = _paged_thread_behind_a_symlinked_day(sb)
    rc, report = sb.run("claude")
    _assert_store_unlistable(sb, rc, report, link)


def test_explicit_paginated_codex_thread_under_a_symlinked_codex_home_restores_every_file(sb):
    """Only the configured root is a link. Paths are compared by basename so
    the test does not fix whether the root is reported resolved."""
    real = sb.root / "codex-real"
    real.mkdir()
    os.symlink(str(real), str(sb.codex_home))
    sb.claude_store()
    _paged_thread_here(sb, _relocate(open(PAGED_WINDOW).read(), str(sb.cwd)))
    rc, report = sb.run("claude", "--session", PAGED_GUID)
    assert rc == 0, _outcome(report)
    assert report.get("error") is None, _outcome(report)
    assert report["session"] == PAGED_GUID
    assert report["provider"] == "codex"
    assert [os.path.basename(p) for p in report["transcript_files"]] == [
        PAGED_BASE_NAME, PAGED_WINDOW_NAME]


# The link under sessions/ for each dated level, and the dated path below the
# link's target where the window sits. Rollouts are matched by filename, so
# the window's directory names do not have to agree with its timestamp.
SYMLINKED_LEVELS = {"year": ("2027", "09/23"),
                    "month": ("2026/10", "23"),
                    "day": ("2026/09/23", "")}


def _paged_thread_behind_a_symlinked_level(sb, level):
    """The paginated thread recorded in the invoking directory, with the base
    in the real sessions/2026/09/21 and the intact window below a real
    directory outside the store that a year, month, or day link names.
    Skipping the link reports the base alone and following it reports both
    files, so either shortcut returns rc 0 and fails the test."""
    sb.put_codex(PAGED_BASE_NAME, PAGED_BASE, day="2026/09/21", cwd=sb.cwd)
    linked, below = SYMLINKED_LEVELS[level]
    outside = sb.root / ("window-" + level)
    window_dir = outside.joinpath(*below.split("/")) if below else outside
    window_dir.mkdir(parents=True)
    (window_dir / PAGED_WINDOW_NAME).write_text(
        _relocate(open(PAGED_WINDOW).read(), str(sb.cwd)))
    link = sb.codex_store().joinpath(*linked.split("/"))
    link.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(str(outside), str(link))
    return link


@pytest.mark.parametrize("level", sorted(SYMLINKED_LEVELS))
def test_explicit_paginated_codex_thread_with_a_symlinked_dated_directory_fails_closed(sb, level):
    sb.claude_store()
    link = _paged_thread_behind_a_symlinked_level(sb, level)
    rc, report = sb.run("claude", "--session", PAGED_GUID)
    _assert_store_unlistable(sb, rc, report, link)


def test_automatic_paginated_codex_thread_with_a_symlinked_year_directory_fails_closed(sb):
    """Explicit and automatic lookup list the Codex stores through the same
    codex_rollouts(), so the explicit matrix covers every level of that walk.
    Automatic lookup is pinned here at the year and in the day test above,
    the two ends of the walk, so a fix that guards only one level on the
    automatic path fails one of them."""
    link = _paged_thread_behind_a_symlinked_level(sb, "year")
    rc, report = sb.run("claude")
    _assert_store_unlistable(sb, rc, report, link)


def _codex_archive_behind_a_symlink(sb, cwd=None):
    """archived_sessions as a link to a real directory outside CODEX_HOME that
    holds the root rollout."""
    outside = sb.root / "archive-outside"
    outside.mkdir()
    data = open(CODEX_FIXTURE).read()
    if cwd is not None:
        data = _relocate(data, str(cwd))
    (outside / CODEX_NAME).write_text(data)
    link = sb.codex_home / "archived_sessions"
    os.symlink(str(outside), str(link))
    return link


def test_explicit_lookup_with_a_symlinked_codex_archive_fails_closed(sb):
    """The id has a valid rollout in the real sessions store. The archive
    link may hold another member of the thread."""
    sb.claude_store()
    sb.put_codex(CODEX_NAME, CODEX_FIXTURE)
    link = _codex_archive_behind_a_symlink(sb)
    rc, report = sb.run("claude", "--session", CODEX_GUID)
    _assert_store_unlistable(sb, rc, report, link)


def test_automatic_fallback_with_a_symlinked_codex_archive_fails_closed(sb):
    sb.put_codex(CODEX_NAME, CODEX_FIXTURE, cwd=sb.cwd)
    link = _codex_archive_behind_a_symlink(sb, cwd=sb.cwd)
    rc, report = sb.run("claude")
    _assert_store_unlistable(sb, rc, report, link)


def _claude_project_behind_a_symlink(sb, project_dir):
    """The Claude project entry for project_dir as a link, under the real
    projects root, to a real directory outside the store holding a copy of
    CLAUDE_GUID."""
    outside = sb.root / "project-outside"
    outside.mkdir()
    (outside / (CLAUDE_GUID + ".jsonl")).write_bytes(open(CLAUDE_FIXTURE, "rb").read())
    link = sb.claude_store() / _slug(str(project_dir))
    os.symlink(str(outside), str(link))
    return link


def test_explicit_lookup_with_a_symlinked_claude_project_directory_fails_closed(sb):
    """The id is valid in a real project. Skipping the link reports that copy
    and following it finds a second owner, so only failing closed on the
    link passes."""
    sb.codex_store()
    sb.put_claude(CLAUDE_GUID, CLAUDE_FIXTURE, sb.root / "where-the-session-ran")
    link = _claude_project_behind_a_symlink(sb, sb.root / "another-project")
    rc, report = sb.run("codex", "--session", CLAUDE_GUID)
    _assert_store_unlistable(sb, rc, report, link)


def test_automatic_fallback_with_this_directorys_claude_project_symlinked_fails_closed(sb):
    """This directory's Claude project is a link. A readable Codex thread for
    the directory means skipping the link still selects a session, and
    following it selects one too, so both shortcuts return rc 0."""
    sb.put_codex(CODEX_NAME, CODEX_FIXTURE, cwd=sb.cwd)
    link = _claude_project_behind_a_symlink(sb, sb.cwd)
    rc, report = sb.run("claude")
    _assert_store_unlistable(sb, rc, report, link)


def _symlinked_home(sb):
    """HOME as a link to a real directory. The Claude store sits beneath the
    configured root, not behind a link inside the store."""
    real = sb.root / "home-real"
    real.mkdir()
    sb.home.rmdir()
    os.symlink(str(real), str(sb.home))


def test_explicit_claude_source_under_a_symlinked_home_restores_context(sb):
    _symlinked_home(sb)
    sb.put_claude(CLAUDE_GUID, CLAUDE_FIXTURE, sb.root / "where-the-session-ran")
    rc, report = sb.run("claude", "--session", CLAUDE_GUID)
    assert rc == 0, _outcome(report)
    assert report.get("error") is None, _outcome(report)
    assert report["session"] == CLAUDE_GUID
    assert report["provider"] == "claude"
    assert report["messages"] == 699


def test_automatic_fallback_under_a_symlinked_home_picks_the_claude_session(sb):
    _symlinked_home(sb)
    sb.put_claude(CLAUDE_GUID, CLAUDE_FIXTURE, sb.cwd)
    rc, report = sb.run("claude")
    assert rc == 0, _outcome(report)
    assert report.get("error") is None, _outcome(report)
    assert report["session"] == CLAUDE_GUID
    assert report["provider"] == "claude"
    assert report["source"] == "transcript_fallback"


# Round 3. The lookup rejects a link only where it descends into an entry or
# reads it as a transcript. A rollout or <id>.jsonl that is itself a link fails
# closed. The Claude projects root is the effective store root, so it may be
# a link. A project child the lookup never reads, such as memory/, is ignored.

def _paged_thread_with_a_symlinked_window(sb):
    """The paginated thread recorded in the invoking directory, with the base
    in the real sessions/2026/09/21 and the window's name in the real
    sessions/2026/09/23 a link to an intact window file outside the store.
    Skipping the link reports the base alone and following it reports both
    files, so either shortcut returns rc 0 and fails the test."""
    sb.put_codex(PAGED_BASE_NAME, PAGED_BASE, day="2026/09/21", cwd=sb.cwd)
    outside = sb.root / "window-outside.jsonl"
    outside.write_text(_relocate(open(PAGED_WINDOW).read(), str(sb.cwd)))
    day = sb.codex_store() / "2026" / "09" / "23"
    day.mkdir(parents=True)
    link = day / PAGED_WINDOW_NAME
    os.symlink(str(outside), str(link))
    return link


def test_explicit_paginated_codex_thread_with_a_symlinked_rollout_file_fails_closed(sb):
    sb.claude_store()
    link = _paged_thread_with_a_symlinked_window(sb)
    rc, report = sb.run("claude", "--session", PAGED_GUID)
    _assert_store_unlistable(sb, rc, report, link)


def test_automatic_paginated_codex_thread_with_a_symlinked_rollout_file_fails_closed(sb):
    link = _paged_thread_with_a_symlinked_window(sb)
    rc, report = sb.run("claude")
    _assert_store_unlistable(sb, rc, report, link)


def _claude_transcript_behind_a_symlink(sb, project_dir):
    """<CLAUDE_GUID>.jsonl in a real project directory for project_dir as a
    link to a real copy of the transcript outside the store."""
    outside = sb.root / "transcript-outside.jsonl"
    outside.write_bytes(open(CLAUDE_FIXTURE, "rb").read())
    project = sb.claude_store() / _slug(str(project_dir))
    project.mkdir()
    link = project / (CLAUDE_GUID + ".jsonl")
    os.symlink(str(outside), str(link))
    return link


def test_explicit_lookup_with_a_symlinked_claude_transcript_fails_closed(sb):
    """The id is valid in a real project. Skipping the link reports that copy
    and following it finds a second owner, so only failing closed on the
    link passes."""
    sb.codex_store()
    sb.put_claude(CLAUDE_GUID, CLAUDE_FIXTURE, sb.root / "where-the-session-ran")
    link = _claude_transcript_behind_a_symlink(sb, sb.root / "another-project")
    rc, report = sb.run("codex", "--session", CLAUDE_GUID)
    _assert_store_unlistable(sb, rc, report, link)


def test_automatic_fallback_with_a_symlinked_claude_transcript_fails_closed(sb):
    """A readable Codex thread for the directory means skipping the link
    still selects a session, and following it selects one too, so both
    shortcuts return rc 0."""
    sb.put_codex(CODEX_NAME, CODEX_FIXTURE, cwd=sb.cwd)
    link = _claude_transcript_behind_a_symlink(sb, sb.cwd)
    rc, report = sb.run("claude")
    _assert_store_unlistable(sb, rc, report, link)


def _symlinked_claude_projects_root(sb):
    """~/.claude/projects as a link to a real projects directory."""
    real = sb.root / "projects-real"
    real.mkdir()
    (sb.home / ".claude").mkdir()
    os.symlink(str(real), str(sb.home / ".claude" / "projects"))


def test_explicit_claude_source_under_a_symlinked_projects_root_restores_context(sb):
    _symlinked_claude_projects_root(sb)
    sb.codex_store()
    sb.put_claude(CLAUDE_GUID, CLAUDE_FIXTURE, sb.root / "where-the-session-ran")
    rc, report = sb.run("codex", "--session", CLAUDE_GUID)
    assert rc == 0, _outcome(report)
    assert report.get("error") is None, _outcome(report)
    assert report["session"] == CLAUDE_GUID
    assert report["provider"] == "claude"
    assert report["messages"] == 699


def test_automatic_fallback_under_a_symlinked_projects_root_picks_the_claude_session(sb):
    _symlinked_claude_projects_root(sb)
    sb.put_claude(CLAUDE_GUID, CLAUDE_FIXTURE, sb.cwd)
    rc, report = sb.run("claude")
    assert rc == 0, _outcome(report)
    assert report.get("error") is None, _outcome(report)
    assert report["session"] == CLAUDE_GUID
    assert report["provider"] == "claude"
    assert report["source"] == "transcript_fallback"


def test_automatic_fallback_ignores_a_symlinked_memory_directory_in_this_project(sb):
    """Regression pin: memory stores sync as a link inside a Claude project,
    as ~/.claude/projects/-Users-alex/memory does on the MacBook. The lookup
    reads only <id>.jsonl entries there, so the link is not store content."""
    sb.put_claude(CLAUDE_GUID, CLAUDE_FIXTURE, sb.cwd)
    outside = sb.root / "memory-outside"
    outside.mkdir()
    (outside / "MEMORY.md").write_text("- [Note](note.md)\n")
    os.symlink(str(outside), str(sb.claude_store() / _slug(str(sb.cwd)) / "memory"))
    rc, report = sb.run("claude")
    assert rc == 0, _outcome(report)
    assert report.get("error") is None, _outcome(report)
    assert report["session"] == CLAUDE_GUID
    assert report["provider"] == "claude"
    assert report["source"] == "transcript_fallback"


def test_explicit_codex_source_with_no_claude_store_restores_context(sb):
    """A machine that never ran Claude has no ~/.claude at all."""
    sb.put_codex(CODEX_NAME, CODEX_FIXTURE)
    assert not (sb.home / ".claude").exists()
    rc, report = sb.run("codex", "--session", CODEX_GUID)
    assert rc == 0, _outcome(report)
    _assert_codex_root_context(report)


def test_explicit_claude_source_with_no_codex_home_restores_context(sb):
    """A machine that never ran Codex has no CODEX_HOME at all."""
    sb.put_claude(CLAUDE_GUID, CLAUDE_FIXTURE, sb.root / "where-the-session-ran")
    assert not sb.codex_home.exists()
    rc, report = sb.run("claude", "--session", CLAUDE_GUID)
    assert rc == 0, _outcome(report)
    assert report.get("error") is None, _outcome(report)
    assert report["session"] == CLAUDE_GUID
    assert report["provider"] == "claude"
    assert report["messages"] == 699


def test_automatic_fallback_with_no_codex_home_picks_the_claude_session(sb):
    sb.put_claude(CLAUDE_GUID, CLAUDE_FIXTURE, sb.cwd)
    assert not sb.codex_home.exists()
    rc, report = sb.run("claude")
    assert rc == 0, _outcome(report)
    assert report.get("error") is None, _outcome(report)
    assert report["session"] == CLAUDE_GUID
    assert report["provider"] == "claude"
    assert report["source"] == "transcript_fallback"


# ================================================================== fixture redaction

PLACEHOLDER = re.compile(r"^\[REDACTED TEXT #\d+\]$")
REDACTED_PATH = re.compile(r"^/redacted/\[REDACTED TEXT #\d+\]$")


@pytest.mark.parametrize("fixture", [CODEX_FIXTURE, PAGED_BASE, PAGED_WINDOW, SUBAGENT_FIXTURE],
                         ids=os.path.basename)
def test_redact_commands_fixtures_keep_only_placeholder_command_fields(fixture):
    """These fixtures were produced with --redact-commands (PROVENANCE.md).
    A regeneration without it would put client command text, output, cwd or
    changed paths into the repo and still pass every behavior test. Reads
    the committed fixture only. Violations are collected as (row, field)
    pairs and asserted once, so a failure prints no field value."""
    commands = 0
    bad = []
    for n, line in enumerate(open(fixture)):
        item = (json.loads(line).get("payload") or {}).get("item") or {}
        if item.get("type") == "CommandExecution":
            commands += 1
            command = item.get("command") or []
            if command[:-1] not in (["/bin/zsh", "-lc"], ["/bin/zsh", "-c"]):
                bad.append((n, "shell"))
            if not command or not PLACEHOLDER.match(command[-1]):
                bad.append((n, "command"))
            if not PLACEHOLDER.match(item.get("aggregated_output") or ""):
                bad.append((n, "aggregated_output"))
            if item.get("cwd") != "/redacted":
                bad.append((n, "cwd"))
        elif item.get("type") == "FileChange":
            if not all(REDACTED_PATH.match(p) for p in item.get("changes") or {}):
                bad.append((n, "changes"))
    assert not bad, bad
    if fixture in (CODEX_FIXTURE, PAGED_BASE, PAGED_WINDOW):
        assert commands > 0, "no CommandExecution rows: the invariant would be vacuous"


# Pruning uses the same real captured sources as reconstruction. Handoffs
# are contract inputs; no transcript records are invented for these cases.
def _put_prune_handoff(sb, guid):
    from test_pickup import _handoff, _write_handoff

    path = sb.state / (guid + ".json")
    _write_handoff(path, _handoff(
        str(sb.cwd), str(sb.cwd), "main", "Resume captured session", "Continue",
        "2026-09-06T00:00:00Z", session_id=guid))
    return path


@pytest.mark.parametrize("flavor", ["claude", "codex"])
@pytest.mark.parametrize("archived", [False, True])
def test_prune_keeps_existing_codex_rollout_and_archives_missing_one(sb, flavor, archived):
    rollout = sb.put_codex(CODEX_NAME, CODEX_FIXTURE, archived=archived)
    handoff = _put_prune_handoff(sb, CODEX_GUID)
    env = {"CONTINUITY_CONFIG": str(sb.root / "absent-config.json"),
           "PICKUP_PRUNE_DAYS": "7"}

    rc, report = sb.run(flavor, "--prune", env_extra=env)
    assert rc == 0, report
    assert report["prune_candidates"] == []
    assert report["moved"] == []
    assert handoff.is_file()

    rollout.unlink()
    rc, report = sb.run(flavor, "--prune", env_extra=env)
    assert rc == 0, report
    assert [(row["session_id"], row["reason"]) for row in report["moved"]] == [
        (CODEX_GUID, "missing_transcript")]
    assert not handoff.exists()
    assert (sb.state / "archive" / handoff.name).is_file()


@pytest.mark.parametrize("window_archived", [False, True])
@pytest.mark.parametrize("newest_days, stale", [(6, False), (7, True), (8, True)])
def test_prune_ages_codex_thread_by_newest_rollout(sb, window_archived, newest_days, stale):
    base = sb.put_codex(PAGED_BASE_NAME, PAGED_BASE, day="2026/09/21")
    window = sb.put_codex(PAGED_WINDOW_NAME, PAGED_WINDOW, day="2026/09/23",
                          archived=window_archived)
    handoff = _put_prune_handoff(sb, PAGED_GUID)
    now = time.time()
    os.utime(base, (now - 30 * 86400, now - 30 * 86400))
    os.utime(window, (now - newest_days * 86400, now - newest_days * 86400))

    rc, report = sb.run("codex", env_extra={
        "CONTINUITY_CONFIG": str(sb.root / "absent-config.json"),
        "PICKUP_PRUNE_DAYS": "7"})
    assert rc == 0, report
    expected = [(PAGED_GUID, "stale_transcript")] if stale else []
    assert [(row["session_id"], row["reason"]) for row in report["prune_candidates"]] == expected
    assert handoff.is_file()  # Listing is read-only even for stale sessions.


@pytest.mark.parametrize("config_days, override, age_days, stale", [
    (14, "", 8, False),
    (3, "", 4, True),
    (14, "3", 4, True),
    (3, "14", 8, False),
    (None, "", 7, True),
])
@pytest.mark.parametrize("location", ["explicit", "xdg", "default"])
def test_prune_threshold_is_shared_config_then_environment_then_default(
        sb, config_days, override, age_days, stale, location):
    claude = sb.put_claude(CLAUDE_GUID, CLAUDE_FIXTURE, sb.cwd)
    codex = sb.put_codex(CODEX_NAME, CODEX_FIXTURE)
    for guid in (CLAUDE_GUID, CODEX_GUID):
        _put_prune_handoff(sb, guid)
    modified = time.time() - age_days * 86400
    for source in (claude, codex):
        os.utime(source, (modified, modified))
    env = {"CONTINUITY_CONFIG": "", "XDG_CONFIG_HOME": "",
           "PICKUP_PRUNE_DAYS": override}
    if location == "explicit":
        config = sb.root / "config.json"
        env["CONTINUITY_CONFIG"] = str(config)
    elif location == "xdg":
        env["XDG_CONFIG_HOME"] = str(sb.root / "xdg")
        config = sb.root / "xdg" / "continuity" / "config.json"
    else:
        config = sb.home / ".config" / "continuity" / "config.json"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(json.dumps({} if config_days is None else {"prune_days": config_days}))

    rc, report = sb.run("claude", env_extra=env)
    assert rc == 0, report
    expected = {CLAUDE_GUID: "stale_transcript", CODEX_GUID: "stale_transcript"} if stale else {}
    assert {row["session_id"]: row["reason"] for row in report["prune_candidates"]} == expected


@pytest.mark.parametrize("invalid", [0, -1, True, 1.5, "7", [], {}])
def test_invalid_prune_days_configuration_refuses_archiving(sb, invalid):
    handoff = _put_prune_handoff(sb, CODEX_GUID)
    config = sb.root / "config.json"
    config.write_text(json.dumps({"prune_days": invalid}))

    rc, report = sb.run("codex", "--prune", env_extra={
        "CONTINUITY_CONFIG": str(config), "PICKUP_PRUNE_DAYS": ""})
    assert rc != 0
    assert report["error"] == "handoff_config_error"
    assert "prune_days" in report["message"]
    assert handoff.is_file()


def test_prune_refuses_unknown_codex_store_before_archiving(sb, unlistable):
    handoff = _put_prune_handoff(sb, CODEX_GUID)
    rollout = sb.put_codex(CODEX_NAME, CODEX_FIXTURE)
    unlistable(rollout.parent)

    rc, report = sb.run("codex", "--prune", env_extra={
        "CONTINUITY_CONFIG": str(sb.root / "absent-config.json"),
        "PICKUP_PRUNE_DAYS": "7"})
    assert rc != 0
    assert report["error"] == "session_store_unavailable"
    assert handoff.is_file()
