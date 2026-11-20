#!/usr/bin/env python3
"""Move lesson routing and the auto-apply setting into the knowledge profile, with approval.

The knowledge profile is the one policy owner: its ``auto_apply`` field and its
``## Lesson routing`` section. ``plan`` shows the exact move from the retired
owners (the standalone routing file and the configuration's
``auto_apply_lessons``), or a requested change to the setting, and writes
nothing. ``apply`` recomputes the plan, refuses a changed plan or an unresolved
conflict, then writes the profile and retires the old owners. Nothing here runs
at session start.
"""
import argparse
import contextlib
import difflib
import hashlib
import importlib.util
import io
import json
import os
import pathlib
import re
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


compose = _load("policy_compose_rules", HERE / "compose_rules.py")
fence_after = compose.fence_after
reader = _load("policy_validate_profile", HERE / "validate_profile.py")
handoff = _load("policy_handoff", HERE / "lib" / "handoff.py")

RETIRED_SETTING = "auto_apply_lessons"
SURFACE_PATH = re.compile(r"(    - path:)(.*)")
HEADING = re.compile(r"(#{1,6})(\s.*)")


def state(path):
    """What a plan saw at a path, so apply can refuse when it changed."""
    if path.is_file():
        return hashlib.sha256(path.read_bytes()).hexdigest()
    return "not a file" if path.exists() else "absent"


def fixed_path(raw, old):
    """A Produced surfaces path as written, or made absolute when it was relative to ``old``."""
    value = compose.routing_scalar(raw)
    if pathlib.Path(os.path.expandvars(value)).expanduser().is_absolute():
        return raw.strip()
    return json.dumps(str(compose.resolved_routing_path(value, old)))


def produced_block(lines):
    """For each line, whether it sits in the Produced surfaces block, as ``parse_surfaces`` reads it."""
    flags, active = [], False
    for line in lines:
        if line.strip() == "Produced surfaces:":
            active = True
        elif active and line.strip() and not line.startswith(" ") and not line.lstrip().startswith("#"):
            active = False
        flags.append(active)
    return flags


def moved_routing(text, old, rebase):
    """The routing file's lines as a profile section, headings two levels down, paths kept effective.

    Returns the lines and any heading too deep to move two levels.
    """
    lines, deep, fence = [], [], None
    source_lines = text.splitlines()
    for line, active in zip(source_lines, produced_block(source_lines)):
        heading = HEADING.fullmatch(line) if fence is None else None
        fence = fence_after(line, fence)
        if heading:
            if len(heading[1]) > 4:
                deep.append(line)
            line = "#" * (len(heading[1]) + 2) + heading[2]
        elif active and rebase:
            source = compose.SURFACE_SOURCE.fullmatch(line)
            surface = SURFACE_PATH.fullmatch(line)
            if source:
                line = f"  {fixed_path(source[1], old)}:" + (" []" if source[2] else "")
            elif surface:
                line = f"{surface[1]} {fixed_path(surface[2], old)}"
        lines.append(line)
    while lines and not lines[-1].strip():
        lines.pop()
    while lines and not lines[0].strip():
        lines.pop(0)
    return lines, deep


def without_paths(lines):
    """The routing's text with every Produced surfaces path masked, for comparing everything else."""
    masked = []
    for line, active in zip(lines, produced_block(lines)):
        if active and compose.SURFACE_SOURCE.fullmatch(line):
            line = "  <source>:" + (" []" if compose.SURFACE_SOURCE.fullmatch(line)[2] else "")
        elif active and SURFACE_PATH.fullmatch(line):
            line = "    - path: <path>"
        if line.strip():
            masked.append(line)
    return masked


def effective(lines, directory, label):
    """What a routing text decides: delivery keys and every produced surface, fully resolved."""
    surfaces = compose.parse_surfaces(lines, directory, label)
    return {"delivery": compose.parse_lesson_delivery(lines, label),
            "surfaces": {str(source): rows for source, rows in sorted(surfaces.items())}}


def nonblank(lines):
    return [line for line in lines if line.strip()]


def frontmatter_end(lines):
    return next(index for index in range(1, len(lines)) if lines[index].rstrip("\r\n") == "---")


def newline(lines):
    return "\r\n" if lines and lines[0].endswith("\r\n") else "\n"


def with_field(text, key, value):
    """The profile with one frontmatter field set (``None`` removes it), every other line kept."""
    if value is not None and ("\n" in value or "\r" in value):
        raise ValueError(f"{key} must be one line")
    lines = text.splitlines(keepends=True)
    end = frontmatter_end(lines)
    row = [] if value is None else [f"{key}: {value}{newline(lines)}"]
    for index in range(1, end):
        if lines[index].partition(":")[0].strip() == key and ":" in lines[index] and not lines[index].startswith(" "):
            return "".join([*lines[:index], *row, *lines[index + 1:]])
    return "".join([*lines[:end], *row, *lines[end:]])


def with_setting(text, value):
    return with_field(text, "auto_apply", "true" if value else "false")


