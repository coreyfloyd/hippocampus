---
name: absorb
description: Validate and execute authorized source-linked changes in a research artifact or in-place meeting record, with durable row receipts and retry-safe retention.
---

# Absorb

Run `python3` with `../../scripts/validate_profile.py` (relative to this skill)
and `~/.config/hippocampus/profile.md`. If invalid or missing, use
`hippocampus-set-up` before writes. Read the profile body, each target's rules,
and [the shared distribution contract](references/distribution-contract.md).
For research artifacts also read [the artifact contract](references/artifact-contract.md).

Input is one supported research artifact or meeting record and its existing
source-linked plan. Output is each row's confirmed result, pending reason or
explicit decline, plus the retained record/source paths. Do not extract a new
plan from a chat here; capture frontends own proposals. Existing authorization
carries through. Ask only about changed scope, missing facts or destination-required
confirmation; no second generic approval after a caller approved the concrete rows.

## Validate and execute

1. Read the whole record, sources, scope, decision items and prior results.
   Normalize a legacy research table into shared rows without rewriting prose
   or changing its decision IDs. Rows need parent decisions, stable IDs, evidence,
   named targets, concrete changes, authorization and preconditions. Reject orphan
   rows, staging-only outcomes, and generated records offered as primary evidence.
   Custom meeting headings do not change these semantics.
2. Show the actual target changes and uncovered confirmations. Execute only
   approved rows with satisfied preconditions. Keep others pending or declined.
   In runtime use, return the concrete plan to the authorized caller and wait
   for its approval; capturing an artifact does not approve its mutations.
3. Wiki rows stage selected complete extracted evidence, when needed, then call
   `wiki-compile` with only the approved primary subset and existing assignments.
   Summary-only files and Notebook source IDs alone are not raw evidence. When
   the wiki is disabled, stage nothing for compilation and invoke no compiler;
   propose a permitted document route for approval instead.
4. Document rows use the named target's workflow. Project/context/content rules
   remain authoritative: confirm historical claims before promoting them to current
   context, and preserve authored prose. A document update or wiki row executes
   inline; it cannot silently become a task for another session.
5. Action rows use `artifact_followup_destination`, with owner, evidence, next
   action, dependencies and source timing or explained planning dates. Search
   existing tasks, enrich exact matches without losing notes, then read back
   target, content and saved dates. Only confirmed writes complete a row.
6. Writing rows use the configured local writing workflow and writable target.
   Search ideas, drafts and published records again before writing. Apply only
   the authorized seed/addition; preserve attribution and reuse limits. Never
   rewrite an authored draft, publish, or create an invented ideas folder.
   With no available writable route, keep the candidate in the record.
7. Retention/discard rows use their explicitly approved destination/action.
   Default completed research retention is already part of absorption; deleting
   a source or artifact requires an explicit discard direction for that object.

Use [the deterministic helper](scripts/distribution.py) for capture/plan/receipts,
scoped workflow dispatch and filing. It invokes only caller-supplied workflow
argv; it supplies no task, document, writing or wiki integration of its own.
If a destination has only agent tools, follow the same durable protocol from
[the helper interface](references/distribution-contract.md#helper-interface):
persist an inflight identity before writing, read back, then reconcile its receipt.
Never infer success from a tool's attempted write or repeat an uncertain effect.

## Finish and retain

Meeting records stay at their original path. Research artifacts stay in `output/`
while any row is pending; after all rows complete or are explicitly declined,
retain them in `raw/derived/` with absorbed status, date, original path,
`use: artifact` and `compile_mode: exclude`. Never overwrite another artifact.
Repair durable references, including task evidence links through their workflow,
and report the actual retained path. An excluded report is not new primary evidence.

Original meeting transcripts have a separate policy-defined raw intake and archive
lifecycle. Reuse source identity across both. Pending authorized routes keep the
source in intake; compilation ingestion status is not absorption completion.
After every authorized route is terminal, file the original transcript, preserving
bytes, identity, sensitivity and ingestion metadata; repair all discovered durable
references and local manifests, then verify links and content. Missing optional
inputs and documented partial coverage are gaps, not automatic closure blockers.
A different destination source is a collision, never an overwrite. On failed
filing or link repair, report pending, keep intake available, and reconcile before
retrying. The transcript remains primary evidence; the meeting record stays in place.

Report confirmed task dates/targets, compiled or updated documents, writing receipts,
pending confirmations, source coverage and separate record/source retention paths.
Persist using the knowledge store's own Git and delivery rules. No scheduling,
messages, release or publication is authorized by this skill.
