"""Contract tests for the stdlib-only reference check.

The check reads its terms from a file the caller names, so these tests write
their own term list; the strings below are placeholders, not anyone's setup.
"""
import os
import subprocess
import sys

import pytest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHECK = os.path.join(ROOT, "scripts", "lib", "reference_check.py")


def run_check(*args, env=None):
    return subprocess.run(
        [sys.executable, CHECK, *args],
        capture_output=True,
        text=True,
        env=env,
    )


@pytest.fixture
def terms(tmp_path):
    path = tmp_path / "terms.txt"
    path.write_text(
        "# terms the check looks for, one per line\n"
        "\n"
        "examplehandle\n"
        "example-host-1\n"
        "~/example-ops\n"
    )
    return str(path)


def test_clean_file_passes(tmp_path, terms):
    clean = tmp_path / "clean.md"
    clean.write_text("# Handoff\n\nA handoff is one session's pointer.\n")

    result = run_check("--terms", terms, str(clean))

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == ""


def test_reference_is_reported_with_file_and_line(tmp_path, terms):
    clean = tmp_path / "clean.md"
    clean.write_text("Nothing personal here.\n")
    dirty = tmp_path / "dirty.md"
    dirty.write_text(
        "line one\n"
        "Run it on Example-Host-1 first.\n"
        "Logs go to ~/example-ops/logs.\n"
    )

    result = run_check("--terms", terms, str(clean), str(dirty))

    assert result.returncode == 1
    assert result.stdout.splitlines() == [
        f"{dirty}:2:11: example-host-1: Run it on Example-Host-1 first.",
        f"{dirty}:3:12: ~/example-ops: Logs go to ~/example-ops/logs.",
    ]
    assert str(clean) not in result.stdout


def test_every_occurrence_on_a_line_is_reported(tmp_path, terms):
    dirty = tmp_path / "dirty.md"
    dirty.write_text("examplehandle/examplehandle on example-host-1\n")

    result = run_check("--terms", terms, str(dirty))

    assert result.returncode == 1
    assert [line.split(": ")[0] for line in result.stdout.splitlines()] == [
        f"{dirty}:1:1",
        f"{dirty}:1:15",
        f"{dirty}:1:32",
    ]


def test_a_separator_in_a_term_matches_any_separator_or_none(tmp_path, terms):
    """A name can be written spaced, hyphenated, underscored, dotted, or run together."""
    dirty = tmp_path / "dirty.md"
    dirty.write_text(
        "Example Host 1\n"
        "examplehost1\n"
        "example_host.1\n"
        "example--host-1\n"
        "example handle\n"
    )

    result = run_check("--terms", terms, str(dirty))

    assert result.returncode == 1
    assert result.stdout.splitlines() == [
        f"{dirty}:1:1: example-host-1: Example Host 1",
        f"{dirty}:2:1: example-host-1: examplehost1",
        f"{dirty}:3:1: example-host-1: example_host.1",
        f"{dirty}:4:1: example-host-1: example--host-1",
    ]


def test_a_backslash_lets_a_term_start_with_a_hash(tmp_path):
    terms = tmp_path / "terms.txt"
    terms.write_text("# a comment, not a term\n\\#example-room\n")
    dirty = tmp_path / "dirty.md"
    dirty.write_text("posted in #example-room\nexample-room alone\n")

    result = run_check("--terms", str(terms), str(dirty))

    assert result.returncode == 1
    assert result.stdout.splitlines() == [f"{dirty}:1:11: #example-room: posted in #example-room"]


def test_directory_is_scanned_recursively(tmp_path, terms):
    tree = tmp_path / "pkg"
    (tree / "skills" / "one").mkdir(parents=True)
    (tree / "skills" / "one" / "SKILL.md").write_text("ask examplehandle\n")
    (tree / "README.md").write_text("clean\n")
    (tree / ".git").mkdir()
    (tree / ".git" / "config").write_text("examplehandle\n")
    (tree / "image.bin").write_bytes(b"\xff\xfe\x00examplehandle")

    result = run_check("--terms", terms, str(tree))

    assert result.returncode == 1
    lines = result.stdout.splitlines()
    assert lines == [f"{tree / 'skills' / 'one' / 'SKILL.md'}:1:5: examplehandle: ask examplehandle"]


def test_provenance_upstream_lines_do_not_count(tmp_path, terms):
    skill = tmp_path / "skill"
    skill.mkdir()
    provenance = skill / "PROVENANCE.md"
    provenance.write_text(
        "# Provenance\n"
        "\n"
        "- **Upstream repo**: git@github.com:examplehandle/skills.git\n"
        "- **Fork (copied from)**: git@github.com:examplehandle/skills-fork.git\n"
        "- **Path in upstream**: skills/examplehandle\n"
        "- **License**: LICENSE (see upstream repo)\n"
        "- **Ticket**: https://github.com/examplehandle/tracker/issues/601\n"
        "\n"
        "Copied as a snapshot (policy, examplehandle-tracker#264).\n"
        "Credit for the original content belongs to the upstream author, examplehandle.\n"
    )

    result = run_check("--terms", terms, str(provenance))

    assert result.returncode == 1
    reported = [int(line.split(":")[1]) for line in result.stdout.splitlines()]
    assert reported == [4, 7, 9]


