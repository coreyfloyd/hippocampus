"""Run the documented optional session check with a controlled command."""
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "tests/fixtures/open-session-ids.txt"
COMMAND_PLACEHOLDER = "REPLACE_WITH_SESSION_COMMAND"
ARGUMENT_PLACEHOLDER = "REPLACE_WITH_ARGUMENT"


def documented_check(argument="active sessions"):
    document = (ROOT / "docs/sweep.md").read_text(encoding="utf-8")
    examples = re.findall(r"```json\n(.*?)\n```", document, re.S)
    checks = [check for example in examples
              for check in json.loads(example).get("sweep", {}).get("open_session_checks", [])]
    assert len(checks) == 1, "document one copyable session check"
    assert COMMAND_PLACEHOLDER in checks[0], "document a command the user must replace"
    argv = shlex.split(checks[0])
    assert argv[:2] == ["python3", "-c"], "check must run without a shell"
    argv = [part.replace(COMMAND_PLACEHOLDER, "session-tool")
            .replace(ARGUMENT_PLACEHOLDER, argument) for part in argv]
    return [sys.executable, *argv[1:]]


@pytest.mark.parametrize("available", [True, False], ids=["recorded-sessions", "missing-command"])
@pytest.mark.parametrize("argument", ["list", "active sessions"])
def test_documented_open_session_check(tmp_path, available, argument):
    if available:
        executable = tmp_path / "session-tool"
        executable.write_text('#!/bin/sh\n[ "$#" = 1 ] && [ "$1" = "$EXPECTED_ARGUMENT" ] || exit 2\n/bin/cat "$SESSION_SAMPLE"\n')
        executable.chmod(0o755)
    result = subprocess.run(documented_check(argument), capture_output=True, text=True,
                            env={**os.environ, "PATH": str(tmp_path), "SESSION_SAMPLE": str(SAMPLE),
                                 "EXPECTED_ARGUMENT": argument})
    if available:
        assert result.returncode == 0, result.stderr
        assert result.stdout.splitlines() == SAMPLE.read_text().splitlines()
    else:
        assert result.returncode == 1
        assert result.stdout == ""
        assert "FileNotFoundError" in result.stderr
