#!/usr/bin/env python3
"""Compose the fixed checklist spine and route carried items, using stdlib only.

This module executes record-write commands but never writes handoffs. The skill runs the plan,
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

_record_spec = importlib.util.spec_from_file_location("record_write", Path(__file__).with_name("record_write.py"))
record_write = importlib.util.module_from_spec(_record_spec)
_record_spec.loader.exec_module(record_write)
_lessons_spec = importlib.util.spec_from_file_location("lessons", Path(__file__).with_name("lessons.py"))
lessons = importlib.util.module_from_spec(_lessons_spec)
_lessons_spec.loader.exec_module(lessons)
_knowledge_spec = importlib.util.spec_from_file_location("knowledge", Path(__file__).with_name("knowledge.py"))
knowledge = importlib.util.module_from_spec(_knowledge_spec)
_knowledge_spec.loader.exec_module(knowledge)
_over_limit_spec = importlib.util.spec_from_file_location("over_limit", Path(__file__).with_name("over_limit.py"))
over_limit = importlib.util.module_from_spec(_over_limit_spec)
_over_limit_spec.loader.exec_module(over_limit)

SLOTS = ("persist",)
NATIVE = {"knowledge": {"command": "/hippocampus:knowledge-capture", "consumes": ["knowledge"]},
          "lessons": {"command": "/hippocampus:improve-harness", "consumes": ["lesson"]}}
NATIVE_STATUSES = ("nothing", "not configured", "declined")
TYPES = {"progress", "commitment", "decision", "knowledge", "lesson", "artifact", "open_loop"}
TITLES = ("Reconcile the record", "Capture knowledge", "Fold in lessons", "Persist")
SPINE = ("record", "knowledge", "lessons", "persist", "handoff")
# The one step allowed after the handoff: removing the session's own worktree earlier
# would leave the handoff naming no repository, so `/hippocampus:pickup` could not find it.
AFTER_HANDOFF = "own-worktree"
# What unbound destinations leave in the handoff: the item types their step exists for.
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


def reject_native_bindings(profile: Mapping[str, Any], label: str, text: str = "") -> None:
    """Refuse obsolete bindings with an explicit manual deletion instruction."""
    bindings = profile.get("bindings", {})
    if not isinstance(bindings, Mapping):
        return  # The normal profile validator reports malformed bindings.
    fence = re.search(r"^```checklist-profile\s*\n(.*?)^```\s*$", text, re.M | re.S)
    start, end = fence.span(1) if fence else (0, len(text))
    obsolete = []
    for step in NATIVE:
        if step not in bindings:
            continue
        match = re.compile(r'"' + step + r'"\s*:').search(text, start, end)
        line = text.count("\n", 0, match.start()) + 1 if match else None
        location = f" (line {line})" if line else ""
        obsolete.append(f"bindings.{step}{location}")
    if obsolete:
        raise ValueError(f"{label}: delete the {', '.join(obsolete)} binding blocks, including their "
                         "command/consumes/instructions lines; knowledge and lessons are native steps. "
                         "Only persist is a configurable slot; ask is a separate binding. "
                         "No automatic conversion is performed")


def reject_record_binding(profile: Mapping[str, Any]) -> None:
    if isinstance(profile.get("bindings"), Mapping) and "record" in profile["bindings"]:
        raise ValueError('retired bindings.record: use record_writes: '
                         '{"tickets": {"command": "..."}, "projects": {"command": "..."}, '
                         '"documents": {"command": "..."}, "scheduled_jobs": {"command": "..."}}')


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
    reject_record_binding(profile)
    reject_native_bindings(profile, str(path), text)
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


def load_profiles(user_profile: Path | None, repository_profiles: Sequence[Path]) -> list[dict[str, Any]]:
    paths = ([user_profile] if user_profile else []) + list(repository_profiles)
    profiles = [load_profile(path) for path in paths]
    for path, profile in zip(repository_profiles, profiles[1:] if user_profile else profiles):
        if "record_writes" in profile:
            raise ValueError(f"{path}: repository profiles cannot bind record_writes")
        if "ask" in profile:
            raise ValueError(f"{path}: repository profiles cannot bind ask")
        if "record_read" in profile:
            raise ValueError(f"{path}: repository profiles cannot bind record_read")
        if profile.get("bindings"):
            raise ValueError(f"{path}: repository profiles only add steps; cannot bind {', '.join(profile['bindings'])}")
    return profiles


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
    bindings: dict[str, Any] = {"record": None, "persist": None, **copy.deepcopy(NATIVE)}
    additions: dict[str, list[dict[str, Any]]] = {anchor: [] for anchor in ("before-spine", *SPINE)}
    seen = set(SPINE)
    bound: set[str] = set()
    writes = {}
    for profile in profiles:
        if not isinstance(profile, Mapping):
            raise ValueError("profile must be an object")
        name = profile.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("profile requires a name")
        unknown = sorted(set(profile) - {"name", "bindings", "steps", "record_read", "record_writes", "ask"})
        if unknown:
            steps = _removed_spine_steps(profile, unknown)
            if steps:
                raise ValueError(f"{name}: cannot remove or skip spine step {', '.join(steps)}")
            raise ValueError(f"{name}: unknown profile field {', '.join(unknown)}")
        reject_record_binding(profile)
        declared_writes = record_write.bindings(profile)
        if "record_writes" in profile:
            if writes:
                raise ValueError(f"{name}: cannot replace record_writes")
            writes = declared_writes
        record_read_binding(profile)
        ask_binding(profile)
        declared = profile.get("bindings", {})
        if not isinstance(declared, Mapping):
            raise ValueError(f"{name}: bindings must be an object")
        reject_native_bindings(profile, name)
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
    bindings["record"] = {"command": "/hippocampus:record", "consumes": CARRIES["record"]}
    plan = additions["before-spine"][:]
    for slot, title in zip(SPINE[:-1], TITLES):
        step = {"id": slot, "title": title, "binding": bindings[slot]}
        if slot == "record":
            step.update(package=True, record_writes=writes)
        elif slot in NATIVE:
            step["native"] = True
        else:
            step["slot"] = slot
        if bindings[slot] is None or (slot == "record" and not any(writes.values())):
            step["carries"] = list(CARRIES[slot])
        plan.append(step)
        plan.extend(additions[slot])
    plan.append({"id": "handoff", "title": "Write and validate the handoff"})
    plan.extend(additions["handoff"])
    return plan


def slot_inputs(plan: Sequence[Mapping[str, Any]], slot: str,
                handoff: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Select indexed carried loops without changing their producing identity."""
    if slot not in ("record", *SLOTS, *NATIVE):
        raise ValueError(f"unknown step {slot}")
    step = next(s for s in plan if s["id"] == slot)
    binding = step.get("binding")
    consumes = binding["consumes"] if binding else []
    if slot == "record" and not any(step["record_writes"].values()):
        consumes = []
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
        if slot == "record":
            raise ValueError("record requires per-item record-write receipts; use file or record")
        eligible = {entry["index"] for entry in slot_inputs(plan, slot, handoff)}
        if not isinstance(indexes, list) or any(type(i) is not int or i not in eligible for i in indexes):
            raise ValueError(f"{slot}: receipt includes an item this binding cannot consume")
        removed.update(indexes)
    result = copy.deepcopy(dict(handoff))
    if "resume" in result and "open_loops" in result["resume"]:
        loops = result["resume"]["open_loops"]
        result["resume"]["open_loops"] = [loop for i, loop in enumerate(loops) if i not in removed]
        # A saved item is settled, so no later checkpoint restores it from the ledger.
        module = _load_handoff_module()
        session_id = result.get("subject", {}).get("session_id") or module.ambient_session_id()
        module.settle_session_items([loop for i, loop in enumerate(loops) if i in removed], session_id)
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


