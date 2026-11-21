# Release candidate: 0.16.0

## Scope

Package the setup and policy part of the public-launch work delivered by [PR268](https://github.com/coreyfloyd/hippocampus/pull/268) (epic for [hippocampus#112](https://github.com/coreyfloyd/hippocampus/issues/112)): [hippocampus#217](https://github.com/coreyfloyd/hippocampus/issues/217), [hippocampus#215](https://github.com/coreyfloyd/hippocampus/issues/215), [hippocampus#216](https://github.com/coreyfloyd/hippocampus/issues/216) and the Python 3.9 import fix for [hippocampus#266](https://github.com/coreyfloyd/hippocampus/issues/266). This preparation changes package version metadata and this release record only.

This release changes set-up behavior, hence the minor version. It does not announce the Public launch milestone or claim that local lookup or the README review is complete.

## Included

- The knowledge profile is the one owner of lesson and knowledge policy: `auto_apply` in profile frontmatter and a `## Lesson routing` section. Custom routing replaces the default table.
- A set-up step that shows and, on approval, moves the retired lesson routing file, `HIPPOCAMPUS_ROUTING` and the `auto_apply_lessons` setting into the profile; until then wraps refuse auto-apply and say how to finish. Kept as a deliberate migration path for existing files.
- One required knowledge setup: a knowledge root, compiled wiki and both follow-up destinations. No checklist-only or wiki-disabled finish. A released wiki-disabled profile stays readable and gets an explicit upgrade; declining changes nothing.
- Rule entry files only for installed tools that need them; the thin preset is recommended for several tools or portable rules; a missing AGENTS.md never makes CLAUDE.md the shared source; nothing is deleted.
- Setup and wrap modules import on Python 3.9 again.

## Compatibility and operational boundaries

Claude Code and Codex consume the same package runtime. Released profile readability, installation layout and composer entry points remain supported. A user with a retired `routing.md`, an exported `HIPPOCAMPUS_ROUTING` or an `auto_apply_lessons` setting sees auto-apply refused until they run set-up and approve the move. Installing this release does not change any profile by itself.

Known limits, ticketed: rules set-up (`scripts/rules_setup.py`) still needs Python 3.11 for `tomllib`, as in earlier releases ([hippocampus#266](https://github.com/coreyfloyd/hippocampus/issues/266)); [hippocampus#261](https://github.com/coreyfloyd/hippocampus/issues/261), [#262](https://github.com/coreyfloyd/hippocampus/issues/262), [#263](https://github.com/coreyfloyd/hippocampus/issues/263), [#264](https://github.com/coreyfloyd/hippocampus/issues/264), [#267](https://github.com/coreyfloyd/hippocampus/issues/267).

## Verification and publication state

Each ticket passed native review and independent evaluation on its exact head; the integrated epic passed independent evaluation (conditional) at 8f731ea, and the Python 3.9 fix was re-checked on the affected tests. PR268 CI run 44841327012 passed on Ubuntu and macOS at head bc54041, merged to main as 160224a.

Not yet signed, tagged or published. Exact commit, immutable unsigned asset digests and the maintainer's SIGN are recorded by the release operation before publication.

## Release-note draft

Hippocampus 0.16.0 makes set-up opinionated. The knowledge profile now holds lesson and knowledge policy, knowledge setup with a wiki is required, and rule entry files are written only for the tools you have installed. Existing routing files and the old auto-apply setting move into the profile through set-up, after you approve the exact change. Python 3.9 can run set-up and wraps again; rules set-up still needs Python 3.11.
