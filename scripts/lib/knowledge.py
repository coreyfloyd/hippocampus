#!/usr/bin/env python3
"""Record a wrap's knowledge captures under the auto-apply setting, using stdlib only.

The agent assesses each knowledge item and, for a wiki capture or a retained source or
output under the knowledge root, captures it without an approval. This module checks
what was written against the knowledge profile, settles the captured item and keeps its
outcome in the session ledger, where the filing pass and the report read it. A fact
about the user becomes an ordinary ask. Nothing here runs unless the setting is on.
"""
from __future__ import annotations

import copy
from datetime import datetime
import importlib.util
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

OUTCOME = "knowledge_outcome"
# Each capture that applies without an approval, and the knowledge root folders it may write.
# A wiki capture also keeps its provenance under raw/; at least one file is in the first folder.
CAPTURES = {"wiki": ("wiki", "raw"), "source": ("raw",), "output": ("output",)}
# The profile's files a compile is required to write after it: the session cache and the
# operation log. A wiki capture lists them with its articles; no other capture writes them.
COMPILE_FILES = {"wiki": ("hot_file", "operation_log_file")}
START_MARKER = "checklist-start"
USER_FACT = "user_fact"


def profile_path(explicit: Path | None) -> Path:
    """The knowledge profile: the one named, else the configured default location."""
    if explicit:
        return Path(explicit).expanduser()
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / "hippocampus" / "profile.md"


