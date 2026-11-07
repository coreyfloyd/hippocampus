# hippocampus — agent rules

Rules for any agent changing this repository, in any tool.

## Public repository

This repository is public. Commits, pull requests, issues and comments contain no
private repository names, personal home-directory paths, or private hostnames.
Before every push, scan the whole pushed range (`git log -p origin/main..HEAD`) and
stop on any hit.

## Both tools, same behavior

Every feature works the same in Claude Code and Codex: shipped skills, hooks, the
Codex adapter and plugin metadata change together. A change that cannot ship for
one tool is not finished.

## No backward compatibility for session features until the public launch

The session features (checklist, checkpoint, handoff-prompt, pickup, sweep, wip,
improve-harness, slim-harness, slim-unattended) are unreleased until the first announced public release, tracked by
the `Public launch` milestone. Until then, replace old shapes outright: no aliases,
no migration code, no compatibility paths. hippocampus's released surfaces keep
working: its install path, knowledge profile format and composer entry point.

## Vocabulary

`docs/glossary.md` names every concept. Use its terms and never a word on an entry's
avoid list; add or revise an entry before naming a new concept in code or docs.

## Verify before handing off

Run the checks in `RELEASING.md` § Verify the candidate. At minimum:

```bash
git diff --check
python3 scripts/generate-release-metadata.py --check
python3 tests/test-fold-names.py
python3 -m pytest -q tests
bash tests/test-pickup-wrapper.sh
bash tests/test-pickup-branch-scan.sh
python3 tests/test-public-docs.py
bash tests/test-contracts.sh
```

Tests live in `tests/` and assert what the user sees: the report, the handoff, or
the exit status.
