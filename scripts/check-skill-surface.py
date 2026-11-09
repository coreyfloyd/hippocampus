#!/usr/bin/env python3
"""Reject private history and unavailable package references in shipped skills."""
import argparse
import re
import subprocess
import sys
from pathlib import Path


DATE = re.compile(r"20\d{2}-\d{2}-\d{2}")
TICKET = re.compile(r"(?<![\w/])#\d+")
# A slash command starts a token; paths, URLs and division are not invocations.
SKILL = re.compile(
    r"(?<![^\s`\"'(\[{])(?:\*{1,2})?/([A-Za-z][A-Za-z0-9_-]*(?::[A-Za-z][A-Za-z0-9_-]*)?)"
    r"(?![\w/-]|:[\w]|\.[\w])"
)
# Client built-ins, rather than package skills (Claude Code / Codex CLI docs).
BUILTIN_COMMANDS = {"clear", "compact", "doctor", "help", "init", "resume", "status"}
ADAPTER_TOOLS = {
    "TaskList": "Claude Code",
    "TaskGet": "Claude Code",
    "TaskOutput": "Claude Code",
    "BashOutput": "Claude Code",
    "run_in_background": "Claude Code",
    "collaboration.list_agents": "Codex",
    "functions.write_stdin": "Codex",
}

CLIENT = re.compile(r"\b(?:Claude Code|Codex)\b", re.IGNORECASE)
CLAUSE_BREAK = re.compile(
    r"(;|[.!?]\s+|,|[—–|]|\s-\s|\b(?:and|while|whereas|but|instead of|rather than)\b)",
    re.IGNORECASE,
)
TOOL = re.compile(
    r"(?<![\w.])(?:" + "|".join(map(re.escape, ADAPTER_TOOLS)) + r")(?![\w]|\.[\w])"
)


def unavailable_adapter_tools(line):
    clients = set()
    pending_subjects = False
    separator = ""
    for index, clause in enumerate(CLAUSE_BREAK.split(line)):
        if index % 2:
            separator = clause.strip().lower()
            if separator in {";", ".", "!", "?", "—", "–", "|", "-"}:
                clients = set()
                pending_subjects = False
            continue
        named = {match.group().lower() for match in CLIENT.finditer(clause)}
        tools = list(TOOL.finditer(clause))
        if named:
            # A shared subject ("Codex and Claude Code") applies to both clients.
            clients = clients | named if separator == "and" and pending_subjects else named
        for match in tools:
            tool = match.group()
            if clients != {ADAPTER_TOOLS[tool].lower()}:
                yield tool
        if tools:
            pending_subjects = False
        elif named:
            pending_subjects = True


def skill_contents(root, ancestors=frozenset()):
    real = root.resolve()
    if real in ancestors:
        return
    ancestors = ancestors | {real}
    for path in sorted(root.iterdir()):
        if path.is_dir():
            if path.is_symlink():
                # In a checkout only tracked links ship. Exported installations
                # have no Git index, so follow their links with cycle protection.
                tracked = subprocess.run(
                    ["git", "-C", str(path.parent), "ls-files", "--error-unmatch", "--", path.name],
                    capture_output=True, text=True,
                )
                if tracked.returncode == 1:
                    continue
                if tracked.returncode and "not a git repository" not in tracked.stderr:
                    raise OSError(tracked.stderr.strip())
            yield from skill_contents(path, ancestors)
        elif path.is_file():
            yield path


def skill_files(paths):
    for root in paths:
        if root.is_file():
            yield root
        elif (root / "SKILL.md").is_file():
            yield from skill_contents(root)
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


def date_is_allowed(line, match):
    before, after = line[:match.start()], line[match.end():]
    if re.search(r"\bchecked\s*$", before, re.IGNORECASE):
        return True
    if re.search(r"https?://\S*$", before):
        return True
    # A date within a file name is sample data, even in a comment.
    if re.match(r"[-\w]*\.[a-zA-Z0-9]+", after):
        return True
    # Permit exact date/timestamp literals, not narrative hidden in inline code.
    for literal in re.finditer(r"([`\"'])([^`\"']*)\1", line):
        if literal.start(2) == match.start() and re.fullmatch(
            r"20\d{2}-\d{2}-\d{2}(?:T[0-9:.+Z-]+)?", literal.group(2)
        ):
            return True
    return bool(re.fullmatch(
        r"\s*(?:-\s+)?[\w-]+:\s*20\d{2}-\d{2}-\d{2}(?:T[0-9:.+Z-]+)?\s*",
        line,
    ))


def findings(paths):
    skills = available_skills(paths)
    rows = []
    for path in skill_files(paths):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(lines, start=1):
            for match in DATE.finditer(line):
                if not date_is_allowed(line, match):
                    rows.append((path, number, "dated incident note"))
            for match in TICKET.finditer(line):
                own = f"coreyfloyd/hippocampus{match.group()}"
                if own not in line:
                    rows.append((path, number, f"internal ticket reference: {match.group()}"))
            for match in SKILL.finditer(line):
                command = match.group(1)
                name = command.removeprefix("hippocampus:")
                if name not in skills and command not in BUILTIN_COMMANDS:
                    rows.append((path, number, f"unshipped skill: {name}"))
            for tool in unavailable_adapter_tools(line):
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
