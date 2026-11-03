---
name: record
description: "Run the package record step mid-session or during checklist, filing session items through per-kind record writes."
---

# Record

Run this package step on its own before compaction or when asked to record
progress, or as checklist's first step. Claude Code uses `/hippocampus:record`;
Codex uses the discovered `record` skill. Both use the same module and contract.
Running it alone never runs knowledge, lessons, persist, or the rest of checklist.

Resolve the user and repository profiles as checklist does. Apply checklist's
ordered filing rules to carried open loops and unrecorded `session_items`.
A commitment is a session item; apply the same rules, with no separate pass.
Preserve each item's original `session_id`, `produced_at`, and complete `context`.
Capture these once when the item is produced; never regenerate them on retry,
wrap, compaction, or resume. Missing identity fields fail the write and keep it.

Choose the rule, read evidence, priority where needed, and destination kind.
`record_kind` on an item or filing row is one of `tickets`, `projects`,
`documents`, `scheduled_jobs`; R7 defaults to documents, R2/R5 to tickets.
Commitments with `time`, `scheduled_at`, `due_at`, or `recurrence` use
scheduled_jobs when bound, otherwise tickets. User decisions still go to ask;
R1 and R6 still drop with a reason; knowledge and lessons keep their native steps.
Read-dependent rules require a successful record read before any write.
Do not invent a successful read when the binding is unavailable.

```bash
python3 <package>/scripts/lib/checklist.py record --user-profile <profile> \
  --handoff <items.json> --filing <outcomes.json>
```

Use checklist's `file` operation at wrap; it runs the same record writes.
The module executes commands and returns the updated handoff payload, including
its filing report, on stdout even when a write fails. Preserve that payload
through checkpoint before reporting an error. Never run record-write commands
separately or use numeric `settle` acknowledgements for record items.
With no command for a kind the item stays carried with a warning; it does not
fail the wrap. Bound failures or uncertain writes keep the item and fail wrap.
No store is supplied by the package.

The user profile's optional `record_writes` object maps each kind to
`{"command": ["executable", "argument"]}` or a shell-quoted command string.
Commands are executables, not slash skills; the module parses strings as argv
and never runs a shell. Null or omitted kinds are unbound. Repository profiles
cannot bind record writes. The retired `bindings.record` shape is refused.

Every invocation reads one JSON request on stdin and writes one JSON response
on stdout. A request contains `operation` (`lookup` or `write`), `kind`, the
complete `item`, the chosen `filing` row, and `identity`:
`{"session_id": "producer", "produced_at": "original time", "text": "original context"}`.
Lookup returns exactly `{"status": "not_found"}` or
`{"status": "found", "receipt": {"identity": <same identity>, "destination": "durable location"}}`.
Write returns `{"status": "saved", "receipt": <same receipt shape>}`.
An explicit store rejection returns `{"status": "failed", "error": "reason"}`.
A receipt must match the entire identity and name a non-empty destination.

Before every write the module looks up the identity. A found receipt is reused
without writing. A failed or malformed lookup keeps the item and fails wrap.
If a write ends without a usable receipt (including timeout or invalid output),
its outcome is uncertain. Retry with the unchanged item: lookup must succeed
before another write is attempted. Stores must make identity lookup durable and
make their writes idempotent for that identity, including concurrent requests.

Keep summary composition as checklist currently describes: after the record
writes, retain the composed session-summary file or the reason none was
composed for checklist's report. This standalone step does not print a wrap report.
