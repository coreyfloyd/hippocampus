---
name: knowledge-capture
description: Capture sources and synthesized knowledge from the current conversation or meetings, proposing their authorized durable disposition. Use for session knowledge and meeting records; existing durable research artifacts go to absorb, and direct selected-source compilation goes to wiki-compile.
---

# Knowledge Capture

Turn conversation knowledge into an explicit, complete disposition. Before proposing or performing a persistent capture, run `python3` with `../../scripts/validate_profile.py` (resolved relative to this skill) and `~/.config/hippocampus/profile.md`. If the profile is missing or invalid, stop and use `hippocampus-set-up`; do not choose a fallback destination. Cross-project work uses `artifact_followup_destination`, not the wiki-maintenance route. This skill owns knowledge preservation and routing. Project work records use the caller’s own workflows; agent-rule maintenance belongs to `improve-harness`, which the checklist runs as its own step. A durable research artifact is processed by `absorb`, not by this session-capture workflow.

## Meeting inputs

For calls, meetings, supplied transcripts, or connected recordings, read [meeting capture mode](references/meetings.md). It applies the same disposition routes to source-linked people records, coaching/advice observations, existing-document updates, and dated actions. `meeting-capture` is a thin entry point to this same procedure. Honor authorization already present in the user’s request; only unapproved routes or facts needing confirmation require a further question.

## Procedure

1. Inventory external sources, synthesized claims, and generated outputs from the conversation.
2. Classify each: discard; retain in `output/`; capture external provenance in `raw/research/`; preserve a reusable synthesis in `raw/derived/`; or, when the profile records the wiki as enabled, compile into wiki knowledge. When the wiki is disabled, this skill offers no wiki classification and stages no provenance for compilation; the other classifications are unchanged.
3. Inventory **named referents** — a person, organization, product, or concept the conversation established as a substantive subject rather than an incidental mention. Propose an entity page for each that clears that bar, resolving its destination and page conventions from local policy; do not invent a taxonomy. Propose nothing when nothing clears the bar. When the wiki is disabled, classify a named referent using this skill's own classifications instead of the wiki — typically preserving a reusable synthesis in `raw/derived/` — resolving its destination the same way from local policy.
4. Include source-grounded custom proposal classes only when declared in local policy using the shared distribution contract; when none is declared, propose none. Search the declared locations, report coverage, include required fields, attribution and reuse limits, and preserve approval gates. Include source-supported updates to existing non-wiki documents and actionable follow-ups in the disposition table. Resolve destinations from the profile and the target’s own rules. Historical personal preferences are not current context facts without confirmation; never silently write first-person prose. An Action names its owner, route, commitment status, and timing; suggested due dates must be distinguished from source deadlines. Use the configured task workflow to deduplicate, write, and confirm approved actions.
5. Reconcile those items with the conversation's decisions and existing knowledge. Present one disposition table, noting which rows are already authorized and which need approval. Every wiki recommendation is a complete action: capture required provenance **and run `wiki-compile`**. Never stop at raw staging. A proposed cross-project follow-up names `artifact_followup_destination`.
6. After approval (including explicit authorization already given in the request), hand the existing source-linked rows to `absorb` for shared approved execution, including any lengthy `wiki-compile` work. For conversational captures, retain a supported research-shaped distribution artifact only when the caller asked for durable retention; do not manufacture one for direct authorized compilation. Report articles created/updated and the final disposition of every item.

## Auto-apply

This section applies only when the checklist's `plan` returns `auto_apply.knowledge: apply` (the
`auto_apply_lessons` setting is on), in attended and unattended runs alike. Meeting mode, research
workflows and `absorb` are unchanged. With the setting off, follow the Procedure above exactly.

Run steps 1 to 5 as above, but do not wait for approval of these rows:

- **Wiki** (the profile records the wiki as enabled): capture the provenance and run `wiki-compile`.
- **Source or output**: retain it under `raw/` or `output/` in the knowledge root.

Every other row keeps today's approval: discards, destinations outside the knowledge root,
Actions for other people, document updates and custom proposal classes. A **fact about the
user** (a preference, habit or circumstance) is never written without the user: it becomes an
ordinary ask. Add any new knowledge item to `session_items` in `<remaining-items>`, then write one
row per captured item or fact. `index` counts `resume.open_loops`, then unrecorded `session_items`:

```json
[{"index": 0, "capture": "wiki", "created": ["wiki/topic.md", "raw/research/source.md"], "updated": ["wiki/index.md"]},
 {"index": 1, "capture": "source", "created": ["raw/derived/synthesis.md"]},
 {"index": 2, "capture": "user_fact", "text": "Proposed text", "destination": "Where it would go",
  "source": "Where in this conversation it came from", "choices": ["save", "edit", "discard"],
  "approve": "save"}]
```

`capture` is `wiki`, `source`, `output` or `user_fact`. Paths are relative to the knowledge root or
absolute inside it. List every file the capture wrote, all during this wrap: a wiki capture writes
under `wiki/` and `raw/` plus the two files `wiki-compile` writes after a compile, the profile's
session cache (`hot_file`) and operation log (`operation_log_file`); a source writes only under
`raw/`; an output only under `output/`. A fact about the user has no default.

```bash
python3 <checklist-module> apply-knowledge --user-profile <user-profile> \
  --repository-profile <repository-profile> --knowledge-profile <knowledge-profile> \
  --handoff <remaining-items> --knowledge <rows>
```

Keep its output as `<remaining-items>`; `knowledge_outcomes` says what happened to each row. A
captured item is settled. A file outside the knowledge root or its kind's files, missing, or
not written since the checklist's `plan`, fails: the item stays carried and keeps its approval. Each `knowledge_asks` payload goes to the ask
binding through an R4 row with `destination: "ask"` and its choices; the fact stays carried until
the user answers. The row that then settles it, a filing row or a later capture row, carries
`answer` with the choice the user picked. Only the row's `approve` choice saves the fact: a
capture row or a `filed` filing row needs it, and any other answer settles the fact only by
dropping it, with nothing written. For "edit", write a new `user_fact` row with the edited
text; it asks again. The module refuses a row without the answer its action needs. Report
the articles created or updated from `knowledge_outcomes`.

## Boundaries

- Approved Action captures may create or update tasks through the configured task workflow. Do not implement the work those tasks own, perform unrelated project status updates, or propose harness/rule changes; route those observations to their owners.
- Do not auto-promote outside the requested scope. Capture and compilation require authorization, which may already be explicit in the request, or the auto-apply setting for the rows its section names.
- Do not absorb a research artifact here; route it to `absorb`, which owns its approval gate and archival.
