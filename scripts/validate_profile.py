#!/usr/bin/env python3
"""Validate the minimal versioned Hippocampus profile schema."""
import pathlib
import sys

TOP_LEVEL_FIELDS = {
    "profile_version", "knowledge_root", "hot_file", "operation_log_file",
    "decision_log_file", "wiki_followup_destination", "artifact_followup_destination",
    "wiki_enabled",
}


def fail(message):
    print(f"profile invalid: {message}", file=sys.stderr)
    raise SystemExit(1)


def parse(path):
    lines = path.read_text().splitlines()
    if not lines or lines[0] != "---":
        fail("missing YAML frontmatter")
    values = {}
    for line in lines[1:]:
        if line == "---":
            return values
        if not line:
            continue
        if line.startswith("#"):
            continue
        if line.startswith(" "):
            fail("nested profile fields are not supported")
        if ":" not in line:
            fail("invalid profile field")
        key, value = line.split(":", 1)
        key = key.strip()
        if key not in TOP_LEVEL_FIELDS:
            fail(f"unsupported profile field: {key}")
        if key in values:
            fail(f"duplicate profile field: {key}")
        values[key] = value.strip()
    fail("unterminated YAML frontmatter")


def contained(root, candidate, label):
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        fail(f"{label} escapes knowledge_root")
    if not resolved.is_dir():
        fail(f"{label} is not an existing directory")
    return resolved


def contained_file(root, value, label):
    if not value:
        fail(f"missing {label}")
    candidate = pathlib.Path(value)
    if candidate.is_absolute():
        fail(f"{label} must be relative to knowledge_root")
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        fail(f"{label} escapes knowledge_root")
    if not resolved.is_file():
        fail(f"{label} is not an existing file")
    return resolved


def main():
    args = sys.argv[1:]
    require_wiki = "--require-wiki" in args
    args = [a for a in args if a != "--require-wiki"]
    if len(args) != 1:
        fail("usage: validate_profile.py PROFILE [--require-wiki]")
    values = parse(pathlib.Path(args[0]))
    if values.get("profile_version") != "4":
        fail("profile_version must be 4")
    root_value = values.get("knowledge_root")
    if not root_value or not pathlib.Path(root_value).is_absolute():
        fail("knowledge_root must be an absolute path")
    root = pathlib.Path(root_value).resolve()
    if not root.is_dir():
        fail("knowledge_root is not an existing directory")

    wiki_value = values.get("wiki_enabled")
    if wiki_value is not None and wiki_value not in ("true", "false"):
        fail("wiki_enabled must be true or false")
    wiki_enabled = wiki_value != "false"

    # Checks common to both wiki states run first, so a profile missing more
    # than one canonical directory or file may report a different offender
    # than a pre-#12 profile would have (message ordering only; a single
    # defect still fails with the same message either way).
    for key in ("raw", "output", "docs"):
        contained(root, root / key, key)
    for key in ("operation_log_file", "decision_log_file"):
        contained_file(root, values.get(key), key)
    if not values.get("artifact_followup_destination"):
        fail("missing artifact_followup_destination")

    if wiki_enabled:
        contained(root, root / "wiki", "wiki")
        contained_file(root, values.get("hot_file"), "hot_file")
        if not values.get("wiki_followup_destination"):
            fail("missing wiki_followup_destination")
    else:
        # Check presence, not truthiness: a wiki-only key whose value was
        # emptied (e.g. a bare `hot_file:` line left behind by an edit) is
        # still the key being present, and must still fail as a
        # contradiction rather than being silently treated as absent.
        for key in ("hot_file", "wiki_followup_destination"):
            if key in values:
                fail(f"{key} must be absent when wiki_enabled is false")
        if require_wiki:
            fail(
                "wiki is not configured; run hippocampus-set-up to enable it"
            )

    print(root)


if __name__ == "__main__":
    main()
