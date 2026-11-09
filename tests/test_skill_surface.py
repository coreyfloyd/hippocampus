"""Regression coverage for public skill content checks."""
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
CHECK = ROOT / "scripts" / "check-skill-surface.py"


def run_check(path):
    return subprocess.run(
        [sys.executable, CHECK, path], capture_output=True, text=True
    )


def write_skill(root, text):
    path = root / "skills" / "sample" / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text(text)
    return path


def test_rejects_personal_and_unavailable_references(tmp_path):
    path = write_skill(
        tmp_path,
        """# Sample

Keep the rule after an incident on 2026-10-01.
Run /hippocampus:record-update before reporting.
Check a subagent with `TaskList`.
See #123 for the original report.
""",
    )

    result = run_check(tmp_path / "skills")

    assert result.returncode == 1
    assert result.stdout.splitlines() == [
        f"{path}:3: dated incident note",
        f"{path}:4: unshipped skill: record-update",
        f"{path}:5: unavailable adapter tool: TaskList",
        f"{path}:6: internal ticket reference: #123",
    ]


def test_accepts_source_citations_examples_and_qualified_adapter_tools(tmp_path):
    write_skill(
        tmp_path,
        """# Sample

Sources checked 2026-10-01.
Read `2026-10-01-example.md`.
In Claude Code, use `TaskList`; in Codex, use `collaboration.list_agents`.
Run /hippocampus:pickup before reporting.
""",
    )
    pickup = tmp_path / "skills" / "pickup" / "SKILL.md"
    pickup.parent.mkdir()
    pickup.write_text("---\nname: pickup\n---\n")

    result = run_check(tmp_path / "skills")

    assert result.returncode == 0, result.stdout + result.stderr


def test_scans_skills_reached_through_an_installed_link(tmp_path):
    source = tmp_path / "source"
    write_skill(source, "Rule recorded after 2026-10-01.\n")
    installed = tmp_path / "installed" / "skills"
    installed.mkdir(parents=True)
    (installed / "sample").symlink_to(source / "skills" / "sample")

    result = run_check(installed)

    assert result.returncode == 1
    assert result.stdout.splitlines() == [
        f"{installed / 'sample' / 'SKILL.md'}:1: dated incident note",
    ]


@pytest.mark.parametrize("invocation", [
    "/record-update", "/hippocampus:record-update", "/other:record-update",
    "/other:sample", "/unknown_command", "/missing.", "/missing:", "/Missing",
])
@pytest.mark.parametrize("template", [
    "Run {} before reporting.\n", "Use `{} argument`.\n",
    "```text\n{}\n```\n", "# Run {} before reporting.\n",
    "Run **{}** before reporting.\n", "Run ({}).\n",
])
def test_rejects_unshipped_slash_commands(tmp_path, invocation, template):
    path = write_skill(tmp_path, template.format(invocation))

    result = run_check(tmp_path / "skills")

    assert result.returncode == 1
    assert str(path) in result.stdout
    assert "unshipped skill:" in result.stdout


@pytest.mark.parametrize("text", [
    "Run /sample or /hippocampus:sample.\n",
    "Claude Code's `/doctor prompt-audit` checks prompts.\n",
    "Use /clear, /compact, /help, /init, /resume, or /status.\n",
    "Read `/example/path.md`, `relative/path`, and `https://example.com/help`.\n",
    'Use {"command": "/<user-bound-skill>"}.\n',
    "```python\nvalue = Path(base)/path\n```\n",
    "Environment prefixes include CLIENT_*/OTHER_*.\n",
])
def test_accepts_shipped_commands_builtins_and_paths(tmp_path, text):
    write_skill(tmp_path, text)

    result = run_check(tmp_path / "skills")

    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("fence", ["```", "~~~", "````"])
@pytest.mark.parametrize("comment", [
    "# 2026-08-30: a resumed session reported stale status.",
    "// 2026-08-30: a resumed session reported stale status.",
    "/* Incident on 2026-08-30 caused stale status. */",
    "<!-- 2026-08-30: a resumed session reported stale status. -->",
    "# `2026-08-30: a resumed session reported stale status.`",
    "# Checked the status; 2026-08-30: a resumed session failed.",
])
def test_rejects_dated_incidents_in_fenced_comments(tmp_path, fence, comment):
    path = write_skill(tmp_path, f"{fence}text\n{comment}\n{fence}\n")

    result = run_check(tmp_path / "skills")

    assert result.returncode == 1
    assert result.stdout == f"{path}:2: dated incident note\n"


@pytest.mark.parametrize("example", [
    '# Sources checked 2026-10-01.',
    '# Read `2026-10-01-example.md`.',
    'date = "2026-10-01"',
    '{"produced_at": "2026-10-01T00:00:00Z"}',
    'date: 2026-10-01',
    'Read https://example.com/2026-10-01/report.',
])
@pytest.mark.parametrize("fence", ["```", "~~~"])
def test_accepts_sample_dates_and_citations_in_fences(tmp_path, example, fence):
    write_skill(tmp_path, f"{fence}text\n{example}\n{fence}\n")

    result = run_check(tmp_path / "skills")

    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("text, expected", [
    ("# 2026-08-30: a resumed session reported stale status.\n", 1),
    ('date = "2026-08-30"\n', 0),
    ("# Run /record-update before reporting.\n", 1),
    ("# Run /sample before reporting.\n", 0),
])
def test_scans_skill_code_comments_and_literals(tmp_path, text, expected):
    skill = write_skill(tmp_path, "# Sample\n")
    script = skill.parent / "helper.py"
    script.write_text(text)

    result = run_check(tmp_path / "skills")

    assert result.returncode == expected, result.stdout + result.stderr
    if expected:
        assert f"{script}:1:" in result.stdout


