---
name: improve-harness
description: "Fold what a session taught into rules files, skills, agent definitions, or memory, with one placement per lesson. Use at wrap-up, or when the user says \"from now on\", \"remember this\", \"make this a durable rule\", \"always/never do X\", or asks where a rule belongs. Interactive: proposes, then waits. Unattended: carries proposals."
---

# Improve Harness

The **inward-writing** wrap-up pass. The record holds what this session *did*; this skill folds what the session *taught* back into the instructions that will govern the next one. It is also the place to decide where a single durable rule belongs when the user asks for one mid-session.

Rules, skills and agent definitions, and memory are covered in one pass, because the interesting decision is shared: **where does this lesson belong?** Answering that separately per surface means several scans of the same transcript and constant hand-offs.

## Routing: the user's file, or the default

Look for a **routing file**: `$HIPPOCAMPUS_ROUTING` when set, otherwise `hippocampus/routing.md` under `$XDG_CONFIG_HOME` (default `~/.config`). When it exists, read the whole file: it **replaces** the default routing table below, and it may also name where the sources live, where unattended proposals are filed, recording conventions, and extra steps for this procedure. Follow it wherever it differs from this skill. When it does not exist, use the default routing; it needs no configuration.

### Default routing

Make the placement call **once per lesson**, then write to whichever surface won. Prefer the narrowest surface that still loads when the lesson is needed: always-loaded files cost every future session context.

| A lesson is… | It goes to |
|---|---|
| A deterministic "always / whenever / before X" the harness can enforce | A **hook** in the tool's settings. Text is a request; a hook fires |
| Something that matters only while running one skill | **That skill** (its steps or gotchas) |
| Behavior of one agent type | **That agent's definition** |
| A constraint of one repository | **That repository's instruction file**: `AGENTS.md` when present (both tools read it), else `CLAUDE.md` |
| Something every session must obey, in any repository | **The user-level rules file** (`~/.claude/CLAUDE.md` for Claude Code, `~/.codex/AGENTS.md` for Codex; both when it binds both tools). Last resort for rules |
| A cross-session fact the agent needs that is not a rule and has no narrower trigger | **Memory**, when the running tool has an agent-written store; otherwise flag the missing destination |

### Memory policy

The routing file accepts `memory-policy` with values `native` | `promote`;
absent means `native` (including when there is no routing file). Example:

```yaml
memory-policy: native
```

- **`native`**: leave placement to the tool's memory system; propose no memory moves. Index hygiene and handling of verification failures still run.
- **`promote`**: propose moving each in-scope memory with a configured home to that home, then deleting the memory. Keep only facts with no other home. Use the routing table's destinations, not an instruction-versus-fact test: a knowledge destination can take facts too. With default routing, behavior instructions move to rules, skills, agent definitions, or hooks; facts without a home stay in memory.

A routing file can replace the default table with non-rule destinations, for example:

| A lesson is… | It goes to |
|---|---|
| User context or reference knowledge | A note in `knowledge/context/` or `knowledge/wiki/`, relative to the routing file |

These destinations and the policy apply in both tools; a missing memory store
skips only the memory step. Promotion makes knowledge available beyond one tool's
memory; native placement preserves the tool's own choices.

**Recording form.** Write each rule as the rule plus a one-line why with its date and source, and keep inline whatever mechanism is needed to apply it (the exact command or construct). One home per rule: other sites get a one-line pointer if discovery matters, never a second copy. A pointer to the canonical home beats a restatement.

Fixing an *existing* rule edits it where it already lives; placement applies to new lessons, or to proposing a **move** when something is clearly in the wrong place. Flag moves explicitly; never silently relocate.

**A single rule asked for mid-session** ("from now on…", "remember this") gets the same lookup: place it, state the placement (which surface, which trigger) so the user can redirect, and follow the mode rules below.

## Produced surfaces routing contract

The routing file may include a **Produced surfaces** section. Each entry names
one canonical source path and every produced surface's path and regeneration
command. Paths resolve relative to the routing file unless absolute; expand
home/environment references and resolve symlinks before matching a source.
A source with no entry produces no surfaces; an explicit empty list has the same
meaning. Edit these sources without asking about outputs. Example:

```yaml
Produced surfaces:
  rules/shared.md:
    - path: generated/AGENTS.md
      regeneration command: "make instructions"
  skills/local/SKILL.md: []
```

