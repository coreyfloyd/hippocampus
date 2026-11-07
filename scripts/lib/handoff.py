#!/usr/bin/env python3
"""Deterministic, stdlib-only handoff state contract.

Shell callers relay stdin/stdout and plain arguments to this module; structured
parsing and routing stay here. Paths come from arguments, the established
HANDOFF_* environment variables, or the configured values (``handoff_dir`` is
where handoffs are stored; ``config-get`` prints any other). They are read from
a JSON file at ``$HIPPOCAMPUS_CONFIG``, else
``${XDG_CONFIG_HOME:-~/.config}/hippocampus/config.json``, so Claude Code and
Codex resolve the same location.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


DEFAULT_STATE_DIR = "~/.local/state/hippocampus/handoffs"
# Raw pre-compaction hook input is kept beside the handoffs, outside either tool's own data area.
COMPACT_STATE_DIR = "~/.local/state/hippocampus/compact-state"
HANDOFF_SH = str(Path(__file__).resolve().with_name("handoff.sh"))
TIMED_CHECKPOINT_DEFAULTS = {"timed_checkpoint_minutes": 55, "timed_checkpoint_token_limit": 200_000}
ITEM_TYPES = {"progress", "commitment", "decision", "knowledge", "lesson", "artifact", "open_loop"}
HEADLESS_ENTRYPOINTS = {"sdk-cli", "sdk-py", "sdk-ts", "sdk", "mcp", "headless"}
BANNED = {
    "tickets": "the ticket list is queried live, never carried",
    "ticket_list": "the ticket list is queried live, never carried",
    "runtime_posture": "runtime posture -> the runtime's own state file",
    "governor": "runtime posture -> the runtime's own state file",
    "jobs": "runtime posture -> the runtime's own state file",
    "monitors": "monitor doctrine -> the charter (Layer 5a)",
    "near_term_status": "near-term status -> the project brief",
    "project_status": "near-term status -> the project brief",
}


class CheckpointResult:
    def __init__(self, path: str, exit_code: int, output: str, errors: list[str]):
        self.path = path
        self.exit_code = exit_code
        self.output = output
        self.errors = errors


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _run_git(cwd: str, *args: str) -> str | None:
    result = subprocess.run(["git", "-C", cwd, *args], text=True, capture_output=True)
    return result.stdout.strip() if result.returncode == 0 else None


def repository_root(cwd: str) -> str | None:
    """Return parent of git-common-dir, including for a linked worktree."""
    if not cwd:
        return None
    common = _run_git(cwd, "rev-parse", "--git-common-dir")
    if not common:
        return None
    common_path = Path(common)
    if not common_path.is_absolute():
        common_path = Path(cwd) / common_path
    return str(common_path.resolve().parent)


def canonical_subject(cwd: str) -> str:
    return str(Path(cwd).resolve())


def config_path() -> str:
    explicit = os.environ.get("HIPPOCAMPUS_CONFIG")
    if explicit:
        return os.path.expanduser(explicit)
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "hippocampus", "config.json")


def read_config() -> dict:
    """Return the hippocampus configuration; a malformed file is an error, never a silent default."""
    path = config_path()
    try:
        data = read_json(path)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        raise ValueError(f"hippocampus config {path} is unreadable: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"hippocampus config {path}: must be a JSON object")
    return data


def timed_setting(key: str) -> int:
    value = read_config().get(key, TIMED_CHECKPOINT_DEFAULTS[key])
    if type(value) is not int or value < 1:
        requirement = ("a whole number of minutes, at least 1" if key == "timed_checkpoint_minutes"
                       else "a positive integer")
        raise ValueError(f"hippocampus config {config_path()}: {key} must be {requirement}")
    return value


def timer_directory() -> Path:
    return Path(os.path.expanduser(os.environ.get("HANDOFF_TIMER_DIR")
                or os.path.join(os.path.dirname(state_dir().rstrip(os.sep)), "timed-checkpoints")))


def timer_file(session_id: str, suffix: str) -> Path:
    if not session_id.strip():
        raise ValueError("timed checkpoint: a session id is required")
    return timer_directory() / (urllib.parse.quote(session_id, safe="-_.") + suffix)


def remember_transcript(payload: Mapping[str, Any]) -> None:
    session_id = str(payload.get("session_id") or "")
    transcript = payload.get("transcript_path")
    if session_id and isinstance(transcript, str) and transcript:
        atomic_write(str(timer_file(session_id, ".context.json")), {
            "transcript_path": str(Path(transcript).resolve()),
            "harness": "codex" if os.environ.get("HIPPOCAMPUS_HARNESS") == "codex" else "claude"})


def transcript_for_session(session_id: str) -> tuple[str, bool]:
    try:
        context = read_json(str(timer_file(session_id, ".context.json")))
        return context["transcript_path"], context.get("harness") == "codex"
    except FileNotFoundError:
        pass
    codex = os.environ.get("HIPPOCAMPUS_HARNESS") == "codex" or bool(os.environ.get("CODEX_THREAD_ID"))
    home = Path(os.environ.get("CODEX_HOME") or os.path.expanduser("~/.codex")) if codex else Path(
        os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude"))
    # Session ids are glob literals, never user-provided patterns.
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", session_id):
        return "", codex
    paths = sorted((home / ("sessions" if codex else "projects")).rglob("*" + session_id + ".jsonl"),
                   key=lambda path: path.stat().st_mtime, reverse=True)
    return (str(paths[0]) if paths else ""), codex


def timed_prompt(session_id: str) -> str:
    command = shlex.join([sys.executable, str(Path(__file__).resolve()), "timed-checkpoint-check",
                          "--session-id", session_id])
    return Path(__file__).with_name("timed-checkpoint-prompt.txt").read_text().strip().format(check_command=command)


def claude_schedule(session_id: str, written_at: str) -> str:
    minutes = timed_setting("timed_checkpoint_minutes")
    due = datetime.fromisoformat(written_at.replace("Z", "+00:00")) + timedelta(minutes=minutes)
    # Never truncate seconds into an earlier (or already elapsed) cron minute.
    # A delayed restore may be scheduling after the original due time.
    due = max(due, datetime.now(timezone.utc) + timedelta(microseconds=1)).astimezone(timezone.utc)
    rounded = due.replace(second=0, microsecond=0)
    if rounded < due:
        rounded += timedelta(minutes=1)
    # CronCreate's five-field expression is evaluated in the session's local timezone.
    local = rounded.astimezone()
    cron = f"{local.minute} {local.hour} {local.day} {local.month} *"
    job_file = timer_file(session_id, ".claude.json")
    previous = read_json(str(job_file)).get("job_id") if job_file.exists() else None
    delete = f"CronDelete job {previous}" if previous else "CronDelete any previous timed checkpoint job for this session"
    register = shlex.join([sys.executable, str(Path(__file__).resolve()), "claude-timer-set", "--session-id", session_id, "--job-id", "<new-job-id>"])
    return (f"\nTimed checkpoint: {delete} before scheduling its replacement. Use CronCreate now: "
            f"session-only, recurring: false, pinned to {local.isoformat(timespec='minutes')} "
            f"(at least {minutes:g} minutes after this checkpoint, rounded up to a future cron minute), cron: {cron}. "
            f"Use this exact prompt:\n{timed_prompt(session_id)}\n"
            f"After CronCreate succeeds, record its job id: {register}\n")


def schedule_checkpoint(cwd: str, session_id: str, written_at: str) -> str:
    # Headless jobs and subagents never own interactive-session timers.
    if not session_id or not is_interactive({"session_id": session_id}):
        return ""
    minutes = timed_setting("timed_checkpoint_minutes")
    timed_setting("timed_checkpoint_token_limit")
    if os.environ.get("HIPPOCAMPUS_HARNESS") != "codex" and not os.environ.get("CODEX_THREAD_ID"):
        return claude_schedule(session_id, written_at)
    codex = shutil.which("codex")
    if not codex:
        raise ValueError("timed checkpoint: codex executable is unavailable")
    path = timer_file(session_id, ".pending.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    with timer_file(session_id, ".schedule.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        atomic_write(str(path), {"session_id": session_id, "cwd": cwd, "codex": codex,
            "due_at": datetime.fromisoformat(written_at.replace("Z", "+00:00")).timestamp() + minutes * 60,
            "prompt": timed_prompt(session_id)})
        # Competing workers exit under worker.lock; an existing worker reads the
        # replacement deadline. No PID-based kill can target a recycled process.
        subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "timed-checkpoint-wait", str(path)],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         close_fds=True, start_new_session=True)
    return f"\nTimed checkpoint pending for session {session_id} in {minutes:g} minutes; replaced any previous timer.\n"


def wait_for_checkpoint(path: str) -> None:
    pending = Path(path)
    prefix = pending.name.removesuffix(".pending.json")
    with pending.with_name(prefix + ".worker.lock").open("a") as worker:
        try:
            fcntl.flock(worker, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        while True:
            with pending.with_name(prefix + ".schedule.lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                if not pending.exists():
                    # Release while still holding schedule.lock so a concurrent
                    # checkpoint cannot lose its replacement on worker exit.
                    fcntl.flock(worker, fcntl.LOCK_UN)
                    return
                state = read_json(str(pending))
                remaining = state["due_at"] - time.time()
                if remaining <= 0:
                    try:
                        result = subprocess.run([state["codex"], "queue", "--thread", state["session_id"],
                            "--message", state["prompt"]], cwd=state["cwd"], capture_output=True, text=True, timeout=15)
                        receipt = {"queued": result.returncode == 0, "exit_code": result.returncode,
                                   "stdout": result.stdout, "stderr": result.stderr, "fired_at": utc_now()}
                    except (OSError, subprocess.TimeoutExpired) as error:
                        receipt = {"queued": False, "error": str(error), "fired_at": utc_now()}
                    atomic_write(str(pending.with_name(prefix + ".receipt.json")), receipt)
                    pending.unlink()
                    fcntl.flock(worker, fcntl.LOCK_UN)
                    return
            time.sleep(min(remaining, 0.5))


def config_string(key: str) -> str | None:
    """Return one configured string, or None when the key is absent."""
    value = read_config().get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"hippocampus config {config_path()}: {key} must be a non-empty string")
    if key == "harness_enforcement_reference" and not (os.path.isabs(value) or value.startswith("~/")):
        raise ValueError(f"hippocampus config {config_path()}: {key} must be an absolute or ~/ path")
    return value


def config_string_list(key: str) -> list[str]:
    """Return one configured list of strings; absent means empty."""
    value = read_config().get(key)
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise ValueError(f"hippocampus config {config_path()}: {key} must be a list of non-empty strings")
    return value


def configured_handoff_dir() -> str | None:
    """Return the configured ``handoff_dir``."""
    return config_string("handoff_dir")


def state_dir() -> str:
    """Where handoffs are stored: HANDOFF_STATE_DIR, else the configured value, else the default."""
    return os.path.expanduser(os.environ.get("HANDOFF_STATE_DIR")
                              or configured_handoff_dir() or DEFAULT_STATE_DIR)


def ambient_session_id() -> str:
    """The calling tool's id, not an inherited parent harness's session."""
    return (os.environ.get("CODEX_THREAD_ID") or os.environ.get("CLAUDE_SESSION_ID")
            or os.environ.get("CLAUDE_CODE_SESSION_ID", ""))


def resolve_path(cwd: str, session_id: str, use_override: bool = True) -> str:
    if use_override and os.environ.get("HANDOFF_PATH"):
        return os.environ["HANDOFF_PATH"]
    if not isinstance(session_id, str) or not session_id.strip():
        return ""
    if not cwd:
        return ""
    subject = canonical_subject(cwd)
    readable = re.sub(r"[^A-Za-z0-9]+", "-", subject.strip("/")).strip("-")[-120:] or "root"
    digest = hashlib.sha256(subject.encode("utf-8")).hexdigest()[:12]
    encoded_session = urllib.parse.quote(session_id, safe="-_.")
    return os.path.join(state_dir(), f"{readable}-{digest}-{encoded_session}.json")


def resolve_subject_path(cwd: str, session_id: str) -> str:
    return resolve_path(cwd, session_id, use_override=False)


def cycle_request_handoff_path(session: str, session_id: str, home: str) -> str:
    """Return the session-specific handoff path used by cycle requests."""
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError(
            "cycle request: a session id is required "
            "(--session-id or CLAUDE_SESSION_ID/CLAUDE_CODE_SESSION_ID/CODEX_THREAD_ID)"
        )
    sessions = read_config().get("cycle_sessions")
    subject = sessions.get(session) if isinstance(sessions, dict) else None
    if not isinstance(subject, str) or not subject.strip():
        return ""
    return resolve_subject_path(os.path.join(home, subject), session_id)


def automated_cycle_handoff_path(cwd: str, max_age_hours: int,
                                 now: datetime | None = None) -> str:
    """Select one fresh session handoff for an unattended cycle, or fail closed."""
    if max_age_hours <= 0:
        raise ValueError("automated cycle: max handoff age must be positive")
    subject = canonical_subject(cwd)
    timestamp = (now or datetime.now(timezone.utc)).timestamp()
    cutoff = timestamp - max_age_hours * 3600
    candidates: list[str] = []
    for path in Path(state_dir()).glob("*.json"):
        try:
            data = read_json(str(path))
            handoff_subject = data.get("subject", {}) if isinstance(data, dict) else {}
            if (handoff_subject.get("working_directory") != subject
                    or not isinstance(handoff_subject.get("session_id"), str)
                    or not handoff_subject["session_id"].strip()
                    or path.stat().st_mtime < cutoff):
                continue
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
        candidates.append(str(path))
    if len(candidates) != 1:
        condition = "no fresh handoff" if not candidates else "ambiguous fresh handoffs"
        raise ValueError(
            f"automated cycle: {condition} for {subject} "
            f"(found {len(candidates)}); pass --state-file to select one"
        )
    return candidates[0]


def write_cycle_request(path: str, session: str, reason: str,
                        handoff_age_min: int | None, handoff_path: str,
                        requested_at: datetime | None = None,
                        requested_by_pid: int | None = None) -> dict[str, Any]:
    """Write the durable cycle request atomically and return its record."""
    stamp = requested_at or datetime.now().astimezone()
    record: dict[str, Any] = {
        "session": session,
        "requested_at": stamp.isoformat(),
        "requested_by_pid": os.getppid() if requested_by_pid is None else requested_by_pid,
        "reason": reason or "operator-requested cycle",
        "handoff_path": handoff_path,
    }
    if handoff_age_min is not None:
        record["handoff_age_min"] = handoff_age_min
    atomic_write(path, record)
    return record


def validate_cycle_request(path: str, ttl_sec: int, allowed: Sequence[str],
                           now: datetime | None = None) -> tuple[str, str]:
    """Validate a queued cycle request and return its plain dispatch fields."""
    try:
        record = read_json(path)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"unparseable JSON ({exc.__class__.__name__})") from exc
    if not isinstance(record, dict):
        raise ValueError("not a JSON object")
    session = record.get("session")
    if not isinstance(session, str) or re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", session) is None:
        raise ValueError("missing or malformed 'session'")
    if session not in allowed:
        raise ValueError(f"session {session!r} not in allowlist {list(allowed)!r}")
    handoff_path = record.get("handoff_path", "")
    if not isinstance(handoff_path, str):
        raise ValueError("malformed 'handoff_path'")
    raw_timestamp = record.get("requested_at")
    if not isinstance(raw_timestamp, str):
        raise ValueError("missing 'requested_at'")
    try:
        requested_at = datetime.fromisoformat(raw_timestamp)
    except ValueError as exc:
        raise ValueError(f"unparseable 'requested_at': {raw_timestamp!r}") from exc
    if requested_at.tzinfo is None:
        requested_at = requested_at.astimezone()
    current = now or datetime.now().astimezone()
    age = (current - requested_at).total_seconds()
    if age > ttl_sec:
        raise ValueError(f"stale: {int(age)}s old (ttl {ttl_sec}s)")
    if age < -60:
        raise ValueError(
            f"timestamp {int(-age)}s in the future (clock skew or hand-edited)"
        )
    return session, handoff_path


def dispatch_cycle_request(path: str, cycle_bin: str) -> int:
    """Invoke the cycler with routing fields read directly from its request."""
    record = read_json(path)
    if not isinstance(record, dict):
        raise ValueError("not a JSON object")
    session = record.get("session")
    if not isinstance(session, str) or re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", session) is None:
        raise ValueError("missing or malformed 'session'")
    handoff_path = record.get("handoff_path", "")
    if not isinstance(handoff_path, str):
        raise ValueError("malformed 'handoff_path'")
    command = [cycle_bin, session]
    if handoff_path:
        command.extend(["--state-file", handoff_path])
    else:
        command.append("--automated-handoff")
    return subprocess.run(command).returncode


def migrate_legacy_handoffs() -> dict[str, list[dict[str, str]]]:
    """Rename cwd-keyed v2 handoffs to their per-session path, idempotently."""
    result: dict[str, list[dict[str, str]]] = {"moved": [], "left": []}
    directory = state_dir()
    try:
        names = sorted(os.listdir(directory))
    except FileNotFoundError:
        return result
    for name in names:
        if not name.endswith(".json"):
            continue
        old_path = os.path.join(directory, name)
        try:
            data = read_json(old_path)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            result["left"].append({"path": old_path, "reason": "invalid_json"})
            continue
        subject = data.get("subject") if isinstance(data, dict) else None
        session_id = subject.get("session_id") if isinstance(subject, dict) else None
        cwd = subject.get("working_directory") if isinstance(subject, dict) else None
        if (not isinstance(session_id, str) or not session_id.strip()
                or not isinstance(cwd, str) or not cwd):
            result["left"].append({"path": old_path, "reason": "missing_valid_session_id"})
            continue
        new_path = resolve_subject_path(cwd, session_id)
        if old_path == new_path:
            continue
        if os.path.exists(new_path):
            result["left"].append({"path": old_path, "reason": "target_exists"})
            continue
        os.rename(old_path, new_path)
        result["moved"].append({"from": old_path, "to": new_path})
    return result


def atomic_write(path: str, data: Any, before_replace: Callable[[], None] | None = None,
                 *, replace: bool = True) -> None:
    """Publish complete JSON atomically; replace=False preserves any existing file."""
    if not path:
        raise ValueError("handoff_atomic_write: empty path")
    encoded = json.dumps(data, separators=(",", ":")) if not isinstance(data, str) else _validate_raw_json(data)
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=directory, prefix=".operator-handoff.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(encoded)
        if before_replace is not None:
            before_replace()
        if replace:
            os.replace(temporary, path)
        else:
            try:
                os.link(temporary, path)
            except FileExistsError:
                pass
            finally:
                os.unlink(temporary)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _validate_raw_json(raw: str) -> str:
    json.loads(raw)
    return raw


def read_json(path: str) -> Any:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def real_history_text(text: Any) -> bool:
    return (isinstance(text, str) and bool(text.strip())
            and text.strip() != "Session checkpoint." and "\n" not in text and "\r" not in text)


def lint_data(data: Any) -> tuple[list[str], list[str]]:
    problems: list[str] = []
    warnings: list[str] = []
    if not isinstance(data, dict):
        return ["handoff must be a JSON object"], warnings
    if not isinstance(data.get("written_at"), str) or not _valid_history_time(data["written_at"]):
        problems.append("written_at must be an ISO timestamp with timezone")
    version = data.get("schema_version")
    if version not in (1, 2):
        problems.append(f"schema_version is {version!r}, expected 1 or 2")
    if version == 2:
        subject = data.get("subject")
        if not isinstance(subject, dict):
            problems.append("schema_version 2 requires a subject block")
        else:
            if not isinstance(subject.get("working_directory"), str) or not subject["working_directory"]:
                problems.append("schema_version 2 requires subject.working_directory")
            if not isinstance(subject.get("session_id"), str) or not subject["session_id"].strip():
                problems.append("schema_version 2 requires subject.session_id to be a non-empty string")
        git = data.get("git")
        if not isinstance(git, dict):
            problems.append("schema_version 2 requires a git block")
        else:
            for key in ("repository_root", "branch"):
                if not isinstance(git.get(key), str):
                    problems.append(f"schema_version 2 requires git.{key}")
    for key, reason in BANNED.items():
        if key in data:
            problems.append(f"banned top-level key {key!r}: {reason}")
    resume = data.get("resume")
    if not isinstance(resume, dict):
        problems.append("missing/invalid resume block")
        resume = {}
    if not resume.get("headline"):
        warnings.append("resume.headline empty")
    loops = resume.get("open_loops", [])
    if not isinstance(loops, list):
        problems.append("resume.open_loops must be an array")
        loops = []
    try:
        validate_ticket_facts(resume)
        project_references(resume)
    except (ValueError, TypeError) as error:
        problems.append(str(error))
    chain = resume.get("resumed_chain", [])
    if not isinstance(chain, list):
        problems.append("resume.resumed_chain must be an array")
    else:
        for index, row in enumerate(chain):
            if not isinstance(row, dict) or any(not isinstance(row.get(key), str) or not row[key].strip()
                                                for key in ("handoff", "session_id", "resumed_at")):
                problems.append(f"resumed_chain[{index}] requires handoff, session_id, and resumed_at")
            elif not _valid_history_time(row["resumed_at"]):
                problems.append(f"resumed_chain[{index}].resumed_at must be an ISO timestamp with timezone")
    summary = resume.get("session_summary")
    if summary is not None and (not isinstance(summary, str) or not summary.strip()):
        problems.append("resume.session_summary must be a non-empty string")
    history = resume.get("session_history", [])
    if not isinstance(history, list):
        problems.append("resume.session_history must be an array")
    else:
        for index, entry in enumerate(history):
            if not isinstance(entry, dict):
                problems.append(f"session_history[{index}] must be an object")
                continue
            for field in ("session_id", "produced_at", "summary"):
                if not isinstance(entry.get(field), str) or not entry[field].strip():
                    problems.append(f"session_history[{index}].{field} must be a non-empty string")
            try:
                stamp = datetime.fromisoformat(str(entry.get("produced_at", "")).replace("Z", "+00:00"))
                if stamp.tzinfo is None:
                    raise ValueError("timezone required")
            except ValueError:
                problems.append(f"session_history[{index}].produced_at must be an ISO timestamp with timezone")
            if isinstance(entry.get("summary"), str) and entry["summary"].strip() == "Session checkpoint.":
                problems.append(f"session_history[{index}] must contain a real history entry")
            summary_text = entry.get("summary", "")
            if isinstance(summary_text, str) and ("\n" in summary_text or "\r" in summary_text):
                problems.append(f"session_history[{index}].summary must be one line")
    if data.get("skeleton") is True:
        if data.get("trigger") != "stop":
            problems.append("only an automatic stop handoff may be a skeleton")
    elif version == 2:
        session_id = data.get("subject", {}).get("session_id") if isinstance(data.get("subject"), dict) else None
        if not isinstance(history, list) or not any(
                isinstance(row, dict) and row.get("session_id") == session_id
                and row.get("produced_at") == data.get("written_at")
                and real_history_text(row.get("summary")) for row in history):
            problems.append("a real history entry for this handoff write is required")
    files = data.get("uncommitted_files", [])
    if not isinstance(files, list) or any(not isinstance(path, str) or not os.path.isabs(path) for path in files):
        problems.append("uncommitted_files must be an array of absolute paths")
    for index, loop in enumerate(loops):
        if not isinstance(loop, dict):
            problems.append(f"open_loops[{index}] not an object")
            continue
        if "type" in loop:
            prefix = f"open_loops[{index}]"
            if not isinstance(loop["type"], str) or loop["type"] not in ITEM_TYPES:
                problems.append(f"{prefix}.type is not a session-item type")
            for field in ("context", "session_id", "produced_at", "disposition"):
                if not isinstance(loop.get(field), str) or not loop[field].strip():
                    problems.append(f"{prefix}.{field} must be a non-empty string")
            try:
                stamp = datetime.fromisoformat(str(loop.get("produced_at", "")).replace("Z", "+00:00"))
                if stamp.tzinfo is None:
                    raise ValueError("timezone required")
            except ValueError:
                problems.append(f"{prefix}.produced_at must be an ISO timestamp with timezone")
            if loop["type"] == "decision":
                for field in ("author", "location"):
                    if not isinstance(loop.get(field), str) or not loop[field].strip():
                        problems.append(f"{prefix}.{field} is required for a decision")
            if loop["type"] == "artifact":
                if not isinstance(loop.get("location"), str) or not loop["location"].strip():
                    problems.append(f"{prefix}.location is required for an artifact")
                if loop.get("disposition") not in ("keep", "remove"):
                    problems.append(f"{prefix}.disposition must be keep or remove for an artifact")
        context = loop.get("context", "")
        full_proposal = loop.get("type") in ("decision", "lesson") or bool(loop.get("choices"))
        if isinstance(context, str) and len(context) > 600 and not full_proposal:
            problems.append(f"open_loops[{index}].context is {len(context)} chars — that reads like durable progress; put it in the record and leave a pointer here")
        anchor = loop.get("anchor")
        anchored = isinstance(anchor, dict) and bool(anchor.get("ticket") or anchor.get("project"))
        if not anchored and not loop.get("disposition"):
            problems.append(f"open_loops[{index}] has no anchor (ticket|project) and no disposition — an un-anchored loop MUST say where it will be filed")
    processes = data.get("spawned_processes", [])
    if not isinstance(processes, list):
        problems.append("spawned_processes must be an array")
        processes = []
    for index, process in enumerate(processes):
        if not isinstance(process, dict):
            problems.append(f"spawned_processes[{index}] not an object")
        elif process.get("pid") is None or not process.get("started_at"):
            problems.append(f"spawned_processes[{index}] missing pid+started_at — identity reconcile (F4) is impossible without both; kill -0 alone can hit a stranger")
    return problems, warnings


def lint_file(path: str) -> tuple[list[str], list[str]]:
    return lint_data(read_json(path))


def lint_output(path: str) -> tuple[int, str]:
    try:
        problems, warnings = lint_file(path)
    except FileNotFoundError:
        return 2, f"lint-handoff: no file at {path}\n"
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return 2, f"lint-handoff: not valid JSON: {exc}\n"
    lines = [f"WARN: {warning}" for warning in warnings] + [f"FAIL: {problem}" for problem in problems]
    if problems:
        lines.append(f"lint-handoff: {len(problems)} violation(s)")
        return 1, "\n".join(lines) + "\n"
    lines.append("lint-handoff: clean" + ("" if not warnings else f" (with {len(warnings)} warning(s))"))
    return 0, "\n".join(lines) + "\n"


def _valid_history_time(value: Any) -> bool:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).tzinfo is not None
    except ValueError:
        return False


def resumed_handoff(session_id: str) -> dict[str, Any] | None:
    """The selected handoff snapshot, held only in this session's ledger."""
    return next((row for row in reversed(_ledger_records(ledger_path(session_id)))
                 if row.get("kind") == "resumed_handoff"), None) if session_id else None


