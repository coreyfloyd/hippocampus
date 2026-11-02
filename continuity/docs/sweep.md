# Sweep command

Sweep finds abandoned sessions and writes one sweep report. Invoke
`/continuity:sweep <directory-or-all>` in Claude Code, or ask Codex to use the
`sweep` skill with that scope. Both use the same skill and standard-library
command. A directory includes every handoff for its repository, across sibling
worktrees. Outside a repository, only that exact directory matches. `all`
includes the whole local handoff store, including legacy handoffs without a
subject (reported under `unknown directory`). Archives are not scanned.

A session is abandoned only when its newest handoff or transcript write is
strictly older than the idle threshold. Both Claude Code transcripts and Codex
active and archived rollouts count. A transcript store that cannot be inspected
prevents filing for that run and is reported. Malformed handoffs are reported
with their paths and reasons and left in place. Discovery executes no binding.

## Configuration

Add a `sweep` object to the existing continuity configuration file resolved by
`CONTINUITY_CONFIG`, else `$XDG_CONFIG_HOME/continuity/config.json` (default
`~/.config/continuity/config.json`). Other configuration is preserved.

```json
{
  "sweep": {
    "mode": "watch-only",
    "idle_days": 2,
    "open_session_checks": [],
    "new_ticket_limit": 10,
    "report_location": "~/sweep-reports",
    "archive_retention_days": null
  }
}
```

`mode` defaults to `watch-only`; the user can switch it to `act` to plan
filing for an agent to perform through their bindings, then complete the run
and move handled handoffs to the archive. `idle_days` is a non-negative finite number. `report_location` is a
directory; absent, reports go to `sweep-reports` beside the resolved handoff
store. A report location inside the handoff store is rejected. The handoff
store itself follows `HANDOFF_STATE_DIR`, then `handoff_dir`, then the existing
default. No handoff migration is performed.

`open_session_checks` is a list of command strings, default none. Each command
prints whitespace-separated session ids; the union is open. Commands use argv
quoting without a shell and have the configured binding timeout. Nonzero exits,
timeouts, and commands that cannot start prevent every session in scope from
counting as abandoned; the report names the command and error. Successful checks
and their ids are recorded too. Checks must be read-only, including in watch-only.
For example, this optional Herdr check reads `herdr pane list` and prints the
session ids from panes whose `agent_session.kind` is `id`:

```bash
python3 -c 'import json,subprocess; out=subprocess.run(["herdr","pane","list"],check=True,capture_output=True,text=True).stdout; [print(p["agent_session"]["value"]) for p in json.loads(out)["result"]["panes"] if (p.get("agent_session") or {}).get("kind")=="id"]'
```

Every Herdr agent state (`idle`, `done`, `working`, `blocked`) counts as open.

Put the same command in the configuration as a JSON string (the double quotes
inside the command must be escaped):

```json
{
  "sweep": {
    "open_session_checks": [
      "python3 -c 'import json,subprocess; out=subprocess.run([\"herdr\",\"pane\",\"list\"],check=True,capture_output=True,text=True).stdout; [print(p[\"agent_session\"][\"value\"]) for p in json.loads(out)[\"result\"][\"panes\"] if (p.get(\"agent_session\") or {}).get(\"kind\")==\"id\"]'"
    ]
  }
}
```

The command runs without a shell or pipeline. If Herdr is missing or inspection
fails, it exits nonzero so sweep prevents sessions from counting as abandoned.
Herdr is an optional example, never a package dependency. Other session managers
can implement the same command contract. `new_ticket_limit` (a non-negative
integer, default 10) and `archive_retention_days` (default null, retention off)
control creation capacity and optional archive deletion respectively.
Retention runs only through the separate `retention` command described below. Watch-only creates no ticket and
deletes nothing, regardless of these values. Act mode never deletes a
handoff; it can remove eligible linked worktrees and their local branches. `binding_timeout_seconds` defaults to 30; it
must be a positive finite number.

## Command and judgment contract

From the package root:

```bash
python3 scripts/lib/sweep.py inspect --scope all
python3 scripts/lib/sweep.py run --scope all --decisions /example/decisions.json
```

`inspect` prints candidates as JSON and writes nothing. Candidates include the
original handoff, directory, session id, latest activity, idle seconds,
abandoned status, and every item's identity. Identity consists of the producing
session, production time and text. Legacy items without provenance use their
source handoff's session and timestamp, falling back to the filename and file
write time. No item is identified by its array position.

