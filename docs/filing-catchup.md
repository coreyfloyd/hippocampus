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

Catch-up reads the settled-identity store the carry step reads:
`settled-identities.jsonl` in `HANDOFF_LEDGER_DIR`, else in the parent directory
of `--store`. An identity whose producing session, time, type and text have a
settlement receipt is never filed and never counted in `unfiled_before_cutoff`;
the report lists it under `already_settled` with its identity, type, and the
receipt's `disposition` and `settled_at`. The recount reads the store again, so a
receipt written during the run also settles its identity. An unreadable store, or
a line that is not valid JSON or not a valid receipt, is a report error naming the
line; it settles nothing and blocks readiness.

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
remains unfiled. New tickets require `priority` and `priority_reason`. Project
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
No supplied receipt alone bypasses the writer. Drops do not count as filing.

Copies of one producing identity may differ in `status` and `recorded` hints,
which never prove settlement. Nonconflicting `anchor` fields are combined so a
later ticket or project reference reaches the writer. All original copies and
source paths remain in the report. Other item content must agree exactly,
including proposal text, choices, author, type and record kind; conflicting
anchor destinations also block that identity before any write. Missing versus
present proposal fields are ambiguous. Retry preserves the same refusal until
the substantive conflict is resolved; it never selects the first proposal.

Exit 0 requires `ready_for_durable_filing: true`: every older identity has a
confirmed destination for its eligible content and there are no inventory errors.
The final recount scans the entire store again. Checkpoint timestamps, new or
rewritten newer-only handoffs, and changes to newer items do not block readiness.
Changed older proposals or destinations invalidate readiness; newly discovered
older identities remain pending for retry. Failed initial items remain counted
even if a concurrent checkpoint omits them. Source snapshots remain in the
report for audit, rather than requiring whole-file equality. Missing stores, malformed handoffs, conflicting copies, absent provenance,
unbound destinations and failed writes block readiness. Newer items remain for
periodic filing. The report is saved before effects and after each result. Source
handoffs and dated history remain untouched, including on failure.

The coordinator must retain a successful report for **every expected node**, with
one fixed cutoff, before enabling 4-hourly filing. This command enables nothing.
Real cross-node recount, delivery of real approval asks, and job enablement are
separate coordinated acceptance proofs. Until those proofs pass, keep the old
filing path. Roll back the package change by reverting its commit; external writes
and delivered asks retain their receipts and are not automatically reversed.
