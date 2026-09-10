---
name: knowledge-capture
description: Review sources, synthesized findings, and artifacts from the current conversation; propose their complete durable disposition. Use when a user asks to capture knowledge, save research, or add selected material to a configured knowledge base.
---

# Knowledge Capture

Turn conversation knowledge into an explicit, complete disposition. Before proposing or performing a persistent capture, validate `~/.config/hippocampus/profile.md` with `../../scripts/validate_profile.py`, resolved relative to this skill. If it is missing or invalid, stop and use `hippocampus-set-up`; do not choose a fallback destination. Cross-project work uses `artifact_followup_destination`, not the wiki-maintenance route. This skill owns only knowledge preservation and routing; `record-update` owns work records and `harness-improve` owns lessons about the harness. A durable research artifact is processed by `research-absorb`, not by this session-capture workflow.

## Procedure

1. Inventory external sources, synthesized claims, and generated outputs from the conversation.
2. Classify each: discard; retain in `output/`; capture external provenance in `raw/research/`; preserve a reusable synthesis in `raw/derived/`; or, when the profile records the wiki as enabled, compile into wiki knowledge. When the wiki is disabled, this skill offers no wiki classification and stages no provenance for compilation; the other classifications are unchanged.
3. Inventory **named referents** — a person, organization, product, or concept the conversation established as a substantive subject rather than an incidental mention. Propose an entity page for each that clears that bar, resolving its destination and page conventions from local policy; do not invent a taxonomy. Propose nothing when nothing clears the bar. When the wiki is disabled, classify a named referent using this skill's own classifications instead of the wiki — typically preserving a reusable synthesis in `raw/derived/` — resolving its destination the same way from local policy.
4. Reconcile those items with the conversation's decisions and existing knowledge. Present one approval table. Every wiki recommendation is a complete action: capture required provenance **and run `research-to-wiki`**. Never stop at raw staging. A proposed cross-project follow-up names `artifact_followup_destination`.
5. After explicit approval, perform the approved captures and dispatch potentially lengthy `research-to-wiki` work headlessly. Report articles created/updated and the final disposition of every item.

## Boundaries

- Do not create tickets, update project status, or propose harness/rule changes; route those observations to their owners.
- Do not auto-promote. Approval is required before any capture or compile.
- Do not absorb a research artifact here; route it to `research-absorb`, which owns its approval gate and deletion.
