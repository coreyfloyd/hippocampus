#!/usr/bin/env python3
"""Apply a wrap's recommended lessons, one commit each, using stdlib only.

The agent assesses each lesson; this module writes it, commits only its own lines,
delivers the commit and keeps each outcome in the session ledger, where the filing
pass and the report read it. Nothing here runs unless the auto-apply setting is on.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any, Mapping, Sequence

SETTING = "auto_apply"
RETIRED_SETTING = "auto_apply_lessons"
OUTCOME = "lesson_outcome"
STATUSES = ("applied", "dropped", "failed", "asked")
NOT_PUSHED = "committed, not pushed"
PULL_REQUEST = "pull request"
DELIVERED_REFS = "refs/hippocampus/delivered/"
IN_PROGRESS = ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply")
GENERATED_MARK = b"<!-- hippocampus-rules: generated"
INSTRUCTION_FILES = ("CLAUDE.md", "AGENTS.md")
REFUSED_DIRECT = re.compile(r"GH006|GH013|protected branch|pull request|merge request", re.IGNORECASE)
REMOTE_MOVED = re.compile(r"non-fast-forward|fetch first")


_record_spec = importlib.util.spec_from_file_location("lessons_record_write", Path(__file__).with_name("record_write.py"))
record_write = importlib.util.module_from_spec(_record_spec)
_record_spec.loader.exec_module(record_write)


class UpgradeRequired(ValueError):
    """A retired policy owner is still in place: auto-apply is refused until set-up moves it."""


class LessonError(Exception):
    """One lesson could not be applied or delivered; the wrap continues without it."""


def _holds_retired_setting(config: Mapping[str, Any]) -> bool:
    return RETIRED_SETTING in config


def enabled(config: Mapping[str, Any]) -> bool:
    """The knowledge profile's auto-apply setting, refused while the configuration still holds it."""
    if _holds_retired_setting(config):
        raise UpgradeRequired(f"hippocampus config: {RETIRED_SETTING} moved to the knowledge profile's {SETTING}; "
                         "run hippocampus-set-up to move it")
    return bool(policy().auto_apply)


WARNED = "HIPPOCAMPUS_RETIRED_SETTINGS_WARNED"
SKIPPED = "retired-settings check skipped"


def config_file() -> Path:
    """The configuration file the readers read, by the rule handoff.config_path shares."""
    return Path(_load("config_location", Path(__file__).with_name("config_location.py")).config_path())


def _setting_warnings() -> list[str]:
    path = config_file()
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as error:
        return [f"{path}: config unreadable; {SKIPPED} ({error})"]
    if not isinstance(config, dict):
        return [f"{path}: config unreadable; {SKIPPED} (not a JSON object)"]
    if not _holds_retired_setting(config):
        return []
    return [f"{path} still sets {RETIRED_SETTING}: replace it with {SETTING} in the knowledge "
            "profile's frontmatter; run hippocampus-set-up to move it"]


def _routing_warnings() -> list[str]:
    compose = _compose_rules()
    try:
        # The retired-file check comes first and reads only the profile's path, so a profile
        # that does not parse still gets the warning.
        compose.lesson_routing(compose.Policy(compose.profile_path(), None, None))
    except compose.RetiredOwner as error:
        return [str(error)]
    return []


def retired_owners() -> tuple[int, list[str]]:
    """How many retired policy owners are still in place, and the warning lines: one per owner
    (the file, its replacement in the knowledge profile, and hippocampus-set-up) and one per
    check that could not run. A failed check never hides another check's warning."""
    found, lines = 0, []
    for check in (_setting_warnings, _routing_warnings):
        try:
            messages = check()
        except Exception as error:  # A warning must never turn a finished install into a failure.
            lines.append(f"{SKIPPED}: {error}")
            continue
        found += sum(SKIPPED not in message for message in messages)
        lines += messages
    return found, lines


def print_retired() -> int:
    """Print each warning line on stderr; returns how many retired owners were found."""
    try:
        found, lines = retired_owners()
    except Exception as error:
        found, lines = 0, [f"{SKIPPED}: {error}"]
    for line in lines:
        print(f"warning: {line}", file=sys.stderr)
    return found


def warn_retired() -> None:
    """An install helper's warning, once per install flow.

    The helper marks the environment with its process id, so the install.sh it runs as a child
    does not repeat the warning; a value naming any other process is stale and ignored.
    """
    if os.environ.get(WARNED) == str(os.getppid()):
        return
    os.environ[WARNED] = str(os.getpid())
    print_retired()


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve deferred annotations through sys.modules
    spec.loader.exec_module(module)
    return module


_COMPOSE: Any = None


def _compose_rules() -> Any:
    """The routing contract's parser, loaded once so its ComposeError is one class."""
    global _COMPOSE
    if _COMPOSE is None:
        _COMPOSE = _load("compose_rules", Path(__file__).parents[1] / "compose_rules.py")
    return _COMPOSE


def policy() -> Any:
    """The knowledge profile's policy; an unreadable profile is a ValueError."""
    compose = _compose_rules()
    try:
        return compose.load_policy()
    except compose.ComposeError as error:
        raise ValueError(str(error)) from None


