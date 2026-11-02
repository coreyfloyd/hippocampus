#!/usr/bin/env python3
"""Stdlib-only handoff discovery and cross-provider transcript reconstruction.

Prints a version-2 JSON object; the agent renders it as a resume briefing.
Git checks carry their own provenance. Record pointers remain handoff data.
"""
import datetime
import json
import os
import re
import stat
import subprocess
import sys
from collections import defaultdict

REPORT_VERSION = 2
HANDOFF_SCHEMA_VERSION = 2


# ================================================================== handoff-first resume (#1024)
# Handoff discovery deliberately owns no harness-specific dependency. The
# candidate interface accepts only a state directory and current subject; a
# handoff itself supplies its repository, branch, anchors, and resume text.
# That makes this stdlib-only module movable without importing ticket-update,
# record-update, factory, or issue-workflow.

def _canonical(path):
    return os.path.realpath(os.path.abspath(path))


def _utc_now():
    return datetime.datetime.now(datetime.timezone.utc)


def _parse_timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return None


def _age(value):
    then = _parse_timestamp(value)
    if then is None:
        return "unknown"
    seconds = max(0, int((_utc_now() - then).total_seconds()))
    if seconds < 60:
        return "%ds" % seconds
    if seconds < 3600:
        return "%dm" % (seconds // 60)
    if seconds < 86400:
        return "%dh" % (seconds // 3600)
    return "%dd" % (seconds // 86400)


def transcript_path(home, cwd, session_id):
    """Return Claude Code's transcript path for one stored handoff subject."""
    slug = cwd.replace("/", "-").replace(".", "-")
    return os.path.join(home, ".claude", "projects", slug, session_id + ".jsonl")


def _prune_days(value=None):
    raw = str(value if value is not None else os.environ.get("PICKUP_PRUNE_DAYS", "7"))
    try:
        days = int(raw)
    except ValueError:
        days = 7
    return days if days > 0 else 7


def prune_candidates(state_dir, home, prune_days=None, now=None, codex_home=None):
    """List handoffs whose transcript is absent or older than the threshold."""
    now = now or _utc_now()
    threshold = _prune_days(prune_days) * 86400
    codex_home = codex_home or os.environ.get("CODEX_HOME") or os.path.join(home, ".codex")
    codex_files = None
    rows = []
    try:
        names = sorted(os.listdir(state_dir))
    except OSError:
        return rows
    for name in names:
        if not name.endswith(".json"):
            continue
        path = os.path.join(state_dir, name)
        handoff = _load_handoff(path)
        if handoff is None:
            continue
        subject = handoff["subject"]
        session_id = subject.get("session_id")
        cwd = subject.get("working_directory")
        if not isinstance(session_id, str) or not session_id or not isinstance(cwd, str):
            continue
        # Enumerate once per pass, only when there is a valid handoff. The
        # existing store walker includes archived and paginated rollouts and
        # refuses unknown store state before any candidate can be archived.
        if codex_files is None:
            codex_files = defaultdict(list)
            for rollout, thread_id in codex_rollouts(codex_home):
                codex_files[thread_id].append(rollout)
        transcript = transcript_path(home, cwd, session_id)
        files = list(codex_files.get(session_id, []))
        if os.path.isfile(transcript):
            files.append(transcript)
        if not files:
            rows.append({"path": path, "session_id": session_id,
                         "reason": "missing_transcript", "age": _age(handoff.get("written_at"))})
            continue
        try:
            newest_mtime = max(os.path.getmtime(source) for source in files)
        except OSError as exc:
            raise _store_unavailable("session transcript", exc.filename or session_id, exc)
        modified = datetime.datetime.fromtimestamp(newest_mtime, tz=datetime.timezone.utc)
        if (now - modified).total_seconds() >= threshold:
            rows.append({"path": path, "session_id": session_id,
                         "reason": "stale_transcript", "age": _age(modified.isoformat())})
    return rows


def archive_prune_candidates(state_dir, candidates):
    """Move candidates under archive/, preserving every source as a file."""
    archive_dir = os.path.join(state_dir, "archive")
    os.makedirs(archive_dir, exist_ok=True)
    moved = []
    for row in candidates:
        source = row["path"]
        target = os.path.join(archive_dir, os.path.basename(source))
        if os.path.exists(target):
            stem, extension = os.path.splitext(target)
            suffix = 1
            while os.path.exists("%s.%d%s" % (stem, suffix, extension)):
                suffix += 1
            target = "%s.%d%s" % (stem, suffix, extension)
        os.rename(source, target)
        moved.append({"from": source, "to": target,
                      "session_id": row["session_id"], "reason": row["reason"],
                      "age": row["age"]})
    return moved


def _load_handoff_with_reason(path):
    """Load only valid v2 handoffs; discovery must tolerate stale/corrupt
    neighbour files instead of making every resume unavailable."""
    try:
        with open(path) as f:
            data = json.load(f)
    except OSError:
        return None, "unreadable"
    except (ValueError, TypeError):
        return None, "invalid_json"
    if not isinstance(data, dict) or data.get("schema_version") != HANDOFF_SCHEMA_VERSION:
        return None, "unsupported_schema"
    if not isinstance(data.get("subject"), dict) or not isinstance(data.get("git"), dict):
        return None, "missing_subject_or_git"
    if not isinstance(data["subject"].get("working_directory"), str) or not data["subject"]["working_directory"]:
        return None, "invalid_subject"
    if not isinstance(data.get("resume"), dict):
        return None, "missing_resume"
    return data, None


def _load_handoff(path):
    return _load_handoff_with_reason(path)[0]


def handoff_candidates(state_dir, current_cwd, include_skipped=False):
    """Return candidates ordered current subject, repository siblings, then
    all other subjects. A candidate is derived at read time, never indexed."""
    current = _canonical(current_cwd)
    raw = []
    skipped = []
    try:
        names = sorted(os.listdir(state_dir))
    except OSError:
        return ([], skipped) if include_skipped else []
    for name in names:
        if not name.endswith(".json"):
            continue
        path = os.path.join(state_dir, name)
        data, reason = _load_handoff_with_reason(path)
        if data is None:
            skipped.append({"path": path, "reason": reason})
            continue
        subject = data["subject"].get("working_directory")
        repo = data["git"].get("repository_root")
        resume = data["resume"]
        if not isinstance(subject, str) or not isinstance(repo, str):
            continue
        raw.append((path, data, _canonical(subject)))

    # A fresh worktree may have no readable .git yet. Its own handoff still
    # records the repository identity, which is the authoritative grouping
    # input for this feature; only then fall back to a live git lookup.
    current_repo = None
    for _, data, subject in raw:
        if subject == current:
            root = data["git"]["repository_root"]
            # An empty root means the subject is outside any repository; it
            # must never canonicalize to the process cwd and group as a sibling.
            current_repo = _canonical(root) if root else None
            break
    if current_repo is None:
        current_repo = _repository_root(current_cwd)
    rows = []
    for path, data, canonical_subject in raw:
        subject = data["subject"]["working_directory"]
        repo = data["git"]["repository_root"]
        resume = data["resume"]
        if canonical_subject == current:
            group, rank = "this_directory", 0
        elif repo and current_repo is not None and _canonical(repo) == current_repo:
            group, rank = "sibling_worktrees", 1
        else:
            group, rank = "elsewhere", 2
        rows.append({
            "group": group,
            "subject": subject,
            "headline": str(resume.get("headline") or ""),
            "next_action": str(resume.get("next_action") or ""),
            "branch": data["git"].get("branch") or None,
            "age": _age(data.get("written_at")),
            "written_at": data.get("written_at"),
            "path": path,
            "session_id": data["subject"].get("session_id"),
            "_rank": rank,
            "_sort_time": _parse_timestamp(data.get("written_at")),
        })
    rows.sort(key=lambda r: (r["_rank"],
                             0 if r["_sort_time"] is not None else 1,
                             -(r["_sort_time"] - datetime.datetime(1970, 1, 1,
                                                                      tzinfo=datetime.timezone.utc)).total_seconds()
                             if r["_sort_time"] is not None else 0,
                             r["path"]))
    for row in rows:
        del row["_rank"]
        del row["_sort_time"]
    return (rows, skipped) if include_skipped else rows


def _repository_root(cwd):
    """Repository identity for grouping. Git's common directory is stable
    across linked worktrees; unreadable/non-git directories stay distinct."""
    common = git(cwd, "rev-parse", "--git-common-dir")
    if not common:
        return _canonical(cwd)
    if not os.path.isabs(common):
        common = os.path.join(cwd, common)
    return _canonical(os.path.dirname(os.path.normpath(common)))


def handoff_briefing(path, no_commitments=False):
    """Build the directory-lens briefing shape from a selected handoff.

    Handoff text remains inferred. Git checks state their own provenance.
    """
    handoff = _load_handoff(path)
    if handoff is None:
        return error_report("invalid_handoff", "no valid schema-v2 handoff at %s" % path)
    subject = handoff["subject"].get("working_directory")
    branch = handoff["git"].get("branch")
    exists = bool(subject and branch and git_ok(subject, "rev-parse", "--verify", "--quiet",
                                                str(branch) + "^{commit}"))
    head = git(subject, "rev-parse", "--short", str(branch)) if exists else None
    git_provenance = "validated: git rev-parse" if exists else "inferred: handoff git block; branch unavailable"
    resume = handoff["resume"]
    files = handoff.get("uncommitted_files", [])
    files = files if isinstance(files, list) else []
    loops = resume.get("open_loops", [])
    loops = loops if isinstance(loops, list) else []
    report = {
        "version": REPORT_VERSION,
        "source": "handoff",
        "notice": "Selected handoff; transcript miner was not used.",
        "session": handoff["subject"].get("session_id"),
        "git": {"branch": branch, "head": head, "exists": exists,
                "on_main": None, "unmerged": None, "ahead_behind": None},
        "branches": [],
        "resume": resume,
        "handoff": handoff,
        "uncommitted_files": files,
        "provenance": "validated_or_inferred_required",
        "briefing": [
            {"line": resume.get("headline") or "", "provenance": "inferred: handoff resume block"},
            {"line": resume.get("next_action") or "", "provenance": "inferred: handoff resume block"},
            {"line": "branch %s" % (branch or "unknown"), "provenance": git_provenance},
            {"line": "No record read is bound.", "provenance": "validated: pickup has no record-read binding"},
        ] + [
            {"line": "Uncommitted file: %s" % filename, "provenance": "inferred: handoff ledger snapshot"}
            for filename in files
        ] + [
            {"line": "Session summary: %s" % resume.get("session_summary", ""), "provenance": "inferred: handoff resume block"}
        ] * bool(resume.get("session_summary")) + [
            {"line": ("Commitments from handoff: " if isinstance(loop, dict) and loop.get("type") == "commitment" else "") + json.dumps(loop, ensure_ascii=False), "provenance": "inferred: handoff open loop"}
            for loop in loops
        ],
    }

    reader = os.environ.get("PICKUP_RECORD_HELPER") or os.path.join(
        os.path.dirname(os.path.realpath(__file__)), "../../../scripts/lib/pickup_record.py")
    args = [sys.executable, reader]
    if no_commitments:
        args.append("--no-commitments")
    try:
        result = subprocess.run(args, input=json.dumps(report), text=True,
                                capture_output=True, timeout=30)
        if result.returncode != 0:
            reason = " ".join(result.stderr.split()) or "no diagnostic on stderr"
            raise ValueError("exited %s: %s" % (result.returncode, reason))
        try:
            prepared = json.loads(result.stdout)
        except ValueError as error:
            raise ValueError("invalid JSON output: " + str(error)) from None
        if not isinstance(prepared, dict):
            raise ValueError("expected a JSON object from helper")
        return prepared
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        report["briefing"] = [row for row in report["briefing"]
                              if row["line"] != "No record read is bound."]
        message = "record-read helper %s: %s" % (reader, error)
        report.update(error="record_helper_failed", message=message)
        report["briefing"].append({"line": message,
                                   "provenance": "validated: record-read helper failed"})
        return report


def error_report(code, message, **fields):
    """One stable envelope for every directory-lens error object."""
    report = {"version": REPORT_VERSION, "error": code, "message": message}
    report.update(fields)
    return report


def handoff_candidates_report(candidates, skipped, prune=None):
    return {"version": REPORT_VERSION, "source": "handoff_candidates",
            "candidates": candidates, "skipped": skipped,
            "prune_candidates": prune or []}


def report_exit_status(report):
    """Normal absence is an answer; malformed selections and engine errors are failures."""
    if not report.get("error"):
        return 0
    return 0 if report["error"] in ("no_transcript_directory", "no_other_session") else 1


# ================================================================== transcript primitives

def load(path):
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows


def text(m):
    c = m.get("message", {}).get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return " ".join(p.get("text", "") for p in c
                         if isinstance(p, dict) and p.get("type") == "text")
    return ""


def real(r):
    return not r.get("isMeta") and not r.get("isSidechain")


def stop_reason(r):
    return r.get("message", {}).get("stop_reason")


def has_tool_result(r):
    """A4: a user row synthesized to carry a tool_result, not something the user
    typed. text() already returns "" for these in the common case, but a row
    can carry a tool_result block ALONGSIDE a text block (e.g. an image
    result plus a caption) — that combination must still be excluded from
    message selection, not just get lucky on an empty string."""
    c = r.get("message", {}).get("content")
    if not isinstance(c, list):
        return False
    return any(isinstance(p, dict) and p.get("type") == "tool_result" for p in c)


def tool_use_blocks(r):
    """assistant row -> list of its tool_use content blocks."""
    if r.get("type") != "assistant":
        return []
    c = r.get("message", {}).get("content")
    if not isinstance(c, list):
        return []
    return [p for p in c if isinstance(p, dict) and p.get("type") == "tool_use"]


def tool_result_text(block):
    c = block.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return " ".join(p.get("text", "") for p in c
                         if isinstance(p, dict) and p.get("type") == "text")
    return ""


def substantive(rows):
    return any(text(r).strip() for r in rows
               if r.get("type") == "assistant" and real(r))


def is_prompt_noise(t):
    return not t or t.startswith("<") or "system-reminder" in t[:40]


# ================================================================== A1-A4 message capture

def first_user_message(users):
    """A2 — first real user prompt. Uncapped."""
    for r in users:
        if has_tool_result(r):
            continue
        t = text(r).strip()
        if t and not is_prompt_noise(t):
            return t, r.get("timestamp")
    return "", None


def last_user_message(users):
    """A3 — last user instruction. Uncapped."""
    for r in reversed(users):
        if has_tool_result(r):
            continue
        t = text(r).strip()
        if t and not t.lstrip().startswith("<"):
            return t, r.get("timestamp")
    return "", None


def last_assistant_message(asst):
    """A1 — last assistant message sent TO the user, not the last row with any
    text. stop_reason == "end_turn" is what separates a sign-off from a
    mid-work narration turn that happens to include prose alongside/instead
    of a tool call.

    Falls back to the old last-any-text scan when no end_turn row has text —
    a session that was interrupted mid-response can end on stop_reason None
    or max_tokens, and that is still the honest stopping point to report."""
    for r in reversed(asst):
        if stop_reason(r) != "end_turn":
            continue
        t = text(r).strip()
        if t:
            return t, r.get("timestamp")
    for r in reversed(asst):
        t = text(r).strip()
        if t:
            return t, r.get("timestamp")
    return "", None


# ================================================================== git helpers (ported #909, cwd-parameterized)
# CLAUDE.md gotcha: never reuse a cwd-implicit git() across repos. Every call
# here takes an explicit cwd/repo argument.

def git(cwd, *args):
    try:
        return subprocess.run(["git"] + list(args), capture_output=True,
                               text=True, cwd=cwd).stdout.strip()
    except Exception:
        return ""


def git_ok(cwd, *args):
    try:
        return subprocess.run(["git"] + list(args), capture_output=True,
                               text=True, cwd=cwd).returncode == 0
    except Exception:
        return False


def default_trunk(repo_cwd=None):
    """#910 eval F9 (round 1) hardcoded "main" at six new call sites,
    silently breaking every classification and log range on a
    master/trunk/develop repo. round 1's fix added PICKUP_TRUNK but
    rejected auto-detection on the theory that it meant guessing among
    main/master/trunk/develop by trial — which conflated detection with
    guessing (#910 eval round 2 correction). `git symbolic-ref
    refs/remotes/origin/HEAD` is DETERMINISTIC: it names the one branch the
    remote itself designates as default, and is simply empty when unset —
    never a wrong guess between candidates. PICKUP_TRUNK still wins
    when set (an explicit override always should); "main" is the last
    resort only for a repo with no remote HEAD configured at all, which is
    not a guess between competing names either — it is the one case
    nothing else answers."""
    override = os.environ.get("PICKUP_TRUNK")
    if override:
        return override
    if repo_cwd:
        ref = git(repo_cwd, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
        if ref and "/" in ref:
            return ref.split("/", 1)[1]
    return "main"


def worktree_map(repo_cwd):
    """path -> branch name (or None if detached), for the repo containing
    repo_cwd. Fails open to {}."""
    out = git(repo_cwd, "worktree", "list", "--porcelain")
    m = {}
    cur = None
    for line in out.splitlines():
        if line.startswith("worktree "):
            cur = line[len("worktree "):].strip()
            m[cur] = None
        elif line.startswith("branch ") and cur:
            ref = line[len("branch "):].strip()
            m[cur] = ref[len("refs/heads/"):] if ref.startswith("refs/heads/") else ref
    return m


def status_short(path):
    """None means "could not read" — never collapse a git error into clean."""
    try:
        p = subprocess.run(["git", "-C", path, "status", "--short"],
                            capture_output=True, text=True)
        return p.stdout if p.returncode == 0 else None
    except Exception:
        return None


def status_paths(status_output):
    """Parse `git status --short` lines into a plain path list. Handles the
    rename form "R  old -> new" by keeping the new path."""
    paths = []
    if not status_output:
        return paths
    for line in status_output.splitlines():
        if not line or len(line) < 4:
            continue
        p = line[3:].strip()
        if " -> " in p:
            p = p.split(" -> ", 1)[1]
        paths.append(p)
    return paths


def repo_root_for(cwd):
    """Identify the REPO a cwd belongs to, not the worktree directory.
    `git rev-parse --show-toplevel` names the branch directory inside a
    linked worktree — use
    --git-common-dir and take its parent instead, which is stable across
    every worktree of the same repo."""
    common = git(cwd, "rev-parse", "--git-common-dir")
    if not common:
        return None
    if not os.path.isabs(common):
        common = os.path.join(cwd, common)
    return os.path.dirname(os.path.normpath(common))


def merge_log(repo_cwd, trunk):
    """One history walk over the trunk branch, reused for every branch that
    needs it."""
    out = git(repo_cwd, "log", "--merges", trunk, "--format=%h\t%s")
    rows = []
    for line in out.splitlines():
        if "\t" in line:
            h, s = line.split("\t", 1)
            rows.append((h, s))
    return rows


def find_merge(merge_log_rows, branch):
    """Anchored on non-identifier boundaries so "feature-scope" does not
    also match the merge subject for "feature-scope-2" (#909 review
    finding, guarded by test Case E)."""
    pat = re.compile(r"(^|[^A-Za-z0-9_-])" + re.escape(branch) + r"([^A-Za-z0-9_-]|$)")
    for h, s in merge_log_rows:
        if pat.search(s):
            return "%s %s" % (h, s)
    return None


def branch_state(repo_cwd, branch, wt_by_path, path_by_branch, cwd_status, merge_log_rows, trunk):
    rep = {"branch": branch}
    local_exists = git_ok(repo_cwd, "rev-parse", "--verify", "--quiet", branch + "^{commit}")
    path = path_by_branch.get(branch)
    rep["worktree_path"] = path
    rep["worktree_exists"] = bool(path and cwd_status.get(path, {}).get("exists"))
    rep["dirty"] = cwd_status.get(path, {}).get("dirty") if path else None

    if local_exists:
        rep["ref"] = "local"
        on_main = git_ok(repo_cwd, "merge-base", "--is-ancestor", branch, trunk)
    else:
        remote_exists = git_ok(repo_cwd, "rev-parse", "--verify", "--quiet",
                                "refs/remotes/origin/" + branch + "^{commit}")
        if remote_exists:
            rep["ref"] = "remote"
            on_main = git_ok(repo_cwd, "merge-base", "--is-ancestor", "origin/" + branch, trunk)
        else:
            rep["ref"] = "none"
            on_main = None
    rep["on_main"] = on_main
    rep["merge_evidence"] = None

    if rep["worktree_exists"] and rep["dirty"] is None:
        # #910 eval F6: status_short() returning None ("could not read", a
        # git error) must never fall through as falsy into "not dirty". The
        # ONE classification path whose purpose is to raise an alarm was
        # failing toward the reassuring answer — fail toward the alarm
        # instead, distinctly from every other state.
        rep["state"] = "unknown"
    elif rep["dirty"]:
        rep["state"] = "dirty"
    elif on_main is True:
        rep["state"] = "merged"
    elif on_main is False:
        rep["state"] = "clean_unmerged" if rep["worktree_exists"] else "gone_unmerged"
    else:
        mc = find_merge(merge_log_rows, branch)
        rep["merge_evidence"] = mc
        rep["state"] = "landed" if mc else "deleted_no_merge"
    # #910 eval round 2 F5: ALARM_RANK's only consumer used to be the
    # deleted render_text() — a dead constant with a live-looking test. A
    # JSON-only consumer has no severity signal at all without it, and
    # would otherwise have to re-derive SKILL.md's ordering prose. Emit it.
    rep["alarm_rank"] = ALARM_RANK.get(rep["state"], 9)
    return rep


ALARM_RANK = {"unknown": 0, "dirty": 0, "deleted_no_merge": 1, "clean_unmerged": 2,
              "gone_unmerged": 2, "merged": 3, "landed": 3}


# ================================================================== A5b — commit subjects per branch

def _merge_evidence_for(repo_root, rep, merge_log_rows):
    """The merge commit for a branch that state classification didn't already
    resolve one for. branch_state() only looks one up when a branch's ref is
    gone entirely (landed/deleted_no_merge) — but an ALREADY-MERGED branch
    whose local/remote ref still exists also has an empty trunk..branch
    range (it is fully contained in trunk), so branch_commits and
    files_for_repo need the same merge-commit fallback there too. One
    anchored lookup (find_merge, #909's Case E regression guard) reused by
    both instead of a second unanchored path."""
    if rep.get("merge_evidence"):
        return rep["merge_evidence"]
    if merge_log_rows is None:
        return None
    return find_merge(merge_log_rows, rep["branch"])


def branch_commits(repo_root, rep, merge_log_rows, trunk):
    """Commit subjects for one #909 branch report — the session's own
    contemporaneous, ticket-tagged summary of what it did on that branch.

    Returns (commits, source). source distinguishes WHY the list is what it
    is (#910 eval F4: a branch whose contribution genuinely could not be
    resolved was serializing identically to one that touched nothing):

    - "direct"        — trunk..branch (or trunk..origin/branch) is
                         authoritative. For an unmerged branch (on_main is
                         False) an empty range here is a TRUE empty — the
                         branch really has no commits ahead yet (e.g. a
                         "dirty" branch that only has uncommitted work).
    - "merge_evidence" — trunk..branch was empty because the branch is
                         already merged (or its ref is gone entirely), and
                         its own merge commit was found instead.
    - "not_applicable" — ref is gone and no merge was found either; this IS
                         the "deleted_no_merge" alarm state, already
                         distinctly flagged there.
    - "unresolved"     — ref exists, the branch is merged (on_main True),
                         trunk..branch is empty (as it always is once
                         merged), and no merge commit could be found by
                         name either. The branch's `state` still correctly
                         says "merged"; what it CONTAINED is unknown, not
                         empty.
    """
    branch = rep["branch"]
    ref = rep.get("ref")
    on_main = rep.get("on_main")
    lines = []
    if ref == "local":
        out = git(repo_root, "log", "--format=%h %s", trunk + ".." + branch)
        lines = [l for l in out.splitlines() if l]
    elif ref == "remote":
        out = git(repo_root, "log", "--format=%h %s", trunk + "..origin/" + branch)
        lines = [l for l in out.splitlines() if l]
    if lines:
        return lines, "direct"
    if on_main is False:
        # Not yet merged, ref exists, so the direct range IS the ground
        # truth — a genuinely empty range means genuinely no commits ahead.
        return [], "direct"
    evidence = _merge_evidence_for(repo_root, rep, merge_log_rows)
    if evidence:
        return [evidence], "merge_evidence"
    if ref == "none":
        return [], "not_applicable"
    return [], "unresolved"


# ================================================================== A6 — files per repo

_PATH_KEYS = ("file_path", "path", "notebook_path")
_ABS_PATH_RE = re.compile(r"(/[\w.\-]+(?:/[\w.\-]+)+\.[A-Za-z0-9_]{1,10})")


def extract_transcript_paths(rows):
    """A6 — paths this session touched, scraped from tool_use blocks. Direct
    Read/Write/Edit/NotebookEdit calls carry a file_path field; bypass-mode
    edits route through Bash (heredocs, sed, python3 -c) and only show up as
    absolute-path-shaped substrings in the command string (#910: tool-name
    extraction alone caught 5 of 26 real paths in the sample session)."""
    paths = set()
    for r in rows:
        for b in tool_use_blocks(r):
            inp = b.get("input", {})
            if not isinstance(inp, dict):
                continue
            for k in _PATH_KEYS:
                v = inp.get(k)
                if isinstance(v, str) and v.startswith("/"):
                    paths.add(v)
            if b.get("name") == "Bash":
                cmd = inp.get("command", "") or ""
                for m in _ABS_PATH_RE.findall(cmd):
                    paths.add(m)
    return paths


def discover_repos(seen_cwds):
    """Distinct repos among every cwd the transcript named, keyed by repo
    root (identified via repo_root_for, so worktrees of the same repo
    collapse to one entry). Value: the cwds (worktrees) belonging to it."""
    repos = defaultdict(list)
    for c in seen_cwds:
        if not os.path.isdir(c):
            continue
        root = repo_root_for(c)
        if root:
            repos[root].append(c)
    return repos


def files_for_repo(repo_root, cwds, branch_reports_here, transcript_paths, merge_log_rows, trunk,
                    unresolved_branches):
    """A6 — committed + uncommitted + transcript-scraped files for one repo.
    #910 eval F2: earlier drafts also returned a `reconciled` per-path
    {committed,uncommitted,transcript: bool} map — pure restatement of set
    membership already visible in these three lists (measured at 48% of the
    entire JSON payload on the real sample session). Dropped; a consumer
    that wants per-path provenance can intersect the three lists itself at
    negligible cost."""
    committed = set()
    for rep in branch_reports_here:
        found = []
        if rep.get("ref") == "local":
            out = git(repo_root, "log", "--name-only", "--format=", trunk + ".." + rep["branch"])
            found = [l for l in out.splitlines() if l.strip()]
        elif rep.get("ref") == "remote":
            out = git(repo_root, "log", "--name-only", "--format=", trunk + "..origin/" + rep["branch"])
            found = [l for l in out.splitlines() if l.strip()]
        if not found:
            evidence = _merge_evidence_for(repo_root, rep, merge_log_rows)
            if evidence:
                h = evidence.split(" ", 1)[0]
                # A plain `git show` on a merge commit prints no diff at all
                # (needs -m/-c) — diff the merge commit against its first
                # parent instead, which is the total change the merge
                # brought into trunk, i.e. the branch's own contribution.
                out = git(repo_root, "diff", "--name-only", h + "^", h)
                found = [l for l in out.splitlines() if l.strip()]
        committed.update(found)

    uncommitted = set()
    for c in cwds:
        raw = status_short(c)
        uncommitted.update(status_paths(raw))

    scraped = set()
    for p in transcript_paths:
        if p.startswith(repo_root + os.sep):
            scraped.add(os.path.relpath(p, repo_root))

    return {
        "committed": sorted(committed),
        "uncommitted": sorted(uncommitted),
        "transcript_scraped": sorted(scraped),
        # #910 eval F4: names the branches in THIS repo whose contribution
        # could not be resolved (state "merged", ref present, no direct log
        # AND no merge commit found by name) — their real files are simply
        # absent above, not confirmed empty. Cross-reference against
        # branches[].commits_source == "unresolved".
        "unresolved_branches": sorted(unresolved_branches),
    }


# ================================================================== A7 — staleness

def staleness(rows):
    """Timestamp of the last end_turn assistant row, plus how many tool
    calls (assistant rows carrying tool_use, real only) followed it. A
    session that died mid-run can be hours and hundreds of calls past its
    last sign-off with nothing today signaling it."""
    last_end_turn_idx = None
    last_end_turn_ts = None
    for i, r in enumerate(rows):
        if r.get("type") == "assistant" and real(r) and stop_reason(r) == "end_turn":
            last_end_turn_idx = i
            last_end_turn_ts = r.get("timestamp")
    if last_end_turn_idx is None:
        return {"last_end_turn_ts": None, "tool_calls_after": 0, "stale": False}
    after = 0
    for r in rows[last_end_turn_idx + 1:]:
        if r.get("type") == "assistant" and real(r) and tool_use_blocks(r):
            after += 1
    return {"last_end_turn_ts": last_end_turn_ts, "tool_calls_after": after,
            "stale": after > 0}


# ================================================================== session sources (#1453)
# A session id names a transcript in exactly one provider's store. The owner
# is decided by what the stores actually hold, never by the id's UUID
# version or by ambient CLAUDE_*/CODEX_* variables (a nested session carries
# both families). Claude keeps one file per session under
# ~/.claude/projects/<cwd-slug>/<id>.jsonl; Codex keeps one or more rollout
# files per thread under $CODEX_HOME/sessions/YYYY/MM/DD/ and the flat
# $CODEX_HOME/archived_sessions/. A Codex thread is keyed by
# session_meta.payload.id (== the filename thread id). payload.session_id is
# the PARENT thread for a subagent, so it is never a lookup key.

PROVIDER_CLAUDE = "claude"
PROVIDER_CODEX = "codex"

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
# rollout-<YYYY-MM-DDThh-mm-ss>-<thread id>[_<window id>].jsonl — a thread
# split across windows keeps its id and gains a suffix per later file.
_ROLLOUT_RE = re.compile(
    r"^rollout-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-(.+?)(?:_([A-Za-z0-9-]+))?\.jsonl$")
_AGENTS_INJECTION = "# AGENTS.md instructions"


class SourceError(Exception):
    """A session source matched by id but unusable; carries a report code."""

    def __init__(self, code, message):
        Exception.__init__(self, message)
        self.code = code
        self.message = message


def claude_store(home):
    return os.path.join(home, ".claude", "projects")


def codex_stores(codex_home):
    return [os.path.join(codex_home, "sessions"),
            os.path.join(codex_home, "archived_sessions")]


def _store_unavailable(what, path, exc):
    return SourceError("session_store_unavailable",
                       "cannot list %s %s: %s; a session there can be neither ruled in nor out"
                       % (what, path, exc.strerror or exc.__class__.__name__))


def list_store_dir(path, what):
    """Names in one store directory, or None when it does not exist (that
    provider may never have run here). A directory that exists but cannot
    be listed is unknown state and raises session_store_unavailable naming
    it; the message carries the path and errno text, never file content."""
    try:
        return os.listdir(path)
    except (FileNotFoundError, NotADirectoryError):
        return None
    except OSError as exc:
        raise _store_unavailable(what, path, exc)


# Symbolic links. A configured root may resolve through links: HOME,
# CODEX_HOME, and ~/.claude/projects are used as given and never lstat'ed,
# so a relocated root, or a link above one, works. Below a root, every entry
# the lookup descends into or reads as a transcript is lstat'ed before it is
# followed, and a link there raises session_store_unavailable naming the
# link: following it may leave the store, and skipping it may drop a member
# of a thread or a second owner of an id. An entry the lookup neither
# descends into nor reads (memory/ in a Claude project) is not examined.

def _store_link(what, path):
    return SourceError("session_store_unavailable",
                       "%s %s is a symbolic link inside the session store; a session there "
                       "can be neither ruled in nor out" % (what, path))


def lstat_store_entry(path, what):
    """lstat of one store entry, or None when it does not exist. Any other
    error raises session_store_unavailable naming the entry."""
    try:
        return os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        return None
    except OSError as exc:
        raise _store_unavailable(what, path, exc)


def _link_is_traversed(path):
    """Whether a link met while enumerating a store names a directory the
    lookup would descend into. A dangling link names nothing; a link that
    cannot be classified is treated as traversed."""
    try:
        return stat.S_ISDIR(os.stat(path).st_mode)
    except FileNotFoundError:
        return False
    except OSError:
        return True


def _codex_session_tree(top, found):
    """Walk one directory of CODEX_HOME/sessions, lstat before follow. A
    subdirectory is descended; a link that is a rollout or a directory
    raises; a link to any other file is ignored, since it is neither read
    nor descended."""
    for name in sorted(list_store_dir(top, "Codex session directory") or []):
        path = os.path.join(top, name)
        st = lstat_store_entry(path, "Codex session entry")
        if st is None:
            continue
        m = _ROLLOUT_RE.match(name)
        if stat.S_ISLNK(st.st_mode):
            if m or _link_is_traversed(path):
                raise _store_link("Codex session entry", path)
        elif stat.S_ISDIR(st.st_mode):
            _codex_session_tree(path, found)
        elif m and stat.S_ISREG(st.st_mode):
            found.append((path, m.group(1)))


def codex_rollouts(codex_home):
    """Every rollout file in both Codex stores as (path, thread id), from the
    filename alone: active files sit in dated dirs, archived files are flat.
    An absent store contributes nothing. A store, dated, or archive directory
    that exists but cannot be listed raises session_store_unavailable rather
    than being skipped, since it may hold a member of any thread. So does a
    symbolic link at sessions, archived_sessions, any directory in the
    sessions tree, or a rollout file (see Symbolic links above)."""
    active, archived = codex_stores(codex_home)
    found = []
    for top, what in ((active, "Codex sessions directory"), (archived, "Codex archive")):
        st = lstat_store_entry(top, what)
        if st is not None and stat.S_ISLNK(st.st_mode):
            raise _store_link(what, top)
    _codex_session_tree(active, found)
    for name in list_store_dir(archived, "Codex archive") or []:
        m = _ROLLOUT_RE.match(name)
        if not m:
            continue
        path = os.path.join(archived, name)
        st = lstat_store_entry(path, "Codex archived rollout")
        if st is None:
            continue
        if stat.S_ISLNK(st.st_mode):
            raise _store_link("Codex archived rollout", path)
        if stat.S_ISREG(st.st_mode):
            found.append((path, m.group(1)))
    found.sort()
    return found


def claude_project_transcripts(project_dir, exclude=()):
    """Names of the <id>.jsonl transcripts in one Claude project directory,
    or None when it does not exist. The project directory and each
    transcript read from it are lstat'ed first and a link raises; other
    entries, such as a linked memory/, are not examined."""
    st = lstat_store_entry(project_dir, "Claude project directory")
    if st is None:
        return None
    if stat.S_ISLNK(st.st_mode):
        raise _store_link("Claude project directory", project_dir)
    names = list_store_dir(project_dir, "Claude project directory")
    if names is None:
        return None
    kept = []
    for name in names:
        if not name.endswith(".jsonl") or name[:-6] in exclude:
            continue
        path = os.path.join(project_dir, name)
        st = lstat_store_entry(path, "Claude transcript")
        if st is not None and stat.S_ISLNK(st.st_mode):
            raise _store_link("Claude transcript", path)
        kept.append(name)
    return kept


def _first_row(path):
    try:
        with open(path) as f:
            return json.loads(f.readline())
    except Exception:
        return None


def load_source_rows(path, what):
    """Every row of one provider source file. Unlike load(), a non-empty line
    that does not decode as a JSON object, the final line included, makes the
    file malformed, and so does a read error anywhere in it: the source fails
    rather than being reconstructed with that record missing. Messages carry
    the path and line number, never the record text."""
    rows = []
    try:
        with open(path) as f:
            for number, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    raise SourceError("invalid_session_transcript",
                                      "%s %s has an undecodable record at line %d"
                                      % (what, path, number))
                if not isinstance(row, dict):
                    raise SourceError("invalid_session_transcript",
                                      "%s %s has a non-object record at line %d"
                                      % (what, path, number))
                rows.append(row)
    except UnicodeDecodeError as exc:
        raise SourceError("invalid_session_transcript",
                          "%s %s is not valid text: %s" % (what, path, exc))
    except OSError as exc:
        raise SourceError("invalid_session_transcript",
                          "cannot read %s %s: %s" % (what, path, exc))
    return rows


def load_claude_source(path):
    """Rows of one Claude transcript. Every non-empty record must decode as a
    JSON object, and a file with no user or assistant row is malformed, not
    an empty session."""
    rows = load_source_rows(path, "Claude transcript")
    if not any(r.get("type") in ("user", "assistant") for r in rows):
        raise SourceError("invalid_session_transcript",
                          "Claude transcript %s has no parseable user or assistant record" % path)
    return rows


def _codex_text(parts):
    if isinstance(parts, str):
        return parts
    return "\n".join(p.get("text", "") for p in parts or []
                     if isinstance(p, dict) and isinstance(p.get("text"), str))


def _codex_command(command):
    if isinstance(command, str):
        return command
    command = [str(c) for c in command or []]
    if len(command) >= 3 and command[-2] in ("-lc", "-c"):
        return command[-1]
    return " ".join(command)


def normalize_codex_rows(raw, thread_id):
    """Codex rollout records -> the Claude-shaped rows build_report reads.

    User turns come from UserMessage items (older rollouts: event_msg
    user_message; oldest: response_item user text minus injected context).
    Assistant text comes from response_item assistant messages, and the
    final_answer phase is Claude's end_turn. Each CommandExecution becomes a
    Bash tool_use plus its paired tool_result, and each FileChange an Edit
    tool_use per path, so file extraction reads them unchanged.
    cwd comes from this thread's session_meta and each turn_context; the
    branch from session_meta.git (Codex records no per-turn branch)."""
    def event(row, kind):
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        return row.get("type") == "event_msg" and payload.get("type") == kind, payload

    def item_type(row):
        ok, payload = event(row, "item_completed")
        item = payload.get("item") if ok else None
        return item.get("type") if isinstance(item, dict) else None

    if any(item_type(r) == "UserMessage" for r in raw):
        user_source = "item"
    elif any(event(r, "user_message")[0] for r in raw):
        user_source = "event"
    else:
        user_source = "response"

    cwd, branch = None, None
    rows = []

    def emit(kind, ts, message):
        rows.append({"type": kind, "timestamp": ts, "cwd": cwd, "gitBranch": branch,
                     "message": message})

    for r in raw:
        kind = r.get("type")
        payload = r.get("payload") if isinstance(r.get("payload"), dict) else {}
        ts = r.get("timestamp")
        if kind == "session_meta":
            if payload.get("id") == thread_id:
                cwd = payload.get("cwd") or cwd
                branch = (payload.get("git") or {}).get("branch") or branch
                # The session (or window) start, as a meta row: it dates
                # first_ts without counting as a user or assistant turn.
                rows.append({"type": "system", "isMeta": True, "timestamp": ts,
                             "cwd": cwd, "gitBranch": branch})
        elif kind == "turn_context":
            cwd = payload.get("cwd") or cwd
        elif kind == "response_item" and payload.get("type") == "message":
            role = payload.get("role")
            if role == "assistant":
                emit("assistant", ts, {
                    "role": "assistant",
                    "content": [{"type": "text", "text": _codex_text(payload.get("content"))}],
                    "stop_reason": "end_turn" if payload.get("phase") == "final_answer" else None})
            elif role == "user" and user_source == "response":
                parts = [p for p in payload.get("content") or []
                         if isinstance(p, dict) and isinstance(p.get("text"), str)
                         and not p["text"].lstrip().startswith(("<", _AGENTS_INJECTION))]
                t = _codex_text(parts)
                if t.strip():
                    emit("user", ts, {"role": "user", "content": t})
        elif kind == "event_msg":
            etype = payload.get("type")
            if etype == "task_complete":
                rows.append({"type": "system", "isMeta": True, "timestamp": ts,
                             "cwd": cwd, "gitBranch": branch})
            elif etype == "user_message" and user_source == "event":
                emit("user", ts, {"role": "user", "content": payload.get("message") or ""})
            elif etype == "item_completed" and isinstance(payload.get("item"), dict):
                item = payload["item"]
                itype = item.get("type")
                if itype == "UserMessage" and user_source == "item":
                    emit("user", ts, {"role": "user", "content": _codex_text(item.get("content"))})
                elif itype == "CommandExecution":
                    call_id = item.get("id")
                    emit("assistant", ts, {"role": "assistant", "content": [{
                        "type": "tool_use", "id": call_id, "name": "Bash",
                        "input": {"command": _codex_command(item.get("command"))}}]})
                    emit("user", ts, {"role": "user", "content": [{
                        "type": "tool_result", "tool_use_id": call_id,
                        "content": item.get("aggregated_output") or ""}]})
                elif itype == "FileChange":
                    blocks = [{"type": "tool_use", "id": item.get("id"), "name": "Edit",
                               "input": {"file_path": path}}
                              for path in sorted(item.get("changes") or {})]
                    if blocks:
                        emit("assistant", ts, {"role": "assistant", "content": blocks})
    return rows


def load_codex_source(paths, thread_id):
    """Rows of one Codex thread from all of its rollout files, oldest file
    first. Every file must be readable, open with this thread's
    session_meta, and hold only non-empty records that decode as JSON
    objects; any one file failing fails the thread."""
    ordered = []
    for path in paths:
        file_rows = load_source_rows(path, "Codex rollout")
        first = file_rows[0] if file_rows else {}
        payload = first.get("payload")
        if not isinstance(payload, dict) or first.get("type") != "session_meta":
            raise SourceError("invalid_session_transcript",
                              "Codex rollout %s does not open with a parseable session_meta record" % path)
        if payload.get("id") != thread_id:
            raise SourceError("invalid_session_transcript",
                              "Codex rollout %s names thread %s in its filename but %r in session_meta"
                              % (path, thread_id, payload.get("id")))
        ordered.append((first.get("timestamp") or payload.get("timestamp") or "", path, file_rows))
    ordered.sort(key=lambda entry: entry[:2])
    raw = []
    for _ts, _path, file_rows in ordered:
        raw.extend(file_rows)
    rows = normalize_codex_rows(raw, thread_id)
    if not any(r["type"] in ("user", "assistant") for r in rows):
        raise SourceError("invalid_session_transcript",
                          "Codex thread %s has no user or assistant record in %s"
                          % (thread_id, ", ".join(p for _t, p, _r in ordered)))
    return rows, [p for _t, p, _r in ordered]


def resolve_session(home, codex_home, session_id):
    """Find and validate one session id across both stores, independent of
    the caller's cwd. Returns (provider, rows, files) or raises SourceError.

    Fail-closed order: a store directory that exists but cannot be searched,
    or a link to a project directory, transcript, Codex store directory, or
    rollout below the configured roots, fails the lookup before any
    transcript is read, since it may hide a member or a second owner; any
    malformed match fails the lookup, even
    beside a valid one; two valid owners are ambiguous; no match names every
    root searched, and an absent store is reported as unavailable."""
    if not _SESSION_ID_RE.match(session_id or ""):
        raise SourceError("invalid_session_id",
                          "session id %r is not a transcript id (letters, digits, '-' and '_' only)"
                          % session_id)
    claude_root = claude_store(home)
    projects = list_store_dir(claude_root, "Claude projects directory")
    claude_paths = []
    for project in sorted(projects or []):
        project_dir = os.path.join(claude_root, project)
        entry = lstat_store_entry(project_dir, "Claude project directory")
        if entry is None:
            continue
        if stat.S_ISLNK(entry.st_mode):
            if _link_is_traversed(project_dir):
                raise _store_link("Claude project directory", project_dir)
            continue
        if not stat.S_ISDIR(entry.st_mode):
            continue
        path = os.path.join(project_dir, session_id + ".jsonl")
        try:
            mode = os.lstat(path).st_mode
        except (FileNotFoundError, NotADirectoryError):
            continue
        except OSError as exc:
            raise _store_unavailable("Claude project directory", project_dir, exc)
        if stat.S_ISLNK(mode):
            raise _store_link("Claude transcript", path)
        if stat.S_ISREG(mode):
            claude_paths.append(path)
    codex_paths = [p for p, tid in codex_rollouts(codex_home) if tid == session_id]

    if not claude_paths and not codex_paths:
        roots = [claude_root] + codex_stores(codex_home)
        missing = []
        if projects is None:
            missing.append("Claude store %s (from HOME)" % claude_root)
        if not any(os.path.isdir(r) for r in codex_stores(codex_home)):
            missing.append("Codex store %s (from CODEX_HOME, default ~/.codex)" % codex_home)
        if missing:
            raise SourceError("session_store_unavailable",
                              "no transcript for session %s; unavailable: %s; searched %s"
                              % (session_id, "; ".join(missing), ", ".join(roots)))
        raise SourceError("no_such_session",
                          "no transcript for session %s in %s"
                          % (session_id, ", ".join(roots)))

    found = []
    for path in claude_paths:
        found.append((PROVIDER_CLAUDE, load_claude_source(path), [path]))
    if codex_paths:
        rows, files = load_codex_source(codex_paths, session_id)
        found.append((PROVIDER_CODEX, rows, files))
    if len(found) > 1:
        raise SourceError("ambiguous_session",
                          "session %s is a valid transcript in more than one place: %s"
                          % (session_id, "; ".join("%s %s" % (prov, ", ".join(files))
                                                   for prov, _rows, files in found)))
    return found[0]


def _same_dir(a, b):
    return bool(a) and bool(b) and (a == b or _canonical(a) == _canonical(b))


def codex_directory_candidates(codex_home, cwd):
    """Root Codex threads recorded in this directory as {thread id: [paths]}.
    A thread's files are every rollout whose filename carries its id,
    whatever each file's first record says, so an unreadable, undecodable, or
    mismatched member stays in the list and load_codex_source fails the whole
    thread on it. The thread is recorded here when a member's own
    session_meta names this directory. Subagent threads (a member's
    session_meta sets parent_thread_id) are not resume targets here, as
    Claude's nested subagent transcripts are not. An unlistable store
    directory or a rejected link raises session_store_unavailable
    (codex_rollouts)."""
    threads = {}
    for path, thread_id in codex_rollouts(codex_home):
        threads.setdefault(thread_id, []).append(path)
    here = {}
    for thread_id, paths in threads.items():
        metas = []
        for path in paths:
            first = _first_row(path)
            payload = first.get("payload") if isinstance(first, dict) else None
            if (isinstance(payload, dict) and first.get("type") == "session_meta"
                    and payload.get("id") == thread_id):
                metas.append(payload)
        if any(m.get("parent_thread_id") for m in metas):
            continue
        if any(_same_dir(m.get("cwd"), cwd) for m in metas):
            here[thread_id] = paths
    return here


# ================================================================== orchestration

def pick_candidate(cands):
    """First candidate, in the caller's order, with a substantive assistant
    turn, for transcript paths passed to the engine positionally (the
    wrapper never does); a single path skips the substance check.
    --session resolves through resolve_session, not here. Rows come from
    load(), which drops undecodable lines."""
    skipped = 0
    for c in cands:
        try:
            rows = load(c)
        except Exception:
            skipped += 1
            continue
        if len(cands) == 1 or substantive(rows):
            return c, rows, skipped
        skipped += 1
    return None, None, skipped


def build_report(cands):
    """Returns a single JSON-serializable dict — always an object, never a
    bare list, whether or not a substantive transcript was found (#910 eval
    F1: the caller must never see a shape that depends on cwd)."""
    path, rows, skipped = pick_candidate(cands)
    if path is None:
        return error_report("no_substantive_transcript", "no substantive transcript found",
                            candidates=len(cands), skipped=skipped)
    return report_from_rows(rows, os.path.basename(path)[:-6], skipped)


def report_from_rows(rows, sid, skipped=0):
    """The version-2 report for one already-loaded session's rows."""
    session_repo_cwd = next((r.get("cwd") for r in reversed(rows) if r.get("cwd")), os.getcwd())
    # #910 eval round 2 F5: every OTHER cwd in cwd_status gets an isdir
    # check; this one, the one everything else is computed relative to,
    # did not. A gone session_repo_cwd makes all 44+ git calls fail
    # silently and cascades every branch to deleted_no_merge (the highest
    # alarm) with nothing distinguishing "git itself was unreadable" from
    # a real, resolved all-red report. Marking it, not working around it —
    # falling back to a different cwd changes WHOSE git state is being
    # reported without saying so, which is its own silent-wrong-answer risk.
    session_repo_readable = os.path.isdir(session_repo_cwd)
    trunk = default_trunk(session_repo_cwd if session_repo_readable else None)

    users = [r for r in rows if r.get("type") == "user" and real(r)]
    asst = [r for r in rows if r.get("type") == "assistant" and real(r)]

    fu, fu_ts = first_user_message(users)
    lu, lu_ts = last_user_message(users)
    la, la_ts = last_assistant_message(asst)

    first_ts = next((r.get("timestamp") for r in rows if r.get("timestamp")), None)
    last_ts = next((r.get("timestamp") for r in reversed(rows) if r.get("timestamp")), None)

    sbranch = None
    for r in reversed(rows):
        b = r.get("gitBranch")
        if b:
            sbranch = b
            break

    git_info = {"branch": sbranch, "head": None, "exists": None, "on_main": None,
                "unmerged": None, "ahead_behind": None}
    if sbranch:
        git_info["exists"] = git_ok(session_repo_cwd, "rev-parse", "--verify", "--quiet",
                                     sbranch + "^{commit}")
        if sbranch == trunk:
            git_info["head"] = git(session_repo_cwd, "rev-parse", "--short", trunk) or None
            git_info["on_main"] = True
        elif git_info["exists"]:
            git_info["head"] = git(session_repo_cwd, "rev-parse", "--short", sbranch) or None
            git_info["on_main"] = git_ok(session_repo_cwd, "merge-base", "--is-ancestor", sbranch, trunk)
            git_info["unmerged"] = git(session_repo_cwd, "rev-list", "--count", trunk + ".." + sbranch) or "?"
            ab = git(session_repo_cwd, "rev-list", "--left-right", "--count",
                     "origin/%s...%s" % (sbranch, sbranch))
            git_info["ahead_behind"] = ab or None

    seen_branches = []
    seen_cwds = []
    for r in rows:
        b = r.get("gitBranch")
        c = r.get("cwd")
        if b and b not in seen_branches:
            seen_branches.append(b)
        if c and c not in seen_cwds:
            seen_cwds.append(c)

    wt_by_path = worktree_map(session_repo_cwd)
    path_by_branch = {b: p for p, b in wt_by_path.items() if b}

    cwd_status = {}
    for c in seen_cwds:
        if not os.path.isdir(c):
            cwd_status[c] = {"exists": False, "dirty": None, "branch": None}
            continue
        cur_branch = wt_by_path.get(c)
        if cur_branch is None:
            cur_branch = git(c, "rev-parse", "--abbrev-ref", "HEAD") or None
        out = status_short(c)
        cwd_status[c] = {"exists": True,
                          "dirty": (bool(out.strip()) if out is not None else None),
                          "branch": cur_branch}

    merge_log_rows = merge_log(session_repo_cwd, trunk)

    branch_reports = []
    covered = set()
    for b in seen_branches:
        if b == trunk:
            continue
        branch_reports.append(branch_state(session_repo_cwd, b, wt_by_path, path_by_branch,
                                            cwd_status, merge_log_rows, trunk))
        covered.add(b)
    for c in seen_cwds:
        cb = cwd_status.get(c, {}).get("branch")
        if cb and cb != trunk and cb not in covered:
            branch_reports.append(branch_state(session_repo_cwd, cb, wt_by_path, path_by_branch,
                                                cwd_status, merge_log_rows, trunk))
            covered.add(cb)

    # ---- #910 additive worklog ----
    for rep in branch_reports:
        commits, source = branch_commits(session_repo_cwd, rep, merge_log_rows, trunk)
        rep["commits"] = commits
        rep["commits_source"] = source

    transcript_paths = extract_transcript_paths(rows)
    repos = discover_repos(seen_cwds)
    # #910 eval round 2 F1: every entry in branch_reports was resolved
    # against session_repo_cwd (branch_state/branch_commits are always
    # called with it) -- there is exactly ONE repo whose branches this
    # report tracks at all, and it is repo_root_for(session_repo_cwd), not
    # "whichever repo the session happened to be sitting in when it last
    # wrote a cwd." The old predicate (worktree_path in cwds, i.e. "did the
    # SESSION ITSELF sit in this worktree", OR root == session_repo_cwd, a
    # repo-root-vs-cwd comparison true only when the session ended AT the
    # repo root) silently dropped every branch for any session that ended
    # inside a worktree -- reproduced on a real transcript (15 resolvable
    # files from a found merge commit, absent with no marker). One
    # comparison against the single owning repo fixes both broken clauses
    # at once because they were both proxies for this one fact.
    session_repo_root = repo_root_for(session_repo_cwd) or session_repo_cwd
    files_by_repo = {}
    for root, cwds in repos.items():
        branches_here = branch_reports if root == session_repo_root else []
        unresolved_here = [r["branch"] for r in branches_here if r.get("commits_source") == "unresolved"]
        files_by_repo[root] = files_for_repo(root, cwds, branches_here, transcript_paths,
                                              merge_log_rows, trunk, unresolved_here)

    stale = staleness(rows)

    return {
        "version": REPORT_VERSION,
        "session": sid,
        "messages": len(rows),
        "first_ts": first_ts,
        "last_ts": last_ts,
        "first_user": fu,
        "last_user": lu,
        "last_assistant": la,
        "git": git_info,
        "branches": branch_reports,
        # additive (#910)
        "files_by_repo": files_by_repo,
        "staleness": stale,
        "skipped_candidates": skipped,
        "session_repo_cwd": session_repo_cwd,
        "session_repo_readable": session_repo_readable,
    }


def _usage_error(message):
    print(json.dumps(error_report("usage", message)))
    return 2


def _directory_error(code, message):
    return error_report(code, message)


def _pick_directory_session(candidates):
    """First substantive session among (mtime, provider, sid, paths) rows,
    in the caller's order, across both providers. Every candidate, a lone
    one included, must load as its provider's transcript and carry a
    substantive assistant turn; the rest are skipped with a reason, so a
    malformed or never-answered session is never reported as context."""
    skipped = []
    for _mtime, provider, sid, paths in candidates:
        try:
            if provider == PROVIDER_CODEX:
                rows, paths = load_codex_source(paths, sid)
            else:
                rows = load_claude_source(paths[0])
        except SourceError as exc:
            skipped.append(exc.message)
            continue
        except OSError as exc:
            skipped.append("cannot read %s: %s" % (", ".join(paths), exc))
            continue
        if substantive(rows):
            return provider, sid, rows, paths, skipped
        skipped.append("%s transcript %s has no substantive assistant turn"
                       % (provider, ", ".join(paths)))
    return None, None, None, None, skipped


def directory_resume(state_dir, cwd, home, current_session,
                     transcript_session=None, prune=False, codex_home=None):
    """Resolve the whole directory-lens policy behind one engine interface.

    The shell supplies ambient inputs but does not inspect candidate JSON or
    decide when to fall back. This keeps selection, output shape, and error
    status together in the stdlib engine.

    An explicit session id resolves across both providers' stores wherever
    it ran (resolve_session). The automatic fallback lists this directory's
    sessions from both stores, newest first. current_session is one id or a
    list of ids to exclude: the invoking tool's own session is never a
    resume target.
    """
    if codex_home is None:
        codex_home = os.path.join(home, ".codex")
    if isinstance(current_session, str):
        current_session = [current_session]
    exclude = set(s for s in current_session or [] if s)
    slug = cwd.replace("/", "-").replace(".", "-")
    transcript_dir = os.path.join(home, ".claude", "projects", slug)
    candidates, skipped = handoff_candidates(state_dir, cwd, include_skipped=True)
    try:
        dead = prune_candidates(state_dir, home, codex_home=codex_home)
    except SourceError as exc:
        return _directory_error(exc.code, exc.message)
    if prune:
        moved = archive_prune_candidates(state_dir, dead)
        return {"version": REPORT_VERSION, "source": "handoff_prune",
                "moved": moved, "prune_candidates": dead}
    # An explicit session is a direct selection and bypasses handoff discovery.
    if transcript_session is not None:
        try:
            provider, rows, files = resolve_session(home, codex_home, transcript_session)
        except SourceError as exc:
            return _directory_error(exc.code, exc.message)
        report = report_from_rows(rows, transcript_session)
    else:
        local_candidates = [row for row in candidates
                            if row["group"] in ("this_directory", "sibling_worktrees")]
        if local_candidates:
            return handoff_candidates_report(candidates, skipped, dead)
        # Only this directory's Claude project is read. An unlistable or
        # linked one, a linked transcript in it, or an unlistable or linked
        # Codex store entry fails before selection.
        try:
            codex_threads = codex_directory_candidates(codex_home, cwd)
            claude_names = claude_project_transcripts(transcript_dir, exclude)
        except SourceError as exc:
            report = _directory_error(exc.code, exc.message)
            report["prune_candidates"] = dead
            return report
        if claude_names is None and not codex_threads:
            report = _directory_error(
                "no_transcript_directory",
                "no transcript directory for %s (looked in %s and Codex rollouts under %s)"
                % (cwd, transcript_dir, codex_home))
            report["prune_candidates"] = dead
            return report
        sessions = []
        for name in claude_names or []:
            path = os.path.join(transcript_dir, name)
            sessions.append((os.path.getmtime(path), PROVIDER_CLAUDE, name[:-6], [path]))
        for thread_id, paths in codex_threads.items():
            if thread_id not in exclude:
                sessions.append((max(os.path.getmtime(p) for p in paths), PROVIDER_CODEX,
                                 thread_id, paths))
        # Newest mtime first; equal mtimes break by session id, then provider,
        # so the choice never depends on file creation or listing order.
        sessions.sort(key=lambda row: (-row[0], row[2], row[1]))
        if not sessions:
            report = _directory_error(
                "no_other_session",
                "no OTHER session transcript in %s (only the current one)"
                % cwd)
            report["prune_candidates"] = dead
            return report
        provider, sid, rows, files, skipped_sessions = _pick_directory_session(sessions)
        if provider is None:
            report = error_report(
                "no_substantive_transcript",
                "no substantive transcript for %s; skipped: %s; pass --session <id>"
                % (cwd, "; ".join(skipped_sessions)),
                candidates=len(sessions), skipped=len(skipped_sessions))
        else:
            report = report_from_rows(rows, sid, len(skipped_sessions))

    if not report.get("error"):
        report["provider"] = provider
        report["transcript_files"] = files
        report["source"] = "transcript_fallback"
        report["notice"] = "No handoff was found for this directory; used the transcript miner."
    report["skipped"] = skipped
    report["prune_candidates"] = dead
    return report


def main(argv):
    sid_out = None
    handoff_state_dir = None
    handoff_current_cwd = None
    handoff_path = None
    no_commitments = False
    directory_resume_args = None
    transcript_session = None
    current_sessions = []
    codex_home = None
    transcript_fallback = False
    prune = False
    cands = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--sid-out":
            if i + 1 >= len(argv):
                return _usage_error("--sid-out requires a value")
            sid_out = argv[i + 1]
            i += 2
        elif a == "--prune":
            prune = True
            i += 1
        elif a == "--handoff-candidates":
            if i + 2 >= len(argv):
                return _usage_error("--handoff-candidates requires state directory and current cwd")
            handoff_state_dir = argv[i + 1]
            handoff_current_cwd = argv[i + 2]
            i += 3
        elif a == "--handoff":
            if i + 1 >= len(argv):
                return _usage_error("--handoff requires a file path")
            handoff_path = argv[i + 1]
            i += 2
        elif a == "--directory-resume":
            if i + 3 >= len(argv):
                return _usage_error("--directory-resume requires state directory, cwd, and home")
            directory_resume_args = (argv[i + 1], argv[i + 2], argv[i + 3])
            i += 4
        elif a == "--transcript-session":
            if i + 1 >= len(argv):
                return _usage_error("--transcript-session requires a session id")
            if not argv[i + 1]:
                return _usage_error("--transcript-session requires a non-empty session id")
            transcript_session = argv[i + 1]
            i += 2
        elif a == "--current-session":
            if i + 1 >= len(argv):
                return _usage_error("--current-session requires a session id")
            current_sessions.append(argv[i + 1])
            i += 2
        elif a == "--codex-home":
            if i + 1 >= len(argv):
                return _usage_error("--codex-home requires a directory")
            codex_home = argv[i + 1]
            i += 2
        elif a == "--transcript-fallback":
            transcript_fallback = True
            i += 1
        elif a == "--no-commitments":
            no_commitments = True
            i += 1
        elif a == "--json":
            i += 1
        elif a.startswith("--"):
            return _usage_error("unrecognized option: %s" % a)
        else:
            cands.append(a)
            i += 1

    if handoff_state_dir is not None:
        candidates, skipped = handoff_candidates(handoff_state_dir, handoff_current_cwd,
                                                 include_skipped=True)
        print(json.dumps(handoff_candidates_report(candidates, skipped), indent=2))
        return 0

    if handoff_path is not None:
        report = handoff_briefing(handoff_path, no_commitments=no_commitments)
        print(json.dumps(report, indent=2))
        return report_exit_status(report)

    if directory_resume_args is not None:
        report = directory_resume(*directory_resume_args,
                                  transcript_session=transcript_session,
                                  current_session=current_sessions,
                                  codex_home=codex_home,
                                  prune=prune)
        print(json.dumps(report, indent=2))
        return report_exit_status(report)

    report = build_report(cands)
    if transcript_fallback and not report.get("error"):
        report["source"] = "transcript_fallback"
        report["notice"] = "No handoff was found for this directory; used the transcript miner."

    if sid_out and report.get("session"):
        try:
            with open(sid_out, "w") as f:
                f.write(report["session"])
        except Exception:
            pass

    print(json.dumps(report, indent=2))
    return report_exit_status(report)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
