"""What the package ships: six hook adapters, no reference to a script it lacks, no personal reference.

Everything in the repository ships, tests and fixtures included, so the checks
walk the whole tree.
"""
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHECK = os.path.join(ROOT, "scripts", "lib", "reference_check.py")
SKIPPED_DIRS = {".git", "__pycache__", ".pytest_cache"}

# The six hooks: session start restores, pre-compaction saves, prompt submit warns
# about context, a tool call feeds the ledger, stop checks staleness, and a tool
# call reminds about the checklist. Each is a thin adapter over a shared module.
HOOK_ADAPTERS = {
    "scripts/post-compact-restore.sh": "lib/handoff.py",
    "scripts/pre-compact.sh": "lib/handoff.py",
    "scripts/context-guard.sh": "lib/handoff.py",
    "hooks/handoff-ledger.sh": "lib/handoff.py",
    "hooks/handoff-staleness-guard.sh": "lib/handoff.py",
    "hooks/checklist-nudge.sh": "lib/checklist.py",
}


def shipped_files():
    """Files git tracks (what the release archive ships), so ignored worktree copies are never scanned."""
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--cached"],
        cwd=ROOT, capture_output=True, check=True).stdout.decode().split("\0")
    for name in sorted(name for name in listed if name):
        if not set(Path(name).parts) & SKIPPED_DIRS:
            yield os.path.join(ROOT, name)


def read_text(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except UnicodeDecodeError:
        return None


def test_all_six_hook_adapters_ship_and_call_their_module():
    for path, module in HOOK_ADAPTERS.items():
        full = os.path.join(ROOT, path)
        assert os.path.isfile(full), path
        assert module in read_text(full), path


def test_every_hook_adapter_fails_open_on_an_empty_payload(tmp_path):
    env = dict(os.environ, HOME=str(tmp_path), HANDOFF_STATE_DIR=str(tmp_path / "state"),
               HANDOFF_LEDGER_DIR=str(tmp_path / "ledger"), HANDOFF_COMPACT_STATE_DIR=str(tmp_path / "compact"),
               HIPPOCAMPUS_CONFIG=str(tmp_path / "config.json"), TMPDIR=str(tmp_path))
    for path in HOOK_ADAPTERS:
        result = subprocess.run(["bash", os.path.join(ROOT, path)], input="{}", text=True, capture_output=True, env=env)
        assert result.returncode == 0, (path, result.stderr)


SCRIPT_NAME = re.compile(r"(?<![\w.-])([\w./<>-]+\.(?:sh|py|mjs))\b")
# Names that are not scripts the package should ship: a project marker file the
# surface detector looks for.
NOT_SCRIPTS = {"setup.py"}


def test_no_shipped_file_names_a_script_the_package_does_not_ship():
    """Skills, hooks, scripts, and documents: the files a user reads or runs."""
    shipped = {os.path.basename(path) for path in shipped_files()}
    missing = {}
    for path in shipped_files():
        if os.path.relpath(path, ROOT).startswith(("tests" + os.sep, "docs/examples/", "docs/implementation/", "docs/reviews/")):
            continue  # tests name the stubs they build, and recorded sessions name what they ran
        text = read_text(path)
        if text is None:
            continue
        for match in SCRIPT_NAME.finditer(text):
            name = os.path.basename(match.group(1).strip("<>"))
            if name in NOT_SCRIPTS or name in shipped:
                continue
            missing.setdefault(name, set()).add(os.path.relpath(path, ROOT))
    assert not missing, {name: sorted(paths) for name, paths in missing.items()}


TERMS = os.environ.get("REFERENCE_CHECK_TERMS")


@pytest.mark.skipif(not TERMS, reason="REFERENCE_CHECK_TERMS names the private term list")
def test_no_shipped_file_carries_a_listed_term():
    """The list of terms lives outside this repository, so the check itself ships none."""
    result = subprocess.run([sys.executable, CHECK, "--terms", TERMS, ROOT], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr


def test_improve_harness_skill_publishes_the_new_routing_contract():
    path = os.path.join(ROOT, "skills", "improve-harness", "SKILL.md")
    assert os.path.isfile(path)


# Assemble the prohibited vocabulary so this guard does not match itself.
RECORD_CONVENTIONS = re.compile(
    r'\b' + 'g' + r'h\b|claim[\s-]+comment\b|claim[\s-]+comments\b|'
    + 'host' + r'/', re.I)


def convention_hits(root):
    hits = []
    for directory, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIPPED_DIRS)
        for filename in sorted(files):
            if filename == ".git":
                continue
            path = os.path.join(directory, filename)
            text = read_text(path)
            if text is not None and RECORD_CONVENTIONS.search(text):
                hits.append(os.path.relpath(path, root))
    return hits


def test_shipped_files_contain_no_external_record_conventions():
    # The session package must stay record-provider neutral. Knowledge research
    # and the release runbook legitimately describe concrete provider commands.
    # Milestone and epic are provider-neutral close-outcome kinds in the spec.
    session_roots = ['hooks', 'scripts/lib', 'docs/sweep.md', 'INTERFACE.md',
                     'docs/session-guide.md', 'docs/session-installation.md']
    session_roots += ['skills/' + name for name in (
        'checklist', 'checkpoint', 'handoff-prompt', 'improve-harness', 'pickup',
        'hippocampus-set-up', 'slim-harness', 'sweep', 'wip')]
    for relative in session_roots:
        path = os.path.join(ROOT, relative)
        if os.path.isdir(path):
            assert not convention_hits(path), relative
        else:
            assert not RECORD_CONVENTIONS.search(read_text(path)), relative


@pytest.mark.parametrize('term', ['g' + 'h', 'claim ' + 'comments', 'claim-' + 'comment',
                                  'host' + '/example'])
def test_record_convention_guard_detects_new_shipped_content(tmp_path, term):
    path = tmp_path / 'new.md'
    path.write_text(term)
    assert convention_hits(str(tmp_path)) == ['new.md']
