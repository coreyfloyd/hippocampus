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
One exception: the knowledge-profile policy move (the set-up step that moves the
retired lesson routing file, `HIPPOCAMPUS_ROUTING` and the `auto_apply_lessons`
setting into the knowledge profile, and the refusals that send users to it) is
kept so existing files have a migration path: "I want to provide a migration path
for existing files. The setup step should catch it." (maintainer, 2026-11-20).

## Vocabulary

`docs/glossary.md` names every concept. Use its terms and never a word on an entry's
avoid list; add or revise an entry before naming a new concept in code or docs.

## Tests and configuration

Stated exception to keeping a rule in one place: the shared development rules
reach only private repositories, so this public repository carries its own copy.

No test fails because configuration changed. Configuration is settings, per-node values, job and label lists, and the text of rules, skills and agent definitions, whether live or recorded. A test may check that configuration is valid: it parses, generated views match their source, references resolve, a tool's size limit holds. It never asserts a count, name, value, hash or wording taken from configuration. Remove any test that does when you come across it in your work (how: `test-driven-development`). Test code against an input the test controls: written in the test or a recorded fixture. Agents check wording when reviewing rules and skills (`/improve-harness`, `/slim-harness`). Why: such tests check no behaviour, and they turned checks red on legitimate changes and blocked unrelated pull requests (maintainer, 2026-11-05).

## Verify before handing off

Run the tests that cover the changed files, plus these quick checks. Do not run
the full suite locally; CI on the pull request is the full gate:

```bash
git diff --check
python3 scripts/generate-release-metadata.py --check
python3 tests/test-fold-names.py
python3 tests/test-public-docs.py
python3 scripts/check-skill-surface.py skills
```

Tests live in `tests/` and assert what the user sees: the report, the handoff, or
the exit status.
<!-- hippocampus-rules:block:start ab88c4b7f138d034e5e2b6e24a46a501f05aed08be0bbb8ace07c340178cfeae -->
<!-- hippocampus-rules: generated from ["capability-catalog/domain-vocabulary","capability-catalog/shell-rules","capability-catalog/pr-to-main","capability-catalog/ticket-lifecycle","capability-catalog/code-graph","capability-catalog/development-core","capability-catalog/agent-workflows"]; do not hand-edit -->
This folder's kind is development. Its rules below come from the scope capabilities its scope profile has on.

## Vocabulary

