#!/usr/bin/env python3
"""Run the unattended slim: pick recorded files, build slim branches, compose the asks.

The driving agent reviews each file and decides its edits; this module chooses what it may
review, applies those edits in temporary clones of each repository's hosted default branch,
pushes one branch per repository and writes the asks. The user's checkouts are only read.
Nothing here merges or schedules. Standard library only.
"""
from __future__ import annotations

import argparse
import contextlib
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Iterator, Mapping, Sequence
import uuid

sys.dont_write_bytecode = True

STORE = "slim-state.json"
SCHEMA_VERSION = 1
FILES_PER_RUN = 3
CHECKOUTS = "slim_checkouts"
PENDING, MERGED, REJECTED = "awaiting decision", "merged", "rejected"
REJECTED_REASON = "over limit, slim rejected"
PENDING_REASON = "slim branch awaiting its decision"
REPORT_LISTS = ("contradictions", "duplicates", "rules", "changes", "deferred", "unverified", "surfaces_verified")
ORDINARY_CHOICES = ["run the attended slim review on it", "leave it as it is"]


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HERE = Path(__file__).resolve().parent
checklist = _load("slim_checklist", HERE / "checklist.py")
harness = _load("slim_harness", HERE.parents[1] / "skills/slim-harness/scripts/harness.py")
lessons, over_limit = checklist.lessons, checklist.over_limit
handoff = checklist._load_handoff_module()


def _require_setting(operation: str) -> None:
    """Refuse unless the auto-apply setting is on and the routing file lets lessons apply."""
    state = checklist.auto_apply_state()
    if not state:
        raise ValueError(f"{operation}: the auto-apply setting is off")
    if state["lessons"] == "propose":
        raise ValueError(f"{operation}: {state['reason']}")


def _state_path() -> Path:
    return over_limit.store_path(handoff).with_name(STORE)


def _blank_state() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "slims": [], "asks": [], "run": None}


@contextlib.contextmanager
def _transaction() -> Iterator[dict[str, Any]]:
    """The state under its lock, written back only when the block succeeds."""
    path = _state_path()
    with over_limit._locked(path):
        try:
            state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else _blank_state()
        except ValueError as error:
            raise ValueError(f"slim: {path} is not valid JSON: {error}") from error
        if not isinstance(state, dict) or not all(key in state for key in _blank_state()):
            raise ValueError(f"slim: {path} is not a slim state file")
        yield state
        handoff.atomic_write(str(path), state)


def _key(row: Mapping[str, Any]) -> tuple[str, str]:
    return row["repository"], row["path"]


def _name(row: Mapping[str, Any]) -> str:
    return f"{row['repository']} {row['path']}"


def _status(slim: Mapping[str, Any]) -> str:
    states = [branch["status"] for branch in slim["branches"]]
    return PENDING if PENDING in states else REJECTED if REJECTED in states else MERGED


def _frozen(state: Mapping[str, Any]) -> dict[tuple[str, str], str]:
    """Every file a slim branch awaiting its decision changed, with that branch."""
    return {(branch["repository"], path): branch["branch"] for slim in state["slims"]
            for branch in slim["branches"] if branch["status"] == PENDING for path in branch["changed"]}


def merge_records(paths: Sequence[Path]) -> list[dict[str, Any]]:
    """Read the given records, from one machine or several, keeping one per file.

    The newest measurement of each tool and unit stands; duplicate rules and sessions join.
    """
    rows: list[Mapping[str, Any]] = []
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, Mapping) or not isinstance(data.get("records"), list):
            raise ValueError(f"slim: {path} is not a records file")
        for number, row in enumerate(data["records"], 1):
            if not over_limit._is_record(row):
                raise ValueError(f"slim: {path} row {number} is not a record")
            rows.append(row)
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for row in sorted(rows, key=lambda row: row.get("last_recorded") or ""):
        entry = merged.setdefault(_key(row), {"repository": row["repository"], "path": row["path"], "size": {},
                                              "limits": {}, "duplicates": {}, "sessions": []})
        entry["size"].update(row.get("size") or {})
        entry["limits"].update({(limit["tool"], limit["unit"]): limit for limit in row["limits"]})
        entry["duplicates"].update({over_limit._finding_key(finding): finding for finding in row["duplicates"]})
        entry["sessions"].extend(session for session in row["sessions"] if session not in entry["sessions"])
    return [{**entry, "limits": list(entry["limits"].values()), "duplicates": list(entry["duplicates"].values())}
            for entry in merged.values()]


