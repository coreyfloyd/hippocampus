#!/usr/bin/env python3
"""Compose the fixed checklist spine and route carried items, using stdlib only.

This module does not execute skills or write handoffs. The skill runs the plan,
collects explicit saved-item receipts, and sends the settled payload to checkpoint.
Filing judgments come from the skill; source items and provenance pass through intact.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Mapping, Sequence

SLOTS = ("record", "knowledge", "lessons", "persist")
TYPES = {"progress", "commitment", "decision", "knowledge", "lesson", "artifact", "open_loop"}
TITLES = ("Reconcile the record", "Capture knowledge", "Fold in lessons", "Persist")
SPINE = (*SLOTS, "handoff")
# The one step allowed after the handoff: removing the session's own worktree earlier
# would leave the handoff naming no repository, so `/pickup` could not find it.
AFTER_HANDOFF = "own-worktree"
# What an unbound slot leaves in the handoff: the item types its step exists for.
CARRIES = {"record": ["progress", "commitment", "decision", "artifact"], "knowledge": ["knowledge"],
           "lessons": ["lesson"], "persist": []}
# How a step ended, as the run reports it. `carried` is an unbound slot.
STATUSES = ("run", "carried", "pending", "failed")
UNATTENDED_RULE = ("Nobody is present to answer: a step that needs the user's answer reports "
                   "pending with the answer it needs, writes nothing, and the checklist continues. "
                   "Before the handoff, apply the filing rules; user decisions go to the ask binding.")


def _spine_steps_named(value: Any) -> list[str]:
    """Spine step names a disallowed profile field refers to, for its error."""
    if isinstance(value, str):
        return [value] if value in SPINE else []
    if isinstance(value, Mapping):
        value = [*value.keys(), *value.values()]
    if isinstance(value, (list, tuple)):
        return list(dict.fromkeys(step for item in value for step in _spine_steps_named(item)))
    return []


def _removed_spine_steps(profile: Mapping[str, Any], fields: Sequence[str]) -> list[str]:
    named: list[str] = []
    for field in fields:
        steps = _spine_steps_named(profile[field])
        # A restated spine order removes what it leaves out; other fields name their target.
        if field in ("spine", "order") and isinstance(profile[field], list):
            steps = [step for step in SPINE if step not in steps]
        named.extend(steps)
    return list(dict.fromkeys(named))


def load_profile(path: Path) -> dict[str, Any]:
    """Read JSON or a Markdown profile with one checklist-profile JSON fence."""
    text = Path(path).read_text()
    if Path(path).suffix == ".json":
        profile = json.loads(text)
    else:
        fences = re.findall(r"^```checklist-profile\s*\n(.*?)^```\s*$", text, re.M | re.S)
        if len(fences) != 1:
            raise ValueError(f"{path}: expected one checklist-profile fence")
        profile = json.loads(fences[0])
    if not isinstance(profile, dict):
        raise ValueError(f"{path}: profile must be an object")
    # A section reference keeps instructions and machine-readable ordering together.
    for entry in [*profile.get("bindings", {}).values(), *profile.get("steps", [])]:
        if entry is None:
            continue
        if not isinstance(entry, dict):
            raise ValueError(f"{path}: binding/step must be an object")
        section = entry.pop("section", None)
        if section is not None:
            match = re.search(r"^## " + re.escape(section) + r"\s*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
            if not match or not match[1].strip():
                raise ValueError(f"{path}: missing instructions section {section}")
            entry["instructions"] = match[1].strip()
    return profile


def record_read_binding(profile: Mapping[str, Any]) -> dict[str, str] | None:
    """The optional user-bound read skill, separate from the writing slots."""
    if "record_read" not in profile:
        return None
    binding = profile["record_read"]
    if (not isinstance(binding, Mapping) or set(binding) != {"command"}
            or not isinstance(binding["command"], str) or not binding["command"].strip()):
        raise ValueError(f"{profile.get('name', 'profile')}: record_read requires only a non-empty command")
    return dict(binding)


def ask_binding(profile: Mapping[str, Any]) -> dict[str, str] | None:
    """One user command for asks, separate from the spine and its slots."""
    if "ask" not in profile:
        return None
    binding = profile["ask"]
    if (not isinstance(binding, Mapping) or set(binding) != {"command"}
            or not isinstance(binding["command"], str) or not binding["command"].strip()):
        raise ValueError(f"{profile.get('name', 'profile')}: ask requires only a non-empty command")
    return dict(binding)


def compose(profiles: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Merge user then repository additions; no profile can alter the spine."""
    bindings: dict[str, Any] = {
        "record": None, "knowledge": None,
        "lessons": {"command": "/improve-harness", "consumes": ["lesson"]},
        "persist": None,
    }
    additions: dict[str, list[dict[str, Any]]] = {anchor: [] for anchor in ("before-spine", *SPINE)}
    seen = set((*SLOTS, "handoff"))
    bound: set[str] = set()
    for profile in profiles:
        if not isinstance(profile, Mapping):
            raise ValueError("profile must be an object")
        name = profile.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("profile requires a name")
        unknown = sorted(set(profile) - {"name", "bindings", "steps", "record_read", "ask"})
        if unknown:
            steps = _removed_spine_steps(profile, unknown)
            if steps:
                raise ValueError(f"{name}: cannot remove or skip spine step {', '.join(steps)}")
            raise ValueError(f"{name}: unknown profile field {', '.join(unknown)}")
        record_read_binding(profile)
        ask_binding(profile)
        declared = profile.get("bindings", {})
        if not isinstance(declared, Mapping):
            raise ValueError(f"{name}: bindings must be an object")
        for slot, binding in declared.items():
            if slot not in SLOTS or slot in bound:
                raise ValueError(f"{name}: cannot replace step/binding {slot}")
            if binding is None:
                bindings[slot] = None
                bound.add(slot)
                continue
            if not isinstance(binding, Mapping) or set(binding) - {"command", "consumes", "instructions"}:
                raise ValueError(f"{name}: invalid binding for {slot}")
            command = binding.get("command")
            consumes = binding.get("consumes")
            if not isinstance(command, str) or not command.strip():
                raise ValueError(f"{name}: cannot remove or skip spine step {slot}; a binding requires a command")
            if not isinstance(consumes, list) or any(not isinstance(t, str) or t not in TYPES for t in consumes):
                raise ValueError(f"{name}: {slot} requires known consumed item types")
            bindings[slot] = copy.deepcopy(dict(binding))
            bound.add(slot)
        steps = profile.get("steps", [])
        if not isinstance(steps, list):
            raise ValueError(f"{name}: steps must be an array")
        for step in steps:
            if not isinstance(step, Mapping) or set(step) - {"id", "after", "instructions", "title"}:
                raise ValueError(f"{name}: invalid added step {step}")
            identity, anchor = step.get("id"), step.get("after")
            if not isinstance(identity, str) or not identity.strip() or identity in seen:
                raise ValueError(f"{name}: cannot replace or duplicate step {identity}")
            if identity == AFTER_HANDOFF and anchor != "handoff":
                raise ValueError(f"{name}: step {AFTER_HANDOFF} must follow handoff, not {anchor}")
            if anchor == "handoff" and identity != AFTER_HANDOFF:
                raise ValueError(f"{name}: cannot add step {identity} after handoff; only {AFTER_HANDOFF} may follow it")
            if not isinstance(anchor, str) or anchor not in additions:
                raise ValueError(f"{name}: step {identity} has unknown anchor {anchor}")
            if not isinstance(step.get("instructions"), str) or not step["instructions"].strip():
                raise ValueError(f"{name}: step {identity} requires instructions")
            seen.add(identity)
            additions[anchor].append({**copy.deepcopy(dict(step)), "profile": name})
    plan = additions["before-spine"][:]
    for slot, title in zip(SLOTS, TITLES):
        step = {"id": slot, "slot": slot, "title": title, "binding": bindings[slot]}
        if bindings[slot] is None:
            step["carries"] = list(CARRIES[slot])
        plan.append(step)
        plan.extend(additions[slot])
    plan.append({"id": "handoff", "title": "Write and validate the handoff"})
    plan.extend(additions["handoff"])
    return plan


