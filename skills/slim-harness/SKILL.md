---
name: slim-harness
description: Review and slim one rules file, skill, agent definition, or output style, and measure whole start-up token budgets. Use /hippocampus:slim-harness on one file manually or from improve-harness over-limit rows. For ordinary reviews, requires the user present and leaves edits uncommitted. Evidence-backed start-up extraction leaves a slim branch with one user ask per removal.
---

# Slim Harness

Review one handed or loaded instruction file. This skill adds source edits and
cross-file conflict checks to Claude Code's `/doctor prompt-audit`, and works in
both tools. Review the target; read the comparison files below for cross-file
checks. Never scan a catalog or independently review unrelated files.
Whole start-up budget overage is also a trigger; measure the explicit loaded set
using the budget workflow below in both tools. Size is one trigger: a user or
scheduled review may request an under-limit file. Ordinary file reviews require
user presence; no schedule is installed.

## Start and measure

1. Decide mode first. For start-up budget extraction use the branch workflow below.
   For an ordinary unattended file review, stop before any edit: “slim-harness
   needs the user present; edited nothing.” Do not self-approve or enqueue a review.
2. Read only the running tool's reference: `references/claude.md` for Claude Code,
   `references/codex.md` for Codex. These define limits and loading scope. A manually
   handed file can be reviewed regardless of size; over-limit does not authorize it.
3. Resolve symlinks to the resolved source. Read the entire target and the files
   loaded beside it: user-level rules, invoked skills, output style when applicable,
   and a dispatched agent's system-prompt/role files. Read only the applicable files,
   not the other tool's loaded set. Role files are every path the definition tells
   the agent to read; the parent resolves and measures them itself. Report paths
   that do not resolve; do not measure them or rely on the child's load report.
4. Measure lines, words, bytes, skill body lines and discovery-field characters.
   Report each size against the reference's unit and limit. For Codex, also check
   the combined loaded project chain, from repository root to session start folder,
   even when its members are individually under 200 lines. Distinguish the user file.
   Use `scripts/harness.py measure <manifest.json>` (schema below). Do not infer a
   loaded set from the filesystem. If text was truncated, read the source in full
   for review but retain the actual session loading scope for the trigger.
5. Read the improve-harness routing file: `$HIPPOCAMPUS_ROUTING`, otherwise
   `hippocampus/routing.md` under `$XDG_CONFIG_HOME` (default `~/.config`).
   From its **Produced surfaces** section, find the resolved source's entry and
   each produced surface path with its regeneration command. A source with
   no entry produces no surfaces; an explicit empty list means the same. Do not
   ask about outputs in either case. Use the package's
   `scripts/compose_rules.py surfaces --source <path>` (optional `--routing <file>`)
   for the canonical mapping; malformed entries are errors.
   If handed a generated surface, trace it to its owning source through that mapping
   or ask the user; never edit a generated surface. Review the source only, never
   each generated copy separately. Every finding names its source file and lines.
6. Establish each surface's applicable limits from its tool reference. Predict or
   render in isolation the content each surface would contain after the source edit
   (including aggregation with other sources), then measure that content. Do not
   pretend that measuring another tool's installed files establishes its loaded set.
   Apply only a change set whose preview keeps every produced surface within its
   own limits. If the generator cannot be safely previewed, ask how to verify its output and
   hold edits requiring that evidence. Name the regeneration step; do not run an
   unknown regeneration command against live configuration without authorization.
   After a source edit, regenerate the listed surfaces within the authorized scope.
   For rule targets run `python3 scripts/compose_rules.py refresh --config <targets.json>`,
   then `python3 scripts/compose_rules.py check --config <targets.json>`; drift is an
   error, and check writes nothing.

## Review in this order

