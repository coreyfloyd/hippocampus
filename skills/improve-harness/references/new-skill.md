# New-skill lessons

A new-skill lesson proposes a skill for a process this session carried out by
hand. It is a lesson like any other, placed on the skills rung, with one
difference: no skill is created without the user's yes, whatever the mode or the
auto-apply setting.

## What counts

- Three or more ordered steps, carried out in this session, by the user or the
  agent. A shorter procedure is a rule or a skill gotcha.
- Likely to recur. One occurrence is enough when the row says why it will recur;
  cite earlier handoffs or tickets only when this session already read them.
- No available skill covers it. Compare it with the running tool's skill catalog,
  as source (c) does. When a skill covers the work, the row is a description or
  trigger edit to that skill, never a new skill.

Earlier sessions are not mined for processes; only this conversation grounds a row.

## The proposal

Every new-skill row, presented or carried, holds all of these and no draft skill text:

1. **Process**: what was done, in a few words.
2. **Steps observed**: the ordered steps as carried out in this session.
3. **Why it recurs**: the reason, with any earlier handoff or ticket the session read.
4. **Name**: the proposed skill name.
5. **Trigger**: when it should fire, in the words a description would use.
6. **Nearest skill**: the closest skill in the running tool's catalog, by its real
   name, and why it is not that one.

Its placement column reads `new skill`. Its target is the location the lesson
routing names for the user's skill sources, or `ask the user` without one.

A carried `lesson` item holds the whole proposal in `context`, `new_skill: true`,
the target and evidence, and `choices` (for example `create the skill`, `edit
<nearest skill> instead`, `decline`). A later interactive run presents it unchanged.

## Auto-apply

With `plan` returning `auto_apply.lessons: apply`, give the row `new_skill: true`
and its `choices`; it needs no `target`, `edits` or `change`. `apply-lessons` never
writes it: a row recommending `apply` makes its outcome `asked`, the item stays
carried, and `new_skill_asks` holds the asks raised by that call
(`new_skill_ask_errors` names any it could not build). Send each ask to the ask
binding through an R4 row with `destination: "ask"` and its choices, as for a fact
about the user; the lesson stays carried until the user answers. A `skip` row drops
it with its reason, `dictated` or not. An item marked `approved: true` is never asked
again, and neither is an ask already delivered. A sweep in act mode does the same,
raises an undelivered ask again from its recorded outcome, and keeps a lesson whose ask
was delivered carried in its handoff until the user answers.

## The user's answer

Read the answer from the ask binding. Give the lesson's next row `answer`, the choice
the user picked, at a wrap or in a sweep's assessment, with `recommend: apply` for
`create the skill` and `skip` for any other answer; a contradicting row is refused.
An answer counts only for an ask a ledger records as raised, and is checked against
the choices that ask offered. `create the skill` records the yes as `approved: true`
and carries the item without choices; any other answer drops the lesson with that
reason. With no answer yet, the lesson stays carried and its delivered ask is not
raised again.

## After the yes

Each approved lesson comes back once, in `skill_creator_handoffs` from `apply-lessons`
or as the sweep row's `skill_creator`; the ledger marks it handed off
(`creator_handed_off`), so no later run hands it again. improve-harness writes no
skill text. Hand the proposal, unchanged, to the
running tool's built-in skill creator, which drafts, tests and tunes the skill:

| Tool | Skill creator | When it is missing |
|---|---|---|
| Claude Code | the `skill-creator` plugin from the `claude-plugins-official` marketplace | `claude plugin install skill-creator@claude-plugins-official` |
| Codex | the bundled `skill-creator` system skill | it ships with the Codex CLI; update the CLI to restore it |

Tell the creator where to write: the skill-source location the lesson routing names,
so the new skill lands where the user's skills are committed. When the routing names
none, tell the creator to ask the user for the location.

Never rewrite the carried item's `context`: that is part of the item's identity, so a
changed one would be asked again.
When the running tool has no skill creator, apply nothing: keep the approved
proposal carried and report the install line from the table.
At a wrap the approved lesson stays carried until the creator reports the skill
written: then its row is a `skip` naming the written skill. A sweep has nobody waiting
on the creator: the hand-off is the lesson's receipt, and its handoff is archived.