def resumed_chain(session_id: str) -> list[dict[str, Any]]:
    return [row["record"] for row in _ledger_records(ledger_path(session_id))
            if row.get("kind") == "resumed_chain"] if session_id else []


def record_pickup(path: str, data: Mapping[str, Any], session_id: str) -> None:
    """Copy the complete chain before pickup returns; retries add nothing twice."""
    if not session_id:
        return  # A standalone inspection has no successor to write to.
    problems, _ = lint_data(data)
    if problems:
        raise ValueError("pickup: invalid handoff: " + "; ".join(problems))
    selected = str(Path(path).resolve())
    previous = resumed_handoff(session_id)
    if previous:
        if previous["handoff"] != selected:
            raise ValueError(f"pickup: session already recorded resumed handoff {previous['handoff']}; got {selected}")
        return
    predecessor = data["subject"]["session_id"]
    # The resumed session's unsettled items: its handoff's typed loops and its ledger.
    loops = data["resume"].get("open_loops", [])
    written = {session_item_identity(loop) for loop in loops}
    carried = [*loops, *(item for item in retained_session_items(predecessor)
                         if session_item_identity(item) not in written)]
    if predecessor == session_id:
        retain_session_facts(data["resume"], session_id)
        retain_session_items(carried, session_id, foreign=True)
        return  # Native continuation keeps its facts without creating a chain link.
    resume = data["resume"]
    chain = list(resume.get("resumed_chain", []))
    chain.append({"handoff": selected, "session_id": data["subject"]["session_id"],
                  "resumed_at": utc_now(), "skeleton": data.get("skeleton", False),
                  "written_at": data["written_at"]})
    rows = [{"kind": "history_entry", "entry": entry}
            for entry in resume.get("session_history", [])]
    rows += [{"kind": "close_outcome", "outcome": outcome}
             for outcome in resume.get("close_outcomes", [])]
    rows += [{"kind": "touched_ticket", "ticket": ticket}
             for ticket in resume.get("touched_tickets", [])]
    rows += [{"kind": "touched_project", "project": project}
             for project in resume.get("touched_projects", [])]
    _, settled = _session_item_rows(predecessor)
    items: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for item in carried:
        identity = session_item_identity(item)
        if identity and identity not in settled and item.get("recorded") is not True:
            items.setdefault(identity, []).append(dict(item))
    rows += [{"kind": "session_item", "identity": list(identity), "items": _distinct(copies)}
             for identity, copies in items.items()]
    rows += [{"kind": "resumed_chain", "record": record} for record in chain]
    rows.append({"kind": "resumed_handoff", "handoff": selected, "data": data})
    existing = _ledger_records(ledger_path(session_id))
    rows = [row for row in rows if row not in existing]
    target = Path(ledger_path(session_id))
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write("".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows))


