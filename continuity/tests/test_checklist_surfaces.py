"""The checklist's candidate detector carries no standing surface of its own (#1709)."""
import json
import os
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "checklist-surfaces.sh")


def make_repo(path, profile=False):
    os.makedirs(path)
    subprocess.run(["git", "init", "-q", path], check=True)
    if profile:
        os.makedirs(os.path.join(path, ".claude"))
        with open(os.path.join(path, ".claude", "checklist-profile.md"), "w") as handle:
            handle.write("profile\n")
    else:
        with open(os.path.join(path, "dirty.txt"), "w") as handle:
            handle.write("change\n")


def run(cwd, home, config=None):
    env = dict(os.environ, HOME=str(home), CONTINUITY_CONFIG=str(config or home / "absent.json"))
    result = subprocess.run(["bash", SCRIPT], cwd=cwd, env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    return result.stdout.splitlines()


def test_unconfigured_detector_reports_only_the_session_repository(tmp_path):
    home = tmp_path / "home"
    elsewhere = tmp_path / "elsewhere"
    make_repo(str(home / "Development" / "tool"), profile=True)
    make_repo(str(elsewhere))
    os.makedirs(home / "Obsidian")
    assert run(str(elsewhere), home) == []
    own = str(home / "Development" / "tool")
    assert run(own, home) == [f"discovered\t{own}/.claude/checklist-profile.md"]


def test_configured_standing_surfaces_and_baselines_are_candidates(tmp_path):
    home = tmp_path / "home"
    standing = home / "standing"
    own = tmp_path / "own"
    make_repo(str(standing), profile=True)
    make_repo(str(own))
    baselines = home / "baselines"
    os.makedirs(baselines)
    (baselines / "own.yaml").write_text("suite: x\n")
    config = home / "config.json"
    config.write_text(json.dumps({"checklist_surfaces": ["~/standing"],
                                  "checklist_suite_baselines_dir": "~/baselines"}))
    assert run(str(own), home, config) == [
        f"code\t{os.path.realpath(own)}",
        f"discovered\t{os.path.realpath(standing)}/.claude/checklist-profile.md",
    ]


def test_filing_through_checkpoint_wrap_and_report_in_both_modes(tmp_path):
    """The written handoff, not just the in-memory outcome, gates completion."""
    import sys

    engine = os.path.join(ROOT, "scripts", "lib", "checklist.py")
    writer = os.path.join(ROOT, "scripts", "lib", "handoff.py")
    config = tmp_path / "config.json"
    config.write_text("{}")
    env = dict(os.environ, CONTINUITY_CONFIG=str(config), CLAUDE_CODE_ENTRYPOINT="cli",
               HANDOFF_LEDGER_DIR=str(tmp_path / "ledger"), CHECKLIST_STATE_DIR=str(tmp_path / "state"),
               HANDOFF_STATE_DIR=str(tmp_path / "handoffs"))

    def invoke(script, *args, payload=None):
        return subprocess.run([sys.executable, script, *args], input=payload,
                              env=env, text=True, capture_output=True)

    for unattended in [False, True]:
        for bound, status, expected in [(True, "filed", 0), (True, "failed", 1), (False, "pending", 0)]:
            profile = tmp_path / "profile.json"
            profile.write_text(json.dumps({"name": "test", "bindings": {"lessons": None},
                                           **({"ask": {"command": "/ask"}} if bound else {})}))
            common = ["--user-profile", str(profile)]
            mode = ["--unattended"] if unattended else []
            source = tmp_path / "source.json"
            source.write_text(json.dumps({"subject": {"session_id": "producer", "working_directory": str(tmp_path)},
                "resume": {"headline": "wrap", "open_loops": [{"type": "decision", "context": "Approve document change",
                    "session_id": "producer", "produced_at": "2026-10-23T12:00:00Z", "author": "user",
                    "location": "https://example.test/spec", "anchor": {"ticket": "https://example.test/ticket"},
                    "disposition": "carry"}]}}))
            outcomes = tmp_path / "outcomes.json"
            outcomes.write_text(json.dumps([{"index": 0, "rule": "R3", "status": status, "destination": "ask receipt",
                                              "choices": ["approve", "decline"], "error": "ask store refused write"}]))
            filed = invoke(engine, "file", *common, *mode, "--handoff", str(source), "--filing", str(outcomes))
            assert filed.returncode == 0, filed.stderr
            data = json.loads(filed.stdout)
            assert data["filing"]["items"][0]["ask"]["ticket"] == "https://example.test/ticket"
            checkpoint = invoke(writer, "checkpoint", "--cwd", str(tmp_path), "--session-id", "producer",
                                "--trigger", "wrap", payload=filed.stdout)
            assert checkpoint.returncode == 0, checkpoint.stderr
            # Locate the actual writer's output via its configured path, rather than a mock.
            paths = list((tmp_path / "handoffs").rglob("*.json"))
            assert len(paths) == 1, paths
            written = paths[0]
            wrap = invoke(engine, "wrap-check", *common, *mode, "--written-handoff", str(written))
            assert wrap.returncode == expected, wrap.stderr
            if expected:
                assert "Approve document change" in wrap.stderr
                assert "ask store refused write" in wrap.stderr
            elif not bound:
                assert "missing ask binding" in wrap.stderr
                assert "Approve document change" in json.loads(written.read_text())["resume"]["next_action"]
            else:
                assert json.loads(written.read_text())["resume"]["next_action"] == "Session finished."
            results = tmp_path / "results.json"
            results.write_text(json.dumps([{"id": step, "status": "run", "writes": []}
                for step in ["record", "knowledge", "lessons", "persist", "handoff"]]))
            report = invoke(engine, "report", *common, *mode, "--handoff", str(written), "--results", str(results))
            assert report.returncode == expected, report.stderr
            if not expected:
                assert json.loads(report.stdout)["filing"]["items"][0]["rule"] == "R3"
