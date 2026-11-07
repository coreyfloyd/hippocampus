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
improve-harness, slim-harness) are unreleased until the first announced public release, tracked by
the `Public launch` milestone. Until then, replace old shapes outright: no aliases,
no migration code, no compatibility paths. hippocampus's released surfaces keep
working: its install path, knowledge profile format and composer entry point.

## Vocabulary

`docs/glossary.md` names every concept. Use its terms and never a word on an entry's
avoid list; add or revise an entry before naming a new concept in code or docs.

## Tests and configuration

Stated exception to keeping a rule in one place: the shared development rules
reach only private repositories, so this public repository carries its own copy.

No test fails because configuration changed. Configuration is settings, per-node values, job and label lists, and the text of rules, skills and agent definitions, whether live or recorded. A test may check that configuration is valid: it parses, generated views match their source, references resolve, a tool's size limit holds. It never asserts a count, name, value, hash or wording taken from configuration. Remove any test that does when you come across it in your work (how: `test-driven-development`). Test code against an input the test controls: written in the test or a recorded fixture. Agents check wording when reviewing rules and skills (`/improve-harness`, `/slim-harness`). Why: such tests check no behaviour, and they turned checks red on legitimate changes and blocked unrelated pull requests (maintainer, 2026-11-05).

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
