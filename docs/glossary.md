# Hippocampus Glossary

Defines the shared knowledge and session-memory vocabulary.

## Language

**Interactive session**:
A session a person starts and can keep prompting after it begins, or one that another interactive session starts on that person's behalf. Interactive sessions write and read handoffs. A session started by an automated scheduler, and a subagent, are not interactive sessions and never write or read one.
_Avoid_: chat, one-shot session

**Record**:
The durable place a session's work is kept: tickets, project status, documents, and their history. It is the primary persistence, and a handoff only points to it. The package runs the record step and calls the record writes named by the user checklist profile; it provides no record store.
_Avoid_: handoff, session memory

**Record write**:
A user-bound command that writes one kind of record change: tickets, projects, documents, or scheduled jobs. The package record step looks up an item by its unchanged producing session, time, and text before writing it. Only a matching receipt proves the item was saved. Each kind is optional in the user checklist profile.

**Record read**:
A read of the existing record through a user-bound skill. It is read-only: it reports ticket status and work carried by a resumed session without writing to the record. The user checklist profile binds the skill; a repository checklist profile cannot. The package record step calls record writes to save changes.
_Avoid_: tracker

**Handoff**:
The thin pointer one interactive session writes for one subject, so the next session can find its way back to the record. A handoff is identified by its subject and its session together, so two sessions on the same subject never overwrite each other. It holds where to find the record, the session's open loops, and the uncommitted files the session changed. It also holds the session's dated history entries and session summary, close outcomes, touched tickets, and touched projects. Checkpoint and wrap both end by writing it.
_Avoid_: record

**History entry**:
One handoff write's account of the work since that session's previous entry, with its producing session identity, time, and text. Every checkpoint and wrap adds one real entry. Entries stay in the session ledger through compaction. An automatic stop handoff is marked as a skeleton and adds no entry, while retaining earlier entries.

**Close outcome**:
One milestone or epic state reported when a ticket closes: kind, title, open or closed state, done of total, triggering ticket, and time. The ticket record write reports it; the package stores it in the session ledger beside history entries. The wrap builds its outcome line only from these stored facts, without rediscovering milestone or epic state.

**Session summary**:
One account the agent writes at wrap from every history entry and close outcome in the resumed chain, including the current session's work. It covers every entry, describes every ticket it names, and names any session that ended with only a skeleton and the time it ended without an account of its work. The final handoff stores it; the report prints it immediately after the outcome line. Record writes never compose it. A projects record write receives it with close outcomes and touched projects.

**Touched ticket**:
A ticket the session read, changed, or closed. Its reference is retained in the session ledger and handoff. At wrap the ticket record write re-reads only touched tickets, including those carried from a resumed chain, and records any closed ticket's missing close outcomes.

**Touched project**:
A project the session worked on, identified by a stable reference in `resume.touched_projects` or an item's `anchor.project`. The ledger and handoff retain its reference through compaction and pickup. A projects record write receives all touched projects alongside the session summary and close outcomes.

**Resumed chain**:
The sessions continued through pickup, native same-session resume, or compaction. A session started from a brief or pasted prompt without pickup starts its own chain. At pickup, the successor's ledger immediately receives the selected handoff's history entries, close outcomes, touched tickets, retained session items, and resumed-chain records. Later commands use only that ledger, never the resumed handoff file.

**Resumed-chain record**:
One session's pickup of a handoff: its path, producing session identity, and resume time. It also retains the handoff's write time and skeleton marker so a successor can identify a session that ended without an account of its work. Records are carried whole through every successor's ledger and handoff.

**Successor**:
The interactive session that resumed another session's handoff through `pickup`. The session whose handoff it resumed is the **resumed session**, which is never used again. Every contract bound to the resumed session's id — claims, pending approvals, pending replies, granted scopes, and any other record keyed by session id — is carried to the successor's id. See [The successor rule](../skills/pickup/SKILL.md#the-successor-rule) for transfer ownership and the fallback when no transfer tool is available.
_Avoid_: resumed session (when referring to the successor)

**Subject**:
What a handoff is about: the working directory of an ordinary session, or the channel of a session that answers one channel.
_Avoid_: session, repository

**Sibling**:
A handoff whose subject is a different worktree of the same repository as the current subject. Resume lists siblings and marks them as such.
_Avoid_: duplicate, related session

**Checkpoint**:
Writing the handoff now, without finishing the session's work. A checkpoint never commits, merges, or pushes. It carries every session item the record does not yet hold as an open loop, and restores the session's retained session items it was not given again. When the handoff fails its validity check, a checkpoint still writes it and reports the failure.
_Avoid_: wrap, save

