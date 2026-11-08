"""The public-content guard keeps portable and caller-supplied checks separate."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


def run_contract_guard(tmp_path, *, readme_line, denylist=None):
    worktree = tmp_path / "candidate"
    subprocess.run(["git", "-C", str(ROOT), "worktree", "add", "--detach", str(worktree), "HEAD"], check=True)
    try:
        shutil.copy2(ROOT / "tests/test-contracts.sh", worktree / "tests/test-contracts.sh")
        readme = worktree / "README.md"
        readme.write_text(readme.read_text(encoding="utf-8") + f"\n{readme_line}\n", encoding="utf-8")
        environment = os.environ.copy()
        environment.pop("PUBLIC_CONTENT_DENYLIST", None)
        if denylist is not None:
            environment["PUBLIC_CONTENT_DENYLIST"] = str(denylist)
        return subprocess.run(["bash", "tests/test-contracts.sh"], cwd=worktree,
                              env=environment, capture_output=True, text=True)
    finally:
        subprocess.run(["git", "-C", str(ROOT), "worktree", "remove", "--force", str(worktree)], check=True)


def test_configured_denylist_rejects_matching_tracked_content(tmp_path):
    denylist = tmp_path / "release-denylist.txt"
    denylist.write_text("restricted-fixture-token\n", encoding="utf-8")
    result = run_contract_guard(tmp_path, readme_line="restricted-fixture-token", denylist=denylist)
    assert result.returncode != 0
    assert "configured denylist" in result.stderr


def test_unavailable_configured_denylist_fails_closed(tmp_path):
    result = run_contract_guard(tmp_path, readme_line="ordinary fixture", denylist=tmp_path / "missing-denylist.txt")
    assert result.returncode != 0
    assert "configured denylist" in result.stderr


def test_default_guard_rejects_machine_specific_path(tmp_path):
    result = run_contract_guard(tmp_path, readme_line="/home/fixture-user")
    assert result.returncode != 0
    assert "machine-specific paths or hostnames" in result.stderr


@pytest.mark.parametrize("line", [
    "fixture-host.local",
    "host: fixture-host.local running",
    "connect to https://fixture-host.local:8443/health",
    "(build.box-2.local)",
    "FIXTURE-HOST.LOCAL",
])
def test_default_guard_rejects_local_hostname(tmp_path, line):
    result = run_contract_guard(tmp_path, readme_line=line)
    assert result.returncode != 0
    assert "machine-specific paths or hostnames: leaked" in result.stderr
    assert line in result.stderr


@pytest.mark.parametrize("line", [
    "ordinary fixture", "fixture-host.locality", "local settings",
])
def test_default_guard_accepts_clean_content(tmp_path, line):
    result = run_contract_guard(tmp_path, readme_line=line)
    assert result.returncode == 0, result.stdout + result.stderr