# All writers use the same four ledger fact shapes. Omitted fields never erase facts.
SESSION_FACTS = (
    ("touched_tickets", "touched_ticket", "ticket"),
    ("touched_projects", "touched_project", "project"),
    ("close_outcomes", "close_outcome", "outcome"),
    ("session_history", "history_entry", "entry"),
)


def retain_session_facts(resume: Mapping[str, Any], session_id: str, *,
                         record: bool = True) -> dict[str, list]:
    """Record supplied facts, then restore all facts needed by wrap from the ledger."""
    facts = {field: resume.get(field, []) for field, _, _ in SESSION_FACTS}
    problems, _ = lint_data({"schema_version": 1, "written_at": utc_now(), "resume": facts})
    if problems:
        raise ValueError("; ".join(problems))
    existing = _ledger_records(ledger_path(session_id)) if session_id else []
    for field, kind, key in SESSION_FACTS:
        values = [row[key] for row in existing if row.get("kind") == kind]
        for value in facts[field]:
            # Only pickup can introduce another session's history.
            if field == "session_history" and value["session_id"] != session_id and value not in values:
                continue
            if value not in values:
                if session_id and record:
                    append_ledger(session_id, {"kind": kind, key: value})
                values.append(value)
        facts[field] = values
    return facts


# A retained session item is identified by its producer, time, type and text.
# Artifacts have their own ledger rows and status, so they are not retained here.
SESSION_ITEM_IDENTITY = ("session_id", "produced_at", "type", "context")