def with_routing(text, routing):
    lines = text.splitlines(keepends=True)
    end = newline(lines)
    block = [compose.POLICY_HEADING + end, end, *(line + end for line in routing)]
    spans = compose.policy_sections(lines, frontmatter_end(lines) + 1)
    if spans:
        span = spans[0]
        following = [end] if span[1] < len(lines) else []
        return "".join([*lines[:span[0]], *block, *following, *lines[span[1]:]])
    body = "".join(lines).rstrip("\r\n")
    return body + end + end + "".join(block)


def without_setting(text, config):
    """The configuration's text without the retired key, every other byte kept when that parses back."""
    expected = {key: value for key, value in config.items() if key != RETIRED_SETTING}
    member = rf'"{RETIRED_SETTING}"\s*:\s*(?:true|false|null|-?[0-9][0-9.eE+-]*|"(?:[^"\\]|\\.)*")'
    for pattern in (rf"\s*{member}\s*,", rf",\s*{member}", rf"\s*{member}\s*"):
        for match in re.finditer(pattern, text):
            candidate = text[:match.start()] + text[match.end():]
            try:
                if json.loads(candidate) == expected:
                    return candidate
            except json.JSONDecodeError:
                continue
    return json.dumps(expected, indent=2) + "\n"


def checked(candidate_text, profile, require_wiki=False, planned=()):
    """A proposed profile's policy, its lesson routing problem kept; a profile the validator rejects is refused."""
    with tempfile.TemporaryDirectory() as temporary:
        candidate = pathlib.Path(temporary) / "profile.md"
        candidate.write_text(candidate_text, encoding="utf-8")
        errors = io.StringIO()
        try:
            with contextlib.redirect_stderr(errors):
                reader.validate(candidate, require_wiki, planned)
        except SystemExit:
            raise ValueError(f"{profile}: {errors.getvalue().strip()}") from None
        policy = compose.load_policy(candidate)
        error = policy.routing_error and policy.routing_error.replace(str(candidate), str(profile))
        return compose.Policy(profile, policy.auto_apply, policy.routing, error)


def validated(candidate_text, profile):
    """Refuse a proposed profile the validator or the policy reader would reject."""
    policy = checked(candidate_text, profile)
    if policy.routing_error:
        raise ValueError(policy.routing_error)
    return policy


def plan(profile, auto_apply=None, keep_routing=None):
    profile = pathlib.Path(profile)
    if not profile.is_file():
        raise ValueError(f"no knowledge profile at {profile}; configure the knowledge profile first")
    original = profile.read_bytes().decode("utf-8")
    current = validated(original, profile)
    config_file = pathlib.Path(handoff.config_path())
    config = handoff.read_config()
    legacy = compose.retired_routing()
    proposed = original
    result = {"profile": str(profile), "auto_apply": {"current": bool(current.auto_apply)},
              "moves": [], "conflicts": [], "removals": [], "manual": [], "notes": []}

    config_text = config_file.read_bytes().decode("utf-8") if RETIRED_SETTING in config else None
    if os.environ.get("HIPPOCAMPUS_ROUTING"):
        result["manual"].append("unset HIPPOCAMPUS_ROUTING in your shell configuration; until then lesson "
                                "routing and auto-apply stay refused")
    if legacy is not None and legacy.exists() and not legacy.is_file():
        result["manual"].append(f"move {legacy} away: it is not a file, so set-up neither reads nor deletes it; "
                                "until then lesson routing and auto-apply stay refused")
    elif legacy is not None and legacy.is_symlink() and not legacy.exists():
        result["removals"].append({"kind": "routing", "file": str(legacy),
                                   "action": "delete the broken link to a retired routing file"})
    elif legacy is not None and legacy.is_file():
        legacy_text = legacy.read_text(encoding="utf-8")
        rebase = legacy.parent.resolve() != profile.parent.resolve()
        routing, deep = moved_routing(legacy_text, legacy.parent, rebase)
        before = effective(legacy_text.splitlines(), legacy.parent, str(legacy))
        same = current.routing is not None and (nonblank(current.routing) == nonblank(routing) or (
            without_paths(current.routing) == without_paths(routing)
            and effective(current.routing, profile.parent, str(profile)) == before))
        if keep_routing == "profile" and current.routing is None:
            raise ValueError(f"--keep-routing profile: {profile} has no {compose.POLICY_HEADING} section to keep; "
                             "nothing written")
        if deep and keep_routing != "profile":
            result["conflicts"].append({
                "setting": "lesson routing headings",
                "owners": [{"file": str(legacy), "headings": deep}],
                "resolve": "these headings cannot move two levels down (Markdown stops at level six); raise "
                           "them in the routing file" + (", or keep the profile's routing with --keep-routing profile"
                                                         if current.routing is not None else "")})
        elif current.routing is not None and not same and keep_routing is None:
            result["conflicts"].append({
                "setting": "lesson routing",
                "owners": [{"file": str(legacy), "text": legacy_text},
                           {"file": f"{profile} {compose.POLICY_HEADING}", "text": "\n".join(current.routing)}],
                "resolve": "choose which routing to keep (--keep-routing file or --keep-routing profile), "
                           "or edit one to match the other"})
        else:
            if current.routing is None or (not same and keep_routing == "file"):
                proposed = with_routing(proposed, routing)
                result["moves"].append({"setting": "lesson routing", "from": str(legacy),
                                        "to": f"{profile} {compose.POLICY_HEADING}"})
            after = effective(validated(proposed, profile).routing or [], profile.parent, str(profile))
            if keep_routing != "profile" and after != before:
                raise ValueError("the moved lesson routing would change its effective destinations; nothing written")
            result["removals"].append({"kind": "routing", "file": str(legacy),
                                       "action": "delete the retired routing file"})
            if rebase:
                result["notes"].append(
                    f"Produced surfaces paths were relative to {legacy.parent}; they are now absolute. Prose "
                    f"destinations relative to the routing file now read relative to {profile.parent}: "
                    "review them in profile_diff before approving.")

    if RETIRED_SETTING in config:
        value = config[RETIRED_SETTING]
        if type(value) is not bool:
            # Not a setting to move, but still a retired owner every reader refuses: show it and remove it.
            result["notes"].append(f"{config_file} {RETIRED_SETTING} holds {json.dumps(value)}, not true or "
                                   f"false: it is removed and not moved; choose the setting with --auto-apply")
        if type(value) is bool and auto_apply is None and current.auto_apply is not None \
                and current.auto_apply != value:
            result["conflicts"].append({
                "setting": "auto-apply",
                "owners": [{"file": str(config_file), "value": value},
                           {"file": f"{profile} auto_apply", "value": current.auto_apply}],
                "resolve": "choose the setting with --auto-apply true or --auto-apply false"})
        else:
            if auto_apply is None and current.auto_apply is None and type(value) is bool:
                auto_apply = value
            result["removals"].append({"kind": "config", "file": str(config_file),
                                       "action": f"remove {RETIRED_SETTING}"})
            result["_config"] = without_setting(config_text, config)
            result["config_diff"] = "".join(difflib.unified_diff(
                config_text.splitlines(keepends=True), result["_config"].splitlines(keepends=True),
                str(config_file), str(config_file)))
            if type(value) is bool:
                result["moves"].append({"setting": "auto-apply", "from": f"{config_file} {RETIRED_SETTING}",
                                        "to": f"{profile} auto_apply"})
    if auto_apply is not None and auto_apply != current.auto_apply:
        proposed = with_setting(proposed, auto_apply)
    result["auto_apply"]["proposed"] = bool(validated(proposed, profile).auto_apply)
    result["profile_diff"] = "".join(difflib.unified_diff(
        original.splitlines(keepends=True), proposed.splitlines(keepends=True), str(profile), str(profile)))
    result["file_states"] = {str(path): state(path)
                             for path in sorted({profile, config_file, *([legacy] if legacy else [])})}
    result["ready"] = not result["conflicts"] and not result["manual"]
    payload = json.dumps({key: value for key, value in result.items() if not key.startswith("_")}, sort_keys=True)
    result["approval_fingerprint"] = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    result["_proposed"] = proposed
    return result


