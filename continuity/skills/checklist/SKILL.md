---
name: checklist
description: "End-of-task wrap-up for any session: run the five-step spine with user bindings and additive repository steps. Use when finishing a unit of work, or when the user says 'checklist', 'wrap up', or 'wrap up session'."
---

# Checklist — end-of-task wrap-up

Run one fixed spine: reconcile the record, capture knowledge, fold in lessons,
persist, then write and validate the handoff. The first four steps are slots.
Profiles bind them and add steps; the handoff is not a slot, and only an
`own-worktree` step may follow it.
Run the named binding skill as the step, preserving its own approval requirements.

## Resolve profiles before running the spine

Read the **user profile**, which applies to every session. It is
`$CHECKLIST_USER_PROFILE` when that is set, otherwise `checklist/profile.md` under
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
`checklist_surfaces` in the continuity configuration (none by default).

Treat output as candidates: exclude another session's changes, and include your
own work even if already committed and pushed. For a linked worktree, read its
profile first if it differs from the main checkout's. A repository profile at
`.claude/checklist-profile.md` is additive. Read each complete file, including
notes that qualify its steps.

Profiles with a `checklist-profile` JSON fence are composed by the standard-library
module `scripts/lib/checklist.py`. The fence declares `name`, optional `bindings`,
optional `steps`, and an optional `ask: {"command": "/ask-step"}`. The ask
binding is one user command, not a slot or a spine step. Repository profiles
cannot bind it. A binding has a `command` and a list of item types it
`consumes`; a step has a unique `id`, an `after` anchor, and `instructions` (or
a `section` naming a level-two heading in the same Markdown file).

Run the composer with the user profile first and repository profiles in resolved
order. Paths below are placeholders to replace with the actual resolved files:

```bash
python3 <checklist-module> plan --user-profile <user-profile> \
  --repository-profile <repository-profile> --handoff <resumed-handoff> \
  --session-id <current-session-id>
```

Repeat `--repository-profile` for each additional file. Omit `--handoff` when no
handoff was resumed. `plan` writes a start marker row to the current session's
ledger; `--session-id` defaults to the Claude Code session in the environment,
so pass it in Codex. No profile is also a valid plan: omit the profile arguments, and the plan is the
five spine steps ending with the handoff. Record, knowledge, and persist are
unbound in the spine; lessons defaults to `/improve-harness`, consuming `lesson`
items. An unbound slot's `carries` lists item types for the final filing pass.

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
knows unattended mode only through the optional `unattended` section of the continuity
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

### 1. Reconcile the record — slot `record`

Run the bound command with current session items and matching carried items.
The profile defines the record's stores and policy. If unbound, the step does
not fail: send its `carries` items through the filing rules before the final handoff. When
bound, note the UTC time the record write finishes; the wrap check needs it.

A bound record also composes the **session summary** after its ticket step,
once the session's record writes are final: the bound record's outcomes,
each project's goal, what shipped, follow-up tickets, and
decisions. It writes each project's part into that project's session-log entry.
Keep the summary file it names, or the reason it gives for not composing one;
the report starts with it.

### 2. Capture knowledge — slot `knowledge`

Run the binding on new knowledge and matching carried knowledge. Keep anything
pending approval or otherwise unsaved for the filing pass. If unbound, the
filing pass warns and retains the item.

### 3. Fold in lessons — slot `lessons`

Run the bound lesson-routing command on current lessons and carried lesson text.
The default command is `/improve-harness`; a user profile can replace it.
Send every unsaved lesson through R4 in the filing pass. Anything the slot
leaves pending becomes an ask; a failed bound write is reported with its error.

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
| R4 | Lesson or knowledge | Pass to `lessons` or `knowledge`; anything the slot leaves pending becomes an ask. |
| R7 | Changes a project document (spec, design document, README) | Edit through `record`; a change to an approved spec becomes an ask. |
| R2 | Names an open ticket | Comment on that ticket through `record`. |
| R5 | Work with a stated outcome and no matching open ticket | New ticket through `record`, with recommended priority and a one-line reason. |
| R6 | Otherwise: optional suggestion, observation, idea with no outcome | Drop with the reason. |

The agent makes the judgment, including R5 versus R6 and whether R7 needs
approval. R1's already-recorded check, R2's open-ticket check and R5's matching
search require a successful, supported, valid record read. Use `record_read`
and its response contract when bound. A failed, unsupported, or malformed read
is **unknown**, never absence: keep the item with outcome `read failed`, naming
the item and the error. Never drop it under R1 or create a ticket under R5 on
that evidence. An information-only R1 can explicitly set `information_only: true`.