def session_item_identity(item: Any) -> tuple[str, ...] | None:
    """The identity of a well-formed retainable session item, else None."""
    if (not isinstance(item, Mapping) or not isinstance(item.get("type"), str)
            or item["type"] not in ITEM_TYPES or item["type"] == "artifact"):
        return None
    if any(not isinstance(item.get(field), str) or not item[field].strip() for field in SESSION_ITEM_IDENTITY):
        return None
    probe = {"schema_version": 1, "written_at": utc_now(),
             "resume": {"headline": "probe", "open_loops": [dict(item)]}}
    if lint_data(probe)[0]:
        return None
    return tuple(item[field] for field in SESSION_ITEM_IDENTITY)


def _session_item_rows(session_id: str) -> tuple[dict[tuple[str, ...], list[dict[str, Any]]], set[tuple[str, ...]]]:
    """Latest retained copies per identity, in first-retained order, and settled identities.

    One identity can name several distinct items, such as two asks for the same lesson
    with different choices; the latest write that supplied the identity holds them all.
    """
    items: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    settled: set[tuple[str, ...]] = set()
    for row in _ledger_records(ledger_path(session_id)) if session_id else []:
        if row.get("kind") == "session_item" and isinstance(row.get("items"), list):
            copies = [dict(item) for item in row["items"] if session_item_identity(item)]
            identities = {session_item_identity(item) for item in copies}
            if len(identities) == 1:
                items[identities.pop()] = copies
        elif row.get("kind") == "session_item_settled" and isinstance(row.get("identity"), list):
            settled.add(tuple(row["identity"]))
    return items, settled


def retained_session_items(session_id: str) -> list[dict[str, Any]]:
    """This session's retained, unsettled session items from its own ledger."""
    items, settled = _session_item_rows(session_id)
    return [item for identity, copies in items.items() if identity not in settled for item in copies]


def _distinct(items: Sequence[Any]) -> list[Any]:
    result: list[Any] = []
    for item in items:
        if item not in result:
            result.append(item)
    return result


def retain_session_items(items: Sequence[Any], session_id: str, *, foreign: bool = False) -> None:
    """Retain unrecorded items; a recorded item settles its retained copies.

    Another session's item enters only through pickup (``foreign``) or when this
    session's ledger already retains it.
    """
    if not session_id.strip():
        return
    retained, settled = _session_item_rows(session_id)
    supplied: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for item in items:
        identity = session_item_identity(item)
        if not identity:
            continue
        if item.get("recorded") is True:
            if identity in retained and identity not in settled:
                append_ledger(session_id, {"kind": "session_item_settled", "identity": list(identity)})
                settled.add(identity)
            continue
        if identity[0] != session_id and identity not in retained and not foreign:
            continue
        supplied.setdefault(identity, []).append(dict(item))
    for identity, copies in supplied.items():
        copies = _distinct(copies)
        if identity in settled or retained.get(identity) == copies:
            continue
        append_ledger(session_id, {"kind": "session_item", "identity": list(identity), "items": copies})


def settle_session_items(items: Sequence[Any], session_id: str) -> None:
    """Mark filed or dropped items settled so no later write restores them."""
    if not session_id.strip():
        return
    _, settled = _session_item_rows(session_id)
    for item in items:
        identity = session_item_identity(item)
        if identity and identity not in settled:
            append_ledger(session_id, {"kind": "session_item_settled", "identity": list(identity)})
            settled.add(identity)


def merge_session_items(loops: list[Any], session_id: str,
                        recorded: Sequence[Any] = ()) -> list[Any]:
    """Drop exact duplicates, then restore retained, unsettled items not supplied or recorded."""
    excluded = {session_item_identity(item) for item in recorded} - {None}
    result: list[Any] = []
    supplied: set[tuple[str, ...]] = set()
    for loop in loops:
        identity = session_item_identity(loop)
        if identity and loop in result:
            continue
        if identity:
            supplied.add(identity)
        result.append(loop)
    for item in retained_session_items(session_id):
        identity = session_item_identity(item)
        if identity not in supplied and identity not in excluded and item not in result:
            result.append(item)
    return result


def supplied_session_items(supplied: Mapping[str, Any]) -> list[Any]:
    """Typed items a writer received: the continuation's open loops and session items."""
    resume = supplied.get("resume") if isinstance(supplied, Mapping) else None
    loops = resume.get("open_loops", []) if isinstance(resume, Mapping) else []
    items = supplied.get("session_items", []) if isinstance(supplied, Mapping) else []
    return [*(loops if isinstance(loops, list) else []), *(items if isinstance(items, list) else [])]


def missing_chain_facts(data: Mapping[str, Any]) -> list[str]:
    """Validate final coverage against the successor's own ledger, never a source file."""
    session_id = data.get("subject", {}).get("session_id", "")
    resume = data.get("resume", {})
    failures = []
    for row in _ledger_records(ledger_path(session_id)) if session_id else []:
        if row.get("kind") == "history_entry" and row["entry"] not in resume.get("session_history", []):
            failures.append("missing history entry: " + json.dumps(row["entry"], ensure_ascii=False))
        elif row.get("kind") == "close_outcome" and row["outcome"] not in resume.get("close_outcomes", []):
            failures.append("missing close outcome: " + json.dumps(row["outcome"], ensure_ascii=False))
    return failures


def ticket_facts(resume: Mapping[str, Any], session_id: str) -> dict[str, list]:
    """Merge carried ticket facts with this session's compaction-safe ledger."""
    validate_ticket_facts(resume)
    tickets = list(resume.get("touched_tickets", []))
    outcomes = list(resume.get("close_outcomes", []))
    for row in _ledger_records(ledger_path(session_id)) if session_id else []:
        if row.get("kind") == "touched_ticket" and row["ticket"] not in tickets:
            tickets.append(row["ticket"])
        elif row.get("kind") == "close_outcome" and row["outcome"] not in outcomes:
            outcomes.append(row["outcome"])
    validate_ticket_facts({"touched_tickets": tickets, "close_outcomes": outcomes})
    return {"touched_tickets": tickets, "close_outcomes": outcomes}


def project_references(resume: Mapping[str, Any]) -> list[str]:
    projects = resume.get("touched_projects", [])
    if not isinstance(projects, list) or any(not isinstance(p, str) or not p.strip() for p in projects):
        raise ValueError("touched_projects must be an array of non-empty project references")
    return list(projects)


