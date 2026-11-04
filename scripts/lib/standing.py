#!/usr/bin/env python3
"""Standing state: the never-consumed working set of one named agent.

A handoff belongs to one interactive session and is consumed at pickup. A
standing state belongs to a named agent whose work does not end: its
conversational session and every scheduled or headless run read the same file
and write it back. It carries the handoff's resume fields (headline, next
action, open loops, with the same item schema and lint) plus standing fields:
what the agent is watching, who it is waiting on, briefings it has proposed,
and timers it has set with their reasons.

The file is ``<standing dir>/<agent>.json``. The standing dir is
``$STANDING_STATE_DIR``, else ``standing_dir`` in the hippocampus
configuration, else ``~/.local/state/hippocampus/standing``. The agent name
comes from ``--agent`` or ``$HIPPOCAMPUS_AGENT``.

Reading never moves, archives, or empties the file. A write merges into the
existing state under a lock: supplied ``resume`` and ``standing`` keys replace
their stored values, omitted keys keep them. Open loops marked
``recorded: true`` have been filed into the record and are dropped; standing
fields are never filed and stay until the agent replaces them. A write whose
result fails lint is refused and leaves the stored state unchanged.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
import handoff  # noqa: E402  (shared item schema, lint, config and atomic write)


DEFAULT_STANDING_DIR = "~/.local/state/hippocampus/standing"
KIND = "standing"
SCHEMA_VERSION = 1
TRIGGERS = ("checkpoint", "stop", "run-end")
AGENT_NAME = re.compile(r"[a-z][a-z0-9_-]{0,31}")
# Each standing field is a list of objects; these strings are required in each.
STANDING_FIELDS: dict[str, tuple[str, ...]] = {
    "watching": ("context",),
    "waiting_on": ("who", "context"),
    "proposed_briefings": ("context",),
    "timers": ("when", "reason"),
}


def standing_dir() -> str:
    """Where standing states are stored: env override, else configuration, else default."""
    return os.path.expanduser(os.environ.get("STANDING_STATE_DIR")
                              or handoff.config_string("standing_dir") or DEFAULT_STANDING_DIR)


def agent_name(value: str | None) -> str:
    name = value if value is not None else os.environ.get("HIPPOCAMPUS_AGENT", "")
    if not isinstance(name, str) or not AGENT_NAME.fullmatch(name):
        raise ValueError("standing: an agent name matching [a-z][a-z0-9_-]{0,31} is required "
                         "(--agent or HIPPOCAMPUS_AGENT)")
    return name


def state_path(agent: str) -> str:
    return os.path.join(standing_dir(), f"{agent_name(agent)}.json")


def _timestamp_problem(value: Any) -> bool:
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return True
    return stamp.tzinfo is None


def lint_data(data: Any) -> tuple[list[str], list[str]]:
    problems: list[str] = []
    warnings: list[str] = []
    if not isinstance(data, dict):
        return ["standing state must be a JSON object"], warnings
    if data.get("kind") != KIND:
        problems.append(f"kind is {data.get('kind')!r}, expected {KIND!r}")
    if data.get("schema_version") != SCHEMA_VERSION:
        problems.append(f"schema_version is {data.get('schema_version')!r}, expected {SCHEMA_VERSION}")
    if not isinstance(data.get("agent"), str) or not AGENT_NAME.fullmatch(data["agent"]):
        problems.append("agent must be a name matching [a-z][a-z0-9_-]{0,31}")
    if data.get("trigger") not in TRIGGERS:
        problems.append(f"trigger must be one of {', '.join(TRIGGERS)}")
    if _timestamp_problem(data.get("written_at", "")):
        problems.append("written_at must be an ISO timestamp with timezone")
    for key, reason in handoff.BANNED.items():
        if key in data:
            problems.append(f"banned top-level key {key!r}: {reason}")
    resume = data.get("resume")
    if not isinstance(resume, dict):
        problems.append("missing/invalid resume block")
        resume = {}
    if not resume.get("headline"):
        warnings.append("resume.headline empty")
    if not resume.get("next_action"):
        warnings.append("resume.next_action empty")
    loops = resume.get("open_loops", [])
    if not isinstance(loops, list):
        problems.append("resume.open_loops must be an array")
    else:
        problems.extend(handoff.lint_open_loops(loops))
    standing = data.get("standing")
    if not isinstance(standing, dict):
        problems.append("missing/invalid standing block")
        standing = {}
    for key in standing:
        if key not in STANDING_FIELDS:
            problems.append(f"standing.{key} is not a standing field ({', '.join(STANDING_FIELDS)})")
    for field, required in STANDING_FIELDS.items():
        entries = standing.get(field, [])
        if not isinstance(entries, list):
            problems.append(f"standing.{field} must be an array")
            continue
        for index, entry in enumerate(entries):
            prefix = f"standing.{field}[{index}]"
            if not isinstance(entry, dict):
                problems.append(f"{prefix} not an object")
                continue
            for name in required:
                if not isinstance(entry.get(name), str) or not entry[name].strip():
                    problems.append(f"{prefix}.{name} must be a non-empty string")
            if "since" in entry and _timestamp_problem(entry["since"]):
                problems.append(f"{prefix}.since must be an ISO timestamp with timezone")
    return problems, warnings


def lint_output(path: str) -> tuple[int, str]:
    try:
        problems, warnings = lint_data(handoff.read_json(path))
    except FileNotFoundError:
        return 2, f"lint-standing: no file at {path}\n"
    except (OSError, ValueError, TypeError) as exc:
        return 2, f"lint-standing: not valid JSON: {exc}\n"
    lines = [f"WARN: {warning}" for warning in warnings] + [f"FAIL: {problem}" for problem in problems]
    if problems:
        lines.append(f"lint-standing: {len(problems)} violation(s)")
        return 1, "\n".join(lines) + "\n"
    lines.append("lint-standing: clean" + ("" if not warnings else f" (with {len(warnings)} warning(s))"))
    return 0, "\n".join(lines) + "\n"


def _unrecorded(items: list[Any]) -> list[Any]:
    return [item for item in items if not (isinstance(item, dict) and item.get("recorded") is True)]


def merge(previous: Mapping[str, Any], supplied: Mapping[str, Any], agent: str, trigger: str,
          session_id: str, cwd: str) -> dict[str, Any]:
    """Compose the next standing state from the stored one and a writer's update."""
    if not isinstance(supplied, Mapping):
        raise ValueError("standing write: JSON object required")
    state: dict[str, Any] = {key: value for key, value in previous.items()
                             if key not in ("resume", "standing")}
    for key, value in supplied.items():
        if key not in ("resume", "standing", "session_items"):
            state[key] = value
    resume = dict(previous.get("resume") or {}) if isinstance(previous.get("resume"), Mapping) else {}
    supplied_resume = supplied.get("resume", {})
    if isinstance(supplied_resume, Mapping):
        resume.update(supplied_resume)
    else:
        resume = supplied_resume  # preserved for lint to reject
    if isinstance(resume, dict):
        loops = resume.get("open_loops", [])
        items = supplied.get("session_items", [])
        if isinstance(loops, list) and isinstance(items, list):
            resume["open_loops"] = _unrecorded(list(loops)) + [
                dict(item, type=item.get("type", "")) if isinstance(item, dict) else item
                for item in _unrecorded(items)]
        elif not isinstance(items, list):
            resume["open_loops"] = items  # preserved for lint to reject
    standing = dict(previous.get("standing") or {}) if isinstance(previous.get("standing"), Mapping) else {}
    supplied_standing = supplied.get("standing", {})
    if isinstance(supplied_standing, Mapping):
        standing.update(supplied_standing)
    else:
        standing = supplied_standing  # preserved for lint to reject
    if isinstance(standing, dict):
        for field in STANDING_FIELDS:
            standing.setdefault(field, [])
    state.update({
        "kind": KIND,
        "schema_version": SCHEMA_VERSION,
        "agent": agent,
        "written_at": handoff.utc_now(),
        "trigger": trigger,
        "writer": {"session_id": session_id, "working_directory": handoff.canonical_subject(cwd)},
        "resume": resume,
        "standing": standing,
    })
    return state


