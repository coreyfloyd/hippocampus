"""Run the documented optional session check without requiring Herdr."""
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "tests/fixtures/herdr-pane-list.json"


def documented_check():
    document = (ROOT / "docs/sweep.md").read_text(encoding="utf-8")
    examples = re.findall(r"```json\n(.*?)\n```", document, re.S)
    checks = [check for example in examples
              for check in json.loads(example).get("sweep", {}).get("open_session_checks", [])]
    assert len(checks) == 1, "document one copyable Herdr check"
    argv = shlex.split(checks[0])
    assert argv[:2] == ["python3", "-c"], "check must run without a shell"
    return [sys.executable, *argv[1:]]


@pytest.mark.parametrize("available", [True, False], ids=["recorded-panes", "missing-herdr"])
def test_documented_herdr_check(tmp_path, available):
    if available:
        executable = tmp_path / "herdr"
        executable.write_text('#!/bin/sh\n[ "$*" = "pane list" ] || exit 2\n/bin/cat "$HERDR_SAMPLE"\n')
        executable.chmod(0o755)
    result = subprocess.run(documented_check(), capture_output=True, text=True,
                            env={**os.environ, "PATH": str(tmp_path), "HERDR_SAMPLE": str(SAMPLE)})
    if available:
        assert result.returncode == 0, result.stderr
        assert result.stdout.splitlines() == [
            "00000000-0000-4000-8000-000000000001",
            "00000000-0000-4000-8000-000000000002",
            "00000000-0000-4000-8000-000000000003",
            "00000000-0000-4000-8000-000000000004",
            "00000000-0000-4000-8000-000000000005",  # A done pane is still open.
        ]
    else:
        assert result.returncode == 1
        assert result.stdout == ""
        assert "FileNotFoundError" in result.stderr