def validate_ticket_facts(resume: Mapping[str, Any]) -> None:
    tickets = resume.get("touched_tickets", [])
    if not isinstance(tickets, list) or any(not isinstance(t, str) or not t.strip() for t in tickets):
        raise ValueError("touched_tickets must be an array of non-empty ticket references")
    outcomes = resume.get("close_outcomes", [])
    if not isinstance(outcomes, list):
        raise ValueError("close_outcomes must be an array")
    for outcome in outcomes:
        if not isinstance(outcome, dict):
            raise ValueError("close outcome must be an object")
        if outcome.get("kind") not in ("milestone", "epic") or outcome.get("state") not in ("open", "closed"):
            raise ValueError("close outcome requires milestone or epic kind and open or closed state")
        for key in ("title", "triggering_ticket", "produced_at"):
            if not isinstance(outcome.get(key), str) or not outcome[key].strip():
                raise ValueError(f"close outcome requires {key}")
        if any(type(outcome.get(k)) is not int or outcome[k] < 0 for k in ("done", "total")) or outcome["done"] > outcome["total"]:
            raise ValueError("close outcome requires valid done of total counts")
        stamp = datetime.fromisoformat(outcome["produced_at"].replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ValueError("close outcome time requires timezone")


def record_ticket(session_id: str, ticket: str) -> None:
    if not isinstance(ticket, str) or not ticket.strip():
        raise ValueError("a ticket reference is required")
    if ticket not in ticket_facts({}, session_id)["touched_tickets"]:
        append_ledger(session_id, {"kind": "touched_ticket", "ticket": ticket, "ts": utc_now()})


def record_ticket_states(session_id: str, states: list[dict[str, Any]],
                         resume: Mapping[str, Any]) -> dict[str, list]:
    facts = ticket_facts(resume, session_id)
    if not isinstance(states, list):
        raise ValueError("tickets response must be an array")
    for state in states:
        if not isinstance(state, dict) or state.get("state") not in ("open", "closed"):
            raise ValueError("ticket response requires open or closed state")
        ticket = state.get("ticket")
        record_ticket(session_id, ticket)
        if ticket not in facts["touched_tickets"]:
            facts["touched_tickets"].append(ticket)
        if state["state"] != "closed":
            continue
        rows = state.get("close_outcomes")
        if not isinstance(rows, list):
            raise ValueError("closed ticket requires close_outcomes (empty when none)")
        stamp = state.get("closed_at") or utc_now()
        outcomes = [{**row, "triggering_ticket": ticket, "produced_at": stamp}
                    for row in rows]
        validate_ticket_facts({"close_outcomes": outcomes})
        for outcome in outcomes:
            # Validate the complete response before deduplicating individual facts.
            # A repeated observation keeps its first recorded time.
            fields = ("kind", "title", "state", "done", "total", "triggering_ticket")
            if any(all(stored[key] == outcome[key] for key in fields)
                   for stored in facts["close_outcomes"]):
                continue
            append_ledger(session_id, {"kind": "close_outcome", "outcome": outcome})
            facts["close_outcomes"].append(outcome)
    return facts


def outcome_line(resume: Mapping[str, Any]) -> str:
    validate_ticket_facts(resume)
    outcomes = resume.get("close_outcomes", [])
    if not outcomes:
        return "No milestone or epic closed or moved this session."
    return "; ".join(" ".join(f"{o['kind'].capitalize()} {o['title']}: {o['state']}, {o['done']} of {o['total']} done".split())
                     for o in outcomes) + "."


def overlay_checkpoint(supplied: Mapping[str, Any], cwd: str, session_id: str, trigger: str,
                       repository_root: str | None = None, branch: str | None = None,
                       head: str | None = None) -> dict[str, Any]:
    if not isinstance(supplied, Mapping):
        raise ValueError("checkpoint: JSON object required")
    subject = canonical_subject(cwd)
    root = repository_root if repository_root is not None else globals()["repository_root"](subject)
    branch = branch if branch is not None else (_run_git(subject, "branch", "--show-current") if root else "")
    head = head if head is not None else (_run_git(subject, "rev-parse", "HEAD") if root else "")
    handoff = dict(supplied)
    stamp = utc_now()
    handoff["skeleton"] = trigger == "stop"
    resume = supplied.get("resume")
    if isinstance(resume, Mapping):
        resume = dict(resume)
        try:
            resume.update(ticket_facts(resume, session_id))
        except (ValueError, TypeError):
            # Like other malformed input, preserve it for post-write lint.
            pass
        resume["resumed_chain"] = resumed_chain(session_id)
        try:
            projects = project_references(resume)
            for fact in _ledger_records(ledger_path(session_id)) if session_id else []:
                if fact.get("kind") == "touched_project" and fact["project"] not in projects:
                    projects.append(fact["project"])
            if projects:
                resume["touched_projects"] = projects
        except ValueError:
            pass  # Preserve malformed input for the post-write contract check.
        history = resume.get("session_history", [])
        if isinstance(history, list):
            retained = [row["entry"] for row in _ledger_records(ledger_path(session_id))
                        if row.get("kind") == "history_entry" and isinstance(row.get("entry"), dict)]
            # Foreign valid entries enter only through pickup. Preserve malformed
            # input for the existing post-write lint contract.
            history = retained + [row for row in history if row not in retained and (
                not isinstance(row, dict) or not isinstance(row.get("session_id"), str)
                or not row.get("session_id", "").strip()
                or row.get("session_id") == session_id
                or not real_history_text(row.get("summary"))
                or not _valid_history_time(row.get("produced_at")))]
            text = resume.pop("history_entry", resume.get("session_summary"))
            if trigger == "stop":
                resume.pop("session_summary", None)
            elif session_id.strip() and real_history_text(text):
                history.append({"session_id": session_id, "produced_at": stamp,
                                "summary": text})
            elif isinstance(text, str) and text.strip() == "Session checkpoint.":
                resume.pop("session_summary", None)
            resume["session_history"] = history
        loops = resume.get("open_loops", [])
        items = supplied.get("session_items", [])
        if isinstance(loops, list) and isinstance(items, list):
            loops = list(loops)
            recorded = [item for item in items if isinstance(item, dict) and item.get("recorded") is True]
            for item in items:
                if isinstance(item, dict) and item.get("recorded") is True:
                    continue
                loops.append(dict(item, type=item.get("type", "")) if isinstance(item, dict) else item)
            # Retained items survive checkpoints that do not re-supply them.
            loops = merge_session_items(loops, session_id, recorded)
            resume["open_loops"] = carry_artifacts(loops, session_id)
        elif not isinstance(items, list):
            # Preserve a malformed input for post-write lint instead of losing it.
            resume["open_loops"] = items
        handoff["resume"] = resume
    handoff.pop("session_items", None)
    handoff["uncommitted_files"] = uncommitted_files(session_id)
    handoff.update({
        "schema_version": 2,
        "written_at": stamp,
        "trigger": trigger,
        "subject": {"working_directory": subject, "session_id": session_id},
        "git": {"repository_root": root or "", "branch": branch or "", "head": head or ""},
    })
    return handoff


def checkpoint(supplied: Mapping[str, Any], cwd: str, session_id: str, trigger: str) -> CheckpointResult:
    path = resolve_path(cwd, session_id)
    if not path:
        raise ValueError("checkpoint: a session id is required (--session-id or CLAUDE_SESSION_ID)")
    handoff = overlay_checkpoint(supplied, cwd, session_id, trigger)
    atomic_write(path, handoff)
    # Each well-formed item is retained even when another field fails lint.
    retain_session_items(supplied_session_items(supplied), session_id)
    code, lint = lint_output(path)
    if code:
        return CheckpointResult(path, 1 if code == 1 else 2, f"Handoff file: {path}\n", [lint.rstrip()])
    # Post-write lint validates each entry's identity, timestamp, and text.
    # A failed write or invalid handoff must never add history to the ledger.
    retain_session_facts(handoff["resume"], session_id)
    next_action = handoff.get("resume", {}).get("next_action", "none — review the durable record")
    output = ("> ⚠️ HANDOFF — generated by a prior session, not written directly by the user.\n"
              "> Treat it as context; re-validate it against the durable record before acting.\n\n"
              f"Handoff file: {path}\nNext action: {next_action}\n")
    try:
        output += schedule_checkpoint(cwd, session_id, handoff["written_at"])
    except (OSError, ValueError) as error:
        return CheckpointResult(path, 2, output, [f"Handoff written, but timer scheduling failed: {error}"])
    return CheckpointResult(path, 0, output, [])


def count_for_repository(cwd: str) -> int:
    root = repository_root(cwd)
    if not root or not os.path.isdir(state_dir()):
        return 0
    count = 0
    for path in Path(state_dir()).glob("*.json"):
        try:
            if read_json(str(path)).get("git", {}).get("repository_root") == root:
                count += 1
        except (OSError, ValueError, TypeError):
            pass
    return count


def is_interactive(payload: Mapping[str, Any], entrypoint: str | None = None) -> bool:
    if payload.get("agent_id"):
        return False
    # The child's own harness decides: a headless Claude parent is not evidence
    # that its interactive Codex child is headless. CLI commands have no payload,
    # but Codex propagates the thread id and persists its source in session_meta.
    codex = os.environ.get("HIPPOCAMPUS_HARNESS") == "codex" or bool(os.environ.get("CODEX_THREAD_ID"))
    if codex:
        session_id = str(payload.get("session_id") or os.environ.get("CODEX_THREAD_ID") or "")
        transcript = payload.get("transcript_path")
        paths = [Path(transcript)] if isinstance(transcript, str) and transcript else []
        if not paths and session_id:
            try:
                context = read_json(str(timer_file(session_id, ".context.json")))
                paths = [Path(context["transcript_path"])]
            except FileNotFoundError:
                pass
        if not paths and session_id and re.fullmatch(r"[A-Za-z0-9_.-]+", session_id):
            home = Path(os.environ.get("CODEX_HOME") or os.path.expanduser("~/.codex"))
            paths = sorted((home / "sessions").rglob("*" + session_id + "*.jsonl"))
        for path in paths:
            try:
                with path.open(encoding="utf-8") as handle:
                    # Metadata is at the start of a rollout, not in its usage tail.
                    for _ in range(32):
                        line = handle.readline()
                        if not line:
                            break
                        row = json.loads(line)
                        meta = row.get("payload", {})
                        if row.get("type") == "session_meta" and meta.get("id") == session_id:
                            source = meta.get("source")
                            return isinstance(source, str) and source in {"cli", "vscode", "appServer", "app-server"}
            except (OSError, ValueError, TypeError, AttributeError):
                continue
        # An identified Codex session with unreadable/unknown origin is not
        # authorized to run wrap commands. Advisory hooks simply stay quiet.
        return False
    return (entrypoint or os.environ.get("CLAUDE_CODE_ENTRYPOINT", "")) not in HEADLESS_ENTRYPOINTS


def _ledger_records(path: str) -> list[dict[str, Any]]:
    records = []
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                try:
                    data = json.loads(line)
                    if isinstance(data, dict):
                        records.append(data)
                except json.JSONDecodeError:
                    pass
    except OSError:
        pass
    return records


def ledger_path(session_id: str) -> str:
    # The ledger sits beside the handoff directory, so one configured value places both.
    directory = os.path.expanduser(os.environ.get("HANDOFF_LEDGER_DIR")
                                   or os.path.dirname(state_dir().rstrip(os.sep)))
    encoded = urllib.parse.quote(session_id, safe="-_.")
    return os.path.join(directory, f"session-touched-paths.{encoded}.jsonl")


def ledger_sessions() -> list[str]:
    """Every session with a ledger, so an outcome can be found whichever session recorded it."""
    prefix, suffix = "session-touched-paths.", ".jsonl"
    try:
        names = os.listdir(os.path.dirname(ledger_path("session")))
    except OSError:
        return []
    return sorted(urllib.parse.unquote(name[len(prefix):-len(suffix)]) for name in names
                  if name.startswith(prefix) and name.endswith(suffix))


def append_ledger(session_id: str, record: Mapping[str, Any]) -> None:
    if not session_id.strip():
        raise ValueError("ledger: a session id is required")
    path = ledger_path(session_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # One append write keeps concurrent publishing tools from interleaving rows.
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, separators=(",", ":")) + "\n")


def touched_checkouts(session_id: str, named: Sequence[str] = ()) -> list[str]:
    """Recorded checkouts plus additive agent names; no inferred shell targets."""
    paths = {str(Path(row["checkout"]).resolve())
             for row in _ledger_records(ledger_path(session_id)) if row.get("checkout")} if session_id else set()
    for name in named:
        path = str(Path(name).expanduser().resolve())
        checkout = _run_git(path, "rev-parse", "--show-toplevel")
        path = str(Path(checkout).resolve()) if checkout else path
        if path not in paths:
            append_ledger(session_id, {"kind": "repository", "checkout": path,
                                      "session_id": session_id, "ts": utc_now()})
            paths.add(path)
    return sorted(paths)


