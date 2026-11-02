---
name: hippocampus-set-up
description: Configure or repair hippocampus knowledge and checklist profiles with the user present. Use after installation or to change the knowledge root, checklist bindings, record-read skill, rules, or memory choices.
---

# Configure Hippocampus

Configure the system through a conversation. The purpose of this skill is not merely to produce a valid file: help the user understand the storage model, make the choices that belong to them, and see how those choices affect later research and knowledge workflows.

The installed, version-matched template is [`profiles/karpathy-wiki.example.md`](../../profiles/karpathy-wiki.example.md). The canonical structural check is [`scripts/validate_profile.py`](../../scripts/validate_profile.py). Resolve both relative to this skill so the configuration matches the active package release; run the validator with `python3`.

## Explain the model first

Before asking for values, explain that one knowledge root always contains:

- `raw/`: selected source material and provenance;
- `output/`: durable research artifacts and audit reports awaiting review or distribution;
- `docs/`: AI-maintained operating records, including the operation log and decision log.

Explain the main flow: research creates an inline answer or an artifact; an approved distribution step moves useful findings to named targets or follow-up work, and — when the wiki is enabled — to the wiki.

## Ask whether to use a wiki

Before asking for any wiki-specific value, describe the wiki and its alternative in neutral terms and let the user choose. Neither option is the default or the recommendation:

- **With a wiki**: a `wiki/` folder holds compiled, atomic articles connected
  by Obsidian-style wikilinks, plus `wiki/hot.md` as the recent-context entry
  point. `absorb` and `knowledge-capture` can route selected findings
  into it, and `wiki-compile` and `wiki-audit` compile and audit it.
  Wikilinks are a portable Markdown convention either way; Obsidian is an
  optional client for browsing the result.
- **Without a wiki**: no `wiki/` folder, no wiki-only profile fields, no wiki
  routing in absorption plans or knowledge captures, and `research-to-wiki`
  and `wiki-audit` refuse to run. `raw/`, `output/`, `docs/`, and the rest of
  the research and distribution workflow are unaffected.

If the user declines the wiki, ask none of the wiki-only questions below (the
wiki-maintenance route or whether they use a wikilink-aware client).

## Inspect before asking

Read `~/.config/hippocampus/profile.md` if it exists. Inspect referenced paths without modifying them. Distinguish among:

- no profile;
- a structurally invalid or incomplete profile;
- a valid profile whose local policy may still need clarification;
- a requested change to an existing configuration.

Do not assume that an existing directory is disposable or dedicated to this package. Preserve existing files and the free-form profile body unless the user explicitly approves changing them.

## Configure rules and memory after the base profile is valid

When the user is configuring or changing their rules and memory choices, inspect
the available tools before asking them to choose a preset. Run the installed
`scripts/rules_setup.py inspect` helper (with fake homes only in tests). It
reports each supported tool's installation state, user instruction target,
target existence and composer ownership, current memory state and settings
file, and the memory store's location and file count. Report a nonempty store
as content for the user to act on; set-up never deletes a store or any file in
it.

If the profile's optional `rules.development_root` is present, include one
delivery column in the state table: Claude Code receives development rules by
directory walk from that root; Codex and OpenClaw receive them through a
repository block. The profile may record the absolute development root; it is
not a rules document location.

Offer two editable starting points for installed tools:

- **standard:** every rules target is `none` and every memory value is
  `native`;
- **thin:** each rules target is its detected default instruction file and
  every memory value is `off`.

The user may change either value in any row before approval. `native` records
the choice while retaining the detected state and proposes no memory setting
change. `off` proposes only an already-documented off setting that differs
from the detected value. Claude Code uses `autoMemoryEnabled: false`; Codex
uses `features.memories = false`; OpenClaw disables both pre-compaction memory flush and
memory-core dreaming. If a memory directory or workspace is customized,
describe it, flag an `off` selection for the user, and propose no change.

Use `scripts/rules_setup.py plan --profile <profile>` to prepare the complete proposed mutation
list. It names every target file that will change and every memory setting with
its current and proposed value. Also show the four useful context documents —
devices, file locations, people and preferences — as optional guidance only;
do not include them in the mutation list. Record the returned
`approval_fingerprint` with that exact review.

