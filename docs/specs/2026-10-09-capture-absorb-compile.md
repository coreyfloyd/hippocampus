# Template-driven capture, shared absorption and wiki compilation

## Problem Statement

Meeting capture currently distributes information without a persistent configurable meeting record. Research to Wiki and the vault-local compiler duplicate wiki-writing behavior, while research absorption and conversational capture duplicate distribution responsibilities. Users need one understandable lifecycle for capturing evidence, reviewing proposed changes and executing approved updates.

## Solution

Create meeting records directly in a configured meeting folder using a user-selected Markdown template. Provide a small public example; Corey’s richer coaching format remains private. Introduce absorb as the shared approved-plan executor and wiki-compile as its wiki-writing dependency, retaining compatibility entry points for existing commands. Research artifacts keep their existing output-to-retained-reference lifecycle; meeting records remain in place.

## User Stories

### S1 — Keep a configurable meeting record
- A user can select a default meeting-record folder and Markdown template through the profile, and override the template for one capture.
- The record is created directly in that folder and retains its path through capture, review, partial execution and completed absorption. It is never staged in output or archived as a replacement for its primary sources.
- The bundled example includes identity/date, sources and coverage, summary, decisions, actions, writing opportunities, proposed changes, open questions and execution results; coaching is optional template content.
- Transcript, calendar event and meeting-note adapters remain independent. Local paths or Google Docs links remain accepted as note inputs, without requiring a common notes directory.
- A provider-returned calendar event URL is saved and linked when available; missing links or inputs are reported, not fabricated.
- Repeated capture reuses the record/source by source identity and preserves user edits and prior execution results.
- An explicitly selected missing or invalid template fails clearly instead of silently substituting the example. Relative paths resolve from the configured knowledge root; explicit absolute template paths are accepted. Record folders remain within the configured knowledge root.
- Public examples, tests and docs contain no private names, transcript excerpts or machine paths.

### S2 — Absorb an approved plan across destinations
- absorb accepts supported research artifacts and meeting records, validates their source-linked proposed changes and executes only authorized rows.
- Shared row semantics cover wiki changes, named document changes, owned actions, writing opportunities and explicit retention/discard decisions; custom templates need not use the research artifact’s headings.
- Authorization already given is carried through; only changed scope, missing facts or destination-required confirmation produces a further approval request.
- Approved wiki rows call wiki-compile using selected primary evidence, never the generated record as independent evidence.
- Project, context, content and task writes use the target’s configured workflow and rules. Context confirmation, authored prose ownership and task deduplication/read-back remain intact.
- Each row records completion, pending work or explicit decline. A retry reuses confirmed results and never recreates already-confirmed tasks or source records.
- Meeting absorption updates the record in place. Research absorption retains the existing completed-artifact filing rule. Source ingestion status remains distinct from complete capture/absorption.
- Original transcripts keep a separate policy-configured raw intake/archive lifecycle: complete routes permit retention filing, pending routes retain intake, references are repaired and no different source is overwritten.

### S3 — Use one wiki compiler and audit implementation
- wiki-compile is the canonical compiler for selected primary sources. research-to-wiki and vault-compile delegate to it as compatibility entry points rather than maintaining independent synthesis rules.
- Explicit inbox/backlog triage selects a coherent source subset before compilation; there is no automatic whole-library sweep or approval expansion.
- Direct authorized compilation remains supported without first manufacturing a meeting/research artifact.
- Existing wiki-disabled behavior, blind drafting/source comparison, privacy, tension/gap checks, local page conventions, links/indexes and ingestion tracking remain supported.
- wiki-audit remains opt-in and read-only; vault-audit becomes a compatibility entry point. Local mode thresholds and coverage expectations come from policy rather than being discarded.

### S4 — Preserve packaging, clients and migration
- Both Claude Code and Codex receive the same package skills, templates and contracts through normal installation.
- research-absorb remains a deprecated wrapper around absorb. Existing research artifact links continue resolving, including the former artifact-contract reference path.
- No installer overwrites an unowned local skill or custom template; collisions remain explicit. Migration docs explain local compiler/audit policy and wrapper replacement after installing a signed release.
- README, public images/diagrams, the existing presentation, profile/setup instructions, installation/migration docs, contracts and architecture references agree on names, record shapes, execution and filing.
- Render the finished README, images and presentation with an explicit before/after change inventory for the maintainer’s public-communication approval. That approval is a separate delivery gate before publication/release; implementation approval does not supply it.
- Existing profile version 4 remains valid when the new optional settings are absent. Missing optional settings use the bundled minimal template and documented meeting-folder default; setting meeting defaults never creates files during profile validation.

