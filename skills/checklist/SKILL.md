---
name: checklist
description: "End-of-task wrap-up for any session: run the five-step spine with user bindings and additive repository steps. Use when finishing a unit of work, or when the user says 'checklist', 'wrap up', or 'wrap up session'."
---

# Checklist — end-of-task wrap-up

Run one fixed spine: reconcile the record, capture knowledge, fold in lessons,
persist, then write and validate the handoff. Persist is the only configurable
slot; record is a package step calling per-kind record writes; knowledge and lessons are native package steps. Profiles bind slots and add steps; the handoff is not a slot, and only an
`own-worktree` step may follow it.
Run package steps and named bindings as planned, preserving their approval requirements.

## Resolve profiles before running the spine

Read the **user profile**, which applies to every session. It is
`$CHECKLIST_USER_PROFILE` when that is set, otherwise `hippocampus/checklist-profile.md` under
`$XDG_CONFIG_HOME` (default `~/.config`). Claude Code and Codex use the same
profile and composer. When no user profile file exists, run with none: that is a
configured-nothing user. The user profile may name further profile files to pass
as repository profiles for some surfaces; follow it.

Then identify every repository this session touched. The candidate detector is
this package's `scripts/checklist-surfaces.sh` (resolve the path from this
skill's real directory: `../../scripts/checklist-surfaces.sh`):

```bash
bash <checklist-surfaces.sh>
```

It lists the session's own repository plus the standing surfaces named by
`checklist_surfaces` in the hippocampus configuration (none by default).

Treat output as candidates: exclude another session's changes, and include your
own work even if already committed and pushed. For a linked worktree, read its
profile first if it differs from the main checkout's. A repository profile at
`.claude/checklist-profile.md` is additive. Read each complete file, including
notes that qualify its steps.

Profiles with a `checklist-profile` JSON fence are composed by the standard-library
module `scripts/lib/checklist.py`. The fence declares `name`, optional `bindings`,
optional per-kind `record_writes` (see the record skill), optional `steps`, and an optional `ask: {"command": "/ask-step"}`. The ask
binding is one user command, not a slot or a spine step. Repository profiles
cannot bind it. A binding has a `command` and a list of item types it
`consumes`; a step has a unique `id`, an `after` anchor, and `instructions` (or
a `section` naming a level-two heading in the same Markdown file).

Run the composer with the user profile first and repository profiles in resolved
order. Paths below are placeholders to replace with the actual resolved files:

```bash
python3 <checklist-module> plan --user-profile <user-profile> \
  --repository-profile <repository-profile> \
  --session-id <current-session-id>
```

Repeat `--repository-profile` for each additional file. After pickup, `plan`
loads the resumed handoff snapshot and chain from the current session's ledger;
the source file is never read again. Its returned `handoff` payload is the input
for filing and settling: save it as `<remaining-items>`. Optional `--handoff`
must name the path pickup recorded, even if that file no longer exists; a
different path fails. Without pickup, a brief or pasted prompt starts its own
chain and contributes no earlier history. `plan` writes a start marker row to the current session's
ledger; `--session-id` defaults to the Claude Code session in the environment,
so pass it in Codex. No profile is also a valid plan: omit the profile arguments, and the plan is the
five spine steps ending with the handoff. Record has no bound record writes and persist is unbound.
Knowledge always runs the package’s knowledge-capture, consuming `knowledge`;
lessons always runs improve-harness, consuming `lesson`. In Claude Code these
are `/hippocampus:knowledge-capture` and `/hippocampus:improve-harness`; in Codex
use the same skills by their plain discovered names. Neither can be rebound or disabled. An unbound slot's `carries` lists item types for the final filing pass.

Added steps may run `before-spine` or after `record`, `knowledge`, `lessons`, or
`persist`. At each anchor they run in profile order, then declaration order.
The composer rejects removal, skipping, replacement of a spine step, duplicate
step IDs, rebinding by repository profiles, and any step after `handoff` but
`own-worktree`; each error names the step. Report its error and stop; do not silently drop a
malformed profile.

