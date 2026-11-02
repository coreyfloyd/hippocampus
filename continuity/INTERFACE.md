# Interface

What an adapter, a profile author, or another tool may rely on. Anything not listed here is
internal and may change. The vocabulary is defined in `docs/glossary.md`.

Paths below are relative to the repository root. An adapter locates the package by the
directory it installs it into, never by importing it: every entry point is a command.

## 1. Storage

| What | Default | Override |
|---|---|---|
| Handoffs | `~/.local/state/continuity/handoffs/` | `HANDOFF_STATE_DIR`, else `handoff_dir` in the configuration |
| Ledger (one file per session) | the parent of the handoff directory | `HANDOFF_LEDGER_DIR` |
| Pre-compaction backups | `~/.local/state/continuity/compact-state/` | `HANDOFF_COMPACT_STATE_DIR` |
| Checklist state (the unattended-wrap marker) | `~/.local/state/continuity/checklist/` | `CHECKLIST_STATE_DIR`, else `checklist_state_dir` in the configuration |

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

One JSON object, read from `$CONTINUITY_CONFIG`, else
`${XDG_CONFIG_HOME:-~/.config}/continuity/config.json`. The same file serves both tools. An
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
| `prune_days` | positive integer | Age in days at which a handoff becomes a `stale_transcript` prune candidate. Shared by Claude and Codex; `PICKUP_PRUNE_DAYS` overrides it. Default: 7. |
| `cycle_sessions` | object | Maps a session name to a directory under the home directory, for a consumer that cycles sessions (section 8). |
| `unattended` | object | Optional unattended mode, section 6. |

`python3 scripts/lib/handoff.py config-get <key>` prints one value, a list one item per line,
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
| `checkpoint [--cwd D] [--session-id ID] [--trigger T]` | Read continuation JSON on stdin, compose subject and git, lint, write atomically, print the resume paste block. Writes even when the lint fails and reports the failure. `T` is `checkpoint`, `wrap`, or `manual`. |
| `write PATH` | Low-level atomic write. Refuses a payload that fails the lint. |
| `lint [PATH] [--session-id ID]` | Validate a handoff. `scripts/lint-handoff.sh` is a thin adapter over this command. |
| `ledger-file PATH --cwd D --session-id ID` | Record a file a shell-driven edit changed. |
| `ledger-artifact --location L --disposition keep\|remove [--status pending\|recorded\|removed] --session-id ID --cwd D` | Record, link, or retire a published artifact. The one command any publishing tool calls. |
| `is-interactive [JSON]` | Exit 0 for an interactive session, 1 for a headless entry point or a subagent (`agent_id` in the payload). |
| `state-dir`, `config-get KEY` | Where handoffs are stored, and one configured value. |
| `migrate` | Rename handoffs keyed by directory alone to their per-session path. Idempotent. |
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
slot binding consumes it.

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

The ledger attributes a commit to the session only after a shell call that succeeded: the
payload's `exit_code` (or `exitCode`) is 0, or, with no exit code, the event is
`PostToolUse` and `tool_response.interrupted` is `false`. Claude Code reports no exit code
and sends a failed call to `PostToolUseFailure` instead.

`hooks/checklist-nudge.sh` names the checklist command `$CHECKLIST_COMMAND`, default
`/checklist`. An adapter whose tool namespaces the package's skills sets it.

**The Claude Code plugin** is this repository: `.claude-plugin/plugin.json` is its manifest,
`.claude-plugin/marketplace.json` lists it, and `hooks/hooks.json` registers the six hooks
above with `${CLAUDE_PLUGIN_ROOT}` paths. The plugin sets `CHECKLIST_COMMAND` to
`/continuity:checklist`. It registers no `PreToolUse` hook.

Hook output is JSON in the tool's hook format or plain text context. At stop, an interactive
session with no handoff gets a skeleton handoff written for it (subject, git state, and the
files it wrote, with an empty headline); the hook never overwrites an existing handoff and does
not block. Once a handoff exists, the stop hook prints a block decision only for the session's
own work since it: a commit the session made after the handoff's baseline, or a file the
session wrote that is still uncommitted and newer than the handoff. Another session's changes
in the same checkout never block.

## 6. Checklist engine: `scripts/lib/checklist.py`

Standard library only. The skill (`skills/checklist/SKILL.md`) runs the plan; the engine
composes and checks it. It writes no handoff and runs no skill.

| Operation | Purpose |
|---|---|
| `plan [--user-profile P] [--repository-profile P ...] [--handoff H] [--unattended] [--session-id ID]` | Compose the spine with the profiles and route a resumed handoff's carried items to their slots. Writes a start marker to the session's ledger. |
| `settle ... --handoff H --receipts R` | Remove the loops a binding acknowledged. Never rewrites the source handoff. |
| `file ... --handoff H --filing F` | Apply explicit filing outcomes to remaining loops and unrecorded session items; return a handoff payload with a filing report. Executes no binding. |
| `wrap-check ... --written-handoff H [--record-at T] [--unattended]` | Fail, with the reason, when the handoff is invalid, a bound item is still carried, a read/write failed, or `record` is bound and its latest write is older than the session's last change. |
| `report ... --results R --handoff H [--summary F \| --no-summary WHY] [--unattended]` | Require a valid written handoff and check its filing outcomes and the run's step results; the report starts with the session summary. |
| `wrap-cadence` | Read a hook payload on stdin and print `none`, `checkpoint`, `unattended-checklist`, or `checklist`. |
| `actor-guard`, `is-completion-command` | Hook helpers. The first prints a deny decision; the second exits 0 when the command completes an unattended slate. |