def overage(record: Mapping[str, Any]) -> float:
    """How far over its worst limit a file is, as a share of that limit, so units compare."""
    return max([(limit["measured"] - limit["limit"]) / max(limit["limit"], 1) for limit in record["limits"]],
               default=0.0)


def _checkout(config: Mapping[str, Any], repository: str) -> Path | None:
    checkouts = config.get(CHECKOUTS, {})
    if not isinstance(checkouts, Mapping) or not all(isinstance(path, str) for path in checkouts.values()):
        raise ValueError(f"hippocampus config: {CHECKOUTS} must map each repository to a checkout path")
    return Path(checkouts[repository]).expanduser() if repository in checkouts else None


def _clone_address(config: Mapping[str, Any], repository: str) -> tuple[str | None, str | None]:
    """The address to clone a repository from, read from its checkout, or why there is none."""
    checkout = _checkout(config, repository)
    if checkout is None:
        return None, f"{CHECKOUTS} in the hippocampus configuration does not name {repository}"
    if not checkout.is_dir():
        return None, f"its checkout {checkout} does not exist"
    remotes = lessons._text(lessons._git(checkout, "remote")).split()
    remote = "origin" if "origin" in remotes else remotes[0] if len(remotes) == 1 else None
    address = lessons._text(lessons._git(checkout, "config", "--get", f"remote.{remote}.url")) if remote else ""
    if not address or over_limit.repository_slug(address) != repository:
        return None, f"the remote of {checkout} does not name {repository}"
    return address, None


