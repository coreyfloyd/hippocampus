"""Regression coverage for public skill content checks."""
import subprocess
import sys
from pathlib import Path


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