Each inspected item has `identity_occurrences`, the number of times its identity
appears within that handoff. More than one occurrence is ambiguous, including
exact copies: fields outside the identity can affect filing, and the sweep
does not guess which copy a judgment meant. For a swept handoff, all copies
remain visible with the outcome `ambiguous identity`, their unchanged identity and source item, the
occurrence count, and a reason requiring manual judgment. No filing rule or
action is proposed for these copies, and their handoff is kept. Zero, one or
multiple supplied decisions for an ambiguous identity all produce that same
retained outcome per copy; none is applied. Discovery repeats this check at
run time. This check is local to a handoff: carrying the same identity into a
separate successor handoff is valid and does not create an ambiguity.

The sweep skill chooses filing rules using the checklist's ordered filing
rules, then supplies an array via `--decisions`. Each row names `handoff` (the
candidate's path), copies `identity` unchanged, and supplies the checklist
filing fields: `rule`, `destination`, `reason`, `choices`, `read_status`,
`information_only`, `priority`, `priority_reason`, and `error` as applicable.
The engine uses the checklist's filing validator and binding resolution,
without executing bindings in any mode. The agent performs the reads and all
binding calls under the [plan/results contract](../INTERFACE.md#12-sweep-plan-and-results-contract). Untyped legacy items use the same fields for
every rule. For R4, `destination: "lessons"` or `"knowledge"` supplies the agent's
classification to the validator using a temporary typed copy; the report keeps
the original item and its identity. R4 with `destination: "ask"` routes pending
slot work to an ask. `--user-profile` accepts the existing JSON or
Markdown checklist profile. Unbound destinations keep their handoffs and are
reported. R1/R2/R5 reads must succeed; failed or unsupported reads remain
`read failed`, never evidence that no ticket exists. Missing decisions stay
`pending judgment`. Stale and unknown decisions fail explicitly, as do multiple
decisions for an identity that occurs only once in its source handoff.
A direct run without decisions is a watch-only inventory even with act
configured: it archives no handoff and removes no worktree.

Unattended runs never request input. With no configured checks, interactive runs require `--interactive
--open-sessions /example/open.json` on both commands. This evidence object has
`session_ids` (an array) and `method` (a description of the read-only inspection).
With configured checks, `--interactive` uses their results and agent evidence
is optional. An empty result is explicit. The report records that evidence and lists open
sessions with their idle time. The skill presents the choices `wrap it`,
`leave it`, `close it` directly for open idle sessions. This command neither
waits for those choices nor acts on them. An open or recently active session
also protects a worktree from removal, including when its directory is inside
that worktree. In act mode an idle open session raises one ask, or presents the
choice directly through the driving agent without invoking the ask binding.
The agent returns a receipt for that presentation in completion.
`open-session-asks.json` beside the reports records session ids and the activity
at which asks succeeded or choices were presented. A later run suppresses that
ask until a newer handoff or transcript write. Unbound or failed writes retry;
uncertain writes first query identity existence. Watch-only never updates this
record. The sweep never reads ask answers or wraps or closes a live session.

`run` acquires an exclusive nonblocking lock on the handoff store's directory
inode before discovering candidates. It writes no lock file; when the store
is absent it locks the nearest existing ancestor conservatively. A concurrent
sweep over the same store exits 2 with `already running` and writes nothing.
Other command/configuration failures exit 1. Successful inspect/run exits 0;
a watch-only run prints its report path. An act plan or completion prints JSON
with its report path, run id, phase and work list. Source parse failures appear inside
the report, so they do not prevent reporting the remaining sources. An item's
planning or validation failure also stays in the report: its outcome is `failed`,
with the source item, unchanged identity, chosen rule/destination and error. Its
handoff is kept, and the run continues with other items and handoffs. Exit 0 means
the report was written; read its outcomes to distinguish failures from proposals.

## Sweep report

Each run writes exactly one new Markdown file named by its run id, containing
text and an embedded JSON object for structured consumers. Parse the sole
`json` fence to read that same run. The object includes run id, host, start and
end times, scope, mode, open-session inspection results, parse errors, and
`directories`. Every directory has these arrays in order:

1. `asks_raised`: proposed asks, source session/directory/ticket and choices.
2. `open_sessions`: sessions protected by evidence, with idle seconds.
3. `new_tickets`: proposed new tickets, recommended priority and reason.
4. `comments_added`: proposed ticket comments.
5. `documents_changed`: proposed document edits.
6. `items_dropped`: proposed drops with the deciding rule and reason.
7. `worktrees_removed`: proposed worktree removals with branch, commit and checks.
8. `handoffs_archived`: proposed archives with source and destination.

`filing_outcomes` includes every item, including lessons/knowledge, pending
judgments, ambiguous identities, failed items, read failures and unbound
destinations. `worktrees_kept` and `handoffs_kept` explain retention. Every decided
item names its rule.
`dry run` means a proposal; nothing has been filed, dropped, archived, or
removed. An uncommitted-files ask names the session, directory and files and
always keeps its handoff. Proposed archives require every item to be fileable
or droppable and no unbound ask. Proposed worktree removals require a linked
checkout with no changed/untracked files and its branch contained in the
locally observed remote trunk; plain removal is explicitly unattempted.
The main checkout is never proposed for removal. Failed checks raise proposed
asks. Git remote refs are not fetched or changed by watch-only.

A run with no work still writes a report with `nothing_to_do: true` and
`Nothing to do.` This is distinct from a run with parse or discovery errors.

## External scheduling

The package ships no scheduler. For example, a user-owned cron entry can run a
local agent driver daily. Replace the paths with an installed package and your
existing unattended driver; the driver invokes the sweep skill and supplies
its judgments, performs binding calls, and supplies their results to completion:

```cron
0 3 * * * /absolute/path/to/agent-driver 'Use the sweep skill with scope all unattended'
```

For a deterministic inventory without an agent's filing judgments, schedule the
command directly instead:

```cron
0 3 * * * /usr/bin/python3 /absolute/path/to/continuity/scripts/lib/sweep.py run --scope all
```

Scheduled act runs require this agent driver; the direct command without
decisions remains a watch-only inventory even when act is configured.

The driver's environment must resolve the same configuration and local handoff
store as interactive use. No session, transcript, handoff, binding destination,
or worktree is modified by either watch-only route. Review real-directory
reports and their rule choices before switching configuration to act mode.

## Act mode

Act mode needs an agent. `inspect` stays read-only; `run --decisions` journals
validated write intents before returning a machine-readable plan. It performs
no binding call, archive or removal. Missing judgments and read failures keep
their handoffs. The driving agent follows the profile's existing `command` and
`instructions` for each binding, as during wrap. No executable adapter or
binding stdin/stdout protocol is required.

```bash
python3 scripts/lib/sweep.py run --scope all --decisions /example/decisions.json --user-profile /example/profile.md
python3 scripts/lib/sweep.py complete --run-id <run-id> --results /example/results.json
```

The plan includes stable write ids, operations, identities, sources and
operation fields. The agent performs record reads and the open-ticket search
before choosing R5: one match becomes R2, several become an R3 ask. Successful
`read_status` is agent evidence; the engine does not repeat the read or search.
Before every write the agent checks the record or ask binding's durable identity
index. Bindings store the identity with each write, covering closed destinations
and successor handoffs, and prevent concurrent or delayed duplicates. Found
identities return `already_written` with their original receipt and destination.
A failed identity lookup blocks writing.

Completion takes an array of write ids and results: `written` or
`already_written` (receipt and destination), `failed` (error, no write occurred),
or `uncertain`. Missing results are uncertain. It flushes each result, rechecks
sources and repository/session protections, attempts worktree removals, and
archives only fully handled sources. If a slot leaves work pending, report
`failed` with `pending: true` and its error. Completion journals the follow-up
ask. Worktree-retention and open-idle-session asks are deferred until completion
rechecks eligibility, current open sessions and activity after filing; initial
inventory proposals are never delivered as act intents. Configured session
checks rerun with no inherited command results. Interactive drivers refresh
their inspection and pass `--open-sessions /example/open.json` to `complete`.
When those rechecks require an ask, completion returns `phase: "planned"`:
the agent performs the new `intent` entries and
completes the same run again. `phase: "completed"` ends the run.

Every command takes the store lock. Between act planning and completion a
durable report pointer beside the store (`.<store-name>.sweep-pending.json`)
reserves that entire store. Later runs, undo and retention exit `already running`
even if report configuration changes. Inspect remains available. Recover by
completing the reserved run with known results and uncertain for unknowns; do
not delete its intents or reservation. The reservation is released only after
finalization. This prevents a second run from filing the same planned item or
archiving it before the first run's results arrive.

`new_tickets` is **new this run**, with priority and reason; `comments_added`
names matching tickets; `unfiled_items` names retained work and errors. The
default new-ticket limit is 10 across the entire run. Each planned creation
reserves capacity, conservatively including failures, unknown results and
identities later found to exist. One tripwire ask names affected directories
and leaves excess work unfiled. Unknown results keep their source until a later
run's identity lookup resolves them.

Asks carry the original item identity and producer, directory, linked ticket,
and choices. An unbound or failed ask keeps its handoff. Uncommitted-files asks
name the session, directory and files, and always keep their handoff. Archives
are moves, preserve file bytes, and occur only after every item is filed or
dropped and all asks succeeded. A delivered ask does not clear dirty work.
Repository status must be clean both at planning and after bindings finish,
including main checkouts and handoffs naming subdirectories; failed status
reads keep the source. Discovery also snapshots source bytes and file metadata;
formatting-only rewrites, same-byte rewrites and file replacement keep the
source, even when parsed JSON is unchanged. The snapshot is checked again
immediately before the archive move.

Before proposing removal, the sweep gathers protection from every handoff for
the worktree, including subjects in its subdirectories. Recorded uncommitted
files, kept handoffs, and open or recently active sessions protect the whole
worktree. Act mode finishes filing across every directory before gathering
actual retention outcomes and checking all related handoff snapshots. It makes
one removal attempt per worktree, then archives handoffs across all directories;
removing a root does not make its subdirectory handoffs unreadable for archiving.

Act mode rechecks worktree eligibility after filing, verifies the source handoff
is unchanged, and runs plain `git worktree remove` without force. Only after it
succeeds does it compare-and-delete the local branch at its observed commit.
Remote branches are never changed. A failed eligibility or removal check keeps
the worktree and raises an ask naming its path and failed check. The main
checkout, detached worktrees, worktrees with recorded or observed uncommitted
work, and worktrees used by open or recently active sessions are kept. A removal
row records path, branch, commit, all three checks, and whether branch deletion
succeeded; a concurrently moved branch is preserved and reported. Pushed trunk
means the locally observed remote trunk ref; the sweep does not fetch. A check
failure prevents all removals for that run. Open-session evidence protects every
listed session.

## Undo and retention

Only an explicit user request starts undo, in either Claude Code or Codex:

```bash
python3 scripts/lib/sweep.py undo --run-id <act-run-id> --user-started --user-profile /example/profile.json
python3 scripts/lib/sweep.py retention
```

These commands need no scope. Undo is planned separately from completion:

```bash
python3 scripts/lib/sweep.py complete-undo --run-id <act-run-id> --results /example/reversals.json
```

Undo reads the completed act report and journals a reversal work list plus
archive restorations. Planning performs no reversal or restore. Confirmed record
and slot writes belonging to this run are included; preexisting identities,
failed/uncertain writes and asks are excluded. The agent uses the original
profile's bindings and checks each target immediately before reversing it:
close a ticket the run created as not planned, edit a comment to a stub, or
restore a document/slot preimage. The comment stub consists of the line
`Removed by sweep undo <run_id>`, followed by a blank line, then the original
record marker, unchanged. Never delete the comment. A retry recognizes this
run's stub by both the run id and the unchanged original record marker and
returns `reversed`. With one shared token, a manual
"not planned" close also reads as `reversed`; the binding cannot distinguish it
from the undo close. A later comment or edit on a created ticket, or a later
document edit, is a conflict and must be preserved. The check and reversal are
separate: a change made **between them is not detected**. An atomic check and
reverse binding is not required.

The agent supplies `write_id` and `status` (`reversed`, `conflict`, `failed`)
plus a reason/error when needed. Missing results are failed. Completion flushes
each result and restores archives under the conflict rules. Both commands
acquire the handoff-store lock. Undo also reserves the store between steps,
using the same durable report pointer as act; repeating an incomplete undo
returns its original work list. Retention remains separate and never runs
implicitly during any sweep or undo operation.

An occupied original handoff path is a conflict; it is never overwritten. An
archive changed since the act run is also preserved. Worktree removal and local
branch deletion cannot be reversed by undo; their commits remain in the pushed
trunk. Undo does not re-create those worktrees. It does not change ask activity
records, delivered asks, remote branches, or unrelated record writes.

Undo writes `<run-id>.undo.md` beside the original report. Its structured `items`
list gives each record write and archive the outcome `reversed`, `conflict`, or
`failed` and a reason when needed. Each outcome is flushed atomically; retries
use the same reversal key (run id and receipt), so the binding must acknowledge
`reversed` for an already completed reversal even after a lost response.
Running undo again retries only failed items. Conflicts and successful reversals
are retained without another attempt. A missing archived file, including one
removed by retention, is reported as failed. Original act reports are retained.

Retention defaults to off: `archive_retention_days: null` deletes nothing.
When configured, only regular `*.json` files directly in the resolved handoff
store's `archive` directory are eligible. Age is measured from the archived
file's modification time, preserved by the archive move; it is the handoff's
age, not time since the sweep. Only ages **strictly greater** than the configured
number of days are deleted; an exact age boundary is kept. Symbolic links,
nested directories, non-JSON files and every live handoff are preserved. A
symbolic-link archive is rejected. Each retention command writes one
`<id>.retention.md` report listing kept/deleted/failed files and reasons, with
intent saved before deletion. Retention removes the ability to restore deleted
handoffs; it never deletes reports or changes record destinations.