Before Redundancy, build the comparison set from the files loaded beside the
target, the skills and files the target points to, and any files the user names
as normally co-loaded. When following target references, honor explicit tool
conditions: exclude references limited to the inactive tool, including this
skill's alternate-tool reference. Read the applicable sources in full even in a
fresh session where they were not previously loaded. Resolve relative paths from their owning file's
documented base and skill names through the running tool's skill catalog; resolve
symlinks to source. Ask whether the user has additional normally co-loaded files
to include. Report unresolved or unreadable references and the resulting coverage
gap; ask for ambiguous paths rather than guessing. Follow the target's direct
instruction references, not every link or references recursively. Reading a skill
for comparison does not invoke its workflow or execute commands it names.

Keep comparison context separate from the session's original loading scope:
these extra reads do not create over-limit trigger rows or authorize independent
reviews or edits of those files. Use this same preparation in Claude Code and Codex.

Before Redundancy, apply `references/removable-rules.md` to classify every rule and check enforcement and supersession.
For every finding, first try redundancy, unneeded context, and conflicts. Use
extraction and compression only for what those first three leave.

### Redundancy

Find repetitions within the file and across the comparison set, including
canonical homes loaded beside it. Each cross-file finding names both source files
and line ranges, shows the repeated rules, and preserves any distinct boundary.
Ask the user which file should own the rule **before any edit**, with options,
tradeoffs, and a recommendation, as for conflicts. Wait for the ownership decision;
never silently choose a home or remove a duplicate.
When a rule restates a skill's procedure, the skill keeps the procedure and the
rules file keeps at most a pointer: recommend that ownership in the question.
After resolution, state the instruction once where the user agreed it is owned.

### Unneeded context

Preserve intent, goals, audience; a one-line why states the goal or consequence protected.
Move dated incident provenance to the rule’s ticket, keeping at most one repo-qualified link.
Keep always-on only what the model cannot work out: unguessable tools/commands,
deviations from defaults, repeated gotchas, and boundaries. Delete general good
practice, obvious behavior, tool explanations, and facts obtainable with one read
or command the task already needs. Keep material when finding it takes a search or
several steps, knowing where to look first, a convention invisible in code, or most
sessions need it. Put it behind a pointer when only some sessions need it.

A partly needed list of cases becomes the **judgment criterion** behind it rather
than being kept whole or deleted. Name that rewrite in the summary. Replace a long
block of examples with its criterion; retain only exact failing command forms or
other mechanisms the rule cannot state, reduced to that clause.
Flag wording written for older models; explain which assumption is stale rather
than deleting a safety boundary just because it is old. Flag “double-check your
work” and “think hard” for deletion: checking is default behavior and effort is a
setting. For IMPORTANT/MUST/NEVER, default to delete; record **delete, propose a hook, or keep**
with a basis per `references/removable-rules.md`; propose both tools’ hooks for zero-exception rules. Write no hooks or tickets.

### Conflicts

Compare against the same comparison set, not just the target's own lines.
Ask each conflict as a question **before any edit**, showing both source rules,
the incompatibility, options with tradeoffs, and a recommendation. Wait for the
user to resolve all conflicts; never silently choose a winner. A resolution may
require editing the other side: include it as a separately numbered change.

### Extraction

When a section usage report is supplied, read it before extraction and cite its
skill path, section, size, sessions loaded, and sessions with evidence in each
report-supported finding. Read `references/usage.md` for the report schema and
coverage limits; generate it with `scripts/harness.py usage <manifest.json>` when
transcripts and snapshots are supplied. Treat prose-only rules as “no evidence of
use”, never “unused”. Suggest a split from usage evidence only after the configured
number of distinct loaded sessions (default ten). For whole start-up reviews, the branch
workflow below moves sections with zero evidence by default after the configured
session minimum. Other extraction findings
remain evidence for the existing review and user decisions.

Sort remaining instructions into always-on (stays), situational, or tool-specific.
Situational material moves behind a pointer; tool-specific material goes in a file
only that tool's entry points to. Follow the running tool's destination rules.
A pointer is a path in backticks plus when to read it, never an `@` import.
Every situational subfile is pointed to directly from the always-loaded file:
**one level deep**. Every pointed-to file over **100 lines** starts with a table of
contents. Path-scoped rules are exempt from pointers because matching files load
them. For skills, these come from Anthropic's published best-practices page; their
extension to rules files is this **skill’s own rule**, chosen without a
depth experiment. Do not attribute that extension to Anthropic. The published page
wins over skill-creator guidance that permits deeper references or a 300-line TOC.