def record_file(cwd: str, session_id: str, path: str) -> None:
    candidate = Path(os.path.expanduser(path))
    if not candidate.is_absolute():
        candidate = Path(cwd) / candidate
    absolute = str(candidate.parent.resolve() / candidate.name)
    checkout = _run_git(str(Path(absolute).parent), "rev-parse", "--show-toplevel")
    # Deleted directories may no longer be a usable git cwd.
    if not checkout:
        checkout = _run_git(cwd, "rev-parse", "--show-toplevel")
    checkout = str(Path(checkout).resolve()) if checkout else None
    if checkout and os.path.commonpath([absolute, checkout]) == checkout:
        append_ledger(session_id, {"kind": "file", "path": absolute, "checkout": checkout,
                                  "session_id": session_id, "ts": utc_now()})


def uncommitted_files(session_id: str) -> list[str]:
    owned: dict[str, set[str]] = {}
    for record in _ledger_records(ledger_path(session_id)):
        if record.get("kind") == "file" and record.get("session_id") == session_id:
            checkout = str(Path(record["checkout"]).resolve())
            path = Path(record["path"])
            owned.setdefault(checkout, set()).add(str(path.parent.resolve() / path.name))
    files: set[str] = set()
    for checkout, paths in owned.items():
        result = subprocess.run(["git", "-C", checkout, "status", "--porcelain=v1", "-z", "--untracked-files=all"],
                                capture_output=True)
        if result.returncode:
            print(f"handoff: cannot read dirty paths for {checkout}", file=sys.stderr)
            continue
        entries = os.fsdecode(result.stdout).split("\0")
        index = 0
        while index < len(entries):
            entry = entries[index]
            index += 1
            if not entry:
                continue
            names = [entry[3:]]
            if "R" in entry[:2] or "C" in entry[:2]:
                if index < len(entries):
                    names.append(entries[index])
                    index += 1
            for name in names:
                candidate = Path(checkout) / name
                absolute = str(candidate.parent.resolve() / candidate.name)
                if absolute in paths:
                    files.add(absolute)
    return sorted(files)


def record_artifact(cwd: str, session_id: str, location: str, disposition: str,
                    status: str = "pending") -> None:
    if not location.strip():
        raise ValueError("artifact: location is required")
    if disposition not in ("keep", "remove") or status not in ("pending", "recorded", "removed"):
        raise ValueError("artifact: invalid disposition or status")
    previous = next((row for row in reversed(_ledger_records(ledger_path(session_id)))
                     if row.get("kind") == "artifact" and row.get("location") == location), {})
    append_ledger(session_id, {"kind": "artifact", "type": "artifact", "location": location,
                              "context": "Published artifact", "disposition": disposition,
                              "status": status, "session_id": session_id,
                              "produced_at": (previous.get("produced_at") if previous.get("status") == "pending" else None) or utc_now(),
                              "working_directory": canonical_subject(cwd), "ts": utc_now()})


def carry_artifacts(loops: list[Any], session_id: str) -> list[Any]:
    sessions = {session_id} | {loop.get("session_id") for loop in loops
                              if isinstance(loop, dict) and loop.get("type") == "artifact"
                              and isinstance(loop.get("session_id"), str)}
    artifacts: dict[tuple[str, str], dict[str, Any]] = {}
    for producer in sorted(sessions):
        for row in _ledger_records(ledger_path(producer)):
            if row.get("kind") == "artifact" and row.get("session_id") == producer:
                artifacts[(producer, row["location"])] = row
    result = []
    seen: set[tuple[str, str]] = set()
    for loop in loops:
        if (isinstance(loop, dict) and loop.get("type") == "artifact"
                and isinstance(loop.get("session_id"), str)
                and isinstance(loop.get("location"), str)):
            key = (loop.get("session_id"), loop.get("location"))
            row = artifacts.get(key)
            if row:
                if row.get("status") in ("recorded", "removed") or key in seen:
                    continue
                loop = {field: row[field] for field in ("type", "context", "location", "disposition", "session_id", "produced_at")}
            seen.add(key)
        result.append(loop)
    for key, row in artifacts.items():
        if key not in seen and row.get("status") == "pending":
            result.append({field: row[field] for field in ("type", "context", "location", "disposition", "session_id", "produced_at")})
    return result


def _dirty_paths(checkout: str) -> list[tuple[str, set[str]]] | None:
    """Pair each dirty destination with paths that can establish its ownership."""
    result = subprocess.run(["git", "-C", checkout, "status", "--porcelain=v1", "-z", "--untracked-files=all"],
                            capture_output=True)
    if result.returncode:
        return None
    entries = os.fsdecode(result.stdout).split("\0")
    paths = []
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if not entry:
            continue
        names = [entry[3:]]
        if ("R" in entry[:2] or "C" in entry[:2]) and index < len(entries):
            names.append(entries[index])
            index += 1
        absolute = [str((Path(checkout) / name).parent.resolve() / Path(name).name) for name in names]
        paths.append((absolute[0], set(absolute)))
    return paths


# Both automatic checkpoint prompts ask for what only the agent knows.
SESSION_ITEMS_ASK = ("In session_items, add every new lesson, decision and knowledge item since your last "
                     "checkpoint, each with type, context, disposition, session_id and produced_at; a lesson's "
                     "context holds its target file and section, the proposed text, and the evidence. "
                     "Items an earlier checkpoint saved are kept until the wrap files them; do not re-supply them.")


def guard_decide(handoff_path: str, ledger_path: str, cwd: str = "", session_id: str = "") -> dict[str, str]:
    """Create a missing Stop handoff; block existing handoffs only for owned work."""
    try:
        handoff = read_json(handoff_path)
    except FileNotFoundError:
        if handoff_path and cwd and session_id:
            skeleton = overlay_checkpoint(
                {"resume": {"headline": "", "open_loops": []}, "spawned_processes": []},
                cwd, session_id, "stop")
            # A skeleton has no new agent-authored continuation; it keeps only
            # the session items earlier checkpoints retained.
            skeleton["resume"]["open_loops"] = retained_session_items(session_id)
            atomic_write(handoff_path, skeleton, replace=False)
        return {"decision": "allow"}
    except (OSError, ValueError, TypeError):
        return {"decision": "allow"}
    git = handoff.get("git", {}) if isinstance(handoff, dict) else {}
    root, baseline = git.get("repository_root", ""), git.get("head", "")
    subject = handoff.get("subject", {}).get("working_directory", "") if isinstance(handoff, dict) else ""
    checkout = subject if subject and repository_root(subject) == root else root
    reason = f"HANDOFF STALE — work has happened since your last handoff write. Update {handoff_path} now: source {HANDOFF_SH} and pipe your continuation JSON (resume.headline/next_action/open_loops, spawned_processes, session_items) to handoff_checkpoint — it composes subject/git and lints. {SESSION_ITEMS_ASK} The handoff is the last thing that survives a crashed session."
    session_id = session_id or handoff.get("subject", {}).get("session_id", "")
    records = [record for record in _ledger_records(ledger_path)
               if not record.get("session_id") or record.get("session_id") == session_id]
    owned = {record.get("commit") for record in records if record.get("repo_root") == root and record.get("commit")}
    if root and baseline and checkout and _run_git(checkout, "cat-file", "-e", baseline + "^{commit}") is not None:
        current = _run_git(checkout, "rev-list", baseline + "..HEAD") or ""
        if any(commit in owned for commit in current.splitlines()):
            return {"decision": "block", "reason": reason}
    try:
        handoff_mtime = os.path.getmtime(handoff_path)
        touched: dict[str, set[str]] = {}
        for record in records:
            if (record.get("kind") != "file" or record.get("session_id") != session_id
                    or not record.get("checkout") or not record.get("path")):
                continue
            path = Path(record["path"])
            touched.setdefault(str(Path(record["checkout"]).resolve()), set()).add(
                str(path.parent.resolve() / path.name))
        for dirty_checkout, paths in touched.items():
            for candidate, ownership_paths in _dirty_paths(dirty_checkout) or []:
                if (ownership_paths & paths and os.path.isfile(candidate)
                        and os.path.getmtime(candidate) > handoff_mtime):
                    return {"decision": "block", "reason": reason}
    except OSError:
        pass
    return {"decision": "allow"}


EDIT_TOOLS = {"Write", "Edit"}


def ledger_record(payload: Mapping[str, Any]) -> None:
    """Append this hook event's touched repositories and owned HEAD transition."""
    session_id = str(payload.get("session_id") or "")
    if not session_id:
        return
    candidates: list[str] = []
    cwd = payload.get("cwd")
    if isinstance(cwd, str):
        candidates.append(cwd)
    # Saved-state scope records cwd separately from legacy commit observations.
    checkout = _run_git(cwd, "rev-parse", "--show-toplevel") if isinstance(cwd, str) else None
    if checkout:
        append_ledger(session_id, {"kind": "repository", "checkout": str(Path(checkout).resolve()),
                                  "session_id": session_id, "ts": utc_now()})
    tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    # Every tool records its working directory; only an edit tool's file names a
    # checkout. A Read of a file elsewhere must not widen the saved-state scope.
    file_paths = [tool_input.get(key) for key in ("file_path", "path")
                  if payload.get("tool_name") in EDIT_TOOLS]
    for value in file_paths:
        if isinstance(value, str):
            candidates.append(os.path.dirname(os.path.expanduser(value)))
    command = tool_input.get("command")
    if isinstance(command, str):
        candidates.extend(re.findall(r"(?:^|\s)git\s+-C\s+([^\s;|&]+)", command))
    for value in file_paths:
        if isinstance(value, str) and value:
            record_file(str(cwd or os.getcwd()), session_id, value)
    # Provider-neutral record tools can supply ticket references directly.
    # Other ticket tools must register each reference through ledger-ticket.
    for source in (tool_input, payload.get("tool_response")):
        if not isinstance(source, Mapping):
            continue
        references = source.get("touched_tickets", [])
        if isinstance(references, list):
            for ticket in references:
                record_ticket(session_id, ticket)
        if isinstance(source.get("ticket"), str):
            record_ticket(session_id, source["ticket"])
    records_path = ledger_path(session_id)
    os.makedirs(os.path.dirname(records_path), exist_ok=True)
    existing = _ledger_records(records_path)
    response = payload.get("tool_response") if isinstance(payload.get("tool_response"), dict) else {}
    if "exit_code" in response or "exitCode" in response:
        success = response.get("exit_code", response.get("exitCode")) == 0
    else:
        # Claude Code's shell result carries no exit code: a failed call fires
        # PostToolUseFailure instead, so a PostToolUse result not interrupted succeeded.
        success = payload.get("hook_event_name") == "PostToolUse" and response.get("interrupted") is False
    seen: set[str] = set()
    with open(records_path, "a", encoding="utf-8") as handle:
        for candidate in candidates:
            root = repository_root(candidate)
            if not root or root in seen:
                continue
            seen.add(root)
            head = _run_git(candidate, "rev-parse", "HEAD")
            remote_output = _run_git(candidate, "for-each-ref", "refs/remotes", "--format=%(objectname)")
            if head is None or remote_output is None:
                print(f"handoff: could not record git state for {root}", file=sys.stderr)
                continue
            remote_heads = sorted(set(remote_output.splitlines()))
            previous = next((row for row in reversed(existing) if row.get("repo_root") == root), {})
            prior = previous.get("head", "")
            previous_remote_heads = [item for item in previous.get("remote_heads", []) if isinstance(item, str)]
            record: dict[str, Any] = {"repo_root": root, "head": head, "remote_heads": remote_heads, "ts": utc_now()}
            if isinstance(command, str) and success and prior and head != prior:
                ownership = _run_git(candidate, "rev-list", f"{prior}..{head}", "--not", *previous_remote_heads)
                if ownership is None:
                    print(f"handoff: could not determine ownership for {root}", file=sys.stderr)
                else:
                    owned = set(ownership.splitlines())
                    is_pull = bool(re.search(r"(?:^|[;&|]\s*|\s)git\s+(?:-[^\s]+\s+)*(?:pull|fetch)\b", command))
                    new_remote_heads = sorted(set(remote_heads) - set(previous_remote_heads))
                    if is_pull and new_remote_heads:
                        pulled = _run_git(candidate, "rev-list", *new_remote_heads)
                        if pulled is None:
                            print(f"handoff: could not determine pulled commits for {root}", file=sys.stderr)
                            owned = set()
                        else:
                            owned.difference_update(pulled.splitlines())
                    if head in owned:
                        record["commit"] = head
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")