### S5 — Feed source-grounded opportunities into writing
- Meeting capture and durable research skills offer a writing-opportunities route alongside actions, wiki and document changes; no useful opportunity is a valid explicit result.
- Candidates distinguish a new idea from enrichment of an existing idea or a follow-up to already-published material. Search configured ideas, drafts and published records before proposing duplicate ideas; report unavailable publication coverage rather than claiming novelty.
- Each candidate retains source pointers, speaker/author attribution, a proposed angle, target when known, a specific proposed addition, privacy/public-reuse limits and approval/execution state. Another person's idea is not attributed to the user.
- User-specific writing storage, templates, scoring and writing workflows are supplied by profile/local policy. Without a configured writable destination, candidates remain in the meeting/research artifact; do not invent an ideas directory or require the user's taxonomy.
- Capture proposes writing material, not unsolicited first-person drafts or publication. absorb files only authorized candidate rows through the configured writing workflow and preserves authored drafts, published text and target-required confirmations.
- Candidate identities and receipts support retry without duplicate seeds or repeated additions. Meeting candidates remain with the in-place meeting record; research candidates remain in the research artifact until its normal approved retention transition.
- Both meeting and research examples demonstrate new idea, enrichment, already-published overlap and no-candidate cases without private meeting content.

## Data Model

One meeting record describes one meeting with source identifiers, source links, coverage, participants, date, template-derived content, proposed changes and execution results. One distribution row describes one proposed change with stable identity, evidence, target, authorization, timing when relevant and confirmed result. Writing opportunity is a distribution-row kind, identifying a proposed new idea, enrichment or published follow-up and its evidence. Record kind determines retention behavior. Original sources and generated records retain distinct provenance.

## Architecture Decisions

Capture frontends gather evidence and propose dispositions. A shared distribution contract owns approval and execution semantics. absorb orchestrates the plan; wiki-compile owns wiki synthesis. Local policy owns taxonomy, personal templates and task/project adapters. Custom templates control presentation without removing provenance or approval requirements. Compatibility entry points contain delegation only.

## Testing Decisions

Use existing profile, contract, isolated-install and release/tamper suites. Add behavior checks for template selection/path resolution, root containment, absent defaults, preserved profile-version-4 compatibility and install collisions. Run realistic isolated captures/absorption against public or supplied source fixtures with stubbed target workflows: prove stable record location, optional coaching, correct calendar linking, selected-only execution, retry deduplication, wiki-disabled routing, new/enrich/published/no-candidate writing routes, preserved authored prose, writing retry deduplication and separate research/meeting retention. Contract checks must not merely assert heading wording. Swift transcription checks are unchanged but remain part of a future release gate.

## Out of Scope

No live meeting backfill, new personal follow-up tasks, paid consulting scope, changes to authored prose, unrelated open Hippocampus tickets, automatic research-to-wiki ingestion, scheduling, direct messages, production installation or release publication. Existing transcript-filing candidate and all worktrees are preserved; applicable approved filing behavior is reconciled without merging or publishing that candidate implicitly. Version/tag/signing decisions belong to a later authorized release pass.

## Evaluator Rubric

Existing runtime rubric for this pass; a dedicated skills platform and rubric are a separately tracked future workflow change. Feature-specific checks: configuration boundaries, source provenance, scoped authorization, durable results, idempotent external effects, client parity, packaging and documentation consistency.

## Open questions

- [x] Independent spec evaluation: skipped at Corey’s direction on October 9; an independent agent code review of the finished changes is required.

## Further Notes

Scope reflects Corey’s October 9 directions: personal meeting format approved; record created and retained in meeting folder; configurable template with smaller public example; generic absorb coordinates approved changes; one shared wiki compiler with direct invocation and compatibility aliases. Package implementation authorized in chat; this document is the concrete acceptance contract for the development workflow, approved by Corey on October 9, 2026.

October 9 scope amendment: Corey requested writing-opportunity capture for meetings and research, immediate routing using the existing workflow, future dedicated skills dispatch/evaluation setup, and personal meeting backfill beginning with Kate. Live backfill belongs to the vault capture pass, not this public-package implementation. Independent spec review remains skipped; independent code review remains required.

Approval: Corey approved the amended five-story specification on October 9, 2026, and explicitly required README, public images and presentation updates plus review of those finished public-facing pieces before using them for communication. Independent code review is required. No release or production installation is authorized by this approval.
