# Release candidate: 0.16.5

## Scope

Package binding command expansion ([hippocampus#323](https://github.com/coreyfloyd/hippocampus/issues/323), from the investigation of [hippocampus#322](https://github.com/coreyfloyd/hippocampus/issues/322), through [PR324](https://github.com/coreyfloyd/hippocampus/pull/324)). Also include named durable checkpoint enablement refusals and explicit enablement guidance ([hippocampus#327](https://github.com/coreyfloyd/hippocampus/issues/327), through [PR329](https://github.com/coreyfloyd/hippocampus/pull/329)). This final preparation updates the release record and release-note draft only.

This is a patch release. It does not announce the Public launch milestone.

## Included

- A binding command the package runs itself now expands a leading `$NAME`, `${NAME}` or `~` path prefix, once, when `/` or the end of the argument follows it. It still runs without a shell. Any other `$` text, `~user`, pipes and glob characters reach the program unchanged. An unset variable stays literal, and the command fails with an error naming that argument.
- Every package-run command uses this one rule: record writes, ask writes, the ticket read, the durable checkpoint's scheduled-report and adapter commands, the sweep's open-session checks and the lesson pull-request command. An ask binding written as `"$HOME/.../tool" ...` now delivers from an unattended durable checkpoint in Codex as it does in Claude Code.
- INTERFACE.md lists every command the package runs and states the rule once. It no longer claims that the package never runs ask bindings.

- Durable checkpoint enablement now names every blocking node and its condition: a missing report, differing cutoff, mode other than `run`, readiness, unfiled count or errors. Ready nodes are not named as failing, and a refusal still happens before the scheduler adapter is called.
- The checkpoint skill and session guide explain explicit per-session enablement after catch-up run reports are ready on every required node. Claude Code and Codex use the same command and receipt. Enablement is never a side effect of checkpointing or catch-up.

## Migration

No profile or data migration. Durable checkpoint schedules still require explicit enablement after catch-up; this release does not complete catch-up or enable schedules automatically. Profiles that name commands through `$HOME` or `~` start working without edits. A command argument that begins with a set `$NAME/` path prefix is now expanded; before 0.16.5 nothing was.

## Compatibility and operational boundaries

Claude Code and Codex use the same code. Handoff, ledger and profile formats are unchanged. A command list must contain only strings; a non-string element is now refused with an error naming it.

## Verification and publication state

The binding-command change passed native review and independent evaluation. The durable checkpoint change passed native review after repairs and received an independent CONDITIONAL PASS; [hippocampus#328](https://github.com/coreyfloyd/hippocampus/issues/328) tracks its follow-up. Candidate verification results and final commit identity are retained in the release-session evidence until the post-publication update.

Not yet signed, tagged or published. The release operation records the exact commit, the immutable unsigned asset digests and the maintainer's SIGN before publication.

## Release-note draft

Hippocampus 0.16.5 lets binding commands name their program through `$HOME` or `~`. The package expands a leading path prefix itself, still without a shell, so the same profile delivers asks and record writes from Claude Code and from an unattended Codex checkpoint.

Durable checkpoint enablement now identifies each blocking node and its catch-up condition before calling the scheduler adapter. The checkpoint skill and session guide explain how to enable periodic durable checkpoints explicitly after every required node is ready. This release does not run catch-up or enable schedules automatically.
