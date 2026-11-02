"""Public documentation stays tied to the shipped contract, including archives."""
import json
from pathlib import Path
import re
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
NUMBER_WORDS = dict(zip("zero one two three four five six seven eight nine ten eleven twelve".split(), range(13)))


def text(path):
    path = {'README.md': 'docs/session-guide.md', 'INSTALLATION.md': 'docs/session-installation.md',
            'docs/architecture/runtime.architecture.json': 'docs/architecture/session/runtime.architecture.json'}.get(path, path)
    return (ROOT / path).read_text(encoding="utf-8")


def table_rows(document, heading):
    section = document.split(heading, 1)[1].split("\n## ", 1)[0]
    return [line for line in section.splitlines() if line.startswith("| `")]


@pytest.mark.parametrize("path,heading", [("README.md", "## Skills"), ("INTERFACE.md", "## 7. Skills")])
def test_skill_tables_and_all_skill_counts_match_directories(path, heading):
    skills = {p.name for p in (ROOT / "skills").iterdir() if p.is_dir()}
    document = text(path)
    rows = table_rows(document, heading)
    listed = {re.match(r"\| `([^`]+)`", row).group(1) for row in rows}
    assert listed == skills
    counts = re.findall(r"\b(\d+|" + "|".join(NUMBER_WORDS) + r") (?:hippocampus )?skill(?:s| links| directories)\b", document, re.I)
    assert counts, f"{path}: state the installed skill count"
    for count in counts:
        value = int(count) if count.isdigit() else NUMBER_WORDS[count.lower()]
        assert value == len(skills), (path, count, len(skills))
    if path == "README.md":
        for skill in skills:
            row = next(row for row in rows if row.startswith(f"| `{skill}` |"))
            assert f"/hippocampus:{skill}" in row


def test_installation_owns_commands_and_fixed_contract_facts():
    readme, guide = text("README.md"), text("INSTALLATION.md")
    assert "[INSTALLATION.md](session-installation.md)" in readme
    for command in ("claude plugin install hippocampus --marketplace coreyfloyd/hippocampus",
                    "python3 scripts/install-codex.py"):
        assert command in guide
        assert command not in readme
    storage = text("INTERFACE.md").split("## 1. Storage", 1)[1].split("## 2. Configuration", 1)[0]
    defaults = re.findall(r"`(~/.local/state/hippocampus/[^`]+)`", storage)
    for default in defaults:
        assert default in guide
    assert "parent of the handoff directory" in guide
    assert text("RELEASE_SIGNING_FINGERPRINT").strip() in guide
    keys = re.findall(r"^\| `([^`]+)` \| ([^|]+) \|", text("INTERFACE.md").split("## 2. Configuration", 1)[1].split("## 3.", 1)[0], re.M)
    for key, kind in keys:
        assert re.search(r"^\| `" + re.escape(key) + r"` \| " + re.escape(kind.strip()) + r" \|", guide, re.M)


def test_readme_hook_inventory_matches_registration():
    hooks = json.loads(text("hooks/hooks.json"))["hooks"]
    commands = [handler["command"] for groups in hooks.values() for group in groups for handler in group["hooks"]]
    section = text("README.md").split("## Hooks", 1)[1].split("\n## ", 1)[0]
    assert len(commands) == len(table_rows(text("README.md"), "## Hooks"))
    assert f"{len(commands)} hippocampus hooks" in section
    for command in commands:
        path = re.search(r"\$\{CLAUDE_PLUGIN_ROOT\}/([^\"]+)", command).group(1)
        assert f"`{path}`" in section


def architecture():
    return json.loads(text("docs/architecture/runtime.architecture.json"))


def has_source_history():
    """A staged snapshot has files, but not its original repository history."""
    probe = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--show-toplevel"],
                           capture_output=True, text=True)
    return False  # Imported architecture cites the pinned source repository, not this repository history.


def test_architecture_citations_exist_at_the_pinned_revision():
    candidate = architecture()
    revision = candidate["meta"]["repository"]["revision"]
    assert re.fullmatch(r"[0-9a-f]{40}", revision)
    assert candidate["meta"]["repository"] == {
        "url": "https://github.com/coreyfloyd/continuity.git", "provider": "github",
        "link_mode": "web", "revision": revision}
    assert (ROOT / "docs/architecture/session/runtime.html").is_file()
    in_git = has_source_history()
    for component in candidate["components"]:
        assert component.get("sources") or component["type"] == "external", component["id"]
        for source in component.get("sources", []):
            path = source["path"]
            assert not Path(path).is_absolute() and ".." not in Path(path).parts
            assert (ROOT / path).is_file(), path
            content = text(path)
            if in_git:
                result = subprocess.run(["git", "-C", str(ROOT), "show", f"{revision}:{path}"], text=True, capture_output=True)
                assert result.returncode == 0, result.stderr
                content = result.stdout
            start = source["line"]
            assert 1 <= start <= source.get("end_line", start) <= len(content.splitlines()), source


def test_architecture_revision_is_an_ancestor():
    if not has_source_history():
        pytest.skip("extracted or staged snapshot has no source git history")
    revision = architecture()["meta"]["repository"]["revision"]
    result = subprocess.run(["git", "-C", str(ROOT), "merge-base", "--is-ancestor", revision, "HEAD"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr or f"{revision} is not an ancestor of HEAD"
