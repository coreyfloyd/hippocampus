"""Install and verify warn about retired lesson settings and keep their exit status."""
import json
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def env(tmp_path):
    """A test-owned home whose configuration sits under XDG_CONFIG_HOME, as a user's does."""
    environment = {key: value for key, value in os.environ.items()
                   if key not in ("HIPPOCAMPUS_CONFIG", "HIPPOCAMPUS_ROUTING")}
    environment.update(HOME=str(tmp_path / "home"), XDG_CONFIG_HOME=str(tmp_path / "config"),
                       CLAUDE_CONFIG_DIR=str(tmp_path / "home/.claude"), CODEX_HOME=str(tmp_path / "home/.codex"),
                       HANDOFF_STATE_DIR=str(tmp_path / "handoffs"), HANDOFF_LEDGER_DIR=str(tmp_path / "ledger"))
    (tmp_path / "home").mkdir()
    (tmp_path / "config/hippocampus").mkdir(parents=True)
    return environment


def install(env, *args):
    return subprocess.run(["bash", str(ROOT / "install.sh"), *args], env=env, capture_output=True, text=True)


def warnings(result):
    return [line for line in result.stderr.splitlines() if line.startswith("warning: ")]


def test_retired_settings_warn_once_each_and_keep_exit_zero(env):
    config = Path(env["XDG_CONFIG_HOME"]) / "hippocampus"
    (config / "config.json").write_text(json.dumps({"auto_apply_lessons": True}))
    (config / "routing.md").write_text("| Lesson | Destination |\n")
    for args in ((), ("--verify-runtime",)):
        result = install(env, *args)
        assert result.returncode == 0, result.stderr
        setting, routing = warnings(result)
        assert str(config / "config.json") in setting and "auto_apply frontmatter" in setting
        assert str(config / "routing.md") in routing and "## Lesson routing" in routing
        assert all("hippocampus-set-up" in line for line in (setting, routing))


def test_a_migrated_configuration_prints_no_warning(env):
    config = Path(env["XDG_CONFIG_HOME"]) / "hippocampus"
    (config / "config.json").write_text("{}")
    (config / "profile.md").write_text("---\nauto_apply: true\n---\n\n## Lesson routing\n\n| Lesson | Destination |\n")
    for args in ((), ("--verify-runtime",)):
        result = install(env, *args)
        assert result.returncode == 0, result.stderr
        assert warnings(result) == []