def read_profile(path: Path) -> tuple[Path, bool, dict[str, Path]]:
    """The knowledge root, whether the wiki is enabled and the compile's files, from a validated profile."""
    spec = importlib.util.spec_from_file_location("validate_profile",
                                                  Path(__file__).parents[1] / "validate_profile.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not path.is_file():
        raise ValueError(f"apply-knowledge: no knowledge profile at {path}; run hippocampus-set-up")
    root, values = module.validate(path)
    # A compile file that escapes the root is kept as its reason, so only a row naming a file
    # outside the folders is affected, and the message names the profile key.
    files: dict[str, Path | str] = {}
    for key in sorted({key for keys in COMPILE_FILES.values() for key in keys}):
        if values.get(key):
            try:
                files[key] = (root / values[key]).resolve().relative_to(root)
            except ValueError:
                files[key] = f"the profile's {key} ({values[key]}) is outside the knowledge root"
    return root, values.get("wiki_enabled") != "false", files


def outcomes(module: Any, session_id: str) -> list[dict[str, Any]]:
    """The latest outcome per knowledge item in this session's ledger, in first-recorded order."""
    latest: dict[tuple[str, ...], dict[str, Any]] = {}
    for row in module._ledger_records(module.ledger_path(session_id)) if session_id else []:
        if row.get("kind") == OUTCOME:
            latest[tuple(row["outcome"]["identity"])] = row["outcome"]
    return list(latest.values())


def report_section(rows: Sequence[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    section: dict[str, list[dict[str, Any]]] = {"captured": [], "asked": [], "failed": []}
    for row in rows:
        section[row["status"]].append({key: value for key, value in row.items()
                                       if key not in ("identity", "status") and value is not None})
    return section


def ask_text(row: Mapping[str, Any]) -> str:
    """An ordinary ask: the proposed text, where it would go and where it came from."""
    destination, source = (row[field].strip().rstrip(".") for field in ("destination", "source"))
    return (f"Fact about you to confirm before it is saved: {row['text'].strip()} "
            f"Destination: {destination}. Source: {source}.")


UNANSWERED = ("a fact about the user leaves only through its ask; the row that settles it records "
              "the user's answer, one of the ask's choices")


def user_answer(item: Mapping[str, Any], row: Mapping[str, Any], *, saving: bool) -> str:
    """The user's recorded answer to the ask about this fact, checked against what the row does.

    Only the ask's approving choice (`approve`) lets a row save the fact; any other answer
    settles it without a write, and never the other way round.
    """
    answer = row.get("answer")
    if not isinstance(answer, str) or answer not in item.get("choices", []):
        raise ValueError(UNANSWERED)
    approved = answer == item.get("approve")
    if saving and not approved:
        raise ValueError(f"the user answered {answer!r}, not {item.get('approve')!r}; "
                         "a fact about the user is saved only on its approving choice")
    if approved and not saving:
        raise ValueError(f"the user answered {answer!r}, approving the save; the fact is not dropped")
    return answer


def _strings(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(entry, str) and entry.strip() for entry in value)


def _validate(rows: Any, items: Sequence[Mapping[str, Any]]) -> None:
    if not isinstance(rows, list) or not all(isinstance(row, Mapping) for row in rows):
        raise ValueError("knowledge must be an array of objects")
    indices = [row.get("index") for row in rows]
    if len(set(map(repr, indices))) != len(indices):
        duplicates = sorted({repr(index) for index in indices if indices.count(index) > 1})
        raise ValueError(f"knowledge: one row per item; index {duplicates[0]} appears more than once")
    for row in rows:
        index = row.get("index")
        if type(index) is not int or not 0 <= index < len(items) or items[index].get("type") != "knowledge":
            raise ValueError(f"knowledge: index {index!r} does not name a knowledge item")
        capture = row.get("capture")
        if "answer" in row and (not isinstance(row["answer"], str) or not row["answer"].strip()):
            raise ValueError(f"knowledge: row {index}: answer is the user's choice, as text")
        if capture == USER_FACT:
            if any(not isinstance(row.get(field), str) or not row[field].strip()
                   for field in ("text", "destination", "source")):
                raise ValueError(f"knowledge: row {index}: a fact about the user requires text, destination and source")
            if not _strings(row.get("choices")) or not row["choices"]:
                raise ValueError(f"knowledge: row {index}: a fact about the user requires the user's choices")
            if row.get("approve") not in row["choices"]:
                raise ValueError(f"knowledge: row {index}: a fact about the user names which choice approves the save")
            if "default" in row:
                raise ValueError(f"knowledge: row {index}: a fact about the user has no default")
        elif isinstance(capture, str) and capture in CAPTURES:
            created, updated = row.get("created", []), row.get("updated", [])
            if not _strings(created) or not _strings(updated) or not created + updated:
                raise ValueError(f"knowledge: row {index}: a capture names the files it created or updated")
        else:
            raise ValueError(f"knowledge: row {index}: capture must be one of "
                             f"{', '.join([*CAPTURES, USER_FACT])}")


def started_at(module: Any, session_id: str) -> datetime:
    """When this session's wrap first started: a capture's files are written after it.

    `plan` marks a start each time it runs, and a wrap may run it again; files compiled
    between two runs were still written during this wrap, so the first marker counts.
    """
    stamps = [row["ts"] for row in module._ledger_records(module.ledger_path(session_id))
              if row.get("kind") == START_MARKER and row.get("ts")]
    if not stamps:
        raise ValueError("apply-knowledge: run the checklist's plan first; it marks when the wrap started")
    return datetime.fromisoformat(stamps[0].replace("Z", "+00:00"))


def _relative(root: Path, value: str, folders: Sequence[str], files: Sequence[Path], since: datetime,
              unusable: Sequence[str] = ()) -> Path:
    """A file this wrap wrote under one of the capture's folders, or one of the compile's own
    files, or the reason it is not one; `unusable` names compile files the profile misplaces."""
    candidate = Path(value).expanduser()
    resolved = (candidate if candidate.is_absolute() else root / candidate).resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError:
        raise ValueError(f"{value} is outside the knowledge root; a capture there keeps its approval") from None
    if not relative.parts:
        raise ValueError(f"{value} names the knowledge root itself, not a file the capture wrote")
    if relative.parts[0] not in folders and relative not in files:
        allowed = ", ".join(f + "/" for f in folders)
        if files:
            allowed += " and the profile's " + ", ".join(str(file) for file in files)
        reason = f"{relative} is outside {allowed} in the knowledge root; a capture there keeps its approval"
        if unusable:
            reason += "; " + "; ".join(unusable)
        raise ValueError(reason)
    if not resolved.is_file():
        raise ValueError(f"{value} was not written")
    # Whole seconds: the start marker and a file system's times may round differently.
    if int(resolved.stat().st_mtime) < int(since.timestamp()):
        raise ValueError(f"{value} was not written during this wrap")
    return relative


def _captured(row: Mapping[str, Any], root: Path, wiki: bool, profile_files: Mapping[str, Path | str],
              since: datetime) -> dict[str, Any]:
    capture = row["capture"]
    if capture == "wiki" and not wiki:
        raise ValueError("the wiki is disabled in the knowledge profile")
    folders = CAPTURES[capture]
    compile_files = [profile_files[key] for key in COMPILE_FILES.get(capture, ()) if key in profile_files]
    allowed = [file for file in compile_files if isinstance(file, Path)]
    unusable = [file for file in compile_files if isinstance(file, str)]
    files = {change: [str(_relative(root, value, folders, allowed, since, unusable)) for value in row.get(change, [])]
             for change in ("created", "updated")}
    if not any(Path(path).parts[0] == folders[0] for path in [*files["created"], *files["updated"]]):
        raise ValueError(f"a {capture} capture writes under {folders[0]}/ in the knowledge root")
    return files


def apply(handoff: Mapping[str, Any], rows: Sequence[Mapping[str, Any]], module: Any,
          session_id: str, profile: Path, since: datetime | None = None) -> dict[str, Any]:
    """Settle each captured item, raise each fact about the user as an ask, keep failures.

    `rows` index the filing pass's list: open loops, then unrecorded session items.
    Knowledge items with no row keep today's approval and stay carried. `since` is when the
    captures began: a sweep names its run's start, and a wrap uses its first start marker.
    """
    if not session_id:
        raise ValueError("apply-knowledge requires a session id")
    resume = handoff.get("resume", {})
    loops = list(resume.get("open_loops", []))
    current = [item for item in handoff.get("session_items", []) if item.get("recorded") is not True]
    items = [*loops, *current]
    _validate(rows, items)
    root, wiki, profile_files = read_profile(profile)
    since = since or started_at(module, session_id)
    known = {tuple(outcome["identity"]): outcome for outcome in outcomes(module, session_id)}
    removed: list[Mapping[str, Any]] = []
    annotated: dict[int, dict[str, Any]] = {}
    for row in sorted(rows, key=lambda row: row["index"]):
        item = items[row["index"]]
        identity = module.session_item_identity(item)
        if identity is None:
            raise ValueError(f"knowledge: item {row['index']} has no session item identity")
        if known.get(identity, {}).get("status") == "captured":
            removed.append(item)
            continue
        outcome: dict[str, Any] = {"identity": list(identity), "context": item["context"],
                                   "capture": row["capture"]}
        if row["capture"] == USER_FACT:
            outcome.update(status="asked", text=row["text"], destination=row["destination"], source=row["source"])
            annotated[row["index"]] = {**copy.deepcopy(dict(item)), "user_fact": True, "ask_text": ask_text(row),
                                       "choices": list(row["choices"]), "approve": row["approve"]}
        else:
            try:
                if item.get("user_fact"):
                    # A fact about the user leaves only through its ask: the row carries the answer.
                    outcome["answer"] = user_answer(item, row, saving=True)
                outcome.update(_captured(row, root, wiki, profile_files, since), status="captured")
                removed.append(item)
            except (OSError, ValueError) as error:
                outcome.update(status="failed", error=str(error))
        module.append_ledger(session_id, {"kind": OUTCOME, "outcome": outcome})
    result = copy.deepcopy(dict(handoff))
    if "resume" in result and "open_loops" in result["resume"]:
        result["resume"]["open_loops"] = [annotated.get(index, item) for index, item in enumerate(loops)
                                          if item not in removed]
    if current:
        offset = len(loops)
        kept = [annotated.get(offset + index, item) for index, item in enumerate(current) if item not in removed]
        result["session_items"] = [*(item for item in handoff["session_items"] if item.get("recorded") is True), *kept]
    module.settle_session_items(removed, session_id)
    module.retain_session_items(list(annotated.values()), session_id)
    result["knowledge_outcomes"] = outcomes(module, session_id)
    return result