def slot_inputs(plan: Sequence[Mapping[str, Any]], slot: str,
                handoff: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Select indexed carried loops without changing their producing identity."""
    if slot not in SLOTS:
        raise ValueError(f"unknown slot {slot}")
    step = next(s for s in plan if s.get("slot") == slot)
    binding = step.get("binding")
    consumes = binding["consumes"] if binding else []
    resume = handoff.get("resume", {})
    if not isinstance(resume, Mapping) or not isinstance(resume.get("open_loops", []), list):
        raise ValueError("resume.open_loops must be an array")
    return [{"index": index, "item": copy.deepcopy(item)}
            for index, item in enumerate(resume.get("open_loops", []))
            if isinstance(item, dict) and item.get("type") in consumes]


def settle(plan: Sequence[Mapping[str, Any]], handoff: Mapping[str, Any],
           receipts: Mapping[str, Sequence[int]]) -> dict[str, Any]:
    """Remove only loops explicitly acknowledged as saved by their binding.

    Receipt indexes refer to the original input, across all slots. Pending,
    failed, unbound, unknown-type and legacy loops are retained. The caller must
    checkpoint the returned payload; the resumed source file is never mutated.
    """
    if not isinstance(receipts, Mapping):
        raise ValueError("receipts must be an object")
    removed: set[int] = set()
    for slot, indexes in receipts.items():
        eligible = {entry["index"] for entry in slot_inputs(plan, slot, handoff)}
        if not isinstance(indexes, list) or any(type(i) is not int or i not in eligible for i in indexes):
            raise ValueError(f"{slot}: receipt includes an item this binding cannot consume")
        removed.update(indexes)
    result = copy.deepcopy(dict(handoff))
    if "resume" in result and "open_loops" in result["resume"]:
        result["resume"]["open_loops"] = [loop for i, loop in enumerate(result["resume"]["open_loops"]) if i not in removed]
    return result


def filing_binding(rule: str, item: Mapping[str, Any], row: Mapping[str, Any]) -> str | None:
    """Resolve the destination binding after the agent chooses the first matching rule."""
    if rule in ("R1", "R6"):
        return None
    if rule == "R3" or (rule == "R4" and row.get("destination") == "ask"):
        return "ask"
    if rule == "R4":
        if item.get("type") not in ("lesson", "knowledge"):
            raise ValueError("R4 requires a lesson or knowledge item")
        return "lessons" if item["type"] == "lesson" else "knowledge"
    return "record"


def file_items(plan: Sequence[Mapping[str, Any]], handoff: Mapping[str, Any],
               outcomes: Sequence[Mapping[str, Any]], ask: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Bookkeep explicit filing outcomes; never execute commands or infer saved writes.

    The skill supplies one row per remaining loop and unrecorded current item.
    Failed reads and writes keep the source item intact. This is a wrap operation;
    checkpoint and the earlier saved-slot receipt protocol remain unchanged.
    """
    loops = handoff.get("resume", {}).get("open_loops", [])
    current = handoff.get("session_items", [])
    if (not isinstance(loops, list) or not isinstance(current, list)
            or not all(isinstance(item, Mapping) for item in [*loops, *current])):
        raise ValueError("filing items must be arrays of objects")
    loops = [*loops, *(item for item in current if item.get("recorded") is not True)]
    if (not isinstance(outcomes, list) or not all(isinstance(row, Mapping) for row in outcomes)
            or any(type(row.get("index")) is not int for row in outcomes)
            or sorted(row["index"] for row in outcomes) != list(range(len(loops)))):
        raise ValueError("filing requires exactly one outcome for every item")
    bindings = {step["slot"]: step.get("binding") for step in plan if "slot" in step}
    bindings["ask"] = ask
    result = copy.deepcopy(dict(handoff))
    report: dict[str, Any] = {"items": [], "warnings": [], "failures": [], "asks": {}}
    kept = []
    for row in sorted(outcomes, key=lambda row: row["index"]):
        item = loops[row["index"]]
        rule, status = row.get("rule"), row.get("status")
        if rule not in ("R1", "R3", "R4", "R7", "R2", "R5", "R6"):
            raise ValueError(f"filing: unknown rule {rule!r}")
        if status not in ("filed", "dropped", "pending", "failed", "read failed"):
            raise ValueError(f"filing: unknown status {status!r}")
        binding = filing_binding(rule, item, row)
        entry = {**copy.deepcopy(dict(row)), "item": copy.deepcopy(item), "binding": binding}
        label = item.get("context", str(item))
        error = row.get("error") or "missing, unsupported, or malformed record read"
        # Information-only R1 does not depend on a record read. Other R1,
        # R2 and R5 require explicit evidence that the read succeeded.
        needs_read = rule in ("R2", "R5") or (rule == "R1" and not row.get("information_only"))
        if status == "read failed" or (needs_read and row.get("read_status") != "ok"):
            entry.update(status="read failed", error=error)
            report["failures"].append(f"{label}: read failed: {error}")
            kept.append(copy.deepcopy(item))
        elif binding is None:
            if status != "dropped" or not isinstance(row.get("reason"), str) or not row["reason"].strip():
                raise ValueError(f"{label}: {rule} requires dropped with a reason")
        else:
            if binding == "ask":
                choices = row.get("choices")
                if not isinstance(choices, list) or not choices or not all(isinstance(c, str) and c.strip() for c in choices):
                    raise ValueError(f"{label}: an ask requires the user's choices")
                subject = handoff.get("subject", {})
                entry["ask"] = {"text": label, "session_id": item.get("session_id") or subject.get("session_id"),
                                "directory": subject.get("working_directory"),
                                "ticket": (item.get("anchor") or {}).get("ticket"), "choices": choices}
                report["asks"].setdefault(entry["ask"]["directory"] or "unknown directory", []).append(entry["ask"])
            if bindings[binding] is None:
                entry["status"] = "unbound"
                report["warnings"].append(f"{label}: missing {binding} binding; kept in handoff")
                kept.append(copy.deepcopy(item))
            elif status != "filed":
                entry["error"] = row.get("error") or "no successful write receipt"
                report["failures"].append(f"{label}: {binding} write failed: {entry['error']}")
                kept.append(copy.deepcopy(item))
            elif not isinstance(row.get("destination"), str) or not row["destination"].strip():
                raise ValueError(f"{label}: a filed item requires its destination or receipt")
            elif rule == "R5" and (not row.get("priority") or not row.get("priority_reason")):
                raise ValueError(f"{label}: a new ticket requires priority and priority_reason")
        report["items"].append(entry)
    result.setdefault("resume", {})["open_loops"] = kept
    result["resume"]["next_action"] = ("Session finished." if not kept else
        "Unfiled items: " + "; ".join(item.get("context", str(item)) for item in kept))
    result.pop("session_items", None)
    result["filing"] = report
    return result


def filing_check(plan: Sequence[Mapping[str, Any]], data: Mapping[str, Any],
                 ask: Mapping[str, str] | None = None) -> tuple[list[str], list[str]]:
    """Validate filing failures and reject bound items still carried after a wrap."""
    report = data.get("filing", {})
    if not isinstance(report, Mapping):
        return ["filing report must be an object"], []
    failures = list(report.get("failures", []))
    warnings = list(report.get("warnings", []))
    bindings = {step["slot"]: step.get("binding") for step in plan if "slot" in step}
    bindings["ask"] = ask
    loops = data.get("resume", {}).get("open_loops", [])
    for row in report.get("items", []):
        item = row.get("item")
        if row.get("status") in ("unbound", "pending", "failed", "read failed") and item not in loops:
            failures.append(f"{item.get('context', str(item))}: retained item missing from handoff")
    if "filing" in data and not loops and data.get("resume", {}).get("next_action") != "Session finished.":
        failures.append("resume.next_action must say Session finished. when filing is complete")
    for item in loops:
        if not isinstance(item, Mapping):
            continue  # The handoff linter names this error.
        entry = next((row for row in report.get("items", []) if row.get("item") == item), None)
        label = item.get("context", str(item))
        binding = entry.get("binding") if entry else (
            "ask" if item.get("type") == "decision" else
            "lessons" if item.get("type") == "lesson" else
            "knowledge" if item.get("type") == "knowledge" else "record")
        if entry and entry.get("status") == "read failed":
            failures.append(f"{label}: read failed: {entry.get('error')}")
        elif binding is None or bindings.get(binding) is not None:
            failures.append(f"{label}: still carried with bound {binding or 'drop'} destination")
        else:
            warnings.append(f"{label}: missing {binding} binding; kept in handoff")
    return list(dict.fromkeys(failures)), list(dict.fromkeys(warnings))


def _load_handoff_module() -> Any:
    spec = importlib.util.spec_from_file_location("handoff", Path(__file__).with_name("handoff.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def unattended_settings() -> dict[str, Any]:
    """The optional ``unattended`` section of the continuity configuration.

    The package does not know how a user launches an unattended session. A user
    who does names, under ``unattended``: ``state_module`` (a Python file
    exposing ``state_path(session_id)`` and ``read_state(path, session_id)``,
    which return where a session's mode record lives and its contents, a mapping
    with ``mode``, ``updated_by`` and ``updated_at``), ``completion_command``
    (a regular expression matching the command that completes an unattended
    slate), and ``completed_by`` (the ``updated_by`` values that command leaves).
    With the section absent every session is attended.
    """
    value = _load_handoff_module().read_config().get("unattended")
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("continuity config: unattended must be an object")
    return value


def _load_session_mode_module() -> Any:
    """The configured state module, or None when no unattended mode is configured."""
    path = unattended_settings().get("state_module")
    if path is None:
        return None
    if not isinstance(path, str) or not path.strip():
        raise ValueError("continuity config: unattended.state_module must be a non-empty string")
    module_path = Path(path).expanduser()
    name = "continuity_unattended_state"
    if name in sys.modules and getattr(sys.modules[name], "__file__", None) == str(module_path):
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, module_path)
    if spec is None or spec.loader is None:
        raise ValueError(f"continuity config: unattended.state_module {module_path} cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    # Dataclasses in the module resolve their own module by name while it loads.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def session_kind(payload: Mapping[str, Any], entrypoint: str | None = None) -> str:
    """Only an interactive session runs the checklist; factory sessions and subagents never do."""
    if payload.get("agent_id"):
        return "subagent"
    return "interactive" if _load_handoff_module().is_interactive(payload, entrypoint) else "factory"


def completion_pattern() -> "re.Pattern[str] | None":
    """The configured pattern for the command that completes an unattended slate, if any."""
    pattern = unattended_settings().get("completion_command")
    if pattern is None:
        return None
    if not isinstance(pattern, str) or not pattern.strip():
        raise ValueError("continuity config: unattended.completion_command must be a non-empty string")
    return re.compile(pattern)


def is_completion_command(command: Any) -> bool:
    """True when the command completes an unattended slate, as configured."""
    pattern = completion_pattern()
    return bool(pattern and isinstance(command, str) and pattern.search(command))


def completed_by() -> set[str]:
    """The ``updated_by`` values a completion command leaves in the session's mode record."""
    return set(unattended_settings().get("completed_by") or [])


# Commands that run the checklist or write a handoff; only an interactive session may.
WRAP_COMMAND = re.compile(r"checklist\.py['\"]?\s+(?:plan|settle|file|wrap-check|report)\b"
                          r"|checkpoint\.sh\b|handoff\.py['\"]?\s+checkpoint\b")


DEFAULT_STATE_DIR = "~/.local/state/continuity/checklist"


def _configured_state_dir() -> str:
    """The configured ``checklist_state_dir``, else the package default."""
    return _load_handoff_module().config_string("checklist_state_dir") or DEFAULT_STATE_DIR


def _unattended_marker(session_id: str) -> Path:
    """Exists from a slate's completion until its unattended wrap passes the wrap check."""
    root = Path(os.environ.get("CHECKLIST_STATE_DIR") or _configured_state_dir()).expanduser()
    return root / f"{re.sub(r'[^A-Za-z0-9_.-]', '_', session_id)}.unattended-wrap"


def wrap_cadence(payload: Mapping[str, Any], entrypoint: str | None = None) -> str:
    """What finishing a unit of work calls for now.

    `none` for factory sessions and subagents. `checkpoint` while an unattended
    session (the configured state module reports mode `afk`) is mid-slate.
    `unattended-checklist` from the completion command returning it to attended
    mode until its unattended wrap passes; the completion call itself records
    that, since the reset erases the unattended mode. `checklist` otherwise,
    which is every session when no unattended mode is configured.
    """
    if session_kind(payload, entrypoint) != "interactive":
        return "none"
    session_id = str(payload.get("session_id") or "")
    modes = _load_session_mode_module()
    state = None
    if modes is not None:
        path = modes.state_path(session_id)
        state = modes.read_state(path, session_id) if path is not None and path.exists() else None
    if state is not None and state.get("mode") == "afk":
        return "checkpoint"
    marker = _unattended_marker(session_id)
    if marker.exists():
        return "unattended-checklist"
    command = (payload.get("tool_input") or {}).get("command")
    if (state is not None and state.get("updated_by") in completed_by() and is_completion_command(command)):
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps({"session_id": session_id, "completed_at": state.get("updated_at")}) + "\n")
        return "unattended-checklist"
    return "checklist"


def actor_guard(payload: Mapping[str, Any], entrypoint: str | None = None) -> str | None:
    """The deny reason for a factory session or subagent running the checklist, else None."""
    command = (payload.get("tool_input") or {}).get("command")
    if not isinstance(command, str) or not WRAP_COMMAND.search(command):
        return None
    kind = session_kind(payload, entrypoint)
    if kind == "interactive":
        return None
    return f"checklist DENY: a {kind} session never runs the checklist or writes a handoff"


def check_report(plan: Sequence[Mapping[str, Any]], results: Sequence[Mapping[str, Any]],
                 unattended: bool = False) -> list[str]:
    """Return what is wrong with a run's step results; empty means the report stands.

    Every planned step reports, in plan order, so a pending or failed step never
    ends the run early. A pending step names the answer it waits for and wrote
    nothing. Unattended, nothing may wait: every step reports, and the handoff runs.
    """
    if not isinstance(results, list) or not all(isinstance(r, Mapping) for r in results):
        return ["results must be an array of step objects"]
    planned = [step["id"] for step in plan]
    reported = [result.get("id") for result in results]
    problems = [] if reported == planned else [f"steps reported {reported}, plan is {planned}"]
    for result in results:
        identity, status = result.get("id"), result.get("status")
        if status not in STATUSES:
            problems.append(f"{identity}: status {status!r} is not one of {', '.join(STATUSES)}")
        elif status == "pending":
            if not isinstance(result.get("reason"), str) or not result["reason"].strip():
                problems.append(f"{identity}: a pending step names the answer it needs")
            if result.get("writes"):
                problems.append(f"{identity}: a pending step writes nothing, but wrote {result['writes']}")
    handoff = next((r for r in results if r.get("id") == "handoff"), None)
    if unattended and (handoff is None or handoff.get("status") != "run"):
        problems.append("handoff: an unattended run still writes the handoff")
    return problems


def session_summary(plan: Sequence[Mapping[str, Any]], summary: str | None,
                    unavailable: str | None) -> tuple[dict[str, Any], list[str]]:
    """The session summary the report starts with, and what is wrong with it.

    A bound `record` composes it after its ticket step,
    so a bound record needs either its text or the reason it could not be
    composed. With `record` unbound, nothing composes one and the report says so.
    """
    if summary is not None and unavailable is not None:
        return {}, ["session summary: pass --summary or --no-summary, not both"]
    if summary is not None:
        if not summary.strip():
            return {}, ["session summary: the summary file is empty"]
        return {"summary": summary}, []
    if unavailable is not None:
        if not unavailable.strip():
            return {}, ["session summary: --no-summary names why it is unavailable"]
        return {"summary": None, "summary_unavailable": unavailable.strip()}, []
    record = next(step for step in plan if step.get("slot") == "record")
    if record.get("binding") is None:
        return {"summary": None, "summary_unavailable": "record unbound: no binding composes a session summary"}, []
    command = record["binding"]["command"]
    return {}, [f"session summary: missing; pass --summary <file> from {command}, or, when its output has "
                f"none (an older binding, or a failed compose), --no-summary \"{command} composed no session "
                "summary\" or the reason it gave"]


def _timestamp(value: Any, label: str) -> datetime:
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        stamp = None
    if stamp is None or stamp.tzinfo is None:
        raise ValueError(f"{label} must be an ISO timestamp with timezone, got {value!r}")
    return stamp


# The ledger row `plan` writes when the checklist starts.
START_MARKER = "checklist-start"


def mark_start(session_id: str) -> None:
    """Record in the session's ledger that the checklist started."""
    handoff = _load_handoff_module()
    handoff.append_ledger(session_id, {"kind": START_MARKER, "session_id": session_id, "ts": handoff.utc_now()})


def last_change(session_id: str) -> str | None:
    """Latest change the session's ledger holds: an edited file, artifact, or owned commit.

    Rows appended after the latest start marker are the checklist's own wrap-up
    writes, not the session's work, so they do not count.
    """
    handoff = _load_handoff_module()
    rows = handoff._ledger_records(handoff.ledger_path(session_id))
    starts = [index for index, row in enumerate(rows) if row.get("kind") == START_MARKER]
    if starts:
        rows = rows[:starts[-1]]
    stamps = [row["ts"] for row in rows
              if row.get("ts") and (row.get("kind") in ("file", "artifact") or row.get("commit"))]
    return max(stamps, key=lambda ts: _timestamp(ts, "ledger ts"), default=None)


def wrap_check(plan: Sequence[Mapping[str, Any]], handoff_path: Path,
               record_at: str | None = None, ask: Mapping[str, str] | None = None) -> list[str]:
    """Return the reasons wrap fails; an empty list means wrap may report success.

    The handoff must pass its validity check. Only a bound `record` slot adds a
    freshness check: the record must not predate the session's last change
    made before the checklist started.
    """
    handoff = _load_handoff_module()
    try:
        problems, _ = handoff.lint_file(str(handoff_path))
    except FileNotFoundError:
        return [f"handoff invalid: no file at {handoff_path}"]
    except (OSError, ValueError, TypeError) as error:
        return [f"handoff invalid: not valid JSON: {error}"]
    failures = [f"handoff invalid: {problem}" for problem in problems]
    data = handoff.read_json(str(handoff_path)) if not problems else {}
    filing_failures, _ = filing_check(plan, data, ask)
    failures.extend(filing_failures)
    record = next(step for step in plan if step.get("slot") == "record")
    if record.get("binding") is None:
        return failures
    command = record["binding"]["command"]
    if not record_at:
        return failures + [f"record not checked: {command} is bound but no record time was supplied"]
    data = handoff.read_json(str(handoff_path)) if not problems else {}
    session_id = (data.get("subject") or {}).get("session_id") if isinstance(data, dict) else None
    if not session_id:
        return failures + ["record not checked: the handoff names no session"]
    recorded = _timestamp(record_at, "record time")
    changed = last_change(session_id)
    if changed and recorded < _timestamp(changed, "ledger ts"):
        failures.append(f"record stale: {command} recorded at {record_at}, "
                        f"older than the session's last change at {changed}")
    return failures


def _handoff_session(path: Path) -> str | None:
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None
    subject = data.get("subject") if isinstance(data, dict) else None
    session_id = subject.get("session_id") if isinstance(subject, dict) else None
    return session_id if isinstance(session_id, str) and session_id else None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("plan", "settle", "file", "wrap-check", "report", "wrap-cadence", "actor-guard",
                                                      "is-completion-command"))
    parser.add_argument("--user-profile", type=Path)
    parser.add_argument("--repository-profile", type=Path, action="append", default=[])
    parser.add_argument("--handoff", type=Path)
    parser.add_argument("--receipts", type=Path)
    parser.add_argument("--filing", type=Path, help="file: explicit outcome for each remaining item")
    parser.add_argument("--written-handoff", type=Path, help="wrap-check: the handoff step 5 wrote")
    parser.add_argument("--record-at", help="wrap-check: time of the record's latest write or passing check")
    parser.add_argument("--unattended", action="store_true",
                        help="plan/report/wrap-check: nobody is present to answer a step")
    parser.add_argument("--results", type=Path, help="report: the run's step results, in order")
    parser.add_argument("--session-id", help="plan: the current session, whose ledger gets the start marker")
    parser.add_argument("--summary", type=Path, help="report: the session summary the record binding composed")
    parser.add_argument("--no-summary", help="report: why no session summary could be composed")
    args = parser.parse_args(argv)
    try:
        if args.operation == "wrap-cadence":
            # The hook payload arrives on stdin; the answer is one word.
            print(wrap_cadence(json.loads(sys.stdin.read() or "{}")))
            return 0
        if args.operation == "is-completion-command":
            # Exit 0 when the hook payload's command completes an unattended slate, as configured.
            payload = json.loads(sys.stdin.read() or "{}")
            return 0 if is_completion_command((payload.get("tool_input") or {}).get("command")) else 1
        if args.operation == "actor-guard":
            # A PreToolUse hook: the hook payload is the only place a subagent shows.
            reason = actor_guard(json.loads(sys.stdin.read() or "{}"))
            if reason:
                print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                  "permissionDecision": "deny", "permissionDecisionReason": reason}}))
            return 0
        kind = session_kind({})
        if kind != "interactive":
            raise ValueError(f"a {kind} session never runs the checklist or writes a handoff")
        paths = ([args.user_profile] if args.user_profile else []) + args.repository_profile
        profiles = [load_profile(path) for path in paths]
        for path, profile in zip(args.repository_profile, profiles[1:] if args.user_profile else profiles):
            if "ask" in profile:
                raise ValueError(f"{path}: repository profiles cannot bind ask")
            if "record_read" in profile:
                raise ValueError(f"{path}: repository profiles cannot bind record_read")
            if profile.get("bindings"):
                raise ValueError(f"{path}: repository profiles only add steps; cannot bind {', '.join(profile['bindings'])}")
        plan = compose(profiles)
        ask = ask_binding(profiles[0]) if args.user_profile else None
        handoff = json.loads(args.handoff.read_text()) if args.handoff else {}
        if not isinstance(handoff, dict):
            raise ValueError("handoff must be an object")
        if args.operation == "plan":
            session_id = args.session_id or _load_handoff_module().ambient_session_id()
            if session_id:
                if not args.unattended:
                    # An explicit attended plan starts every step afresh even if
                    # the earlier unattended wrap failed and left its marker.
                    _unattended_marker(session_id).unlink(missing_ok=True)
                mark_start(session_id)
            else:
                print("checklist: no session id; the wrap check will count wrap-up changes", file=sys.stderr)
            for step in plan:
                if "slot" in step:
                    step["carried_items"] = slot_inputs(plan, step["slot"], handoff)
            output = {"profiles": [str(path) for path in paths], "unattended": args.unattended, "steps": plan,
                      "record_read": record_read_binding(profiles[0]) if args.user_profile else None,
                      "ask": ask, "rerun_all_steps": True}
            if args.unattended:
                output["when_answer_needed"] = UNATTENDED_RULE
        elif args.operation == "file":
            if not args.handoff or not args.filing:
                raise ValueError("file requires --handoff and --filing")
            output = file_items(plan, handoff, json.loads(args.filing.read_text()), ask)
        elif args.operation == "wrap-check":
            if not args.written_handoff:
                raise ValueError("wrap-check requires --written-handoff")
            failures = wrap_check(plan, args.written_handoff, args.record_at, ask)
            session_id = _handoff_session(args.written_handoff)
            marker = _unattended_marker(session_id) if session_id else None
            if marker is not None and marker.exists() and not args.unattended:
                failures.append("this session's slate completed unattended; "
                                "run the checklist with --unattended on plan, report, and wrap-check")
            data = json.loads(args.written_handoff.read_text()) if args.written_handoff.exists() and not failures else {}
            _, warnings = filing_check(plan, data, ask)
            for warning in warnings:
                print(f"checklist: warning: {warning}", file=sys.stderr)
            for failure in failures:
                print(f"checklist: wrap failed: {failure}", file=sys.stderr)
            if failures:
                return 1
            if marker is not None and args.unattended:
                marker.unlink(missing_ok=True)
            record = next(step for step in plan if step.get("slot") == "record")
            output = {"wrap": "ok", "record_check": "passed" if record["binding"] else "not run: record unbound"}
        elif args.operation == "report":
            if not args.results or not args.handoff:
                raise ValueError("report requires --results and --handoff")
            handoff_problems, _ = _load_handoff_module().lint_data(handoff)
            if handoff_problems:
                raise ValueError("report handoff invalid: " + "; ".join(handoff_problems))
            results = json.loads(args.results.read_text())
            summary, problems = session_summary(
                plan, args.summary.read_text() if args.summary else None, args.no_summary)
            problems += check_report(plan, results, args.unattended)
            for problem in problems:
                print(f"checklist: report invalid: {problem}", file=sys.stderr)
            if problems:
                return 1
            filing_failures, warnings = filing_check(plan, handoff, ask)
            for problem in filing_failures:
                print(f"checklist: report invalid: {problem}", file=sys.stderr)
            if filing_failures:
                return 1
            # The report starts with the session summary.
            output = {**summary, "report": "ok", "pending": [r["id"] for r in results if r["status"] == "pending"],
                      "filing": handoff.get("filing", {}), "warnings": warnings}
        else:
            if not args.handoff or not args.receipts:
                raise ValueError("settle requires --handoff and --receipts")
            output = settle(plan, handoff, json.loads(args.receipts.read_text()))
        print(json.dumps(output, indent=2))
        return 0
    except (OSError, ValueError, TypeError, AttributeError) as error:
        print(f"checklist: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