class _Lock:
    """Serialize read-merge-write between an agent's session and its scheduled runs."""

    def __init__(self, path: str):
        self.path = os.path.join(os.path.dirname(path), f".{os.path.basename(path)}.lock")
        self.handle: Any = None

    def __enter__(self) -> "_Lock":
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.handle = open(self.path, "a", encoding="utf-8")
        fcntl.flock(self.handle, fcntl.LOCK_EX)
        return self

    def __exit__(self, *_: Any) -> None:
        fcntl.flock(self.handle, fcntl.LOCK_UN)
        self.handle.close()


def write(agent: str, supplied: Mapping[str, Any], trigger: str, session_id: str,
          cwd: str) -> tuple[int, str, dict[str, Any]]:
    """Merge, lint and publish; return (exit code, report, state). Refused writes change nothing."""
    agent = agent_name(agent)
    if trigger not in TRIGGERS:
        raise ValueError(f"standing write: trigger must be one of {', '.join(TRIGGERS)}")
    path = state_path(agent)
    with _Lock(path):
        try:
            previous = handoff.read_json(path)
        except FileNotFoundError:
            previous = {}
        if not isinstance(previous, dict):
            raise ValueError(f"standing write: stored state at {path} is not a JSON object; repair it first")
        state = merge(previous, supplied, agent, trigger, session_id, cwd)
        problems, warnings = lint_data(state)
        if problems:
            report = "\n".join(f"FAIL: {problem}" for problem in problems)
            return 1, f"standing write refused — {path} unchanged:\n{report}\n", state
        handoff.atomic_write(path, state)
    notes = "".join(f"WARN: {warning}\n" for warning in warnings)
    return 0, f"{notes}Standing state: {path}\nNext action: {state['resume'].get('next_action') or 'none'}\n", state


