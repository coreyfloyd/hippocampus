# Interface

What an adapter, a profile author, or another tool may rely on. Anything not listed here is
internal and may change. The vocabulary is defined in `docs/glossary.md`.

Paths below are relative to the repository root. An adapter locates the package by the
directory it installs it into, never by importing it: every entry point is a command.

## 1. Storage

| What | Default | Override |
|---|---|---|
| Handoffs | `~/.local/state/hippocampus/handoffs/` | `HANDOFF_STATE_DIR`, else `handoff_dir` in the configuration |
| Ledger (one file per session) | the parent of the handoff directory | `HANDOFF_LEDGER_DIR` |
| Timed checkpoint state | `timed-checkpoints/` beside the handoff directory | `HANDOFF_TIMER_DIR` |
| Pre-compaction backups | `~/.local/state/hippocampus/compact-state/` | `HANDOFF_COMPACT_STATE_DIR` |
| Checklist state (the unattended-wrap marker) | `~/.local/state/hippocampus/checklist/` | `CHECKLIST_STATE_DIR`, else `checklist_state_dir` in the configuration |

None of these is inside a tool's own data area (`~/.claude`, `~/.codex`, a plugin's data
directory), so removing an adapter never removes a handoff. Both tools read and write the
same directory, so a handoff written under one is listed by the other.

A handoff is one JSON file, `schema_version` 2, named
`<readable-subject>-<12-hex-subject-hash>-<session-id>.json`. The subject and the session
together identify it, so two sessions on one subject never overwrite each other. The
`subject.working_directory` is a canonical path, and `git.repository_root` is the parent of
`git rev-parse --git-common-dir`, so every worktree of a repository shares one root.

The session id comes from `--session-id`, else `CODEX_THREAD_ID`, else
`CLAUDE_SESSION_ID`, else `CLAUDE_CODE_SESSION_ID`. Codex's own thread takes priority
over an inherited Claude parent's session identity.

## 2. Configuration

One JSON object, read from `$HIPPOCAMPUS_CONFIG`, else
`${XDG_CONFIG_HOME:-~/.config}/hippocampus/config.json`. The same file serves both tools. An
absent file is an empty configuration. A file that is unreadable, not an object, or holds a
wrongly typed value is an error, reported by the command that read it. It is never read as
an empty configuration.

| Key | Type | Meaning |
|---|---|---|
| `handoff_dir` | string | Where handoffs are stored. `~` is expanded. |
| `checklist_state_dir` | string | Where the checklist keeps its marker. |
| `checklist_surfaces` | list of strings | Standing surfaces the surface detector reports in addition to the session's own repository. |
| `checklist_suite_baselines_dir` | string | Directory of per-repository suite baseline files the surface detector reports. |
| `harness_enforcement_reference` | string | Optional slim-harness enforcement reference; require an absolute path or a `~/` path (expand `~` to the current user’s home). Ordinary relative paths are configuration errors, never relative to the working directory. If absent, report “no enforcement reference configured” and inspect hooks directly. |
| `timed_checkpoint_minutes` | positive integer | Whole-minute interval after each checkpoint; at least 1, default 55. Fractional values and other JSON types are refused in both tools. |
| `timed_checkpoint_token_limit` | positive integer | Timed prompts checkpoint only below this token count; default 200,000. |
| `prune_days` | positive integer | Age in days at which a handoff becomes a `stale_transcript` prune candidate. Shared by Claude and Codex; `PICKUP_PRUNE_DAYS` overrides it. Default: 7. |
| `cycle_sessions` | object | Maps a session name to a directory under the home directory, for a consumer that cycles sessions (section 8). |
| `unattended` | object | Optional unattended mode, section 6. |
| `auto_apply_lessons` | boolean | The auto-apply setting: a wrap, and a sweep in act mode, applies the lessons it recommends and the wiki captures and retained sources and outputs under the knowledge root. Default false. Any other type is an error. |

`python3 scripts/lib/handoff.py config-get <key>` prints one value (a boolean as `true` or `false`, so `auto_apply_lessons` prints `false` when absent), a list one item per line,
and exits 2 with the reason on stderr when the configuration is unreadable or the value is
mistyped.

## 3. Handoff engine: `scripts/lib/handoff.py`

Standard library only. Every command reads plain arguments, the environment, and stdin, and
writes stdout. Exit status: 0 done, 1 for a negative answer (`repository-root`,
`is-interactive`), 2 for a refused or failed operation. The hook adapters exit 0 whatever their command
returned, so a broken hook never blocks a session.

| Command | Purpose |
|---|---|
| `resolve [cwd] [--subject] [--session-id ID]` | Print the handoff path for a directory and session. |
| `repository-root [cwd]`, `count [cwd]` | The shared repository root, and how many handoffs exist for it. |
| `checkpoint [--cwd D] [--session-id ID] [--trigger T]` | Read continuation JSON on stdin, append a dated history entry from `resume.history_entry` (the authored one-line `resume.session_summary` at checkpoints), retain earlier ledger entries, compose subject and git, write atomically, lint, and print the resume paste block. A wrap stores the complete chain's `resume.session_summary` separately. Writes even when the lint fails and reports the failure. `T` is `checkpoint`, `wrap`, or `manual`; the pre-compaction hook uses `pre-compact`. |
| `write PATH` | Low-level atomic write. Refuses a payload that fails the lint. |
| `lint [PATH] [--session-id ID]` | Validate a handoff. `scripts/lint-handoff.sh` is a thin adapter over this command. |
| `ledger-ticket --ticket T --session-id ID` | Record a ticket the session read, changed, or closed. |
| `ledger-file PATH --cwd D --session-id ID` | Record a file a shell-driven edit changed. |
| `ledger-artifact --location L --disposition keep\|remove [--status pending\|recorded\|removed] --session-id ID --cwd D` | Record, link, or retire a published artifact. The one command any publishing tool calls. |
| `is-interactive [JSON]` | Exit 0 for an interactive session, 1 for a headless entry point or a subagent (`agent_id` in the payload). |
| `state-dir`, `config-get KEY` | Where handoffs are stored, and one configured value. |
| `migrate` | Rename handoffs keyed by directory alone to their per-session path. Idempotent. |
| `timed-checkpoint-check [--session-id ID] [--transcript-path P]` | Print JSON with `tokens`, `limit`, `below_limit`. Read the same latest transcript usage as the context guard; unknown usage exits 2 and never means below the limit. |
| `timed-checkpoint-prompt [--session-id ID]` | Print the exact shared timed prompt, rendered from `scripts/lib/timed-checkpoint-prompt.txt`. |
| `claude-timer-set --session-id ID --job-id ID` | Retain the CronCreate job ID for the next checkpoint's CronDelete instruction. |
| `timed-checkpoint-wait PATH` | Internal detached Codex worker; locks ensure one pending timer per session. |
| `post-compact`, `pre-compact`, `context-guard`, `ledger-record`, `guard-decide` | Hook decisions, section 5. |
| `cycle-request-*`, `automated-cycle-handoff` | Support for a consumer that cycles sessions, section 8. |

