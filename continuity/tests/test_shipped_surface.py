"""What the package ships: six hook adapters, no reference to a script it lacks, no personal reference.

Everything in the repository ships, tests and fixtures included, so the checks
walk the whole tree.
"""
import os
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
    for root, dirs, files in os.walk(ROOT):
        dirs[:] = sorted(d for d in dirs if d not in SKIPPED_DIRS)
        for name in sorted(files):
            yield os.path.join(root, name)


def read_text(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except UnicodeDecodeError:
        return None


def test_all_six_hook_adapters_ship_and_call_their_module():
    assert len(HOOK_ADAPTERS) == 6
    for path, module in HOOK_ADAPTERS.items():
        full = os.path.join(ROOT, path)
        assert os.path.isfile(full), path
        assert module in read_text(full), path


def test_every_hook_adapter_fails_open_on_an_empty_payload(tmp_path):
    env = dict(os.environ, HOME=str(tmp_path), HANDOFF_STATE_DIR=str(tmp_path / "state"),
               HANDOFF_LEDGER_DIR=str(tmp_path / "ledger"), HANDOFF_COMPACT_STATE_DIR=str(tmp_path / "compact"),
               CONTINUITY_CONFIG=str(tmp_path / "config.json"), TMPDIR=str(tmp_path))
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
        if os.path.relpath(path, ROOT).startswith("tests" + os.sep):
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
    text = read_text(path)
    assert "name: improve-harness\n" in text
    assert "$IMPROVE_HARNESS_ROUTING" in text
    assert "`improve-harness/routing.md` under `$XDG_CONFIG_HOME`" in text
    assert "default `~/.config`" in text


def test_memory_policy_contract_defaults_and_destination_routing():
    text = read_text(os.path.join(ROOT, "skills", "improve-harness", "SKILL.md"))
    assert "### Memory policy" in text
    routing = text.split("### Memory policy", 1)[1].split("**Recording form.", 1)[0]
    for clause in ("memory-policy: native", "`native` | `promote`", "absent means `native`",
                   "no memory moves", "configured home", "knowledge/context/", "knowledge/wiki/",
                   "no other home", "instruction-versus-fact"):
        assert clause in routing, clause
    assert "**Memory is never for rules.**" not in text
    assert "Promote it and delete the original" not in text


def test_memory_review_is_session_scoped_and_running_tool_specific():
    text = read_text(os.path.join(ROOT, "skills", "improve-harness", "SKILL.md"))
    memory = text.split("**(e) Memory.**", 1)[1].split("### 2.", 1)[0]
    for clause in ("recalled or written this session", "no full-store sweep", "running tool",
                   "Codex", "skip", "do not emulate", "index", "both modes",
                   "verification", "`native`", "`promote`", "table row", "deletion"):
        assert clause in memory, clause
    assert "<n> recalled or written" in text
    assert "Memory: <policy; reviewed count | skipped — reason>" in text


def test_unattended_proposals_carry_full_memory_move_until_interactive_resume():
    text = read_text(os.path.join(ROOT, "skills", "improve-harness", "SKILL.md"))
    afk = text.split("**AFK output", 1)[1].split("## Procedure", 1)[0]
    for clause in ("`lesson`", "memory file", "target", "proposed text", "grounding",
                   "deletion", "`lessons`", "next interactive", "resume the handoff",
                   "Without an override", "do not file tickets"):
        assert clause in afk, clause
    assert "where unattended proposals are filed" in text


@pytest.mark.parametrize("surface", ["routing", "size", "mode", "output"])
def test_afk_routing_preserves_configured_sink_and_headless_delivery(surface):
    text = read_text(os.path.join(ROOT, "skills", "improve-harness", "SKILL.md"))
    sections = {
        "routing": text.split("### Default routing", 1)[0],
        "size": text.split("In an unattended run,", 1)[1].split("## The one rule", 1)[0],
        "mode": text.split("**AFK output", 1)[1].split("## Procedure", 1)[0],
        "output": text.split("## Output format", 1)[1].split("## Gotchas", 1)[0],
    }
    required = {
        "routing": ("where unattended proposals are filed",),
        "size": ("configured proposal destination", "`lesson`"),
        "mode": ("configured durable sink", "overrides this default", "including tickets",
                 "Factory sessions and subagents never write handoffs", "parent or caller",
                 "no parent or sink", "report the persistence blocker"),
        "output": ("configured sink + receipt", "parent/caller", "persistence blocker"),
    }
    for clause in required[surface]:
        assert clause in sections[surface], clause


def test_shipped_sources_use_only_the_current_lessons_skill_name():
    retired = "-".join(("harness", "improve"))
    retired_variable = "_".join(("HARNESS", "IMPROVE"))
    for path in shipped_files():
        assert retired not in os.path.relpath(path, ROOT), path
        text = read_text(path)
        if text is not None:
            assert retired not in text, path
            assert retired_variable not in text, path


# Assemble the prohibited vocabulary so this guard does not match itself.
RECORD_CONVENTIONS = re.compile(
    r'\b' + 'g' + r'h\b|claim[\s-]+comment\b|claim[\s-]+comments\b|'
    + 'host' + r'/|\b' + 'mile' + r'stones?\b|\b' + 'ep' + r'ics?\b', re.I)


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
    assert not convention_hits(ROOT)


@pytest.mark.parametrize('term', ['g' + 'h', 'claim ' + 'comments', 'claim-' + 'comment',
                                  'host' + '/example', 'mile' + 'stone', 'ep' + 'ic'])
def test_record_convention_guard_detects_new_shipped_content(tmp_path, term):
    path = tmp_path / 'new.md'
    path.write_text(term)
    assert convention_hits(str(tmp_path)) == ['new.md']
