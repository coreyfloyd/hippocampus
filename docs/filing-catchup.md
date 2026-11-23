# One-time catch-up before periodic filing

A catch-up pass is separate from a sweep: it files carried items even when their
sessions are open, without archiving handoffs, changing ledgers, removing
worktrees, or enabling a scheduled job. Both tools use the same Python command.
Run it locally on each node against that node's explicitly supplied handoff
store. Do not infer completion on other nodes from one report.

```sh
python3 scripts/lib/filing_catchup.py inspect \
  --node example-node --store /fixture/handoffs \
  --cutoff 2026-11-19T12:00:00Z --user-profile /fixture/profile.json \
  --report /fixture/catch-up-inspect.json
python3 scripts/lib/filing_catchup.py run \
  --node example-node --store /fixture/handoffs \
  --cutoff 2026-11-19T12:00:00Z --user-profile /fixture/profile.json \
  --decisions /fixture/filing.json --report /fixture/catch-up-run.json
```

Use actual operator-supplied paths; these are examples. The command reads no
knowledge root or provider transcripts. The profile and all binding commands
must be explicitly supplied and authorized. Inspect writes only its report and
returns 1 until a run proves readiness. Reports must be outside the handoff store.
Keep each dated report; give retries a new report path and the same cutoff.

The inspect report lists unique items with immutable `identity`, original item,
and every source path. `unique_items` counts every carried identity older than
the cutoff, settled or not.

Catch-up lists open loops with the sweep's own reader (`sweep.carried_items`):
every loop is an item, whatever its `type`. Both read a null
`resume.open_loops` in an existing handoff as no items, with a warning; catch-up
names the file only when its `written_at` is not after the cutoff. Any other
non-array `open_loops` is an inventory error. Writers still refuse a null list.

Catch-up then requires an identity it can keep stable, and reports an
inventory error naming the file and `open_loops` index for any loop without one.
The error blocks readiness; the handoff's other items are still filed.

- An empty loop (no `type` and no `context`, such as `{"what": ..., "owner": ..., "disposition": ...}`)
  is named by its handoff's own fields: its session (`subject.session_id`, else
  `session_id`), its valid `written_at`, and its position, as the text
  `open_loops[N]`. A handoff without that session or time leaves it an error.
- A typed item (a session-item `type`) needs a `context` and its own `session_id`
  and `produced_at`, because the carry step settles it by its own fields; a typed
  item without context is an error, never an empty loop.
- Any other loop takes a missing session from its handoff's `subject.session_id`
  and a missing time from its `written_at`. The sweep falls back further, to the
  file's name and modification time; catch-up never does, so touching or copying
  a file never changes an identity or the cutoff decision.

Catch-up reads the settled-identity store the carry step reads:
`settled-identities.jsonl` in `HANDOFF_LEDGER_DIR`, else in the parent directory
of `--store`, and reads it the same way: a row settles the identity (producing
session, time, type and text) named by its valid `identity`. A settled identity is
never filed and never counted in `unfiled_before_cutoff`, and its receipt wins over
conflicting carried copies. Copies of one session, time and text with different
types are settled only when every type has a receipt. The report lists one
`already_settled` entry per settled type, with the identity, type, and the
receipt's `disposition` and `settled_at`, and for a drop its `reason`; a filing judgment supplied for a settled
identity is listed under `ignored_decisions`.

`run` reads the store again before each write and skips an identity settled by
then, giving its row `status: "already_settled"`. The recount reads it once more:
a row this run never tried to write whose identity is now settled gets the same
status and no error; a row with an attempted write keeps its status and error and
gains a `recount_note` that the identity is now settled.

Every line the carry step skips (blank, undecodable, unparseable, not an object,
or with no valid identity) settles nothing and is one `warnings` entry giving the
count and the first 20 line numbers. A settling row that fails another receipt
check still settles, as for the carry step, and is warned about only when it
settles a carried identity. Warnings never block writes or readiness. Only an
unreadable store is an error: it blocks readiness and stops every remaining `run`
write, leaving each item pending with `settled store unreadable; no write
attempted`. A missing store has no receipts and no error.

