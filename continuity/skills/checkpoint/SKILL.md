---
name: checkpoint
description: Write and lint the current interactive session's handoff, then print a short paste block for resuming it. Use when the user runs /checkpoint or asks to checkpoint a session now.
disable-model-invocation: true
---

# Checkpoint

Write the handoff for the current subject now. Do not ask which form to produce.

The record is primary. Carry every session item the record does not yet hold; do not
require reconciliation or persistence before checkpointing. Never commit, merge, or push
as part of a checkpoint. Do not carry a live ticket list, project status, runtime posture,
or monitor doctrine.

Supply the handoff's judgment-bearing fields: a one-line `resume.headline`, concrete
`resume.next_action`, a one-line `resume.session_summary` of what this session did,
short anchored or disposed `resume.open_loops`, `spawned_processes`, and `suggested_skills`.
Pass all unrecorded session items in `session_items`. Each needs `type` (progress,
commitment, decision, knowledge, lesson, artifact, or open_loop), `context` (at most
600 characters), `disposition`, `session_id` of its producer, and `produced_at` (ISO
timestamp with timezone). Decisions also need `author` and `location` (where decided).
Lessons carry the lesson text in `context`, not a pointer. Only items already saved in
the record may have `recorded: true`; those are omitted. Already-carried items stay in
`resume.open_loops` with their original identity and date until a binding consumes them.
Preserve `resume.session_history` from a resumed handoff, so earlier summaries keep
their producing session's identity. Update `resume.session_summary` to describe the
current session: the module records it under the calling session ID, including when
checkpointing a payload whose subject still names the prior session.

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
