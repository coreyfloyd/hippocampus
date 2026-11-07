# hippocampus

A coding session that ends, compacts, or runs out of context can lose its work:
what changed, where the decisions went, and what still needs attention.
hippocampus keeps the **record** primary and writes a thin **handoff** pointing
back to it. **Checkpoint** writes that handoff while work is still in progress;
**wrap** finishes the session through a checklist; **pickup** helps the next
session find its way back, in Claude Code or Codex.

![Mid-task, checkpoint writes a handoff; a finished task wraps through checklist and writes one. Pickup in Claude Code or Codex reads the handoff and follows it back to your record.](images/session-lifecycle.svg)

The record is your durable home for tickets, project status, documents, and
their history. The package does not provide that home. A handoff carries pointers,
open loops, and the session's uncommitted files; it does not replace the record.
Both tools use the same engines and shared storage. With nothing configured,
handoffs live in `~/.local/state/hippocampus/handoffs/`, outside either tool's
own data area, and survive adapter removal.

## Skills

Both installers register **27 skills**. Claude Code uses plugin-namespaced
commands; in Codex, invoke the skill by its name, for example `Use checkpoint`.

| Skill name in Codex | Claude Code command | Role |
|---|---|---|
| `hippocampus-set-up` | `/hippocampus:hippocampus-set-up` | Create or extend the user profile and write and validate a user-owned record-read skill, with the user present. |
| `checkpoint` | `/hippocampus:checkpoint` | Write and lint the current interactive session's handoff without finishing its work. |
| `pickup` | `/hippocampus:pickup` | List handoffs after a cold start, select one, and check it against the record. |
| `checklist` | `/hippocampus:checklist` | Wrap the session through the spine and profile steps, ending with a validated handoff. |
| `record` | `/hippocampus:record` | File session items through per-kind record writes, mid-session or during wrap. |
| `handoff-prompt` | `/hippocampus:handoff-prompt` | Produce a portable prompt for deliberately transferring a slice of work to another session. |
| `sweep` | `/hippocampus:sweep` | Report abandoned sessions; file and archive them when act mode is configured. |
| `wip` | `/hippocampus:wip` | Report current work, blockers, and pending approvals from verified state. |
| `improve-harness` | `/hippocampus:improve-harness` | Route grounded lessons to their owning rules, skills, agent definitions, or memory. |
| `slim-harness` | `/hippocampus:slim-harness` | Review one instruction source with the user, resolve conflicts, and leave source edits uncommitted. |
| `slim-unattended` | `/hippocampus:slim-unattended` | Slim recorded over-limit files without the user, leaving each result on a branch with an ask. |
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

Your user profile names optional `record_writes` commands for tickets, projects,
documents, and scheduled jobs. The package record step applies the filing rules,
looks up each unchanged item identity before writing, and requires a matching
receipt to save it. Run `record` on its own mid-session or through checklist.
Commitments follow these same filing rules; timed or recurring commitments use
the scheduled-job write when bound, otherwise tickets. Profiles bind `persist`,
the only **slot**, and can add steps without removing the spine.
Knowledge and lessons always run the package’s knowledge-capture and improve-harness. Before writing the handoff, apply the
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

### Let a wrap apply its lessons and knowledge

Set `"auto_apply_lessons": true` in the hippocampus configuration (off by default).
A wrap then no longer shows the lesson table and waits, attended or unattended:

- Each lesson it recommends is written to its source as one commit of its own, holding only
  that lesson's lines, so reverting the commit removes it. A target outside git, or one its
  repository does not track, is written without a commit. A rule you dictated is applied whatever its recommendation.
- A lesson recommended "skip" is dropped and listed; it is not carried or asked about again.
- A lesson for an always-loaded rules file is in effect before anyone reviews it. It also
  raises an ask naming the target, text, evidence and commit, and saying how to undo it.
  The ask has no choices.
- The persist step pushes the commits with the wrap's others, and when the remote moved
  brings in its commits and pushes once more. A repository that refuses a direct push gets
  the wrap's lessons for that checkout on one lesson branch, one commit each, with a pull
  request opened by the routing file's `lesson-pull-request-command`, which you set up to
  merge through the repository's checks. The local commit stays on your branch with a
  delivered mark, so a later wrap in that checkout does not count it as unpushed, before or
  after the request merges. With no such command the lesson is `committed, not pushed`.
  With persist unbound nothing is pushed.
