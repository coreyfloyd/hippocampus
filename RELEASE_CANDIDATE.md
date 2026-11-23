# Release candidate: 0.16.1

## For the next release

Carry these into the next release's scope and release-note draft.

- Migration: a configuration that still sets `auto_apply_lessons` in `config.json`, or still has a standalone lesson routing file (`routing.md` or `HIPPOCAMPUS_ROUTING`), must run `hippocampus-set-up` to move them into the knowledge profile (`auto_apply` in its frontmatter, a `## Lesson routing` section). Until then auto-apply and lesson routing stay refused. `install.sh`, `install.sh --verify-runtime`, `install.sh --verify` and the Claude and Codex install helpers now print one warning per retired setting they find, naming the file, its replacement and `hippocampus-set-up`; the exit status is unchanged.

## Scope

Package the carry fix from [hippocampus#147](https://github.com/coreyfloyd/hippocampus/issues/147), merged through [PR277](https://github.com/coreyfloyd/hippocampus/pull/277). It is the only change on main since 0.16.0. This preparation changes package version metadata and this release record only.

This is a patch release: it fixes sessions carrying items that are already settled and adds no new setup step. It does not announce the Public launch milestone.

## Included

- One settled-identity store per machine, `settled-identities.jsonl` beside the session ledgers. Every settle path writes a settlement receipt keyed by the item's producing session, time, type and text.
- Pickup, checkpoint, merge, the stop-hook skeleton and pre-compaction skip any session item that has a receipt, so a predecessor no longer restores an item its successor settled, and copies in other handoffs stop coming back.
- A carried item whose status or disposition is a past-tense terminal value (captured, dropped, filed, applied, recorded, done) is closed with a receipt saying no filing step settled it, and the checkpoint reports how many it closed.
- `handoff.py settle-identity --receipts <file>` records operator-supplied receipts: it validates each row, writes each identity once, survives a torn last line and reports invalid rows by line number.
- Durable filing matches rows to items by position, not equality.

## Compatibility and operational boundaries

Claude Code and Codex use the same code. Handoff, ledger and profile formats are unchanged; the store is a new file. Installing this release changes no handoff by itself: items settle when the next checkpoint or pickup runs. Agents should state intent with plan words (drop, file, keep, pending); a past-tense value on a carried item now closes it for every session on the machine.

Catch-up readiness (`filing_catchup.py`) is unchanged and is decided in [hippocampus#271](https://github.com/coreyfloyd/hippocampus/issues/271). Known follow-ups: [hippocampus#276](https://github.com/coreyfloyd/hippocampus/issues/276).

## Verification and publication state

The change passed two native reviews (all findings fixed but one kept by design and documented) and independent evaluation (conditional pass), then CI: PR277 run 45085713696 passed on Ubuntu and macOS at head aacb40b, merged to main as ee2b829.

Not yet signed, tagged or published. Exact commit, immutable unsigned asset digests and the maintainer's SIGN are recorded by the release operation before publication.

## Release-note draft

Hippocampus 0.16.1 stops sessions from carrying items that are already settled. Each machine now keeps one store of settlement receipts, and pickup and checkpoint skip any item with a receipt, so a predecessor no longer brings back what its successor filed or dropped. An item marked with a past-tense status such as done or filed is closed the same way, with a receipt that says so. A new `settle-identity` command records receipts in bulk.