`scripts/lib/handoff.sh` is a sourceable shell library over the same commands:
`handoff_checkpoint`, `resolve_handoff_path`, `handoff_repository_root`, and the rest.

A checkpoint's input is the continuation JSON described in `skills/checkpoint/SKILL.md`:
`resume.headline`, `resume.next_action`, `resume.session_summary`, `resume.open_loops[]`,
`spawned_processes`, and `session_items[]`. Each session item has a `type` (progress,
commitment, decision, knowledge, lesson, artifact, or open_loop), `context` (at most 600
characters), `disposition`, the producing `session_id`, and `produced_at`. A decision also
has `author` and `location`; an artifact has `location` and a `keep` or `remove`
disposition. An item carried in a handoff keeps its producer's identity and date until a
slot binding consumes it. Checkpoint retains every session item other than an artifact
in the session ledger; it is restored into `resume.open_loops`
by each later checkpoint, pre-compaction write, stop skeleton and wrap, once per
`session_id`, `produced_at`, `type` and `context`, until the wrap files or drops it.
Pickup copies the resumed session's unsettled items into the successor's ledger. The
stale-handoff guard and the context-usage warning ask for new lessons, decisions and
knowledge in `session_items`.

Checkpoint also retains `resume.close_outcomes[]` and `resume.touched_tickets[]`
from the session ledger, beside `resume.session_history[]` and
`resume.touched_projects[]`. At wrap the agent supplies `resume.history_entry`
for the current write and the complete `resume.session_summary` for the report.
Projects lookups and writes receive `session_summary`, `close_outcomes`, and
`touched_projects` as additional request fields outside the item identity.
Project items remain pending without a lookup or write when the session summary
is missing, null, or blank; the agent must write a nonempty summary and retry.
At wrap, when a tickets record write is bound and touched tickets exist, their
reread must succeed before project lookup or write. A failed or malformed reread
keeps project items pending. With no tickets record write bound, no reread runs:
stored close outcomes are the complete known set, and a projects-only profile
proceeds with those outcomes and the supplied summary. The filing result records
`ticket_read.status` as `unbound` for that case, `not_needed` when there are no
touched tickets, or `read` after a successful reread.
A close outcome holds
`kind` (milestone or epic), `title`, `state` (open or closed), integer `done` and
`total`, `triggering_ticket`, and timezone-qualified `produced_at`. A touched
ticket is a stable reference string. The shared ticket record-write contract,
including the wrap-only read of exactly these tickets, is defined in
[record](skills/record/SKILL.md#ticket-reads-and-close-outcomes).
Checklist report emits `outcome_line` first, built only from these stored facts.

`resume.resumed_chain[]` retains each selected `handoff` path, its producing
`session_id`, and timezone-qualified `resumed_at`, plus `written_at` and `skeleton`.
Pickup copies history entries, close outcomes, touched tickets, and these records
into the successor ledger immediately. Checkpoint restores them from that ledger
through compaction; `wrap-check` names every missing history entry or close outcome
in the final handoff. Only pickup, native same-session resume, and compaction
continue the chain. A brief or pasted prompt alone starts a new chain.

## 4. Pickup: `scripts/pickup.sh`

Prints one JSON object. With no arguments it lists handoff candidates for the current
directory (siblings marked), falling back to recent sessions from the tool's own history.

| Option | Effect |
|---|---|
| `--handoff PATH` | A briefing for one handoff. |
| `--session ID` | A specific transcript, from either tool. |
| `--json` | Accepted for compatibility; JSON is always emitted. |
| `--no-commitments` | Skip the binding's commitments request and label it skipped; preserve handoff commitments. |
| `--prune` | Archive handoffs whose transcript is missing or at least the configured prune age. Never deletes. |

Every failure prints the same object shape, `{"version": 2, "error": CODE, "message": TEXT,
...}`. Normal absence (`no_transcript_directory` or `no_other_session`) exits zero;
other errors exit non-zero. Codes include `usage`, `handoff_config_error` (the configuration
is unreadable or mistyped), `engine_not_found`, `engine_failed`, `engine_bad_output`,
and `record_helper_failed` (the record-read helper could not run or produce a JSON
object). Helper failures exit non-zero, retain handoff-derived sections, and name
the helper path and actual failure in `message`; they are not record outages.
`PICKUP_ENGINE` names the engine (`skills/pickup/scripts/pickup.py`) when an
adapter installs it away from the scripts. The wrapper resolves its own real
location, including when invoked through a symlink, and supplies its package's
`scripts/lib/pickup_record.py` independently of the engine location.
`PICKUP_RECORD_HELPER` overrides that helper path for an adapter that installs
helpers elsewhere. Both paths may be absolute or relative to the invoking
working directory. A direct engine invocation uses `PICKUP_RECORD_HELPER` when
set; otherwise it resolves the helper from the engine's real package location.
A standalone engine outside the package therefore needs the helper override.
The helper's accompanying library modules must remain available alongside it.

Prune discovery checks Claude's `~/.claude/projects/<cwd-slug>/<session-id>.jsonl`
(`/` and `.` in the stored working directory become `-`) and Codex rollouts in
`${CODEX_HOME:-~/.codex}/sessions/` and `archived_sessions/`. Codex rollouts match the
session's thread id, including window files; age is measured from the newest matching
file's modification time. A missing transcript is a `missing_transcript` candidate;
a transcript at least `prune_days` old is a `stale_transcript` candidate. Listing
reports candidates without moving them; only `--prune` archives them. An unavailable
Codex store returns `session_store_unavailable` before archiving.

Other settings: `PICKUP_TRUNK` selects the comparison branch and
`PICKUP_PRUNE_DAYS` sets the archive age threshold. A selected handoff preserves
record pointers and carried commitments labeled "from handoff". With no user
binding it states that no record read is bound. With a binding it adds
`record_read.command` and `record_read.requests` for the agent to run; it never
executes the skill. Requests use the resumed session identity and full handoff.
Ticket references come from handoff open-loop `anchor.ticket` pointers, without
service-specific parsing. Profile resolution matches the checklist user profile;
an invalid or unreadable profile is a record-read failure.

The agent saves this report and the raw skill responses, then runs:

```sh
python3 scripts/lib/pickup_record.py --complete --ticket-status ticket-response.json \
  --commitments commitments-response.json < pickup-report.json
```

Omit a response argument when its skill failed to run or commitments were
skipped. `--complete` treats missing requested responses as failures. The helper
validates each response with the record-read validator, checks exact ticket
reference coverage, and appends only passing rows to `briefing`, retaining all
handoff-derived sections. Successful rows also appear in `record_read.results`;
failed requests have no results entry and say `record read unavailable: <reason>`.
Only a validated empty response renders as none. Commitments from the binding
are labeled "from record". This helper reads stdin, profiles and response files;
it performs no record writes and never starts a checklist or writes a ledger
marker. It also accepts `--no-commitments` when preparing a report directly.

## 5. Hooks

Six hook moments, each a bash adapter that pipes the hook payload on stdin to an engine
command and exits 0. An adapter registers each in its tool's own format.

| Moment | Adapter | Engine command |
|---|---|---|
| Session start | `scripts/post-compact-restore.sh` | `handoff.py post-compact` |
| Before compaction | `scripts/pre-compact.sh` | `handoff.py pre-compact` |
| Prompt submit | `scripts/context-guard.sh` | `handoff.py context-guard` |
| After a tool call | `hooks/handoff-ledger.sh` | `handoff.py ledger-record` |
| Stop | `hooks/handoff-staleness-guard.sh` | `handoff.py guard-decide` |
| After a tool call (shell) | `hooks/checklist-nudge.sh` | `checklist.py wrap-cadence` |

The payload fields the engine reads: `session_id`, `cwd`, `source` (session start;
`compact` after a compaction), `transcript_path` (prompt submit), `tool_input` and
`tool_response` (after a tool call), `stop_hook_active` (stop), and `agent_id` (present only
for a subagent). Hooks act only for an interactive session: a payload with `agent_id`, or an
entry point in `sdk-cli`, `sdk-py`, `sdk-ts`, `sdk`, `mcp`, or `headless`
(`CLAUDE_CODE_ENTRYPOINT`), gets no output.

`hooks/checklist-actor-guard.sh` is an optional seventh adapter. Registered before a shell
tool call, it denies a subagent or headless session the checklist and the checkpoint
writers, using `checklist.py actor-guard`.

Every successful interactive checkpoint replaces its timed checkpoint. Claude Code
receives a pinned local cron minute rounded up so it is strictly in the future
and never earlier than checkpoint time plus the interval, `recurring: false`, session-only CronCreate,
CronDelete of the previous job, and the exact shared prompt. The agent records
the new job ID with `claude-timer-set`. Codex starts a detached worker that reads
the session's replaceable deadline and queues the same prompt through
`codex queue --thread ID --message TEXT`. One worker lock serializes delivery;
a scheduling lock makes replacement and delivery mutually exclusive. No PID is
killed. A delivery receipt records command failures as well as success. Timers,
receipts, Claude job IDs, and transcript locations live in `timed-checkpoints/`
beside the handoff directory; `HANDOFF_TIMER_DIR` overrides it.

At or above the configured token limit the timed prompt does nothing. Below it,
the agent writes a checkpoint. The pre-compaction hook writes one itself from
ledger history, touched tickets and projects, and git state; it preserves any
agent-written continuation and appends a factual history entry. It keeps the
five raw-input backups as well. The command has an eight-second budget inside
the hook's ten-second timeout. Post-compaction restore and pickup read the
updated handoff; Claude restore repeats the scheduling instruction because
PreCompact cannot call CronCreate.

An automatic stop handoff is marked `skeleton: true`, carries earlier history
entries from the ledger, and adds no entry. Every handoff, including a skeleton,
requires a timezone-qualified ISO `written_at`; a schema-v2 subject requires a non-empty `session_id`. The stop
writer supplies the timestamp through the shared checkpoint composer. Pickup
refuses invalid copy metadata with `chain_copy_failed` and names the invalid
field, preserving that diagnostic across its helper boundary. A valid skeleton
passes handoff lint but cannot complete a wrap. Checkpoint and wrap never fill a
missing account from a headline or placeholder; a missing real history entry fails validation.

The ledger attributes a commit to the session only after a shell call that succeeded: the
payload's `exit_code` (or `exitCode`) is 0, or, with no exit code, the event is
`PostToolUse` and `tool_response.interrupted` is `false`. Claude Code reports no exit code
and sends a failed call to `PostToolUseFailure` instead.

`hooks/checklist-nudge.sh` names the checklist command `$CHECKLIST_COMMAND`, default
`/checklist`. An adapter whose tool namespaces the package's skills sets it.

**The Claude Code plugin** is this repository: `.claude-plugin/plugin.json` is its manifest,
`.claude-plugin/marketplace.json` lists it, and `hooks/hooks.json` registers the six hooks
above with `${CLAUDE_PLUGIN_ROOT}` paths. The plugin sets `CHECKLIST_COMMAND` to
`/hippocampus:checklist`. It registers no `PreToolUse` hook.

Hook output is JSON in the tool's hook format or plain text context. At stop, an interactive
session with no handoff gets a skeleton handoff written for it (subject, git state, and the
files it wrote, with an empty headline); the hook never overwrites an existing handoff and does
not block. Once a handoff exists, the stop hook prints a block decision only for the session's
own work since it: a commit the session made after the handoff's baseline, or a file the
session wrote that is still uncommitted and newer than the handoff. Another session's changes
in the same checkout never block.

## 6. Checklist engine: `scripts/lib/checklist.py`

Standard library only. The skill (`skills/checklist/SKILL.md`) runs the plan; the engine
composes and checks it and executes record-write commands. It writes no handoff and runs no skill.

| Operation | Purpose |
|---|---|
| `plan [--user-profile P] [--repository-profile P ...] [--handoff H] [--unattended] [--session-id ID]` | Compose the spine and route carried items from the session ledger snapshot. Returns its `handoff` payload. An optional handoff path must match pickup’s recorded selection; its source file is never reopened. Writes a start marker to the session’s ledger. |
| `settle ... --handoff H --receipts R` | Remove the loops a binding acknowledged. Never rewrites the source handoff. |
| `apply-lessons ... --handoff H --lessons L` | With the auto-apply setting on: write and commit each lesson row, one commit each; drop `skip` rows; keep each outcome in the session ledger; return the payload without settled items, plus `lesson_outcomes`. A failed lesson stays carried and exits 0. With the setting off it refuses, exit 1. |
| `deliver-lessons ... --handoff H` | After the persist binding: push undelivered lesson commits, retrying once when the remote moved, or, when the repository refuses a direct push or the routing file requires it, undo the retry's merge when that second push is refused for a pull request, re-apply the checkout's lessons on one lesson branch (`lesson/<session id>-<digest>`, distinct per session, one commit each, cut from the remote's base branch or continuing the session's branch), push it, and run the routing file's `lesson-pull-request-command` once. That command reads one JSON object on stdin (`checkout`, `remote`, `base`, `branch`, `title`, `body`, and `lessons`: one `title`, `path` and `commit` per lesson), opens the pull request, owns how it merges, and prints the pull request's reference as its last line. The package never merges. Each delivered row names the delivered `commit`, its `local_commit`, `lesson_branch` and `pull_request`; the local commit gets a delivered mark (`refs/hippocampus/delivered/<local_commit>`) that the saved line honors in every later wrap. Adds `lesson_outcomes` and `lesson_asks`, one ask per applied lesson in `resume.open_loops` or unrecorded `session_items`, each with `choices: []`. Pushes nothing with persist unbound. |
| `apply-knowledge ... --handoff H --knowledge K [--knowledge-profile P]` | With the auto-apply setting on: check each captured row (`wiki`, `source`, `output`) against the knowledge profile (default `~/.config/hippocampus/profile.md`): every named file written since this session's `plan` start marker, inside its kind's files (`wiki` under `wiki/` or `raw/` with at least one under `wiki/`, plus the profile's `hot_file` and `operation_log_file` that a compile writes; `source` under `raw/`; `output` under `output/`), and a `wiki` capture only with the wiki enabled. A row naming the knowledge root itself fails. A captured item is settled; a failed one stays carried with its approval and exits 0. A `user_fact` row (`text`, `destination`, `source`, `choices`, `approve` naming the choice that approves the save, never `default`) marks its item `user_fact` and keeps it carried; a later capture row for that item settles it only with `answer` equal to `approve`, recorded in the outcome. A compile file the profile places outside the root fails only a row that names a file outside the folders, naming the key. Written-during-this-wrap is measured from the wrap's first `plan` start marker. Keeps each outcome in the session ledger; returns the payload plus `knowledge_outcomes` and `knowledge_asks`, one ordinary ask per carried fact about the user. Items with no row are unchanged. With the setting off it refuses, exit 1. |
| `record-over-limit ... --measure M --duplicates D [--session-id ID]` | With the auto-apply setting on and lessons applying: merge the slim helper's `measure` and `duplicates` output into the over-limit records. Each tracked file in a git repository with a hosted remote is one record keyed by `repository` (the `origin` remote's, else the only remote's, whole repository path, such as `owner/name` or `group/sub/name`, with no host; local-path, `file://`, scp-absolute and `~user` remotes name none) and `path` inside it, holding `size`, `limits` (each with `tool`, `unit`, `measured`, `limit`), `duplicates` (each with `match`, `similarity` and its `spans` by repository and path), `sessions`, `first_recorded` and `last_recorded`. A measurement replaces only what it measured: the running tool's limits, every unit for a file loaded in full and the description units for a skill only listed, and a duplicate rule only when every file it names was loaded in full in this call; new findings merge with kept ones. A record is removed only when nothing remains. Returns `recorded` (one `line` each), `reported` (rows outside git, not tracked by git, without a hosted remote, where git could not be read, or a Codex chain, with their attended `action` and a `reason`; never recorded) and `unresolved`. The store is `over-limit-records.json` in the session ledger directory. With the setting off, or the routing file's `lesson-policy: propose`, it refuses, exit 1. A damaged store (not valid JSON, not a records file, or a malformed row) or a malformed payload row is a clear error, exit 1, and the store is left as it is. |
| `over-limit-records` | Print `{"records": [...]}` from the store, in any session kind; read-only. |
| `file ... --handoff H --filing F` | Apply explicit filing outcomes to remaining loops and unrecorded session items (an applied lesson's row must be R3; a `user_fact` item is `filed` outside its ask only with `answer` equal to its `approve` choice and `dropped` only with another answer; any other row fails alone); execute per-kind record writes with lookup before write; return a handoff payload with receipts and a filing report. A failed or uncertain write returns exit 1 and retains the payload on stdout. |
| `record ... --handoff H --filing F` | Run the same filing and record writes mid-session without the rest of checklist. |
| `wrap-check ... --written-handoff H [--record-at T] [--unattended]` | Fail, with the reason, when the handoff is invalid, a bound item is still carried, a read/write failed, or `record` is bound and its latest write is older than the session's last change. |
| `report ... --results R --handoff H [--unattended]` | Require a valid written handoff containing the agent-authored `resume.session_summary` and check its filing outcomes and the run's step results; the report starts with the stored outcome line followed by that summary. |
| `wrap-cadence` | Read a hook payload on stdin and print `none`, `checkpoint`, `unattended-checklist`, or `checklist`. |
| `actor-guard`, `is-completion-command` | Hook helpers. The first prints a deny decision; the second exits 0 when the command completes an unattended slate. |

An operation that cannot run prints `checklist: <reason>` on stderr and nothing on stdout, exit 1. A malformed routing file is such an error for every operation that reads it;
`report` lists it in `errors` and still ends with its asks.

With the auto-apply setting on, `plan` adds `auto_apply` (`{"lessons": "apply", "knowledge": "apply"}`,
or `{"lessons": "propose", "reason": ..., "knowledge": "apply"}` when the routing file's
`lesson-policy: propose` forbids applying lessons), `file` adds `filing.lessons` and
`filing.knowledge` (`captured`, `asked` and `failed` rows; a captured row lists `created` and
`updated` paths relative to the knowledge root), and `report` adds `lessons` and `knowledge`.
With it off, none of these appear and `record-over-limit` refuses.

**The spine** has five steps in this order: `record`, `knowledge`, `lessons`, `persist`,
`handoff`. Only `persist` is a slot. Record is the package step calling per-kind record writes. Knowledge and lessons are native
steps running `/hippocampus:knowledge-capture` and `/hippocampus:improve-harness`
(plain skill names in Codex), consuming `knowledge` and `lesson` respectively.
Their destinations follow the knowledge profile and lesson routing file.
Profiles cannot replace or disable either native step. Unbound slots are carried: the items they would consume stay in the handoff
until the filing pass. Missing destinations warn and retain their items;
bound write failures fail wrap. `handoff` is not a slot and is the last spine step; only a profile step
`own-worktree` may follow it.

**A profile** is JSON, or Markdown with one fenced block tagged `checklist-profile`:

```json
{
  "name": "example",
  "record_read": {"command": "/read-work"},
  "ask": {"command": "/ask-step"},
  "record_writes": {"tickets": {"command": ["write-tickets"]}, "projects": {"command": ["write-projects"]}, "documents": {"command": ["write-documents"]}, "scheduled_jobs": {"command": ["write-jobs"]}},
  "bindings": {"persist": {"command": "/persist-step", "consumes": []}},
  "steps": [{"id": "tidy", "after": "persist", "instructions": "..."}]
}
```

A binding names a `command` and the item types it `consumes`. A user slot may
explicitly bind `persist` to JSON `null` to leave it unbound. This keeps the spine step and carries
its unsaved items; it does not remove or skip the step. A step has a unique `id`, an
`after` anchor (`before-spine`, `record`, `knowledge`, `lessons`, or `persist`; `handoff`
only for the step `own-worktree`, which must use it), and
`instructions`, or a `section` naming a level-two heading in the same Markdown file. A user
profile applies to every session; a repository profile only adds steps. A profile that
removes, skips, or replaces a spine step, or adds any step but `own-worktree` after `handoff`, is rejected with a
message naming the step. User profile: `$CHECKLIST_USER_PROFILE`, else
`${XDG_CONFIG_HOME:-~/.config}/hippocampus/checklist-profile.md`.

**Record-read binding.** A user profile may also declare
`"record_read": {"command": "/read-work"}`. This object has exactly one field,
`command`, a non-empty string naming the user's skill. Omit `record_read` to leave
it unbound; `null` is not a binding. A repository profile cannot declare
`record_read`, even if no user profile binds it. The composer rejects it with an
error naming `record_read`. The `plan` result includes `record_read` as that object,
or `null` when unbound; it adds no spine step. The composer never executes it.
The binding and validator contract below is identical for Claude Code and Codex.

**Ask binding and filing outcomes.** A user profile may declare
`"ask": {"command": "/ask-step"}`: exactly one non-empty command, separate
from slots and steps. Repository profiles cannot bind it. `plan` returns `ask`
(or null) and `rerun_all_steps: true`; an attended run after an unattended run
executes every step again and asks the user, without reusing pending results.

The agent applies the filing rules in order R1, R3, R4, R7, R2, R5, R6 (see
`skills/checklist/SKILL.md`). It runs bindings, then supplies `file` an array of
outcomes with `index`, `rule`, `status`. Indexes refer to remaining open loops
followed by unrecorded `session_items`. Status is `filed`, `dropped`, `pending`,
`failed`, or `read failed`. Filed outcomes require `destination`; dropped
outcomes require `reason`. Failed outcomes carry `error`. Read-dependent R1,
R2 and R5 require `read_status: "ok"`, otherwise the item is retained as
`read failed`. Information-only R1 uses `information_only: true`. R5 also
requires `priority` and `priority_reason`. R4 native rows retain unsaved items with `pending`, `failed`, `declined`,
`nothing`, or `not configured`; only a capture disposition or applied/proposal
receipt removes the item. Failed, declined, and pending native results make
`report: "incomplete"`, listing each step and reason, without failing handoff
validation. Nothing and not configured do not make wrap incomplete. Every ask requires non-empty `choices`. R4 `destination: "ask"` retains its
payload in `filing.asks` for invocation by the driving skill. After a successful
ask acknowledgement its row keeps `binding: "ask"`, `ask_status: "filed"`,
`native_step` and `status: "pending"`; its original item stays carried. Ask
delivery does not substitute for a capture receipt.

The ask command receives `text`, source `session_id`, `directory`, linked
`ticket` or null, and `choices`. Asks never become tickets. `file` returns the
payload with a `filing` object holding `items`, `warnings`, `failures`, and
`asks` grouped by directory. Each item includes the original item, its rule,
its binding and outcome; asks include their command payload. Keep this report
in the checkpoint payload and pass the written handoff to `report --handoff H`.
Without an ask binding, retain the handoff and list its asks under their
directory for the sweep report. Failed writes also retain items and report
errors. A completed filing sets `resume.next_action` to `Session finished.`;
retained items are named there. The wrap check fails on bound carried items,
but warns and passes for unbound destinations. Checkpoint behavior is unchanged.

**Unattended mode** is optional and absent by default. A user who launches sessions and
leaves them to execute approved work describes that mode in the `unattended` section:

| Key | Meaning |
|---|---|
| `state_module` | A Python file exposing `state_path(session_id)` and `read_state(path, session_id)`. The state is a mapping with `mode` (`"afk"` while the slate is running), `updated_by`, and `updated_at`. |
| `completion_command` | A regular expression matching the command that completes a slate. |
| `completed_by` | The `updated_by` values that command leaves in the state. |

While the state module reports `afk`, `wrap-cadence` answers `checkpoint`. After the
completion command succeeds it answers `unattended-checklist` until a passing
`wrap-check --unattended`, or an explicit attended `plan` starts all steps
afresh after an unfinished unattended wrap. Without the section every interactive session is `checklist`.

## 7. Skills

26 skills, each a directory with a `SKILL.md`. An adapter installs them where its tool
looks for skills. Each resolves its scripts from its own real directory, never from a
tool-specific home directory.

| Skill | Role |
|---|---|
| `hippocampus-set-up` | Create or extend the user profile and write and validate the user-owned record-read skill, with the user present. |
| `checkpoint` | Checkpoint the current session. `scripts/checkpoint.sh` is the entry point the checklist also calls. |
| `pickup` | Resume after a cold start. Its engine is `scripts/pickup.py`. |
| `checklist` | Wrap through the spine plus profile steps. |
| `record` | Run per-kind record writes mid-session or as checklist’s first step. |
| `handoff-prompt` | A copy-pasteable prompt that hands a slice of work to another session. |
| `sweep` | Sweep report and configured filing for abandoned sessions; see [sweep contract](docs/sweep.md). |
| `wip` | In-flight work, blockers, and pending approvals for the current session. |
| `improve-harness` | Route a lesson to the user's rules, skills, agent definitions, or memory. |
| `slim-harness` | Review one instruction source with the user, resolve conflicts, and leave edits uncommitted. |
| `absorb` | `/hippocampus:absorb` | See the absorb skill. |
| `dev-research` | `/hippocampus:dev-research` | See the dev-research skill. |
| `feature-research` | `/hippocampus:feature-research` | See the feature-research skill. |
| `feedback-research` | `/hippocampus:feedback-research` | See the feedback-research skill. |
| `knowledge-capture` | `/hippocampus:knowledge-capture` | See the knowledge-capture skill. |
| `meeting-capture` | `/hippocampus:meeting-capture` | See the meeting-capture skill. |
| `quick-research` | `/hippocampus:quick-research` | See the quick-research skill. |
| `research-absorb` | `/hippocampus:research-absorb` | See the research-absorb skill. |
| `research-sources` | `/hippocampus:research-sources` | See the research-sources skill. |
| `research-to-wiki` | `/hippocampus:research-to-wiki` | See the research-to-wiki skill. |
| `research-topic` | `/hippocampus:research-topic` | See the research-topic skill. |
| `transcribe` | `/hippocampus:transcribe` | See the transcribe skill. |
| `vault-audit` | `/hippocampus:vault-audit` | See the vault-audit skill. |
| `vault-compile` | `/hippocampus:vault-compile` | See the vault-compile skill. |
| `wiki-audit` | `/hippocampus:wiki-audit` | See the wiki-audit skill. |
| `wiki-compile` | `/hippocampus:wiki-compile` | See the wiki-compile skill. |

## 8. For consumers that cycle sessions

Session cycling is not part of the package. A consumer that cycles sessions reaches the
engine through commands and the configuration, never by import: `cycle_sessions` in the
configuration, and `cycle-request-path`, `cycle-request-write`, `cycle-request-validate`,
`cycle-request-dispatch`, and `automated-cycle-handoff` on the handoff engine.

## 9. Checking for personal references

`scripts/lib/reference_check.py --terms FILE PATH...` reports every occurrence of a listed
term, case-insensitively, as `path:line:column: term: text`. Exit status 0 is clean, 1 has
findings, 2 is a usage error. The term list is supplied by the caller and is not part of this
repository. `tests/test_shipped_surface.py` runs the check over the whole tree when
`REFERENCE_CHECK_TERMS` names a list.

## 10. Codex installation and normalization

`python3 scripts/install-codex.py [--codex-home PATH] [--codex PATH]` installs a
runtime copy, the 26 skill links, six hippocampus hooks and the optional actor
guard. The installer owns only the registrations and links recorded in
`hippocampus-install.json`; other hooks and configuration survive. Its seven
handlers must match `hooks/list` with `trustStatus: trusted`, or it restores the
previous install. `--uninstall` removes the adapter, retaining shared state.

`scripts/codex-hook.py OPERATION` reads one captured-shape Codex payload on stdin,
normalizes string tool responses and calls the shared engines through commands.
Advisory errors exit zero. `HIPPOCAMPUS_HARNESS=codex` selects the Codex transcript
context parser and actor classification for these calls. With `CODEX_THREAD_ID`
present, command-line checklist operations also read that session's `session_meta`
from `CODEX_HOME/sessions`. Source `exec`, subagents, unknown sources, mismatched
identity, and unreadable metadata are refused; interactive CLI, desktop and
app-server sources ignore a parent's `CLAUDE_CODE_ENTRYPOINT`. No caller-provided
model or tool name establishes interactive authority.

## 9. Record read: `scripts/lib/record_read.py`

A record read is defined in [the glossary](docs/glossary.md#language). The agent
runs the skill named by the user profile's `record_read.command`, gives it one
request below, then validates its JSON response before rendering it. The pickup
script does not execute this binding; the agent owns this read. The skill is read-only;
writes run through per-kind record writes in the package record step. The package supplies no record service.

Requests and responses have fixed fields. No additional, free-form, or
tracker-specific fields are permitted. Skill authors put additional context in
`title` or `latest_progress` text. Reference and link strings belong to the user's
record; the package imposes no service-specific reference or URL format.

### Ticket status

Input: `{"kind": "ticket_status", "references": ["work:17", "work:missing"]}`.
`references` is the list of ticket references the handoff points to. Output has
exactly `kind` and `rows`, with exactly one row per distinct input reference;
unresolvable references must appear, never be omitted:

```json
{
  "kind": "ticket_status",
  "rows": [
    {
      "reference": "work:17",
      "title": "Carry the work",
      "state": "active",
      "link": "https://example.org/work/17",
      "latest_progress": "Contract approved"
    },
    {
      "reference": "work:missing",
      "title": "",
      "state": "not_found",
      "link": "",
      "latest_progress": ""
    }
  ]
}
```

Every row has exactly the five fields shown, all strings. `reference` and `state`
are non-empty. `title` and `link` are non-empty except for a `not_found` row.
`latest_progress` may be empty when no progress is recorded. `not_found` is the
reserved state for an unresolvable reference; other non-empty state strings come
from the record. References cannot repeat within a response.

### Commitments

Input: `{"kind": "commitments", "session_id": "resumed-session-id",
"repository": "/path/to/repository", "handoff": {}}`. `session_id` is the resumed
session's id, `repository` is its repository path, and `handoff` is its full handoff
JSON object (the empty object here only abbreviates that value).
Output has exactly `kind` and `rows`; one row represents one piece of work the
record holds as carried by that session:

```json
{
  "kind": "commitments",
  "rows": [
    {
      "reference": "work:17",
      "title": "Carry the work",
      "state": "active",
      "link": "https://example.org/work/17"
    }
  ]
}
```

Each row has exactly these four fields, all non-empty strings. References cannot
repeat within a response. The state is text from the record, with no
service-specific enumeration. The handoff is input context, not a response field.

### Empty results, errors, and validation

Successful responses with no work use `{"kind": "ticket_status", "rows": []}` or
`{"kind": "commitments", "rows": []}`. For ticket status, an empty list is appropriate
only when no references were requested. Either request may instead return exactly
`{"kind": "error", "reason": "record unavailable"}` with a non-empty reason. An
error is never interpreted as an empty list or reported as `valid`.

Pass a response on stdin to either command:

```sh
python3 scripts/lib/record_read.py --expect ticket_status < response.json
python3 scripts/lib/record_read.py --expect commitments < response.json
```

| Stdout (one line) | Exit status | Meaning |
|---|---|---|
| `valid` | 0 | A structurally valid success response. |
| `invalid: <reason>` | 1 | Malformed JSON, missing or extra fields, wrong types, duplicate fields or references, unknown shape, or unexpected response kind. |
| `error: <reason>` | 2 | An explicit failure reported by the binding. Whitespace in its reason is collapsed to keep the verdict on one line. |

Without `--expect`, either success kind is accepted. An error is accepted as a
failure for either expected kind. Validation uses only the Python standard library,
reads stdin, prints a deterministic verdict, and never executes a skill or contacts
the record. It validates response structure; the calling agent must also check
that the response covers the requested references and reflects the requested
session. A structural verdict cannot establish record accuracy or completeness.

## 12. Sweep plan and results contract

The shared command defaults to watch-only. `sweep.mode: "act"` enables planning
when `run` receives `--decisions`. Without decisions it writes a watch-only
inventory, even with act configured. The agent performs every profile binding
call, following its `command` and `instructions` as during a checklist wrap.
The package executes record writes as described in `skills/record/SKILL.md`; it never executes record-read, persist or ask bindings. Skill
commands need no executable adapter or JSON stdin/stdout protocol.
`--user-profile` overrides `CHECKLIST_USER_PROFILE`, then
`$XDG_CONFIG_HOME/hippocampus/checklist-profile.md` (default `~/.config/hippocampus/checklist-profile.md`).
Only the user profile supplies bindings.

### Plan, perform, complete

```bash
python3 scripts/lib/sweep.py run --scope all --decisions /example/decisions.json --user-profile /example/profile.md
python3 scripts/lib/sweep.py complete --run-id <run-id> --results /example/results.json
```

Act `run` validates the agent's decisions, journals every planned write with
outcome `intent`, and returns JSON containing `run_id`, `report`, `phase` and
`work`. No archive or worktree removal happens at this step. Each work entry
contains a stable `write_id`, `operation`, unchanged `identity`, producing
`session_id`, `directory`, `source_handoff`, `text`, `rule` and `destination`.
Record-write work also carries the selected `command`, retained with its receipt
for undo through the same record write. Identity consists of the producing session, production time and text, never
position. A successor keeps the original identity. Per-operation fields are:

| Operation | Agent uses | Additional fields |
|---|---|---|
| `create_ticket` | `record_writes.tickets` | `priority`, `priority_reason` |
| `comment` | `record_writes.tickets` | destination ticket; inherits its priority |
| `edit_document` | `record_writes.documents` | destination document |
| `native_step` | package skill in unattended mode | `native_step`: `lessons` or `knowledge`; `command`; `unattended: true` |
| `apply_lesson` | agent's assessment; `complete` writes and commits it | `native_step`: `lessons`; `command`; `ledger_session` |
| `apply_knowledge` | package skill's Auto-apply section; `complete` checks the capture | `native_step`: `knowledge`; `command`; `ledger_session` |
| `persist` | persist binding, after lessons are committed | `command`; `checkouts`; `surfaces` |
| `ask` | ask binding, or direct presentation for interactive open sessions | `ticket` (possibly null), `choices`; open sessions also carry `activity_at` |

R1/R2 reads use the profile's `record_read`; the agent searches open tickets
through `record_writes.tickets` before choosing R5. One match becomes R2 and its
`destination` names that match; several become R3 with choices listing the
candidates. The engine treats `read_status: "ok"` as agent evidence, without
performing a read or search. Missing, failed, unsupported or malformed reads
remain `read failed`, never absence. Information-only R1 needs no read.

The agent supplies one result per `write_id` in a JSON array:

```json
[{"write_id":"<from-work>","status":"written","receipt":"<binding-receipt>","destination":"<actual-destination>"}]
```

| Status | Meaning and required fields |
|---|---|
| `written` | Confirmed write by this run; nonempty `receipt` and `destination` |
| `already_written` | Identity found before writing; original `receipt` and `destination` |
| `failed` | No write occurred; `error` |
| `uncertain` | Write may have occurred; optional `error` |
| `assessed` | `apply_lesson` or `apply_knowledge` only: a `lesson` or `knowledge` object, the wrap's row without `index` |

A missing result is `uncertain`. Missing or malformed acknowledgements and
lost replies must never be reported as failed. The engine flushes each result
into the report before post-filing work. Failed and uncertain items keep their
handoffs. Results cannot overwrite already recorded outcomes. A later run
resolves uncertain writes through identity lookup. `already_written` does not
count as new this run and does not belong to this run's undo journal.

A `native_step` carries its item and applies nothing. Return `carried`;
`nothing`, `not configured`, `declined`, `failed`, and `uncertain` also retain
the item. Native `written` and `already_written` are rejected.

With the auto-apply setting on, `run` adds `auto_apply`, as `plan` does at a wrap, and
act mode plans `apply_lesson` and `apply_knowledge` in place of `native_step`, except a
lesson under `lesson-policy: propose`, which stays a `native_step` whose `reason` says so.
Each section adds `would_apply` (watch-only, outcome `would apply`), `lessons_applied`,
`lessons_not_pushed`, `knowledge_captured` and `already_settled`. Watch-only runs the same ledger
search as act mode, read-only: an item a ledger already settles is listed under `already_settled`,
never under `would_apply`. With the setting off none of these appear. An unreadable routing file or a mistyped setting adds an `auto-apply` row to `errors` and sets what it governs to `failed` in `auto_apply`; those items stay `native_step` and the run continues.

Those two operations also accept the `native_step` statuses except `written` and
`already_written`, which are rejected. `complete --knowledge-profile P` (default
`~/.config/hippocampus/profile.md`) applies each `assessed` result through the wrap's
modules, measuring a capture's files from the run's `started_at`; one that cannot apply
is `failed` alone, whatever it raises; work already in the ledger stands, with a `warning`,
and goes on to delivery. Before it applies anything, `complete` reads the open-session evidence
given on that same call (or the configured checks) and the current activity of every handoff: an
`assessed` item whose handoff's or producing session is open, active again, or of unknown
abandonment is `carried` with that reason and nothing is written, committed or pushed for it; an
`applied` commit whose session is open is `not pushed` until a later sweep delivers it, and its
ask is not raised. New outcomes go to the ledger of the item's producing session, and every
session's ledger is searched by the item's identity (`ledger_session` names the one used); a
malformed ledger row, including one whose status is not a known terminal status (`applied`,
`dropped`, `failed`; `captured`, `asked`, `failed`), fails only itself, named in `errors`, and the
rest of that ledger is still searched; the item such a row names stays `carried`, with the reason,
until the row is repaired. A
settled item (a lesson not failed, a capture, or a fact whose ask was delivered) gets no work
entry and is reported under `already_settled` with outcome `already_written`, or `dropped`;
those rows are this run's work in no list, and undo never names them. A row's `receipt` is its commit, its target with no commit,
or a capture's files; a lesson row also keeps `target`, `change`, `commit`, `branch`,
`delivery` and any `pull_request`. A commit is `applied` until delivered, then `written`, or
`not pushed` with `error`, which keeps its handoff. With commits to deliver and persist bound,
`complete` journals one `persist` intent, returns `planned`, and on the next call delivers
as `deliver-lessons` does, only when that result is `written` or `already_written`; any other
result leaves the commits `not pushed` with the reason, including `uncertain` with a null `error`. With persist unbound it delivers at once. Asks for facts about the user and for always-loaded lessons follow in the
same way, the latter only once its commit is delivered, with `choices: []`; a commit `not pushed` raises no ask yet; a delivered ask settles its item, and its ledger records that, so no later run raises it again.
One ask per item identity per run: when two handoffs carry the same item, the second's ask row
carries `shares_ask` (the first ask's write id) and takes that ask's outcome, receipt and error
instead of journaling a second intent.

If an older slot leaves work pending without writing, return `failed` with `pending:
true` and an error. Completion journals an ask for that item. If worktree
checks fail after filing, completion journals an ask from that recheck, never
from the initial inventory's retention proposal. Open-idle-session asks likewise
wait for refreshed session checks and activity during completion. Configured
checks rerun without inheriting their earlier session ids; `complete` accepts
`--open-sessions` to replace agent inspection evidence. These deferred asks and
slot-pending asks return `phase: "planned"` with the expanded work list: perform
only new `intent` entries and call `complete` again. Archive waits for those results.
The global new-ticket limit (default 10) reserves a place for each planned
creation across all directories. Excess items stay unfiled and one ask names
the affected directories. This conservatively counts failed or preexisting
creations against that plan's capacity too.

### Binding identity obligation

Record writes and ask bindings store the unchanged item identity with every write,
with its original receipt, destination and originating run id. The agent asks
the appropriate binding whether that identity exists **before every write**,
including retries, slots, asks and successor handoffs. An existing identity
becomes `already_written`; a failed lookup blocks the write. The identity
index covers all writes, including closed destinations, and must prevent
concurrent or delayed writes with the same identity. Never change an existing
write's ownership to the current run. Keep preimages needed for document or
slot reversal under the receipt. These obligations name no record service.

### Store reservation and completion safeguards

Each command acquires the exclusive nonblocking lock on the handoff store's
directory inode (or nearest existing ancestor). Before an act plan returns,
it also saves a store-scoped reservation report pointer beside the store,
`.<store-name>.sweep-pending.json`. This survives the command exiting and a
change of configured report location. A later `run`, undo or retention exits
with `already running` until the reserved run completes; `inspect` remains
read-only. `complete` follows that pointer and accepts only its owning run id.
After recording all results and finalizing the run it releases the reservation.
To recover an interrupted plan, complete that run with known receipts and
`uncertain` for unknown writes. Do not discard its reservation or intents.

Completion rechecks handoff byte/file snapshots, current repository status,
open-session checks, and newly discovered sibling handoffs. Recorded dirty
files, retained items or asks, changed sources, active or open sessions veto
worktree removal. Each worktree gets at most one plain removal attempt;
successful removal precedes compare-and-delete of its local branch at its
observed commit. Remote refs are never changed. Archives are byte-preserving
moves, after every item is filed or dropped and every ask confirmed, with no
recorded or observed uncommitted files. Name collisions preserve existing
archives. See [sweep usage](docs/sweep.md) for the full worktree safeguards.

### Reversing a sweep run

```bash
python3 scripts/lib/sweep.py undo --run-id <act-run-id> --user-started
python3 scripts/lib/sweep.py complete-undo --run-id <act-run-id> --results /example/reversals.json
```

Only an explicit user request starts undo. Planning returns a journaled work
list of confirmed record/slot writes belonging to that run, plus
`archive_restorations`; it performs no reversal or restoration. Asks and
preexisting identities are excluded. The agent checks each target immediately
before reversing it through its profile binding. For an unchanged target,
close a ticket this run created as not planned, edit its comment to a stub, or
restore its document/slot preimage. The comment stub consists of the line
`Removed by sweep undo <run_id>`, followed by a blank line, then the original
record marker, unchanged. Never delete the comment. A retry recognizes this
run's stub by both the run id and the unchanged original record marker and
returns `reversed`. With one shared token, a manual
"not planned" close also reads as `reversed`; the binding cannot distinguish it
from the undo close. Never close an existing ticket. A later comment or
edit on a created ticket, or a later document edit, is a `conflict` and must
remain unchanged. A change made **between the check and the reversal is not
detected**. Bindings need not check and reverse atomically.

Reversal results are an array of `write_id`, `status` (`reversed`, `conflict`
or `failed`), and a reason/error when needed. Missing results are failed.
Undo also reserves the store between plan and completion; repeating a pending
undo returns that same work list. Completion flushes results and exclusively
restores archive snapshots, never
overwriting a newer handoff or a changed archive. The undo report is
`<run-id>.undo.md`; rerunning undo retries only failed items. Reversals use
the original run id and receipt so an already completed reversal can be
acknowledged after a lost reply. Worktree removal and local branch deletion
cannot be undone. Asks and their activity history remain delivered. Lessons and captures
this run applied stay in place: undo plans no reversal for them, and `undo` and the undo report
list them as `applied_left_in_place`, each with its `commit` or files. Optional
retention remains a separate operation, off by default; see
[usage](docs/sweep.md#undo-and-retention).

Checklist setup's `skills/hippocampus-set-up/scripts/profile.py` accepts only
`persist` in `--bindings`. `--record-writes` accepts an object of changed
`tickets`, `projects`, `documents` and `scheduled_jobs` commands, with JSON
`null` unbinding an individual kind. Omission preserves existing record writes.
Retired `bindings.record` profiles are refused with the `record_writes` shape. `--ask` accepts the JSON command object or
JSON `null` to unbind; omission preserves the existing ask. Legacy knowledge or
lessons binding blocks are refused, with the source file's line numbers and the
instruction to delete those blocks manually; no configuration is converted.
