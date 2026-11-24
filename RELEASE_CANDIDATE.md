# Release candidate: 0.16.3

## Scope

Package two catch-up changes merged since 0.16.2: [hippocampus#271](https://github.com/coreyfloyd/hippocampus/issues/271) through [PR290](https://github.com/coreyfloyd/hippocampus/pull/290), and [hippocampus#291](https://github.com/coreyfloyd/hippocampus/issues/291) through [PR292](https://github.com/coreyfloyd/hippocampus/pull/292). This preparation changes package version metadata and this release record only.

This is a patch release. It does not announce the Public launch milestone.

## Included

- Catch-up drops `progress`, `open_loop` and `artifact` items with a reason, through a `dropped` receipt in the settled-identity store, and never drops knowledge, lessons, decisions or commitments. Where carried copies of one identity conflict, the newest copy (by the handoff's `written_at`) is filed and the older ones stay in the report under `superseded_copies`. A commitment with no ticket anchor stays unfiled with a reason; catch-up never creates a ticket for it.
- A `dropped` receipt now settles an untyped open loop (receipt type `untyped_loop`) or an empty open loop (`empty_loop`, named by its handoff's session, `written_at` and position). No other disposition is accepted for them, and a catch-up run never files them. A typed item without context stays an inventory error. The sweep skips settled loops and reports how many it skipped (`settled_loops`).

## Migration

None. Existing settled-identity stores keep working; the two new receipt types are additive.

## Compatibility and operational boundaries

Claude Code and Codex use the same code. Handoff, ledger and profile formats are unchanged. The carry step skips a settled untyped loop only when the loop carries its own session and time; catch-up reads only handoffs written before its cutoff. Decisions with no user author and no ticket remain unfiled until a decisions record writer exists (#271, N1). Known follow-ups: [hippocampus#282](https://github.com/coreyfloyd/hippocampus/issues/282), [#285](https://github.com/coreyfloyd/hippocampus/issues/285), [#286](https://github.com/coreyfloyd/hippocampus/issues/286).

## Verification and publication state

Each change passed native review with every finding repaired, then independent evaluation: #271 CONDITIONAL PASS, #291 PASS. Each passed CI on Ubuntu and macOS at its exact head before merge.

Not yet signed, tagged or published. The release operation records the exact commit, the immutable unsigned asset digests and the maintainer's SIGN before publication.

## Release-note draft

Hippocampus 0.16.3 lets catch-up finish. It can now drop progress notes, open items, artifact pointers and untyped or empty open loops, each with a recorded reason, while knowledge, lessons, decisions and commitments are always filed. When carried copies of an item disagree, the newest copy wins and the older ones stay in the report.
