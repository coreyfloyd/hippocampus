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
import hashlib
import json
import os
import pathlib
import re
import stat
import tempfile
from dataclasses import dataclass


CLAUDE_OWNERSHIP_HEADER = b"<!-- hippocampus-rules: generated; do not hand-edit -->"
GENERATED_HEADER_PREFIX = b"<!-- hippocampus-rules: generated from "
OWNERSHIP_HEADER_SUFFIX = b"; do not hand-edit -->"


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
    mode: int | None
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
        destination = destination.resolve(strict=False)
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
    for target in targets:
        for source in target.sources:
            resolved_source = source.resolve(strict=False)
            if resolved_source in seen:
                fail(f"configuration: target {resolved_source} overlaps source {source}")
    return root, targets


def routing_path() -> pathlib.Path:
    configured = os.environ.get("HIPPOCAMPUS_ROUTING")
    if configured:
        return pathlib.Path(os.path.expandvars(configured)).expanduser()
    return pathlib.Path(os.environ.get("XDG_CONFIG_HOME", str(pathlib.Path.home() / ".config"))) / "hippocampus" / "routing.md"


def routing_scalar(value: str) -> str:
    """Read the plain or quoted strings in the routing contract's YAML subset."""
    value = value.strip()
    if value.startswith('"'):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            fail(f"routing: invalid quoted string: {exc}")
    elif value.startswith("'"):
        if len(value) < 2 or not value.endswith("'"):
            fail("routing: unterminated quoted string")
        value = value[1:-1].replace("''", "'")
    if not isinstance(value, str) or not value:
        fail("routing: paths and regeneration commands must be nonempty strings")
    return value


def resolved_routing_path(value: str, directory: pathlib.Path) -> pathlib.Path:
    path = pathlib.Path(os.path.expandvars(value)).expanduser()
    return (path if path.is_absolute() else directory / path).resolve()