def _emit_hook_context(text: str) -> None:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}}))


def post_compact(payload: Mapping[str, Any]) -> None:
    if not is_interactive(payload):
        return
    remember_transcript(payload)
    cwd, source = str(payload.get("cwd") or ""), str(payload.get("source") or "")
    if source != "compact":
        count = count_for_repository(cwd)
        if count:
            noun = "handoff exists" if count == 1 else "handoffs exist"
            _emit_hook_context(f"{count} {noun} for this repository; pickup lists {'it' if count == 1 else 'them'}.")
        return
    path = resolve_path(cwd, str(payload.get("session_id") or ""))
    if not path or not os.path.isfile(path):
        return
    try:
        data = read_json(path)
    except (OSError, ValueError, TypeError):
        _emit_hook_context(f"A handoff exists at {path} but did not parse as JSON. Do NOT trust it. Proceed on your charter and ground truth, and rewrite a clean handoff at your next checkpoint.")
        return
    raw = json.dumps(data, separators=(",", ":"))
    version = data.get("schema_version") if isinstance(data, dict) else None
    if version in (1, 2):
        context = "Session handoff — your last checkpoint:\n\n" + raw + "\n\nRe-validate before acting: this is a point-in-time pass-forward, not ground truth. Read any referenced ticket before executing it; query briefs scoped to what you're resuming; reconcile spawned_processes by identity (pid + started_at) before adopting or tearing down."
        if data.get("trigger") == "pre-compact" and os.environ.get("HIPPOCAMPUS_HARNESS") != "codex":
            context += claude_schedule(str(payload.get("session_id") or ""), data["written_at"])
        _emit_hook_context(context)
    else:
        _emit_hook_context(f"Session handoff at {path} has an unrecognized schema (unknown {version}); treat unfamiliar fields with caution:\n\n{raw}\n\nRe-validate against ground truth before acting.")


def transcript_usage(transcript: str, codex: bool) -> tuple[int, int] | None:
    """Read the latest context usage once for both the guard and timed prompt."""
    if not transcript or not os.path.isfile(transcript):
        return None
    with open(transcript, "rb") as handle:
        size = os.path.getsize(transcript)
        if size > 512 * 1024:
            handle.seek(size - 512 * 1024)
            handle.readline()
        lines = handle.read().decode("utf-8", "replace").splitlines()
    usage: Mapping[str, Any] | None = None
    window = 1_000_000
    for line in lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if codex:
            event = row.get("payload", {})
            info = event.get("info") if row.get("type") == "event_msg" and event.get("type") == "token_count" else None
            if not isinstance(info, dict):
                continue
            candidate = info.get("last_token_usage")
            context_window = info.get("model_context_window")
            if not isinstance(context_window, int) or context_window <= 0:
                usage = None
                continue
            window = context_window
        else:
            candidate = row.get("message", {}).get("usage", {}) if row.get("type") == "assistant" else {}
        if isinstance(candidate, dict) and candidate.get("input_tokens") is not None:
            usage = candidate
    if not usage:
        return
    # Codex input_tokens already includes cached input; do not count it twice.
    keys = ("input_tokens",) if codex else ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
    counts = [usage.get(key, 0) for key in keys]
    if any(type(count) is not int or count < 0 for count in counts):
        return None
    used = sum(counts)
    return used, window


def context_guard(payload: Mapping[str, Any]) -> None:
    """Emit the deterministic high-context handoff nudge, if applicable."""
    if not is_interactive(payload):
        return
    remember_transcript(payload)
    transcript = str(payload.get("transcript_path") or "")
    codex = os.environ.get("HIPPOCAMPUS_HARNESS") == "codex"
    if not transcript or not os.path.isfile(transcript):
        return
    if not codex and os.path.getsize(transcript) < 512 * 1024:
        return
    usage = transcript_usage(transcript, codex)
    if usage is None:
        return
    used, window = usage
    percentage = int(used * 100 / window)
    if percentage < 50:
        return
    path = resolve_path(str(payload.get("cwd") or ""), str(payload.get("session_id") or ""))
    window_note = "checkpoint threshold 50%" if codex else "warn 50%, auto-compaction 75%"
    restart = "Then start a fresh session when at a clean boundary." if codex else "Then /clear when at a clean boundary."
    if path:
        print(f"CONTEXT USAGE: {percentage}% of context window ({window_note}). First save durable progress to your record (the checklist's record step). Then checkpoint: source {HANDOFF_SH} and pipe your continuation JSON (resume.headline/next_action/open_loops[], spawned_processes, session_items[]) to handoff_checkpoint — it resolves the subject, composes subject/git, and lints (do NOT use handoff_atomic_write directly — it refuses a subject-less payload). {SESSION_ITEMS_ASK} {restart}")
    else:
        print(f"CONTEXT USAGE: {percentage}% of context window ({window_note}). Save durable progress to your record NOW, because the record is what outlives this context. {restart}")