def test_upstream_line_carrying_a_ticket_link_still_counts(tmp_path, terms):
    provenance = tmp_path / "provenance.md"
    provenance.write_text(
        "- **Upstream repo**: examplehandle/skills, see examplehandle-tracker#12\n"
        "- **Upstream repo**: examplehandle/skills (fork of examplehandle/base)\n"
    )

    result = run_check("--terms", terms, str(provenance))

    assert result.returncode == 1
    assert {int(line.split(":")[1]) for line in result.stdout.splitlines()} == {1, 2}


def test_upstream_lines_count_outside_a_provenance_file(tmp_path, terms):
    readme = tmp_path / "README.md"
    readme.write_text("- **Upstream repo**: git@github.com:examplehandle/skills.git\n")

    result = run_check("--terms", terms, str(readme))

    assert result.returncode == 1


def test_a_term_matches_whole_words_only(tmp_path, terms):
    """continuity#34: a term inside a longer word is not a reference; a camel-case join or plural is."""
    dirty = tmp_path / "dirty.md"
    dirty.write_text(
        "deploy to example-host-1 now\n"
        "var examplehost12 = null;\n"
        "notexamplehandle\n"
        "ExampleHandleLogs\n"
        "two examplehandles\n"
    )

    result = run_check("--terms", terms, str(dirty))

    assert result.returncode == 1
    assert result.stdout.splitlines() == [
        f"{dirty}:1:11: example-host-1: deploy to example-host-1 now",
        f"{dirty}:4:1: examplehandle: ExampleHandleLogs",
        f"{dirty}:5:5: examplehandle: two examplehandles",
    ]


def test_two_terms_written_as_one_word_still_count(tmp_path):
    terms = tmp_path / "terms.txt"
    terms.write_text("example\nhandle\n")
    dirty = tmp_path / "dirty.md"
    dirty.write_text("examplehandle\nexamplehandler\n")

    result = run_check("--terms", str(terms), str(dirty))

    assert result.returncode == 1
    assert [line.split(": ")[:2] for line in result.stdout.splitlines()] == [
        [f"{dirty}:1:1", "example"],
        [f"{dirty}:1:8", "handle"],
    ]


# The repository's own public slug; the owner login appears in this file only inside it.
OWN_REPOSITORY = "coreyfloyd/continuity"


def test_the_repository_own_url_is_allowed_and_other_owner_uses_count(tmp_path):
    """continuity#34: the owner login in the repository's own URL is not a reference; anywhere else it is."""
    owner = OWN_REPOSITORY.split("/")[0]
    terms = tmp_path / "terms.txt"
    terms.write_text(f"{owner[:5]}\n{owner[5:]}\n")
    dirty = tmp_path / "dirty.md"
    dirty.write_text(
        f"git clone https://github.com/{OWN_REPOSITORY}.git\n"
        f"claude plugin install continuity --marketplace {OWN_REPOSITORY}\n"
        f"see github.com/{owner}/other\n"
        f"{OWN_REPOSITORY}-fork\n"
        f"written by {owner[:5].title()}\n"
        f"{OWN_REPOSITORY}.private\n"
        f"{OWN_REPOSITORY}.docs/README.md\n"
        f"{OWN_REPOSITORY}.github\n"
        f"see {OWN_REPOSITORY}#34, {OWN_REPOSITORY}/issues?q=x or \"{OWN_REPOSITORY}\".\n"
        f"clone {OWN_REPOSITORY}.git.\n"
    )

    result = run_check("--terms", str(terms), str(dirty))

    assert result.returncode == 1
    assert [int(line.split(":")[1]) for line in result.stdout.splitlines()] == [3, 3, 4, 4, 5, 6, 6, 7, 7, 8, 8]


def test_terms_file_from_environment(tmp_path, terms):
    dirty = tmp_path / "dirty.md"
    dirty.write_text("examplehandle\n")
    env = dict(os.environ, REFERENCE_CHECK_TERMS=terms)

    result = run_check(str(dirty), env=env)

    assert result.returncode == 1


@pytest.mark.parametrize(
    "setup",
    ["missing_terms", "empty_terms", "missing_path", "no_terms_given"],
)
def test_usage_errors_exit_2(tmp_path, terms, setup):
    target = tmp_path / "file.md"
    target.write_text("clean\n")
    env = {k: v for k, v in os.environ.items() if k != "REFERENCE_CHECK_TERMS"}
    if setup == "missing_terms":
        args = ["--terms", str(tmp_path / "absent.txt"), str(target)]
    elif setup == "empty_terms":
        empty = tmp_path / "empty.txt"
        empty.write_text("# only a comment\n\n")
        args = ["--terms", str(empty), str(target)]
    elif setup == "missing_path":
        args = ["--terms", terms, str(tmp_path / "absent.md")]
    else:
        args = [str(target)]

    result = run_check(*args, env=env)

    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr


def test_check_imports_stdlib_only():
    source = open(CHECK, encoding="utf-8").read()
    imports = {
        line.split()[1].split(".")[0]
        for line in source.splitlines()
        if line.startswith(("import ", "from "))
    }
    assert imports <= set(sys.stdlib_module_names) | {"__future__"}
