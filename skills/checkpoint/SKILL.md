---
name: checkpoint
description: Write and lint the current interactive session's handoff, then print a short paste block for resuming it. Use when the user runs /hippocampus:checkpoint or asks to checkpoint a session now.
disable-model-invocation: true
---

# Checkpoint

Write the handoff for the current subject now. Do not ask which form to produce.

The record is primary. Carry every session item the record does not yet hold; do not
require reconciliation or persistence before checkpointing. Never commit, merge, or push
as part of a checkpoint. Do not carry a live ticket list, project status, runtime posture,
or monitor doctrine.

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