**The spine** has five steps in this order: `record`, `knowledge`, `lessons`, `persist`,
`handoff`. The first four are slots. `lessons` is bound to `/improve-harness`, consuming
`lesson` items. Unbound slots are carried: the items they would consume stay in the handoff
until the filing pass. Missing destinations warn and retain their items;
bound write failures fail wrap. `handoff` is not a slot and is the last spine step; only a profile step
`own-worktree` may follow it.

**A profile** is JSON, or Markdown with one fenced block tagged `checklist-profile`:

```json
{
  "name": "example",
  "record_read": {"command": "/read-work"},
  "ask": {"command": "/ask-step"},
  "bindings": {"record": {"command": "/record-step", "consumes": ["progress", "decision"]}},
  "steps": [{"id": "tidy", "after": "persist", "instructions": "..."}]
}
```

A binding names a `command` and the item types it `consumes`. A user slot may
explicitly bind to JSON `null` to leave it unbound, including `lessons`, which
otherwise defaults to `/improve-harness`. This keeps the spine step and carries
its unsaved items; it does not remove or skip the step. A step has a unique `id`, an
`after` anchor (`before-spine`, `record`, `knowledge`, `lessons`, or `persist`; `handoff`
only for the step `own-worktree`, which must use it), and
`instructions`, or a `section` naming a level-two heading in the same Markdown file. A user
profile applies to every session; a repository profile only adds steps. A profile that
removes, skips, or replaces a spine step, or adds any step but `own-worktree` after `handoff`, is rejected with a
message naming the step. User profile: `$CHECKLIST_USER_PROFILE`, else
`${XDG_CONFIG_HOME:-~/.config}/checklist/profile.md`.

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
requires `priority` and `priority_reason`. R4 routes pending slot items through
ask with `destination: "ask"`. Every ask requires non-empty `choices`.

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

Nine skills, each a directory with a `SKILL.md`. An adapter installs them where its tool
looks for skills. Each resolves its scripts from its own real directory, never from a
tool-specific home directory.

| Skill | Role |
|---|---|
| `setup` | Create or extend the user profile and write and validate the user-owned record-read skill, with the user present. |
| `checkpoint` | Checkpoint the current session. `scripts/checkpoint.sh` is the entry point the checklist also calls. |
| `pickup` | Resume after a cold start. Its engine is `scripts/pickup.py`. |
| `checklist` | Wrap through the spine plus profile steps. |
| `handoff-prompt` | A copy-pasteable prompt that hands a slice of work to another session. |
| `sweep` | Sweep report and configured filing for abandoned sessions; see [sweep contract](docs/sweep.md). |
| `wip` | In-flight work, blockers, and pending approvals for the current session. |
| `improve-harness` | Route a lesson to the user's rules, skills, agent definitions, or memory. |
| `slim-harness` | Review one instruction source with the user, resolve conflicts, and leave edits uncommitted. |

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
runtime copy, the nine skill links, six continuity hooks and the optional actor
guard. The installer owns only the registrations and links recorded in
`continuity-install.json`; other hooks and configuration survive. Its seven
handlers must match `hooks/list` with `trustStatus: trusted`, or it restores the
previous install. `--uninstall` removes the adapter, retaining shared state.

`scripts/codex-hook.py OPERATION` reads one captured-shape Codex payload on stdin,
normalizes string tool responses and calls the shared engines through commands.
Advisory errors exit zero. `CONTINUITY_HARNESS=codex` selects the Codex transcript
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
writes remain with the `record` slot. The package supplies no record service.

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
The package never executes record, record-read, slot or ask bindings. Skill
commands need no executable adapter or JSON stdin/stdout protocol.
`--user-profile` overrides `CHECKLIST_USER_PROFILE`, then
`$XDG_CONFIG_HOME/checklist/profile.md` (default `~/.config/checklist/profile.md`).
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
Identity consists of the producing session, production time and text, never
position. A successor keeps the original identity. Per-operation fields are:

| Operation | Agent uses | Additional fields |
|---|---|---|
| `create_ticket` | record binding | `priority`, `priority_reason` |
| `comment` | record binding | destination ticket; inherits its priority |
| `edit_document` | record binding | destination document |
| `file_slot` | named slot binding | `slot`: `lessons` or `knowledge` |
| `ask` | ask binding, or direct presentation for interactive open sessions | `ticket` (possibly null), `choices`; open sessions also carry `activity_at` |

R1/R2 reads use the profile's `record_read`; the agent searches open tickets
through the record binding before choosing R5. One match becomes R2 and its
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

A missing result is `uncertain`. Missing or malformed acknowledgements and
lost replies must never be reported as failed. The engine flushes each result
into the report before post-filing work. Failed and uncertain items keep their
handoffs. Results cannot overwrite already recorded outcomes. A later run
resolves uncertain writes through identity lookup. `already_written` does not
count as new this run and does not belong to this run's undo journal.

If a slot leaves work pending without writing, return `failed` with `pending:
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

Record and ask bindings store the unchanged item identity with every write,
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
cannot be undone. Asks and their activity history remain delivered. Optional
retention remains a separate operation, off by default; see
[usage](docs/sweep.md#undo-and-retention).
