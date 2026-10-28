#!/usr/bin/env python3
"""Compose tool instruction files from a knowledge root's rule documents.

The configuration is JSON so installers and set-up can supply only the targets
they have already approved.  For example:

{
  "knowledge_root": "/path/to/knowledge",
  "targets": [
    {
      "tool": "claude",
      "scope": "user",
      "file": "/path/to/instructions",
      "sources": ["context/rules.md"],
      "extras": ["/path/to/tool-mechanics.md"]
    }
  ]
}

Relative source paths are relative to ``knowledge_root``. Target paths are
explicit absolute paths. ``compose`` and ``refresh`` deliberately perform the
same operation: refresh is the stable entry point for synchronizers.
"""

import argparse
import json
import os
import pathlib
import tempfile
from dataclasses import dataclass


OWNERSHIP_PREFIX = b"<!-- hippocampus-rules:"
BLOCK_START = b"<!-- hippocampus-rules:start -->"
BLOCK_END = b"<!-- hippocampus-rules:end -->"


class ComposeError(Exception):
    """A preflight failure that must leave every target untouched."""


@dataclass
class Target:
    tool: str
    scope: str
    path: pathlib.Path
    sources: list[pathlib.Path]


@dataclass
class PlannedWrite:
    target: Target
    original: bytes | None
    desired: bytes
    ownership: str


def fail(message: str) -> None:
    raise ComposeError(message)


def load_config(path: pathlib.Path) -> tuple[pathlib.Path, list[Target]]:
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        fail(f"configuration {path}: {exc}")
    if not isinstance(config, dict):
        fail(f"configuration {path}: expected an object")

    root_value = config.get("knowledge_root")
    if not isinstance(root_value, str) or not root_value:
        fail("configuration: knowledge_root must be a nonempty path")
    root = pathlib.Path(root_value).expanduser()
    if not root.is_absolute():
        fail("configuration: knowledge_root must be an absolute path")
    if not root.is_dir() or not os.access(root, os.R_OK | os.X_OK):
        fail(f"knowledge root unavailable: {root}")

    target_values = config.get("targets")
    if not isinstance(target_values, list) or not target_values:
        fail("configuration: targets must be a nonempty list")
    targets: list[Target] = []
    seen: set[pathlib.Path] = set()
    for index, value in enumerate(target_values, start=1):
        label = f"target {index}"
        if not isinstance(value, dict):
            fail(f"configuration: {label} must be an object")
        tool = value.get("tool")
        if tool not in {"claude", "codex", "openclaw"}:
            fail(f"configuration: {label} has unsupported tool {tool!r}")
        scope = value.get("scope", "user")
        if not isinstance(scope, str) or not scope:
            fail(f"configuration: {label} scope must be a nonempty string")
        file_value = value.get("file")
        if not isinstance(file_value, str) or not file_value:
            fail(f"configuration: {label} file must be a nonempty path")
        destination = pathlib.Path(file_value).expanduser()
        if not destination.is_absolute():
            fail(f"configuration: {label} file must be an absolute path")
        destination = destination.absolute()
        if destination in seen:
            fail(f"configuration: duplicate target {destination}")
        seen.add(destination)

        source_values = value.get("sources")
        if not isinstance(source_values, list) or not source_values:
            fail(f"configuration: {label} sources must be a nonempty list")
        extra_values = value.get("extras", [])
        if not isinstance(extra_values, list):
            fail(f"configuration: {label} extras must be a list")
        sources: list[pathlib.Path] = []
        for source_value in [*source_values, *extra_values]:
            if not isinstance(source_value, str) or not source_value:
                fail(f"configuration: {label} source must be a nonempty path")
            source = pathlib.Path(source_value).expanduser()
            if not source.is_absolute():
                source = root / source
            sources.append(source.absolute())
        targets.append(Target(tool=tool, scope=scope, path=destination, sources=sources))
    return root, targets


def read_source(path: pathlib.Path) -> bytes:
    try:
        if not path.is_file():
            fail(f"source document is missing or unreadable: {path}")
        return path.read_bytes()
    except OSError as exc:
        fail(f"source document is missing or unreadable: {path}: {exc}")


def ownership_header(sources: list[pathlib.Path], generated: bool) -> bytes:
    if not generated:
        return b"<!-- hippocampus-rules: generated; do not hand-edit -->\n"
    names = ", ".join(str(source) for source in sources)
    return f"<!-- hippocampus-rules: generated from {names}; do not hand-edit -->\n".encode()


def with_final_newline(content: bytes) -> bytes:
    return content if not content or content.endswith(b"\n") else content + b"\n"