def validate_ask_payload(ask: Mapping[str, Any]) -> None:
    """Require complete text and usable choices for both new and stored asks.

    An ask about an applied lesson reports what happened, so it has no choices. A fact
    about the user is an ordinary ask: it keeps its choices and never has a default.
    """
    if not isinstance(ask.get("text"), str) or not ask["text"].strip():
        raise ValueError("an ask requires non-empty text")
    if ask.get("applied"):
        return
    choices = ask.get("choices")
    if not isinstance(choices, list) or not choices or not all(isinstance(c, str) and c.strip() for c in choices):
        raise ValueError(f"{ask['text']}: an ask requires the user's choices")
    if ask.get("user_fact") and "default" in ask:
        raise ValueError(f"{ask['text']}: a fact about the user has no default")


def ask_payload(item: Mapping[str, Any], subject: Mapping[str, Any]) -> dict[str, Any]:
    """Keep the complete proposal and provenance alongside the ask's text and choices."""
    text = item["ask_text"] if item.get("applied") or item.get("user_fact") else item.get("context", str(item))
    ask = {**copy.deepcopy(dict(item)), "text": text,
           "session_id": item.get("session_id") or subject.get("session_id"),
           "directory": subject.get("working_directory"),
           "ticket": (item.get("anchor") or {}).get("ticket"),
           "choices": [] if item.get("applied") else copy.deepcopy(item.get("choices", []))}
    validate_ask_payload(ask)
    return ask


def report_asks(handoff: Mapping[str, Any], problems: list[str]) -> list[dict[str, Any]]:
    """List every recoverable ask, even when another item is malformed or missing."""
    asks = []
    seen = set()
    subject = handoff.get("subject", {})
    candidates = []
    for index, row in enumerate(handoff.get("filing", {}).get("items", [])):
        if "ask" in row:
            candidates.append((f"filing.items[{index}].ask", row["ask"], True))
        elif (row.get("status") in ("unbound", "pending", "failed", "read failed", "uncertain", *NATIVE_STATUSES)
              and isinstance(row.get("item"), Mapping)
              and (row["item"].get("choices") or row["item"].get("applied"))):
            candidates.append((f"filing.items[{index}].item", row["item"], False))
    groups = handoff.get("filing", {}).get("asks", {})
    if not isinstance(groups, Mapping):
        problems.append("filing.asks must be an object")
    else:
        for directory, payloads in groups.items():
            if not isinstance(payloads, list):
                problems.append(f"filing.asks[{directory!r}] must be an array")
                continue
            candidates.extend((f"filing.asks[{directory!r}][{index}]", payload, True)
                              for index, payload in enumerate(payloads))
    candidates.extend((f"open_loops[{index}]", item, False)
                      for index, item in enumerate(handoff.get("resume", {}).get("open_loops", []))
                      if item.get("choices") or item.get("applied"))
    for label, item, is_payload in candidates:
        try:
            if not isinstance(item, Mapping):
                raise ValueError("ask must be an object")
            ask = item if is_payload else ask_payload(item, subject)
            if is_payload:
                validate_ask_payload(ask)
        except (ValueError, TypeError, AttributeError) as error:
            problems.append(f"{label}: {error}")
            continue
        # The same item identity can carry different tickets, choices, or proposals.
        # Only identical ask payloads are duplicates across filing and carried items.
        identity = json.dumps(ask, sort_keys=True)
        if identity not in seen:
            asks.append(copy.deepcopy(ask))
            seen.add(identity)
    return sorted(asks, key=lambda ask: ask.get("type") != "lesson")