Before naming a runtime, panel or workflow concept, use the glossary in `~/Development/admin-panel/CONTEXT.md` (rule owned by admin-panel's `CLAUDE.md`); session-continuity terms follow [hippocampus's `docs/glossary.md`](https://github.com/coreyfloyd/hippocampus/blob/main/docs/glossary.md) (continuity was folded into hippocampus and archived, 2026-11-03). Why: 27 concepts were named differently across panel, skills and code (2026-09-21, [admin-panel#187](https://github.com/coreyfloyd/admin-panel/issues/187)).

## Shell (macOS zsh)

The shell is zsh and the userland is BSD; these fail silently or abort:

- Write a variable followed by `:` as `${var}:` (`git show ${base}:path`); `$var:f…` is read as a history modifier and the command gets the wrong argument (2026-11-18: empty files and two invalid RED runs).
- An unquoted `$args` does not word-split, so `gh … $args` passes one word; write arguments literally or use an array, and read labels back before reporting a move (2026-10-07: a label loop failed while its "moved" comments posted).
- A word starting with `=` expands as a command path: `echo ===` aborts with `== not found`; quote it (2026-10-14).
- BSD `sed` ignores `\b`; use `perl -pi -e` for word-boundary replacements (2026-11-20: three references survived a `sed` rename in admin-panel PR 2079).
- Never pipe an interactive installer or sign-in (xcodes, sudo) through `tee` or a redirect: the credential prompt is hidden and the process idles. Run it in a visible Herdr pane (2026-10-12).

## Git

Load `git-practices` before any `git commit`, `push` or `merge`, even a one-line fix. Before architecture, refactor or cross-cutting work, run `pwd` and `git worktree list` and state the worktree; wrong-worktree work has required full redos. Make development changes in a new worktree off `origin/main`, created without asking (2026-09-29). Before any merge, read `git-practices` §Merge-to-Main Gate; before a pull request or epic integration, read `git-practices/references/epic-branches.md`. On resume, before asking to merge an open pull request, confirm its target file still exists and is still the source; a concurrent source move strands the approved edit (2026-11-03: an approved rule edit never reached the live rule after the rules moved).

## Issues

Load `issue-workflow` before the first `gh issue create/edit/close` or label change; repo-local `docs/agents/issue-tracker.md` files are historical. Before assigning `spec/*`, read `issue-workflow/references/policy-tables.md` §`spec/*`; `to-spec` owns the approval ask.

## Code graph

Where a repo lists code-graph tools in its own instructions, query them before grep for usage, callers and impact. Catalog: [[macbook-pro-m5-operations#Installed Applications]].

## Repository kinds and test placement

The configuration repository holds no logic: if a change to a file could break something only a test would catch, the file is code and moves to its owner with its tests (shared runtime to admin-panel, rule and skill composition to hippocampus, personal tools to their product repository). It keeps settings, rule and skill text, per-node values, and one-line hook entries that call the runtime. New work adds no tests to the configuration repository. Code moving into admin-panel arrives generic, with private values through deployment settings, because admin-panel is headed for public release. Inventory: [admin-panel#903](https://github.com/coreyfloyd/admin-panel/issues/903); until it is migrated, the configuration repository keeps its current suite as the merge gate. Why: what belonged in dotfiles was undefined, so migration sessions could not tell what to move (Corey 2026-11-01).

No test fails because configuration changed. Configuration is settings, per-node values, job and label lists, and the text of rules, skills and agent definitions, whether live or recorded. A test may check that configuration is valid: it parses, generated views match their source, references resolve, a tool's size limit holds. It never asserts a count, name, value, hash or wording taken from configuration. Remove any test that does when you come across it in your work (how: `test-driven-development`). Test code against an input the test controls: written in the test or a recorded fixture. Agents check wording when reviewing rules and skills (`/improve-harness`, `/slim-harness`). Why: such tests check no behaviour, and they turned checks red on legitimate changes and blocked unrelated pull requests (Corey 2026-11-05).

## Problem solving

Propose the correct fix, never a workaround as the primary recommendation; an active production outage may get a labeled mitigation first.

Validate a measurement method against a known positive control before asking Corey to act on a device. Why: a clipboard check flattened Safari and Chrome alike, so his Chrome copy proved nothing (2026-10-12).

An unexplained failure gets an investigation ticket (`dev-investigate`) before any fix, guard or audit, including preventive tickets and evaluator follow-ups that name a suspected cause; the only exception is a catastrophic P0 with Corey's approval. Why: a guard built on an unconfirmed outage cause was closed unmerged (2026-10-10).

## Deleting a shared surface

Before retiring a registered job, produced artifact, cache or entry point, list its callers in every repo and confirm with the owning session. Why: a single-repo grep would have stranded an admin-panel button (2026-09-18).

## Runtime paths

Never hardcode `~/ops`, `$HOME/ops`, `Path.home() / "ops"` or another home-relative literal; resolve from `OPS_HOME` or the deployment setting, with the default only inside that resolver; docs write `$OPS_HOME/...`. Why: the layout must change without code edits (2026-10-02; migration [admin-panel#346](https://github.com/coreyfloyd/admin-panel/issues/346)).

Code, launchers, hooks, scripts and tests never read the vault (the knowledge root) at runtime. Vault content that code or configuration needs reaches it as a generated file: an install or compose step reads the vault and writes the file the tool reads, the way tool instruction files are composed from `rules/agent-rules.md`. Tests never read live configuration, rules or vault files; they create the inputs they need. Spec review and evaluation fail a design or change that does either. Why: moving the decision criteria into the vault made the factory launcher read the vault, so every test that launched a session, and CI, needed the real vault (Corey 2026-11-14).

Validate a tool's output for runtime code from that runtime's interpreter, not from a shell: macOS 27 filters some kernel tables by the caller's signature. Why: a probe validated from a shell on every node failed from Homebrew Python (2026-11-20, [admin-panel#2127](https://github.com/coreyfloyd/admin-panel/issues/2127)).

## Cutovers and layout

Offer to skip a shadow soak for a runtime cutover, with the rollback path stated and external holds explicit; Corey prefers a live cutover once the mechanism is proven. Before a visual layout change to a screen with no approved design, show a small structural sketch and get his confirmation. When an approved design exists, show that exact design file and never send new mocks for the screen. Why: Corey asked "why aren't we using the approved designs?" (2026-11-21).

## Scope under failure

A failed tool or workflow step does not authorize skipping the remaining independent requirements. For a codebase-wide rename, search production and test code, including raw SQL strings and record initializers, and name the affected test files in the handoff.

## Dev workflow

Feature work → load the **dev-plan** skill. Bug fixing or executing an approved ticket → load **dev-execute**. Before entering the planning pipeline (to-spec, grilling), check whether a documented procedure already covers the work, and run it instead. Why: a built, documented node-install procedure was sent through spec grilling (2026-10-25).

When deciding whether a change can merge without Corey, how urgent a ticket is, which ready work to take next (an orchestrator choosing its next ticket included), or where a solution should live, use the installed generated decision criteria at the path the deployment setting `generated_practice_file` (or `FACTORY_GENERATED_PRACTICE_FILE`) names and name the criterion and level you chose. Standard generators and investigators receive that complete text automatically; other readers open the installed artifact on demand. Implementation placement stays in Hippocampus improve-harness, with private destinations in its generated local routing file. Canonical edits belong in `rules/decision-criteria.md` and `rules/lesson-routing.md`; install/refresh delivers them. A missing generated artifact requires installation/refresh, never a runtime vault fallback.

Runtime repository boundary: [[agent-runtime-product#New runtime work targets the admin-panel repo (IMPORTANT)]].

## Change class

In a repository that declares change classes, the classifier decides whether a change goes through the workflow; it alone holds the class table, so never restate it. Before opening a pull request, run `python3 scripts/ci/change_classes.py --base origin/main --head HEAD --record <scratch>/verification.json` (for an epic ticket, `--base origin/epic/<N>-<slug>`), run affected tests plus quick checks locally, and put the exact-head record and actual results/logs on the PR. T2 (Corey, 2026-11-09): CI on the PR is the full-suite gate; mark an unexecuted full `local_command` unrun/returncode null with its approval provenance. Without CI, generators stay affected-only and the evaluator runs the full suite once per ticket on a quiet serialized node as the pre-merge gate. Epic children use affected checks; full CI runs at the epic PR and also midway for more than five tickets. Details: `git-practices` §Merge-to-Main Gate. Its `workflow` answer is binding: `direct-edit` when every file is in a direct-edit class (docs, instruction text, config), so edit directly and launch no generator, reviewer or evaluator; `dev-execute` when any file is in tests, code or locked inputs, whatever else the change touches. One exception: a removal-only change to test files answers `direct-edit` when its other files are all in direct-edit classes. It adds no line to a test file, changes no mode or type, deletes binaries only whole, moves nothing, and may drop suite-declaration entries naming deleted tests. Shared test setup, the test runner, and a file a remaining test reads stay `dev-execute`. The exception changes the workflow only; selected CI suites still run, with affected checks locally under T2. A repository with no change classes has no classifier to run; by policy, a removal-only change there is a direct edit: a pull request that passes its own checks. Paths and that exception alone decide: no size bound and no session judgment. Rounds stay a panel setting, and an unexplained failure still gets its investigation first (Problem solving). Why: a config-only change was planned through the full workflow (2026-10-30), and test removals waited on overrides (2026-11-05).
<!-- hippocampus-rules:block:end ab88c4b7f138d034e5e2b6e24a46a501f05aed08be0bbb8ace07c340178cfeae -->