Existing repository profiles without a fence still apply: read their `Slot:`
declarations and merge their instructions at the corresponding anchors using
the same additive rule. Reject attempts to remove/skip any spine step or add
after handoff, except `own-worktree`. A legacy `after-persist` declaration means after `persist`.
Do not silently omit a repository's existing steps during this transition.

## Who runs it, and when

Only an interactive session runs the checklist. Factory sessions and subagents
never run it and never write a handoff. The module refuses a headless session
(`a factory session never runs the checklist or writes a handoff`), and the
`checklist-actor-guard` PreToolUse hook, in both tools, denies a subagent or
factory session the module's operations and the checkpoint writers. A subagent
that reaches this skill stops and reports to its parent instead.

An interactive session its user launched and left to execute approved work (unattended
mode: a one-ticket scope or a slate) wraps itself, on the slate's cadence. The package
knows unattended mode only through the optional `unattended` section of the hippocampus
configuration (see `INTERFACE.md`); with none, every session is attended and this section
does not apply.

- **After each ticket** in the slate (or the scope's work landing), checkpoint: write
  the handoff with every unrecorded session item through `checkpoint`'s script,
  as in step 5. Do not run the checklist;
  it would clean up worktrees and agents the slate still uses.
- **After the whole slate**, once its completion command (the configured
  `unattended.completion_command`) succeeds, run this full checklist once with
  `--unattended` on `plan`, `report`, and `wrap-check`.

`python3 <checklist-module> wrap-cadence` reads a hook payload on stdin and
prints which applies now: `none`, `checkpoint`, `unattended-checklist`, or
`checklist`. The completion command returns the session to attended mode, so the checklist
nudge records the successful call as a marker under `CHECKLIST_STATE_DIR`
(the module's state directory). While it exists the cadence stays
`unattended-checklist`, and `wrap-check` without `--unattended` fails for that
session. A passing `wrap-check --unattended` removes it. An explicit attended `plan`
also removes it and starts all steps afresh, including after a failed unattended wrap.

**Unattended runs.** Nobody is present to answer. A step, binding, or profile
step that would need the user's answer (an approval, a choice, a confirmation)
reports `pending` with the answer it needs, writes nothing, and the checklist
continues with the next step. Keep its unsaved items for the filing pass;
items are not deferred to a next session. Before writing the handoff, turn each item
that needs the user into an ask through the ask binding; never file an ask as a
ticket. Step 5 still runs and the wrap check still applies.

## The five-step spine

An attended run after an unattended run starts a fresh `plan`, runs **every
step again**, and asks the user wherever an answer is needed. Never reuse an
earlier run's pending results, saved-item receipts, or filing outcomes as the
new run's results. The composer returns every step without cached statuses
(`rerun_all_steps: true`). Prior durable writes remain evidence to read under R1.

### 1. Reconcile the record — package `record` step

Run this package's record skill (`/hippocampus:record` in Claude Code, `record`
in Codex). It applies the filing rules and calls the user profile's optional
record writes for tickets, projects, documents, and scheduled jobs. It can also
run alone mid-session without the rest of checklist. No separate commitment
pass runs: commitments follow the same filing rules. Timed or recurring
commitments use scheduled_jobs when bound, otherwise the ticket path.

The record module looks up each unchanged item identity before every write.
Only a matching receipt saves an item. Missing bindings warn and keep items;
failed writes fail wrap. Missing write receipts are uncertain; lookup must
succeed before any retry. Preserve the returned payload even on failure.
Note the UTC time the record step finishes for the freshness check when writes
are configured. Run it again at wrap with the same identities; existing receipts
are reused without another write. At wrap use `file`: it re-reads only the
session's touched tickets (including carried references) through the tickets
record write, when bound, and records any closed ticket's missing close outcomes.
When tickets is unbound, no reread runs: stored close outcomes are the complete
known set, and a projects-only profile can write project history using them. No other
ticket, milestone, or epic is queried. See record's ticket-state contract.
Record every ticket read, changed, or closed with `ledger-ticket` as it happens;
close outcomes and touched tickets live in the ledger through compaction.

The agent writes the **session summary** at wrap; record writes never compose
it. First finish ticket writes and the wrap's touched-ticket read, retaining
all returned close outcomes. Keep project session-log items for the final pass,
after summary composition in step 5. Mid-session record runs do not compose the
wrap summary.

### 2. Capture knowledge — native `knowledge`

Run this package's knowledge-capture. Present carried knowledge items first,
intact with their provenance, then new session knowledge. Follow its knowledge
profile and approval requirements. With nothing to capture, report `nothing`.
With no configured knowledge root, report `not configured`, name
`hippocampus-set-up`, and keep carried knowledge. An invalid configuration or
capture error is `failed`, with its error. A refusal is `declined`, with its reason.

### 3. Fold in lessons — native `lessons`

Always run this package's improve-harness, presenting carried lessons first and
then current lessons. Read its routing file to decide destinations; profiles
cannot replace this step. With no lessons, report `nothing`. Failed or declined
work reports its error or reason and keeps every unsaved lesson.

Both native steps continue to the next checklist step on failure or refusal.
Remove an item only after an explicit receipt: the knowledge capture disposition,
or a lesson applied or written to the routing file's proposal destination.
Presentation, approval requests, and ask delivery alone are not capture receipts.
Unattended and sweep runs use these same native steps in unattended mode: carry
items and apply nothing. Report pending proposals and preserve their provenance.

### 4. Persist — slot `persist`

Run the bound command after steps 1–3 and their additions so it includes their
edits. Send unsaved items through the filing pass, including when unbound. Ticket-state decisions
and merge authorization belong to profiles and their bindings.

### 5. Write and validate the handoff — fixed

After the additions through persist, apply the **filing rules** to every item
the earlier steps did not save, including current `session_items`, remaining
typed or legacy open loops, and items needing approval. Evaluate in this order;
the first match decides. Rule numbers are names, not evaluation order.

| Rule | First matching condition | Outcome |
|---|---|---|
| R1 | Already on the ticket or document it names, or information only | Drop with the reason. |
| R3 | Needs the user's decision, approval, or a destructive action | Ask, linking its ticket if any. Removing a clean, merged worktree and its local branch under the sweep's S6 rule is not destructive: its commits are in the pushed trunk. |
| R4 | Lesson or knowledge | Pass to `lessons` or `knowledge`; unsaved native items stay carried until their step returns a receipt. |
| R7 | Changes a project document (spec, design document, README) | Edit through the documents record write; a change to an approved spec becomes an ask. |
| R2 | Names an open ticket | Comment through the tickets record write. |
| R5 | Work with a stated outcome and no matching open ticket | New ticket through the tickets record write, with recommended priority and a one-line reason. |
| R6 | Otherwise: optional suggestion, observation, idea with no outcome | Drop with the reason. |

The agent makes the judgment, including R5 versus R6 and whether R7 needs
approval. R1's already-recorded check, R2's open-ticket check and R5's matching
search require a successful, supported, valid record read. Use `record_read`
and its response contract when bound. A failed, unsupported, or malformed read
is **unknown**, never absence: keep the item with outcome `read failed`, naming
the item and the error. Never drop it under R1 or create a ticket under R5 on
that evidence. An information-only R1 can explicitly set `information_only: true`.

The module runs record writes and collects matching receipts; do not execute them separately. Run the ask command and native steps as before.
For each ask, pass the ask command a JSON object containing `text` (the item),
`session_id` (its source session), `directory`, `ticket` (linked ticket or null),
and `choices` (the user's complete options, with no length limit). An ask is **never filed as a ticket**.
These fields also appear in the filing report's `ask` payload. For R4 native items, preserve the native outcome and carry unsaved items;
an ask acknowledgement does not replace a capture or lesson receipt. Always run
the bound ask command for R4 `destination: "ask"`, using the complete payload in
`filing.asks`, and collect its receipt. Validate non-empty `choices` before
calling. A delivered native ask retains `binding: "ask"`, its payload and receipt,
`ask_status: "filed"`, and the native item's `status: "pending"`. Keep the item
carried until the native step returns its own capture receipt.
A successful invocation alone does not acknowledge every input.

Combine remaining open loops with unsaved current `session_items` in a payload.
Create a JSON array with one outcome for each item, indexed first by the
remaining loops and then by unrecorded `session_items` in order:

```json
[{"index": 0, "rule": "R3", "status": "filed", "destination": "ask receipt", "choices": ["approve", "decline"]}]
```

Each row names `index`, `rule`, and `status` (`filed`, `dropped`, `pending`,
`failed`, or `read failed`). A filed row names `destination`, a drop names
`reason`, and a failed row names `error`. Read-dependent rules need
`read_status: "ok"`; any other or missing read status is a read failure. R5
also needs `priority` and `priority_reason`. R3 and R4-to-ask need `choices`.
A retained native lesson proposal awaiting user approval also keeps non-empty
`choices` on its item or R4 outcome, even when its destination is `lessons`.
Native work retained only because a step failed or was declined needs no ask
choices; keep it in the filing report and incomplete-step details.
Use the same profile arguments for the filing pass:

```bash
python3 <checklist-module> file --user-profile <user-profile> \
  --repository-profile <repository-profile> --handoff <remaining-items> \
  --filing <filing-outcomes>
```

The module executes per-kind record-write commands after a successful identity lookup; ask and native outcomes remain supplied by the agent. Its output removes only
explicitly filed or dropped items and includes a `filing` report listing every
item, rule, destination or reason, warnings and failures. Keep that report in
the payload through checkpoint. A missing binding retains the item and warns,
without failing wrap. A bound record, persist, or ask write failure retains it and fails wrap.
A native failure or refusal retains its items and makes the final report
`incomplete`, without failing wrap validation. `nothing` and `not configured`
do not make the wrap incomplete. With no
ask binding, `filing.asks` groups asks under their directory; retain this
report for the sweep report and keep the producing handoff. Do not archive it.
Asks retain their complete text, choices, and proposal fields in carried items;
never shorten them to fit a carried-item limit. For a failed write, checkpoint
the retained payload before reporting failure.

Before the final project writes and handoff, write one **session summary** in
`resume.session_summary`, in Claude Code and Codex alike. Read every
`resume.session_history` entry and `resume.close_outcomes` from the current
session's payload and ledger, including the chain copied by pickup. Include the
current session's work since its last entry. Cover the work of every entry and
the stored close outcomes in connected prose; do not print a raw list of history
entries. Every ticket named needs a description of its work, not only a number.
The summary must read on its own without opening a ticket. It may span paragraphs.

For each `resume.resumed_chain` row marked `skeleton` whose session has no history
entry, say that the named session ended at its `written_at` time without an
account of its work. A skeleton gap is part of the summary, not a wrap failure.

When a projects record write is named, create a project session-log item for each
project touched, capturing its item identity once for this wrap account and
reusing it unchanged on retries. Pass these
items through `file` after composing the summary. Retain `resume.touched_projects`
(the complete project references, including carried projects); item
`anchor.project` references are added automatically. Every projects lookup and
write receives `session_summary`, `close_outcomes`, and `touched_projects` from
the payload, outside the immutable item identity. Project writes run after ticket
writes and, when tickets is bound and touched tickets exist, a successful
touched-ticket read. With tickets unbound, use the stored close outcomes without
a reread. A failed or malformed required reread keeps every project item pending
without calling its lookup or write. A missing, null, or blank session summary
also keeps the item pending: write a nonempty summary before retrying. If new close outcomes
arrive after summary composition, project items also remain pending: rewrite the
session summary and retry with the retained items and their unchanged identities.
The payload's `resume.summary_rewrite_required` retains the stale summary until
the agent supplies revised text; retrying unchanged text cannot save project history.
Record writes save the supplied
account; they cannot replace it or supply a fallback for the report.

Write the interactive session's handoff using the
same checkpoint module as `checkpoint`. Its slash skill is user-only;
call its script directly: `<checkpoint.sh>` is `scripts/checkpoint.sh` in that
skill's real directory (`../checkpoint/scripts/checkpoint.sh` from this
one). Use the actual current session identity in either tool. Supply a real
`resume.history_entry` account of work since this session's previous history
entry alongside the complete `resume.session_summary`. The writer appends the
one-line history entry with the current identity and date and retains earlier
ledger entries through compaction. The final handoff stores the complete summary
separately from those entries; `history_entry` is consumed as write input and
is not carried to a successor. A missing account fails wrap;
an automatic stop skeleton cannot serve as a finished wrap handoff.

```bash
bash <checkpoint.sh> <<'JSON'
<current handoff JSON returned by the filing pass, including its filing report>
JSON
```

The finished handoff holds context only, with `resume.next_action` saying
`Session finished.`. The filing output sets it; when an unbound destination
keeps items, it names those items instead. Preserve the producing identities
and provenance of retained items. Do not add a next-session work queue after
the filing pass. Checkpoint still includes the session's uncommitted files
through the ledger contract; any newly included open loop must pass wrap check.

Then run the wrap check with the same profile arguments:

```bash
python3 <checklist-module> wrap-check --user-profile <user-profile> \
  --repository-profile <repository-profile> --written-handoff <handoff-file> \
  --record-at <record-time>
```

`<handoff-file>` is the path checkpoint printed. Checkpoint writes even if
validation fails; the wrap check then fails with the validation errors. When
`record` is bound, `--record-at` is the time of its latest write, or of a later
passing freshness check by the binding;
the wrap check fails when that time is older than the session's last recorded
change (an edited file, published artifact, or owned commit) made before the
latest `plan` start marker. Changes after the marker are the checklist's own
writes, such as persist's commits and lessons edits, and do not count. With no
marker in the ledger, every recorded change counts. When no record writes are
configured, omit `--record-at`; no record check runs. On a non-zero exit, report
each `wrap failed:` reason and refuse to report checklist completion.

Then a profile's `own-worktree` step may remove the session's own linked
worktree; removed earlier, the handoff records no repository and resume cannot
find it. It runs only after the wrap check passes, and only when the worktree is
clean, its branch is merged into the pushed trunk, and a plain
`git worktree remove` succeeds. Otherwise keep it.

## Carried-item contract

At each slot or native step, present carried items first and consume the typed open loops listed in that step's `carried_items`
in the plan **as well as** the current conversation. Each entry has an `index`
into the original resumed handoff and its complete `item`. Pass that item intact,
including its producing session identity and time, a decision's author and source,
lesson text, and artifact location/disposition. Also pass all carried history
entries and close outcomes to the record step; earlier history belongs to its producer.

Collect explicit saved-item acknowledgements from native steps and persist as JSON:
`{"knowledge": [3]}`. Record uses per-item receipts through `record` or `file`, never numeric acknowledgements. These are indexes into the original
input, not into a shrinking list. Do not acknowledge pending, failed, unsupported,
or merely presented items. If a binding lacks provenance support, report it and
send the affected loops through the filing rules. Untyped legacy loops also
pass through the filing rules at wrap; checkpoints may still carry them.

Use the same profile arguments to settle the input:

```bash
python3 <checklist-module> settle --user-profile <user-profile> \
  --repository-profile <repository-profile> --handoff <remaining-items> \
  --receipts <saved-item-receipts.json>
```

The returned JSON removes only acknowledged loops of types the slot or native step consumes.
It preserves every other field and never rewrites the source handoff. Merge its
remaining loops with this session's unsaved items, then apply the filing rules
in step 5 under the current session. Unbound destinations warn without failing.

At wrap, every ledger history entry and close outcome must appear unchanged in
the final handoff. `wrap-check` fails and names each missing entry or outcome;
it never reopens the resumed handoff to discover them.

## Report

Start the report with `outcome_line` from stored close outcomes, then the
session summary stored in the final handoff, unedited, in Claude Code and Codex
alike. The agent composes it in step 5 even when no record writes are bound. Then name the
user and repository profiles resolved. Report each planned step in its
execution order, its bound command if any, and its result: run, carried (an
unbound slot), pending, or failed. Check the results with the same profile
arguments before reporting completion:

```bash
python3 <checklist-module> report --user-profile <user-profile> \
  --repository-profile <repository-profile> --results <results.json> \
  --handoff <written-handoff> [--unattended]
```

`--handoff` is required and must name the valid handoff checkpoint wrote;
an omitted, unreadable, malformed, or invalid handoff fails the report. The
report still shows every ask recoverable from readable handoff fields; invalid
fields never hide asks held in other fields.
The report reads `resume.session_summary` only from this handoff. An absent or
empty summary fails the report and wrap; there is no binding-supplied summary or
unavailable-summary fallback. The output's first field is `outcome_line`, followed
by `summary`. It still ends with every pending ask on a failed wrap.

`<results.json>` is an array, in execution order, of
`{"id": <step>, "status": <result>, "writes": [<paths or locations>], "reason": <text>}`.
A pending step needs a `reason` naming the answer it waits for and an empty
`writes`. Every planned step reports, so a pending or failed step never ends the
run early; unattended, the handoff step must have run. On a non-zero exit, fix
the run or report each `report invalid:` reason. Include the filing report: each item, rule, destination or drop reason,
missing-binding warnings, and failed-read/write errors. Include what was saved,
what remains carried, and the final
handoff location, validation result, the wrap check's result, and the own-worktree result:
removed, or kept with the failed check. Profile steps appear at their declared anchors; after
the handoff write, only `own-worktree` and reporting the result follow.

Native result statuses also include `nothing`, `not configured` (knowledge), and
`declined`. Failed and declined results need an `error` or `reason`. Use these
same statuses on retained R4 filing rows; `pending` needs a reason. A native
`filed` row requires its disposition or applied/proposal receipt as `destination`.
The final report returns `report: "incomplete"` and an `incomplete` list naming
every failed, declined, or pending native step with its reason, even with no
carried items. `nothing` and `not configured` leave `report: "ok"`. Record and
persist retain their existing bound-write failure rule.

End every report, attended or unattended, with the output's final `asks` list: every
ask this run filed or carried, complete text and all choices, with lesson asks
first. Each lesson includes its target file and section, full proposed text or
diff, and evidence. Do not replace proposals with pointers or one-line summaries.
Only identical ask payloads appear once; different linked tickets, choices, or
proposal fields remain separate even with the same producing session, time, and
text. Validate stored filing asks as well as carried asks: non-empty text and
non-empty choices are required. A malformed ask fails the report while every
valid ask still appears in full.
Only retained items with user choices belong in this ask list; a lesson's type or
native status alone does not make it an ask. Never omit a retained approval
proposal: preserve its full text and choices. The list follows warnings and incomplete-step details. A failed ask write still
appears in the report, as do failed record or persist writes, failed record
reads, and validation or input errors. These failures return `report: "failed"`,
an `errors` list before the final `asks`, the same errors on stderr, and a
non-zero exit status. Never stop reporting after an error or omit the asks.
Native failures and refusals retain their `incomplete` report and existing exit
status unless another error fails the report.