def file_items(plan: Sequence[Mapping[str, Any]], handoff: Mapping[str, Any],
               outcomes: Sequence[Mapping[str, Any]], ask: Mapping[str, str] | None = None,
               *, execute_writes: bool = True, reread_tickets: bool = False) -> dict[str, Any]:
    """Apply filing judgments and execute record writes with identity lookup.

    The skill supplies one row per remaining loop and unrecorded current item.
    Failed reads and writes keep the source item intact. The same pass runs
    mid-session and at wrap; native steps and asks retain their receipt protocol.
    Sweep uses execute_writes=False to validate a preview without saving anything.
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
    bindings = {step["id"]: step.get("binding") for step in plan if "binding" in step}
    bindings["ask"] = ask
    writes = next(step for step in plan if step["id"] == "record")["record_writes"]
    bindings.update(writes)
    result = copy.deepcopy(dict(handoff))
    result.pop("lesson_outcomes", None)
    result.pop("lesson_asks", None)
    result.pop("knowledge_outcomes", None)
    result.pop("knowledge_asks", None)
    report: dict[str, Any] = {"items": [], "warnings": [], "failures": [], "asks": {}}
    ticket_module = _load_handoff_module()
    session_id = result.get("subject", {}).get("session_id") or ticket_module.ambient_session_id()
    lesson_outcomes = lessons.outcomes(ticket_module, session_id) if execute_writes else []
    knowledge_outcomes = knowledge.outcomes(ticket_module, session_id) if execute_writes else []
    outcome_for = {tuple(outcome["identity"]): outcome for outcome in lesson_outcomes}
    summary_outcomes = copy.deepcopy(result.get("resume", {}).get("close_outcomes", []))
    if execute_writes:
        result.setdefault("resume", {}).update(ticket_module.retain_session_facts(result.get("resume", {}), session_id))
    projects = ticket_module.project_references(result.get("resume", {}))
    for item in loops:
        project = item.get("anchor", {}).get("project")
        if project and project not in projects:
            projects.append(project)
        if execute_writes and session_id:
            ticket = item.get("anchor", {}).get("ticket") or item.get("ticket")
            if ticket:
                ticket_module.record_ticket(session_id, ticket)
    if execute_writes and session_id:
        for project in projects:
            fact = {"kind": "touched_project", "project": project}
            if fact not in ticket_module._ledger_records(ticket_module.ledger_path(session_id)):
                ticket_module.append_ledger(session_id, fact)
        for fact in ticket_module._ledger_records(ticket_module.ledger_path(session_id)) if session_id else []:
            if fact.get("kind") == "touched_project" and fact["project"] not in projects:
                projects.append(fact["project"])
    result.setdefault("resume", {})["touched_projects"] = projects
    tickets_read = False

    def refresh_tickets() -> None:
        nonlocal tickets_read
        if tickets_read or not reread_tickets or not execute_writes:
            return
        tickets_read = True
        binding = writes.get("tickets")
        result["resume"].update(ticket_module.ticket_facts(result["resume"], session_id))
        tickets = result["resume"].get("touched_tickets", [])
        if not binding:
            # Projects may be configured independently: the ledger is the complete
            # known outcome set when no ticket store can be queried.
            report["ticket_read"] = {"status": "unbound", "tickets": tickets}
        elif not tickets:
            report["ticket_read"] = {"status": "not_needed", "tickets": []}
        else:
            try:
                response = record_write.invoke(binding, {"operation": "read", "kind": "tickets", "tickets": tickets})
                states = response.get("tickets")
                if (response.get("status") != "read" or not isinstance(states, list)
                        or sorted(s.get("ticket", "") for s in states) != sorted(tickets)):
                    raise ValueError("ticket read must return exactly the touched tickets")
                result["resume"].update(ticket_module.record_ticket_states(session_id, states, result["resume"]))
                report["ticket_read"] = {"status": "read", "tickets": tickets}
            except (ValueError, TypeError, AttributeError) as error:
                report["ticket_read"] = {"status": "failed", "error": str(error)}
                report["failures"].append(f"touched ticket read failed: {error}")
        result["resume"].update(ticket_module.ticket_facts(result["resume"], session_id))
        if any(outcome not in summary_outcomes for outcome in result["resume"].get("close_outcomes", [])):
            result["resume"]["summary_rewrite_required"] = result["resume"].get("session_summary")

    def project_row(row: Mapping[str, Any]) -> bool:
        item = loops[row["index"]]
        return (filing_binding(row.get("rule"), item, row) == "record"
                and record_write.kind_for(row.get("rule"), item, row, writes) == "projects")

    kept = []
    for row in sorted(outcomes, key=lambda row: (project_row(row), row["index"])):
        item = loops[row["index"]]
        rule, status = row.get("rule"), row.get("status")
        lesson_outcome = outcome_for.get(ticket_module.session_item_identity(item))
        if item.get("applied"):
            if rule != "R3":
                # One mis-ruled row fails alone; the other items still file.
                error = "an applied lesson's ask files under R3"
                report["items"].append({**copy.deepcopy(dict(row)), "item": copy.deepcopy(item), "binding": "ask",
                                        "status": "failed", "error": error})
                report["failures"].append(f"{item.get('context', str(item))}: {error}, not {rule}")
                kept.append(copy.deepcopy(item))
                continue
            if lesson_outcome:
                item = {**item, "ask_text": lessons.ask_text(lesson_outcome), "commit": lesson_outcome.get("commit")}
        if rule not in ("R1", "R3", "R4", "R7", "R2", "R5", "R6"):
            raise ValueError(f"filing: unknown rule {rule!r}")
        if status not in ("filed", "dropped", "pending", "failed", "read failed", "uncertain", *NATIVE_STATUSES):
            raise ValueError(f"filing: unknown status {status!r}")
        binding = filing_binding(rule, item, row)
        if item.get("user_fact") and binding != "ask" and status in ("filed", "dropped"):
            try:
                knowledge.user_answer(item, row)
            except ValueError as error:
                # The fact stays carried with its ask; the other items still file.
                report["items"].append({**copy.deepcopy(dict(row)), "item": copy.deepcopy(item), "binding": binding,
                                        "status": "failed", "error": str(error)})
                report["failures"].append(f"{item.get('context', str(item))}: {error}")
                kept.append(copy.deepcopy(item))
                continue
        if binding == "record":
            binding = record_write.kind_for(rule, item, row, writes)
            bindings.setdefault(binding, None)
        if not item.get("applied") and (binding == "ask" or (binding in NATIVE and "choices" in row)):
            item = {**copy.deepcopy(item), "choices": copy.deepcopy(row.get("choices", item.get("choices")))}
        if status in NATIVE_STATUSES and binding not in NATIVE:
            raise ValueError(f"{status} is only a native-step outcome")
        entry = {**copy.deepcopy(dict(row)), "item": copy.deepcopy(item), "binding": binding}
        if lesson_outcome and lesson_outcome["status"] == "failed":
            entry["apply_failed"] = True
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
                entry["ask"] = ask_payload(item, handoff.get("subject", {}))
                report["asks"].setdefault(entry["ask"]["directory"] or "unknown directory", []).append(entry["ask"])
            if bindings[binding] is None:
                entry["status"] = "unbound"
                report["warnings"].append(f"{label}: missing {binding} binding; kept in handoff")
                kept.append(copy.deepcopy(item))
            elif binding in NATIVE and status != "filed":
                reason = row.get("error") or row.get("reason")
                if status in ("failed", "declined", "pending", "not configured") and not reason:
                    raise ValueError(f"{binding}: {status} requires a reason or error")
                kept.append(copy.deepcopy(item))
            elif binding in record_write.KINDS and execute_writes:
                if rule == "R5" and (not row.get("priority") or not row.get("priority_reason")):
                    raise ValueError(f"{label}: a new ticket requires priority and priority_reason")
                context = None
                project_error = None
                if binding == "projects":
                    refresh_tickets()
                    resume = result["resume"]
                    if reread_tickets and report.get("ticket_read", {}).get("status") not in (
                            "read", "unbound", "not_needed"):
                        project_error = "ticket reread failed; retry before writing project history"
                    elif (not isinstance(resume.get("session_summary"), str)
                          or not resume["session_summary"].strip()):
                        project_error = "write a nonempty session summary before retrying project history"
                    elif ("summary_rewrite_required" in resume
                          and resume["summary_rewrite_required"] == resume["session_summary"]):
                        project_error = "new close outcomes: rewrite the session summary before retrying project history"
                    else:
                        resume.pop("summary_rewrite_required", None)
                    context = {"session_summary": result["resume"].get("session_summary"),
                               "close_outcomes": result["resume"].get("close_outcomes", []),
                               "touched_projects": projects}
                if project_error:
                    row = {**row, "status": "pending", "error": project_error}
                else:
                    row = record_write.execute(bindings[binding], binding, item, row, context=context)
                entry.update(row)
                if binding == "tickets" and "tickets" in row:
                    try:
                        result["resume"].update(ticket_module.record_ticket_states(
                            session_id, row.get("tickets", []), result["resume"]))
                    except (ValueError, TypeError) as error:
                        row.update(status="failed", error=f"ticket facts: {error}")
                        entry.update(row)
                if row["status"] != "filed":
                    report["failures"].append(f"{label}: {binding} write {row['status']}: {row['error']}")
                    kept.append(copy.deepcopy(item))
            elif status != "filed":
                entry["error"] = row.get("error") or "no successful write receipt"
                report["failures"].append(f"{label}: {binding} write failed: {entry['error']}")
                kept.append(copy.deepcopy(item))
            elif not isinstance(row.get("destination"), str) or not row["destination"].strip():
                raise ValueError(f"{label}: a filed item requires its destination or receipt")
            elif rule == "R5" and (not row.get("priority") or not row.get("priority_reason")):
                raise ValueError(f"{label}: a new ticket requires priority and priority_reason")
            if binding == "ask" and item.get("type") in ("knowledge", "lesson"):
                entry["native_step"] = "knowledge" if item["type"] == "knowledge" else "lessons"
                if status == "filed" and ask is not None and not item.get("applied"):
                    # Keep the ask payload and acknowledgement, but not as a capture receipt.
                    entry.update(status="pending", ask_status="filed",
                                 reason="Ask delivered; awaiting native capture receipt")
                    kept.append(copy.deepcopy(item))
        report["items"].append(entry)
    refresh_tickets()
    report["items"].sort(key=lambda row: row["index"])
    result.setdefault("resume", {})["open_loops"] = kept
    result["resume"]["next_action"] = ("Session finished." if not kept else
        "Unfiled items: " + "; ".join(item.get("context", str(item)) for item in kept))
    result.pop("session_items", None)
    if lesson_outcomes:
        report["lessons"] = lessons.report_section(lesson_outcomes)
    if knowledge_outcomes:
        report["knowledge"] = knowledge.report_section(knowledge_outcomes)
    result["filing"] = report
    if execute_writes and session_id:
        # Filed and dropped items are settled; kept items stay retained.
        kept_identities = {ticket_module.session_item_identity(item) for item in kept}
        ticket_module.settle_session_items(
            [item for item in loops if ticket_module.session_item_identity(item) not in kept_identities],
            session_id)
    if execute_writes:
        result["resume"].update(ticket_module.ticket_facts(result["resume"], session_id))
    return result


def filing_check(plan: Sequence[Mapping[str, Any]], data: Mapping[str, Any],
                 ask: Mapping[str, str] | None = None) -> tuple[list[str], list[str]]:
    """Validate filing failures and reject bound items still carried after a wrap."""
    report = data.get("filing", {})
    if not isinstance(report, Mapping):
        return ["filing report must be an object"], []
    failures = list(report.get("failures", []))
    warnings = list(report.get("warnings", []))
    bindings = {step["id"]: step.get("binding") for step in plan if "binding" in step}
    bindings["ask"] = ask
    writes = next(step for step in plan if step["id"] == "record")["record_writes"]
    bindings.update(writes)
    loops = data.get("resume", {}).get("open_loops", [])
    for row in report.get("items", []):
        item = row.get("item")
        if row.get("binding") in record_write.KINDS and row.get("status") == "filed":
            try:
                record_write.receipt(row, record_write.identity(item))
            except (ValueError, AttributeError) as error:
                failures.append(f"record write receipt invalid: {error}")
        if row.get("status") in ("unbound", "pending", "failed", "read failed", "uncertain", *NATIVE_STATUSES) and item not in loops:
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
            "knowledge" if item.get("type") == "knowledge" else
            record_write.kind_for("R2", item, {}, writes))
        if entry and entry.get("status") == "read failed":
            failures.append(f"{label}: read failed: {entry.get('error')}")
        elif entry and entry.get("native_step") in NATIVE and entry.get("ask_status") == "filed":
            warnings.append(f"{label}: ask delivered; native item kept pending in handoff")
        elif binding in NATIVE:
            if entry and entry.get("status") == "filed":
                failures.append(f"{label}: still carried despite native receipt")
            else:
                warnings.append(f"{label}: native {binding} item kept in handoff")
        elif binding is None or bindings.get(binding) is not None:
            failures.append(f"{label}: still carried with bound {binding or 'drop'} destination")
        else:
            warnings.append(f"{label}: missing {binding} binding; kept in handoff")
    return list(dict.fromkeys(failures)), list(dict.fromkeys(warnings))


def saved_state(plan: Sequence[Mapping[str, Any]], data: Mapping[str, Any],
                ask: Mapping[str, str] | None = None) -> tuple[str, list[str], list[str]]:
    """Use receipts and current Git state for the report and wrap verdict alike."""
    failures, warnings = filing_check(plan, data, ask)
    kept: list[str] = []
    not_saved: list[str] = list(failures)
    rows = data.get("filing", {}).get("items", [])
    writes = next(step for step in plan if step["id"] == "record")["record_writes"]
    for row in rows:
        item = row.get("item", {})
        label = item.get("context", str(item))
        status, binding = row.get("status"), row.get("binding")
        reason = row.get("error") or row.get("reason") or "no successful write receipt"
        if row.get("apply_failed"):
            # The lesson is safe in the handoff, so the wrap continues without it.
            kept.append(f"{label}: lesson failed and stays carried: {reason}")
        elif binding == "ask" and (status == "filed" or row.get("ask_status") == "filed"):
            if not isinstance(row.get("destination"), str) or not row["destination"].strip():
                not_saved.append(f"{label}: pending with no ask receipt")
        elif status in ("failed", "uncertain", "read failed", "pending"):
            not_saved.append(f"{label}: {status}: {reason}")
        elif status == "filed":
            if binding not in record_write.KINDS and not row.get("destination"):
                not_saved.append(f"{label}: no successful write receipt")
        elif status == "dropped":
            if not row.get("reason"):
                not_saved.append(f"{label}: dropped without a filing reason")
        elif status == "unbound":
            configured = ask if binding == "ask" else writes.get(binding)
            if configured is not None:
                not_saved.append(f"{label}: pending with no {binding} receipt")
            else:
                kept.append(f"{label}: missing {binding} binding")
        elif binding in NATIVE:
            # Native capture outcomes retain their incomplete-report contract.
            kept.append(f"{label}: native {binding} item kept in handoff ({reason})")
        else:
            not_saved.append(f"{label}: {status or 'pending'}: {reason}")
    for item in data.get("resume", {}).get("open_loops", []):
        if not isinstance(item, Mapping) or any(row.get("item") == item for row in rows):
            continue
        label = item.get("context", str(item))
        binding = ("ask" if item.get("type") == "decision" else
                   "lessons" if item.get("type") == "lesson" else
                   "knowledge" if item.get("type") == "knowledge" else
                   record_write.kind_for("R2", item, {}, writes))
        configured = ask if binding == "ask" else writes.get(binding)
        if binding in NATIVE or configured is None:
            kept.append(f"{label}: " + (f"native {binding} item kept in handoff" if binding in NATIVE
                                       else f"missing {binding} binding"))
        else:
            not_saved.append(f"{label}: pending with no {binding} receipt")

    module = _load_handoff_module()
    session = data.get("subject", {}).get("session_id", "")
    repositories = module.touched_checkouts(session)
    scope = []
    repository_problems: dict[str, list[str]] = {}
    applied = data.get("filing", {}).get("lessons", {}).get("applied", [])
    for checkout in sorted(repositories):
        # Git otherwise walks up to a different checkout if this one lost .git.
        actual = (module._run_git(checkout, "rev-parse", "--show-toplevel")
                  if Path(checkout).is_dir() else None)
        if not actual or str(Path(actual).resolve()) != checkout:
            repository_problems[checkout] = ["cannot check commit and push state: checkout unavailable"]
            continue
        branch = module._run_git(checkout, "symbolic-ref", "--short", "HEAD") or "detached HEAD"
        scope.append(f"{checkout} ({branch})")
        dirty = module._run_git(checkout, "status", "--porcelain=v1", "--untracked-files=all")
        # A lesson commit delivered by pull request, in this wrap or an earlier one, stays on
        # the local branch; its delivered mark says it is not waiting for a push.
        marks = module._run_git(checkout, "for-each-ref", "--format=%(refname)", lessons.DELIVERED_REFS)
        delivered = {ref.rsplit("/", 1)[-1] for ref in (marks or "").splitlines()}
        # Merge commits stay in the query: only the marked commits themselves are left out.
        unpublished = module._run_git(checkout, "rev-list", "HEAD", "--not", "--remotes")
        if unpublished and delivered:
            unpublished = "\n".join(line for line in unpublished.splitlines() if line not in delivered)
        reasons = []
        if dirty is None or unpublished is None:
            reasons.append("cannot check commit and push state")
        else:
            if dirty:
                reasons.append("uncommitted changes")
            if unpublished:
                reasons.append("changes were not pushed")
        if reasons:
            repository_problems[checkout] = reasons
    unpushed: list[str] = []
    persist = next(step for step in plan if step["id"] == "persist").get("binding")
    for checkout, reasons in sorted(repository_problems.items()):
        if not persist and "changes were not pushed" not in reasons:
            reasons.append("changes were not pushed")
        detail = f"{checkout}: " + "; ".join(reasons)
        (not_saved if persist or any("cannot check" in reason for reason in reasons) else unpushed).append(detail)
    for row in applied:
        if row.get("delivery") == lessons.NOT_PUSHED:
            detail = f"{row['change']}: {lessons.NOT_PUSHED}: {row.get('error')}"
            (not_saved if persist else unpushed).append(detail)
    not_saved = list(dict.fromkeys(not_saved))
    warnings = list(dict.fromkeys([*warnings, *kept, *unpushed]))
    parts = []
    if kept:
        parts.append("Kept: " + "; ".join(dict.fromkeys(kept)))
    if unpushed:
        parts.append("Not pushed: " + "; ".join(unpushed))
    if not_saved:
        parts.append("Not saved: " + "; ".join(not_saved))
    return " | ".join(parts) or ("All saved and pushed: " + (", ".join(scope) or "no checkouts listed")), not_saved, warnings


def _load_handoff_module() -> Any:
    spec = importlib.util.spec_from_file_location("handoff", Path(__file__).with_name("handoff.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def unattended_settings() -> dict[str, Any]:
    """The optional ``unattended`` section of the hippocampus configuration.

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
        raise ValueError("hippocampus config: unattended must be an object")
    return value