def routing_rules() -> dict[str, Any]:
    """The lesson routing's delivery keys: `lesson-policy`, `lesson-pull-requests` and the command.

    A malformed Lesson routing section is a ValueError, which every caller reports as an error.
    """
    compose = _compose_rules()
    current = policy()
    try:
        parsed = compose.load_lesson_delivery(current)
    except compose.RetiredOwner as error:
        raise UpgradeRequired(str(error)) from None
    except compose.ComposeError as error:
        raise ValueError(str(error)) from None
    return {"path": str(current.path), "propose": parsed["policy"] == "propose",
            "pull_requests": parsed["pull_requests"], "command": parsed["command"]}


def forbidden_reason(rules: Mapping[str, Any]) -> str | None:
    if rules["propose"]:
        return f"lessons were carried because the knowledge profile {rules['path']} sets lesson-policy: propose"
    return None


def outcomes(module: Any, session_id: str) -> list[dict[str, Any]]:
    """The latest outcome per lesson in this session's ledger, in first-recorded order."""
    latest: dict[tuple[str, ...], dict[str, Any]] = {}
    for row in module._ledger_records(module.ledger_path(session_id)) if session_id else []:
        if row.get("kind") != OUTCOME:
            continue
        # A damaged historical row must not prevent unrelated lessons from applying
        # or delivering. Sweep reports damaged rows separately during ledger search.
        outcome = row.get("outcome")
        if not isinstance(outcome, dict):
            continue
        identity = outcome.get("identity")
        if (not isinstance(identity, list) or not identity
                or not all(isinstance(part, str) for part in identity)
                or outcome.get("status") not in STATUSES):
            continue
        latest[tuple(identity)] = outcome
    return list(latest.values())


def _record(module: Any, session_id: str, outcome: Mapping[str, Any]) -> None:
    module.append_ledger(session_id, {"kind": OUTCOME, "outcome": dict(outcome)})


