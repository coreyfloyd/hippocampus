"""Install and verify warn once about each retired lesson setting and keep their exit status."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
WARNED = "HIPPOCAMPUS_RETIRED_SETTINGS_WARNED"


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A test-owned home whose configuration sits under XDG_CONFIG_HOME, as a user's does."""
    for key in ("HIPPOCAMPUS_CONFIG", "HIPPOCAMPUS_ROUTING", WARNED):
        monkeypatch.setenv(key, "")
        monkeypatch.delenv(key)  # restored to the caller's state at teardown
    for key, value in (("HOME", "home"), ("XDG_CONFIG_HOME", "config"), ("CLAUDE_CONFIG_DIR", "home/.claude"),
                       ("CODEX_HOME", "home/.codex"), ("HANDOFF_STATE_DIR", "handoffs"),
                       ("HANDOFF_LEDGER_DIR", "ledger")):
        monkeypatch.setenv(key, str(tmp_path / value))
    (tmp_path / "home").mkdir()
    (tmp_path / "config/hippocampus").mkdir(parents=True)
    return dict(os.environ)


def config(env):
    return Path(env["XDG_CONFIG_HOME"]) / "hippocampus"


def retire(env):
    (config(env) / "config.json").write_text(json.dumps({"auto_apply_lessons": True}))
    (config(env) / "routing.md").write_text("| Lesson | Destination |\n")


def install(env, *args):
    return subprocess.run(["bash", str(ROOT / "install.sh"), *args], env=env, capture_output=True, text=True)


def warnings(stderr):
    return [line for line in stderr.splitlines() if line.startswith("warning: ")]


def assert_one_per_setting(env, stderr):
    lines = warnings(stderr)
    setting = [line for line in lines if "auto_apply_lessons" in line]
    routing = [line for line in lines if "## Lesson routing" in line]
    assert len(lines) == 2 and len(setting) == 1 and len(routing) == 1, stderr
    assert str(config(env) / "config.json") in setting[0] and "auto_apply in the knowledge profile's frontmatter" in setting[0]
    assert str(config(env) / "routing.md") in routing[0]
    assert all("hippocampus-set-up" in line for line in lines)


def test_each_install_flow_warns_once_per_retired_setting_and_exits_zero(env):
    retire(env)
    for args in ((), ("--verify-runtime",)):
        result = install(env, *args)
        assert result.returncode == 0, result.stderr
        assert_one_per_setting(env, result.stderr)
    # A helper that already warned passes the marker to the install.sh it runs.
    result = install(dict(env, **{WARNED: "1"}), "--verify-runtime")
    assert result.returncode == 0 and warnings(result.stderr) == []


def test_verify_warns_and_keeps_its_exit_status_without_a_profile(env):
    install(env)
    baseline = install(env, "--verify")
    assert baseline.returncode != 0 and "profile missing" in baseline.stderr
    retire(env)
    result = install(env, "--verify")
    assert result.returncode == baseline.returncode
    assert_one_per_setting(env, result.stderr)


def test_a_migrated_configuration_prints_no_warning(env):
    (config(env) / "config.json").write_text("{}")
    (config(env) / "profile.md").write_text("---\nauto_apply: true\n---\n\n## Lesson routing\n\n| Lesson | Destination |\n")
    for args in ((), ("--verify-runtime",)):
        result = install(env, *args)
        assert result.returncode == 0, result.stderr
        assert warnings(result.stderr) == []


def test_an_exported_routing_variable_warns_with_its_unset_step(env):
    result = install(dict(env, HIPPOCAMPUS_ROUTING=str(config(env) / "gone.md")))
    assert result.returncode == 0, result.stderr
    [line] = warnings(result.stderr)
    assert "unset HIPPOCAMPUS_ROUTING" in line and str(config(env) / "gone.md") in line and "hippocampus-set-up" in line


def test_a_malformed_configuration_is_named_and_the_check_skipped(env):
    (config(env) / "config.json").write_text('{"auto_apply_lessons": true,}')
    result = install(env)
    assert result.returncode == 0, result.stderr
    [line] = warnings(result.stderr)
    assert str(config(env) / "config.json") in line and "config unreadable; retired-settings check skipped" in line


def test_an_unreadable_routing_path_never_fails_the_install(env, tmp_path):
    locked = tmp_path / "locked"
    locked.mkdir()
    (locked / "routing.md").write_text("x")
    locked.chmod(0)
    try:
        result = install(dict(env, HIPPOCAMPUS_ROUTING=str(locked / "routing.md")))
    finally:
        locked.chmod(0o755)
    assert result.returncode == 0, result.stderr
    assert "Traceback" not in result.stderr and len(warnings(result.stderr)) == 1, result.stderr


def test_a_failing_check_prints_one_skipped_line(env, monkeypatch, capsys):
    sys.path.insert(0, str(ROOT / "scripts"))
    from lib import lessons
    compose = lessons._compose_rules()

    def unreadable():
        raise PermissionError("routing.md: permission denied")
    monkeypatch.setattr(compose, "retired_routing", unreadable)
    lessons.warn_retired()
    assert warnings(capsys.readouterr().err) == [
        "warning: retired-settings check skipped: routing.md: permission denied"]


def test_the_claude_helper_alone_warns_once_and_not_on_uninstall(env, tmp_path):
    retire(env)
    cli = tmp_path / "claude"
    cli.write_text("#!/bin/sh\nexit 0\n")
    cli.chmod(0o755)
    for operation, expected in (([], 2), (["--uninstall"], 0)):
        result = subprocess.run([sys.executable, str(ROOT / "scripts/install-claude.py"), "--claude", str(cli),
                                 *operation], env=env, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        if expected:
            assert_one_per_setting(env, result.stderr)
        else:
            assert warnings(result.stderr) == []


def test_the_codex_helper_alone_warns_once_and_not_on_uninstall(env, monkeypatch, capfd):
    subprocess.run(["bash", str(ROOT / "install.sh")], env=env, check=True, capture_output=True)
    retire(env)
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("retired_codex", ROOT / "scripts/install-codex.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.trust, "verify_with_hooks_list", lambda *args: None)
    home = env["CODEX_HOME"]
    # Adopting runs install.sh --verify-runtime, which must not repeat the helper's warning.
    for operation, expected in (([], 2), (["--uninstall"], 0)):
        monkeypatch.delenv(WARNED, raising=False)
        monkeypatch.setattr(sys, "argv", ["install", "--codex-home", home, "--codex", "codex", *operation])
        assert module.main() == 0
        stderr = capfd.readouterr().err
        if expected:
            assert_one_per_setting(env, stderr)
        else:
            assert warnings(stderr) == []
