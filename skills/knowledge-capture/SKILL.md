---
name: knowledge-capture
description: Review sources, synthesized findings, and artifacts from conversations or meetings; propose and execute their authorized durable disposition. Use when a user asks to capture knowledge, save research, or add selected material to a configured knowledge base.
---

# Knowledge Capture

Turn conversation knowledge into an explicit, complete disposition. Before proposing or performing a persistent capture, run `python3` with `../../scripts/validate_profile.py` (resolved relative to this skill) and `~/.config/hippocampus/profile.md`. If the profile is missing or invalid, stop and use `hippocampus-set-up`; do not choose a fallback destination. Cross-project work uses `artifact_followup_destination`, not the wiki-maintenance route. This skill owns only knowledge preservation and routing; `record-update` owns work records and `harness-improve` owns lessons about the harness. A durable research artifact is processed by `absorb`, not by this session-capture workflow.

## Meeting inputs

For calls, meetings, supplied transcripts, or connected recordings, read [meeting capture mode](references/meetings.md). It applies the same disposition routes to source-linked people records, coaching/advice observations, existing-document updates, and dated actions. `meeting-capture` is a thin entry point to this same procedure. Honor authorization already present in the user’s request; only unapproved routes or facts needing confirmation require a further question.

## Procedure

1. Inventory external sources, synthesized claims, and generated outputs from the conversation.
2. Classify each: discard; retain in `output/`; capture external provenance in `raw/research/`; preserve a reusable synthesis in `raw/derived/`; or, when the profile records the wiki as enabled, compile into wiki knowledge. When the wiki is disabled, this skill offers no wiki classification and stages no provenance for compilation; the other classifications are unchanged.
3. Inventory **named referents** — a person, organization, product, or concept the conversation established as a substantive subject rather than an incidental mention. Propose an entity page for each that clears that bar, resolving its destination and page conventions from local policy; do not invent a taxonomy. Propose nothing when nothing clears the bar. When the wiki is disabled, classify a named referent using this skill's own classifications instead of the wiki — typically preserving a reusable synthesis in `raw/derived/` — resolving its destination the same way from local policy.
4. Include source-grounded writing opportunities using the shared distribution contract (new ideas, enrichment, published follow-ups or explicit none), with configured ideas/drafts/publication search coverage, attribution and reuse limits. Include source-supported updates to existing non-wiki documents and actionable follow-ups in the disposition table. Resolve destinations from the profile and the target’s own rules. Historical personal preferences are not current context facts without confirmation; never silently write first-person prose. An Action names its owner, route, commitment status, and timing; suggested due dates must be distinguished from source deadlines. Use the configured task workflow to deduplicate, write, and confirm approved actions.
5. Reconcile those items with the conversation's decisions and existing knowledge. Present one disposition table, noting which rows are already authorized and which need approval. Every wiki recommendation is a complete action: capture required provenance **and run `wiki-compile`**. Never stop at raw staging. A proposed cross-project follow-up names `artifact_followup_destination`.
6. After approval (including explicit authorization already given in the request), hand the existing source-linked rows to `absorb` for shared approved execution, including any lengthy `wiki-compile` work. For conversational captures, retain a supported research-shaped distribution artifact only when the caller asked for durable retention; do not manufacture one for direct authorized compilation. Report articles created/updated and the final disposition of every item.

## Boundaries

- Approved Action captures may create or update tasks through the configured task workflow. Do not implement the work those tasks own, perform unrelated project status updates, or propose harness/rule changes; route those observations to their owners.
- Do not auto-promote outside the requested scope. Capture and compilation require authorization, which may already be explicit in the request.
- Do not absorb a research artifact here; route it to `absorb`, which owns its approval gate and archival.