def _load_session_mode_module() -> Any:
    """The configured state module, or None when no unattended mode is configured."""
    path = unattended_settings().get("state_module")
    if path is None:
        return None
    if not isinstance(path, str) or not path.strip():
        raise ValueError("hippocampus config: unattended.state_module must be a non-empty string")
    module_path = Path(path).expanduser()
    name = "hippocampus_unattended_state"
    if name in sys.modules and getattr(sys.modules[name], "__file__", None) == str(module_path):
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, module_path)
    if spec is None or spec.loader is None:
        raise ValueError(f"hippocampus config: unattended.state_module {module_path} cannot be loaded")
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
        raise ValueError("hippocampus config: unattended.completion_command must be a non-empty string")
    return re.compile(pattern)


def is_completion_command(command: Any) -> bool:
    """True when the command completes an unattended slate, as configured."""
    pattern = completion_pattern()
    return bool(pattern and isinstance(command, str) and pattern.search(command))


def completed_by() -> set[str]:
    """The ``updated_by`` values a completion command leaves in the session's mode record."""
    return set(unattended_settings().get("completed_by") or [])


# Commands that run the checklist or write a handoff; only an interactive session may.
WRAP_COMMAND = re.compile(r"checklist\.py['\"]?\s+(?:plan|settle|apply-lessons|deliver-lessons|apply-knowledge|file|record|wrap-check|report)\b"
                          r"|checkpoint\.sh\b|handoff\.py['\"]?\s+checkpoint\b")