Use the package's existing `scripts/compose_rules.py surfaces --source <path>`
entry point to read this mapping (optional `--routing <file>` overrides discovery).
It returns JSON with canonical `sources` and `surfaces`, including each regeneration
command. If handed a produced path, trace it to its owning source; never edit a generated surface.
The routing block uses the indentation shown above and plain, double-quoted or
single-quoted strings; malformed entries are errors, not declarations of no outputs.

After a source edit, regenerate its listed surfaces with the declared commands,
within the user's authorized scope. For rule targets use
`python3 scripts/compose_rules.py refresh --config <targets.json>`, then
`python3 scripts/compose_rules.py check --config <targets.json>`; check reports
missing or changed target content as drift and writes nothing. Mapping lookup
runs nothing and does not authorize unknown generators against live configuration.

## Over-limit files — independent size pass

During this pass, compare every covered file in context this session with its
running-tool limit. Read `../slim-harness/references/claude.md` in Claude Code or
`../slim-harness/references/codex.md` in Codex for units and scope. In context means
auto-loaded rules/output style, or skills and dispatched agent definitions read
in full. A skill only listed gets description checks only. Check no other-tool
loaded files. The parent resolves and measures each role path the definition
instructs its agent to read; report unresolved paths without a measurement.

Use `../slim-harness/scripts/harness.py measure <manifest.json>`; the manifest
schema is in `../slim-harness/SKILL.md` under Measurement manifest. Include Codex's
actual root-to-session-start project chain, alongside its per-file checks and
separate user file. Words and bytes accompany line limits. A file under or equal
to its limit gets no row. Several exceeded limits on one file share one row.

Present a separate **Over-limit files** block, outside the grounded lesson table:

| File | Measured size | Limit | Action |
|---|---|---|---|
| <loaded source path> | <lines, words, bytes; description characters when relevant> | <unit and threshold> | run /hippocampus:slim-harness on `<file>` |

A combined Codex chain over 32 KiB gets a chain row listing its members and their
sizes even if no individual file exceeds 200 lines; ask the user which single
member to run `/hippocampus:slim-harness` on. Size rows are **exempt** from the grounding rule:
the measurement is their evidence. The user chooses; improve-harness **runs nothing**
on its own. No prior-review log is kept; repeat flags until files are under limit.
Codex listing truncation notices get the budget/largest-descriptions report from
its reference, with no automatic trigger.

In an unattended run, use the configured proposal destination; otherwise emit
each row as a `lesson` item through the AFK delivery path below. Preserve the file,
measurement, limit and suggested command; no conversation incident or proposed
diff is required for this measurement-only row. Do not invoke slim-harness.

With the auto-apply setting on (`plan` returns `auto_apply`, either value), record
instead, attended or unattended; see Over-limit records below.

## Duplicate rules — independent detection pass

In both Claude Code and Codex, run
`../slim-harness/scripts/harness.py duplicates <manifest.json>` with the same
running-session manifest used for measurement. Do not discover extra files or
compare the other tool's loaded set. Read
`../slim-harness/references/duplicates.md` for the deterministic threshold,
exclusions, output schema, and limitations. Report unresolved paths explicitly.

Present `duplicates` as a separate **Duplicate rules** block beside **Over-limit
files**, outside the grounded lesson table. Each `duplicate-rule` row names both
files and inclusive line ranges, the matching text, exact/near classification,
and similarity. Its action is: “rule repeated in A:lines and B:lines; run
/hippocampus:slim-harness on the file that does not own it.” Ownership requires user judgment;
near matches are candidates, not proof that either rule can be removed.

Detection edits nothing and invokes no trimming or generators. Like size rows,
duplicate rows are exempt from conversation grounding: the spans are the evidence.
In unattended runs, carry every row through the configured proposal destination
or the AFK `lesson` delivery path below, retaining row type, both spans, match,
score, and action. No proposed diff is needed; do not invoke slim-harness. With no
matches, report no duplicate rules found in the supplied loaded set. Repeat
findings on future runs until resolved; retain no suppression history.
With the auto-apply setting on, record duplicate rows with the size rows below.

## Over-limit records — auto-apply setting on

Do not present the two blocks, ask the user to run the slim review, carry the rows
as `lesson` items, or slim. Pass both outputs to the checklist module:

```bash
python3 <checklist-module> record-over-limit --user-profile <user-profile> \
  --measure <measure-output.json> --duplicates <duplicates-output.json>
```

