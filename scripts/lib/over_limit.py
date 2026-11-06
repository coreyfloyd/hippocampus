#!/usr/bin/env python3
"""Keep over-limit records: files a wrap measured over a size limit or named in a duplicate rule.

With the auto-apply setting on, a wrap hands the slim helper's `measure` and `duplicates`
output here instead of asking the user to run the slim review. Each file in a git repository
with a remote becomes one record, named by repository and path inside it, in a machine-level
store beside the session ledgers, so it outlives the session whether it wraps or is abandoned.
A file outside git, or a repository with no remote, is reported with the attended command and
never recorded. Nothing here slims. Standard library only.
"""
from __future__ import annotations

import contextlib
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any, Iterator, Mapping, Sequence

STORE = "over-limit-records.json"
SCHEMA_VERSION = 1


def store_path(module: Any) -> Path:
    """The store sits in the session ledgers' directory, so one configured value places both."""
    return Path(module.ledger_path("store")).parent / STORE


def _git(cwd: Path, *args: str) -> str | None:
    result = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, timeout=60)
    return result.stdout.strip() if result.returncode == 0 else None


def repository_slug(url: str) -> str | None:
    """`owner/name` from a remote URL, without its host, scheme or `.git`."""
    match = re.search(r"[:/]([^/:]+/[^/:]+?)(?:\.git)?/*$", url.strip())
    return match[1] if match else None


def locate(source: str) -> tuple[dict[str, str] | None, str | None]:
    """The file's repository and path inside it, or why it has none.

    The remote is the current branch's, else `origin`, else the only one. A file that only a
    local checkout path could name gets no record: another machine could not find it.
    """
    path = Path(source).resolve()
    top = _git(path.parent, "rev-parse", "--show-toplevel")
    if not top:
        return None, "not in a git repository"
    remotes = (_git(path.parent, "remote") or "").split()
    branch = _git(path.parent, "symbolic-ref", "--quiet", "--short", "HEAD") or ""
    remote = (_git(path.parent, "config", f"branch.{branch}.remote") if branch else None)
    if remote not in remotes:
        remote = "origin" if "origin" in remotes else remotes[0] if len(remotes) == 1 else None
    url = _git(path.parent, "remote", "get-url", remote) if remote else None
    slug = repository_slug(url) if url else None
    if not slug:
        return None, "its repository has no remote that names it"
    return {"repository": slug, "path": path.relative_to(Path(top).resolve()).as_posix()}, None


@contextlib.contextmanager
def _locked(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.with_name(path.name + ".lock"), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def read(module: Any) -> list[dict[str, Any]]:
    path = store_path(module)
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping) or not isinstance(data.get("records"), list):
        raise ValueError(f"over-limit records: {path} is not a records file")
    return list(data["records"])


def _write(path: Path, records: Sequence[Mapping[str, Any]]) -> None:
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".over-limit.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"schema_version": SCHEMA_VERSION, "records": list(records)}, handle, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise


def _limits_text(limits: Sequence[Mapping[str, Any]]) -> str:
    return "; ".join(f"{row['measured']} {row['unit']}, limit {row['limit']}" for row in limits)


def _span_text(span: Mapping[str, Any]) -> str:
    lines = (f"{span['start_line']}" if span["start_line"] == span["end_line"]
             else f"{span['start_line']}-{span['end_line']}")
    return f"{span['repository']} {span['path']}:{lines}"


def _duplicate_identity(finding: Mapping[str, Any]) -> tuple:
    return (finding["match"], tuple(sorted((s["repository"], s["path"], s["text"]) for s in finding["spans"])))


def record(module: Any, measured: Mapping[str, Any], duplicates: Mapping[str, Any] | None,
           session_id: str | None) -> dict[str, Any]:
    """Merge one wrap's findings into the store; return one line per recorded finding.

    A file several sessions record stays one record: its latest measurement replaces each
    limit it repeats, and every session that recorded it is listed once.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    recorded: list[dict[str, Any]] = []
    reported: list[dict[str, Any]] = []
    sizes: dict[tuple[str, str], dict[str, Any]] = {}
    found: dict[tuple[str, str], list[dict[str, Any]]] = {}
    places: dict[str, tuple[dict[str, str] | None, str | None]] = {}

    def place(source: str) -> tuple[dict[str, str] | None, str | None]:
        if source not in places:
            places[source] = locate(source)
        return places[source]

    for row in measured.get("over_limit", []):
        if row.get("members") is not None:
            reported.append({**row, "reason": "a chain of several files; the user chooses one member"})
            continue
        where, reason = place(row["source"])
        if where is None:
            reported.append({**row, "reason": reason})
            continue
        key = (where["repository"], where["path"])
        sizes[key] = {"size": row["size"], "limits": row["limits"]}
        recorded.append({**where, "kind": "over-limit", "limits": row["limits"],
                         "line": f"Over limit, recorded for a later slim: {where['repository']} "
                                 f"{where['path']} ({_limits_text(row['limits'])})"})
    for row in (duplicates or {}).get("duplicates", []):
        spans = []
        for span in row["spans"]:
            where, reason = place(span["source"])
            if where is None:
                break
            spans.append({**where, "start_line": span["start_line"], "end_line": span["end_line"],
                          "text": span["text"]})
        if len(spans) != len(row["spans"]):
            # A rule's owner needs the user's judgment; a file no record can name keeps both attended.
            reported.append({**row, "reason": f"{span['path']}: {reason}"})
            continue
        finding = {"match": row["match"], "similarity": row["similarity"], "spans": spans}
        for key in dict.fromkeys((span["repository"], span["path"]) for span in spans):
            found.setdefault(key, []).append(finding)
        recorded.append({"kind": "duplicate-rule", "spans": spans,
                         "line": "Duplicate rule, recorded for the slim of the files it names: "
                                 + " and ".join(_span_text(span) for span in spans)})

    if sizes or found:
        path = store_path(module)
        with _locked(path):
            records = {(r["repository"], r["path"]): r for r in read(module)}
            for key in dict.fromkeys([*sizes, *found]):
                entry = records.setdefault(key, {"repository": key[0], "path": key[1], "limits": [],
                                                 "duplicates": [], "sessions": [], "first_recorded": now})
                if key in sizes:
                    entry["size"] = {**entry.get("size", {}), **sizes[key]["size"]}
                    units = {limit["unit"]: limit for limit in entry["limits"]}
                    units.update({limit["unit"]: limit for limit in sizes[key]["limits"]})
                    entry["limits"] = list(units.values())
                for finding in found.get(key, []):
                    entry["duplicates"] = [d for d in entry["duplicates"]
                                           if _duplicate_identity(d) != _duplicate_identity(finding)] + [finding]
                if session_id and session_id not in entry["sessions"]:
                    entry["sessions"].append(session_id)
                entry["last_recorded"] = now
            _write(path, sorted(records.values(), key=lambda r: (r["repository"], r["path"])))
    unresolved = list(dict.fromkeys([*measured.get("unresolved", []), *(duplicates or {}).get("unresolved", [])]))
    return {"recorded": recorded, "reported": reported, "unresolved": unresolved}