Run the required bound command for each write and collect explicit receipts.
For each ask, pass the ask command a JSON object containing `text` (the item),
`session_id` (its source session), `directory`, `ticket` (linked ticket or null),
and `choices` (the user's options). An ask is **never filed as a ticket**.
These fields also appear in the filing report's `ask` payload. For R4 pending
items, use `destination: "ask"` and the ask command's write acknowledgement.
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
Use the same profile arguments for the filing pass:

```bash
python3 <checklist-module> file --user-profile <user-profile> \
  --repository-profile <repository-profile> --handoff <remaining-items> \
  --filing <filing-outcomes>
```

The module does bookkeeping, not command execution. Its output removes only
explicitly filed or dropped items and includes a `filing` report listing every
item, rule, destination or reason, warnings and failures. Keep that report in
the payload through checkpoint. A missing binding retains the item and warns,
without failing wrap. A bound write failure retains it and fails wrap. With no
ask binding, the report's `asks` groups asks under their directory; retain this
report for the sweep report and keep the producing handoff. Do not archive it.
For a failed write, checkpoint the retained payload before reporting failure.

Write the interactive session's handoff using the
same checkpoint module as `checkpoint`. Its slash skill is user-only;
call its script directly: `<checkpoint.sh>` is `scripts/checkpoint.sh` in that
skill's real directory (`../checkpoint/scripts/checkpoint.sh` from this
one). Use the actual current session identity in either tool.

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
marker in the ledger, every recorded change counts. When `record` is
unbound, omit `--record-at`; no record check runs. On a non-zero exit, report
each `wrap failed:` reason and refuse to report checklist completion.

Then a profile's `own-worktree` step may remove the session's own linked
worktree; removed earlier, the handoff records no repository and resume cannot
find it. It runs only after the wrap check passes, and only when the worktree is
clean, its branch is merged into the pushed trunk, and a plain
`git worktree remove` succeeds. Otherwise keep it.

## Carried-item contract

At each slot, consume the typed open loops listed in that step's `carried_items`
in the plan **as well as** the current conversation. Each entry has an `index`
into the original resumed handoff and its complete `item`. Pass that item intact,
including its producing session identity and time, a decision's author and source,
lesson text, and artifact location/disposition. Also pass the resumed handoff's
session summaries to a record binding; earlier history belongs to its producer.

Collect explicit saved-item acknowledgements from each binding as JSON:
`{"record": [0, 2], "knowledge": [3]}`. These are indexes into the original
input, not into a shrinking list. Do not acknowledge pending, failed, unsupported,
or merely presented items. If a binding lacks provenance support, report it and
send the affected loops through the filing rules. Untyped legacy loops also
pass through the filing rules at wrap; checkpoints may still carry them.

Use the same profile arguments to settle the input:

```bash
python3 <checklist-module> settle --user-profile <user-profile> \
  --repository-profile <repository-profile> --handoff <resumed-handoff> \
  --receipts <saved-item-receipts.json>
```

The returned JSON removes only acknowledged loops of types the binding consumes.
It preserves every other field and never rewrites the source handoff. Merge its
remaining loops with this session's unsaved items, then apply the filing rules
in step 5 under the current session. Unbound destinations warn without failing.

## Report

Start the report with the session summary from step 1, unedited, in Claude
Code and Codex alike. When none was composed, start with the one line saying
why. Then name the user and repository profiles resolved. Report each planned step in its
execution order, its bound command if any, and its result: run, carried (an
unbound slot), pending, or failed. Check the results with the same profile
arguments before reporting completion:

```bash
python3 <checklist-module> report --user-profile <user-profile> \
  --repository-profile <repository-profile> --results <results.json> \
  --summary <summary-file> --handoff <written-handoff> [--unattended]
```

`--handoff` is required and must name the valid handoff checkpoint wrote;
report refuses an omitted, unreadable, malformed, or invalid handoff.
`--summary` is the file the record binding wrote. When it could not compose
one, pass `--no-summary <reason>` with its reason instead. When its output has
no session summary at all (a binding that predates session summaries), pass
`--no-summary "<command> composed no session summary"`; the wrap continues. A bound record with
neither fails the check, so the summary is never silently left out. With record
unbound, omit both: nothing composes a summary, and the output says so. The
output's first field is the summary.

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