Print each `recorded[].line`: one line per file or duplicate rule, kept as an
over-limit record for a later unattended slim. Rows in `reported` (outside git, no
remote, or a Codex chain) get today's blocks with their `action` and `reason`;
they are never recorded or slimmed unattended. Report `unresolved` paths. With the
setting off the module refuses; use the blocks above.

## The one rule that makes this safe: every edit must be grounded

A proposed edit is legitimate only if you can point at the **specific moment in this conversation** that motivates it. The failure mode is generating plausible-sounding improvements traceable to nothing — that is how rules files bloat and skills drift from how they actually behave.

Legitimate motivations:

- **A rule or skill led you wrong** — you followed it as written and the user corrected the outcome.
- **An error hit** — a command failed, a path was stale, a step didn't work as written.
- **A missing step** — you had to figure out something the instructions should have told you.
- **A repeated instruction** — the user stated a preference or convention that nothing records.
- **A stale reference** — a named path, flag, command, or label vocabulary no longer exists.
- **A contradiction** — two rules, or a rule and reality, conflict and this session had to resolve it.
- **A trigger miss** — a skill should have fired (or fired wrongly) for what the user asked.
- **A memory that failed verification** — a recalled or newly written fact that no longer holds.

If you can't cite the moment, don't propose the edit. "This could be clearer" with no incident behind it is not grounds. A rule the user dictates is its own grounding.

## Mode — decide this first

| Mode | Detection | Behavior |
|---|---|---|
| **HITL** | interactive session the user is present in | Proposal table → **wait** → apply approved edits |
| **AFK** | the user left the session to run unattended, or it is a scheduled or pipeline run | Record proposals through the AFK delivery path below; do not apply them (mechanical memory-index hygiene is exempt) |

**The auto-apply setting overrides this table.** With `plan` returning
`auto_apply.lessons: apply`, follow Auto-apply below in either mode. With it off, or
with `auto_apply.lessons: propose`, this table applies.

Unattended runs carry proposals because approval needs a present user; waiting stalls the run, and self-approval defeats the gate. A subagent inherits its parent's mode.

**AFK output — one proposal per placement decision.** By default, emit each as
a `lesson` item for the checklist to carry in the handoff, not one per surface.
Without an override, do not file tickets. Never self-approve or apply proposals.
Include the full proposed text or diff, target file and section, and grounding
evidence, plus the user's complete choices in `choices`. Keep the full proposal
and choices at any length through checkpoint, compaction, pickup, and wrap.
A memory move includes the memory file, target, proposed text,
grounding, and deletion of the original as one proposal.

A routing file's configured durable sink overrides this default: file the full
proposal there, including tickets when explicitly configured, and report its
receipt. This preserves user-owned proposal routing for headless runs too.
Without a configured sink, an unattended interactive session carries `lesson`
items in its handoff. Factory sessions and subagents never write handoffs or run
the checklist: return the full `lesson` items to the parent or caller for durable
retention. With no parent or sink, report the persistence blocker alongside the
full proposals; do not claim they were saved or will reach interactive review.

For carried items, the checklist's native `lessons` step presents them at the next interactive
`/hippocampus:improve-harness` run; retain pending items until approved and applied. This
reaches only sessions that resume the handoff, not unrelated future sessions.

## Auto-apply

The `auto_apply_lessons` setting in the hippocampus configuration is off by default. With
it on, a wrap does not show the lesson table and wait; `apply-lessons` writes the lessons.
The setting decides, not whether the user is present. Over-limit and duplicate
rows are not lessons to apply: record them as in Over-limit records.

A routing file can forbid this with the line `lesson-policy: propose`; it wins, and the
report says lessons were carried because the routing file requires it. The module reads
only that key, so a routing file says it with the key. `lesson-pull-requests:` followed by
`  - owner/name` lines names repositories whose lessons always go through a pull request.
`lesson-pull-request-command: <command>` names the user's command that opens one
(see `INTERFACE.md`); the package opens none itself and never merges.

Run steps 1 to 4 and assess each lesson as in step 5: grounding, impact and the
recommendation are unchanged. Add any new lesson to `session_items` in `<remaining-items>`,
then write one row per lesson. `index` counts `resume.open_loops`, then unrecorded `session_items`:

```json
[{"index": 0, "recommend": "apply", "target": "/absolute/path/to/source", "change": "One-line change",
  "evidence": "The moment in this conversation", "edits": [{"old": "exact text", "new": "replacement"}]},
 {"index": 1, "recommend": "skip", "reason": "Future impact is noise"}]
```