**Timed checkpoint**:
A per-session prompt scheduled after each checkpoint. Below the configured token limit,
the agent writes another checkpoint; at or above it, the prompt does nothing. Claude Code
uses a session-only one-shot job; Codex uses a detached timer that queues the same prompt.
Each checkpoint replaces the pending timer. Before compaction the hook writes a checkpoint
from retained facts, preserving the agent's continuation without requiring an agent turn.

**Wrap**:
Finishing a session: running the checklist, which is the spine plus any checklist profile steps, and ending by writing and validating the handoff. Unlike a checkpoint, a wrap fails, and says why, when the handoff fails its validity check.
_Avoid_: checkpoint

**Spine**:
The fixed five steps every wrap runs, in this order: reconcile the record, capture knowledge, fold in lessons, persist, write and validate the handoff. A checklist profile can add steps around the spine but cannot remove or skip one of its steps. Only one step runs after the last: `own-worktree`, which removes the session's own worktree once the handoff is written.
_Avoid_: checklist (the checklist is the spine plus checklist profile steps)

**Checklist profile**:
One file that extends the checklist: it binds slots, adds steps before the spine, and adds steps after any of the spine's first four steps, and may add the one step `own-worktree` after the handoff. A user checklist profile applies to every session; a repository checklist profile adds steps for sessions in that repository.
_Avoid_: configuration (shared settings are separate from checklist profiles)

**Knowledge profile**:
The existing `~/.config/hippocampus/profile.md` file that configures the knowledge root and knowledge workflows. Its format and free-form policy body are preserved.

**Knowledge root**:
The configured root containing retained sources in `raw/`, research artifacts in `output/`, operating records in `docs/`, and an optional compiled `wiki/`.

**Slot**:
A named spine step that a checklist profile binds to a command. Only `persist` is a slot. Record is a package step that calls per-kind record writes. The ask binding is configurable but is not a spine step. A binding names the session-item types it consumes, including carried open loops of those types. An unbound slot carries its items forward in the handoff.
_Avoid_: hook, plugin

**Native step**:
A package-owned checklist step: knowledge capture runs knowledge-capture and lessons run improve-harness. They are not configurable slots. Lesson destinations remain configurable through the routing file. A carried item is removed only after its step returns a receipt.

**Ledger**:
The per-session list of what one session touched: one entry for each file it changed and each artifact it published, plus its history entries, close outcomes, touched tickets, retained session items, and resumed-chain records. Checkpoint reads the ledger to list uncommitted files and pending artifacts, so neither depends on the session remembering them. A publishing tool records an artifact through the package's one ledger command.
_Avoid_: log, history

**Open loop**:
One item carried in a handoff, with a disposition saying what should happen to it. A carried item names its session-item type (progress, commitment, decision, knowledge, lesson, artifact, or open loop) and keeps the identity of the session that produced it and when; a decision also keeps who made it and where. A slot that consumes an open loop removes it from the handoff.
_Avoid_: todo, task

**Retained session item**:
A session item, other than an artifact, that a checkpoint received and stored in the session ledger with its original identity: producing session, time, type, and context. Every later checkpoint, pre-compaction write, stop skeleton, and wrap restores it as an open loop, once, until it is settled. The wrap settles an item when it files or drops it, or when a native step returns its receipt; a later item marked recorded settles it too. Another session's items enter the ledger only through pickup, which copies the resumed session's unsettled items to the successor.

