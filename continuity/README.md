# continuity

A coding session that ends, compacts, or runs out of context can lose its work:
what changed, where the decisions went, and what still needs attention.
continuity keeps the **record** primary and writes a thin **handoff** pointing
back to it. **Checkpoint** writes that handoff while work is still in progress;
**wrap** finishes the session through a checklist; **pickup** helps the next
session find its way back, in Claude Code or Codex.

![Checkpoint or wrap writes a handoff across the session boundary; pickup in either tool follows it back to the record.](docs/images/session-lifecycle.svg)

The record is your durable home for tickets, project status, documents, and
their history. The package does not provide that home. A handoff carries pointers,
open loops, and the session's uncommitted files; it does not replace the record.
Both tools use the same engines and shared storage. With nothing configured,
handoffs live in `~/.local/state/continuity/handoffs/`, outside either tool's
own data area, and survive adapter removal.

## Skills

Both installers register **nine skills**. Claude Code uses plugin-namespaced
commands; in Codex, invoke the skill by its name, for example `Use checkpoint`.

| Skill name in Codex | Claude Code command | Role |
|---|---|---|
| `setup` | `/continuity:setup` | Create or extend the user profile and write and validate a user-owned record-read skill, with the user present. |
| `checkpoint` | `/continuity:checkpoint` | Write and lint the current interactive session's handoff without finishing its work. |
| `pickup` | `/continuity:pickup` | List handoffs after a cold start, select one, and check it against the record. |
| `checklist` | `/continuity:checklist` | Wrap the session through the spine and profile steps, ending with a validated handoff. |
| `handoff-prompt` | `/continuity:handoff-prompt` | Produce a portable prompt for deliberately transferring a slice of work to another session. |
| `sweep` | `/continuity:sweep` | Report abandoned sessions; file and archive them when act mode is configured. |
| `wip` | `/continuity:wip` | Report current work, blockers, and pending approvals from verified state. |
| `improve-harness` | `/continuity:improve-harness` | Route grounded lessons to their owning rules, skills, agent definitions, or memory. |
| `slim-harness` | `/continuity:slim-harness` | Review one instruction source with the user, resolve conflicts, and leave source edits uncommitted. |

`handoff-prompt` produces a prompt to copy; it does not write the stored handoff.
`wip` reports within-session state; `pickup` handles a cold start.

## How the skills fit together

### Context is getting tight

You are midway through a change when the prompt hook reports that context usage
has reached 50%. Reconcile durable progress into your record, then invoke
`checkpoint`. It writes the next action and every unrecorded session item as an
open loop, with uncommitted files drawn from the ledger. It does not commit,
merge, or push. If the handoff fails lint, checkpoint still writes it and reports
the failure. After compaction the start hook restores the handoff as context;
you check its pointers against the record before continuing.

### Finish a task with a profile bound

A test run passes and the tool hook reminds you to wrap. Invoke `checklist`.
It reads your user profile and the additive profiles for repositories you touched,
then runs the five-step **spine** in order:

1. Reconcile the record (`record`).
2. Capture knowledge (`knowledge`).
3. Fold in lessons (`lessons`).
4. Persist (`persist`).
5. Write and validate the handoff (`handoff`).

Suppose your user profile binds `record` to the command that updates your tickets
and documents. That command consumes its acknowledged progress and decisions;
anything it has not acknowledged goes through the filing rules before wrap. Profiles bind the first
four steps, called **slots**, and can add steps without removing the spine.
Lessons defaults to `improve-harness`. Before writing the handoff, apply the
filing rules: file or drop each remaining item, and send user decisions to the
profile's one `ask` command. An unbound destination warns and retains its item. The checklist engine composes and checks the plan; the skill runs
it. Wrap fails on an invalid handoff, a stale bound record, a failed bound
write, or an item still carried for a bound destination. A profile's
`own-worktree` cleanup can run only after the handoff check succeeds.