def report_section(rows: Sequence[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    section: dict[str, list[dict[str, Any]]] = {status: [] for status in STATUSES}
    for row in rows:
        section[row["status"]].append({key: value for key, value in row.items()
                                       if key not in ("identity", "status", "edits") and value is not None})
    return section


def ask_text(outcome: Mapping[str, Any]) -> str:
    """An ask is text: what already happened and how to undo it, with no choices."""
    undo = (f"Commit: {outcome['commit']}. The change is already applied; undo it by reverting that "
            "commit through the repository's normal delivery."
            if outcome.get("commit") else
            f"The target is {outcome.get('delivery') or 'not in a git repository'}, so there is no commit; "
            "the change is already applied, and removing the added text undoes it.")
    return (f"Lesson applied to always-loaded rules file {outcome['target']}. Added: {outcome['added']} "
            f"Evidence: {outcome['evidence']} {undo}")


def _git(cwd: Path | str, *args: str, env: Mapping[str, str] | None = None,
         stdin: bytes | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd), input=stdin, capture_output=True, timeout=120,
                          env={**os.environ, "GIT_TERMINAL_PROMPT": "0", **(env or {})})


def _text(result: subprocess.CompletedProcess) -> str:
    return result.stdout.decode(errors="replace").strip()


def _error(result: subprocess.CompletedProcess) -> str:
    return (result.stderr or result.stdout).decode(errors="replace").strip()


def _must(cwd: Path | str, *args: str, env: Mapping[str, str] | None = None,
          stdin: bytes | None = None) -> str:
    result = _git(cwd, *args, env=env, stdin=stdin)
    if result.returncode:
        raise LessonError(f"git {args[0]} failed: {_error(result)}")
    return _text(result)


def _edited(content: bytes, edits: Sequence[Mapping[str, str]], version: str) -> bytes:
    """Apply a lesson's edits: `old` to `new` when `old` is named, otherwise append `new`."""
    for edit in edits:
        new = edit["new"].encode()
        if edit.get("old"):
            old = edit["old"].encode()
            count = content.count(old)
            if count != 1:
                raise LessonError(f"the text to replace appears {count} times in the {version}, not once")
            content = content.replace(old, new)
        else:
            separator = b"\n" if content and not content.endswith(b"\n") else b""
            content += separator + new + (b"" if new.endswith(b"\n") else b"\n")
    return content


def _rule_files() -> list[Path]:
    """User-level rules files and every file they import, all resolved."""
    claude = Path(os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude").expanduser() / "CLAUDE.md"
    codex = Path(os.environ.get("CODEX_HOME") or "~/.codex").expanduser() / "AGENTS.md"
    pending, seen = [claude.resolve(), codex.resolve()], []
    while pending:
        path = pending.pop()
        if path in seen:
            continue
        seen.append(path)
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            continue
        for line in lines:
            imported = re.match(r"@(\S+)\s*$", line)
            if imported:
                pending.append((path.parent / Path(imported[1]).expanduser()).resolve())
    return seen


def _source(target: Path) -> tuple[Path, list[dict[str, str]]]:
    """Trace a target to the one source a lesson may edit, with its produced surfaces."""
    compose = _compose_rules()
    mapped = compose.surfaces_for(target.resolve(), compose.load_policy())
    if len(mapped["sources"]) != 1:
        raise LessonError(f"{target} is produced from several sources: {', '.join(mapped['sources'])}")
    source = Path(mapped["sources"][0])
    if source.is_file() and source.read_bytes().startswith(GENERATED_MARK):
        raise LessonError(f"{source} is a generated copy; name its source")
    return source, mapped["surfaces"]


def _checkout(path: Path) -> Path | None:
    directory = path.parent
    while not directory.is_dir():
        directory = directory.parent
    result = _git(directory, "rev-parse", "--show-toplevel")
    return Path(_text(result)).resolve() if result.returncode == 0 else None


def _write(path: Path, before: bytes | None, after: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if before != after:
        path.write_bytes(after)


def _commit(checkout: Path, path: Path, before: bytes | None, edits: Sequence[Mapping[str, str]],
            message: str) -> dict[str, str]:
    """Commit only the lesson's lines, leaving other changes to the file where they were.

    The edit is made to HEAD's copy, the index's copy and the working copy alike, so a
    change the user has staged or left unstaged stays exactly as it was.
    """
    if _git(checkout, "rev-parse", "--verify", "-q", "HEAD").returncode:
        raise LessonError("the repository has no commits yet")
    for state in IN_PROGRESS:
        if (checkout / _must(checkout, "rev-parse", "--git-path", state)).exists():
            raise LessonError(f"the checkout is in the middle of an operation ({state})")
    relative = path.relative_to(checkout).as_posix()
    tree = _text(_git(checkout, "ls-tree", "HEAD", "--", relative)).split()
    mode = tree[0] if tree else "100644"
    head = _git(checkout, "cat-file", "blob", tree[2]).stdout if tree else b""
    staged = _text(_git(checkout, "ls-files", "-s", "--", relative)).split()
    index = _git(checkout, "cat-file", "blob", staged[1]).stdout if staged else head
    committed = _edited(head, edits, "committed file")
    index_after = committed if index == head else _edited(index, edits, "staged file")
    working = _edited(before or b"", edits, "working file")
    _write(path, before, working)
    try:
        blob = _must(checkout, "hash-object", "-w", "--stdin", stdin=committed)
        with tempfile.TemporaryDirectory() as directory:
            env = {"GIT_INDEX_FILE": str(Path(directory) / "index")}
            _must(checkout, "read-tree", "HEAD", env=env)
            _must(checkout, "update-index", "--add", "--cacheinfo", f"{mode},{blob},{relative}", env=env)
            _must(checkout, "commit", "-q", "-m", message, env=env)
    except (LessonError, OSError, subprocess.SubprocessError):
        if before is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(before)
        raise
    result = {"commit": _must(checkout, "rev-parse", "HEAD")}
    # The commit stands from here on, so a stale index is a note and not a failed lesson.
    blob = _git(checkout, "hash-object", "-w", "--stdin", stdin=index_after)
    update = _git(checkout, "update-index", "--add", "--cacheinfo", f"{mode},{_text(blob)},{relative}")
    if blob.returncode or update.returncode:
        result["index_note"] = f"the index was not updated: {_error(update if blob.returncode == 0 else blob)}"
    return result


def _message(change: str) -> str:
    return f"lesson: {' '.join(change.split())}"


def _apply_one(row: Mapping[str, Any]) -> dict[str, Any]:
    target = Path(row["target"]).expanduser()
    if not target.is_absolute():
        raise LessonError(f"target {row['target']} must be an absolute path")
    source, surfaces = _source(target)
    before = source.read_bytes() if source.exists() else None
    checkout = _checkout(source)
    outcome: dict[str, Any] = {"target": str(source), "commit": None, "surfaces": surfaces,
                               "always_loaded": bool(row.get("always_loaded")) or source in _rule_files()
                               or source.name in INSTRUCTION_FILES or any(
                                   Path(surface["path"]).name in INSTRUCTION_FILES for surface in surfaces)}
    delivery = "not in a git repository"
    if checkout is not None:
        # A tracked file has a committed copy to build the lesson's commit from, and a new file
        # the repository would track gets its own first commit. An existing untracked file or
        # an ignored path is written in place, like a file outside git.
        tracked = _git(checkout, "--literal-pathspecs", "ls-files", "--error-unmatch", "--",
                       str(source)).returncode == 0
        if not tracked:
            ignored = _git(checkout, "check-ignore", "-q", "--", str(source)).returncode == 0
            if ignored or before is not None:
                delivery = "ignored by its repository" if ignored else "not tracked by its repository"
                checkout = None
    if checkout is None:
        _write(source, before, _edited(before or b"", row["edits"], "file"))
        return {**outcome, "delivery": delivery}
    branch = _git(checkout, "symbolic-ref", "--short", "HEAD")
    if branch.returncode:
        raise LessonError("the checkout has no branch checked out (detached HEAD)")
    committed = _commit(checkout, source, before, row["edits"], _message(row["change"]))
    return {**outcome, **committed, "checkout": str(checkout), "branch": _text(branch), "delivery": None}


def new_skill(row: Mapping[str, Any], item: Mapping[str, Any]) -> bool:
    """A new-skill lesson: its row or its carried item says `new_skill: true`."""
    return row.get("new_skill") is True or item.get("new_skill") is True


# The new-skill ask's choice that approves creating the skill; any other answer drops the lesson.
CREATE = "create the skill"
NO_ASK = {"asked": False, "delivered": False, "approved": False, "handed_off": False, "choices": [], "outcome": None}


def ask_record(module: Any, identity: Sequence[str]) -> dict[str, Any]:
    """What every session's ledger records about one new-skill lesson's ask: whether it was raised,
    delivered, answered yes and handed to the skill creator, and the choices it offered."""
    found = [outcome for session in module.ledger_sessions() for outcome in outcomes(module, session)
             if tuple(outcome["identity"]) == tuple(identity) and outcome["status"] == "asked"]
    if not found:
        return dict(NO_ASK)
    flags = {key: any(outcome.get(field) is True for outcome in found)
             for key, field in (("delivered", "ask_delivered"), ("approved", "approved"),
                                ("handed_off", "creator_handed_off"))}
    choices = next((outcome["choices"] for outcome in found
                    if isinstance(outcome.get("choices"), list) and outcome["choices"]), [])
    # The fullest record, so a new row keeps its delivery and the user's yes.
    fullest = max(found, key=lambda outcome: (outcome.get("creator_handed_off") is True,
                                              outcome.get("approved") is True, outcome.get("ask_delivered") is True))
    return {"asked": True, **flags, "choices": list(choices), "outcome": fullest}


def _asks(row: Mapping[str, Any], item: Mapping[str, Any], record: Mapping[str, Any]) -> bool:
    """Whether this row raises the new-skill ask: only `apply` with no answer, never after the
    user's yes, and never while a delivered ask is still open.

    A skip, dictated or not, drops a new-skill lesson; an `approved` one waits for the skill creator.
    """
    return (row["recommend"] == "apply" and "answer" not in row and not record["approved"]
            and not record["delivered"] and (new_skill(row, item) or record["asked"]))


def _offered(row: Mapping[str, Any], item: Mapping[str, Any], record: Mapping[str, Any]) -> list[Any]:
    """The choices the user answered from: the recorded ask's, else the row's or the item's."""
    choices = record["choices"] or (row["choices"] if "choices" in row else item.get("choices"))
    return list(choices) if isinstance(choices, list) else []


def asking(item: Mapping[str, Any], choices: Sequence[str]) -> dict[str, Any]:
    """A new-skill lesson stays carried, whole, with the choices its ask offers the user; an ask
    is no yes, so it never carries `approved`."""
    kept = {key: value for key, value in copy.deepcopy(dict(item)).items() if key != "approved"}
    return {**kept, "new_skill": True, "choices": list(choices)}


def approve(item: Mapping[str, Any]) -> dict[str, Any]:
    """A new-skill lesson the user said yes to, `context` unchanged. Its ask is answered, so it
    carries no choices; the ledger keeps them."""
    kept = {key: value for key, value in copy.deepcopy(dict(item)).items() if key != "choices"}
    return {**kept, "new_skill": True, "approved": True}


def deliver_ask(module: Any, session_id: str, outcome: Mapping[str, Any], receipt: Any) -> None:
    """Record a delivered new-skill ask beside its outcome, so the open ask is not raised again."""
    _record(module, session_id, {**outcome, "ask_delivered": True, "receipt": receipt})


def _with_ask(item: Mapping[str, Any], outcome: Mapping[str, Any]) -> dict[str, Any]:
    """Mark a carried lesson as applied, so no later wrap or successor applies it again.

    Its ask is text only, so choices the lesson was carried with do not travel with it.
    """
    kept = {key: value for key, value in item.items() if key != "choices"}
    return {**kept, "applied": True, "commit": outcome.get("commit"), "ask_text": ask_text(outcome)}


def apply(handoff: Mapping[str, Any], rows: Sequence[Mapping[str, Any]], module: Any,
          session_id: str) -> dict[str, Any]:
    """Apply, drop or fail each assessed lesson; return the payload without settled items.

    `rows` index the filing pass's list: open loops, then unrecorded session items.
    Lessons with no row stay carried. A lesson already applied is never applied again.
    A new-skill lesson is never applied: a row recommending `apply` makes it `asked`, carried with
    its choices, until the user answers; a delivered ask is not raised again. A row's `answer` is the
    user's answer to that ask, one of its choices: `create the skill` records the yes in the ledger,
    which alone approves it, and lists the proposal in `skill_creator_handoffs`; the ledger marks it
    handed off (`creator_handed_off`). Once marked, it is never handed off again: it stays carried
    and every later call lists it in `skill_creator_waiting`, until a `skip` reports the skill
    written, whatever answer a later row repeats. Any other answer drops it with that reason. A skip,
    dictated or not, drops it with its reason.
    """
    if not session_id:
        raise ValueError("apply-lessons requires a session id")
    resume = handoff.get("resume", {})
    loops = list(resume.get("open_loops", []))
    current = [item for item in handoff.get("session_items", []) if item.get("recorded") is not True]
    items = [*loops, *current]
    if not isinstance(rows, list) or not all(isinstance(row, Mapping) for row in rows):
        raise ValueError("lessons must be an array of objects")
    indices = [row.get("index") for row in rows]
    if len(set(indices)) != len(indices):
        duplicates = sorted({index for index in indices if indices.count(index) > 1}, key=repr)
        raise ValueError(f"lessons: one row per lesson; index {duplicates[0]!r} appears more than once")
    known = {tuple(outcome["identity"]): outcome for outcome in outcomes(module, session_id)}
    records: dict[int, dict[str, Any]] = {}

    def prior_of(item: Mapping[str, Any]) -> Mapping[str, Any] | None:
        identity = module.session_item_identity(item)
        return known.get(identity) if identity else None

    for row in rows:
        index = row.get("index")
        if type(index) is not int or not 0 <= index < len(items) or items[index].get("type") != "lesson":
            raise ValueError(f"lessons: index {index!r} does not name a lesson item")
        if row.get("recommend") not in ("apply", "skip"):
            raise ValueError(f"lessons: row {index}: recommend must be apply or skip")
        item, prior = items[index], prior_of(items[index])
        identity = module.session_item_identity(item)
        records[index] = (ask_record(module, identity) if identity and (
            new_skill(row, item) or "answer" in row or (prior or {}).get("status") == "asked") else dict(NO_ASK))
        record = records[index]
        skill = new_skill(row, item) or record["asked"]
        if "answer" in row:
            # No skill without the user's yes, and the yes only answers an ask that was raised.
            if not skill or not record["asked"]:
                raise ValueError(f"lessons: row {index}: an answer needs the new-skill lesson's ask raised first")
            if not isinstance(row["answer"], str) or row["answer"] not in _offered(row, item, record):
                raise ValueError(f"lessons: row {index}: answer must be one of the ask's choices")
            expected = "apply" if row["answer"] == CREATE else "skip"
            if row["recommend"] != expected:
                raise ValueError(f"lessons: row {index}: recommend {row['recommend']!r} contradicts the answer "
                                 f"{row['answer']!r}; that answer is recommend {expected!r}")
        elif skill and row["recommend"] == "apply":
            # A new skill is never written here: the user's yes comes first, through an ask.
            choices = _offered(row, item, record)
            if _asks(row, item, record) and (not isinstance(choices, list) or not choices
                                            or not all(isinstance(c, str) and c.strip() for c in choices)):
                raise ValueError(f"lessons: row {index}: a new-skill lesson requires the user's choices")
        elif row["recommend"] == "skip" and (skill or not row.get("dictated")):
            if not isinstance(row.get("reason"), str) or not row["reason"].strip():
                raise ValueError(f"lessons: row {index}: a skipped lesson requires its reason")
        else:
            edits = row.get("edits")
            if (any(not isinstance(row.get(field), str) or not row[field].strip()
                    for field in ("target", "change", "evidence"))
                    or not isinstance(edits, list) or not edits
                    or not all(isinstance(edit, Mapping) and isinstance(edit.get("new"), str) and edit["new"]
                               and ("old" not in edit or (isinstance(edit["old"], str) and edit["old"]))
                               for edit in edits)):
                raise ValueError(f"lessons: row {index}: an applied lesson requires target, change, evidence and edits")
    removed: list[Mapping[str, Any]] = []
    dropped: list[Mapping[str, Any]] = []
    annotated: dict[int, dict[str, Any]] = {}
    asked: list[int] = []
    creators: list[int] = []
    waiting: list[int] = []
    handed: set[tuple[str, ...]] = set()
    for row in sorted(rows, key=lambda row: row["index"]):
        item = items[row["index"]]
        identity = module.session_item_identity(item)
        if identity is None:
            raise ValueError(f"lessons: item {row['index']} has no session item identity")
        prior = known.get(identity)
        if prior and prior["status"] == "dropped":
            dropped.append(item)
        if item.get("applied"):
            continue
        record = records[row["index"]]
        skill = new_skill(row, item) or record["asked"]
        if skill and not (prior and prior["status"] in ("applied", "dropped")):
            base = {**(record["outcome"] or {}), "identity": list(identity), "new_skill": True,
                    "change": row.get("change") or (record["outcome"] or {}).get("change") or item["context"],
                    "target": row.get("target") or (record["outcome"] or {}).get("target"),
                    "choices": _offered(row, item, record)}
            if row.get("answer") is not None and row["answer"] != CREATE:
                # Any answer but the yes drops it, below, with that reason.
                row = {**row, "reason": row.get("reason") or f"the user answered {row['answer']!r}"}
            elif row.get("answer") == CREATE or (row["recommend"] == "apply" and record["approved"]):
                # The yes, read from the ledger: carried without choices until a skip reports the skill
                # written. Handed to the skill creator once, marked in the ledger; no answer hands it again.
                annotated[row["index"]] = approve(item)
                if identity in handed:
                    continue
                handed.add(identity)
                if not record["handed_off"]:
                    creators.append(row["index"])
                    _record(module, session_id, {**base, "status": "asked", "approved": True,
                                                 "creator_handed_off": True,
                                                 **({"answer": row["answer"]} if "answer" in row else {})})
                else:
                    waiting.append(row["index"])
                continue
            elif row["recommend"] == "apply":
                if _asks(row, item, record):
                    annotated[row["index"]] = asking(item, _offered(row, item, record))
                    asked.append(row["index"])
                    if not (prior and prior["status"] == "asked"):
                        _record(module, session_id, {**base, "status": "asked", "evidence": row.get("evidence"),
                                                     "choices": _offered(row, item, record)})
                continue  # A delivered ask still open: unchanged until the user answers.
            # A skip drops it below, with its reason.
        elif prior and prior["status"] != "failed":
            if prior.get("ask"):
                annotated[row["index"]] = _with_ask(item, prior)
            else:
                removed.append(item)
            continue
        outcome: dict[str, Any] = {"identity": list(identity), "evidence": row.get("evidence")}
        if row["recommend"] == "skip" and (skill or not row.get("dictated")):
            outcome.update(status="dropped", target=row.get("target"), change=row.get("change") or item["context"],
                           reason=row["reason"], **({"answer": row["answer"]} if "answer" in row else {}))
            removed.append(item)
            dropped.append(item)
        else:
            added = " ".join(edit["new"].strip() for edit in row["edits"])
            outcome.update(change=row["change"], added=added, dictated=bool(row.get("dictated")),
                           edits=[{key: edit[key] for key in ("old", "new") if edit.get(key)} for edit in row["edits"]])
            try:
                outcome.update(_apply_one(row), status="applied")
            except (LessonError, OSError, ValueError, subprocess.SubprocessError) as error:
                outcome.update(status="failed", target=row["target"], error=str(error))
            except _compose_rules().ComposeError as error:  # A malformed Lesson routing section fails one lesson.
                outcome.update(status="failed", target=row["target"], error=str(error))
            if outcome["status"] == "applied":
                outcome["ask"] = outcome.pop("always_loaded")
                # The commit stands, so its outcome is kept before anything else can fail.
                _record(module, session_id, outcome)
                if outcome.get("checkout"):
                    module.touched_checkouts(session_id, [outcome["checkout"]])
                if outcome["ask"]:
                    annotated[row["index"]] = _with_ask(item, outcome)
                else:
                    removed.append(item)
                continue
        _record(module, session_id, outcome)
    result = copy.deepcopy(dict(handoff))
    if "resume" in result and "open_loops" in result["resume"]:
        result["resume"]["open_loops"] = [annotated.get(index, item) for index, item in enumerate(loops)
                                          if item not in removed]
    if current:
        offset = len(loops)
        kept = [annotated.get(offset + index, item) for index, item in enumerate(current) if item not in removed]
        result["session_items"] = [*(item for item in handoff["session_items"] if item.get("recorded") is True), *kept]
    module.settle_session_items(removed, session_id, settlement=lambda item: (
        ("dropped", "the lessons step skipped it") if item in dropped
        else ("applied", "the lessons step applied it")))
    module.retain_session_items(list(annotated.values()), session_id)
    result["lesson_outcomes"] = outcomes(module, session_id)
    # Only the lessons this call asked about: the caller builds their asks and removes the key.
    result["new_skill_asked"] = [annotated[index] for index in asked]
    # Approved new-skill lessons: the agent hands each proposal, unchanged, to the skill creator.
    result["skill_creator_handoffs"] = [annotated[index] for index in creators]
    # Approved lessons already handed off, waiting for the skill, and where each proposal is kept.
    result["skill_creator_waiting"] = [{"proposal": annotated[index],
                                        "kept_in": "resume.open_loops" if index < len(loops) else "session_items"}
                                       for index in waiting]
    return result


def _remote(checkout: Path, branch: str) -> str | None:
    """The remote a push of this branch goes to, in git's own order of precedence."""
    remotes = _text(_git(checkout, "remote")).split()
    for key in (f"branch.{branch}.pushRemote", "remote.pushDefault", f"branch.{branch}.remote"):
        configured = _text(_git(checkout, "config", key))
        if configured in remotes:
            return configured
    return "origin" if "origin" in remotes else remotes[0] if len(remotes) == 1 else None


def _remote_url(checkout: Path, remote: str) -> str:
    url = _text(_git(checkout, "remote", "get-url", remote)).lower()
    return re.sub(r"\.git$", "", url.rstrip("/"))


def _requires_pull_request(checkout: Path, remote: str, rules: Mapping[str, Any]) -> bool:
    url = _remote_url(checkout, remote)
    return any(url.endswith((f"/{name}", f":{name}")) for name in rules["pull_requests"])


def _on_remote(checkout: Path, remote: str | None, branch: str, commit: str) -> bool:
    """Whether the selected remote's branch holds the commit; another remote's copy does not count."""
    return bool(remote) and _git(checkout, "merge-base", "--is-ancestor", commit,
                                 f"refs/remotes/{remote}/{branch}").returncode == 0


def _default_branch(checkout: Path, remote: str) -> str | None:
    head = _git(checkout, "symbolic-ref", "--short", f"refs/remotes/{remote}/HEAD")
    return _text(head).removeprefix(f"{remote}/") if head.returncode == 0 else None


def _push(checkout: Path, remote: str, branch: str) -> tuple[bool, str, int]:
    """Push a branch; when the remote moved, bring its commits in and push again, once.

    A merge brings them in, because it keeps the commit named in the report and the ask.
    """
    first = _git(checkout, "push", remote, f"refs/heads/{branch}:refs/heads/{branch}")
    if first.returncode == 0:
        return True, "", 1
    error = _error(first)
    if REFUSED_DIRECT.search(error) or not REMOTE_MOVED.search(error):
        return False, error, 1
    current = _git(checkout, "symbolic-ref", "--short", "HEAD")
    if current.returncode or _text(current) != branch:
        # A merge acts on the checked-out branch; bringing the remote's commits into another
        # branch would change work the lesson never touched.
        return False, (f"{error}; the checkout is on {_text(current) or 'a detached HEAD'}, not {branch}, "
                       "so the remote's commits were not brought in"), 1
    fetched = _git(checkout, "fetch", remote, f"+refs/heads/{branch}:refs/remotes/{remote}/{branch}")
    if fetched.returncode:
        return False, _error(fetched), 1
    before = _text(_git(checkout, "rev-parse", "HEAD"))
    merged = _git(checkout, "merge", "--no-edit", f"refs/remotes/{remote}/{branch}")
    if merged.returncode:
        _git(checkout, "merge", "--abort")
        return False, f"could not bring in the remote's commits: {_error(merged)}", 1
    second = _git(checkout, "push", remote, f"refs/heads/{branch}:refs/heads/{branch}")
    error = _error(second) if second.returncode else ""
    if second.returncode and before:
        # The merge was made only for the retry; whatever refused the push, undo it and leave
        # the branch as it was, with the user's other changes.
        _git(checkout, "reset", "--merge", before)
    return second.returncode == 0, error, 2


def _lesson_branch(session_id: str) -> str:
    """`lesson/<readable id>-<digest>`: readable, a valid ref, and distinct for distinct sessions.

    Dots are replaced too, so `..`, `.lock` and a leading dot cannot make an invalid ref; the
    digest of the exact id keeps two ids that read the same after replacement apart.
    """
    name = re.sub(r"-+", "-", re.sub(r"[^A-Za-z0-9_-]", "-", session_id)).strip("-")[:40]
    if not name:
        raise LessonError(f"session id {session_id!r} names no lesson branch")
    return f"lesson/{name}-{hashlib.sha256(session_id.encode()).hexdigest()[:8]}"


def _mark_delivered(checkout: Path, local_commit: str, delivered: str) -> None:
    """Record in the checkout that a local lesson commit was delivered by pull request.

    The mark is a ref under `refs/hippocampus/delivered/`, so every later wrap's saved line
    leaves the local commit out of the commits it counts as not pushed.
    """
    _must(checkout, "update-ref", f"{DELIVERED_REFS}{local_commit}", delivered)


def _pull_requests(checkout: Path, remote: str, session_id: str, rows: Sequence[Mapping[str, Any]],
                   command: str | None) -> list[dict[str, Any]]:
    """Deliver a wrap's lessons for one checkout on one lesson branch, with one pull request.

    The branch is cut from the remote's copy of the base branch, or continues the session's
    existing lesson branch, in a temporary worktree, so the user's checkout is not touched.
    Each lesson is re-applied from its edits as one commit of its own; the lessons stack, so
    two of them for one file do not conflict with each other when they merge. The user's
    command opens the request and owns how it merges; the package never merges. It reads one
    JSON request on stdin and prints the pull request's reference last.
    """
    if not command:
        raise LessonError("a pull request is required, but the knowledge profile's lesson routing names no lesson-pull-request-command")
    base = rows[0]["branch"]
    lesson_branch = _lesson_branch(session_id)
    _must(checkout, "fetch", remote, f"+refs/heads/{base}:refs/remotes/{remote}/{base}")
    existing = f"refs/remotes/{remote}/{lesson_branch}"
    continued = _git(checkout, "fetch", remote, f"+refs/heads/{lesson_branch}:{existing}").returncode == 0
    updates: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory() as directory:
        worktree = str(Path(directory) / "lesson")
        _must(checkout, "worktree", "add", "--detach", worktree, existing if continued else f"refs/remotes/{remote}/{base}")
        try:
            for row in rows:
                update: dict[str, Any] = {"lesson_branch": lesson_branch}
                try:
                    # One bad target fails its own row; the others still reach the branch.
                    update["lesson_path"] = _inside(checkout, row["target"]).as_posix()
                    if continued and row.get("lesson_commit") and _git(
                            worktree, "merge-base", "--is-ancestor", row["lesson_commit"], "HEAD").returncode == 0:
                        update["lesson_commit"] = row["lesson_commit"]
                    else:
                        update["lesson_commit"] = _reapply(checkout, worktree, row)
                except (LessonError, OSError, ValueError, subprocess.SubprocessError) as error:
                    update.pop("lesson_path", None)
                    update.update(delivery=NOT_PUSHED, error=f"{lesson_branch}: {error}")
                updates.append(update)
            if any("lesson_commit" in update for update in updates):
                _must(worktree, "push", remote, f"HEAD:refs/heads/{lesson_branch}")
                _git(checkout, "fetch", remote, f"+refs/heads/{lesson_branch}:{existing}")
        finally:
            _git(checkout, "worktree", "remove", "--force", worktree)
    delivered = [(row, update) for row, update in zip(rows, updates) if "lesson_commit" in update]
    for row, update in delivered:
        _mark_delivered(checkout, row["commit"], update["lesson_commit"])
    if not delivered:
        return updates
    paths = [update.pop("lesson_path") for _, update in delivered]
    request = {"checkout": str(checkout), "remote": remote, "base": base, "branch": lesson_branch,
               "title": _message(delivered[0][0]["change"]) if len(delivered) == 1
               else f"lessons: {len(delivered)} applied at wrap",
               "body": "\n".join(f"- {_message(row['change'])} (`{path}`, {update['lesson_commit'][:12]})"
                                 for (row, update), path in zip(delivered, paths)),
               "lessons": [{"title": _message(row["change"]), "path": path, "commit": update["lesson_commit"]}
                           for (row, update), path in zip(delivered, paths)]}
    try:
        opened = subprocess.run(record_write.argv(command), cwd=str(checkout), input=json.dumps(request),
                                capture_output=True, text=True, timeout=120)
        reference = opened.stdout.strip().splitlines()[-1] if opened.stdout.strip() else ""
        if opened.returncode or not reference:
            raise LessonError(opened.stderr.strip() or f"the command exited {opened.returncode} with no reference")
    except (OSError, ValueError, subprocess.SubprocessError, LessonError) as error:
        for _, update in delivered:
            update.update(delivery=NOT_PUSHED, error=f"pushed {lesson_branch}, but no pull request was opened: {error}")
        return updates
    for row, update in delivered:
        update.update(commit=update.pop("lesson_commit"), local_commit=row["commit"],
                      pull_request=reference, delivery=PULL_REQUEST, error=None)
    return updates


def _inside(checkout: Path, target: str) -> Path:
    """A lesson target as a path inside its checkout, symlinks resolved on both sides."""
    try:
        return Path(target).resolve().relative_to(Path(checkout).resolve())
    except ValueError:
        raise LessonError(f"{target} is not inside {checkout}") from None


def _reapply(checkout: Path, worktree: str, row: Mapping[str, Any]) -> str:
    """Commit one lesson's edits on the lesson branch, from the branch's own copy of the file.

    A lesson that fails leaves nothing staged or changed, so the next lesson's commit holds
    only its own lines.
    """
    relative = _inside(checkout, row["target"])
    path = Path(worktree) / relative
    before = path.read_bytes() if path.exists() else b""
    try:
        _write(path, before, _edited(before, row["edits"], "remote's file"))
        _must(worktree, "add", "--", relative.as_posix())
        _must(worktree, "commit", "-q", "-m", _message(row["change"]))
    except (LessonError, OSError, subprocess.SubprocessError):
        _git(worktree, "reset", "-q", "--hard", "HEAD")
        _git(worktree, "clean", "-q", "-fd", "--", relative.as_posix())
        raise
    return _must(worktree, "rev-parse", "HEAD")


def deliver(module: Any, session_id: str, persist_bound: bool, rules: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Run after the persist binding: settle the delivery of every undelivered lesson commit."""
    rows = [row for row in outcomes(module, session_id) if row["status"] == "applied" and row.get("commit")
            and row.get("delivery") in (None, NOT_PUSHED)]
    pushes: dict[tuple[str, str], tuple[bool, str, int]] = {}
    requests: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        checkout, branch = Path(row["checkout"]), row["branch"]
        update: dict[str, Any] = {}
        try:
            remote = _remote(checkout, branch)
            if remote:
                default = _default_branch(checkout, remote)
                if default and default != branch:
                    update.update(default_branch=default,
                                  note=f"Reaches {default} when {branch} does.")
            if _on_remote(checkout, remote, branch, row["commit"]):
                update.update(delivery="pushed", error=None)
            elif not persist_bound:
                update.update(delivery=NOT_PUSHED, error="persist is unbound, so nothing pushes it")
            elif not remote:
                update.update(delivery=NOT_PUSHED, error="the repository has no remote")
            else:
                if _requires_pull_request(checkout, remote, rules):
                    pushed, error, attempts = False, "the lesson routing requires a pull request", 0
                else:
                    key = (str(checkout), branch)
                    if key not in pushes:
                        pushes[key] = _push(checkout, remote, branch)
                    pushed, error, attempts = pushes[key]
                if pushed:
                    update.update(delivery="pushed", attempts=attempts, error=None)
                elif attempts == 0 or REFUSED_DIRECT.search(error):
                    requests.setdefault((str(checkout), branch, remote), []).append({**row, **update})
                    continue
                else:
                    update.update(delivery=NOT_PUSHED, attempts=attempts, error=error)
        except (LessonError, OSError, ValueError, subprocess.SubprocessError) as error:
            update.update(delivery=NOT_PUSHED, error=str(error))
        _record(module, session_id, {**row, **update})
    for (checkout, _, remote), group in requests.items():
        try:
            updates = _pull_requests(Path(checkout), remote, session_id, group, rules["command"])
        except (LessonError, OSError, ValueError, subprocess.SubprocessError) as error:
            updates = [{"delivery": NOT_PUSHED, "error": str(error)} for _ in group]
        for row, update in zip(group, updates):
            _record(module, session_id, {**row, **update})
    return outcomes(module, session_id)


if __name__ == "__main__":
    if sys.argv[1:] != ["warn-retired"]:
        raise SystemExit("usage: lessons.py warn-retired")
    # install.sh decides whether its flow already warned; exit 10 tells it a retired owner was found.
    raise SystemExit(10 if print_retired() else 0)