DEFAULT_STATE_DIR = "~/.local/state/hippocampus/checklist"


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
        step = next((s for s in plan if s["id"] == identity), {})
        allowed = (*STATUSES, *NATIVE_STATUSES) if step.get("native") else STATUSES
        if status not in allowed:
            problems.append(f"{identity}: status {status!r} is not one of {', '.join(allowed)}")
        elif status == "pending":
            if not isinstance(result.get("reason"), str) or not result["reason"].strip():
                problems.append(f"{identity}: a pending step names the answer it needs")
            if result.get("writes"):
                problems.append(f"{identity}: a pending step writes nothing, but wrote {result['writes']}")
        if step.get("native") and status in ("failed", "declined", "not configured"):
            if not (result.get("reason") or result.get("error")):
                problems.append(f"{identity}: {status} requires a reason or error")
        if identity in ("record", *SLOTS) and step.get("binding") and status == "failed":
            problems.append(f"{identity}: bound write failed: {result.get('error') or result.get('reason') or 'unknown error'}")
    handoff = next((r for r in results if r.get("id") == "handoff"), None)
    if unattended and (handoff is None or handoff.get("status") != "run"):
        problems.append("handoff: an unattended run still writes the handoff")
    return problems


def session_summary(handoff: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """The agent's wrap account is owned by the final handoff, never a binding."""
    resume = handoff.get("resume", {})
    text = resume.get("session_summary") if isinstance(resume, Mapping) else None
    if not isinstance(text, str) or not text.strip():
        return {"summary": None}, ["session summary: missing; write resume.session_summary in the final handoff"]
    return {"summary": text}, []


def auto_apply_state() -> dict[str, Any] | None:
    """What the auto-apply setting does for this wrap; None with the setting off."""
    if not lessons.enabled(_load_handoff_module().read_config()):
        return None
    rules = lessons.routing_rules()
    reason = lessons.forbidden_reason(rules)
    # The routing file governs lessons only; knowledge capture follows the setting.
    state = {"lessons": "propose", "reason": reason} if reason else {"lessons": "apply"}
    return {**state, "knowledge": "apply"}


def lesson_section(filing: Mapping[str, Any], loops: Sequence[Mapping[str, Any]],
                   problems: list[str]) -> dict[str, Any] | None:
    """The report's lessons: what auto-apply did, or why the routing file stopped it."""
    section = copy.deepcopy(filing.get("lessons")) if isinstance(filing.get("lessons"), Mapping) else None
    try:
        state = auto_apply_state()
    except (OSError, ValueError) as error:
        problems.append(f"auto-apply: {error}")
        return section
    if state and state["lessons"] == "propose":
        section = {**(section or {}), "reason": state["reason"],
                   "carried": [item.get("context") for item in loops if item.get("type") == "lesson"]}
    return section


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    """Collect failures independently, then always end the report with its asks.

    A failed check must not prevent another check or hide readable handoff data.
    Unreadable inputs remain errors; no receipt or successful step is invented.
    """
    problems: list[str] = []

    def read(path: Path | None, label: str, default: Any, *, text: bool = False) -> Any:
        if path is None:
            return default
        try:
            content = path.read_text()
            return content if text else json.loads(content)
        except (OSError, ValueError) as error:
            problems.append(f"{label}: {error}")
            return default

    def object_rows(value: Any, label: str) -> list[Mapping[str, Any]]:
        if not isinstance(value, list):
            problems.append(f"{label} must be an array of objects")
            return []
        rows = []
        for index, row in enumerate(value):
            if isinstance(row, Mapping):
                rows.append(row)
            else:
                problems.append(f"{label}[{index}] must be an object")
        return rows

    if not args.results or not args.handoff:
        problems.append("report requires --results and --handoff")
    handoff = read(args.handoff, "handoff", {})
    handoff_problems, _ = _load_handoff_module().lint_data(handoff)
    problems.extend(f"report handoff invalid: {problem}" for problem in handoff_problems)
    if not isinstance(handoff, Mapping):
        handoff = {}
    results = read(args.results, "results", [])
    summary, summary_problems = session_summary(handoff)
    problems.extend(summary_problems)

    plan = None
    ask = None
    try:
        profiles = load_profiles(args.user_profile, args.repository_profile)
        plan = compose(profiles)
        ask = ask_binding(profiles[0]) if args.user_profile else None
    except (OSError, ValueError, TypeError, AttributeError) as error:
        problems.append(f"profiles: {error}")
    warnings = []
    saved_line = "Not saved: profiles could not be checked"
    if plan is not None:
        problems.extend(check_report(plan, results, args.unattended))
        try:
            saved_line, filing_failures, warnings = saved_state(plan, handoff, ask)
            problems.extend(filing_failures)
        except (ValueError, TypeError, AttributeError, KeyError, OSError) as error:
            saved_line = "Not saved: saved state could not be checked"
            problems.append(f"filing report invalid: {error}")

    # Invalid rows still fail the report, but cannot suppress other rows' asks.
    results = [row for row in results if isinstance(row, Mapping)] if isinstance(results, list) else []
    filing = handoff.get("filing", {})
    if not isinstance(filing, Mapping):
        problems.append("filing report must be an object")
        filing = {}
    filing_rows = object_rows(filing.get("items", []), "filing.items")
    resume = handoff.get("resume", {})
    resume = resume if isinstance(resume, Mapping) else {}
    loops = object_rows(resume.get("open_loops", []), "resume.open_loops")
    subject = handoff.get("subject", {})
    asks = report_asks({"subject": subject if isinstance(subject, Mapping) else {},
                        "filing": {"items": filing_rows, "asks": filing.get("asks", {})},
                        "resume": {"open_loops": loops}}, problems)
    incomplete = [{"id": r["id"], "status": r["status"], "reason": r.get("error") or r.get("reason")}
                  for r in results if isinstance(r.get("id"), str) and r["id"] in NATIVE
                  and r.get("status") in ("failed", "declined", "pending")]
    for row in filing_rows:
        native = row.get("native_step") or row.get("binding")
        if isinstance(native, str) and native in NATIVE and row.get("status") in ("failed", "declined", "pending"):
            if not any(r["id"] == native for r in incomplete):
                incomplete.append({"id": native, "status": row["status"],
                                   "reason": row.get("error") or row.get("reason")})
    try:
        facts = _load_handoff_module().ticket_facts(resume, handoff.get("subject", {}).get("session_id", ""))
        line = _load_handoff_module().outcome_line(facts)
    except (ValueError, TypeError) as error:
        problems.append(f"close outcomes: {error}")
        line = "Close outcomes unavailable."
    lesson_report = lesson_section(filing, loops, problems)
    output = {"outcome_line": line, **summary, "report": "failed" if problems else "incomplete" if incomplete else "ok",
              "pending": [r.get("id") for r in results if r.get("status") == "pending"],
              "filing": handoff.get("filing", {}), "warnings": warnings}
    if lesson_report:
        output["lessons"] = lesson_report
    if isinstance(filing.get("knowledge"), Mapping):
        output["knowledge"] = copy.deepcopy(filing["knowledge"])
    if incomplete:
        output["incomplete"] = incomplete
    if problems:
        output["errors"] = list(dict.fromkeys(problems))
    if problems and "Not saved:" not in saved_line:
        saved_line = (saved_line + " | " if not saved_line.startswith("All saved and pushed:") else "") + "Not saved: " + "; ".join(dict.fromkeys(problems))
    output["saved_line"] = saved_line
    output["asks"] = asks
    return output


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
    if data.get("skeleton") is True:
        failures.append("handoff invalid: wrap requires a real history entry; stop handoff is a skeleton")
    failures.extend(session_summary(data)[1])
    failures.extend(handoff.missing_chain_facts(data))
    _, filing_failures, _ = saved_state(plan, data, ask)
    failures.extend(filing_failures)
    record = next(step for step in plan if step.get("id") == "record")
    if not any(record["record_writes"].values()):
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
    parser.add_argument("operation", choices=("plan", "settle", "apply-lessons", "deliver-lessons", "apply-knowledge",
                                                      "file", "record", "record-over-limit", "over-limit-records",
                                                      "wrap-check", "report", "wrap-cadence", "actor-guard",
                                                      "is-completion-command"))
    parser.add_argument("--user-profile", type=Path)
    parser.add_argument("--repository-profile", type=Path, action="append", default=[])
    parser.add_argument("--handoff", type=Path)
    parser.add_argument("--receipts", type=Path)
    parser.add_argument("--filing", type=Path, help="file: explicit outcome for each remaining item")
    parser.add_argument("--lessons", type=Path, help="apply-lessons: the assessment of each lesson")
    parser.add_argument("--knowledge", type=Path, help="apply-knowledge: what was captured for each knowledge item")
    parser.add_argument("--knowledge-profile", type=Path,
                        help="apply-knowledge: the knowledge profile (default ~/.config/hippocampus/profile.md)")
    parser.add_argument("--measure", type=Path, help="record-over-limit: the slim helper's measure output")
    parser.add_argument("--duplicates", type=Path, help="record-over-limit: the slim helper's duplicates output")
    parser.add_argument("--written-handoff", type=Path, help="wrap-check: the handoff step 5 wrote")
    parser.add_argument("--record-at", help="wrap-check: time of the record's latest write or passing check")
    parser.add_argument("--unattended", action="store_true",
                        help="plan/report/wrap-check: nobody is present to answer a step")
    parser.add_argument("--results", type=Path, help="report: the run's step results, in order")
    parser.add_argument("--session-id", help="plan: the current session, whose ledger gets the start marker")
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
        if args.operation == "over-limit-records":
            # Read-only, so a later slim step in any session can read what wraps recorded.
            print(json.dumps({"records": over_limit.read(_load_handoff_module())}, indent=2))
            return 0
        kind = session_kind({})
        if kind != "interactive":
            raise ValueError(f"a {kind} session never runs the checklist or writes a handoff")
        if args.operation == "report":
            output = build_report(args)
            for problem in output.get("errors", []):
                print(f"checklist: report invalid: {problem}", file=sys.stderr)
            print(json.dumps(output, indent=2))
            return 1 if output["report"] == "failed" else 0
        paths = ([args.user_profile] if args.user_profile else []) + args.repository_profile
        profiles = load_profiles(args.user_profile, args.repository_profile)
        plan = compose(profiles)
        ask = ask_binding(profiles[0]) if args.user_profile else None
        module = _load_handoff_module()
        session_id = args.session_id or module.ambient_session_id()
        recorded = module.resumed_handoff(session_id) if args.operation == "plan" else None
        if recorded and args.handoff and str(args.handoff.resolve()) != recorded["handoff"]:
            raise ValueError(f"plan: recorded resumed handoff {recorded['handoff']} disagrees with {args.handoff}")
        handoff = recorded["data"] if recorded else (json.loads(args.handoff.read_text()) if args.handoff else {})
        if not isinstance(handoff, dict):
            raise ValueError("handoff must be an object")
        if args.operation == "plan" and session_id:
            resume = dict(handoff.get("resume", {}))
            resume.update(module.ticket_facts({}, session_id))
            resume["session_history"] = [row["entry"] for row in module._ledger_records(module.ledger_path(session_id))
                                         if row.get("kind") == "history_entry"]
            resume["resumed_chain"] = module.resumed_chain(session_id)
            projects = list(dict.fromkeys(
                row["project"] for row in module._ledger_records(module.ledger_path(session_id))
                if row.get("kind") == "touched_project"))
            if projects:
                resume["touched_projects"] = projects
            loops = resume.get("open_loops", [])
            if isinstance(loops, list):
                # The lessons and knowledge steps see every unsettled retained item,
                # including a successor's own, without reading the transcript.
                _, settled = module._session_item_rows(session_id)
                resume["open_loops"] = module.merge_session_items(
                    [loop for loop in loops if module.session_item_identity(loop) not in settled], session_id)
            handoff = dict(handoff, resume=resume, subject={
                "session_id": session_id, "working_directory": str(Path.cwd())})
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
                if "binding" in step:
                    step["carried_items"] = slot_inputs(plan, step["id"], handoff)
                    if step.get("native"):
                        step["unattended"] = args.unattended
            output = {"profiles": [str(path) for path in paths], "unattended": args.unattended, "steps": plan,
                      "record_read": record_read_binding(profiles[0]) if args.user_profile else None,
                      "ask": ask, "rerun_all_steps": True, "handoff": handoff}
            if args.unattended:
                output["when_answer_needed"] = UNATTENDED_RULE
            auto_apply = auto_apply_state()
            if auto_apply:
                output["auto_apply"] = auto_apply
        elif args.operation in ("apply-lessons", "deliver-lessons"):
            state = auto_apply_state()
            if not state:
                raise ValueError(f"{args.operation}: the auto-apply setting is off")
            if not args.handoff:
                raise ValueError(f"{args.operation} requires --handoff")
            session_id = (handoff.get("subject") or {}).get("session_id") or session_id
            if state["lessons"] == "propose":
                output = {**handoff, "lesson_outcomes": []}
            elif args.operation == "apply-lessons":
                if not args.lessons:
                    raise ValueError("apply-lessons requires --lessons")
                output = lessons.apply(handoff, json.loads(args.lessons.read_text()), module, session_id)
            else:
                persist = next(step for step in plan if step["id"] == "persist").get("binding")
                rows = lessons.deliver(module, session_id, bool(persist), lessons.routing_rules())
                # An applied lesson may be a carried open loop or one found during this wrap.
                items = [*handoff.get("resume", {}).get("open_loops", []),
                         *(item for item in handoff.get("session_items", []) if item.get("recorded") is not True)]
                output = {**handoff, "lesson_outcomes": rows,
                          "lesson_asks": [ask_payload({**item, "ask_text": lessons.ask_text(row)},
                                                      handoff.get("subject", {}))
                                          for item in items for row in rows if item.get("applied")
                                          and tuple(row["identity"]) == module.session_item_identity(item)]}
        elif args.operation == "apply-knowledge":
            if not auto_apply_state():
                raise ValueError("apply-knowledge: the auto-apply setting is off")
            if not args.handoff or not args.knowledge:
                raise ValueError("apply-knowledge requires --handoff and --knowledge")
            session_id = (handoff.get("subject") or {}).get("session_id") or session_id
            output = knowledge.apply(handoff, json.loads(args.knowledge.read_text()), module, session_id,
                                     knowledge.profile_path(args.knowledge_profile))
            # A fact about the user, carried or found this wrap, goes to the ask binding.
            items = [*output.get("resume", {}).get("open_loops", []),
                     *(item for item in output.get("session_items", []) if item.get("recorded") is not True)]
            output["knowledge_asks"] = [ask_payload(item, output.get("subject", {}))
                                        for item in items if item.get("user_fact")]
        elif args.operation == "record-over-limit":
            state = auto_apply_state()
            if not state:
                raise ValueError("record-over-limit: the auto-apply setting is off")
            # The routing file's `lesson-policy: propose` overrides the setting (glossary,
            # Auto-apply setting), so the blocks stay as they are with the setting off.
            if state["lessons"] == "propose":
                raise ValueError(f"record-over-limit: {state['reason']}")
            if not args.measure or not args.duplicates:
                raise ValueError("record-over-limit requires --measure and --duplicates")
            tool = "codex" if (os.environ.get("HIPPOCAMPUS_HARNESS") == "codex"
                               or os.environ.get("CODEX_THREAD_ID")) else "claude"
            output = over_limit.record(module, json.loads(args.measure.read_text()),
                                       json.loads(args.duplicates.read_text()), session_id or None, tool)
        elif args.operation in ("file", "record"):
            if not args.handoff or not args.filing:
                raise ValueError("file requires --handoff and --filing")
            output = file_items(plan, handoff, json.loads(args.filing.read_text()), ask,
                                reread_tickets=args.operation == "file")
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
            record = next(step for step in plan if step.get("id") == "record")
            output = {"wrap": "ok", "record_check": "passed" if any(record["record_writes"].values()) else "not run: record unbound"}
        else:
            if not args.handoff or not args.receipts:
                raise ValueError("settle requires --handoff and --receipts")
            output = settle(plan, handoff, json.loads(args.receipts.read_text()))
        print(json.dumps(output, indent=2))
        return 1 if args.operation in ("file", "record") and (output.get("filing", {}).get("ticket_read", {}).get("status") == "failed" or any(
            row.get("binding") in record_write.KINDS and row.get("status") in ("failed", "uncertain", "pending")
            for row in output.get("filing", {}).get("items", []))) else 0
    except (OSError, ValueError, TypeError, AttributeError) as error:
        print(f"checklist: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