### Pick up in the other tool or worktree

You checkpoint in Claude Code, then start Codex in the same directory and invoke
`pickup`. It reads the same handoff directory. Candidates for this subject come
first, followed by **siblings**: handoffs from other worktrees of the same
repository. Each group is newest first. Choose one and read the record it points
to before acting; starting a session does not authorize its old work queue.
If this directory and its siblings have no candidate, pickup falls back to
local session transcripts from either tool. A handoff is keyed by subject and
session together, so separate sessions do not overwrite each other's files.

### Route a lesson, then slim its source

During a wrap you identify a rule that caused a concrete mistake.
`improve-harness` finds its narrowest owning source and proposes the grounded
change. Its independent passes flag instruction files over the running tool's
limit and exact or near-duplicate rules across loaded files. Duplicate rows name
both files and line ranges; the lexical threshold is documented in
[the matching reference](skills/slim-harness/references/duplicates.md). Both passes
only report findings, including in unattended runs. You choose one source for
`slim-harness`, which reads the source
and neighboring instructions, asks about conflicts and produced surfaces,
then applies the agreed edits. It reports numbered changes for rejection and
leaves them uncommitted. It does not automatically slim every flagged file;
unattended lessons default to `lesson` items for sessions that resume the handoff.
A routing file can override this with a durable proposal sink; headless runners
without one return full proposals to their parent or report a persistence blocker.
The [routing contract](skills/improve-harness/SKILL.md#memory-policy) accepts
`memory-policy: native` (default, no placement changes) or `promote` (propose
moving session memories to configured destinations after approval). Codex skips memory review because it
has no comparable agent-written store; other routing still applies.

The [sweep command](docs/sweep.md) reports abandoned sessions across a directory
and its sibling worktrees, or the whole machine. It defaults to watch-only mode
and ships no scheduler.

## Hooks

The plugin registers **6 continuity hooks**. These act on interactive sessions;
headless sessions and subagents do not receive the continuity prompts.

| Adapter | When it fires | What you see |
|---|---|---|
| `scripts/post-compact-restore.sh` | Session start, including after compaction | At startup, a count of repository handoffs; after compaction, this session's handoff and a reminder to revalidate it. |
| `scripts/pre-compact.sh` | Before compaction | A reminder to reconcile the record and checkpoint continuation; the raw hook input is backed up. |
| `scripts/context-guard.sh` | Prompt submission | A context warning at 50% or above when usable usage data is available, with instructions to reconcile the record and checkpoint. |
| `hooks/handoff-ledger.sh` | After a file edit or shell tool call | Usually nothing: the ledger tracks touched files and session-owned commits for checkpoint and the stop check. Shell-driven edits need explicit ledger registration. |
| `hooks/handoff-staleness-guard.sh` | Session stop | If no handoff exists, a skeleton is written without blocking. An existing handoff made stale by this session's own work prompts an update and blocks that stop. |
| `hooks/checklist-nudge.sh` | After a shell tool call signaling commit, push, or passing tests | A once-per-session checklist reminder when that wraps a unit of work; configured unattended work uses checkpoint until the whole slate finishes. |

Codex normalizes its hook payloads before calling the same engines and registers
an additional actor guard before shell calls. The guard refuses checklist and
checkpoint writers from headless sessions and subagents. The Claude Code plugin
registers the six continuity hooks without that additional `PreToolUse` guard.
Advisory hook errors exit zero; a valid stop decision can still request a block.
The hooks do not automatically run the five-step wrap.

## Example requests

These natural-language requests work in both tools:

```text
Use checkpoint to write a handoff for this session now.
Use checklist to wrap this task with my profiles.
Use pickup to list what I can resume here, including sibling worktrees.
Use wip to report current work, blockers, and pending approvals.
Use handoff-prompt to prepare a prompt for another session to review this change.
Use improve-harness to route the lesson from the mistake we just corrected.
Use slim-harness to review this instruction file with me.
```

## Where things live

The defaults below are shared by both tools ([storage contract](INTERFACE.md#1-storage)
and [configuration contract](INTERFACE.md#2-configuration)). Each comment names its
contents and the setting that changes its location. The ledger follows the parent
of the resolved handoff directory unless its own override is set.

```text
~/
├── .local/state/continuity/
│   ├── handoffs/                       # handoff JSON; HANDOFF_STATE_DIR, else handoff_dir
│   ├── session-touched-paths.<id>.jsonl # per-session ledger; HANDOFF_LEDGER_DIR
│   ├── compact-state/                  # raw pre-compaction inputs; HANDOFF_COMPACT_STATE_DIR
│   └── checklist/                      # unattended-wrap markers; CHECKLIST_STATE_DIR, else checklist_state_dir
├── .config/continuity/config.json      # shared configuration; CONTINUITY_CONFIG, else XDG_CONFIG_HOME/continuity/config.json
├── .config/checklist/profile.md        # user profile; CHECKLIST_USER_PROFILE, else XDG_CONFIG_HOME/checklist/profile.md
└── <repository>/.claude/checklist-profile.md # additive repository profile; explicit --repository-profile arguments
```

`XDG_CONFIG_HOME` defaults to `~/.config`. These shared state locations and the
user configuration and profile are outside either tool's own data area. The
repository profile is a user-maintained file in that repository. Uninstall removes
the adapter's registrations and installed files; it leaves shared handoffs,
ledgers, backups, checklist state, configuration, and user-maintained profiles in
place. Removing a tool does not remove the record, which your bindings maintain.

## What the package writes

These outlines describe outputs and the inputs they depend on. The normative
contracts are [handoff commands and continuation input](INTERFACE.md#3-handoff-engine-scriptslibhandoffpy)
and [checklist commands and profiles](INTERFACE.md#6-checklist-engine-scriptslibchecklistpy).
[Examples and provenance](docs/examples/PROVENANCE.md) distinguish captured outputs
from validated inputs. Commands below are relative to the package root.

### Handoffs

Location: `<readable-subject>-<12-hex-subject-hash>-<session-id>.json`
directly in the resolved handoff directory. `python3 scripts/lib/handoff.py checkpoint`
(wrapped by the checkpoint skill, also called by wrap) writes schema version 2;
the stop hook can write a skeleton when none exists. Pickup, the restore hook,
and checklist `plan`, `settle`, and `wrap-check` read it next.
[Captured handoff](docs/examples/handoff.json).

```text
handoff JSON
├── schema_version                     # 2 for current checkpoint output
├── written_at                         # UTC checkpoint time
├── trigger                            # checkpoint, wrap, or manual
├── subject
│   ├── working_directory              # canonical subject path
│   └── session_id                     # calling interactive session identity
├── git
│   ├── repository_root                # common root shared by sibling worktrees, or empty
│   ├── branch                         # branch at checkpoint, or empty
│   └── head                           # commit at checkpoint, or empty
├── resume
│   ├── headline                       # one-line continuation headline
│   ├── next_action                    # concrete next action
│   ├── session_summary                # current session's one-line continuation context
│   ├── session_history[]              # earlier summaries plus the current producer
│   │   └── session_id, produced_at, summary # producer, UTC time, one-line context
│   └── open_loops[]                   # unconsumed items, with original provenance
├── uncommitted_files[]                # absolute changed paths owned by this session in the ledger
├── spawned_processes[]                # processes to reconcile before adoption or teardown
│   └── pid, started_at                # process identity; a PID alone can name a different process
└── suggested_skills[]                 # optional continuation suggestions supplied by the session
```

`session_items[]` is checkpoint **input**, not a stored top-level field. Every
item has `type`, `context` (at most 600 characters), `disposition` (what to do
next), `session_id` (producer), and `produced_at` (ISO timestamp with timezone).
All seven types carry those fields:

```text
session_items[] / typed resume.open_loops[]
├── progress                           # unrecorded progress or a pointer needing reconciliation
├── commitment                         # commitment still needing reconciliation
├── decision                           # also author (who decided), location (where decided)
├── knowledge                          # knowledge still needing capture
├── lesson                             # lesson text in context, pending routing
├── artifact                           # also location; disposition must be keep or remove
└── open_loop                          # other continuation with an explicit disposition
```

An optional `anchor` with `ticket` or `project` points at the record; legacy
untyped loops need an anchor or disposition. Only an item already saved in the
record may have `recorded: true` in the input; checkpoint omits it. Other input
items move into `resume.open_loops`. Pending artifacts are supplied from the
ledger, preserving their producer and time. Extra session-supplied fields are
preserved rather than constituting a closed schema.

A handoff never holds anything the record holds: no live ticket list, project
status, runtime posture, or monitor doctrine. Its short continuation summaries
are not the bound record's session summary described below.

### Ledger (one file per session)

Location: `session-touched-paths.<URL-encoded-session-id>.jsonl` in the resolved
ledger directory. The tool hook writes observations and file entries;
`python3 scripts/lib/handoff.py ledger-file` registers shell-driven edits,
`ledger-artifact` registers published artifacts, and checklist `plan` appends its
start marker. Checkpoint and the stop and wrap checks read it next.
[Captured ledger](docs/examples/ledger.jsonl).

```text
ledger JSONL                          # one JSON object per line
├── file entry
│   └── kind, path, checkout, session_id, ts
│       # kind=file; absolute changed path, owning checkout, producer, UTC write time
├── artifact entry
│   └── kind, type, location, context, disposition, status,
│       session_id, produced_at, working_directory, ts
│       # kind/type=artifact; published location; context="Published artifact";
│       # keep/remove; pending/recorded/removed; producer; original production time;
│       # canonical subject; UTC append time
├── start marker
│   └── kind, session_id, ts
│       # kind=checklist-start; current session; UTC plan start
└── repository observation (tool hook; no kind field)
    └── repo_root, head, remote_heads[], ts, commit (when attributed)
        # common repository root; observed HEAD; remote tip hashes; UTC observation;
        # optional session-owned commit hash
```

Repeated events append lines. Pending artifact updates preserve production time;
a recorded or removed status stops that artifact being carried. The wrap check
uses the latest start marker to exclude the checklist's own later writes from
record freshness. The captured example contains file, artifact, and marker lines;
repository observations are written by the hook, not those capture commands.

### Checklist plan

Location: JSON on stdout, saved wherever the caller chooses. The command
`python3 scripts/lib/checklist.py plan` composes it from the user and repository
profiles, optionally routing a resumed handoff. The checklist skill reads and
executes it; the engine does not run bindings.
[Captured plan](docs/examples/plan.json).

```text
plan JSON
├── profiles[]                         # supplied profile paths in composition order
├── unattended                         # whether the caller passed --unattended
├── when_answer_needed                 # only unattended: continue, then file user decisions as asks
├── ask                                # user command for asks, or null; never a slot
├── rerun_all_steps                    # true; no pending results reused from an earlier run
├── record_read                        # user command for reading the record, or null
└── steps[]                            # execution order, including additions at their anchors
    ├── id, title                      # step identity; spine title or optional added title
    ├── slot                           # only record, knowledge, lessons, persist
    ├── binding                        # null if unbound, else command, consumes[], optional instructions
    ├── carries[]                      # only unbound slots: item types for the filing pass
    ├── carried_items[]                 # slot inputs selected by binding.consumes
    │   └── index, item                # original open-loop index and intact producer's item
    └── after, instructions, profile   # added steps: anchor, work to run, originating profile name
```

The spine is `record` (reconcile the record), `knowledge` (capture knowledge),
`lessons` (fold in lessons), `persist`, then `handoff` (write and validate).
The first four are slots; `handoff` has only `id` and `title`. With no profile,
record, knowledge, and persist are unbound; lessons binds `/improve-harness`
and consumes `lesson`. Unbound destinations retain items with a warning. Profile steps
may run `before-spine` or after `record`, `knowledge`, `lessons`, or `persist`;
only `own-worktree` may follow `handoff`. Additions retain declaration order
within profile order. Carried open loops go to bindings consuming their types;
untyped and unacknowledged loops also pass through the filing rules. A
finished handoff says `Session finished.`; when destinations are unbound,
its next action names the retained items. Checkpoints may still carry unfiled items.

### Checklist report input

Location: a caller-chosen JSON file passed to checklist `report --results`.
The interactive session writes it as it runs the plan; `report` checks it.
There is no example because this is session-written input, not package output.

```text
results JSON array                    # one result for every planned step, in execution order
└── each result
    ├── id                            # planned step identity
    ├── status                        # run, carried (unbound), pending, or failed
    ├── writes[]                      # paths or locations saved by the step
    └── reason                        # explanation; pending names the answer required
```

Pending steps write nothing. A pending or failed step does not omit later
results; unattended, the handoff step must still report `run`. Pass the written
handoff with `--handoff` so the report includes each filing outcome, its rule,
destination or drop reason, and any warnings or errors. Asks are grouped under
their directory when no ask binding can save them; keep their handoff.

### Session summary

Location: a file named by the bound record, passed to checklist `report --summary`.
The package does **not** compose it. After its ticket step, a bound record
composes it from final ticket outcomes and writes each project's durable history
to its record. The checklist report starts with that summary unedited. There is
no example because the bound record writes it, not the package.

```text
bound record's summary text           # binding-defined format, not a package JSON schema
└── each project's goal, shipped work, follow-up tickets, and decisions

report command output                 # JSON on stdout, checked by the reporting session
├── summary                           # unedited file text, or null
├── summary_unavailable               # reason when no summary was composed
├── report                            # ok after validation
├── pending[]                         # identities of pending steps
├── filing                            # item outcomes, asks by directory, warnings and failures
└── warnings[]                        # unbound destinations and retained item names
```

If none was composed, pass `--no-summary` with the record's reason; an older
binding can be reported as `<command> composed no session summary`. With record
unbound, omit both arguments and the engine supplies that reason. A bound record
with neither summary nor reason fails validation.

### Configuration file

Location: `${XDG_CONFIG_HOME:-~/.config}/continuity/config.json`, overridden by
`CONTINUITY_CONFIG`. The user writes it; both engines, pickup, and the surface
detector read it. [Validated configuration input](docs/examples/config.json).
All keys are optional; absence means an empty configuration.

```text
configuration JSON object             # shared settings, not a profile
├── handoff_dir: string               # handoff storage (~ expands)
├── checklist_state_dir: string       # unattended-wrap marker directory
├── checklist_surfaces: string[]      # standing surface-detector candidates
├── checklist_suite_baselines_dir: string # per-repository suite baseline directory
├── harness_enforcement_reference: string # optional slim-harness reference; absolute or ~/ path
├── prune_days: positive integer      # stale-transcript prune age, default 7; PICKUP_PRUNE_DAYS overrides
├── cycle_sessions: object            # consumer session-name to home-relative directory mapping
└── unattended: object                # optional unattended-mode integration
    ├── state_module                  # Python file providing state_path and read_state
    ├── completion_command            # regex identifying the slate completion command
    └── completed_by[]                # accepted updated_by values after that command
```

The example exercises storage and the optional `harness_enforcement_reference` path.
The reference must be an absolute path or a `~/` path; expand `~` to the current
user’s home directory. Ordinary relative paths are configuration errors, never
resolved against the working directory. Without that key, slim-harness reports “no enforcement reference configured” and
inspects hooks directly; the review continues. `config-get` validates
that input's string key; it is not a full validator for the object-valued
`cycle_sessions` and `unattended` integrations. Their consumers validate those
settings when used. See [the full settings table](INTERFACE.md#2-configuration).

### Profile file

Location: `${XDG_CONFIG_HOME:-~/.config}/checklist/profile.md`, overridden by
`CHECKLIST_USER_PROFILE`, plus each repository's `.claude/checklist-profile.md`.
The user or repository author writes profiles; the skill resolves them and passes
`--user-profile` and repeatable `--repository-profile` arguments to the engine's
profile loader and composer. [Validated profile input](docs/examples/profile.md).

```text
JSON object, or one checklist-profile JSON fence in Markdown
├── name                              # non-empty profile name
├── bindings                          # user profile only: bind one or more of the four slots
│   └── <slot>: command, consumes[], instructions (optional)
│       # command to run; accepted session-item types; execution guidance
└── steps[]                           # additive steps, never spine removal or replacement
    └── id, after, instructions, title (optional)
        # unique identity, allowed anchor, execution guidance, display title

Markdown section references           # available on a binding or added step
└── section                           # level-two heading whose text becomes instructions
```

The loader replaces `section` with that heading's text. Repository profiles add
steps only; they cannot replace bindings. A binding can consume any of the seven
session-item types. Added steps use the anchors listed in the plan outline;
`own-worktree` must anchor after `handoff`. Existing unfenced repository profiles
are read by the skill through their `Slot:` declarations; the engine loader
requires JSON or a single fence. The example is a loader fixture showing format
and composition, not a recommended cleanup or persistence policy.

### Pre-compaction backups

Location: `pre-compact-<YYYYMMDD_HHMMSS>.json` in the resolved backup
directory. The pre-compaction hook calls `handoff.py pre-compact` to write the raw
hook input; recovery or inspection can read it. It retains the five newest
matching files. These are adapter payloads, not schema-version-2 handoffs.

```text
raw hook input                        # adapter-specific JSON, preserved as supplied
└── session_id, cwd, ...               # calling identity, subject, other adapter event fields
```

No example is required: these payloads are adapter inputs, outside the three
captured output formats above.

### Checklist state (the unattended-wrap marker)

Location: `checklist/<sanitized-session-id>.unattended-wrap`. Checklist
`wrap-cadence` writes the marker after a successful configured completion command;
`wrap-cadence` and `wrap-check` read it. Passing `wrap-check --unattended` removes it.

```text
marker file                           # existence keeps the cadence unattended-checklist
├── session_id                        # session whose unattended wrap is due
└── completed_at                      # completion state's updated_at value
```

No example is required: this operational marker is not one of the example
formats. Without optional unattended configuration, it is not used.

## Architecture

[`docs/architecture/runtime.html`](docs/architecture/runtime.html) is the runtime
architecture map: the two tools, hook adapters, skills, handoff and checklist
engines, profiles, and shared storage. Its boxes link to source files and lines
at a pinned commit. [`runtime.architecture.json`](docs/architecture/runtime.architecture.json)
is its source. Agents and maintainers should read the relevant map before
structural work, confirm it against the code, and regenerate it with the
[archify skill](https://github.com/tt-a1i/archify) after a change moves a box or
an edge. The map leaves out installer trust internals, transcript parsing,
optional session cycling, and the user's record implementation.

For a guided explanation, open the standalone
[presentation](docs/presentation.html), with keyboard and on-screen controls.
The [glossary](docs/glossary.md) defines the vocabulary; [INTERFACE.md](INTERFACE.md)
is the contract for adapter and profile authors.
[docs/examples/](docs/examples/PROVENANCE.md) holds captured outputs, validated
inputs, and their provenance.

## Installation and configuration

See [INSTALLATION.md](INSTALLATION.md) for prerequisites, checkout and signed
release routes for both tools, shared configuration and profiles, verification,
uninstall, and test commands.

## License

Apache-2.0. See [LICENSE](LICENSE).
