#!/usr/bin/env python3
"""Plan and apply the complete knowledge setup for the configured knowledge profile, with approval.

The complete knowledge setup is a knowledge root with ``raw/``, ``output/``,
``docs/`` and ``wiki/``, the session cache ``wiki/hot.md``, the operation and
decision logs, and the two independent follow-up destinations, all recorded in a
valid knowledge profile. ``plan`` reports whether the configured profile already
has it, and the exact changes that would complete it, and writes nothing.
``apply`` recomputes the plan, refuses a changed plan, creates only what is
missing and writes the profile. Existing files, profile lines and body text are
kept; a released profile with ``wiki_enabled: false`` stays readable and is
upgraded only through an approved plan.
"""
import argparse
import contextlib
import hashlib
import difflib
import importlib.util
import io
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


policy = _load("knowledge_policy_setup", HERE / "policy_setup.py")
reader = policy.reader
EXAMPLE = HERE.parent / "profiles/karpathy-wiki.example.md"
FOLDERS = ("raw", "output", "docs", "wiki")
FILES = (("operation_log_file", "docs/log.md"), ("decision_log_file", "docs/DECISIONS.md"),
         ("hot_file", "wiki/hot.md"))
ROUTES = ("wiki_followup_destination", "artifact_followup_destination")


def parsed(path):
    """The profile's frontmatter values, or the reader's refusal as an error."""
    errors = io.StringIO()
    try:
        with contextlib.redirect_stderr(errors):
            return reader.parse(path)
    except SystemExit:
        raise ValueError(f"{path}: {errors.getvalue().strip()}; repair it before set-up continues") from None


def unquoted(value):
    value = (value or "").strip()
    return value[1:-1].strip() if len(value) > 1 and value[0] == value[-1] and value[0] in "\"'" else value


def placeholders():
    """The example profile's instructional destination text, which is never a configured route."""
    values = parsed(EXAMPLE)
    return {unquoted(values[key]) for key in ROUTES}


def kind(path):
    if path.is_dir():
        return "directory"
    return "file" if path.is_file() else "other" if path.exists() or path.is_symlink() else "absent"


def plan(profile, root=None, routes=None):
    profile = pathlib.Path(profile)
    routes = {key: value for key, value in (routes or {}).items() if value is not None}
    original = profile.read_bytes().decode("utf-8") if profile.is_file() else None
    if original is None and profile.exists():
        raise ValueError(f"{profile} is not a file; move it away before set-up continues")
    values = parsed(profile) if original is not None else {}
    result = {"profile": str(profile), "profile_exists": original is not None, "needs": [], "conflicts": [],
              "create_directories": [], "create_files": [], "preserved": [], "profile_fields": []}
    fields = {}

    def field(key, value):
        if values.get(key) != value:
            fields[key] = value
            result["profile_fields"].append({"field": key, "current": values.get(key), "proposed": value})

    if original is None:
        field("profile_version", "4")
    elif values.get("profile_version") != "4":
        raise ValueError(f"{profile}: profile_version must be 4; repair it before set-up continues")
    root_value = root if root is not None else values.get("knowledge_root")
    if not root_value:
        result["needs"].append("knowledge_root: the absolute knowledge-root location")
    elif not pathlib.Path(root_value).is_absolute():
        raise ValueError(f"knowledge_root must be an absolute path: {root_value}")
    else:
        field("knowledge_root", root_value)
    if values.get("wiki_enabled") == "false":
        field("wiki_enabled", None)
    for key, default in FILES:
        field(key, values.get(key) or default)
    unusable = placeholders()
    for key in ROUTES:
        value = routes.get(key, values.get(key))
        if not unquoted(value) or unquoted(value) in unusable:
            result["needs"].append(f"{key}: a concrete route another agent can follow "
                                   "(the example's instructional text is not one)")
        else:
            field(key, value)

    if root_value:
        base = pathlib.Path(root_value)
        resolved = base.resolve()
        if not base.exists() and not base.parent.is_dir():
            result["conflicts"].append(f"{base.parent} does not exist; create it or choose another root")
        directories = [base, *(base / name for name in FOLDERS)]
        files = []
        for key, default in FILES:
            relative = pathlib.Path(values.get(key) or default)
            target = (base / relative).resolve()
            if relative.is_absolute() or not target.is_relative_to(resolved) or target == resolved:
                raise ValueError(f"{key} must name a file inside knowledge_root: {relative}")
            directories += [parent for parent in reversed((base / relative).parents) if parent.is_relative_to(base)]
            files.append(base / relative)
        for path in dict.fromkeys(directories):
            state = kind(path)
            if state == "absent":
                result["create_directories"].append(str(path))
            elif state == "directory":
                result["preserved"].append(str(path))
            else:
                result["conflicts"].append(f"{path} exists and is not a directory; move it away")
        for path in files:
            state = kind(path)
            if state == "absent":
                result["create_files"].append(str(path))
            elif state == "file":
                result["preserved"].append(str(path))
            else:
                result["conflicts"].append(f"{path} exists and is not a file; move it away")

    proposed = original if original is not None else "---\n---\n"
    for key, value in fields.items():
        proposed = policy.with_field(proposed, key, value)
    result["profile_diff"] = "".join(difflib.unified_diff(
        (original or "").splitlines(keepends=True), proposed.splitlines(keepends=True), str(profile), str(profile)))
    if original is not None and not result["profile_diff"]:
        result["preserved"].append(str(profile))
    result["ready"] = not result["needs"] and not result["conflicts"]
    changes = result["create_directories"] or result["create_files"] or result["profile_diff"]
    result["status"] = "complete" if result["ready"] and not changes else "incomplete"
    # A lesson routing problem is reported here, never hidden, and does not block the knowledge setup.
    current = policy.checked(proposed, profile, require_wiki=True) if result["status"] == "complete" else (
        policy.compose.load_policy(profile) if original is not None else None)
    result["problems"] = [current.routing_error] if current and current.routing_error else []
    result["file_states"] = {path: policy.state(pathlib.Path(path)) if kind(pathlib.Path(path)) != "directory"
                             else "directory" for path in sorted({str(profile), *result["preserved"],
                                                                  *result["create_directories"],
                                                                  *result["create_files"]})}
    payload = json.dumps(result, sort_keys=True)
    result["approval_fingerprint"] = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    result["_proposed"] = proposed
    return result