A decisions file is an array with one object per identity:

In `run`, an omitted status requests filing, as in the example below. An explicit
pending, dropped, failed, uncertain or read-failed judgment remains unfiled and
never authorizes a write. Only an ask-bound pending row with the explicit
`ask_delivery: "requested"` request may deliver its approval ask; its actual
receipt still governs completion. Native ask delivery is not a capture receipt.

```json
[
  {
    "identity": {"session_id": "producer", "produced_at": "2026-11-18T12:00:00Z", "text": "Record the completed work"},
    "rule": "R2",
    "read_status": "ok"
  }
]
```

Supply the shared filing rules' judgment and read evidence; a missing judgment
remains unfiled. New tickets require `priority` and `priority_reason`. A
commitment files only as a ticket comment (`R2`) through `tickets` on its
`anchor.ticket`, which must be a non-empty string. Without one, catch-up never
files it under any rule or binding (ask, documents, projects, scheduled jobs or a
new ticket): it stays pending, with a `reason` saying so, until the maintainer
sets a rule. An anchored commitment judged any other way fails with an error
saying commitments file only as anchored R2 comments. Neither writes anything.
Durable checkpoint asks keep the wrap's routes. Project
writes require `session_summary`, and accept `close_outcomes` and
`touched_projects`. Decision documents require the existing explicit user
approval, author/source and configured folder safeguards. Agent operational
choices remain audit material. Route items needing approval through `R3` with
full proposal text and `choices`; configure `ask.owner_agent` first. Native
lesson/knowledge work without a capture receipt remains unfiled: route an
approval proposal to the ask owner rather than claiming capture.

Record writes reuse lookup-before-write and identity receipts. For this pass,
the ask command implements the same `lookup` / `write` request protocol as record
writes, using `kind: "asks"` and the full owned ask as `item`. Its receipt must
confirm the exact identity, destination and saved `owner_agent`. A failed lookup
never writes; an uncertain write retries by lookup, including after interruption.
No supplied receipt alone bypasses the writer.

A drop judgment uses the wrap's drop rules, `R1` or `R6`, with no status or
`status: "dropped"`, and a non-empty `reason`; it passes the same checks as at a
wrap, so an `R1` drop needs `read_status: "ok"` unless it is `information_only`. Only `progress`, `open_loop` and
`artifact` items may be dropped. Knowledge, lessons, decisions and commitments
are filed, never dropped, and an untyped or empty loop is dropped only by a
receipt (below): a run's drop judgment for any of them fails with an error and
writes nothing, and a drop without a reason fails the same way. A
drop writes one settlement receipt (`disposition: "dropped"`, the reason,
`destination: null`, `settled_by: "filing-catchup:<node>"`) through the carry
step's writer into the settled-identity store catch-up reads, so no later
checkpoint or pickup restores the item, an artifact included. The drop counts
only when the store then settles the identity as this drop; if another receipt
settled it first, the row fails with an error naming that receipt's disposition.
The run report
keeps the dropped row with `status: "dropped"`, its `reason`, the `receipt`, the
item and every source, so the item can be recovered; a later report lists the
identity under `already_settled`. A recorded drop counts as settled for readiness.
The recount compares a dropped row with the current copies, read without
receipts, as it does a filed row: changed content gives a `recount_error` and
leaves the identity unfiled, and the identity is removed from `already_settled`.

Untyped and empty loops are never filed: each is dropped with a recorded reason.
Such a row's `identity`, repeated as its `receipt_identity`, adds a reserved
`type`: `untyped_loop` for a loop with context but no session-item type, or
`empty_loop` for an untyped loop without context, so an empty loop and an
untyped loop of the same text are never one row. Settle it with a receipt naming that
identity, `disposition: "dropped"` and the reason, through
`handoff.py settle-identity --receipts FILE`, the carry step's own writer and
store; any other disposition is refused as invalid, and a store row with another
disposition settles nothing. The next report lists the loop under `already_settled`
with the receipt's `reason`. The sweep never files a loop so settled, reading the
settled-identity store beside its handoff store; the handoff's report row gives the
number it skipped as `settled_loops`. A run reads the store again before each write:
a loop settled by then is `already_settled`, and a run judgment for a loop still
unsettled fails, saying so. The sweep's own legacy path is unchanged: a loop in a
handoff without a valid `written_at` has no receipt identity, so the sweep keeps
filing it under its fallback identity while catch-up reports it as a loop error.

