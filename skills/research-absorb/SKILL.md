---
name: research-absorb
description: Validate and execute the approved distribution plan in a durable research artifact. Use after research-sources or research-topic; not for research-feature or research-feedback deliverables, capturing a chat session, or routine task closeout.
---

# Research Absorb

Process one research artifact through its existing proposed distribution plan.
The artifact is coordination material, not an archive: it must reach terminal
dispositions and then be deleted. Read [the artifact contract](references/artifact-contract.md)
and validate `~/.config/hippocampus/profile.md` with
`../../scripts/validate_profile.py`, resolved relative to this skill, before
acting. If it is missing or invalid, stop and use `hippocampus-set-up`; do not
mutate or delete the artifact. Research-derived tasks
use `artifact_followup_destination`, never the wiki-maintenance route.

## Interface

Input: a single durable research artifact with a **How to Absorb** section and its execution appendix.
Output: an approved execution summary that names the final disposition of every
row, then no remaining artifact.

Do not use this to extract knowledge from the current conversation; that is
`knowledge-capture`. Do not perform routine project records, ticket updates, or
harness/rule maintenance. Do not implement code or document changes that a
filed follow-up task should own.

## Validate before approval

1. Read the artifact and validate the artifact's scope, source provenance,
   destinations, and each requested target. Every execution row must derive
   from an item in the artifact's How to Absorb section; a row with no parent
   item is invalid. A row whose only outcome is staging a source is invalid —
   staging is not a terminal disposition. Correct an invalid plan in the
   artifact only with the caller's direction; do not silently invent a new
   destination.
2. Classify each row as ready, blocked, or needing a narrower decision. Present
   the actual changes, raw source staging, and tasks that execution would make.
   Inline-rejected candidates need no per-item confirmation — approval of the
   plan is their explicit discard.
3. Obtain explicit approval before mutations. In HITL, `research-absorb <file>
   and apply all` is sufficient approval only after the caller has seen the
   validated plan. In runtime use, post the artifact link, summary, and its
   existing plan to the originating thread and wait; do not auto-distribute.

## Execute an approved plan

- Wiki Additions and Document Updates always execute inline during absorption;
  they never file a task. Only an Action may be filed as a task for another
  session, and only when its own item says so.
- For a Wiki Addition, place the selected external source material and
  provenance in canonical `raw/research/` when it is not already there, then
  invoke `research-to-wiki` on that curated subset. Do not send the report
  itself to the compiler. Wiki Additions apply only when the profile records
  the wiki as enabled: when it is disabled, the artifact has no Wiki Additions
  class, and this workflow stages no provenance for compilation and never
  invokes `research-to-wiki`.
- Update an explicitly named target document only when the approved row permits
  it and the target's own rules allow the mutation.
- File a research-derived follow-up task when the plan calls for future work.
  File it through `artifact_followup_destination` with its evidence; do not
  perform the implementation in this workflow.
- Mark the actual terminal disposition for every row: integrated, target
  document updated, task filed, or explicitly discarded. If any row cannot
  reach a terminal disposition, the artifact stays blocked until the blocker
  is resolved; it has no retain or archive disposition, and the run is not
  complete.
- When every row has a terminal disposition, delete the artifact and report
  what was integrated, updated, filed, or discarded.

## Runtime seam

The same input and plan work in HITL and future AFK execution. The runtime may
produce the artifact and post its link and plan, but it must wait for the same
approval gate. Scheduling or Slack implementation is outside this skill.
