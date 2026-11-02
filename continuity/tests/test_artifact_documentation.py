"""Published examples round-trip through the commands that own their formats."""
from datetime import datetime
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "docs/examples"
HANDOFF = ROOT / "scripts/lib/handoff.py"
CHECKLIST = ROOT / "scripts/lib/checklist.py"


def sandbox_env(tmp_path):
    env = dict(os.environ)
    for key in ("CODEX_THREAD_ID", "CLAUDE_SESSION_ID", "CLAUDE_CODE_SESSION_ID",
                "CLAUDE_CODE_ENTRYPOINT", "CONTINUITY_HARNESS", "HANDOFF_FILE"):
        env.pop(key, None)
    env.update(HANDOFF_STATE_DIR=str(tmp_path / "handoffs"),
               HANDOFF_LEDGER_DIR=str(tmp_path / "ledger"),
               CHECKLIST_STATE_DIR=str(tmp_path / "checklist"),
               CONTINUITY_CONFIG=str(EXAMPLES / "config.json"))
    return env


def command(module, *args, env, input=None):
    result = subprocess.run([sys.executable, str(module), *map(str, args)],
                            input=input, text=True, capture_output=True, env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


@pytest.fixture
def captured_outputs(tmp_path):
    """Repeat the provenance capture, including the committed-then-edited file."""
    env = sandbox_env(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
    # The capture used main; do not depend on the host's init.defaultBranch.
    subprocess.run(["git", "-C", str(repo), "symbolic-ref", "HEAD", "refs/heads/main"],
                   check=True, capture_output=True)
    readme = repo / "README.md"
    readme.write_text("Artifact capture sandbox.\n")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"],
                   check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=Example",
                    "-c", "user.email=example@example.invalid", "-c", "commit.gpgsign=false",
                    "commit", "-qm", "Initialize capture sandbox"],
                   check=True, capture_output=True)
    readme.write_text(readme.read_text() + "Capture in progress.\n")
    command(HANDOFF, "ledger-file", "README.md", "--cwd", repo,
            "--session-id", "example-session", env=env)
    command(HANDOFF, "ledger-artifact", "--location", "https://example.invalid/review",
            "--disposition", "keep", "--cwd", repo, "--session-id", "example-session", env=env)
    continuation = {
        "resume": {
            "headline": "Artifact examples captured; validation remains.",
            "next_action": "Validate the examples against their engines.",
            "session_summary": "Registered the changed sandbox file and a pending review artifact.",
            "open_loops": [],
        },
        "spawned_processes": [],
        "suggested_skills": ["checklist"],
    }
    command(HANDOFF, "checkpoint", "--cwd", repo, "--session-id", "example-session",
            env=env, input=json.dumps(continuation))
    handoff_path = Path(command(HANDOFF, "resolve", repo, "--session-id", "example-session",
                                env=env).strip())
    command(CHECKLIST, "plan", "--user-profile", EXAMPLES / "profile.md",
            "--handoff", handoff_path, "--session-id", "example-session", env=env)
    ledger = [json.loads(line) for line in
              (tmp_path / "ledger/session-touched-paths.example-session.jsonl").read_text().splitlines()]
    return repo.resolve(), json.loads(handoff_path.read_text()), ledger


def normalize_capture(value, repo, key=None):
    """Keep complete structure and semantics; redact only capture paths and times."""
    if isinstance(value, dict):
        return {field: normalize_capture(item, repo, field) for field, item in value.items()}
    if isinstance(value, list):
        return [normalize_capture(item, repo) for item in value]
    if key in ("written_at", "produced_at", "ts"):
        assert isinstance(value, str)
        assert datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is not None
        return "<capture-time>"
    if isinstance(value, str):
        prefix = str(repo)
        if value == prefix or value.startswith(prefix + "/"):
            return "/workspace/example-repo" + value[len(prefix):]
    return value


def test_handoff_example_round_trips_through_checkpoint(tmp_path, captured_outputs):
    assert "lint-handoff: clean" in command(
        HANDOFF, "lint", EXAMPLES / "handoff.json", env=sandbox_env(tmp_path))
    repo, actual, _ = captured_outputs
    expected = json.loads((EXAMPLES / "handoff.json").read_text())
    # The commit includes creation time, so its hash varies between fresh captures.
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                          check=True, text=True, capture_output=True).stdout.strip()
    assert actual["git"]["head"] == head
    assert re.fullmatch(r"[0-9a-f]{40}", expected["git"]["head"])
    actual["git"]["head"] = expected["git"]["head"]
    assert normalize_capture(actual, repo) == normalize_capture(expected, repo)


def test_profile_loads_and_plan_recomposes(tmp_path):
    spec = importlib.util.spec_from_file_location("example_checklist", CHECKLIST)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    profile = EXAMPLES / "profile.md"
    assert profile.read_bytes() == (ROOT / "tests/fixtures/profiles/user.md").read_bytes()
    module.compose([module.load_profile(profile)])
    actual = json.loads(command(CHECKLIST, "plan", "--user-profile", profile,
                                "--handoff", EXAMPLES / "handoff.json",
                                "--session-id", "example-session", env=sandbox_env(tmp_path)))
    actual["profiles"] = ["docs/examples/profile.md"]
    assert actual == json.loads((EXAMPLES / "plan.json").read_text())


def test_ledger_example_round_trips_complete_rows(captured_outputs):
    repo, _, generated = captured_outputs
    examples = [json.loads(line) for line in (EXAMPLES / "ledger.jsonl").read_text().splitlines()]
    assert normalize_capture(generated, repo) == normalize_capture(examples, repo)


def test_configuration_example_is_read_by_config_get(tmp_path):
    config = json.loads((EXAMPLES / "config.json").read_text())
    assert config
    for key, value in config.items():
        output = command(HANDOFF, "config-get", key, env=sandbox_env(tmp_path)).strip()
        assert output == ("\n".join(value) if isinstance(value, list) else str(value))


def test_storage_artifacts_have_readme_outlines_and_examples_have_links():
    readme = (ROOT / "README.md").read_text()
    assert "## What the package writes" in readme
    section = readme.split("## What the package writes", 1)[1].split("\n## ", 1)[0]
    storage = (ROOT / "INTERFACE.md").read_text().split("## 1. Storage", 1)[1].split("## 2.", 1)[0]
    # The separator row does not match; skip only the column header.
    rows = re.findall(r"^\| ([^|]+) \|", storage, re.M)[1:]
    for artifact in rows:
        title = artifact.strip().split(" (", 1)[0]
        assert f"### {title}" in section
    for title in ("Checklist plan", "Checklist report input", "Session summary", "Configuration file", "Profile file"):
        assert f"### {title}" in section
    for path in EXAMPLES.iterdir():
        if path.is_file():
            assert f"(docs/examples/{path.name})" in readme, path.name