- The report lists each applied lesson with its target, change and commit, each dropped
  lesson with its reason, and each failure with its error. A failed lesson stays carried.
  A lesson `committed, not pushed` counts as not saved.
- A file over its size limit, or named in a duplicate rule, is not put in front of you.
  The wrap keeps it as an over-limit record, by repository and path inside it, for a later
  unattended slim, and reports it in one line. Several sessions' findings for one file are
  one record, a measurement replaces only what it measured (this tool's limits, and a
  duplicate rule only when the wrap loaded both files), and a file with nothing left
  loses its record. Records outlive the session whether it wraps or is abandoned. A file
  outside git, one git does not track, or one in a repository without a hosted remote, is
  reported with the slim command, as before, and never recorded.

A routing file line `lesson-policy: propose` turns lesson applying off, over-limit records included, and the report says so.
`lesson-pull-requests:` with `- owner/name` list lines sends a repository's lessons through a
pull request every time. The sweep and the attended slim review are unchanged.

### Let over-limit files slim themselves

With the auto-apply setting on, `slim-unattended` works through the over-limit records it is
given, from one machine or several, and treats records of one file as one. Name each
repository's checkout in the configuration, so the step can find its remote and its produced
surfaces: `"slim_checkouts": {"owner/name": "~/code/name"}`. A repository not named waits and
is reported, as does a file whose duplicate rule lives in a repository not named. The routing
file's `lesson-policy: propose` stops this step too.

- One run analyzes at most three files, largest overage first, one after another. The rest
  wait for the next run.
- Each file gets the whole attended review, in the same order, but the agent makes the edits
  itself: it cuts inside the file, removes a rule duplicated in another file (choosing the
  owner) and resolves contradicting rules (choosing the winner). Edits may reach other files.
- The result is one branch per affected repository, built from its hosted default branch in
  a temporary clone. Your checkout is not changed. No commit holds both a lesson and a slim.
- One ask per slimmed file lists each contradiction and its winner, each duplicate and its
  owner, every rule removed or rewritten, sizes before and after against each limit, and the
  branches. It offers no choices and has no deadline. Your automation adds any links and merge time.
- A file still over its limit gets the best result, and the ask says what is left and why.
- A generated surface the step cannot verify means no branch, and an ordinary ask with the reason.
- A file a waiting branch changed is left alone and listed as deferred to a later run, so two
  slims never change one file on two branches, however a path is spelled. A file with a
  waiting branch is skipped; one left alone because of an earlier run's branch gets one ask
  saying so. A slim interrupted while pushing is settled from its remotes at the next run.
- Closing a pull request without merging rejects the slim. Have your automation run
  `scripts/lib/slim.py decide --repository owner/name --branch <branch> --decision rejected`
  (or `merged`); a branch deleted from its remote is settled at the next run, as merged only
  when its change is on the default branch. A rejected file is reported as "over limit, slim
  rejected" and skipped until a session measures it larger than it was at rejection or records
  a new duplicate rule naming it.
- A file that produces no branch in two runs in a row is stalled: its ask says why, and later
  runs report it as "over limit, slim stalled" and skip it. It returns when measured larger,
  on a new duplicate rule, or after `scripts/lib/slim.py retry --repository owner/name --path <file>`.

The package never opens or merges the pull request, and ships no scheduler. How much review a
change gets follows its level:

| Level | What happens | Used for |
|---|---|---|
| Low | Committed and pushed; listed in the report. No ask. | A lesson for a narrow surface; a wiki capture |
| Medium | Committed and pushed; an ask reports it for review afterwards. | A lesson for an always-loaded rules file |
| High | A branch for a pull request that your automation may merge after a period; an ask says how to stop it. | A whole-file slim |
| Critical | A pull request that is never merged automatically; an ask. | None yet. A fact about you stays an ordinary ask. |

To schedule the sweep followed by the slim step, run both from your own scheduler, with your
own agent driver. They are separate runs:

```cron
0 3 * * * /absolute/path/to/agent-driver 'Use the sweep skill with scope all unattended'
30 3 * * * /absolute/path/to/agent-driver 'Use the slim-unattended skill'
```