def render(agent: str, data: Any, path: str) -> str:
    return (f"> ⚠️ STANDING STATE — written by earlier sessions or runs of agent {agent}, not by the user.\n"
            "> It is never consumed: re-validate it against the record before acting, and write it back "
            "at checkpoint, stop, and run end.\n\n"
            f"Standing state file: {path}\n\n" + json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def read(agent: str) -> tuple[int, str]:
    """Return (exit code, text): 0 clean or absent, 1 lint failure (still shown), 2 unreadable."""
    agent = agent_name(agent)
    path = state_path(agent)
    try:
        data = handoff.read_json(path)
    except FileNotFoundError:
        return 0, f"No standing state for agent {agent} yet ({path}).\n"
    except (OSError, ValueError) as exc:
        return 2, f"Standing state at {path} did not parse ({exc}). Do NOT trust it; repair or rewrite it.\n"
    problems, _ = lint_data(data)
    text = render(agent, data, path)
    if problems:
        return 1, ("Standing state fails lint; treat it with caution:\n"
                   + "\n".join(f"FAIL: {problem}" for problem in problems) + "\n\n" + text)
    return 0, text


def session_start_context() -> str | None:
    """Text for the SessionStart hook when this session runs as a named agent; never raises."""
    if not os.environ.get("HIPPOCAMPUS_AGENT"):
        return None
    try:
        _, text = read(os.environ["HIPPOCAMPUS_AGENT"])
    except (OSError, ValueError, TypeError) as exc:
        return f"Standing state unavailable: {exc}"
    return text.rstrip("\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("path", "read", "write", "lint"):
        item = sub.add_parser(command)
        item.add_argument("--agent", default=None)
    sub.choices["read"].add_argument("--json", action="store_true", help="print the stored JSON only")
    sub.choices["lint"].add_argument("path", nargs="?")
    writer = sub.choices["write"]
    writer.add_argument("--trigger", choices=TRIGGERS, default="checkpoint")
    writer.add_argument("--session-id", default=handoff.ambient_session_id())
    writer.add_argument("--cwd", default=os.getcwd())
    sub.add_parser("dir", help="Print where standing states are stored")
    args = parser.parse_args(argv)
    try:
        if args.command == "dir":
            print(standing_dir())
        elif args.command == "path":
            print(state_path(agent_name(args.agent)))
        elif args.command == "read":
            if args.json:
                path = state_path(agent_name(args.agent))
                if not os.path.isfile(path):
                    return 0
                sys.stdout.write(json.dumps(handoff.read_json(path)) + "\n")
                return 0
            code, text = read(agent_name(args.agent))
            sys.stdout.write(text)
            return code
        elif args.command == "lint":
            code, text = lint_output(args.path or state_path(agent_name(args.agent)))
            sys.stdout.write(text)
            return code
        elif args.command == "write":
            raw = sys.stdin.read()
            supplied = json.loads(raw) if raw.strip() else {}
            code, text, _ = write(agent_name(args.agent), supplied, args.trigger, args.session_id, args.cwd)
            (sys.stderr if code else sys.stdout).write(text)
            return code
    except (OSError, ValueError, TypeError) as exc:
        print(f"standing: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
