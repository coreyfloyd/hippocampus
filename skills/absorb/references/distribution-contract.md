# Shared distribution contract

Capture proposes; absorb validates and executes; wiki-compile synthesizes selected
primary evidence. Local policy owns taxonomy, task/document/custom-class adapters and
transcript retention destinations. Markdown presentation and source provenance
are separate: a custom template may use any headings.

New meeting records use a date plus a meaningful meeting title, person or
subject (for example, `2026-10-09-public-contract-review.md`). Provider names
and kind suffixes such as `-transcript` belong in source provenance metadata,
not automatic title decoration. Retained transcripts use a meaningful subject;
a transcript and its record may share a filename in different folders.
Identity lookup reuses existing records and preserves user edits and paths,
even when a title changes on retry. Different meetings with the same title get
a stable identity suffix; filing refuses to overwrite different source content.

## Record and row semantics

One fenced `hippocampus` JSON block in the record holds `version: 1`, `kind`
(`meeting` or `research`), stable `record_id`, `sources`, parent `decisions`,
`rows`, `history`, `status`, and optional `class_results`. Meeting identity comes from
the primary meeting/provider ID or supplied source identity, never a display
name. Source entries hold a stable `id`, root-relative `path` or original `url`,
`primary`, explicit `coverage` (complete/partial/unavailable), attribution and
privacy metadata when known. Local files carry a content digest. Source intake
and ingestion status do not stand in for completed absorption.

Rows carry:

| Field | Meaning |
|---|---|
| `id`, `decision` | Stable operation identity and parent reviewed decision ID |
| `kind` | wiki, document, action, retain, discard or a declared custom name |
| `evidence` | Selected source IDs; wiki evidence must be primary raw content |
| `target`, `change` | Named destination and concrete approved change |
| `authorization` | approved, pending or declined, reflecting actual caller authority |
| `preconditions` | Unresolved facts or target-required confirmations; empty when satisfied |
| `owner`, `timing`, `workflow` | Action ownership/timing and local route when applicable |
| `state`, `receipt`, `inflight` | pending/complete/declined, confirmed result, uncertain-effect identity |
| `scope` | Helper-computed digest; changed scope invalidates carried authorization |

## Local custom-class declarations

In the profile body after YAML frontmatter, optionally add one fenced
`hippocampus-classes` JSON array. The public profile and
[worked example](../../../docs/examples/capture-writing.md) illustrate the shape.
No declarations means no custom proposals. This does not add a frontmatter field.
If the profile names another policy document, read it for local instructions and
place its executable class declarations in this profile block; the helper does
not follow arbitrary Markdown links or load executable code from declarations.

Each declaration has a unique `name` (lowercase letter followed by lowercase
letters, digits, underscores or hyphens; built-in names cannot be overridden),
nonempty unique `search_before_proposing` locations and `required_fields` names,
and a nonempty `workflow` name or `destination` string (or both). Row fields
listed in `required_fields` must be present and nonempty. A row's `search` maps
every declared location to `searched` or `unavailable`; prose records boundaries,
actual matches and uncertainty. Every custom proposal preserves source evidence,
author attribution, privacy/reuse limits, explicit approval and stable identity.
Store optional no-candidate assessments by class in `class_results`.

A workflow declaration selects that exact key in the caller-supplied workflow
map; the row's `workflow` must match. A destination declaration constrains the
row's `target` exactly; when no workflow is declared, the workflow map uses the
class name. If both are declared, both constraints apply. A concrete nonempty
row target is always needed for read-back. Unavailable adapters, missing targets
or route mismatches leave candidates pending. Capture and absorb must not invent
writable destinations or execute through a different route.