An edit with `old` replaces text that must appear exactly once; an edit without it appends
`new`. Set `dictated: true` on a rule the user dictated: it is applied whatever its
recommendation, so give it the apply fields. Set `always_loaded: true` when the target is
always loaded and the module cannot know it, such as a source of a rules composition.
The module detects user-level rules files, their imports and routing-file sources composed into
`CLAUDE.md` or `AGENTS.md`.

```bash
python3 <checklist-module> apply-lessons --user-profile <user-profile> \
  --repository-profile <repository-profile> --handoff <remaining-items> --lessons <rows>
```

Keep its output as `<remaining-items>`; `lesson_outcomes` says what happened to each row.
Each applied lesson is one commit, `lesson: <change>`, on the branch checked out where the
target's source lives, holding only its own lines even in a file with other changes. A
target outside git is written without a commit. A `skip` is dropped: not carried and never
an ask. A produced path is traced to its source, and a generated copy is never edited;
regenerate each outcome's `surfaces` as in the routing contract. A lesson that cannot be
written or committed is `failed` with its error and stays carried. Applying the same lesson
twice does nothing. The persist step delivers the commits, so step 7 does not apply.

A rerun or resumed lesson marked `applied: true` already holds its commit: give it no
row, and let the checklist deliver its ask.

## Procedure

### 1. Collect grounded candidates across all surfaces

Scan the conversation once for the motivations above. Cover:

**(a) Rules you followed or fought** — the user-level rules file and every repository instruction file (`AGENTS.md`, `CLAUDE.md`) loaded this session.

**(b) Skills used** — invoked by name, loaded as guidance, or whose workflow you followed.

**(c) Skills that should have fired but didn't.** The available-skills list has been in your context all session; check the work you actually did against it. Signals, strongest first: the user pointed you at a skill mid-task ("why didn't you use /foo?") — ground truth; you reinvented a workflow a skill already encodes; a skill's domain matched but its "when to use" phrasing didn't match how the task arose.

When (c) holds and the skill genuinely applied, the fix is almost always a **description / triggering edit** — broaden or sharpen the when-to-use so it fires next time on that phrasing. Stay grounded: flag a skill only when you can point at the work *in this conversation* it was built for. Distinguish **correctly didn't fire** (leave it alone) from **trigger missed** (fix the description). If work recurred and *no* skill exists, that is "extract a new skill", out of scope here.

**(d) Agent definitions dispatched this session.** If a subagent misbehaved because its *definition* was wrong — stale path, missing constraint, an instruction that produced the wrong behavior — same grounded-edit pattern applied to that agent's definition file. An agent never dispatched this session is out of scope.

**(e) Memory.** Use only the running tool's own agent-written memory store
(resolve symlinks first). If none exists or memory is disabled, skip this step
and report why; do not emulate a store or use another tool's. Codex currently
has no comparable agent-written store, so report it skipped. Routing still runs
for the other surfaces.

Review memories **recalled or written this session**; no full-store sweep.
Check their facts, paths, flags, and commands against reality and later decisions.
Under `native`, propose no placement changes; flag verification failures and
propose correction or deletion through the mode's approval path. Under `promote`,
also check each memory against the configured destinations: propose every move
as one HITL table row or AFK `lesson` item with its target text and deletion of
the original. Keep only facts with no other home; never delete before the target
has been written successfully. Accuracy corrections use the same approval path.

In both modes and under either policy, mechanically cross-check any index:
every memory file gets one index line, every line points at an existing file.
Fix orphan and dangling index entries without asking; this index check may list
the store, but does not broaden the memory-content review.

### 2. Place each candidate

Run each through the routing (the routing file, or the default table).

### 3. Locate source files

Skills, agents, and rules files are often symlinked into the tool's home directory from a repository. Resolve before editing, so the change lands where it will be committed:

```bash
readlink -f <path to the installed SKILL.md>
```

A file inside an installed plugin is not yours to edit — flag it instead.

### 4. Draft to the house style

