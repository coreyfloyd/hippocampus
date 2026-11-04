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

At wrap the checklist agent composes the session summary from every history
entry and close outcome in the chain, storing it in `resume.session_summary`.
Record writes never compose or replace it. A standalone record run does not
compose a wrap summary or print a wrap report.

Projects requests additionally receive `session_summary`, `close_outcomes`, and
`touched_projects` from the handoff's resume block. These fields are outside the
item identity and are passed unchanged to both lookup and write. Project items'
`anchor.project` references join the carried `resume.touched_projects`; the ledger
retains these through compaction and pickup. The agent files project session-log
items after the wrap summary is ready, so project history describes the whole
chain. At wrap project writes run after ticket writes and a successful touched-ticket
read. A failed reread makes project items pending without lookup or write. New
close outcomes also block project writes until the agent rewrites the summary;
the returned `resume.summary_rewrite_required` keeps that requirement across
retries. Keep the returned payload and reuse unchanged item identities.


## Ticket reads and close outcomes

Record every ticket read, changed, or closed as touched as it happens, including
reads through the record-read binding. Both tools use the shared ledger command:

```bash
python3 <package>/scripts/lib/handoff.py ledger-ticket --session-id <current-session> \
  --ticket <durable-ticket-reference>
```

The shared tool hook also records a string `ticket` or a `touched_tickets`
array of references from structured tool input or output. For tools without
these fields, call the ledger command for every ticket read, changed, or closed.
Keep one stable reference per ticket. Ticket items' `anchor.ticket` is recorded
automatically when the package files them. No provider-specific command parsing
or ticket discovery runs in the package.

A ticket write or found lookup may additionally return `tickets`, an array of
states for every ticket it read, changed, or closed. Each state has `ticket`
(the same stable reference) and `state` (`open` or `closed`). A closed state
must include `close_outcomes`, empty when it has no milestone or epic:

```json
{"ticket": "https://github.com/example/project/issues/7", "state": "closed",
 "close_outcomes": [
   {"kind": "milestone", "title": "Launch", "state": "closed", "done": 4, "total": 4},
   {"kind": "epic", "title": "Session records", "state": "open", "done": 3, "total": 5}
 ]}
```

The package adds `triggering_ticket` and `produced_at` to each close outcome,
using the optional state's `closed_at` timestamp or the current time, and writes
it to the session ledger immediately. Lookup must return the ticket facts with
a reused receipt too. Checkpoint retains ledger facts in `resume.close_outcomes`
and `resume.touched_tickets`, so compaction needs no agent-supplied copy.

At wrap, `file` also sends the ticket record write exactly
`{"operation": "read", "kind": "tickets", "tickets": [<touched references>]}`.
It must return `{"status": "read", "tickets": [<one state per requested ticket>]}`.
It re-reads only those tickets, including any references carried in the handoff.
Return the milestone and epic state already reported with each ticket; do not
query any other ticket, milestone, or epic. A failed or malformed read fails
wrap and retains the handoff. `record` alone does not do this wrap re-read.
Every closed-ticket response must supply a valid `close_outcomes` array, even
when that ticket already has stored outcomes. Both a reported close and a wrap
re-read validate all returned outcomes before adding any of them. Individual
outcomes matching the same triggering ticket, kind, title, state, done, and total
are reused with their original time; distinct outcomes are added, including for
an already-recorded ticket. With no touched tickets no read is made.

The report's first field, `outcome_line`, is composed only from stored close
outcomes. With none it is exactly: "No milestone or epic closed or moved this
session." The agent-authored summary stored in the final handoff follows in the
next field.
