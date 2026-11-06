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
START_MARKER = "checklist-start"
USER_FACT = "user_fact"


def profile_path(explicit: Path | None) -> Path:
    """The knowledge profile: the one named, else the configured default location."""
    if explicit:
        return Path(explicit).expanduser()
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / "hippocampus" / "profile.md"


def read_profile(path: Path) -> tuple[Path, bool]:
    """The knowledge root and whether the wiki is enabled, from a validated profile."""
    spec = importlib.util.spec_from_file_location("validate_profile",
                                                  Path(__file__).parents[1] / "validate_profile.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not path.is_file():
        raise ValueError(f"apply-knowledge: no knowledge profile at {path}; run hippocampus-set-up")
    root, values = module.validate(path)
    return root, values.get("wiki_enabled") != "false"


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
        if capture == USER_FACT:
            if any(not isinstance(row.get(field), str) or not row[field].strip()
                   for field in ("text", "destination", "source")):
                raise ValueError(f"knowledge: row {index}: a fact about the user requires text, destination and source")
            if not _strings(row.get("choices")) or not row["choices"]:
                raise ValueError(f"knowledge: row {index}: a fact about the user requires the user's choices")
            if "default" in row:
                raise ValueError(f"knowledge: row {index}: a fact about the user has no default")
        elif capture in CAPTURES:
            created, updated = row.get("created", []), row.get("updated", [])
            if not _strings(created) or not _strings(updated) or not created + updated:
                raise ValueError(f"knowledge: row {index}: a capture names the files it created or updated")
        else:
            raise ValueError(f"knowledge: row {index}: capture must be one of "
                             f"{', '.join([*CAPTURES, USER_FACT])}")


def started_at(module: Any, session_id: str) -> datetime:
    """When this session's checklist started: a capture's files are written after it."""
    stamps = [row["ts"] for row in module._ledger_records(module.ledger_path(session_id))
              if row.get("kind") == START_MARKER and row.get("ts")]
    if not stamps:
        raise ValueError("apply-knowledge: run the checklist's plan first; it marks when the wrap started")
    return datetime.fromisoformat(stamps[-1].replace("Z", "+00:00"))


def _relative(root: Path, value: str, folders: Sequence[str], since: datetime) -> Path:
    """A file this wrap wrote under one of the capture's folders, or the reason it is not one."""
    candidate = Path(value).expanduser()
    resolved = (candidate if candidate.is_absolute() else root / candidate).resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError:
        raise ValueError(f"{value} is outside the knowledge root; a capture there keeps its approval") from None
    if relative.parts[0] not in folders:
        raise ValueError(f"{relative} is outside {', '.join(f + '/' for f in folders)} in the knowledge root; "
                         "a capture there keeps its approval")
    if not resolved.is_file():
        raise ValueError(f"{value} was not written")
    # Whole seconds: the start marker and a file system's times may round differently.
    if int(resolved.stat().st_mtime) < int(since.timestamp()):
        raise ValueError(f"{value} was not written during this wrap")
    return relative


def _captured(row: Mapping[str, Any], root: Path, wiki: bool, since: datetime) -> dict[str, Any]:
    capture = row["capture"]
    if capture == "wiki" and not wiki:
        raise ValueError("the wiki is disabled in the knowledge profile")
    folders = CAPTURES[capture]
    files = {change: [str(_relative(root, value, folders, since)) for value in row.get(change, [])]
             for change in ("created", "updated")}
    if not any(Path(path).parts[0] == folders[0] for path in [*files["created"], *files["updated"]]):
        raise ValueError(f"a {capture} capture writes under {folders[0]}/ in the knowledge root")
    return files


def apply(handoff: Mapping[str, Any], rows: Sequence[Mapping[str, Any]], module: Any,
          session_id: str, profile: Path) -> dict[str, Any]:
    """Settle each captured item, raise each fact about the user as an ask, keep failures.

    `rows` index the filing pass's list: open loops, then unrecorded session items.
    Knowledge items with no row keep today's approval and stay carried.
    """
    if not session_id:
        raise ValueError("apply-knowledge requires a session id")
    resume = handoff.get("resume", {})
    loops = list(resume.get("open_loops", []))
    current = [item for item in handoff.get("session_items", []) if item.get("recorded") is not True]
    items = [*loops, *current]
    _validate(rows, items)
    root, wiki = read_profile(profile)
    since = started_at(module, session_id)
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
            annotated[row["index"]] = {**copy.deepcopy(dict(item)), "user_fact": True,
                                       "ask_text": ask_text(row), "choices": list(row["choices"])}
        else:
            try:
                outcome.update(_captured(row, root, wiki, since), status="captured")
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