def atomic_write(path, text):
    """Replace a file's content atomically; a symbolic link keeps pointing at its updated target."""
    target = path.resolve()
    mode = target.stat().st_mode & 0o7777 if target.exists() else 0o644
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent, delete=False, newline="")
    try:
        with handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(handle.name, mode)
        os.replace(handle.name, target)
    except BaseException:
        pathlib.Path(handle.name).unlink(missing_ok=True)
        raise


def apply(profile, fingerprint, auto_apply=None, keep_routing=None):
    fresh = plan(profile, auto_apply, keep_routing)
    if fresh["approval_fingerprint"] != fingerprint:
        raise ValueError("the approved policy move changed; rerun plan and approve the new fingerprint")
    if fresh["conflicts"]:
        raise ValueError("resolve the displayed conflict before the policy moves")
    profile = pathlib.Path(profile)
    if fresh["profile_diff"]:
        atomic_write(profile, fresh["_proposed"])
    for removal in fresh["removals"]:
        path = pathlib.Path(removal["file"])
        if removal["kind"] == "config":
            atomic_write(path, fresh["_config"])
        else:
            path.unlink()
    return fresh


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "apply"))
    parser.add_argument("--auto-apply", choices=("true", "false"), help="the auto-apply setting to record")
    parser.add_argument("--keep-routing", choices=("file", "profile"), help="resolve a lesson routing conflict")
    parser.add_argument("--approval-fingerprint", help="fingerprint printed by the approved plan")
    args = parser.parse_args()
    profile = compose.profile_path()  # The one profile every policy reader reads.
    auto_apply = None if args.auto_apply is None else args.auto_apply == "true"
    try:
        if args.command == "plan":
            result = plan(profile, auto_apply, args.keep_routing)
        else:
            if not args.approval_fingerprint:
                parser.error("apply requires --approval-fingerprint from the approved plan")
            result = apply(profile, args.approval_fingerprint, auto_apply, args.keep_routing)
    except (OSError, ValueError, compose.ComposeError) as exc:
        print(f"policy-setup: {exc}", file=sys.stderr)
        return 1
    for key in [key for key in result if key.startswith("_")]:
        result.pop(key)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