def apply(profile, fingerprint, root=None, routes=None):
    fresh = plan(profile, root, routes)
    if fresh["approval_fingerprint"] != fingerprint:
        raise ValueError("the approved knowledge setup changed; rerun plan and approve the new fingerprint")
    if not fresh["ready"]:
        raise ValueError("knowledge setup is incomplete: " + "; ".join(fresh["needs"] + fresh["conflicts"]))
    if fresh["status"] == "complete":
        return fresh
    profile = pathlib.Path(profile)
    created, committed = [], False
    try:
        for path in map(pathlib.Path, fresh["create_directories"]):
            path.mkdir()
            created.append(path)
        for path in map(pathlib.Path, fresh["create_files"]):
            with path.open("x", encoding="utf-8"):
                pass
            created.append(path)
        policy.checked(fresh["_proposed"], profile, require_wiki=True)
        missing = [parent for parent in reversed(profile.parents) if not parent.exists()]
        for parent in missing:
            parent.mkdir()
            created.append(parent)
        policy.atomic_write(profile, fresh["_proposed"])
        committed = True
    finally:
        if not committed:
            for path in reversed(created):
                path.rmdir() if path.is_dir() else path.unlink()
    fresh["status"] = "complete"
    return fresh


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("plan", "apply"))
    parser.add_argument("--root", help="the absolute knowledge-root location to record")
    parser.add_argument("--wiki-followup", help="the route for wiki-maintenance follow-ups")
    parser.add_argument("--artifact-followup", help="the route for source-derived actions")
    parser.add_argument("--approval-fingerprint", help="fingerprint printed by the approved plan")
    args = parser.parse_args()
    profile = policy.compose.profile_path()  # The one profile every knowledge reader reads.
    routes = {"wiki_followup_destination": args.wiki_followup,
              "artifact_followup_destination": args.artifact_followup}
    try:
        if args.command == "plan":
            result = plan(profile, args.root, routes)
        else:
            if not args.approval_fingerprint:
                parser.error("apply requires --approval-fingerprint from the approved plan")
            result = apply(profile, args.approval_fingerprint, args.root, routes)
    except (OSError, ValueError, policy.compose.ComposeError) as exc:
        print(f"knowledge-setup: {exc}", file=sys.stderr)
        return 1
    result.pop("_proposed")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
