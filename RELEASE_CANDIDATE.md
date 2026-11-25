# Release candidate: 0.16.5

## Scope

Package the one change merged since 0.16.4: binding command expansion ([hippocampus#323](https://github.com/coreyfloyd/hippocampus/issues/323), from the investigation of [hippocampus#322](https://github.com/coreyfloyd/hippocampus/issues/322), through [PR324](https://github.com/coreyfloyd/hippocampus/pull/324)). This preparation changes package version metadata and this release record only.

This is a patch release. It does not announce the Public launch milestone.

## Included

- A binding command the package runs itself now expands a leading `$NAME`, `${NAME}` or `~` path prefix, once, when `/` or the end of the argument follows it. It still runs without a shell. Any other `$` text, `~user`, pipes and glob characters reach the program unchanged. An unset variable stays literal, and the command fails with an error naming that argument.
- Every package-run command uses this one rule: record writes, ask writes, the ticket read, the durable checkpoint's scheduled-report and adapter commands, the sweep's open-session checks and the lesson pull-request command. An ask binding written as `"$HOME/.../tool" ...` now delivers from an unattended durable checkpoint in Codex as it does in Claude Code.
- INTERFACE.md lists every command the package runs and states the rule once. It no longer claims that the package never runs ask bindings.

## Migration

None. Profiles that name commands through `$HOME` or `~` start working without edits. A command argument that begins with a set `$NAME/` path prefix is now expanded; before 0.16.5 nothing was.

## Compatibility and operational boundaries

Claude Code and Codex use the same code. Handoff, ledger and profile formats are unchanged. A command list must contain only strings; a non-string element is now refused with an error naming it.

## Verification and publication state

The change passed native review, with all five findings repaired, then independent evaluation (PASS, no follow-ups). It passed CI on Ubuntu and macOS at its exact head before merge.

Not yet signed, tagged or published. The release operation records the exact commit, the immutable unsigned asset digests and the maintainer's SIGN before publication.

## Release-note draft

Hippocampus 0.16.5 lets binding commands name their program through `$HOME` or `~`. The package expands a leading path prefix itself, still without a shell, so the same profile delivers asks and record writes from Claude Code and from an unattended Codex checkpoint.
