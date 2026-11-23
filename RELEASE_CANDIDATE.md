# Release candidate: 0.16.2

## Scope

Package three catch-up and setup fixes merged since 0.16.1: [hippocampus#280](https://github.com/coreyfloyd/hippocampus/issues/280) through [PR283](https://github.com/coreyfloyd/hippocampus/pull/283), [hippocampus#281](https://github.com/coreyfloyd/hippocampus/issues/281) through [PR287](https://github.com/coreyfloyd/hippocampus/pull/287), and [hippocampus#284](https://github.com/coreyfloyd/hippocampus/issues/284) through [PR288](https://github.com/coreyfloyd/hippocampus/pull/288). This preparation changes package version metadata and this release record only.

This is a patch release. It does not announce the Public launch milestone.

## Included

- Catch-up (`filing_catchup.py`) skips identities that already have a receipt in the settled-identity store, using the carry step's settle rule and line tolerance. It lists them under `already_settled` and never files them. It rechecks the store before each write, and an unreadable store blocks every write.
- Catch-up reads open loops through the sweep's own reader, so both count the same items with the same identity. A loop with no `context`, a typed item without its own producing session and time, or an identity that would come from file metadata is an inventory error naming the file and loop. A null `open_loops` in an old handoff reads as no items with a warning. Checkpoint and pre-compaction now write `[]` instead of keeping a null.
- `install.sh` (install, `--verify-runtime` and `--verify`) and the Claude and Codex install helpers print one warning for each retired lesson setting still in the configuration. The exit status is unchanged.

## Migration

A configuration that still sets `auto_apply_lessons` in `config.json`, or still has a standalone lesson routing file (`routing.md` or `HIPPOCAMPUS_ROUTING`), must run `hippocampus-set-up` to move them into the knowledge profile: `auto_apply` in its frontmatter and a `## Lesson routing` section. Until then, auto-apply and lesson routing stay refused, as they have been since 0.16.0. This release adds warnings that name each retired setting, its replacement and `hippocampus-set-up`.

## Compatibility and operational boundaries

Claude Code and Codex use the same code. Handoff, ledger, store and profile formats are unchanged. Catch-up still refuses drops and still reports conflicting carried copies as errors: reasoned drops, newer-copy-wins and the unanchored-commitment hold are [hippocampus#271](https://github.com/coreyfloyd/hippocampus/issues/271) and come in the next release, so catch-up readiness cannot certify on this release. Catch-up runs one item at a time: a drop judgment or a conflicting copy is recorded with no write, and the run continues. Known follow-ups: [hippocampus#282](https://github.com/coreyfloyd/hippocampus/issues/282), [#285](https://github.com/coreyfloyd/hippocampus/issues/285), [#286](https://github.com/coreyfloyd/hippocampus/issues/286).

## Verification and publication state

Each change passed two native review rounds with every finding repaired, then independent evaluation: #280 CONDITIONAL PASS, #281 CONDITIONAL PASS, #284 PASS. Each passed CI on Ubuntu and macOS at its exact head before merge.

Not yet signed, tagged or published. The release operation records the exact commit, the immutable unsigned asset digests and the maintainer's SIGN before publication.

## Release-note draft

Hippocampus 0.16.2 makes catch-up agree with the rest of the package. It skips items already settled, reads open loops the same way the sweep does, and reports loops it could never file instead of retrying them forever. Install and verify now warn when your configuration still uses the retired `auto_apply_lessons` setting or a standalone lesson routing file. Run `hippocampus-set-up` to move them into your knowledge profile.