**Sweep**:
An unattended-safe pass over the handoffs in one scope: a directory together with every worktree of its repository, or every handoff on the machine. For each abandoned session in scope it applies the filing rules to the handoff's items, removes the session's clean, merged worktrees, archives the handoff once nothing in it is left unhandled, and writes a sweep report. A sweep never acts on a session that is still open.
_Avoid_: cleanup, reconcile, prune (prune is pickup's move of dead handoffs into the archive)

**Filing rules**:
The fixed, ordered table that decides what each carried item becomes: dropped with a reason, a comment on the ticket it names, an ask, a lesson or knowledge item for its native step, a document change, or a new ticket. A wrap and a sweep apply the same rules.
_Avoid_: disposition (an open loop's own instruction), triage

**Ask**:
An item only the user can resolve: a decision, an approval, a destructive action, or a session left open. The driving agent hands each ask to the user's ask binding, one configured command that is not a spine step. With nothing bound, an ask stays in the sweep report and its handoff is kept. Its complete text and choices have no length limit through checkpoint, compaction, pickup, and wrap. Every checklist report ends with all filed or carried asks in full, with lesson asks first, including their target file and section, proposed text, and evidence. Failed or incomplete wraps still show the asks alongside their errors. An ask about an applied lesson is text only: it says what was already done and how to undo it, and has no choices. An ask about a fact about the user is an ordinary ask: it keeps its choices, has no default, and never resolves on its own.
_Avoid_: question, needs-you item

**Auto-apply setting**:
The `auto_apply_lessons` value in the hippocampus configuration, off by default. With it on, a wrap applies the lessons it recommends and captures the knowledge it recommends for the wiki or for retention under the knowledge root, instead of waiting for approval, in every interactive session, attended or unattended. The setting decides, not whether the user is present. A routing file's `lesson-policy: propose` overrides it for lessons only.
_Avoid_: auto mode, autopilot

**Applied lesson**:
A lesson a wrap wrote to its source under the auto-apply setting, as one commit of its own in the repository holding that source, so reverting the commit removes exactly that lesson. A target outside git, an existing untracked file, or an ignored path in its repository, is written with no commit; a new file the repository would track gets its own commit. The session ledger keeps each lesson's outcome (applied, dropped or failed) and its delivery. A repository that refuses a direct push, or that the routing file names, gets the wrap's lessons for that checkout on one lesson branch, one commit each, with one pull request opened by the user's command; the lessons stack there, so two for one file do not conflict when they merge. An applied lesson is settled, except one for an always-loaded rules file: that one stays until its ask is delivered, and it carries no choices.

**Applied capture**:
A knowledge item a wrap captured under the auto-apply setting without an approval: compiled into the wiki, or retained as a source under `raw/` or an output under `output/`, all inside the knowledge root. The session ledger keeps each item's outcome (captured, asked or failed) with the files created and updated, relative to the knowledge root. A captured item is settled. Every file a capture names is under its kind's folders (a wiki capture's under `wiki/` or `raw/`, with at least one article in `wiki/`, plus the profile's session cache and operation log that a compile writes) and was written after the wrap's checklist started; otherwise the capture fails and the item keeps its approval. A fact about the user is never an applied capture until the user has answered its ask; the row that settles it records that answer.
_Avoid_: auto-capture, applied knowledge

**Fact about the user**:
A knowledge item that states something about the user: a preference, habit, or circumstance. Under the auto-apply setting it is never captured without the user; it becomes an ordinary ask naming the proposed text, its destination and its source.
_Avoid_: personal fact, user memory

**Delivered mark**:
A ref under `refs/hippocampus/delivered/` in a checkout, named by a local lesson commit and pointing at the commit that carried that lesson to the remote on a lesson branch. The saved line leaves a marked commit, and only that commit, out of the commits it counts as not pushed, in this wrap and every later one, so a pull request's local commit does not fail a later wrap in that checkout, before or after the request merges. The package writes it at delivery and never removes it.
_Avoid_: delivery note, pushed tag

**Over-limit record**:
One file a wrap found over its size limit, or named in a duplicate rule, kept under the auto-apply setting for a later unattended slim instead of being put in front of the user. It names the file by repository (the repository's path on its host, such as `owner/name`, from the checkout's `origin` remote, else its only remote) and path inside that repository, never by a local path, and holds each exceeded limit by tool and unit with its measured size, every duplicate rule naming the file, and the sessions that recorded it. A file recorded by several sessions is one record. A measurement replaces only what it measured: this tool's limits, every unit for a file loaded in full and the description units for a skill only listed, and a duplicate rule only when the wrap loaded every file it names. A file left with no finding under any key has no record. With the routing file's `lesson-policy: propose` nothing is recorded. Records live in the machine's store beside the session ledgers, so they outlive the session whether it wraps or is abandoned. A file outside git, one git does not track, or one in a repository without a hosted remote (none, two without `origin`, or a local, `file://`, absolute or `~user` path), gets no record: the wrap reports it with the attended slim command.
_Avoid_: slim queue, backlog

**Always-loaded rules file**:
A user-level rules file, a file it imports, a repository's instruction file (`CLAUDE.md` or `AGENTS.md`), or a source composed into one of them. An applied lesson for one also raises an ask.

**Abandoned session**:
An interactive session idle for longer than the configured threshold that no open-session check reports as open. Only an abandoned session's handoff is swept.
_Avoid_: dead session, stale session

**Sweep report**:
The file one sweep run writes, grouped by directory: the asks it raised, the items it filed and where, the items it dropped and why, the sessions still open, and the worktrees it removed. It gives status and asks for nothing; the asks themselves go through the ask binding.
_Avoid_: digest, summary

## Touched repository

A checkout in the current session's ledger, recorded from a tool call's working directory or an edit tool's changed file, plus checkouts the agent names during checklist. The shared checked-checkout list is additive: the agent can add, never remove. Each checkout is checked for uncommitted changes and current-HEAD commits absent from every remote-tracking branch. The saved line names each checkout and branch; its claim covers only that list. Shell-only targets not named by the agent, other local branches, other worktrees, and predecessor-only checkouts are accepted limits.
