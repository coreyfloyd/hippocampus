"""Exercise release prerequisite policy through real pytest subprocesses."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("missing_tool", ["gpg", "gpgconf"])
def test_missing_gnupg_fails_release_check_but_skips_contributor_suite(missing_tool):
    # Control prerequisite lookups without depending on installed GnuPG tools.
    script = """
import shutil
import sys
import pytest
original_which = shutil.which
shutil.which = lambda command, *args, **kwargs: (
    None if command == sys.argv[1] else (
        sys.executable if command in ("gpg", "gpgconf")
        else original_which(command, *args, **kwargs)
    )
)
raise SystemExit(pytest.main([
    'tests/test_release.py::test_committed_key_is_the_published_hippocampus_release_key',
    '-q', '-rs', '--tb=short',
]))
"""
    env = dict(os.environ, CONTINUITY_RELEASE_CHECK="1")
    required = subprocess.run(
        [sys.executable, "-c", script, missing_tool], cwd=ROOT,
        env=env, text=True, capture_output=True,
    )
    output = required.stdout + required.stderr
    assert required.returncode == 1, output
    assert f"{missing_tool} is not installed" in output
    assert "1 skipped" not in output

    env.pop("CONTINUITY_RELEASE_CHECK")
    optional = subprocess.run(
        [sys.executable, "-c", script, missing_tool], cwd=ROOT,
        env=env, text=True, capture_output=True,
    )
    output = optional.stdout + optional.stderr
    assert optional.returncode == 0, output
    assert "1 skipped" in output
    assert f"{missing_tool} is not installed" in output


def test_candidate_runbook_requires_release_check():
    candidate = (ROOT / "RELEASING.md").read_text().split(
        "## Verify the candidate\n", 1,
    )[1].split("\n## ", 1)[0]
    assert "CONTINUITY_RELEASE_CHECK=1 python3 -m pytest tests" in candidate