The session and time that name such a loop must be non-blank strings, and the
time an ISO time with a timezone, exactly as a valid receipt requires. An untyped
or empty loop without them has no receipt identity and is a loop error, never
filed by its handoff's other identity. The error says whether the producing time
is missing or present but not an ISO time with a timezone.

Three limits follow from naming a loop by its handoff. An empty loop's identity
names a slot, its position in one handoff write, not its content: a rewrite gives
it a new `written_at`, and a move gives it a new position, so a new identity that
the earlier drop does not settle. Two different empty loops in the same slot of
handoffs with the same session and `written_at` share one identity and are
reported as conflicting copies. And the carry step skips a dropped loop only when
the loop carries its own `session_id` and `produced_at`; an untyped loop named by
its handoff, and every empty loop, are left to the carry step unchanged, since a
live session that writes the loop again writes it in a handoff after the cutoff.
None of this reaches catch-up, which reads only handoffs written before the
cutoff, whose sessions no longer write them.

Copies of one producing identity may differ in `status` and `recorded` hints,
which never prove settlement. When copies otherwise agree, nonconflicting
`anchor` fields are combined so a later ticket or project reference reaches the
writer. All original copies and source paths remain in the report. Any copy
whose `anchor` is present but not an object is an inventory error: it is never
superseded or filed. When copies differ only in their anchor destinations or
proposal text (`choices`, `ask_text`), the copy from the newest handoff wins:
copies are ordered by each handoff's own `written_at`, never by a file's name
or time. That copy, with its own anchor, is inventoried and filed. Each older
copy is compared with it alone; one that differs is listed under the row's
`superseded_copies` with its `source`, `written_at`, `item` and the differing
fields, and its anchor never merges into the filed copy. Superseded copies share
the newest copy's type and text, so one receipt for that carry identity settles
all of the identity's copies. Copies that differ in `type` or any other
field that decides filing (author, record kind, decision record, location, or a
missing versus present field) stay an inventory error, so a filed type is never
superseded by a droppable one. Two artifacts of one session and `produced_at`
with different locations share an identity, so catch-up neither drops nor
settles either and reports an error saying so. A conflict also stays an error
when it cannot be ordered, because a handoff has no valid `written_at` or the
conflicting copies share the newest `written_at`. An error blocks that identity
before any write; retry keeps the same refusal and never selects the first
proposal.

Exit 0 requires `ready_for_durable_filing: true`: every older identity has a
confirmed destination for its eligible content or a recorded drop, and there are
no inventory errors.
The final recount scans the entire store again. Checkpoint timestamps, new or
rewritten newer-only handoffs, and changes to newer items do not block readiness.
Changed older proposals or destinations invalidate readiness; newly discovered
older identities remain pending for retry. Failed initial items remain counted
even if a concurrent checkpoint omits them. Source snapshots remain in the
report for audit, rather than requiring whole-file equality. Missing stores,
malformed handoffs, conflicting copies that cannot be ordered, unbound destinations and failed writes
block readiness. Newer items remain for periodic filing. The report is saved before effects and after each result. Source
handoffs and dated history remain untouched, including on failure.

The coordinator must retain a successful report for **every expected node**, with
one fixed cutoff, before enabling 4-hourly filing. This command enables nothing.
Real cross-node recount, delivery of real approval asks, and job enablement are
separate coordinated acceptance proofs. Until those proofs pass, keep the old
filing path. Roll back the package change by reverting its commit; external writes
and delivered asks retain their receipts and are not automatically reversed.