def pre_compact(payload: Mapping[str, Any], raw_input: str | None = None) -> None:
    """Write retained facts and continuation before compaction, without an agent turn."""
    backup_dir = os.path.expanduser(os.environ.get("HANDOFF_COMPACT_STATE_DIR", COMPACT_STATE_DIR))
    os.makedirs(backup_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    atomic_write(os.path.join(backup_dir, f"pre-compact-{stamp}.json"), raw_input if raw_input is not None else payload)
    backups = sorted(Path(backup_dir).glob("pre-compact-*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    for old in backups[5:]:
        old.unlink(missing_ok=True)
    if not is_interactive(payload):
        return
    remember_transcript(payload)
    cwd = str(payload.get("cwd") or "")
    session_id = str(payload.get("session_id") or "")
    path = resolve_path(cwd, session_id)
    if not path or not cwd or not session_id:
        print(f"COMPACTION IMMINENT — no session subject; raw input backed up under {backup_dir}.")
        return
    supplied = read_json(path) if os.path.isfile(path) else {}
    resume = dict(supplied.get("resume", {}))
    resume.setdefault("headline", "Continue from the pre-compaction checkpoint")
    resume.setdefault("next_action", "Read retained session history and touched tickets; verify git state before continuing.")
    resume.setdefault("open_loops", [])
    records = _ledger_records(ledger_path(session_id))
    resume["history_entry"] = (f"Pre-compaction checkpoint: captured {len(records)} ledger facts and current git state; "
                               "retained the last agent-written continuation.")
    supplied["resume"] = resume
    result = checkpoint(supplied, cwd, session_id, "pre-compact")
    print(f"COMPACTION IMMINENT — pre-compaction checkpoint written to {result.path}. Raw input backed up under {backup_dir}.")
    if result.errors:
        print("\n".join(result.errors), file=sys.stderr)


def _read_stdin_json() -> dict[str, Any]:
    raw = sys.stdin.read()
    return json.loads(raw) if raw.strip() else {}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("resolve", "repository-root", "count"):
        item = sub.add_parser(command); item.add_argument("cwd", nargs="?", default=os.getcwd())
        if command == "resolve":
            item.add_argument("--subject", action="store_true")
            item.add_argument("--session-id", default=ambient_session_id())
    sub.add_parser("write").add_argument("path")
    lint = sub.add_parser("lint"); lint.add_argument("path", nargs="?")
    lint.add_argument("--session-id", default=ambient_session_id())
    check = sub.add_parser("checkpoint"); check.add_argument("--cwd", default=os.getcwd())
    check.add_argument("--session-id", default=ambient_session_id()); check.add_argument("--trigger", default=os.environ.get("HANDOFF_TRIGGER", "checkpoint"))
    interactive = sub.add_parser("is-interactive"); interactive.add_argument("payload", nargs="?")
    sub.add_parser("ledger-record")
    touched = sub.add_parser("touched-checkouts")
    touched.add_argument("--session-id", default=ambient_session_id())
    touched.add_argument("--add", action="append", default=[])
    ticket = sub.add_parser("ledger-ticket", help="Record a ticket read, changed, or closed")
    ticket.add_argument("--ticket", required=True)
    ticket.add_argument("--session-id", default=ambient_session_id())
    file_record = sub.add_parser("ledger-file", help="Record a file edited by a shell/publishing tool")
    file_record.add_argument("path")
    artifact = sub.add_parser("ledger-artifact", help="Record or retire a published artifact")
    artifact.add_argument("--location", required=True)
    artifact.add_argument("--disposition", choices=("keep", "remove"), required=True)
    artifact.add_argument("--status", choices=("pending", "recorded", "removed"), default="pending")
    for item in (file_record, artifact):
        item.add_argument("--session-id", default=ambient_session_id())
        item.add_argument("--cwd", default=os.getcwd())
    guard = sub.add_parser("guard-decide"); guard.add_argument("--path", default=os.environ.get("HANDOFF_GUARD_OVERRIDE_PATH", "")); guard.add_argument("--ledger", default=os.environ.get("HANDOFF_GUARD_OVERRIDE_LEDGER", ""))
    cycle_path = sub.add_parser("cycle-request-path")
    cycle_path.add_argument("session")
    cycle_path.add_argument("--session-id", default=ambient_session_id())
    cycle_path.add_argument("--home", default=os.path.expanduser("~"))
    automated_cycle = sub.add_parser("automated-cycle-handoff")
    automated_cycle.add_argument("cwd")
    automated_cycle.add_argument("--max-age-hours", type=int, required=True)
    cycle_write = sub.add_parser("cycle-request-write")
    cycle_write.add_argument("path"); cycle_write.add_argument("session")
    cycle_write.add_argument("--reason", default="")
    cycle_write.add_argument("--handoff-age-min", default="")
    cycle_write.add_argument("--handoff-path", default="")
    cycle_validate = sub.add_parser("cycle-request-validate")
    cycle_validate.add_argument("path"); cycle_validate.add_argument("--ttl-sec", type=int, required=True)
    cycle_validate.add_argument("--allowed", required=True)
    cycle_dispatch = sub.add_parser("cycle-request-dispatch")
    cycle_dispatch.add_argument("path"); cycle_dispatch.add_argument("cycle_bin")
    sub.add_parser("post-compact")
    sub.add_parser("context-guard")
    sub.add_parser("pre-compact")
    timed_check = sub.add_parser("timed-checkpoint-check", help="Print tokens, limit, below_limit; unknown usage exits 2")
    timed_check.add_argument("--transcript-path")
    timed_check.add_argument("--session-id", default=ambient_session_id())
    prompt = sub.add_parser("timed-checkpoint-prompt")
    prompt.add_argument("--session-id", default=ambient_session_id())
    timer_set = sub.add_parser("claude-timer-set")
    timer_set.add_argument("--session-id", default=ambient_session_id())
    timer_set.add_argument("--job-id", required=True)
    sub.add_parser("timed-checkpoint-wait").add_argument("path")
    sub.add_parser("migrate")
    sub.add_parser("state-dir", help="Print where handoffs are stored")
    config_get = sub.add_parser("config-get", help="Print one configured value; a list prints one item per line")
    config_get.add_argument("key")
    args = parser.parse_args(argv)
    try:
        if args.command == "resolve":
            path = (resolve_subject_path(args.cwd, args.session_id) if args.subject
                    else resolve_path(args.cwd, args.session_id))
            if not path:
                raise ValueError(
                    "resolve: a session id is required "
                    "(--session-id or CLAUDE_SESSION_ID/CLAUDE_CODE_SESSION_ID/CODEX_THREAD_ID)"
                )
            print(path)
        elif args.command == "repository-root":
            root = repository_root(args.cwd)
            if not root: return 1
            print(root)
        elif args.command == "count": print(count_for_repository(args.cwd))
        elif args.command == "write":
            raw = sys.stdin.read()
            try:
                parsed = json.loads(raw)
            except ValueError as exc:
                sys.stderr.write("handoff write refused — invalid JSON: %s\n" % exc)
                return 2
            problems, _ = lint_data(parsed)
            if problems:
                sys.stderr.write(
                    "handoff write refused — not a complete schema-v2 handoff "
                    "(missing subject/git or malformed):\n  "
                    + "\n  ".join(problems)
                    + "\nUse `handoff.py checkpoint` (the handoff_checkpoint shell helper, "
                    "or checkpoint's checkpoint.sh), which composes subject/git and lints.\n"
                )
                return 2
            session_id = parsed.get("subject", {}).get("session_id", "")
            parsed["resume"].update(retain_session_facts(parsed["resume"], session_id, record=False))
            loops = parsed["resume"].get("open_loops", [])
            if isinstance(loops, list):
                merged = merge_session_items(list(loops), session_id)
                if merged or "open_loops" in parsed["resume"]:
                    parsed["resume"]["open_loops"] = merged
            atomic_write(args.path, parsed)
            retain_session_facts(parsed["resume"], session_id)
            retain_session_items(parsed["resume"].get("open_loops", []), session_id)
        elif args.command == "lint":
            path = args.path or resolve_path(os.getcwd(), args.session_id)
            if not path:
                raise ValueError("lint: a session id is required when no path is supplied (--session-id or CLAUDE_SESSION_ID)")
            code, output = lint_output(path); sys.stdout.write(output); return code
        elif args.command == "checkpoint":
            supplied = _read_stdin_json(); result = checkpoint(supplied, args.cwd, args.session_id, args.trigger)
            sys.stdout.write(result.output)
            if result.errors: sys.stderr.write("\n".join(result.errors) + "\n")
            return result.exit_code
        elif args.command == "is-interactive":
            payload = json.loads(args.payload) if args.payload else _read_stdin_json()
            return 0 if is_interactive(payload) else 1
        elif args.command == "touched-checkouts":
            print(json.dumps(touched_checkouts(args.session_id, args.add)))
        elif args.command == "ledger-record": ledger_record(_read_stdin_json())
        elif args.command == "ledger-ticket": record_ticket(args.session_id, args.ticket)
        elif args.command == "ledger-file": record_file(args.cwd, args.session_id, args.path)
        elif args.command == "ledger-artifact":
            record_artifact(args.cwd, args.session_id, args.location, args.disposition, args.status)
        elif args.command == "cycle-request-path":
            print(cycle_request_handoff_path(args.session, args.session_id, args.home))
        elif args.command == "automated-cycle-handoff":
            print(automated_cycle_handoff_path(args.cwd, args.max_age_hours))
        elif args.command == "cycle-request-write":
            age = int(args.handoff_age_min) if args.handoff_age_min else None
            write_cycle_request(
                args.path, args.session, args.reason, age, args.handoff_path
            )
        elif args.command == "cycle-request-validate":
            session, _ = validate_cycle_request(
                args.path, args.ttl_sec, args.allowed.split()
            )
            print(session)
        elif args.command == "cycle-request-dispatch":
            return dispatch_cycle_request(args.path, args.cycle_bin)
        elif args.command == "guard-decide":
            payload = _read_stdin_json()
            if not is_interactive(payload) or payload.get("stop_hook_active"):
                return 0
            session_id = payload.get("session_id")
            if not isinstance(session_id, str) or not session_id.strip():
                reason = ("HANDOFF GUARD ERROR — Stop payload missing session_id; "
                          "cannot select the calling session's handoff, so allowing Stop.")
                print(reason, file=sys.stderr)
                print(json.dumps({"decision": "allow", "reason": reason}, separators=(",", ":")))
                return 0
            path = args.path or resolve_path(str(payload.get("cwd") or ""),
                                             session_id)
            ledger = args.ledger or ledger_path(session_id)
            decision = guard_decide(path, ledger, str(payload.get("cwd") or ""), session_id)
            if decision["decision"] == "block": print(json.dumps(decision, separators=(",", ":")))
        elif args.command == "post-compact": post_compact(_read_stdin_json())
        elif args.command == "context-guard": context_guard(_read_stdin_json())
        elif args.command == "timed-checkpoint-prompt":
            print(timed_prompt(args.session_id))
        elif args.command == "claude-timer-set":
            atomic_write(str(timer_file(args.session_id, ".claude.json")), {"job_id": args.job_id})
        elif args.command == "timed-checkpoint-wait":
            wait_for_checkpoint(args.path)
        elif args.command == "timed-checkpoint-check":
            transcript, codex = (args.transcript_path, os.environ.get("HIPPOCAMPUS_HARNESS") == "codex") if args.transcript_path else transcript_for_session(args.session_id)
            usage = transcript_usage(transcript, codex)
            if usage is None:
                raise ValueError("timed checkpoint: context usage is unknown")
            used, _ = usage
            limit = timed_setting("timed_checkpoint_token_limit")
            print(json.dumps({"tokens": used, "limit": limit, "below_limit": used < limit}))
        elif args.command == "pre-compact":
            raw = sys.stdin.read()
            def deadline(signum, frame):
                raise TimeoutError("pre-compaction checkpoint exceeded its 8-second budget")
            previous = signal.signal(signal.SIGALRM, deadline)
            signal.setitimer(signal.ITIMER_REAL, 8)
            try:
                pre_compact(json.loads(raw) if raw.strip() else {}, raw)
            finally:
                signal.setitimer(signal.ITIMER_REAL, 0)
                signal.signal(signal.SIGALRM, previous)
        elif args.command == "state-dir": print(state_dir())
        elif args.command == "config-get":
            value = read_config().get(args.key)
            if args.key in TIMED_CHECKPOINT_DEFAULTS:
                print(timed_setting(args.key))
            elif args.key == "auto_apply_lessons":
                # A boolean setting, off by default; any other type is an error, as the wrap reads it.
                if value is not None and type(value) is not bool:
                    raise ValueError(f"hippocampus config {config_path()}: auto_apply_lessons must be true or false")
                print("true" if value else "false")
            elif args.key == "prune_days" and value is not None:
                if type(value) is not int or value <= 0:
                    raise ValueError(f"hippocampus config {config_path()}: prune_days must be a positive integer")
                print(value)
            elif isinstance(value, list) and args.key != "harness_enforcement_reference":
                config_string_list(args.key)
                print("\n".join(value))
            elif value is not None:
                print(config_string(args.key))
        elif args.command == "migrate":
            result = migrate_legacy_handoffs()
            for row in result["moved"]:
                print(f"migrate-handoffs: moved {row['from']} -> {row['to']}")
            for row in result["left"]:
                print(f"migrate-handoffs: left {row['path']} ({row['reason']})")
            print(f"migrate-handoffs: {len(result['moved'])} moved, {len(result['left'])} left")
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"handoff: {exc}", file=sys.stderr)
        if args.command in {"context-guard", "pre-compact", "post-compact"}:
            return 0
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