The helper binds each new custom row to the declaration's digest (`class_policy`)
inside its approved scope. Changed declarations require replanning and renewed
approval. Removed declarations block pending execution. Existing version-1 rows,
including legacy `writing` rows and `writing_result`, remain readable without
rewriting prose or IDs. An unchanged existing row may be normalized without a
declaration, but a new or changed undeclared row is rejected. Legacy pending rows
require an explicit declaration and replanning before execution; completed
receipts remain readable. There is no built-in legacy execution adapter.

A row cannot complete by staging alone. Wiki/doc rows run inline in their target
workflow; only an Action with that route becomes a follow-up task. Every confirmed
result names its target and receipt; task results include saved dates and route.
Preserve prior receipts as history when scope changes. Declining/removing work does
not erase uncertain external effects: reconcile them first. Retries skip confirmed
results; an uncertain result requires read-back reconciliation before another write.

## Helper interface

Resolve `scripts/distribution.py` relative to the absorb skill. All commands take
`--profile PROFILE`; the validated knowledge root bounds records and retention.
The script prints paths or JSON and exits, with durable state outside the process.
It does not generate prose, search external systems or grant approval.

- `capture --input capture.json`: JSON fields `identity`, `meeting_date`, `title`,
  `sources`, optional `template` and actual provider-returned `event_url`. Reuses
  an existing record by identity without changing its prose, receipts or path.
  Compare new evidence/coverage against the existing record; explicitly update
  source metadata and reapprove affected rows when versions change. It validates
  the selected template even on retry; no silent fallback.
- `prepare-research RECORD --input sources.json`: add shared mechanics to a
  validated legacy artifact, preserving its prose and original execution table.
- `plan RECORD --input plan.json`: `decisions`, `rows`, optional `class_results` (class-name to assessment map); `writing_result` remains a legacy input.
  Normalize only a plan the caller has seen. For a legacy research artifact, optional `legacy_results` maps row IDs to previously confirmed, target-matching read-back receipts; preserve the original table and adopt those results without reexecuting them. Uncertain writes still require reconciliation, and changed scope cannot inherit a legacy receipt. Changed existing rows become pending;
  a subsequent plan update records renewed authorization after approval. Existing
  receipts remain; pending removed rows must first be explicitly declined.
- `execute RECORD --workflows workflows.json`: map kinds to explicitly authorized
  local executable argv arrays. Never invent an adapter or use a shell string.
  Workflows receive one JSON request on stdin with the row, selected sources,
  record, knowledge root, configured task route and stable idempotency key. They
  own destination rules, deduplication and read-back. Return JSON with
  `confirmed: true`, `target` matching the row, and nonempty `receipt` only after
  read-back; include external IDs, dates, links and source ingestion results.
  Failed/unconfirmed writes stay inflight and cannot automatically repeat.
- Agent-tool route: use `execute` with a local preparation adapter that returns
  `confirmed: false` **without writing** to persist the inflight identity. Then
  run the authorized destination workflow with that key and read back. `reconcile
  RECORD --row ID --input result.json` records a confirmed receipt; alternatively
  `absent: true` plus nonempty `checked` evidence clears inflight for a safe retry.
  Neither operation supplies missing approval or target-required confirmations.
- `finalize RECORD --reference PATH ...`: meeting stays in place; completed
  research moves from output to raw/derived with exclusion metadata and links
  repaired. Reference arguments are an explicit discovered set, not permission
  to sweep the library or rewrite authored prose.
- `file-source RECORD --source PATH --retained-folder raw/... --reference PATH ...`:
  after terminal routes, retain the original raw source independently of the
  meeting record. Discover all affected references/manifests under local policy
  first; use their owning workflow for remote receipts and authored targets.
  Verify them afterward. On a collision choose a distinct authorized filename
  or reconcile identical versions; never overwrite different source content.

The helper checks deterministic mechanics. Agent instructions still own source
reading, semantic evidence sufficiency, approvals, context confirmation, authored
prose, adapter selection and complete reference discovery. A test with a stubbed
workflow proves the dispatch/receipt seam, not external-provider permissions.
