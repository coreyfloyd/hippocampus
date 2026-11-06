#!/usr/bin/env python3
"""Keep over-limit records: files a wrap measured over a size limit or named in a duplicate rule.

With the auto-apply setting on, a wrap hands the slim helper's `measure` and `duplicates`
output here instead of asking the user to run the slim review. Each file in a git repository
with a hosted remote becomes one record, named by repository and path inside it, in a
machine-level store beside the session ledgers, so it outlives the session whether it wraps
or is abandoned. A file outside git, in a repository without a hosted remote, or that git
cannot read or does not track is reported with the attended command and never recorded.
Nothing here slims. Standard library only.
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
# The limits a listed-only skill measurement covers; a full measurement covers every unit.
DESCRIPTION_UNITS = ("description characters", "description + when_to_use characters")
HOME_ROOTS = ("Users", "home")


def store_path(module: Any) -> Path:
    """The store sits in the session ledgers' directory, so one configured value places both."""
    return Path(module.ledger_path("store")).parent / STORE


class GitUnreadable(Exception):
    """Git could not answer for a file; the file is reported, never recorded."""


def _git(cwd: Path, *args: str) -> str | None:
    """Git's answer, None when git says no, or GitUnreadable when git cannot run or hangs."""
    try:
        result = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as error:
        raise GitUnreadable(f"git could not be read: {error}") from error
    return result.stdout.strip() if result.returncode == 0 else None


HOSTED = re.compile(r"^(?:https?|ssh|git)://(?:[^@/]+@)?[^/]+/(?P<path>.+)$")
SCP_LIKE = re.compile(r"^(?:[^@/:]+@)?[^/:]+:(?!/)(?P<path>.+)$")


def repository_slug(url: str) -> str | None:
    """The repository's path on its host, from a hosted remote URL; None for any other remote.

    The whole path is kept, not only its last two segments: a host with nested groups
    names different repositories `g1/sub/proj` and `g2/sub/proj`. A path of one segment
    names no owner and gets no slug. Local-path and `file://` remotes name a directory only
    this machine has, so they get none either, and so does a home path in any form: an
    scp-like absolute path, a `~user` segment, or a path under a home root such as `Users`
    or `home`, whichever scheme carries it.
    """
    url = url.strip()
    match = HOSTED.match(url) or (None if "://" in url else SCP_LIKE.match(url))
    if not match:
        return None
    path = re.sub(r"\.git$", "", match["path"].strip("/"))
    segments = path.split("/")
    if len(segments) < 2 or any(not part or part in (".", "..") for part in segments):
        return None
    if segments[0] in HOME_ROOTS or any(part.startswith("~") for part in segments):
        return None
    return path


class Locator:
    """Resolve files to repository and path: git answers once per directory, repository and file."""

    def __init__(self) -> None:
        self.tops: dict[Path, str | None] = {}
        self.slugs: dict[str, tuple[str | None, str | None]] = {}
        self.located: dict[Path, tuple[dict[str, str] | None, str | None]] = {}

    def _slug(self, top: str) -> tuple[str | None, str | None]:
        if top not in self.slugs:
            cwd = Path(top)
            remotes = (_git(cwd, "remote") or "").split()
            branch = _git(cwd, "symbolic-ref", "--quiet", "--short", "HEAD") or ""
            remote = _git(cwd, "config", f"branch.{branch}.remote") if branch else None
            if remote not in remotes:
                remote = "origin" if "origin" in remotes else remotes[0] if len(remotes) == 1 else None
            url = _git(cwd, "remote", "get-url", remote) if remote else None
            slug = repository_slug(url) if url else None
            self.slugs[top] = (slug, None) if slug else (None, "its repository has no hosted remote that names it")
        return self.slugs[top]

    def __call__(self, source: str) -> tuple[dict[str, str] | None, str | None]:
        """The file's repository and path inside it, or why it has none.

        The remote is the current branch's, else `origin`, else the only one. A file that only
        a local path could name gets no record: another machine could not find it. Neither does
        a file git does not track, ignored or untracked, which only this checkout has.
        """
        path = Path(source).resolve()
        if path not in self.located:
            self.located[path] = self._locate(path)
        return self.located[path]

    def _locate(self, path: Path) -> tuple[dict[str, str] | None, str | None]:
        try:
            if path.parent not in self.tops:
                self.tops[path.parent] = _git(path.parent, "rev-parse", "--show-toplevel")
            top = self.tops[path.parent]
            if not top:
                return None, "not in a git repository"
            inside = path.relative_to(Path(top).resolve()).as_posix()
            if _git(Path(top), "ls-files", "--error-unmatch", "--", inside) is None:
                return None, "git does not track it, so another machine could not find it"
            slug, reason = self._slug(top)
        except GitUnreadable as error:
            return None, str(error)
        if not slug:
            return None, reason
        return {"repository": slug, "path": inside}, None


