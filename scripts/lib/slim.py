#!/usr/bin/env python3
"""Run the unattended slim: pick recorded files, build slim branches, compose the asks.

The driving agent reviews each file and decides its edits; this module chooses what it may
review, applies those edits in temporary clones of each repository's hosted default branch,
pushes one branch per repository and writes the asks. The user's checkouts are only read.
Nothing here merges or schedules. Standard library only.
"""
from __future__ import annotations

import argparse
import base64
import contextlib
import copy
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
STALL_LIMIT = 2
CHECKOUTS = "slim_checkouts"
PENDING, MERGED, REJECTED = "awaiting decision", "merged", "rejected"
REJECTED_REASON = "over limit, slim rejected"
PENDING_REASON = "slim branch awaiting its decision"
STALLED_REASON = "over limit, slim stalled"
REPORT_LISTS = ("contradictions", "duplicates", "rules", "changes", "deferred", "unverified", "surfaces_verified")
CHOICE_LISTS = ("contradictions", "duplicates", "rules")  # The rows a deferred file marks as not done.
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
    return {"schema_version": SCHEMA_VERSION, "slims": [], "asks": [], "stalled": {}, "deferred_reported": [],
            "run": None}


@contextlib.contextmanager
def _transaction() -> Iterator[dict[str, Any]]:
    """The state under its lock, written back only when the block succeeds.

    Nothing inside a transaction clones, fetches or pushes, so `decide` and `ask-delivered`
    never wait on a remote.
    """
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
    """A file's one identity: its repository and the canonical spelling of its path."""
    return row["repository"], _canonical(row["path"])


def _name(row: Mapping[str, Any]) -> str:
    return " ".join(_key(row))


def _canonical(path: Any) -> str:
    """A repository file's one spelling: relative, with no `.`, `..` or repeated or trailing separators.

    Every key, frozen check and size lookup compares this form, so a spelling cannot slip a
    file past the frozen rule or hide it from the sizes.
    """
    if not isinstance(path, str) or not path or Path(path).is_absolute():
        raise ValueError(f"{path!r} is not a path inside its repository")
    normal = os.path.normpath(path)
    if normal == "." or normal == ".." or normal.startswith("../"):
        raise ValueError(f"{path} is not a path inside its repository")
    return normal


def _status(slim: Mapping[str, Any]) -> str:
    states = [branch["status"] for branch in slim["branches"]]
    return PENDING if PENDING in states else REJECTED if REJECTED in states else MERGED


def _file_status(slim: Mapping[str, Any]) -> str:
    """Eligibility follows only the branch that changed the recorded file.

    Other branches still participate in retention and frozen-file protection.
    If no branch changed this file, it has no pending or rejected edit to suppress.
    """
    return next((branch["status"] for branch in slim["branches"]
                 if branch["repository"] == slim["repository"] and slim["path"] in branch["changed"]), MERGED)


def _frozen(state: Mapping[str, Any]) -> dict[tuple[str, str], str]:
    """Every file a slim branch awaiting its decision changed, with that branch."""
    return {(branch["repository"], _canonical(path)): branch["branch"] for slim in state["slims"]
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
            try:
                rows.append({**row, "path": _canonical(row["path"])})
            except ValueError as error:
                raise ValueError(f"slim: {path} row {number}: {error}") from error
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


def _timeout(default: int) -> int:
    """Seconds a remote command may take; `HIPPOCAMPUS_SLIM_REMOTE_TIMEOUT` overrides the default."""
    value = os.environ.get("HIPPOCAMPUS_SLIM_REMOTE_TIMEOUT")
    return int(value) if value and value.isdigit() else default


def _remote(cwd: Path | str, *args: str) -> subprocess.CompletedProcess:
    """A git command that talks to a remote. May raise `subprocess.TimeoutExpired`."""
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, timeout=_timeout(120),
                          env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})


def _listed(address: str, branch: str) -> bool | None:
    """Whether a branch is on its remote; None when the remote cannot be read."""
    try:
        listed = _remote(".", "ls-remote", "--heads", address, f"refs/heads/{branch}")
    except subprocess.SubprocessError:
        return None
    return bool(lessons._text(listed)) if listed.returncode == 0 else None


