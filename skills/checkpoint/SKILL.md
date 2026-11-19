---
name: checkpoint
description: Write and lint the current interactive session's handoff, then print a short paste block for resuming it. Use when the user runs /hippocampus:checkpoint or asks to checkpoint a session now.
---

# Checkpoint

Write the handoff for the current subject now. Do not ask which form to produce.

The record is primary. Carry every session item the record does not yet hold; do not
require reconciliation or persistence before checkpointing. Never commit, merge, or push
as part of a checkpoint. Do not carry a live ticket list, project status, runtime posture,
or monitor doctrine.

## Checkpoint with `durable`

When explicitly requested with `durable`, or when this session's configured
FILE-4H job requests it, run the checklist's record, knowledge, lessons, and
persist steps and applicable profile steps, preserving normal approval requirements.
Use [checklist](../checklist/SKILL.md) for profiles, planning, native receipts and
filing judgments. Do not remove worktrees, finish the session, cancel its work,
or release its processes. Preserve its next action. Ordinary checkpoint stays carry-only.

Restore retained items before choosing filing rows. Supply exactly one indexed
filing row for every item, including those restored from earlier checkpoints.
For an ask awaiting the user's answer that must be delivered now, use
`status: "pending"` with `ask_delivery: "requested"`. This explicitly requests
lookup and delivery; it is not a receipt. Plain pending, dropped, failed,
uncertain, and read-failed ask judgments never authorize delivery. A row marked
filed must already have an actual receipt for the item's producing identity and
configured owner. Do not mark a deferred item filed to make a writer run.
Use the [record](../record/SKILL.md) decision-document contract: only user decisions,
explicitly approved, may reach the configured document folder. Without the user,
deliver the full proposal as an R3 ask to the configured durable agent. Promises
become asks. Agent operational choices remain separate audit material.
Run knowledge-capture and improve-harness through their usual approval routes;
keep native items until actual capture/application receipts arrive. An ask receipt
proves delivery, not native capture. Run the persist binding under its existing
authorization; durable mode does not itself authorize git actions. Do not invoke
the wrap's finalization or cleanup.

After those steps, submit the continuation JSON with the shared writer:

```bash
bash <checkpoint.sh> --durable --user-profile <user-profile> \
  --filing <filing-rows.json> --report <pass-report.json> \
  --scheduled-report '<configured-report-adapter-command>' <<'JSON'
<judgment-bearing handoff JSON>
JSON
```

Repeat `--repository-profile` for additive profiles. The command writes and
validates a checkpoint before filing, settles successful items in the ledger,
keeps failed/unbound items, preserves the continuation, and reports actual receipts.
Checkpoint errors, invalid handoffs and no-write keep-warm results still produce
a failed pass report at the supplied writable report path. They never file from
an older handoff. The report retains supplied and ledger-carried unfiled items
and the continuation; a reporting adapter failure also remains explicit locally.
A nonzero exit reports incomplete filing or reporting; retry by original identity.
The report adapter publishes each pass to Scheduled. Without it, the local report
remains and Scheduled visibility is unproven. See the
[scheduler contract](../../INTERFACE.md#durable-checkpoint-and-file-4h).
Claude Code and Codex use this same command and skill; neither creates a timer.

Supply the handoff's judgment-bearing fields: a one-line `resume.headline`, concrete
`resume.next_action`, a real one-line `resume.session_summary` describing the work since this session's
previous history entry,
anchored or disposed `resume.open_loops`, `spawned_processes`, and `suggested_skills`.
Pass all unrecorded session items in `session_items`. Each needs `type` (progress,
commitment, decision, knowledge, lesson, artifact, or open_loop), `context` (at most
600 characters except asks and lessons, whose complete text has no length limit), `disposition`, `session_id` of its producer, and `produced_at` (ISO
timestamp with timezone). Decisions also need `author` and `location` (where decided).
Asks keep their complete `choices` alongside `context`. Lessons carry the full
proposal in `context`: target file and section, proposed text or diff, and evidence,
not a pointer. Preserve all of this through compaction, pickup, and wrap. Only items already saved in
the record may have `recorded: true`; those are omitted. Already-carried items stay in
`resume.open_loops` with their original identity and date until a binding consumes them.
Checkpoint retains each item, other than an artifact, in the session ledger; later
checkpoints, compaction, the stop skeleton and wrap restore it without your supplying it
again, until the wrap files or drops it. Items an earlier checkpoint saved need not be
supplied again; a re-supplied item is held once. Add a lesson as soon as it is learned,
not only at wrap.
Supply new account text on every checkpoint and wrap; never use a placeholder or
fall back to the headline. At wrap, checklist supplies the complete chain's
`resume.session_summary` and a separate one-line `resume.history_entry` for the
work since this session's previous entry. At a checkpoint, the session summary
itself is the one-line account. The module appends one dated history entry under the
calling session ID and keeps earlier entries in its ledger, so compaction does
not require the agent to re-supply them. Carried `resume.session_history` entries
keep their original identities and dates. A missing or blank account fails
validation: checkpoint still writes and reports the failure; wrap fails.
The automatic stop-time handoff is marked `skeleton: true`, adds no history
entry, and retains earlier ledger entries.

Files and published artifacts come from the ledger. Write/Edit hook events record
file paths. After each shell-driven file change, register its path explicitly:

```bash
python3 scripts/lib/handoff.py ledger-file <path> --cwd <checkout> --session-id <session>
```

Do not substitute a checkout-wide dirty-file list. Publishing tools call the single
artifact command:

```bash
python3 scripts/lib/handoff.py ledger-artifact --session-id <producer> \
  --cwd <subject> --location <published-location> --disposition keep
```

Use `remove` to mark an artifact for later removal; checkpoint does not remove it.
Once the record links it, call the same command with `--status recorded`; after actual
removal use `--status removed`. The ledger automatically supplies pending artifacts,
including a resumed session's carried artifacts. Never rebuild that list from memory.

The checkpoint module overwrites `written_at`, `trigger`, the current
subject, and git metadata from the real environment. Its trigger defaults to `checkpoint`;
callers needing another trigger set `HANDOFF_TRIGGER=wrap` or `HANDOFF_TRIGGER=manual`.

Pipe that JSON to the checkpoint module. It resolves the current subject, writes atomically,
lints the result, and prints the required paste block (prior-session banner, handoff location,
and next action):

`<checkpoint.sh>` is `scripts/checkpoint.sh` in this skill's real directory (resolve the
path from where this skill is installed, not from a tool-specific home directory).

```bash
bash <checkpoint.sh> <<'JSON'
<judgment-bearing handoff JSON>
JSON
```

If lint fails, the checkpoint was still written and the command reports the lint failure.
Report that failure; do not imply the handoff is clean.

Close outcomes and touched tickets are also recovered from the session ledger
into `resume.close_outcomes` and `resume.touched_tickets`. Preserve those facts
unchanged; never reconstruct milestone or epic state during checkpoint.

Checkpoint writes never arm or renew a timer. Keep-warm is off by default and
requires the user's explicit `keep-warm on`; see the keep-warm skill. An empty
keep-warm wake writes no handoff, including through context or staleness guards.
The pre-compaction hook preserves real work directly from retained facts and git
state; restore reads that handoff without scheduling anything.