def _clone(address: str, directory: Path) -> None:
    """Clone only the hosted default branch: the remote's own HEAD, not a checkout's idea of it."""
    result = subprocess.run(["git", "clone", "--quiet", "--single-branch", "--no-tags", address, str(directory)],
                            capture_output=True, text=True, timeout=600,
                            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    if result.returncode:
        raise lessons.LessonError(f"git clone failed: {result.stderr.strip()}")


def measured(text: str, unit: str) -> int | None:
    """One limit's unit measured on a file's text, as the slim helper measures it."""
    if unit in ("lines", "bytes"):
        return harness.size(text)[unit]
    fields, body = harness.frontmatter(text)
    description, when = fields.get("description", ""), fields.get("when_to_use", "")
    return {"body lines": harness.size(body)["lines"], "body bytes": harness.size(body)["bytes"],
            "description characters": len(description),
            "description + when_to_use characters": len(description) + len(when)}.get(unit)


def _measure(text: str, record: Mapping[str, Any]) -> dict[str, Any]:
    """A file's size and each limit's value, in the shape a record holds them."""
    return {"size": harness.size(text),
            "limits": [{**limit, "measured": value} for limit in record["limits"]
                       for value in [measured(text, limit["unit"])] if value is not None]}


def _larger(record: Mapping[str, Any], baseline: Mapping[str, Any]) -> bool:
    """Whether a session measured the file larger than the size held at rejection."""
    limits = {(limit["tool"], limit["unit"]): limit["measured"] for limit in baseline["limits"]}
    if any(limit["measured"] > limits.get((limit["tool"], limit["unit"]), limit["measured"])
           for limit in record["limits"]):
        return True
    return any(isinstance(value, int) and value > baseline["size"].get(unit, value)
               for unit, value in record["size"].items())


def _reject(slim: dict[str, Any], branch: dict[str, Any], config: Mapping[str, Any]) -> None:
    """Mark a branch rejected, keeping the file's size at this moment for the later comparison."""
    branch["status"] = REJECTED
    address, _ = _clone_address(config, slim["repository"])
    if address is None:
        return
    with tempfile.TemporaryDirectory(prefix="hippocampus-slim-") as directory:
        with contextlib.suppress(lessons.LessonError, OSError, subprocess.SubprocessError, ValueError):
            _clone(address, Path(directory) / "clone")
            text = (Path(directory) / "clone" / slim["path"]).read_text(encoding="utf-8")
            slim["measured"] = _measure(text, slim["measured"])


def _reconcile(state: dict[str, Any], config: Mapping[str, Any]) -> list[str]:
    """Settle each pending branch that is gone from its remote; return what could not be read.

    A branch still on the remote stays pending until `decide` says otherwise, because git cannot
    tell that its pull request closed. A branch that is gone merged if its files moved from the
    base they were cut from, and was rejected if they did not.
    """
    warnings: list[str] = []
    for slim in state["slims"]:
        for branch in slim["branches"]:
            if branch["status"] != PENDING:
                continue
            address, reason = _clone_address(config, branch["repository"])
            if address is None:
                warnings.append(f"{branch['branch']}: {reason}")
                continue
            listed = lessons._git(".", "ls-remote", "--heads", address, f"refs/heads/{branch['branch']}")
            if listed.returncode:
                warnings.append(f"{branch['branch']}: {lessons._error(listed)}")
            elif not lessons._text(listed):
                with tempfile.TemporaryDirectory(prefix="hippocampus-slim-") as directory:
                    clone = Path(directory) / "clone"
                    try:
                        _clone(address, clone)
                    except (lessons.LessonError, OSError, subprocess.SubprocessError) as error:
                        warnings.append(f"{branch['branch']}: {error}")
                        continue
                    moved = any(_blob(clone, path) != blob for path, blob in branch["base_blobs"].items())
                if moved:
                    branch["status"] = MERGED
                else:
                    _reject(slim, branch, config)
    return warnings


def _blob(clone: Path, path: str) -> str | None:
    result = lessons._git(clone, "rev-parse", "--verify", "-q", f"HEAD:{path}")
    return lessons._text(result) if result.returncode == 0 else None


def _remove_workspaces(run: Mapping[str, Any] | None) -> None:
    current = (run or {}).get("current")
    if current:
        shutil.rmtree(current["base"], ignore_errors=True)


def plan(paths: Sequence[Path]) -> dict[str, Any]:
    """Start a run: sort the given records, largest overage first, and set aside what must wait."""
    _require_setting("slim plan")
    records = merge_records(paths)
    config = handoff.read_config()
    with _transaction() as state:
        _remove_workspaces(state["run"])
        warnings = _reconcile(state, config)
        state["slims"] = [slim for slim in state["slims"] if _status(slim) != MERGED]
        frozen = _frozen(state)
        latest = {_key(slim): slim for slim in state["slims"]}
        run: dict[str, Any] = {"id": uuid.uuid4().hex[:12], "started": _now(), "queue": [], "analyzed": 0,
                               "current": None, "results": [], "skipped": [], "deferred": [], "unreachable": [],
                               "failed": [], "closed": None}
        for record in sorted(records, key=lambda row: (-overage(row), row["repository"], row["path"])):
            slim = latest.get(_key(record))
            if slim and _status(slim) == PENDING:
                run["skipped"].append(_row(record, PENDING_REASON))
            elif _key(record) in frozen:
                run["deferred"].append(_row(record, f"already changed by {frozen[_key(record)]}"))
            elif slim and _status(slim) == REJECTED and not _larger(record, slim["measured"]):
                run["skipped"].append(_row(record, REJECTED_REASON))
            else:
                _, reason = _clone_address(config, record["repository"])
                if reason:
                    run["unreachable"].append(_row(record, reason))
                else:
                    run["queue"].append(record)
        state["run"] = run
        return {"run_id": run["id"], "queued": len(run["queue"]), "files_per_run": FILES_PER_RUN,
                "skipped": run["skipped"], "deferred": run["deferred"], "unreachable": run["unreachable"],
                "warnings": warnings, "undelivered_asks": state["asks"]}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row(record: Mapping[str, Any], reason: str) -> dict[str, Any]:
    limits = over_limit._limits_text(record.get("limits", []))
    return {"repository": record["repository"], "path": record["path"], "reason": reason,
            "line": f"{reason}: {_name(record)}" + (f" ({limits})" if limits else "")}


def _run(state: Mapping[str, Any], run_id: str) -> dict[str, Any]:
    run = state["run"]
    if not run or run["id"] != run_id:
        raise ValueError(f"slim: run {run_id} is not the current run")
    return run


def _workspace(current: dict[str, Any], repository: str, config: Mapping[str, Any]) -> Path:
    """A temporary clone of a repository's default branch, one per slim and repository."""
    if repository not in current["workspaces"]:
        address, reason = _clone_address(config, repository)
        if address is None:
            raise lessons.LessonError(reason)
        directory = Path(current["base"]) / hashlib.sha256(repository.encode()).hexdigest()[:12]
        _clone(address, directory)
        current["workspaces"][repository] = str(directory)
    return Path(current["workspaces"][repository])


def _inside(workspace: Path, path: str) -> Path:
    target = (workspace / path).resolve()
    if Path(path).is_absolute() or not target.is_relative_to(workspace.resolve()):
        raise lessons.LessonError(f"{path} is not a path inside its repository")
    return target


def _branch(run_id: str, record: Mapping[str, Any]) -> str:
    name = re.sub(r"-+", "-", re.sub(r"[^A-Za-z0-9_-]", "-", record["path"])).strip("-")[:40]
    digest = hashlib.sha256(f"{_name(record)}".encode()).hexdigest()[:8]
    return f"slim/{run_id[:8]}-{name}-{digest}"


def begin(run_id: str) -> dict[str, Any]:
    """Hand the agent the next file, or finish the run. One slim is open at a time."""
    _require_setting("slim begin")
    config = handoff.read_config()
    with _transaction() as state:
        run = _run(state, run_id)
        if run["closed"]:
            return run["closed"]
        if not run["current"]:
            _next_slim(state, run, config)
        if not run["current"]:
            return _close(state, run)
        return _briefing(state, run)


def _next_slim(state: dict[str, Any], run: dict[str, Any], config: Mapping[str, Any]) -> None:
    """Open the next file a slim can change; a file it cannot does not use up the run's three."""
    while run["queue"] and run["analyzed"] < FILES_PER_RUN:
        record = run["queue"].pop(0)
        frozen = _frozen(state)
        if _key(record) in frozen:
            run["deferred"].append({**_row(record, f"already changed by {frozen[_key(record)]}"),
                                    "changed_by": frozen[_key(record)]})
            continue
        base = tempfile.mkdtemp(prefix="hippocampus-slim-")
        current = {"record": record, "base": base, "workspaces": {}, "branch": _branch(run["id"], record),
                   "id": uuid.uuid4().hex[:12]}
        try:
            workspace = _workspace(current, record["repository"], config)
            target = _inside(workspace, record["path"])
            if not target.is_file():
                run["skipped"].append(_row(record, "not on the repository's default branch"))
            else:
                text = target.read_text(encoding="utf-8")
                over = [limit for limit in _measure(text, record)["limits"] if limit["measured"] > limit["limit"]]
                if over or record["duplicates"]:
                    for finding in record["duplicates"]:
                        for span in finding["spans"]:
                            _workspace(current, span["repository"], config)
                    run["analyzed"] += 1
                    run["current"] = current
                    return
                run["skipped"].append(_row(record, "already under its limits on the default branch"))
        except (lessons.LessonError, OSError, UnicodeError, ValueError, subprocess.SubprocessError) as error:
            run["failed"].append(_row(record, str(error)))
        shutil.rmtree(base, ignore_errors=True)


def _briefing(state: Mapping[str, Any], run: Mapping[str, Any]) -> dict[str, Any]:
    current = run["current"]
    record = current["record"]
    try:
        surfaces = _surfaces(record["repository"], record["path"], handoff.read_config())["surfaces"]
    except lessons._compose_rules().ComposeError:
        surfaces = []  # `finish` reports the malformed routing file as a surface it cannot verify.
    return {"done": False, "run_id": run["id"], "slim_id": current["id"], "repository": record["repository"],
            "path": record["path"], "file": str(Path(current["workspaces"][record["repository"]]) / record["path"]),
            "workspaces": current["workspaces"], "limits": record["limits"], "duplicates": record["duplicates"],
            "frozen": [{"repository": repository, "path": path, "changed_by": branch}
                       for (repository, path), branch in _frozen(state).items()],
            "surfaces": surfaces}


def workspace(run_id: str, repository: str) -> dict[str, Any]:
    """A clone of another repository's default branch, for a comparison file or an edit."""
    config = handoff.read_config()
    with _transaction() as state:
        run = _run(state, run_id)
        if not run["current"]:
            raise ValueError("slim workspace: no slim is open")
        return {"repository": repository, "workspace": str(_workspace(run["current"], repository, config))}


def _surfaces(repository: str, path: str, config: Mapping[str, Any]) -> dict[str, Any]:
    """The surfaces the routing file produces from a file, by its path in the user's checkout."""
    compose = lessons._compose_rules()
    checkout = _checkout(config, repository)
    source = (checkout / path).resolve() if checkout else None
    if source is None:
        return {"sources": [], "surfaces": []}
    return compose.surfaces_for(source, compose.routing_path())


def _surface_gaps(changed: Sequence[tuple[str, str]], result: Mapping[str, Any],
                  config: Mapping[str, Any]) -> tuple[list[str], list[dict[str, str]]]:
    """What stops a generated surface being verified, and the surfaces the slim changes."""
    gaps = [f"{row['surface']}: {row['reason']}" for row in result["unverified"]]
    surfaces: list[dict[str, str]] = []
    for repository, path in changed:
        try:
            mapped = _surfaces(repository, path, config)
        except lessons._compose_rules().ComposeError as error:
            gaps.append(f"{path}: {error}")
            continue
        if mapped["sources"] and all(source != str((_checkout(config, repository) / path).resolve())
                                     for source in mapped["sources"]):
            gaps.append(f"{path} is a generated surface of {', '.join(mapped['sources'])}")
        for surface in mapped["surfaces"]:
            if surface not in surfaces:
                surfaces.append(surface)
            if surface["path"] not in result["surfaces_verified"] and not any(
                    gap.startswith(surface["path"] + ":") for gap in gaps):
                gaps.append(f"{surface['path']}: no preview of it was verified")
    return gaps, surfaces


def _check_result(result: Any, record: Mapping[str, Any]) -> dict[str, Any]:
    """Refuse a malformed result before anything changes; the agent can correct and resend it."""
    if not isinstance(result, Mapping):
        raise ValueError("slim finish: the result must be an object")
    checked = {key: result.get(key, []) for key in REPORT_LISTS}
    for key, value in checked.items():
        if not isinstance(value, list):
            raise ValueError(f"slim finish: {key} must be a list")
    required = {"contradictions": ("rules", "winner"), "duplicates": ("rule", "owner"),
                "rules": ("path", "action", "text"), "deferred": ("repository", "path", "reason"),
                "unverified": ("surface", "reason"), "changes": ("path",)}
    for key, fields in required.items():
        for number, row in enumerate(checked[key], 1):
            if not isinstance(row, Mapping) or not all(isinstance(row.get(field), str) and row[field]
                                                       for field in fields):
                raise ValueError(f"slim finish: {key} row {number} requires {', '.join(fields)}")
    changes = []
    for number, row in enumerate(checked["changes"], 1):
        edits = row.get("edits")
        if not isinstance(edits, list) or not edits or not all(
                isinstance(edit, Mapping) and isinstance(edit.get("new"), str)
                and ("old" not in edit or isinstance(edit["old"], str)) and (edit.get("old") or edit["new"])
                for edit in edits):
            raise ValueError(f"slim finish: changes row {number} requires edits, each with old or new text")
        changes.append({**row, "repository": row.get("repository") or record["repository"]})
    left = result.get("left")
    if left is not None and not isinstance(left, str):
        raise ValueError("slim finish: left must be text")
    return {**checked, "changes": changes, "left": left}


def _partition(changes: Sequence[Mapping[str, Any]], frozen: Mapping[tuple[str, str], str]) -> tuple[list, list]:
    """Split changes into those to make and those a frozen file defers, with their whole group."""
    blocked = {row["group"] for row in changes if _key(row) in frozen and row.get("group")}
    kept, deferred = [], []
    for row in changes:
        if _key(row) in frozen:
            deferred.append({"repository": row["repository"], "path": row["path"],
                             "reason": f"already changed by {frozen[_key(row)]}"})
        elif row.get("group") in blocked:
            deferred.append({"repository": row["repository"], "path": row["path"],
                             "reason": "it depends on a change to a deferred file"})
        else:
            kept.append(row)
    return kept, deferred


def _edited(current: dict[str, Any], changes: Sequence[Mapping[str, Any]],
            config: Mapping[str, Any]) -> dict[tuple[str, str], tuple[bytes | None, bytes]]:
    """Each changed file's content before and after, computed before anything is written."""
    contents: dict[tuple[str, str], tuple[bytes | None, bytes]] = {}
    for row in changes:
        target = _inside(_workspace(current, row["repository"], config), row["path"])
        original, content = contents.get(_key(row), (None, None))
        if content is None:
            original = target.read_bytes() if target.is_file() else None
            content = original or b""
        if content.startswith(lessons.GENERATED_MARK):
            raise lessons.LessonError(f"{row['path']} is a generated copy; name its source")
        contents[_key(row)] = (original, lessons._edited(content, row["edits"], "default branch's file"))
    return contents


def _sizes(record: Mapping[str, Any], before: str, after: str) -> list[dict[str, Any]]:
    return [{"tool": limit["tool"], "unit": limit["unit"], "limit": limit["limit"],
             "before": measured(before, limit["unit"]), "after": measured(after, limit["unit"])}
            for limit in record["limits"]]


def _commit(workspace_path: Path, branch: str, paths: Sequence[str], title: str) -> tuple[str, str]:
    base = lessons._must(workspace_path, "symbolic-ref", "--short", "HEAD")
    lessons._must(workspace_path, "checkout", "-q", "-b", branch)
    lessons._must(workspace_path, "add", "--", *paths)
    lessons._must(workspace_path, "commit", "-q", "-m", title)
    return base, lessons._must(workspace_path, "rev-parse", "HEAD")


def finish(run_id: str, result: Any) -> dict[str, Any]:
    """Close the open slim: apply its edits on one branch per repository and push them."""
    _require_setting("slim finish")
    config = handoff.read_config()
    with _transaction() as state:
        run = _run(state, run_id)
        current = run["current"]
        if not current:
            raise ValueError("slim finish: no slim is open")
        record = current["record"]
        report = _check_result(result, record)
        kept, deferred = _partition(report["changes"], _frozen(state))
        report["deferred"] = [*report["deferred"], *deferred]
        outcome = {"id": current["id"], "repository": record["repository"], "path": record["path"],
                   "report": {key: value for key, value in report.items() if key != "changes"}}
        gaps, surfaces = _surface_gaps(list(dict.fromkeys(_key(row) for row in kept)), report, config)
        try:
            if gaps:
                outcome.update(status="unverified", gaps=gaps)
            else:
                outcome.update(_build(state, run, current, kept, report, surfaces, config))
        except (lessons.LessonError, OSError, UnicodeError, subprocess.SubprocessError) as error:
            outcome.update(status="failed", error=str(error))
        run["results"].append(outcome)
        run["current"] = None
        shutil.rmtree(current["base"], ignore_errors=True)
        return {key: outcome.get(key) for key in ("id", "repository", "path", "status", "sizes", "branches", "error", "gaps")}


def _build(state: dict[str, Any], run: Mapping[str, Any], current: dict[str, Any], kept: Sequence[Mapping[str, Any]],
           report: Mapping[str, Any], surfaces: Sequence[Mapping[str, str]], config: Mapping[str, Any]) -> dict[str, Any]:
    record = current["record"]
    contents = _edited(current, kept, config)
    target = _inside(_workspace(current, record["repository"], config), record["path"])
    before = target.read_text(encoding="utf-8")
    after = contents[_key(record)][1].decode("utf-8") if _key(record) in contents else before
    sizes = _sizes(record, before, after)
    over = [row for row in sizes if row["after"] is not None and row["after"] > row["limit"]]
    if over and not report["left"]:
        raise ValueError(f"slim finish: {_name(record)} is still over a limit, so the result requires left: "
                         "what is left and why")
    if not contents:
        return {"status": "unchanged", "sizes": sizes, "branches": []}
    branches, failures = [], []
    title = f"slim: {record['path']}"
    for repository in dict.fromkeys(repository for repository, _ in contents):
        changed = [path for owner, path in contents if owner == repository]
        try:
            # A branch already pushed for another repository stands, so this one fails alone.
            workspace_path = _workspace(current, repository, config)
            blobs = {path: _blob(workspace_path, path) for path in changed}
            for path in changed:
                file = _inside(workspace_path, path)
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(contents[(repository, path)][1])
            base, commit = _commit(workspace_path, current["branch"], changed, title)
            lessons._must(workspace_path, "push", "origin", f"HEAD:refs/heads/{current['branch']}")
        except (lessons.LessonError, OSError, subprocess.SubprocessError) as error:
            failures.append(f"{repository} {current['branch']}: {error}")
            continue
        branches.append({"repository": repository, "branch": current["branch"], "base": base, "commit": commit,
                         "changed": changed, "base_blobs": blobs, "status": PENDING})
    if not branches:
        raise lessons.LessonError("; ".join(failures))
    # This slim replaces the file's earlier rejection, so a later merge cannot uncover it.
    state["slims"] = [slim for slim in state["slims"] if _key(slim) != _key(record) or _status(slim) == PENDING]
    state["slims"].append({"id": current["id"], "run": run["id"], "repository": record["repository"],
                           "path": record["path"], "measured": {"size": record["size"], "limits": record["limits"]},
                           "branches": branches})
    return {"status": "slimmed", "sizes": sizes, "branches": branches, "failures": failures,
            "surfaces": list(surfaces)}


def _section(title: str, lines: Sequence[str]) -> str:
    return "\n".join([title, *(lines or ["- None."])])


def _with_reason(text: str, row: Mapping[str, Any]) -> str:
    return f"{text} Why: {row['reason']}" if row.get("reason") else text


def _ask_text(outcome: Mapping[str, Any]) -> str:
    """The report a slim's ask carries, in its fixed order: choices made, then results, then undo."""
    report = outcome["report"]
    name = _name(outcome)
    branches = outcome.get("branches", [])
    size_lines = [f"- {row['tool']} {row['unit']}: {row['before']} before, {row['after']} after, limit {row['limit']}"
                  for row in outcome["sizes"]]
    parts = [
        (f"Slimmed {name} on a branch; nothing is merged." if branches
         else f"Reviewed {name} and changed nothing, so there is no branch."),
        _section("Contradictions and the winner chosen:", [
            _with_reason(f"- {row['rules']} Winner: {row['winner']}", row) for row in report["contradictions"]]),
        _section("Cross-file duplicates and the owner chosen:", [
            _with_reason(f"- {row['rule']} Owner: {row['owner']}", row) for row in report["duplicates"]]),
        _section("Rules removed or rewritten:", [
            _with_reason(f"- {row['action']} in {row['path']}: {row['text']}", row) for row in report["rules"]]),
        _section("Sizes against each limit:", size_lines),
        _section("Branches:", [f"- {row['repository']} {row['branch']} from {row['base']}, commit {row['commit']}, "
                               f"changing {', '.join(row['changed'])}" for row in branches]),
    ]
    if outcome.get("failures"):
        parts.append(_section("Branches not pushed:", [f"- {row}" for row in outcome["failures"]]))
    if report["deferred"]:
        parts.append(_section("Deferred to a later run, left as they are:", [
            f"- {_name(row)}: {row['reason']}" for row in report["deferred"]]))
    if report["left"]:
        parts.append(f"Still over a limit: {report['left']}")
    if outcome.get("surfaces"):
        parts.append(_section("Generated surfaces to regenerate after a merge:", [
            f"- {row['path']}: {row['regeneration command']}" for row in outcome["surfaces"]]))
    if branches:
        parts.append("To undo or stop it: close the pull request without merging, or delete the branch. "
                     "The package never merges it. Turning the auto-apply setting off stops later slims.")
    return "\n\n".join(parts)


def _ask(run: Mapping[str, Any], outcome: Mapping[str, Any], text: str, choices: Sequence[str]) -> dict[str, Any]:
    return {"id": hashlib.sha256(outcome["id"].encode()).hexdigest()[:12], "text": text, "choices": list(choices),
            "applied": not choices, "repository": outcome["repository"], "path": outcome["path"],
            "identity": {"session_id": f"slim-{outcome['id']}", "produced_at": run["started"], "text": text}}


def _close(state: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    """Compose the run's asks last, so a file an earlier slim froze reaches that slim's ask."""
    asks = []
    for outcome in run["results"]:
        branches = {row["branch"] for row in outcome.get("branches", [])}
        outcome["report"]["deferred"] = [*outcome["report"]["deferred"], *(
            row for row in run["deferred"] if row.get("changed_by") in branches)]
        if outcome["status"] == "slimmed" or (outcome["status"] == "unchanged" and outcome["report"]["left"]):
            asks.append(_ask(run, outcome, _ask_text(outcome), []))
        elif outcome["status"] == "unverified":
            asks.append(_ask(run, outcome, (
                f"The slim of {_name(outcome)} produced no branch: a generated surface it would change could not "
                f"be verified. {'; '.join(outcome['gaps'])}. Every file is left as it is."), ORDINARY_CHOICES))
    for ask in asks:
        checklist.validate_ask_payload(ask)
    state["asks"].extend(asks)
    run["closed"] = {"done": True, "run_id": run["id"], "analyzed": run["analyzed"], "asks": asks,
                     "results": [{key: row.get(key) for key in ("repository", "path", "status", "error")}
                                 for row in run["results"]],
                     "waiting": [_row(record, "waiting for a later run") for record in run["queue"]],
                     "skipped": run["skipped"], "deferred": run["deferred"], "unreachable": run["unreachable"],
                     "failed": run["failed"]}
    return run["closed"]


def decide(repository: str, branch_name: str, decision: str) -> dict[str, Any]:
    """Record a slim branch's decision. Closing its pull request without merging is `rejected`."""
    config = handoff.read_config()
    with _transaction() as state:
        for slim in state["slims"]:
            for branch in slim["branches"]:
                if branch["repository"] == repository and branch["branch"] == branch_name:
                    if decision == REJECTED:
                        _reject(slim, branch, config)
                    else:
                        branch["status"] = MERGED
                    return {"repository": slim["repository"], "path": slim["path"], "branch": branch_name,
                            "status": _status(slim)}
    raise ValueError(f"slim decide: no slim branch {branch_name} in {repository}")


def ask_delivered(ask_id: str, receipt: str) -> dict[str, Any]:
    """Settle an ask the binding took, so `plan` stops listing it as undelivered."""
    with _transaction() as state:
        if any(ask["id"] == ask_id for ask in state["asks"]):
            state["asks"] = [ask for ask in state["asks"] if ask["id"] != ask_id]
            return {"id": ask_id, "receipt": receipt}
    raise ValueError(f"slim ask-delivered: no undelivered ask {ask_id}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    command = commands.add_parser("plan")
    command.add_argument("--records", type=Path, action="append", required=True)
    for name in ("begin", "workspace", "finish"):
        command = commands.add_parser(name)
        command.add_argument("--run", required=True)
        if name == "workspace":
            command.add_argument("--repository", required=True)
        if name == "finish":
            command.add_argument("--result", type=Path, required=True)
    command = commands.add_parser("decide")
    command.add_argument("--repository", required=True)
    command.add_argument("--branch", required=True)
    command.add_argument("--decision", choices=(MERGED, REJECTED), required=True)
    command = commands.add_parser("ask-delivered")
    command.add_argument("--ask", required=True)
    command.add_argument("--receipt", required=True)
    args = parser.parse_args()
    try:
        if args.operation == "plan":
            output = plan(args.records)
        elif args.operation == "begin":
            output = begin(args.run)
        elif args.operation == "workspace":
            output = workspace(args.run, args.repository)
        elif args.operation == "finish":
            output = finish(args.run, json.loads(args.result.read_text(encoding="utf-8")))
        elif args.operation == "decide":
            output = decide(args.repository, args.branch, args.decision)
        else:
            output = ask_delivered(args.ask, args.receipt)
    except (OSError, ValueError, lessons.LessonError, subprocess.SubprocessError,
            lessons._compose_rules().ComposeError) as error:
        print(f"slim: {error}", file=sys.stderr)
        return 1
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