@pytest.mark.parametrize("text, tool", [
    ("In Claude Code use TaskList; in Codex use TaskGet.", "TaskGet"),
    ("In Claude Code use TaskList. In Codex use TaskGet.", "TaskGet"),
    ("In Claude Code, use TaskList, while in Codex, use TaskGet.", "TaskGet"),
    ("Claude Code: TaskList; Codex: BashOutput.", "BashOutput"),
    ("Use TaskList in Claude Code and TaskGet in Codex.", "TaskGet"),
    ("TaskList (Claude Code), TaskOutput (Codex).", "TaskOutput"),
    ("In Codex use collaboration.list_agents; in Claude Code use functions.write_stdin.", "functions.write_stdin"),
    ("In Codex use functions.write_stdin, whereas Claude Code uses collaboration.list_agents.", "collaboration.list_agents"),
    ("In Claude Code use TaskList; in Codex use TaskList.", "TaskList"),
    ("In Claude Code use TaskList — in Codex use TaskGet.", "TaskGet"),
    ("Claude Code: TaskList | Codex: TaskGet.", "TaskGet"),
    ("In Codex and Claude Code use TaskList.", "TaskList"),
    ("In Claude Code and Codex use collaboration.list_agents.", "collaboration.list_agents"),
])
def test_attributes_each_adapter_tool_to_its_clause(tmp_path, text, tool):
    path = write_skill(tmp_path, text + "\n")

    result = run_check(tmp_path / "skills")

    assert result.returncode == 1
    assert f"{path}:1: unavailable adapter tool: {tool}" in result.stdout


@pytest.mark.parametrize("text", [
    "In Claude Code use TaskList; in Codex use collaboration.list_agents.",
    "In Claude Code use TaskList. In Codex use functions.write_stdin.",
    "In Claude Code, use TaskList, while in Codex, use collaboration.list_agents.",
    "Claude Code: TaskList; Codex: functions.write_stdin.",
    "Use TaskList in Claude Code and functions.write_stdin in Codex.",
    "TaskList (Claude Code), collaboration.list_agents (Codex).",
    "In Claude Code use TaskList — in Codex use functions.write_stdin.",
    "Claude Code: TaskList | Codex: functions.write_stdin.",
    "In Claude Code use TaskList and TaskGet; in Codex use functions.write_stdin.",
    "In Codex use functions.write_stdin, whereas Claude Code uses BashOutput.",
])
def test_accepts_adapter_tools_in_their_own_client_clauses(tmp_path, text):
    write_skill(tmp_path, text + "\n")

    result = run_check(tmp_path / "skills")

    assert result.returncode == 0, result.stdout + result.stderr


def make_git_repository(root):
    subprocess.run(["git", "init", "-q", root], check=True, capture_output=True)


@pytest.mark.parametrize("text, expected", [
    ("# 2026-08-30: a resumed session reported stale status.\n", 1),
    ("Run /record-update.\n", 1), ("See #123.\n", 1),
    ("Sources checked 2026-10-01; run /sample.\n", 0),
])
def test_scans_tracked_nested_directory_links(tmp_path, text, expected):
    make_git_repository(tmp_path)
    skill = write_skill(tmp_path, "# Sample\n")
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "notes.md").write_text(text)
    link = skill.parent / "references"
    link.symlink_to(shared, target_is_directory=True)
    subprocess.run(["git", "-C", tmp_path, "add", "skills", "shared"], check=True)

    result = run_check(tmp_path / "skills")

    assert result.returncode == expected, result.stdout + result.stderr
    if expected:
        assert f"{link / 'notes.md'}:1:" in result.stdout


def test_does_not_follow_untracked_build_directory_links(tmp_path):
    make_git_repository(tmp_path)
    skill = write_skill(tmp_path, "# Sample\n")
    shared = tmp_path / "build-output"
    shared.mkdir()
    (shared / "notes.md").write_text("Run /record-update.\n")
    build = skill.parent / ".build"
    build.mkdir()
    (build / "debug").symlink_to(shared, target_is_directory=True)
    subprocess.run(["git", "-C", tmp_path, "add", str(skill)], check=True)

    result = run_check(tmp_path / "skills")

    assert result.returncode == 0, result.stdout + result.stderr


def test_scans_nested_links_in_exported_skills_without_looping(tmp_path):
    skill = write_skill(tmp_path, "# Sample\n")
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "notes.md").write_text("Run /record-update.\n")
    (shared / "cycle").symlink_to(skill.parent, target_is_directory=True)
    link = skill.parent / "references"
    link.symlink_to(shared, target_is_directory=True)

    result = run_check(tmp_path / "skills")

    assert result.returncode == 1
    assert result.stdout.count("unshipped skill: record-update") == 1