def load_surfaces(path: pathlib.Path) -> dict[pathlib.Path, list[dict[str, str]]]:
    """Read a Produced surfaces section, without executing its commands.

    The documented block form uses two spaces for sources, four for list
    entries, and six for regeneration commands. Other routing prose is ignored.
    Malformed entries fail closed rather than silently becoming an empty list.
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        if path.is_symlink():
            fail(f"routing: broken symlink {path}")
        return {}
    except (OSError, UnicodeError) as exc:
        fail(f"routing {path}: {exc}")
    mapping: dict[pathlib.Path, list[dict[str, str]]] = {}
    active = False
    found = False
    source = None
    surface = None
    empty = False
    for line in lines:
        if line.strip() == "Produced surfaces:":
            if found:
                fail("routing: duplicate Produced surfaces section")
            found = active = True
            continue
        if not active or not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith(" "):
            active = False
            continue
        match = re.fullmatch(r"  (.+):(?: *(\[\]))? *", line)
        if match:
            source = resolved_routing_path(routing_scalar(match[1]), path.parent)
            if source in mapping:
                fail(f"routing: duplicate source {source}")
            mapping[source] = []
            empty = match[2] is not None
            surface = None
        elif line.startswith("    - path:") and source is not None and not empty:
            surface = {"path": str(resolved_routing_path(routing_scalar(line[11:]), path.parent))}
            mapping[source].append(surface)
        elif line.startswith("      regeneration command:") and surface is not None:
            if "regeneration command" in surface:
                fail("routing: duplicate regeneration command")
            surface["regeneration command"] = routing_scalar(line.split(":", 1)[1])
        else:
            fail(f"routing {path}: invalid Produced surfaces entry: {line.strip()}")
    for source, surfaces in mapping.items():
        for surface in surfaces:
            if "regeneration command" not in surface:
                fail(f"routing: missing regeneration command for {source}: {surface['path']}")
    return mapping


LESSON_KEYS = ("lesson-policy", "lesson-pull-request-command", "lesson-pull-requests")


def _without_comment(value: str) -> str:
    """Drop a trailing ` # comment` from a scalar; a quoted one keeps the text inside its quotes."""
    value = value.strip()
    quoted = re.match(r'"(?:[^"\\]|\\.)*"|\'(?:[^\']|\'\')*\'', value)
    if quoted:
        rest = value[quoted.end():]
        # Anything after the closing quote other than a comment stays, so routing_scalar refuses it.
        return quoted[0] if not rest.strip() or re.match(r"\s+#", rest) else value
    if value.startswith(('"', "'")):
        return value
    return re.split(r"\s+#", value, maxsplit=1)[0].strip()


def load_lesson_delivery(path: pathlib.Path) -> dict:
    """Read the lesson delivery keys in the routing contract's YAML subset.

    Each key is an unindented `key: value` line outside fenced code blocks;
    `lesson-pull-requests:` takes `- owner/name` entries, indented with spaces or tabs
    or not at all, one per line directly below it. The list ends at the first blank
    line or at the first line that is not an entry, so prose after it is never a
    repository. Prose and fenced examples are ignored. Malformed values, and a line
    in the list that starts like an entry but cannot be read, fail closed, like
    Produced surfaces.
    """
    rules: dict = {"policy": None, "command": None, "pull_requests": []}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        if path.is_symlink():
            fail(f"routing: broken symlink {path}")
        return rules
    except (OSError, UnicodeError) as exc:
        fail(f"routing {path}: {exc}")
    fenced = False
    listing = False
    seen: set = set()
    for line in lines:
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
            listing = False
            continue
        if fenced:
            continue
        if not line.strip() or line.lstrip().startswith("#"):
            listing = False
            continue
        if listing and line.lstrip().startswith("-"):
            entry = re.fullmatch(r"\s*-\s+(.+)", line)
            if not entry:
                fail(f"routing {path}: invalid lesson-pull-requests entry: {line.strip()}")
            rules["pull_requests"].append(routing_scalar(_without_comment(entry[1])).lower())
            continue
        listing = False
        if line[0] in " \t":
            continue
        key, separator, value = line.partition(":")
        if not separator or key not in LESSON_KEYS:
            continue
        if key in seen:
            fail(f"routing {path}: duplicate {key}")
        seen.add(key)
        value = _without_comment(value)
        if key == "lesson-pull-requests":
            if value:
                fail(f"routing {path}: lesson-pull-requests takes `- owner/name` lines, not a value")
            listing = True
        elif key == "lesson-policy":
            if value not in ("apply", "propose"):
                fail(f"routing {path}: lesson-policy must be apply or propose")
            rules["policy"] = value
        else:
            rules["command"] = routing_scalar(value)
    return rules


def surfaces_for(path: pathlib.Path, routing: pathlib.Path) -> dict:
    mapping = load_surfaces(routing)
    requested = resolved_routing_path(str(path), pathlib.Path.cwd())
    # Reverse lookup comes first: even a mapped source may itself be generated.
    sources = [source for source, surfaces in mapping.items()
               if any(surface["path"] == str(requested) for surface in surfaces)]
    if not sources:
        sources = [requested]
    surfaces = []
    for source in sources:
        for surface in mapping.get(source, []):
            if surface not in surfaces:
                surfaces.append(surface)
    return {"sources": [str(source) for source in sources], "surfaces": surfaces}


def read_source(path: pathlib.Path) -> bytes:
    try:
        if not path.is_file():
            fail(f"source document is missing or unreadable: {path}")
        content = path.read_bytes()
        if any(is_block_delimiter(line.rstrip(b"\r\n")) for line in content.splitlines()):
            fail(f"source document {path}: contains a managed block delimiter line")
        return content
    except OSError as exc:
        fail(f"source document is missing or unreadable: {path}: {exc}")


def ownership_header(sources: list[pathlib.Path], generated: bool) -> bytes:
    if not generated:
        return CLAUDE_OWNERSHIP_HEADER + b"\n"
    names = json.dumps(
        [str(source) for source in sources], ensure_ascii=True, separators=(",", ":")
    )
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
    if not first_line:
        return False
    header = first_line[0].rstrip(b"\r\n")
    if header == CLAUDE_OWNERSHIP_HEADER:
        return True
    if not (header.startswith(GENERATED_HEADER_PREFIX) and header.endswith(OWNERSHIP_HEADER_SUFFIX)):
        return False
    encoded_sources = header[len(GENERATED_HEADER_PREFIX):-len(OWNERSHIP_HEADER_SUFFIX)]
    try:
        sources = json.loads(encoded_sources.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    if not isinstance(sources, list) or not sources:
        return False
    if not all(isinstance(source, str) and os.path.isabs(source) for source in sources):
        return False
    return ownership_header([pathlib.Path(source) for source in sources], generated=True).rstrip(b"\n") == header


def block_markers(path: pathlib.Path) -> tuple[bytes, bytes]:
    digest = hashlib.sha256(os.fsencode(str(path))).hexdigest().encode()
    return (
        b"<!-- hippocampus-rules:block:start " + digest + b" -->",
        b"<!-- hippocampus-rules:block:end " + digest + b" -->",
    )


def is_block_delimiter(line: bytes) -> bool:
    # Recognize the reserved delimiter syntax broadly so variants cannot hide
    # beside the one fixed pair that this target is allowed to contain.
    return line.endswith(b" -->") and line.startswith((
        b"<!-- hippocampus-rules:block:start ",
        b"<!-- hippocampus-rules:block:end ",
    ))


def parse_user_block(existing: bytes, replacement: bytes, path: pathlib.Path) -> bytes:
    start_marker, end_marker = block_markers(path)
    markers: list[tuple[bytes, int, int]] = []
    offset = 0
    for line in existing.splitlines(keepends=True):
        normalized = line.rstrip(b"\r\n")
        if is_block_delimiter(normalized):
            markers.append((normalized, offset, offset + len(line)))
        offset += len(line)
    if not markers:
        return existing + (b"" if not existing or existing.endswith(b"\n") else b"\n") + start_marker + b"\n" + replacement + end_marker + b"\n"
    if len(markers) != 2 or markers[0][0] != start_marker or markers[1][0] != end_marker:
        fail(f"malformed marked block in target {path}: expected exactly one fixed start marker followed by one fixed end marker")
    return existing[:markers[0][2]] + replacement + existing[markers[1][1]:]


def preflight_target(target: Target, allow_missing_parents: bool = False, *, read_only: bool = False) -> tuple[bytes | None, int | None]:
    original = None
    mode = None
    try:
        if target.path.exists() and target.path.is_dir():
            action = "read" if read_only else "written"
            fail(f"target cannot be {action}: {target.path} is a directory")
        if target.path.exists():
            if not read_only and not os.access(target.path, os.W_OK):
                fail(f"target cannot be written: {target.path} (file is not writable)")
            original = target.path.read_bytes()
            mode = stat.S_IMODE(target.path.stat().st_mode)
    except OSError as exc:
        fail(f"target cannot be read: {target.path}: {exc}")
    if read_only:
        return original, mode
    parent = target.path.parent
    if allow_missing_parents:
        while not parent.exists():
            parent = parent.parent
    if not parent.is_dir() or not os.access(parent, os.W_OK | os.X_OK):
        fail(f"target cannot be written: {target.path} (parent is unavailable or not writable)")
    return original, mode


def plan(targets: list[Target], allow_missing_parents: bool = False, *, read_only: bool = False) -> list[PlannedWrite]:
    source_cache: dict[pathlib.Path, bytes] = {}
    plans: list[PlannedWrite] = []
    for target in targets:
        source_bytes = []
        for source in target.sources:
            if source not in source_cache:
                source_cache[source] = read_source(source)
            source_bytes.append(source_cache[source])
        original, mode = preflight_target(target, allow_missing_parents, read_only=read_only)
        replacement = target_content(target, source_bytes)
        owned = original is None or has_ownership_header(original)
        desired = replacement if owned else parse_user_block(original, replacement, target.path)
        plans.append(PlannedWrite(target, original, mode, desired, "composer-owned" if owned else "user-owned"))
    return plans


def stage(plans: list[PlannedWrite]) -> list[tuple[PlannedWrite, pathlib.Path]]:
    staged: list[tuple[PlannedWrite, pathlib.Path]] = []
    try:
        for item in plans:
            if item.original == item.desired:
                continue
            descriptor, temporary = tempfile.mkstemp(prefix=".hippocampus-rules-", dir=item.target.path.parent)
            with os.fdopen(descriptor, "wb") as handle:
                if item.mode is None:
                    current_umask = os.umask(0)
                    os.umask(current_umask)
                    os.fchmod(handle.fileno(), 0o666 & ~current_umask)
                else:
                    os.fchmod(handle.fileno(), item.mode)
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
        failed_target = item.target.path
        for item in reversed(replaced):
            if item.original is None:
                item.target.path.unlink(missing_ok=True)
            else:
                descriptor, rollback = tempfile.mkstemp(prefix=".hippocampus-rules-rollback-", dir=item.target.path.parent)
                with os.fdopen(descriptor, "wb") as handle:
                    os.fchmod(handle.fileno(), item.mode)
                    handle.write(item.original)
                os.replace(rollback, item.target.path)
        fail(f"target cannot be written: {failed_target}: {exc}")
    finally:
        for _, temporary in staged:
            temporary.unlink(missing_ok=True)


def compose(config_path: pathlib.Path, check: bool = False) -> None:
    _, targets = load_config(config_path)
    plans = plan(targets, read_only=check)
    if check:
        drift = [str(item.target.path) for item in plans if item.original != item.desired]
        if drift:
            fail("drift in rule targets:\n" + "\n".join(drift))
        return
    for item in plans:
        print(f"{item.ownership}: {item.target.path}")
    write_all(plans)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("compose", "refresh", "check", "surfaces"), nargs="?", default="compose")
    parser.add_argument("--config", type=pathlib.Path, help="JSON file listing explicit rule targets")
    parser.add_argument("--routing", type=pathlib.Path, help="Produced surfaces routing file")
    parser.add_argument("--source", type=pathlib.Path, help="source or generated surface to trace")
    args = parser.parse_args()
    if args.command == "surfaces" and args.source is None:
        parser.error("surfaces requires --source")
    if args.command != "surfaces" and args.config is None:
        parser.error(f"{args.command} requires --config")
    try:
        if args.command == "surfaces":
            print(json.dumps(surfaces_for(args.source, args.routing or routing_path())))
        else:
            compose(args.config, check=args.command == "check")
    except ComposeError as exc:
        print(f"compose-rules: {exc}", file=os.sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