- **Explain the why.** "Do X because Y happens otherwise" is worth ten bare "ALWAYS do X" lines. Heavy all-caps MUSTs are a yellow flag — reframe as reasoning.
- **Keep it lean: pair every addition with a cut.** A long section is a signal to restructure, not to keep appending. Before proposing lines for a file, read the section you are adding to and look for what the new text makes removable: a line it supersedes or duplicates, an incident narrative that compresses to rule plus one-line why, a stale path or flag, a rule another home (a hook, a skill, the ticket) already carries. Propose those cuts in the same row. A row that adds lines and cuts none must say what you checked; leaving a file larger is a cost the row has to justify.
- **Descriptions are the trigger.** For a triggering fix, the frontmatter description is the thing to edit — specific about when to fire *and when not to*.
- **Progressive disclosure.** Large reference material belongs in a `references/` file the SKILL.md points at, not inline.
- **Rules files are aggressively concise** — match that register; they load in every session.
- Tone: written to the future agent, not to this reviewer.

### 5. HITL — present one table, then stop

One table for all surfaces. Grounding gets a candidate INTO the table; impact decides whether it should be applied. Every row carries both:

- **Impact this session** — what it actually cost: turns burned, a wrong action taken, or nothing because you caught it.
- **Impact on future sessions** — how often the moment recurs and what it costs when it does: damage (a wrong or destructive action), a lost cycle, or noise.
- **Strip / compress** — the cuts from step 4 for the same file, and the row's net line change (`+3 −5`).
- **Recommend** — apply / skip, from those two. Skip a grounded edit whose future impact is noise; every line added is context every session pays for. Say which rows you recommend and why the others are not worth their line.

```
| Target | Repo | Tier (placement) | Proposed change | Evidence (this conversation) | Impact this session | Impact on future sessions | Strip / compress | Recommend |
|---|---|---|---|---|---|---|---|---|
| build-sim skill | tools | skill (gotchas) | Note: booting an already-booted simulator exits non-zero but is harmless | We read that message as a build failure | 2 turns lost | Every re-run on a warm simulator; a lost cycle each time | Fold the two older simulator-boot notes into this one; `+1 −2` | apply |
| write-nudge hook | tools | hook | Exclude `merge-base` from the push/merge trigger | Nudge fired after a read-only ancestry check | none, ignored | Advisory noise only | none: config change, no prose; `+0` | skip |
| old-path memory | — | memory → delete | Recorded path no longer exists | `ls` failed on it | 1 turn | Misleads every recall until removed | the whole file; `−1 file` | apply |
```

**"Nothing grounded" is a normal, good outcome.** Still report the independent size and duplicate passes, then say so plainly and stop — "skills used this session all ran cleanly; no rule friction; memory reviewed or skipped as reported." Manufacturing edits to fill the table is the failure mode, not the absence of them.

**Limitation:** self-detecting under-trigger is best-effort. If you never knew a skill existed, you may not realize it at wrap-up either. The retrospective scan catches most of it; the user's mid-task corrections catch the rest.

### 6. Apply

After approval (HITL) — surgical edits only. Don't reflow unrelated content; match each file's existing heading style. Keep any memory index in step with memory files added, changed, or removed.

### 7. Leave commits to the persist step

**Do not commit or push from this skill**, unless the auto-apply setting is on. Edits land as working-tree changes; report which repositories are now dirty so the checklist's `persist` step (or the user) commits them.

## Output format

```
Routing: <routing file path | default>
Surfaces scanned: rules · skills+agents (<list>) · memory (<n> recalled or written)
Memory: <policy; reviewed count | skipped — reason>
Mode: HITL | AFK
Over-limit files: <measurement rows | recorded lines and reported rows (auto-apply) | none>
Duplicate rules: <duplicate-rule rows with both spans, match, score and action | recorded lines and reported rows (auto-apply) | none>

<the table from step 5 with impact, strip/compress, and recommend columns, or "nothing grounded — <one line on what was checked>">
Net: <per file touched, lines added and removed>
Recommend: apply <rows> · skip <rows> — <one line why the skips are not worth their line>

[HITL, after approval]
Applied:
- <target> (<repo>): <one-line change>
Repositories now dirty: <list>

[AFK]
Proposed: <configured sink + receipt | handoff lesson items | parent/caller | persistence blocker>
<full proposals>
Index hygiene: <mechanical fixes | none>
```

## Gotchas

- **Memory placement follows the policy.** `native` leaves it alone; `promote` uses configured destinations, including knowledge folders. Propose the move and deletion together so two copies cannot drift.
- **Symlinked sources.** Editing through a symlink is fine, but resolve it before reasoning about which repository the change commits to; getting this wrong leaves the edit uncommitted in a repository you never look at.
- **Don't route a skill-local lesson into a shared rules file.** A user-level rules file loads in *every* session. A gotcha that only matters inside one skill costs every unrelated session context if it lands there.