def _clone(address: str, directory: Path) -> None:
    """Clone the tip of the hosted default branch: the remote's own HEAD, not a checkout's idea of it.

    Hooks stay off in the clone, for every later command too: nothing in a repository, or in
    a user's git template, runs during an unattended slim.
    """
    result = subprocess.run(["git", "clone", "--quiet", "--depth", "1", "--single-branch", "--no-tags",
                             "--config", "core.hooksPath=/dev/null", address, str(directory)],
                            capture_output=True, text=True, timeout=_timeout(600),
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


def _baseline(record: Mapping[str, Any]) -> dict[str, Any]:
    """What a later record is compared with: the file's size and its duplicate rules."""
    return {"size": record["size"], "limits": record["limits"],
            "findings": [json.dumps(over_limit._finding_key(finding)) for finding in record["duplicates"]]}


def _changed(record: Mapping[str, Any], baseline: Mapping[str, Any]) -> bool:
    """Whether a session measured the file larger than the baseline, or recorded a new duplicate."""
    limits = {(limit["tool"], limit["unit"]): limit["measured"] for limit in baseline["limits"]}
    if any(limit["measured"] > limits.get((limit["tool"], limit["unit"]), limit["measured"])
           for limit in record["limits"]):
        return True
    if any(isinstance(value, int) and value > baseline["size"].get(unit, value)
           for unit, value in record["size"].items()):
        return True
    return any(json.dumps(over_limit._finding_key(finding)) not in baseline["findings"]
               for finding in record["duplicates"])


def _baseline_now(slim: Mapping[str, Any], config: Mapping[str, Any]) -> dict[str, Any] | None:
    """The baseline with the file's size on the default branch now, or None when it cannot be read."""
    address, _ = _clone_address(config, slim["repository"])
    if address is None:
        return None
    with tempfile.TemporaryDirectory(prefix="hippocampus-slim-") as directory:
        try:
            _clone(address, Path(directory) / "clone")
        except (lessons.LessonError, OSError, subprocess.SubprocessError):
            return None
        return _baseline_from(Path(directory) / "clone", slim)


def _probe_all(pending: Sequence[tuple[Mapping[str, Any], Mapping[str, Any]]],
               config: Mapping[str, Any]) -> list[tuple[Mapping[str, Any], tuple[Any, Any, Any]]]:
    """Settle every awaiting branch, cloning each repository at most once for the whole plan."""
    with tempfile.TemporaryDirectory(prefix="hippocampus-slim-") as directory:
        clones: dict[str, Path | Exception] = {}

        def clone_of(repository: str) -> Path:
            if repository not in clones:
                address, reason = _clone_address(config, repository)
                try:
                    if address is None:
                        raise lessons.LessonError(reason)
                    clone = Path(directory) / hashlib.sha256(repository.encode()).hexdigest()[:12]
                    _clone(address, clone)
                    clones[repository] = clone
                except (lessons.LessonError, OSError, subprocess.SubprocessError) as error:
                    clones[repository] = error
            found = clones[repository]
            if isinstance(found, Exception):
                raise found
            return found

        return [(branch, _probe(slim, branch, config, clone_of)) for slim, branch in pending]


def _probe(slim: Mapping[str, Any], branch: Mapping[str, Any], config: Mapping[str, Any],
           clone_of: Any) -> tuple[str | None, dict[str, Any] | None, str | None]:
    """A pending branch's settlement, read from its remote: status, baseline and any warning.

    A branch still on the remote stays pending, because git cannot tell that its pull request
    closed. A branch that is gone merged when its diff reverses cleanly on the default branch.
    It is rejected only when its diff still applies there: the default branch never took the
    change. When neither holds, the outcome is unknown and stays pending. A remote that
    cannot be read, or a git error, is a warning and the branch waits.
    """
    address, reason = _clone_address(config, branch["repository"])
    if address is None:
        return None, None, f"{_branch_name(branch)}: {reason}"
    listed = _listed(address, branch["branch"])
    if listed is None:
        return None, None, f"{_branch_name(branch)}: its remote could not be read; it stays awaiting its decision"
    if listed:
        return PENDING, None, None
    try:
        clone = clone_of(branch["repository"])
    except (lessons.LessonError, OSError, subprocess.SubprocessError) as error:
        return None, None, f"{_branch_name(branch)}: {error}"
    diff = base64.b64decode(branch["diff"])
    reverse = lessons._git(clone, "apply", "--reverse", "--check", stdin=diff)
    if reverse.returncode == 0:
        return MERGED, None, None
    forward = lessons._git(clone, "apply", "--check", stdin=diff) if reverse.returncode == 1 else reverse
    if forward.returncode == 0:
        return REJECTED, _baseline_from(clone, slim), None
    if forward.returncode == 1:
        return None, None, (f"{_branch_name(branch)}: neither patch check is conclusive; "
                            "it stays awaiting its decision")
    return None, None, (f"{_branch_name(branch)}: git apply failed, so it stays awaiting its decision: "
                        f"{lessons._error(forward)}")


def _branch_name(branch: Mapping[str, Any]) -> str:
    return f"{branch['repository']} {branch['branch']}"


def _baseline_from(clone: Path, slim: Mapping[str, Any]) -> dict[str, Any] | None:
    """The baseline with the file's size in a clone of the default branch, or None when unreadable."""
    try:
        text = (clone / slim["path"]).read_text(encoding="utf-8")
        return {**slim["measured"], **_measure(text, slim["measured"])}
    except (OSError, ValueError):
        return None


def _settle(slim: dict[str, Any], branch: dict[str, Any], status: str, baseline: Mapping[str, Any] | None) -> None:
    branch["status"] = status
    branch["push_status"] = "verified"
    if (status == REJECTED and baseline and branch["repository"] == slim["repository"]
            and slim["path"] in branch["changed"]):
        slim["measured"] = dict(baseline)


def _prune_reported(state: dict[str, Any]) -> None:
    """Forget a reported deferral once its branch is settled; the file is free or rejected then."""
    pending = {branch["branch"] for slim in state["slims"] for branch in slim["branches"] if branch["status"] == PENDING}
    state["deferred_reported"] = [key for key in state["deferred_reported"] if key.split(" ", 1)[0] in pending]


def _find(state: Mapping[str, Any], repository: str, name: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
    for slim in state["slims"]:
        for branch in slim["branches"]:
            if branch["repository"] == repository and branch["branch"] == name:
                return slim, branch
    return None


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
        run = state["run"]
        pushing = copy.deepcopy(run["current"]) if run and not run["closed"] and run["current"] and run[
            "current"].get("pushing") else None
    warnings: list[str] = []
    if pushing:
        # The helper stopped between the push and its record: the remotes say what landed.
        pushed, failures, warnings = _landed(pushing["pushing"]["branches"], config)
    with _transaction() as state:
        if pushing:
            _recover(state, pushing, pushed, failures)
        # A run that stopped early still owes its asks; a slim left open starts over.
        if state["run"] and not state["run"]["closed"]:
            _close(state, state["run"])
        _remove_workspaces(state["run"])
        pending = [(copy.deepcopy(slim), copy.deepcopy(branch)) for slim in state["slims"]
                   for branch in slim["branches"] if branch["status"] == PENDING]
    probes = _probe_all(pending, config)
    with _transaction() as state:
        warnings.extend(warning for _, (_, _, warning) in probes if warning)
        for branch, (status, baseline, _) in probes:
            found = _find(state, branch["repository"], branch["branch"])
            if status and found and found[1]["status"] == PENDING:
                _settle(*found, status, baseline)
        state["slims"] = [slim for slim in state["slims"] if _status(slim) != MERGED]
        _prune_reported(state)
        frozen = _frozen(state)
        latest = {_key(slim): slim for slim in state["slims"]}
        run = {"id": uuid.uuid4().hex[:12], "started": _now(), "queue": [], "analyzed": 0,
               "current": None, "results": [], "skipped": [], "deferred": [], "unreachable": [],
               "failed": [], "closed": None}
        for record in sorted(records, key=lambda row: (-overage(row), row["repository"], row["path"])):
            slim = latest.get(_key(record))
            if slim and _file_status(slim) == PENDING:
                run["skipped"].append(_row(record, PENDING_REASON))
            elif _key(record) in frozen:
                run["deferred"].append({**_row(record, f"already changed by {frozen[_key(record)]}"),
                                        "changed_by": frozen[_key(record)]})
            elif slim and _file_status(slim) == REJECTED and not _changed(record, slim["measured"]):
                run["skipped"].append(_row(record, REJECTED_REASON))
            elif _stalled(state, record):
                run["skipped"].append(_row(record, STALLED_REASON))
            else:
                reason = _unreachable(record, config)
                if reason:
                    run["unreachable"].append(_row(record, reason))
                else:
                    run["queue"].append(record)
        state["run"] = run
        return {"run_id": run["id"], "queued": len(run["queue"]), "files_per_run": FILES_PER_RUN,
                "skipped": run["skipped"], "deferred": run["deferred"], "unreachable": run["unreachable"],
                "warnings": warnings, "undelivered_asks": state["asks"]}


def _unreachable(record: Mapping[str, Any], config: Mapping[str, Any]) -> str | None:
    """Why a file waits: its repository, or one holding a duplicate of its rule, cannot be cloned."""
    _, reason = _clone_address(config, record["repository"])
    if reason:
        return reason
    others = dict.fromkeys(span["repository"] for finding in record["duplicates"] for span in finding["spans"])
    for repository in others:
        if repository != record["repository"]:
            _, reason = _clone_address(config, repository)
            if reason:
                return f"{reason}, and it holds a duplicate of this file's rule"
    return None


def _stalled(state: dict[str, Any], record: Mapping[str, Any]) -> bool:
    """Whether a file waits after repeated runs with no branch; a changed file gets a fresh start."""
    row = state["stalled"].get(_name(record))
    if row and _changed(record, row["measured"]):
        del state["stalled"][_name(record)]
        return False
    return bool(row) and row["count"] >= STALL_LIMIT


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row(record: Mapping[str, Any], reason: str) -> dict[str, Any]:
    limits = over_limit._limits_text(record.get("limits", []))
    return {"repository": record["repository"], "path": record["path"], "reason": reason, "limits": limits,
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
        shutil.rmtree(directory, ignore_errors=True)
        _clone(address, directory)
        current["workspaces"][repository] = str(directory)
    return Path(current["workspaces"][repository])


def _inside(workspace: Path, path: str) -> Path:
    """A repository file in a clone. Git's own directory is no repository file, in any case form."""
    path = _canonical(path)
    target = (workspace / path).resolve()
    root = workspace.resolve()
    if not target.is_relative_to(root):
        raise ValueError(f"{path} is not a path inside its repository")
    if any(part.casefold() == ".git" for part in (*Path(path).parts, *target.relative_to(root).parts)):
        raise ValueError(f"{path} is inside .git, which a slim never edits")
    if target.relative_to(root) != Path(path):
        raise ValueError(f"{path} reaches {target.relative_to(root)} through a link; name the file by its own path")
    return target


def _branch(run_id: str, record: Mapping[str, Any]) -> str:
    name = re.sub(r"-+", "-", re.sub(r"[^A-Za-z0-9_-]", "-", record["path"])).strip("-")[:40]
    digest = hashlib.sha256(f"{_name(record)}".encode()).hexdigest()[:8]
    return f"slim/{run_id[:8]}-{name}-{digest}"


def begin(run_id: str) -> dict[str, Any]:
    """Hand the agent the next file, or finish the run. One slim is open at a time."""
    _require_setting("slim begin")
    config = handoff.read_config()
    while True:
        with _transaction() as state:
            run = _run(state, run_id)
            if run["closed"]:
                return run["closed"]
            _not_pushing(run)
            if not run["current"]:
                _next_slim(state, run)
            if not run["current"]:
                return _close(state, run)
            if run["current"]["ready"]:
                return _briefing(state, run)
            current = copy.deepcopy(run["current"])
        reason, failed = _open(current, config)
        with _transaction() as state:
            run = _run(state, run_id)
            record = current["record"]
            if reason is None:
                run["current"] = {**current, "ready": True}
                run["analyzed"] += 1
                continue
            run["current"] = None
            if failed:
                run["failed"].append({**_row(record, reason), "measured": _baseline(record)})
            else:
                run["skipped"].append(_row(record, reason))
        shutil.rmtree(current["base"], ignore_errors=True)


def _next_slim(state: dict[str, Any], run: dict[str, Any]) -> None:
    """Take the next file a slim can change; a file it cannot does not use up the run's three."""
    while run["queue"] and run["analyzed"] < FILES_PER_RUN:
        record = run["queue"].pop(0)
        frozen = _frozen(state)
        if _key(record) in frozen:
            run["deferred"].append({**_row(record, f"already changed by {frozen[_key(record)]}"),
                                    "changed_by": frozen[_key(record)]})
            continue
        run["current"] = {"record": record, "base": tempfile.mkdtemp(prefix="hippocampus-slim-"), "workspaces": {},
                          "branch": _branch(run["id"], record), "id": uuid.uuid4().hex[:12], "ready": False}
        return


def _open(current: dict[str, Any], config: Mapping[str, Any]) -> tuple[str | None, bool]:
    """Clone what a slim reads, outside the lock: why it cannot go ahead, and whether that failed."""
    record = current["record"]
    try:
        target = _inside(_workspace(current, record["repository"], config), record["path"])
        if not target.is_file():
            return "not on the repository's default branch", False
        limits = _measure(target.read_text(encoding="utf-8"), record)["limits"]
        if not record["duplicates"] and not any(limit["measured"] > limit["limit"] for limit in limits):
            return "already under its limits on the default branch", False
        for finding in record["duplicates"]:
            for span in finding["spans"]:
                _workspace(current, span["repository"], config)
    except (lessons.LessonError, OSError, ValueError, subprocess.SubprocessError) as error:
        return str(error), True
    return None, False


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
    _require_setting("slim workspace")
    config = handoff.read_config()
    with _transaction() as state:
        run = _run(state, run_id)
        _not_pushing(run)
        current = copy.deepcopy(run["current"])
        if not current or not current["ready"]:
            raise ValueError("slim workspace: no slim is open")
    path = _workspace(current, repository, config)
    _keep_workspaces(run_id, current)
    return {"repository": repository, "workspace": str(path)}


def _keep_workspaces(run_id: str, current: Mapping[str, Any]) -> None:
    with _transaction() as state:
        _run(state, run_id)["current"]["workspaces"].update(current["workspaces"])


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
            for field in ("repository", "path"):
                if field in row and (not isinstance(row[field], str) or not row[field]):
                    raise ValueError(f"slim finish: {key} row {number}: {field} must be text")
    checked = {**checked, **{key: [_located(row, record) for row in checked[key]] for key in CHOICE_LISTS}}
    changes = []
    for number, row in enumerate(checked["changes"], 1):
        edits = row.get("edits")
        if not isinstance(edits, list) or not edits or not all(
                isinstance(edit, Mapping) and isinstance(edit.get("new"), str)
                and ("old" not in edit or isinstance(edit["old"], str)) and (edit.get("old") or edit["new"])
                for edit in edits):
            raise ValueError(f"slim finish: changes row {number} requires edits, each with old or new text")
        for field in ("repository", "group"):
            if field in row and (not isinstance(row[field], str) or not row[field]):
                raise ValueError(f"slim finish: changes row {number}: {field} must be text")
        try:
            changes.append(_located(row, record))
        except ValueError as error:
            raise ValueError(f"slim finish: changes row {number}: {error}") from error
    if not all(isinstance(surface, str) for surface in checked["surfaces_verified"]):
        raise ValueError("slim finish: surfaces_verified must list surface paths")
    left = result.get("left")
    if left is not None and not isinstance(left, str):
        raise ValueError("slim finish: left must be text")
    return {**checked, "changes": changes, "left": left}


def _located(row: Mapping[str, Any], record: Mapping[str, Any]) -> dict[str, Any]:
    """A result row with its file named canonically: `repository` defaults to the recorded file's."""
    located = {**row, "repository": row.get("repository") or record["repository"]}
    if "path" in row:
        located["path"] = _canonical(row["path"])
    return located


def _partition(report: dict[str, Any], frozen: Mapping[tuple[str, str], str]) -> list[dict[str, Any]]:
    """Keep the changes to make; a frozen file defers its change and its whole group.

    The report's contradiction, duplicate and rule rows whose file is deferred move to
    `not_done`, so the ask lists as done only what the branch changed.
    """
    changes = report["changes"]
    blocked = {row["group"] for row in changes if _key(row) in frozen and row.get("group")}
    kept, deferred, dropped = [], {}, []
    for row in changes:
        if _key(row) in frozen:
            deferred[_key(row)] = f"already changed by {frozen[_key(row)]}"
        elif row.get("group") in blocked:
            deferred.setdefault(_key(row), "it depends on a change to a deferred file")
        else:
            kept.append(row)
            continue
        dropped.append(row)
    partial = dict(deferred)
    # A file with any change kept is changed on the branch, so it is not deferred.
    deferred = {key: reason for key, reason in deferred.items() if key not in {_key(row) for row in kept}}
    report["deferred"] = [*report["deferred"], *({"repository": repository, "path": path, "reason": reason}
                                                 for (repository, path), reason in deferred.items())]
    report["not_done"] = []
    for key in CHOICE_LISTS:
        done = []
        for row in report[key]:
            affected = "path" in row and _key(row) in partial
            matching = [change for change in changes if "path" in row and _key(change) == _key(row)]
            if row.get("group"):
                matching = [change for change in matching if change.get("group") == row["group"]]
            elif affected and _key(row) not in deferred:
                wording = row.get("text", row.get("rule", ""))
                matching = [change for change in matching if wording and any(
                    wording in edit.get("old", "") or wording in edit["new"] for edit in change["edits"])]
            # With ambiguous attribution, do not claim a deferred action was performed.
            not_done = affected and (not matching or any(change in dropped for change in matching))
            if not_done:
                report["not_done"].append({**row, "kind": key, "reason": partial[_key(row)]})
            else:
                done.append(row)
        report[key] = done
    return kept


def _edited(current: dict[str, Any], changes: Sequence[Mapping[str, Any]],
            config: Mapping[str, Any]) -> dict[tuple[str, str], bytes]:
    """Each changed file's new content, computed before anything is written.

    An edit that does not fit the default branch's file is the agent's to correct, so it is
    a refusal, like any other malformed result.
    """
    contents: dict[tuple[str, str], bytes] = {}
    for row in changes:
        target = _inside(_workspace(current, row["repository"], config), row["path"])
        if target.exists() and not target.is_file():
            raise ValueError(f"slim finish: {row['path']} is not a file")
        content = contents.get(_key(row))
        if content is None:
            content = target.read_bytes() if target.is_file() else b""
        if content.startswith(lessons.GENERATED_MARK):
            raise ValueError(f"slim finish: {row['path']} is a generated copy; name its source")
        try:
            edited = content
            for edit in row["edits"]:
                previous = edited
                edited = lessons._edited(previous, [edit], "default branch's file")
                if edited == previous:
                    raise ValueError(f"slim finish: {row['path']}: its edits leave the file as it is")
        except lessons.LessonError as error:
            raise ValueError(f"slim finish: {row['path']}: {error}") from error
        if edited == content:
            raise ValueError(f"slim finish: {row['path']}: its edits leave the file as it is")
        contents[_key(row)] = edited
    return contents


def _sizes(record: Mapping[str, Any], before: str, after: str) -> list[dict[str, Any]]:
    return [{"tool": limit["tool"], "unit": limit["unit"], "limit": limit["limit"],
             "before": measured(before, limit["unit"]), "after": measured(after, limit["unit"])}
            for limit in record["limits"]]


def _commit(workspace_path: Path, branch: str, paths: Sequence[str], title: str) -> dict[str, str]:
    """Commit the written files on a new branch; the diff is kept as base64, so any file's bytes fit."""
    base = lessons._must(workspace_path, "symbolic-ref", "--short", "HEAD")
    lessons._must(workspace_path, "checkout", "-q", "-b", branch)
    lessons._must(workspace_path, "add", "--", *paths)
    lessons._must(workspace_path, "commit", "-q", "-m", title)
    diff = lessons._git(workspace_path, "diff", "--binary", "HEAD~1", "HEAD")
    if diff.returncode:
        raise lessons.LessonError(f"git diff failed: {lessons._error(diff)}")
    return {"base": base, "commit": lessons._must(workspace_path, "rev-parse", "HEAD"),
            "diff": base64.b64encode(diff.stdout).decode("ascii")}


def finish(run_id: str, result: Any) -> dict[str, Any]:
    """Close the open slim: apply its edits on one branch per repository and push them.

    A refusal changes nothing and keeps the slim open, so a corrected result can follow it.
    Every check and commit happens before the first push, and the branches are recorded
    before it, so a helper that dies mid-push leaves nothing the next `plan` cannot settle.
    """
    _require_setting("slim finish")
    config = handoff.read_config()
    with _transaction() as state:
        run = _run(state, run_id)
        if not run["current"] or not run["current"]["ready"]:
            raise ValueError("slim finish: no slim is open")
        _not_pushing(run)
        current = copy.deepcopy(run["current"])
        frozen = _frozen(state)
    record = current["record"]
    report = _check_result(result, record)
    kept = _partition(report, frozen)
    outcome: dict[str, Any] = {"id": current["id"], "repository": record["repository"], "path": record["path"],
                               "measured": _baseline(record),
                               "report": {key: value for key, value in report.items() if key != "changes"}}
    gaps, surfaces = _surface_gaps(list(dict.fromkeys(_key(row) for row in kept)), report, config)
    slim = None
    candidates = None
    try:
        for row in report["changes"]:
            _workspace(current, row["repository"], config)
        _keep_workspaces(run_id, current)
        # Validate every submitted edit, including deferred edits, before any terminal outcome.
        # This computes bytes only; workspaces remain untouched and refusals keep the slim open.
        _edited(current, report["changes"], config)
        if gaps:
            outcome.update(status="unverified", gaps=gaps)
        else:
            contents, sizes = _review(current, kept, report, config)
            outcome.update(sizes=sizes, surfaces=list(surfaces))
            candidates = _commit_all(current, contents, config)
    except (lessons.LessonError, OSError, subprocess.SubprocessError) as error:
        outcome.update(status="failed", error=str(error))
    else:
        if candidates is not None:
            if not candidates:
                outcome.update(status="unchanged", branches=[])
            else:
                with _transaction() as state:
                    _run(state, run_id)["current"]["pushing"] = {"outcome": outcome, "branches": candidates}
                pushed, failures = _push_all(current, candidates, config)
                outcome.update(_built(pushed, failures))
                slim = _slim(run_id, current, pushed) if pushed else None
    with _transaction() as state:
        _record(state, _run(state, run_id), record, outcome, slim)
    shutil.rmtree(current["base"], ignore_errors=True)
    return {key: outcome.get(key) for key in ("id", "repository", "path", "status", "sizes", "branches", "error", "gaps")}


def _review(current: dict[str, Any], kept: Sequence[Mapping[str, Any]], report: Mapping[str, Any],
            config: Mapping[str, Any]) -> tuple[dict[tuple[str, str], bytes], list[dict[str, Any]]]:
    """The new contents and sizes, refusing a result that leaves a limit unexplained."""
    record = current["record"]
    contents = _edited(current, kept, config)
    target = _inside(_workspace(current, record["repository"], config), record["path"])
    before = target.read_text(encoding="utf-8")
    after = contents[_key(record)].decode("utf-8") if _key(record) in contents else before
    sizes = _sizes(record, before, after)
    if not report["left"] and any(row["after"] is not None and row["after"] > row["limit"] for row in sizes):
        raise ValueError(f"slim finish: {_name(record)} is still over a limit, so the result requires left: "
                         "what is left and why")
    return contents, sizes


def _commit_all(current: dict[str, Any], contents: Mapping[tuple[str, str], bytes],
                config: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Write and commit every repository's branch locally, before anything reaches a remote.

    A failure here leaves no branch anywhere: the workspaces are restored, so a refusal can
    be corrected and the result sent again.
    """
    record = current["record"]
    branches, bases = [], {}
    try:
        for repository in dict.fromkeys(repository for repository, _ in contents):
            changed = [path for owner, path in contents if owner == repository]
            workspace_path = _workspace(current, repository, config)
            bases[workspace_path] = lessons._must(workspace_path, "symbolic-ref", "--short", "HEAD")
            for path in changed:
                file = _inside(workspace_path, path)
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(contents[(repository, path)])
            commit = _commit(workspace_path, current["branch"], changed, f"slim: {record['path']}")
            branches.append({"repository": repository, "branch": current["branch"], "changed": changed,
                             "status": PENDING, **commit})
    except (lessons.LessonError, OSError, subprocess.SubprocessError, ValueError):
        _restore(bases, current["branch"])
        raise
    return branches


def _restore(bases: Mapping[Path, str], branch: str) -> None:
    """Put each touched workspace back on its default branch with no slim branch and no edit."""
    for workspace_path, base in bases.items():
        lessons._git(workspace_path, "checkout", "-q", "-f", base)
        lessons._git(workspace_path, "branch", "-q", "-D", branch)
        lessons._git(workspace_path, "clean", "-q", "-fd")


def _push_all(current: Mapping[str, Any], branches: Sequence[Mapping[str, Any]],
              config: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """Push each committed branch; one that fails fails alone, and the others stand."""
    pushed, failures = [], []
    for branch in branches:
        try:
            workspace_path = _workspace(current, branch["repository"], config)
            result = _remote(workspace_path, "push", "origin", f"HEAD:refs/heads/{branch['branch']}")
            if result.returncode:
                raise lessons.LessonError(f"git push failed: {lessons._error(result)}")
        except (lessons.LessonError, OSError, subprocess.SubprocessError) as error:
            # The remote may have taken the branch before the error: what it holds decides.
            address, _ = _clone_address(config, branch["repository"])
            listed = _listed(address, branch["branch"]) if address else None
            if listed is None:
                pushed.append({**branch, "push_status": "pending-unverified"})
                continue
            if not listed:
                failures.append(f"{branch['repository']} {branch['branch']}: {error}")
                continue
        pushed.append(dict(branch))
    return pushed, failures


def _landed(branches: Sequence[Mapping[str, Any]],
            config: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """Which branches a stopped push left on their remotes; one that cannot be read is kept, with a warning."""
    pushed, failures, warnings = [], [], []
    for branch in branches:
        address, reason = _clone_address(config, branch["repository"])
        listed = _listed(address, branch["branch"]) if address else None
        if listed is None:
            warnings.append(f"{branch['repository']} {branch['branch']}: kept as awaiting its decision, its remote "
                            f"could not be read{': ' + reason if reason else ''}")
            pushed.append({**branch, "push_status": "pending-unverified"})
        elif listed:
            pushed.append(dict(branch))
        else:
            failures.append(f"{branch['repository']} {branch['branch']}: not on the remote; the helper stopped before "
                            "its push")
    return pushed, failures, warnings


def _built(pushed: Sequence[Mapping[str, Any]], failures: Sequence[str]) -> dict[str, Any]:
    if not pushed:
        return {"status": "failed", "error": "; ".join(failures), "branches": []}
    status = "pending-unverified" if any(row.get("push_status") == "pending-unverified" for row in pushed) else "slimmed"
    return {"status": status, "branches": list(pushed), "failures": list(failures)}


def _slim(run_id: str, current: Mapping[str, Any], branches: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    record = current["record"]
    return {"id": current["id"], "run": run_id, "repository": record["repository"], "path": record["path"],
            "measured": _baseline(record), "branches": list(branches)}


def _record(state: dict[str, Any], run: dict[str, Any], record: Mapping[str, Any], outcome: Mapping[str, Any],
            slim: Mapping[str, Any] | None) -> None:
    """Close the slim in the state: its outcome for the ask, and its branches for the frozen rule."""
    if slim:
        # This slim replaces the file's earlier rejection, so a later merge cannot uncover it.
        state["slims"] = [row for row in state["slims"] if _key(row) != _key(record) or _status(row) == PENDING]
        state["slims"].append(dict(slim))
    run["results"].append(dict(outcome))
    run["current"] = None


def _not_pushing(run: Mapping[str, Any]) -> None:
    if run["current"] and run["current"].get("pushing"):
        raise ValueError("slim: the open slim's branches were being pushed when the helper stopped; "
                         "run plan to settle them")


def _recover(state: dict[str, Any], current: Mapping[str, Any], pushed: Sequence[Mapping[str, Any]],
             failures: Sequence[str]) -> None:
    """Record a slim whose helper stopped mid-push, from what its remotes hold."""
    run = state["run"]
    if not run or not run["current"] or run["current"]["id"] != current["id"] or not run["current"].get("pushing"):
        return
    outcome = {**current["pushing"]["outcome"], **_built(pushed, failures)}
    _record(state, run, current["record"], outcome, _slim(run["id"], current, pushed) if pushed else None)
    shutil.rmtree(current["base"], ignore_errors=True)


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
    if outcome["status"] == "pending-unverified":
        parts.append("Push result unverified: the remote could not be read. These files stay frozen until "
                     "a later plan reconciles the branches; branch publication is not confirmed.")
    if outcome.get("failures"):
        parts.append(_section("Branches not pushed:", [f"- {row}" for row in outcome["failures"]]))
    if report["not_done"]:
        parts.append(_section("Chosen but not done, their file is deferred:", [
            f"{_choice_text(row)} Not done: {row['reason']}" for row in report["not_done"]]))
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


def _choice_text(row: Mapping[str, Any]) -> str:
    if row["kind"] == "contradictions":
        return f"- {row['rules']} Winner: {row['winner']}"
    if row["kind"] == "duplicates":
        return f"- {row['rule']} Owner: {row['owner']}"
    return f"- {row['action']} in {row['path']}: {row['text']}"


def _deferral_text(row: Mapping[str, Any]) -> str:
    """The ask for a recorded file an earlier run's branch froze: it is left as it is, and why."""
    limits = f" ({row['limits']})" if row.get("limits") else ""
    return (f"{_name(row)} is left as it is{limits}: {row['changed_by']} in {row['repository']}, awaiting its "
            "decision, already changed it. A later run slims it once that branch is merged or rejected. "
            "Nothing was changed.")


def _ask(run: Mapping[str, Any], outcome: Mapping[str, Any], text: str, choices: Sequence[str]) -> dict[str, Any]:
    return {"id": hashlib.sha256(outcome["id"].encode()).hexdigest()[:12], "text": text, "choices": list(choices),
            "applied": not choices, "repository": outcome["repository"], "path": outcome["path"],
            "identity": {"session_id": f"slim-{outcome['id']}", "produced_at": run["started"], "text": text}}


def _stall(state: dict[str, Any], row: Mapping[str, Any], error: str | None) -> str:
    """Count a run with no branch for a file; at the limit, the sentence its ask ends with."""
    entry = state["stalled"].setdefault(_name(row), {"count": 0})
    entry.update(count=entry["count"] + 1, error=error, measured=row["measured"])
    if entry["count"] < STALL_LIMIT:
        return ""
    return (f"It has produced no branch in {entry['count']} runs in a row, so later runs skip it, reported as "
            f'"{STALLED_REASON}", until a session measures it larger or records a new duplicate, or '
            "`slim.py retry` clears it.")


def _close(state: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    """Compose the run's asks last, so a file an earlier slim froze reaches that slim's ask."""
    asks = []
    for outcome in run["results"]:
        branches = {row["branch"] for row in outcome.get("branches", [])}
        outcome["report"]["deferred"] = [*outcome["report"]["deferred"], *(
            row for row in run["deferred"] if row.get("changed_by") in branches)]
        if outcome["status"] in ("slimmed", "pending-unverified"):
            state["stalled"].pop(_name(outcome), None)
            asks.append(_ask(run, outcome, _ask_text(outcome), []))
            continue
        stalled = _stall(state, outcome, outcome.get("error"))
        if outcome["status"] == "unchanged" and (outcome["report"]["left"] or stalled):
            asks.append(_ask(run, outcome, f"{_ask_text(outcome)} {stalled}".strip(), []))
        elif outcome["status"] == "unverified":
            asks.append(_ask(run, outcome, (
                f"The slim of {_name(outcome)} produced no branch: a generated surface it would change could not "
                f"be verified. {'; '.join(outcome['gaps'])}. Every file is left as it is. {stalled}").strip(),
                ORDINARY_CHOICES))
        elif stalled:
            asks.append(_ask(run, outcome, _failed_text(outcome, outcome["error"], stalled), ORDINARY_CHOICES))
    for row in run["failed"]:
        stalled = _stall(state, row, row["reason"])
        if stalled:
            asks.append(_ask(run, {**row, "id": f"{run['id']} {_name(row)}"},
                             _failed_text(row, row["reason"], stalled), ORDINARY_CHOICES))
    this_run = {branch["branch"] for outcome in run["results"] for branch in outcome.get("branches", [])}
    for row in run["deferred"]:
        # A file frozen by an earlier run's branch has no slim here to carry it: it gets its own ask, once.
        key = f"{row.get('changed_by')} {_name(row)}"
        if row.get("changed_by") and row["changed_by"] not in this_run and key not in state["deferred_reported"]:
            state["deferred_reported"].append(key)
            asks.append(_ask(run, {**row, "id": key}, _deferral_text(row), []))
    for ask in asks:
        checklist.validate_ask_payload(ask)
    state["asks"].extend(asks)
    run["closed"] = {"done": True, "run_id": run["id"], "analyzed": run["analyzed"], "asks": asks,
                     "results": [{key: row.get(key) for key in ("repository", "path", "status", "error")}
                                 for row in run["results"]],
                     "waiting": [_row(record, "waiting for a later run") for record in run["queue"]],
                     "skipped": run["skipped"], "deferred": run["deferred"], "unreachable": run["unreachable"],
                     "failed": [{key: value for key, value in row.items() if key != "measured"} for row in run["failed"]]}
    return run["closed"]


def _failed_text(row: Mapping[str, Any], error: str, stalled: str) -> str:
    return f"The slim of {_name(row)} failed: {error}. Every file is left as it is. {stalled}"


def decide(repository: str, branch_name: str, decision: str) -> dict[str, Any]:
    """Settle a branch awaiting its decision. A pull request closed without merging is `rejected`."""
    config = handoff.read_config()

    def pending(state: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        found = _find(state, repository, branch_name)
        if found is None:
            raise ValueError(f"slim decide: no slim branch {branch_name} in {repository}")
        if found[1]["status"] != PENDING:
            raise ValueError(f"slim decide: {branch_name} is already settled as {found[1]['status']}")
        return found

    with _transaction() as state:
        slim = copy.deepcopy(pending(state)[0])
    baseline = _baseline_now(slim, config) if decision == REJECTED else None
    with _transaction() as state:
        slim, branch = pending(state)
        _settle(slim, branch, decision, baseline)
        _prune_reported(state)
        return {"repository": slim["repository"], "path": slim["path"], "branch": branch_name, "status": _status(slim)}


def retry(repository: str, path: str) -> dict[str, Any]:
    """Let a stalled file back into later runs, for a user who has fixed what stopped it."""
    name = _name({"repository": repository, "path": path})
    with _transaction() as state:
        row = state["stalled"].pop(name, None)
        if row is None:
            raise ValueError(f"slim retry: {name} is not stalled")
        return {"repository": repository, "path": _canonical(path), "status": "will be slimmed again"}


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
    command = commands.add_parser("retry")
    command.add_argument("--repository", required=True)
    command.add_argument("--path", required=True)
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
        elif args.operation == "retry":
            output = retry(args.repository, args.path)
        else:
            output = ask_delivered(args.ask, args.receipt)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, lessons.LessonError,
            subprocess.SubprocessError, lessons._compose_rules().ComposeError) as error:
        print(f"slim: {error}", file=sys.stderr)
        return 1
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