Wait for explicit approval of that exact list. A decline writes nothing and
leaves the profile's existing rules section unchanged. On approval, run
`scripts/rules_setup.py apply --profile <profile> --preset <preset> --approve --approval-fingerprint <approval_fingerprint>`
with any approved per-tool overrides. The helper recomputes the plan before
writing and refuses if its fingerprint differs, so no newly introduced mutation
can be applied without a new review. It applies targets through
`compose_rules.py`, updates only the proposed memory settings, and records the
preset, both context document locations, optional development root, and each
installed tool's final rules target and memory value in the profile. The helper
reads and validates the profile through `validate_profile.py` before replacing
only its rules section.

## Discuss the user-owned choices

Ask only for choices that cannot be inferred safely, and explain each before requesting it:

1. The absolute knowledge-root location.
2. When the wiki is enabled, the route for wiki-maintenance follow-ups.
3. The independent task route for source-derived actions, including meeting tasks and research findings that require work in another project.
4. Any local policy the agents should follow: taxonomy, source-library routing, output naming, operation/decision log formats, and local boundaries.
5. Optional meeting inputs: `meeting_transcript_source` (provider or retrieval instructions), `meeting_event_source` (calendar provider or retrieval instructions), and `meeting_note_path` (optional default local path or Google Docs link; `{date}` is optional for local paths). Each independently accepts `disabled`. Explain that notes and events are read-only context, connectors must actually be available, and omitted event/note fields skip those lookups. Do not require meeting configuration for users who do not capture meetings.
6. When the wiki is enabled, whether the user plans to use Obsidian or another wikilink-aware client. This changes the usage guidance, not the profile schema.

When the wiki is enabled, the two follow-up routes may be different and must be concrete enough for another agent to execute. Do not accept the unchanged instructional placeholders from the example profile as configured destinations.

## Present the complete change before writing

Show the proposed values and an exact mutation list: directories to create, files to create, profile fields to add or change, and policy-body edits. Call out everything that already exists and will be preserved.

When the user declines the wiki, the mutation list contains no `wiki/` directory, no `wiki/hot.md`, no `hot_file`, and no `wiki_followup_destination`. It contains `raw/`, `output/`, `docs/`, the operation log, the decision log, and the profile with `wiki_enabled: false` recorded. When the user accepts the wiki, the mutation list adds `wiki/`, `wiki/hot.md`, `hot_file`, and `wiki_followup_destination` to that same base.

Do not write or change configuration until the user approves that complete proposal. Installation and configuration are separate authorization boundaries; the fact that the package is installed is not approval to create a knowledge root.

## Apply an approved configuration safely

After approval:

1. Create only missing canonical directories: `raw/`, `output/`, and `docs/`, plus `wiki/` when the wiki is enabled.
2. Create only missing state files: `docs/log.md` and `docs/DECISIONS.md`, plus `wiki/hot.md` when the wiki is enabled. Never truncate them.
3. Create or update `~/.config/hippocampus/profile.md` from the active example schema. Use root-relative state paths and preserve unapproved frontmatter values and body content. When the wiki is declined, set `wiki_enabled: false` and omit `hot_file` and `wiki_followup_destination`; when it is enabled, omit `wiki_enabled` (or set it to `true`) and include both wiki fields.
4. Run the active `scripts/validate_profile.py` with `python3` against the resulting profile.
5. If validation fails, report the exact failure and propose the smallest repair; do not replace the profile wholesale.
6. If validation succeeds, summarize the configured root and routes, then teach the user one short first workflow appropriate to their goal. When the wiki is declined, the summary and that first-workflow teaching mention no wiki.

Structural validation proves that the required paths and fields exist. It does not prove that the local taxonomy, route descriptions, or operating policy are useful; confirm those meanings conversationally.

## Enable or disable the wiki later

When an existing profile is valid, offer to change its wiki state as part of a
requested-change conversation. Both directions go through the same
present-then-approve gate as any other change:

- **A wiki-disabled profile**: offer to enable the wiki. If accepted, ask only
  the wiki-only questions from Discuss the user-owned choices (the
  wiki-maintenance route and whether the user uses a wikilink-aware client),
  then propose creating `wiki/` and `wiki/hot.md` and adding `hot_file` and
  `wiki_followup_destination` to the profile. Apply only after approval.
- **A wiki-enabled profile**: offer to disable the wiki. If accepted, propose
  removing `hot_file` and `wiki_followup_destination` from the profile and
  recording `wiki_enabled: false`. Never delete or modify `wiki/` or anything
  in it — disabling only changes the profile.


## Meeting records and custom proposal policy

Explain optional `meeting_record_folder` (defaults to root-relative `meetings`)
and `meeting_record_template` (defaults to the bundled minimal Markdown template).
A per-capture template can override the default. Template paths can be relative to
the root or explicit absolute paths; record folders must stay within the root.
Custom headings/coaching are optional presentation, while source and approval
semantics remain shared. Show exact requested settings before changing them.
Validation checks template validity and containment without creating records or
folders. Never copy over a user's custom template during install or setup.

Discuss independent transcript intake and retained-source destinations in the local
policy body, within `raw/`, when meeting filing is requested. When custom classes are requested, explain the profile body's optional
`hippocampus-classes` JSON block from the shared distribution contract. Ask for
class names, searches, required fields and workflow or destination, with attribution
and reuse rules. None are enabled by default; absent writable routes leave
candidates in their records. Preserve local compiler/audit modes, thresholds, coverage and delegated
policy files when replacing an owned local wrapper. No automatic backfill,
whole-library sweep, task creation or publication is part of setup.


## Checklist configuration

Offer checklist configuration independently of knowledge configuration. A user may decline knowledge configuration; write no knowledge profile in that case. Show the exact checklist changes and obtain approval before applying them. Preserve both existing profile bodies and bindings.


Interview the user, then write their choices. The user need not read or edit
profile JSON. Claude Code and Codex follow this same procedure.

## Require the user present

Before any writes, establish that the user is answering this setup interview.
If started unattended, by a scheduler, or as a subagent, stop and report:
“Setup requires the user present; unattended setup stopped without writes.”
An earlier instruction to execute work unattended is not presence. If presence
is unclear, ask and wait. Never supply answers for the user or pass
`--user-present` until they have answered this interview. If the user leaves,
stop with setup incomplete and the unanswered questions.

Resolve this skill's real directory through any installed symlink. The package
root is two directories above it. Read that root's `INTERFACE.md`, sections 6
(profile format) and 9 (record-read contract), before authoring bindings. The
helper below is `scripts/profile.py` inside this skill's real directory.

## Read what is already configured

Resolve the user profile from `$CHECKLIST_USER_PROFILE`, otherwise
`${XDG_CONFIG_HOME:-~/.config}/hippocampus/checklist-profile.md`. Read the complete existing
file if present, including prose and instruction sections. Retain its name,
steps, sections, notes, and bindings the user does not choose to change. Never
replace an existing profile with the example profile. If it is malformed, stop
and explain the error rather than discarding content. Repository profiles add
steps; setup changes only the user profile.

## Offer every slot

Explain and offer each of these four choices, including keeping an existing
binding. Ask which available skill they want, or whether they decline:

| Slot | What its binding does | Usual consumed item types |
|---|---|---|
| `record` | Write progress, commitments, decisions and artifact locations to their durable record. | `progress`, `commitment`, `decision`, `artifact` |
| `knowledge` | Capture knowledge in the user's chosen home. | `knowledge` |
| `lessons` | Fold lessons into rules, skills or memory; offer the installed `improve-harness` skill. | `lesson` |
| `persist` | Persist changes through the user's chosen workflow. | an empty list unless their skill consumes specific item types |