The same setting lets a wrap capture knowledge without asking, attended or unattended:

- A capture recommended for the wiki is compiled, and one retained as a source under `raw/` or
  an output under `output/` is written, both inside the knowledge root. The report lists the
  articles and files created or updated.
- A fact about you is never saved without you. It becomes an ordinary ask with the proposed
  text, where it would go and where it came from, with no default; it stays carried until you
  answer.
- A capture outside the knowledge root, an action for someone else, a discard and a document
  update keep their approval. Meeting capture and the research workflows are unchanged.

### Route a lesson, then slim its source

During a wrap you identify a rule that caused a concrete mistake.
`improve-harness` finds its narrowest owning source and proposes the grounded
change. Its independent passes flag instruction files over the running tool's
limit and exact or near-duplicate rules across loaded files. Duplicate rows name
both files and line ranges; the lexical threshold is documented in
[the matching reference](../skills/slim-harness/references/duplicates.md). Both passes
only report findings, including in unattended runs. You choose one source for
`slim-harness`, which reads the source
and neighboring instructions, asks about conflicts and produced surfaces,
then applies the agreed edits. It reports numbered changes for rejection and
leaves them uncommitted. It does not slim every flagged file; with the auto-apply setting off,
unattended lessons default to `lesson` items for sessions that resume the handoff.
A routing file can override this with a durable proposal sink; headless runners
without one return full proposals to their parent or report a persistence blocker.
The [routing contract](../skills/improve-harness/SKILL.md#memory-policy) accepts
`memory-policy: native` (default, no placement changes) or `promote` (propose
moving session memories to configured destinations after approval). Codex skips memory review because it
has no comparable agent-written store; other routing still applies.

The [sweep command](sweep.md) reports abandoned sessions across a directory
and its sibling worktrees, or the whole machine. It defaults to watch-only mode
and ships no scheduler.

## Hooks

The plugin registers **6 hippocampus hooks**. These act on interactive sessions;
headless sessions and subagents do not receive the hippocampus prompts.

| Adapter | When it fires | What you see |
|---|---|---|
| `scripts/post-compact-restore.sh` | Session start, including after compaction | At startup, a count of repository handoffs; after compaction, this session's handoff and a reminder to revalidate it. |
| `scripts/pre-compact.sh` | Before compaction | A checkpoint written directly from retained ledger facts and git state, preserving continuation; the raw hook input is also backed up. |
| `scripts/context-guard.sh` | Prompt submission | A context warning at 50% or above when usable usage data is available, with instructions to reconcile the record and checkpoint. |
| `hooks/handoff-ledger.sh` | After every tool call | Usually nothing: the ledger records every tool call's working-directory checkout, edit-tool (Write, Edit) file paths, and existing commit ownership for checkpoint and the stop check. A Read of a file elsewhere adds no checkout. Shell-driven file edits need explicit ledger registration. |
| `hooks/handoff-staleness-guard.sh` | Session stop | If no handoff exists, a skeleton is written without blocking. An existing handoff made stale by this session's own work prompts an update and blocks that stop. |
| `hooks/checklist-nudge.sh` | After a shell tool call signaling commit, push, or passing tests | A once-per-session checklist reminder when that wraps a unit of work; configured unattended work uses checkpoint until the whole slate finishes. |

Codex normalizes its hook payloads before calling the same engines and registers
an additional actor guard before shell calls. The guard refuses checklist and
checkpoint writers from headless sessions and subagents. The Claude Code plugin
registers the six hippocampus hooks without that additional `PreToolUse` guard.
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

The defaults below are shared by both tools ([storage contract](../INTERFACE.md#1-storage)
and [configuration contract](../INTERFACE.md#2-configuration)). Each comment names its
contents and the setting that changes its location. The ledger follows the parent
of the resolved handoff directory unless its own override is set.

```text
~/
├── .local/state/hippocampus/
│   ├── handoffs/                       # handoff JSON; HANDOFF_STATE_DIR, else handoff_dir
│   ├── session-touched-paths.<id>.jsonl # per-session ledger; HANDOFF_LEDGER_DIR
│   ├── timed-checkpoints/              # deadlines, job IDs, transcript locations, queue receipts
│   ├── compact-state/                  # raw pre-compaction inputs; HANDOFF_COMPACT_STATE_DIR
│   └── checklist/                      # unattended-wrap markers; CHECKLIST_STATE_DIR, else checklist_state_dir
├── .config/hippocampus/config.json      # shared configuration; HIPPOCAMPUS_CONFIG, else XDG_CONFIG_HOME/hippocampus/config.json
├── .config/hippocampus/checklist-profile.md        # user profile; CHECKLIST_USER_PROFILE, else XDG_CONFIG_HOME/hippocampus/checklist-profile.md
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
contracts are [handoff commands and continuation input](../INTERFACE.md#3-handoff-engine-scriptslibhandoffpy)
and [checklist commands and profiles](../INTERFACE.md#6-checklist-engine-scriptslibchecklistpy).
[Examples and provenance](examples/PROVENANCE.md) distinguish captured outputs
from validated inputs. Commands below are relative to the package root.

### Handoffs

Location: `<readable-subject>-<12-hex-subject-hash>-<session-id>.json`
directly in the resolved handoff directory. `python3 scripts/lib/handoff.py checkpoint`
(wrapped by the checkpoint skill, also called by wrap) writes schema version 2;
the stop hook can write a skeleton when none exists. Pickup, the restore hook,
and checklist `plan`, `settle`, and `wrap-check` read it next.
[Captured handoff](examples/handoff.json).

```text
handoff JSON
├── schema_version                     # 2 for current checkpoint output
├── written_at                         # UTC checkpoint time
├── trigger                            # checkpoint, wrap, manual, or stop
├── skeleton                           # true only for automatic stop handoffs
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
│   ├── session_summary                # authored work since the previous entry
│   ├── session_history[]              # append-only dated history entries
│   │   └── session_id, produced_at, summary # producer, UTC time, one-line context
│   ├── close_outcomes[]               # milestone/epic observations from ticket closes
│   ├── touched_tickets[]              # references read, changed, or closed in the chain
│   ├── resumed_chain[]                # selected handoff, producing session, resume time
│   │   └── handoff, session_id, resumed_at, written_at, skeleton
│   └── open_loops[]                   # unconsumed items, with original provenance
├── uncommitted_files[]                # absolute changed paths owned by this session in the ledger
├── spawned_processes[]                # processes to reconcile before adoption or teardown
│   └── pid, started_at                # process identity; a PID alone can name a different process
└── suggested_skills[]                 # optional continuation suggestions supplied by the session
```

`session_items[]` is checkpoint **input**, not a stored top-level field. Every
item has `type`, `context` (at most 600 characters except asks and lessons), `disposition` (what to do
next), `session_id` (producer), and `produced_at` (ISO timestamp with timezone).
Asks and lessons keep complete text and choices at any length through checkpoint,
compaction, pickup, and wrap. A lesson proposal includes its target file and section,
proposed text or diff, and evidence. All seven types carry those fields:

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
items move into `resume.open_loops`. Checkpoint retains each well-formed item other
than an artifact in the session ledger, keyed by `session_id`, `produced_at`, `type`
and `context`, and every later checkpoint, pre-compaction write, stop skeleton and
wrap restores it, once, without the agent supplying it again. The wrap settles an
item when it files or drops it or a native step returns its receipt; a later input
copy with `recorded: true` settles it too. A settled item is not restored. Another
session's items enter only through pickup. The stale-handoff guard and the
context-usage warning both ask for new lessons, decisions and knowledge in
`session_items`. Pending artifacts are supplied from the
ledger, preserving their producer and time. Extra session-supplied fields are
preserved rather than constituting a closed schema.

A handoff holds continuation context rather than live ticket lists, project
status, runtime posture, or monitor doctrine. At wrap it also stores the
agent-authored session summary described below, alongside its history entries.

### Ledger (one file per session)

Location: `session-touched-paths.<URL-encoded-session-id>.jsonl` in the resolved
ledger directory. The tool hook writes observations and file entries;
`python3 scripts/lib/handoff.py ledger-file` registers shell-driven edits,
`ledger-artifact` registers published artifacts, and checklist `plan` appends its
start marker. `ledger-ticket` registers ticket reads, changes, and closes; the
ticket record write adds close outcomes as it reports them. Every checkpoint and wrap appends its dated history entry;
automatic stop handoffs read earlier entries without adding one. Checkpoint and
the stop and wrap checks read the ledger next. Pickup immediately copies a
selected handoff's history entries, close outcomes, touched tickets, unsettled
retained session items, and resumed-chain records into the successor ledger,
together with its snapshot.
Later commands never reopen the resumed handoff file. Wrap fails and names each
history entry or close outcome missing from the final handoff.
[Captured ledger](examples/ledger.jsonl).

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
├── history entry
│   └── kind, entry
│       # kind=history_entry; entry holds session_id, produced_at, summary
├── touched ticket
│   └── kind, ticket, ts
│       # kind=touched_ticket; stable ticket reference; UTC observation time
├── close outcome
│   └── kind, outcome
│       # kind=close_outcome; milestone/epic title, state, done, total,
│       # triggering_ticket, produced_at; retained through compaction
├── retained session item
│   └── kind, identity, items[]
│       # kind=session_item; identity=[session_id, produced_at, type, context];
│       # items holds every distinct complete copy of that identity from the
│       # latest write that supplied it
├── settled session item
│   └── kind, identity
│       # kind=session_item_settled; [session_id, produced_at, type, context]
│       # of an item the wrap filed or dropped; never restored again
├── resumed-chain record
│   └── kind, record
│       # kind=resumed_chain; selected handoff, producing session, resume time,
│       # original write time and skeleton marker
├── resumed handoff snapshot
│   └── kind, handoff, data
│       # kind=resumed_handoff; canonical source path and complete selected data
├── start marker
│   └── kind, session_id, ts
│       # kind=checklist-start; current session; UTC plan start
├── checked checkout (tool cwd or checklist addition)
│   └── kind, checkout, session_id, ts
│       # kind=repository; checkout path; current session; UTC observation
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
profiles and the current session's ledger. After pickup it routes the saved
handoff snapshot's items; optional `--handoff` must match the recorded source
path but does not read that file. The returned `handoff` payload names the
current session and carries its ledger facts; use it for later filing and
settling. A brief or pasted prompt without pickup starts its own chain. The
checklist skill reads and executes the plan; the engine does not run bindings.
[Captured plan](examples/plan.json).

```text
plan JSON
├── profiles[]                         # supplied profile paths in composition order
├── unattended                         # whether the caller passed --unattended
├── when_answer_needed                 # only unattended: continue, then file user decisions as asks
├── ask                                # user command for asks, or null; never a slot
├── rerun_all_steps                    # true; no pending results reused from an earlier run
├── record_read                        # user command for reading the record, or null
├── handoff                            # current session payload from its snapshot and ledger
└── steps[]                            # execution order, including additions at their anchors
    ├── id, title                      # step identity; spine title or optional added title
    ├── slot                           # only persist
    ├── binding                        # null if unbound, else command, consumes[], optional instructions
    ├── carries[]                      # only unbound slots: item types for the filing pass
    ├── carried_items[]                 # slot/native inputs selected by binding.consumes
    │   └── index, item                # original open-loop index and intact producer's item
    └── after, instructions, profile   # added steps: anchor, work to run, originating profile name
```

The spine is `record` (reconcile the record), `knowledge` (capture knowledge),
`lessons` (fold in lessons), `persist`, then `handoff` (write and validate).
Only persist is a slot; record is a package step calling record writes; knowledge and lessons are native steps
marked `native: true`, running the package’s knowledge-capture and improve-harness.
Knowledge consumes `knowledge` items; lessons consumes `lesson` items.
With no profile, record has no configured record writes and persist is unbound. Unbound destinations retain items with a warning. Profile steps
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

Location: `resume.session_summary` in the final handoff. At wrap, the checklist
agent writes it from every history entry and close outcome in the chain,
including current work since the last entry. Every ticket it names includes a
description of the work. A session with only a skeleton is named with its end
time as having ended without an account of its work; that gap does not fail wrap.
The report starts with the stored close-outcome line, followed by this summary
unedited, even when no record writes are bound. A projects record write receives
the summary, close outcomes, and touched projects for its durable history.

```text
final handoff resume
├── session_summary                   # agent-authored account of the entire chain
├── session_history[]                 # dated entries under their producing sessions
├── close_outcomes[]                  # stored milestone and epic states
└── touched_projects[]                # project references carried through pickup

report command output                 # JSON on stdout, checked by the reporting session
├── outcome_line                      # stored milestone/epic outcomes, or explicit none
├── summary                           # unedited summary from the final handoff
├── report                            # ok, incomplete, or failed
├── pending[]                         # identities of pending steps
├── filing                            # item outcomes, asks by directory, warnings and failures
├── warnings[]                        # unbound destinations and retained item names
├── incomplete[]                      # native steps still awaiting completion, when any
├── errors[]                          # failed writes, reads, inputs or validation, when any
└── asks[]                            # every filed or carried ask in full, lessons first
```

Every attended and unattended report ends with `asks`, including runs with failed
record, persist, or ask writes, failed record reads, or invalid report inputs.
These failures appear in `errors` and on stderr, with `report: "failed"` and a
non-zero exit status. Readable asks still appear when another handoff field is
invalid; an unreadable handoff fails explicitly without inventing missing asks.
Each ask keeps its complete text and choices;
lesson asks include the full target file and section, proposed text, and evidence.
Identical ask payloads appear once. Asks with different linked tickets, choices,
or proposal fields remain separate, even when their producing session, time, and
text match. Every recovered payload must have non-empty text and a non-empty
array of non-blank choices; an invalid payload fails the report without hiding
valid asks.
A native lesson proposal awaiting approval keeps its choices on the carried item
or filing outcome. Native backlog with no user decision stays in the filing
report and incomplete-step details, without appearing as an ask.

An absent or empty summary fails report validation and wrap. Record writes
cannot supply the report's summary or an unavailable-summary fallback.

### Configuration file

Location: `${XDG_CONFIG_HOME:-~/.config}/hippocampus/config.json`, overridden by
`HIPPOCAMPUS_CONFIG`. The user writes it; both engines, pickup, and the surface
detector read it. [Validated configuration input](examples/config.json).
All keys are optional; absence means an empty configuration.

```text
configuration JSON object             # shared settings, not a profile
├── handoff_dir: string               # handoff storage (~ expands)
├── checklist_state_dir: string       # unattended-wrap marker directory
├── checklist_surfaces: string[]      # standing surface-detector candidates
├── checklist_suite_baselines_dir: string # per-repository suite baseline directory
├── harness_enforcement_reference: string # optional slim-harness reference; absolute or ~/ path
├── slim_checkouts: object            # unattended slim: repository (owner/name) to its checkout on this machine
├── timed_checkpoint_minutes: positive integer # whole minutes, at least 1; default 55
├── timed_checkpoint_token_limit: positive integer # below-limit checkpoint, default 200000
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
settings when used. See [the full settings table](../INTERFACE.md#2-configuration).

### Profile file

Location: `${XDG_CONFIG_HOME:-~/.config}/hippocampus/checklist-profile.md`, overridden by
`CHECKLIST_USER_PROFILE`, plus each repository's `.claude/checklist-profile.md`.
The user or repository author writes profiles; the skill resolves them and passes
`--user-profile` and repeatable `--repository-profile` arguments to the engine's
profile loader and composer. [Validated profile input](examples/profile.md).

```text
JSON object, or one checklist-profile JSON fence in Markdown
├── name                              # non-empty profile name
├── record_writes                     # user profile only: optional tickets, projects, documents, scheduled_jobs commands
│   └── <kind>: command                # executable argv array or shell-quoted string; null/omitted is unbound
├── bindings                          # user profile only: bind persist
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

### Timed checkpoint state

Every interactive checkpoint replaces the pending timer for that session. The
shared configuration sets `timed_checkpoint_minutes` (a whole number of minutes,
at least 1; 55 by default) and
`timed_checkpoint_token_limit` (200,000 by default). At the scheduled time the
agent reads transcript usage with `handoff.py timed-checkpoint-check`; below the
limit it checkpoints, at or above it the prompt does nothing, and unknown usage
is reported without guessing.

Claude Code's checkpoint output instructs the agent to delete the previous job,
create a session-only one-shot CronCreate job pinned to the printed minute with
`recurring: false`, and record its job ID. The pinned minute rounds up: it is
always strictly in the future and never earlier than checkpoint time plus the
interval, including when restore runs after the original deadline. Fractions
and non-integer JSON values are refused in both tools. Codex automatically starts a detached
worker that replaces the per-session deadline and calls `codex queue`. The exact
prompt has one source, `scripts/lib/timed-checkpoint-prompt.txt`, rendered by
`handoff.py timed-checkpoint-prompt`. Timer state and delivery receipts live in
`timed-checkpoints/` beside the handoff directory (`HANDOFF_TIMER_DIR` overrides).
Only one worker per session can deliver a pending prompt.

```text
timed-checkpoints/<encoded-session-id>.*
├── context.json                      # transcript_path, harness
├── claude.json                       # job_id returned by CronCreate
├── pending.json                      # session_id, cwd, codex, due_at, prompt
├── receipt.json                      # queued, exit_code/stdout/stderr or error, fired_at
├── schedule.lock                     # serializes replacement and delivery
└── worker.lock                       # one active delivery worker per session
```

The files use the encoded session ID as a prefix (for example,
`<encoded-session-id>.pending.json`); locks contain no session data.

Before compaction, the hook itself writes a checkpoint from ledger history,
touched tickets and projects, and current git state, preserving the agent's last
continuation. It needs no agent turn and has an eight-second budget inside the
ten-second hook timeout. Pickup and post-compaction restore read that handoff;
Claude restore repeats the scheduling instruction for its next timed checkpoint.

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

[`docs/architecture/session/runtime.html`](architecture/session/runtime.html) is the runtime
architecture map: the two tools, hook adapters, skills, handoff and checklist
engines, profiles, and shared storage. Its boxes link to source files and lines
at a pinned commit. [`runtime.architecture.json`](architecture/session/runtime.architecture.json)
is its source. Agents and maintainers should read the relevant map before
structural work, confirm it against the code, and regenerate it with the
[archify skill](https://github.com/tt-a1i/archify) after a change moves a box or
an edge. The map leaves out installer trust internals, transcript parsing,
optional session cycling, and the user's record implementation.

For a guided explanation, open the standalone
[presentation](session-presentation.html), with keyboard and on-screen controls.
The [glossary](glossary.md) defines the vocabulary; [INTERFACE.md](../INTERFACE.md)
is the contract for adapter and profile authors.
[docs/examples/](examples/PROVENANCE.md) holds captured outputs, validated
inputs, and their provenance.

## Installation and configuration

See [INSTALLATION.md](session-installation.md) for prerequisites, checkout and signed
release routes for both tools, shared configuration and profiles, verification,
uninstall, and test commands.

## License

Apache-2.0. See [LICENSE](../LICENSE).

### Saved-line scope

Checklist reads `handoff.py touched-checkouts --session-id <session-id>` and can
add remembered checkouts with repeatable `--add <checkout>` arguments. This same
additive list feeds the saved line: every tool call's working-directory checkout,
every edit-tool file's checkout, and agent-named checkouts. Agent naming is best
effort and cannot remove recorded entries.

Each checkout is checked for uncommitted changes, including deletions, and commits
on current HEAD absent from all remote-tracking branches. With persist bound,
either condition fails wrap; with persist unbound, it warns that changes were
not pushed and passes. An uninspectable checkout is not saved and fails.

When all items are saved and the listed checkouts are pushed, the line reads
`All saved and pushed: <checkout> (<branch>), ...` (`detached HEAD` when detached).
With an empty list it says `All saved and pushed: no checkouts listed`.
Otherwise it names kept items and missing bindings, unpushed checkouts when
persist is unbound, and unsaved items with reasons under `Not saved:`.

The claim covers only the listed checkouts. Shell-only targets the agent did not
name, other local branches, other worktrees, and predecessor-only checkouts are
accepted limits. The saved-state check adds no shell-text parsing, reflog inspection, or session-start
time discovery. Existing hook commit observations and ownership remain unchanged:
`git -C` candidates populate repository-root observations, not checkout fields,
so they do not widen this list. The stop guard still checks owned commits since
the handoff and recorded file edits newer than it.
