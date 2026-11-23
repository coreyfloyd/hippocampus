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

Catch-up then requires an identity it can keep stable and file, and reports an
inventory error naming the file and `open_loops` index for any loop without one.
The error blocks readiness; the handoff's other items are still filed.

- A loop with no `context`, such as `{"what": ..., "owner": ..., "disposition": ...}`,
  cannot be filed.
- A typed item (a session-item `type`) needs its own `session_id` and
  `produced_at`, because the carry step settles it by its own fields.
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
receipt's `disposition` and `settled_at`; a filing judgment supplied for a settled
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
remains unfiled. New tickets require `priority` and `priority_reason`. Catch-up
never creates a ticket (`R5`) for a commitment without `anchor.ticket`: that
commitment stays pending, with a `reason` saying so, until the maintainer sets a
rule, and nothing is written. An anchored commitment files as a ticket comment
(`R2`). Project
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
`status: "dropped"`, and a non-empty `reason`. Only `progress`, `open_loop` and
`artifact` items may be dropped. Knowledge, lessons, decisions, commitments and
untyped loops are filed, never dropped: their drop judgment fails with an error
saying so and writes nothing, and a drop without a reason fails the same way. A
drop writes one settlement receipt (`disposition: "dropped"`, the reason,
`destination: null`, `settled_by: "filing-catchup:<node>"`) through the carry
step's writer into the settled-identity store catch-up reads, so no later
checkpoint or pickup restores the item, an artifact included. The run report
keeps the dropped row with `status: "dropped"`, its `reason`, the `receipt`, the
item and every source, so the item can be recovered; a later report lists the
identity under `already_settled`. A recorded drop counts as settled for readiness.

Copies of one producing identity may differ in `status` and `recorded` hints,
which never prove settlement. Nonconflicting `anchor` fields are combined so a
later ticket or project reference reaches the writer. All original copies and
source paths remain in the report. When copies differ in other content
(proposal text, choices, author, type, record kind, or a missing versus present
field) or name different anchor destinations, the copy from the newest handoff
wins: copies are ordered by each handoff's own `written_at`, never by a file's
name or time. That copy is inventoried and filed, older copies that agree with
it still enrich its anchor, and every older copy that conflicts is listed under
the row's `superseded_copies` with its `source`, `written_at`, `item` and the
`difference`. A superseded copy needs no receipt of its own for the identity to
count as settled. When the conflict cannot be ordered, because a handoff has no
valid `written_at` or the conflicting copies share the newest `written_at`, it
stays an inventory error and blocks that identity before any write; retry keeps
the same refusal and never selects the first proposal.

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
