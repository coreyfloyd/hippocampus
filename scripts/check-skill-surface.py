#!/usr/bin/env python3
"""Reject private history and unavailable package references in shipped skills."""
import argparse
import re
import sys
from pathlib import Path


DATE = re.compile(r"20\d{2}-\d{2}-\d{2}")
TICKET = re.compile(r"(?<![\w/])#\d+")
SKILL = re.compile(r"/hippocampus:([a-z0-9-]+)")
ADAPTER_TOOLS = {
    "TaskList": "Claude Code",
    "TaskGet": "Claude Code",
    "TaskOutput": "Claude Code",
    "BashOutput": "Claude Code",
    "run_in_background": "Claude Code",
    "collaboration.list_agents": "Codex",
    "functions.write_stdin": "Codex",
}


def skill_files(paths):
    for root in paths:
        if root.is_file():
            yield root
        elif (root / "SKILL.md").is_file():
            yield from sorted(path for path in root.rglob("*") if path.is_file())
        else:
            for skill in sorted(root.iterdir()):
                if (skill / "SKILL.md").is_file():
                    yield from skill_files([skill])


def available_skills(paths):
    return {
        path.parent.name
        for root in paths
        for path in skill_files([root])
        if path.name == "SKILL.md"
    }


def inline_code(line, index):
    return line[:index].count("`") % 2 == 1


def date_is_allowed(line, match, in_fence):
    if in_fence or inline_code(line, match.start()):
        return True
    before = line[:match.start()].lower()
    if "checked" in before:
        return True
    return bool(re.search(r"https?://\S*$", line[:match.start()]))


def findings(paths):
    skills = available_skills(paths)
    rows = []
    for path in skill_files(paths):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        in_fence = False
        for number, line in enumerate(lines, start=1):
            if line.lstrip().startswith("```"):
                in_fence = not in_fence
            for match in DATE.finditer(line):
                if not date_is_allowed(line, match, in_fence):
                    rows.append((path, number, "dated incident note"))
            for match in TICKET.finditer(line):
                own = f"coreyfloyd/hippocampus{match.group()}"
                if own not in line:
                    rows.append((path, number, f"internal ticket reference: {match.group()}"))
            for match in SKILL.finditer(line):
                name = match.group(1)
                if name not in skills:
                    rows.append((path, number, f"unshipped skill: {name}"))
            for tool, adapter in ADAPTER_TOOLS.items():
                if tool in line and adapter.lower() not in line.lower():
                    rows.append((path, number, f"unavailable adapter tool: {tool}"))
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args(argv)
    missing = [str(path) for path in args.paths if not path.exists()]
    if missing:
        parser.error("missing path: " + ", ".join(missing))
    rows = findings(args.paths)
    for path, number, reason in rows:
        print(f"{path}:{number}: {reason}")
    return 1 if rows else 0


if __name__ == "__main__":
    sys.exit(main())