@contextlib.contextmanager
def _locked(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.with_name(path.name + ".lock"), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _is_record(row: Any) -> bool:
    return (isinstance(row, Mapping)
            and all(isinstance(row.get(key), str) and row[key] for key in ("repository", "path"))
            and all(isinstance(row.get(key), list) for key in ("limits", "duplicates", "sessions"))
            and isinstance(row.get("size", {}), Mapping))


def read(module: Any) -> list[dict[str, Any]]:
    """Every record in the store; a damaged store is a clear error, never a crash later."""
    path = store_path(module)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as error:
        raise ValueError(f"over-limit records: {path} is not valid JSON: {error}") from error
    if not isinstance(data, Mapping) or not isinstance(data.get("records"), list):
        raise ValueError(f"over-limit records: {path} is not a records file")
    for number, row in enumerate(data["records"], 1):
        if not _is_record(row):
            raise ValueError(f"over-limit records: {path} row {number} is not a record")
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


def record(module: Any, measured: Mapping[str, Any], duplicates: Mapping[str, Any],
           session_id: str | None) -> dict[str, Any]:
    """Merge one wrap's findings into the store; return one line per recorded finding.

    A file several sessions record stays one record, listing each session once. A measurement
    replaces the findings it covers: a file loaded in full gets its limits and duplicate rules
    from this wrap alone, while a skill only listed, whose measurement covers its description
    alone, keeps its body limits and duplicate rules and replaces only its description limits.
    A file left with no limit and no duplicate rule loses its record. A file this wrap did not
    measure keeps its record unchanged.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    recorded: list[dict[str, Any]] = []
    reported: list[dict[str, Any]] = []
    locate = Locator()
    current: dict[tuple[str, str], dict[str, Any]] = {}

    def fresh(where: Mapping[str, str]) -> dict[str, Any]:
        return current.setdefault((where["repository"], where["path"]),
                                  {"size": {}, "limits": [], "duplicates": [], "full": False})

    for row in measured.get("measured", []):
        where, _ = locate(row["source"])
        if where is not None:
            entry = fresh(where)
            entry["size"] = {**entry["size"], **row["size"]}
            # The slim helper gives a listed skill a description-only size; a body measurement has lines.
            entry["full"] = entry["full"] or "lines" in row["size"]
    for row in measured.get("over_limit", []):
        if row.get("members") is not None:
            reported.append({**row, "reason": "a chain of several files; the user chooses one member"})
            continue
        where, reason = locate(row["source"])
        if where is None:
            reported.append({**row, "reason": reason})
            continue
        entry = fresh(where)
        entry["size"] = {**entry["size"], **row["size"]}
        entry["limits"] = list(row["limits"])
        recorded.append({**where, "kind": "over-limit", "limits": row["limits"],
                         "line": f"Over limit, recorded for a later slim: {where['repository']} "
                                 f"{where['path']} ({_limits_text(row['limits'])})"})
    for row in duplicates.get("duplicates", []):
        spans = []
        for span in row["spans"]:
            where, reason = locate(span["source"])
            if where is None:
                break
            spans.append({**where, "start_line": span["start_line"], "end_line": span["end_line"],
                          "text": span["text"]})
        if len(spans) != len(row["spans"]):
            # A rule's owner needs the user's judgment; a file no record can name keeps both attended.
            reported.append({**row, "reason": f"{span['path']}: {reason}"})
            continue
        finding = {"match": row["match"], "similarity": row["similarity"], "spans": spans}
        for where in {(s["repository"], s["path"]): s for s in spans}.values():
            fresh(where)["duplicates"].append(finding)
        recorded.append({"kind": "duplicate-rule", "spans": spans,
                         "line": "Duplicate rule, recorded for the slim of the files it names: "
                                 + " and ".join(_span_text(span) for span in spans)})

    if current:
        path = store_path(module)
        with _locked(path):
            records = {(r["repository"], r["path"]): r for r in read(module)}
            for key, found in current.items():
                kept = records.get(key, {})
                if kept and not found["full"]:
                    found["size"] = {**kept.get("size", {}), **found["size"]}
                    found["limits"] = [row for row in kept["limits"] if row.get("unit") not in DESCRIPTION_UNITS
                                       ] + found["limits"]
                    found["duplicates"] = kept["duplicates"]
                if not found["limits"] and not found["duplicates"]:
                    records.pop(key, None)
                    continue
                entry = records.setdefault(key, {"repository": key[0], "path": key[1], "sessions": [],
                                                 "first_recorded": now})
                entry.update(size=found["size"], limits=found["limits"], duplicates=found["duplicates"])
                if session_id and session_id not in entry["sessions"]:
                    entry["sessions"].append(session_id)
                entry["last_recorded"] = now
            _write(path, sorted(records.values(), key=lambda r: (r["repository"], r["path"])))
    unresolved = list(dict.fromkeys([*measured.get("unresolved", []), *duplicates.get("unresolved", [])]))
    return {"recorded": recorded, "reported": reported, "unresolved": unresolved}