### Compression

Compress what remains without changing its intent, goals, audience, why, commands,
conventions or boundaries. Do not chase a line count at the cost of judgment.
Check every named path and command with `scripts/dead_references.py`:
`python3 <skill-dir>/scripts/dead_references.py --base <reference-base> --path <named-path> --command <executable>`.
Repeat flags for all named references; resolve each relative path using its owning
file's documented base. Pass executable names, not whole shell commands. It checks
existence without executing them; it does not prove flags or runtime behavior.
Report each missing reference and verify stale wording and contradictions in both
tools. Parameterized/example paths need resolution from the user, not a false
missing-path finding. No missing references means nothing is reported as missing.

## Edit, review and reject

After the questions above are resolved, edit working source files only. The named
file may require a new subfile, the duplicate's other home, or a conflict's other
side; include each in the summary. Never write generated surfaces. Record the
pre-edit exact lines for each numbered change, including unique unchanged context.
Preserve existing uncommitted edits. Do not use a whole-file restore, git checkout,
reset, or stash. This skill **never commits** or pushes; leave persistence to the
checklist or user. With no findings, change nothing, including no review marker.

For replacements, use `scripts/harness.py edit <request.json> <journal.json>`.
The request has `path`, `before`, `after`, and `mode` (`interactive` or `unattended`).
The helper resolves symlinks, rejects ambiguous matches, and journals its own lines.
Include context around deletions/insertions so both before and after are nonempty.
Keep requests and the journal in session-local temporary storage, never in the
instruction file or a history of past reviews. Do not remove them before rejection
review is finished. For a new subfile record its creation separately; delete it on
rejection only if it is still exactly the content you created, otherwise ask.

Show a per-change summary, **not the full diff**: number, source file, what changed,
why, and before/after sizes against all applicable limits, plus regeneration steps.
The user can open the diff in their editor. Ask which numbers to reject; rejection
of change N uses `scripts/harness.py revert <journal.json> N`, by its **own lines only**.
If later edits changed those lines or make the match ambiguous, stop and ask for
reconciliation; never clobber them. Revert overlapping rejected changes in reverse
application order, and reconcile any accepted dependent pointer/extraction changes
with the user so no dangling pointer remains. Remeasure after rejection; a partial
slim is flagged again in the next session until under limit. Report **every repository**
left dirty, including other source homes, and say when none is dirty. Do not commit.

## Measurement manifest

Supply JSON to `scripts/harness.py measure`. `tool` is `claude` or `codex`.
`files` contains objects with `path`, `kind` (`rules`, `user-rules`, `skill`, `agent`,
`role`, or `output-style`), and `loaded` (`auto`, `full`, `listed`, or `other`).
Listed-only skills check descriptions only; `other` is ignored. Agent entries may
include `role_paths`, resolved relative to the definition unless absolute; collect
these from what the definition tells the agent to read. `chain` lists the actual
loaded Codex project files root-to-start-folder; each must also be in `files`.
Only when Codex reports shortened descriptions set `shortened_descriptions: true`
and supply `context_window` if known. The helper reports the listing budget and
largest loaded descriptions (unknown window: 8,000 characters; otherwise 2% of
context window), with no automatic trigger. Output has `measured`, `over_limit`,
`unresolved`, and optional `listing`; the script measures and runs no review.

For cross-file detection without a review, `scripts/harness.py duplicates
<manifest.json>` accepts the same manifest. Read `references/duplicates.md` for
its matching rules and result schema. It reports candidates and unresolved paths;
it edits nothing and grants no permission to trim.


## Whole start-up budget and branch extraction

Use the same helper in Claude Code and Codex. In the measurement manifest set
`directory` to the agent's launch directory and `config` to an explicit hippocampus
configuration JSON path. With no config supplied, built-in defaults apply; the
helper never searches a home directory or knowledge root. Configuration holds:

