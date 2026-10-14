# Release candidate: 0.10.0

## Scope

This candidate covers the changes since v0.9.0:

- Retire the old setup compatibility skill; `hippocampus-set-up` is the setup entry point ([hippocampus#24](https://github.com/coreyfloyd/hippocampus/issues/24)).
- File original meeting transcripts from policy-defined intake into retained primary-source storage only after every authorized capture route completes or is explicitly declined, repairing source references ([hippocampus#29](https://github.com/coreyfloyd/hippocampus/issues/29)).
- Create configurable meeting records directly in their meeting folder, preserve meaningful filenames and stable identity on retry, share approved distribution through `absorb`, compile selected primary evidence through `wiki-compile` ([hippocampus#31](https://github.com/coreyfloyd/hippocampus/issues/31)).
- Route retained-source understanding, applicability assessment and distribution planning through `research-sources`; inventory intended outcomes before proposing distribution ([hippocampus#36](https://github.com/coreyfloyd/hippocampus/issues/36)).
- Reconcile skill boundaries, meeting action/document routes, optional profile fields, raw metadata, inline research, compiler/audit guidance and public documentation ([hippocampus#39](https://github.com/coreyfloyd/hippocampus/issues/39)).
- Add opt-in custom proposal classes declared in local policy; writing opportunities become a user-declared worked example, with legacy records preserved ([hippocampus#40](https://github.com/coreyfloyd/hippocampus/issues/40)).
- Preserve Insights & Highlights in research artifacts and meeting reviews: useful specifics with provenance, dispositions linked to existing rows, and read-back of accepted details before archival (shared definition in `skills/absorb/references/insights-highlights.md`).

Research reports stay in output while work is pending, then retain their excluded
reference lifecycle under `raw/derived/`. Meeting records stay at their original
path. Transcript ingestion, completed absorption and retention are distinct.
Custom classes declare searches, required fields and execution workflows or
destinations in the profile body; undeclared classes cannot be proposed.
Source evidence, attribution, approval, receipts and read-back remain required. Curriculum/playbook changes use maintained document/project routes.

## Compatibility

Profile version remains 4. Existing published profiles need no new fields.
Optional `meeting_record_folder` and `meeting_record_template` default to
`meetings/` and the bundled minimal Markdown template. The three independent
meeting inputs remain optional. The unreleased `meeting_daily_note_path` name
became `meeting_note_path`; published profiles need no migration for it.

`research-absorb` delegates to `absorb`; `research-to-wiki` and `vault-compile`
delegate to `wiki-compile`; `vault-audit` delegates to `wiki-audit`. Existing
artifact-contract links remain supported. Direct authorized compilation accepts
selected primary sources without requiring a research or meeting record.
The retired setup compatibility command is removed only when package-owned.
Unowned skill collisions block installation; custom templates and local policy
remain user-owned. Installation neither relocates existing sources nor performs
live captures. Both Claude Code and Codex receive the same package.

## Verification

Run the exact candidate checks in `RELEASING.md`, including
`python3 tests/test-capture-absorb.py`, the documentation sweeps and the public
commit-range scan. Generator evidence and finding dispositions accompany this
candidate; independent review and evaluation belong to the orchestrator.

The reviewed candidate landed as one squash commit so that earlier candidate
commits carrying private references stay out of the published history; the
public range scan passed on the pushed range. The Insights & Highlights change
was reconciled onto the squash and verified with the same suites.

Previous publication evidence: [0.9.0](docs/releases/0.9.0.md).
Public comparison: [before/after inventory](docs/reviews/2026-10-09-public-documentation.md).

## Release-note draft

Hippocampus v0.10.0 unifies approved research and meeting distribution through
`absorb` and selected primary-source compilation through `wiki-compile`.
Template-driven meeting records start and stay in their configured folder,
use meaningful subjects for new filenames, and preserve existing paths, edits
and confirmed receipts on retries. Original transcripts follow a separate
policy-defined intake/archive lifecycle with verified content and source links.
Completed research reports remain excluded reference artifacts. Research
summaries and meeting reviews preserve Insights & Highlights, the useful
specifics with their provenance and dispositions, and verify that accepted
details actually landed before archival.

Capture and durable research support user-declared custom proposal classes through
local policy, with constrained execution and verified receipts. Writing opportunities
are an opt-in worked example rather than a built-in class. Existing legacy rows
remain readable; new custom rows require a declaration. Intended outcomes
are explicitly accounted for, and retained-source analysis reuses existing
primary evidence. Optional meeting settings and public routing/metadata guidance
are documented consistently. Existing profile version 4 and compiler/absorption
compatibility entry points remain supported; use `hippocampus-set-up` instead
of the retired setup compatibility command. Both supported clients receive the
same package, and installation preserves unowned skills, templates and sources.

## Publication checklist

- [x] Verify and commit the candidate; resolve the public commit-history scan.
- [x] Complete independent review, evaluation and public-communication approval.
- [ ] Merge the reviewed candidate and tag its exact commit as `v0.10.0`.
- [ ] Maintainer signs using `HIPPOCAMPUS_GPG_KEY` and `scripts/build-release.sh`.
- [ ] Verify signed assets, publish, and independently verify downloaded assets.
- [ ] Install and verify the signed release in both supported clients.

No v0.10.0 publication or live installation has occurred in this generator pass.
