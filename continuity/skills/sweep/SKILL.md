---
name: sweep
description: Sweep abandoned sessions in a directory or across the machine, applying filing rules and writing a sweep report. Safe for unattended runs.
---

# Sweep

Use the same procedure in Claude Code and Codex. Resolve the package root from
this skill's actual directory (`../..`); the shared command is
`scripts/lib/sweep.py`. Configuration defaults to watch-only, whose only write is its report. The user
may enable act mode in continuity configuration. The driving agent performs
every binding call through the profile, following each binding's `command` and
`instructions`, the same way the checklist wrap does. The engine journals a
plan and records your results; it never executes bindings. See
[the plan/results contract](../../INTERFACE.md#12-sweep-plan-and-results-contract).
After results are recorded it removes eligible clean, merged linked worktrees
and their local branches and archives completed handoffs. Never write a handoff
for the sweep itself.

Take the requested directory or `all` as scope. If none is given, use the
working directory. Read the user checklist profile at `$CHECKLIST_USER_PROFILE`,
else `checklist/profile.md` under `$XDG_CONFIG_HOME` (default `~/.config`). Omit
`--user-profile` when absent. The existing profile binds `record_read`, the
record/knowledge/lessons slots, and the one ask command; do not invent bindings.

## Inspect and decide

Run the command, replacing the package path and scope:

```bash
python3 <package>/scripts/lib/sweep.py inspect --scope <directory-or-all>
```

Unattended runs use idle time alone with no open-session checks configured.
Configured `open_session_checks` commands protect the union of their reported
session ids; any failed check prevents abandonment across the scope. They never
wait for input. With no configured checks, interactive runs first inspect the available session
surfaces read-only, then pass `--interactive --open-sessions <evidence-file>`
to both inspect and run. Evidence is JSON with `session_ids` (possibly empty)
and `method` (how the session surfaces were inspected). Never claim no open
sessions when inspection failed; report that blocker. No process is closed or
wrapped by the sweep. The report's open idle sessions have the choices `wrap it`,
`leave it`, `close it`; present these directly to the user after writing the
interactive report. With configured checks, `--interactive` uses their results;
additional agent evidence is optional. Do not wait before completing the report.
In act mode completion records the activity at which each open-session ask was
raised or presented, and suppresses repeats until a newer handoff or transcript
write. Watch-only proposes asks without recording them as raised. Never read
ask answers or interpret them as permission to wrap or close a session.

Before choosing filing rules for an abandoned session, check each item's
`identity_occurrences`, the number of copies of its identity in that handoff.
A value greater than one is ambiguous: skip filing judgments
for all those copies. The report retains each copy for manual judgment and
keeps the handoff, even if decisions were supplied. Do not distinguish copies
by position or alter their producing identity. The same identity carried into
a separate successor handoff is valid and does not trigger this check.

Read the [checklist filing rules](../checklist/SKILL.md#5-write-and-validate-the-handoff--fixed)
and apply their ordered table to every unambiguous item in an abandoned session,
including untyped items and schema-version-1 handoffs. Interpret the text and disposition;
do not classify solely by item type or keyword. An observation with no outcome
is R6; a concrete deliverable needing work is R5 only after a successful open
ticket search. Mentioning a ticket is insufficient for R2 unless it is open and
the item belongs on it. A proposed change to an approved spec is R3, not R7.
Knowledge for reuse is R4; information already saved in its named destination is
R1 only with evidence from a successful read. Anything a lesson/knowledge slot
would leave pending becomes an ask under R4 with `destination: "ask"`.
For an untyped legacy item going to a slot under R4, set `destination` to
`"lessons"` or `"knowledge"`. That choice supplies its type for validation;
the original item and identity stay unchanged. Other rules need no added type.

Use the profile's read-only `record_read` skill for R1 already-recorded checks
and R2 ticket status, and the record binding for R5 matching searches. A failed, unbound, unsupported or
malformed read is unknown: supply `read_status: "failed"` and the error. Never
write as part of those reads. For multiple plausible matches, choose R3 with
choices naming the candidates; one matching open ticket becomes R2. Give R5
`priority` and `priority_reason`. Give R1/R6 a `reason`; only information-only R1
uses `information_only: true`. Give R3 and R4-to-ask concrete `choices`.

Prepare an array of decisions in a caller-owned temporary JSON file. Each row
copies `handoff` from the candidate's `path`, copies the item's `identity`
**unchanged**, and adds `rule`, `destination` when applicable, plus the fields
above. No position identifies an item. Example shape (replace every value):

```json
[{"handoff":"/example/state/source.json","identity":{"session_id":"example-session","produced_at":"2026-10-01T00:00:00Z","text":"Optional observation"},"rule":"R6","reason":"No stated outcome"}]
```

## Write the sweep report

```bash
python3 <package>/scripts/lib/sweep.py run --scope <directory-or-all> \
  --decisions <decisions-file> --user-profile <profile-file>
```

Pass the same interactive evidence when applicable. The command validates
choices through the checklist filing engine and checks current source identities;
a changed item requires a fresh inspection and decision. Omitted decisions stay
pending and keep their handoffs. A concurrent sweep exits with `already running`
and writes nothing. An item's planning or validation failure appears as `failed`
with its rule, destination and error; its handoff is kept and the remaining items
are still processed into the same report. Command-level errors are reported
explicitly; do not treat them as an empty store. Watch-only prints a report
path; act mode prints JSON with `run_id`, `report`, `phase`, and `work`. Read the
report. With no decisions the command gives a watch-only inventory even when
act is configured. No archive or removal happens before completion.

## Perform an act plan

Use only the returned work entries with outcome `intent`. Each intent was
journaled before return, with a stable `write_id`, operation, unchanged identity,
producer, directory, source handoff, rule, destination and operation fields.
Keep this run id and the work list through all results rounds.

Before **each** write, including a retry, slot work, ask or successor carrying
the same identity, ask its record or ask binding whether that identity was
already written. Bindings must store the identity, original run id, receipt
and destination with every write and prevent duplicate identities. If found,
return `already_written` with that receipt and destination. If lookup fails,
do not write; report failed with the lookup error. Do not infer absence from
an unsupported lookup. For R5, the successful open-ticket search was performed
before deciding: one match is R2 and several are an R3 ask. Never skip it.

For absent identities, perform the operation through the profile's record,
ask or named slot binding. Invoke skill commands as skills; follow inline
instructions where supplied. No executable adapter is needed. Preserve the
item identity, linked ticket, choices, priority and reason. A comment inherits
the destination ticket's priority. An ask is never a ticket. For an interactive
open-session intent with `delivery: "direct"`, present its choices to the user
and record that presentation with a receipt; never infer permission to wrap or
close from a reply.

Write a caller-owned results JSON array, one result per write id:

```json
[{"write_id":"<copied-from-work>","status":"written","receipt":"<receipt>","destination":"<actual-destination>"}]
```

Use `written` only for confirmed writes, `already_written` for identities found
before writing, `failed` with `error` only when no write occurred, or `uncertain`
when a write may have happened. Lost replies, timeouts and malformed receipts
are uncertain. For a slot leaving work pending without a write, use `failed`,
`pending: true`, and its error; completion journals its ask. Missing results
also become uncertain and keep the source. Never blindly retry an unknown
write; the next attempt first looks up its identity.

```bash
python3 <package>/scripts/lib/sweep.py complete --run-id <run-id> --results <results-file>
```

Before completion, refresh interactive session inspection and pass the updated
`--open-sessions <evidence-file>` when using agent evidence. Configured session
checks rerun automatically. Worktree-retention and open-idle asks are deferred
until these post-filing checks. For those asks in act mode, use only deferred
intents, never inventory proposals.

Read the returned JSON and report. If `phase` is `planned`, completion added
asks after a slot, worktree or open-session check: perform only new `intent`
entries, then
complete the **same run** again. Stop when `phase` is `completed`. Failed,
uncertain, unbound, ambiguous, read-failed and undecided items are retained.
Report those outcomes, parse errors, actual archives/removals and tripwire
excess items. Never describe proposals as executed work. A run with nothing
to do still writes a report. Scheduling belongs to the user; scheduled act
runs must invoke this skill through an agent driver (see
[usage](../../docs/sweep.md)).


## User-started undo and configured retention

Run undo only when the user explicitly asks to reverse a named act run. Never
start it during an unattended sweep or infer it from an ask answer. Use the
original run id and the same user profile resolution as run:

```bash
python3 <package>/scripts/lib/sweep.py undo --run-id <run-id> --user-started --user-profile <profile-file>
```

Undo prints JSON with the journaled reversal work and proposed archive
restorations; planning changes no destination or archive. For each work entry,
check its target immediately before reversing it through the original record
or slot binding. A ticket created by the run is closed as not planned; a
comment is edited to a stub; a document or slot edit restores the saved
preimage. The comment stub consists of the line `Removed by sweep undo <run_id>`,
followed by a blank line, then the original record marker, unchanged. Never
delete the comment. A retry recognizes this run's stub by both the run id and
the unchanged original record marker and returns `reversed`. With one shared
token, a manual "not planned" close also reads as `reversed`; the binding cannot
distinguish it from the undo close. Never close
an existing ticket. Later comments or edits on a created ticket, or later
document edits, mean `conflict`: preserve the target. The check is separate
from reversal; a change between them is **not detected**. No atomic reversal
adapter is required.

Record one result per `write_id` with status `reversed`, `conflict` or `failed`,
and an error/reason when needed. An unsupported reversal is failed; do not
invent success. Use the original run id and receipt to recognize an already
completed reversal after a lost reply.

```bash
python3 <package>/scripts/lib/sweep.py complete-undo --run-id <run-id> --results <results-file>
```

Completion records results and restores archives under the existing conflict
rules. Present every reversal, conflict and failure. A newer handoff at the
original path stays untouched. Worktree removal and local branch deletion
cannot be undone; asks remain delivered. Rerunning undo retries only failed
items; conflicts and successful reversals stay unchanged. Never restore an
archive manually.

Optional retention runs separately with `python3 <package>/scripts/lib/sweep.py
retention`. It deletes nothing while `archive_retention_days` is unset. When
configured, it deletes only regular archive JSON handoffs whose modification
age is strictly greater than that number of days. Never run retention implicitly
as part of watch-only or undo. Read its report and report deletions and failures.
See [undo and retention](../../docs/sweep.md#undo-and-retention) for boundaries.