```json
{"startup_budget": {"default_tokens": 8000, "directories": {"/workspace/project": 6000}, "usage_sessions": 10}}
```

Directory overrides must be absolute or `~/` paths and match the resolved launch
directory exactly; every directory without an override uses the default. Both
configuration objects must be JSON objects; all policy values are positive integers.
Budgets use **estimated tokens**, `ceil(UTF-8 bytes / 4)` per input, the existing
review conversion shared by both tools, not an exact provider tokenizer.
`startup` reports total, budget, overage, and every file's contribution, even when
all individual files fit. Existing per-file limits remain additional checks.
Full files and agent role paths count once by resolved source; a full load replaces
a listing contribution. Listed skills contribute their name, listed path, description
and Claude `when_to_use`. Supply `listing_path` when its displayed path differs from
the snapshot path, or `listing_text` with the exact rendered discovery entry, including
formatting. Otherwise the estimate joins those fields with newlines. Supply
non-file start-up material as `inputs: [{"name": "system prompt", "text": "..."}]`.
Attest the whole start-up, including injected text and listings; do not discover it
by scanning files. Missing files make `startup.complete` false: report the gap,
never describe a partial total as within budget. Comparison reads are excluded.

For an over-budget start-up, use `usage` with the same explicit config and captured
session inputs. Attest a complete consecutive window in oldest-to-newest order with
`session_window_complete: true`; do not set this when captures or sessions are missing.
The report retains session identities, per-section loading and matched markers, and
snapshot hashes. Extraction refuses a report missing that window, its policy minimum,
or consistent observations. It uses the larger of the report and request minimums;
omitting the config cannot weaken the report policy. The default is **ten consecutive
sessions**; set a different minimum in the explicit config supplied to both commands.

Move observable sections with no evidence in the latest required consecutive loaded
sessions behind pointers by default on an isolated `slim/…` branch. An unloaded,
partial, or failed read breaks the count; a recent marker match also breaks it. Older
matches remain in the ask's evidence. Preambles and prose-only sections stay loaded:
without observable markers the detector cannot demonstrate non-use. Zero lexical
evidence is not proof of irrelevance, so every removal still awaits the user.
Resolve generated surfaces to their source and preview their outputs as above;
only source files belong in an extraction request. Do not edit the agent's active
home or replace its loaded path during this proof.

Run `python3 <skill-dir>/scripts/harness.py extract <request.json> <journal.json>`.
The request contains `tool`, `directory` (the isolated slim checkout), optional
`config`, and `usage` (the report object). Capture snapshots from that checkout so
report paths name its sources. The helper refuses a different branch, unresolved
inputs, stale section text, ambiguous matches, and existing destinations. It preflights
every replacement, then writes the recovery journal before publishing changes. An IO
failure rolls back its still-matching writes; an independent edit or rollback failure
is preserved with the recovery journal and reported as an error. It moves
all eligible sections, byte for byte, into directly pointed-to `references/` files,
and journals each removal with its own chief-owned ask before changing the source.
Pointers retain their section headings and spacing. The returned asks cover only this
request; earlier asks remain in the journal for the driver to reconcile by receipt.
For a reference longer than 100 lines, add its table of contents before delivery.
Remeasure the start-up using the changed loaded set and report tokens before/after.

Deliver **each** returned ask through the user profile's ask binding, as the
unattended slim does. The chief owns escalation to the user; include the section,
estimated tokens, sessions loaded, and zero-evidence finding verbatim. Retain the
journal and delivery receipts beside the branch's report. Without a binding or a
confirmed receipt, report the undelivered ask in full and keep the branch waiting.
`merge_allowed: false` is deliberate: this helper never merges. Neither delivery
nor an automatic slim grants merge approval. The driving session must retain each
user answer before any merge; a missing answer blocks it. Rejection through `revert` restores the
section using its journaled lines and deletes only a byte-for-byte unchanged extracted
copy. An independently edited copy stays in place and is named in `preserved_reference`.
The ordinary file review still leaves edits uncommitted; this workflow leaves its
changes on a slim branch for the user's decision and does not schedule a job.