Use skills the user actually has. Explain missing capabilities without inventing
commands. Confirm consumed types against the chosen skill. For each accepted
binding prepare `{"command": "<actual skill invocation>", "consumes": [<types>]}`.
For a declined slot use JSON `null`, including for `lessons`: omission would
retain its default binding. Unbound slots still run their spine step and carry
unsaved items as open loops. Declining a replacement for an existing binding
means keep it unless the user explicitly chooses to unbind it; explain that
choice before changing it.

## Write the user's read skill

Ask which tool the user tracks work in, how they access it, and how their tools
identify work carried by a session. Inspect the tools and user-owned skills
already available in this session. Ask about missing access immediately; never
invent results, silently install dependencies, or request secrets in a file.

Agree on a skill name and a user-owned destination outside this package and its
installer-managed directories. Use the running tool's user skill directory or
a shared user-owned skill home with discovery links for both tools when the
user uses both. Preserve any pre-existing skill; ask before replacing it.
Write its `SKILL.md` with the actual read tools available to that user. This is
user configuration, never a package example, adapter, or template. Do not edit
package files or its managed skill links during setup.

The authored skill must implement **both** requests in interface section 9:

- `ticket_status`: take the provided references; return one row per distinct
  reference, including an explicit `not_found` row for each unresolvable one.
- `commitments`: take the resumed session's `session_id`, `repository` and full
  `handoff`; use the user's means to find work carried by that session.

Return only the specified JSON response fields. Use the record's actual state
and progress; an empty successful read and an unavailable read differ. Return
`{"kind": "error", "reason": "<actual reason>"}` for access or tool failures.
Require read-only operations: never create, update, transfer, or close work.
Writing belongs to the separate `record` slot. Use the actual discovered skill
invocation in `record_read.command`, with the same behavior in both tools.

## Prove the read before binding it

Run the new skill at least once with a real request agreed with the user. Prefer
one known work reference for `ticket_status`; an empty input cannot prove access.
For a commitments probe use the actual session identity, repository and handoff;
do not manufacture a resumed session or handoff. Preserve the exact response in
a user-approved evidence location outside the package. Run the package validator
with the matching request kind, replacing the angle-bracket paths:

```bash
python3 <package-root>/scripts/lib/record_read.py --expect <request-kind> < <response-file>
```

Show the exact verdict and exit code. `valid` with exit 0 is required. An
`invalid: <reason>` (exit 1), `error: <reason>` (exit 2), or failed skill execution
means setup is incomplete: explain the blocker, correct it with the user and
retry, or stop. Never change the response by hand to obtain a passing verdict.
Also compare returned references with requested references: schema validation
does not prove completeness or accuracy. Do not bind a failed new skill.

## Merge and check the profile

Show the proposed choices in plain language, including the read skill's path
and invocation. Once the user's choices are settled, pass only changed slots
to the helper. It preserves other bindings and all existing profile content
outside the JSON block, validates the candidate with the composer, and writes
atomically. Before successful replacement, any failure removes its temporary
file and newly created directories, preserving the existing filesystem. A new
profile is created when none exists.

```bash
python3 <setup-directory>/scripts/profile.py --user-present \
  --bindings '<JSON object of accepted bindings and explicit null declines>' \
  --record-read '<actual user-owned skill invocation>'
```

The helper uses the profile resolution above; `--profile <path>` explicitly
selects the same resolved user profile. Omit `--record-read` if preserving an
existing read binding. If the user declines writing a read skill, do not invent
one: preserve their other choices and report record-read setup incomplete.
A user without a binding can still use pickup from handoffs alone.

Run the public composer on the written profile with the actual session id:

```bash
python3 <package-root>/scripts/lib/checklist.py plan \
  --user-profile <resolved-user-profile> --session-id <current-session-id>
```

Show its result. Do not run the checklist or any write binding as a setup test.
On any composition error report setup incomplete; keep existing content intact.

## Report

Name the user profile and user-owned read skill; list all four slot choices,
including unbound slots. Include the request kind, validator verdict and exit
code, composer result, and outstanding access or user decisions. Report success
only after the new skill ran successfully, its response passed validation, and
the written profile passed the composer. When a tracked setup task requires a
manual clean-home run, retain the actual interview answers, commands and verdicts
outside the package and give the caller the evidence for its ticket.
