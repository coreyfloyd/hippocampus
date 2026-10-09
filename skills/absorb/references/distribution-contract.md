# Shared distribution contract

Capture proposes; absorb validates and executes; wiki-compile synthesizes selected
primary evidence. Local policy owns taxonomy, task/document/writing adapters and
transcript retention destinations. Markdown presentation and source provenance
are separate: a custom template may use any headings.

## Record and row semantics

One fenced `hippocampus` JSON block in the record holds `version: 1`, `kind`
(`meeting` or `research`), stable `record_id`, `sources`, parent `decisions`,
`rows`, `history`, `status`, and `writing_result`. Meeting identity comes from
the primary meeting/provider ID or supplied source identity, never a display
name. Source entries hold a stable `id`, root-relative `path` or original `url`,
`primary`, explicit `coverage` (complete/partial/unavailable), attribution and
privacy metadata when known. Local files carry a content digest. Source intake
and ingestion status do not stand in for completed absorption.

Rows carry:

| Field | Meaning |
|---|---|
| `id`, `decision` | Stable operation identity and parent reviewed decision ID |
| `kind` | wiki, document, action, writing, retain or discard |
| `evidence` | Selected source IDs; wiki evidence must be primary raw content |
| `target`, `change` | Named destination and concrete approved change |
| `authorization` | approved, pending or declined, reflecting actual caller authority |
| `preconditions` | Unresolved facts or target-required confirmations; empty when satisfied |
| `owner`, `timing`, `workflow` | Action ownership/timing and local route when applicable |
| `state`, `receipt`, `inflight` | pending/complete/declined, confirmed result, uncertain-effect identity |
| `scope` | Helper-computed digest; changed scope invalidates carried authorization |

Writing rows also require `opportunity` (new/enrich/published-followup), `author`
(speaker/source author, never inferred user ownership), `angle`, `addition`,
`privacy` (reuse limits), and `coverage` with ideas/drafts/published search status
(searched/unavailable). Include exact evidence passages or timestamp pointers,
existing target matches and the search boundaries in the prose proposal. No useful
candidate is an explicit `writing_result` with its basis. A missing writing target
or workflow leaves approved candidates pending in the artifact; availability is
not novelty and private speech is not public-reuse consent.

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
- `plan RECORD --input plan.json`: `decisions`, `rows`, optional `writing_result`.
  Normalize only a plan the caller has seen. Changed existing rows become pending;
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
