---
name: setup
description: Configure continuity with the user present, creating or extending their user profile and writing and validating their own record-read skill. Use after installation or to change checklist bindings.
---

# Set up continuity

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
`${XDG_CONFIG_HOME:-~/.config}/checklist/profile.md`. Read the complete existing
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