def target_content(target: Target, source_bytes: list[bytes]) -> bytes:
    if target.tool == "claude":
        imports = b"".join(f"@{source}\n".encode() for source in target.sources)
        return ownership_header(target.sources, generated=False) + imports
    body = b"".join(with_final_newline(content) for content in source_bytes)
    return ownership_header(target.sources, generated=True) + body


def has_ownership_header(content: bytes) -> bool:
    first_line = content.splitlines(keepends=True)[:1]
    return bool(first_line and first_line[0].startswith(OWNERSHIP_PREFIX)
                and first_line[0].rstrip(b"\r\n").endswith(b"; do not hand-edit -->"))


def parse_user_block(existing: bytes, replacement: bytes, path: pathlib.Path) -> bytes:
    starts = existing.count(BLOCK_START)
    ends = existing.count(BLOCK_END)
    if starts == 0 and ends == 0:
        return existing + (b"" if not existing or existing.endswith(b"\n") else b"\n") + BLOCK_START + b"\n" + replacement + BLOCK_END + b"\n"
    if starts != 1 or ends != 1:
        fail(f"malformed marked block in target {path}: expected exactly one start and one end marker")
    start = existing.index(BLOCK_START)
    end = existing.index(BLOCK_END)
    if end < start:
        fail(f"malformed marked block in target {path}: end marker precedes start marker")
    line_end = existing.find(b"\n", start)
    if line_end == -1:
        fail(f"malformed marked block in target {path}: start marker must end a line")
    return existing[: start] + BLOCK_START + b"\n" + replacement + BLOCK_END + existing[end + len(BLOCK_END) :]


def preflight_target(target: Target) -> bytes | None:
    try:
        if target.path.exists() and target.path.is_dir():
            fail(f"target cannot be written: {target.path} is a directory")
        if target.path.exists():
            return target.path.read_bytes()
    except OSError as exc:
        fail(f"target cannot be read: {target.path}: {exc}")
    parent = target.path.parent
    if not parent.is_dir() or not os.access(parent, os.W_OK | os.X_OK):
        fail(f"target cannot be written: {target.path} (parent is unavailable or not writable)")
    return None


def plan(targets: list[Target]) -> list[PlannedWrite]:
    source_cache: dict[pathlib.Path, bytes] = {}
    plans: list[PlannedWrite] = []
    for target in targets:
        source_bytes = []
        for source in target.sources:
            if source not in source_cache:
                source_cache[source] = read_source(source)
            source_bytes.append(source_cache[source])
        original = preflight_target(target)
        replacement = target_content(target, source_bytes)
        owned = original is None or has_ownership_header(original)
        desired = replacement if owned else parse_user_block(original, replacement, target.path)
        plans.append(PlannedWrite(target, original, desired, "composer-owned" if owned else "user-owned"))
    return plans


def stage(plans: list[PlannedWrite]) -> list[tuple[PlannedWrite, pathlib.Path]]:
    staged: list[tuple[PlannedWrite, pathlib.Path]] = []
    try:
        for item in plans:
            if item.original == item.desired:
                continue
            descriptor, temporary = tempfile.mkstemp(prefix=".hippocampus-rules-", dir=item.target.path.parent)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(item.desired)
                handle.flush()
                os.fsync(handle.fileno())
            staged.append((item, pathlib.Path(temporary)))
        return staged
    except OSError as exc:
        fail(f"target cannot be written: {item.target.path}: {exc}")
    finally:
        if len(staged) != sum(item.original != item.desired for item in plans):
            for _, temporary in staged:
                temporary.unlink(missing_ok=True)


def write_all(plans: list[PlannedWrite]) -> None:
    staged = stage(plans)
    replaced: list[PlannedWrite] = []
    try:
        for item, temporary in staged:
            os.replace(temporary, item.target.path)
            replaced.append(item)
    except OSError as exc:
        for item in reversed(replaced):
            if item.original is None:
                item.target.path.unlink(missing_ok=True)
            else:
                descriptor, rollback = tempfile.mkstemp(prefix=".hippocampus-rules-rollback-", dir=item.target.path.parent)
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(item.original)
                os.replace(rollback, item.target.path)
        fail(f"target cannot be written: {item.target.path}: {exc}")
    finally:
        for _, temporary in staged:
            temporary.unlink(missing_ok=True)


def compose(config_path: pathlib.Path) -> None:
    _, targets = load_config(config_path)
    plans = plan(targets)
    for item in plans:
        print(f"{item.ownership}: {item.target.path}")
    write_all(plans)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("compose", "refresh"), nargs="?", default="compose")
    parser.add_argument("--config", required=True, type=pathlib.Path, help="JSON file listing explicit rule targets")
    args = parser.parse_args()
    try:
        compose(args.config)
    except ComposeError as exc:
        print(f"compose-rules: {exc}", file=os.sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
