---
name: wip
description: "Report in-flight work, blockers, and pending approvals, or catch the user up on changes since their last message. Use for /wip, 'where are we?', 'what's pending?', or 'catch me up.'"
disable-model-invocation: true
---

# What's in flight

A state snapshot with enough context to act on without digging. Three sections, no more.

When asked whether a session can continue beyond its assigned subset, assess the remaining scope separately from current authorization; identify ready work, unresolved decisions, and actual dependencies.

## 0. Read the durable state layers FIRST (mandatory)

Before writing anything else, ALWAYS pull the durable in-flight record. There is no session snapshot file; read the sources relevant to this session:

- **Handoff (current subject)** — resolve it with this package's handoff module, `scripts/lib/handoff.py` (resolve the path from this skill's real directory: `../../scripts/lib/handoff.py`): `python3 <module> resolve "$PWD"` prints this session's handoff path, and the handoff a resumed session started from is the one its `/continuity:pickup` briefing named. If one exists, read it for the previous interactive session's pointer to the record, its open loops (dispatched-but-unreported agents, blocked items, open decisions, unrecorded commitments), and its uncommitted files. It is a thin pointer, not the record: verify it against the record.
- **The record** — wherever the handoff points: tickets, project status, documents. When the record is an issue tracker, read each ticket referenced as active/blocked/awaiting-action with its latest progress comments through the user-bound record workflow; progress comments are the durable in-flight record a prior session left. If a session-start hook injected this session's tickets, that block is your starting list.
- **Session charter** — a persistent session's working-directory instructions file (`CLAUDE.md` or `AGENTS.md`), auto-loaded at boot, when the session has one. It holds identity, queues, monitor re-arm specs, and boot doctrine — not per-task state, but it tells you what standing loops this session owns.

If a source doesn't apply to the current session (no charter or no prior handoff), note that and proceed from the ones that do. Do not rely on in-context awareness alone; context is incomplete after a restart or compaction.

Context, tickets, charter, and handoff tell you WHAT to check. They are not themselves the report — they are stale the moment something finishes, closes, or dies in the background. Step 1 below verifies each candidate against current reality before it goes in the report.

## 1. Verify against reality (mandatory)

For every candidate item surfaced by Section 0, confirm its actual current state before it appears in Section 2 or 3. Don't report from memory of what you dispatched or were told.

Two kinds of things need checking, and neither is a fixed checklist — reason from the actual work in this session, don't just pattern-match the examples below:

- **Things this session or its agents touched** — anything you or a dispatched subagent created, edited, started, or committed. If context/handoff/tickets show work against it, go verify the current state of that specific thing.
- **Things another actor could have changed underneath you** — anything whose truth this session is *assuming* rather than just-verified, where a concurrent session, agent, scheduled job, or human could have altered it since. The risk isn't "is this stale" in general, it's "would this specific assumption break the report if it's wrong."

Typical examples of each (illustrative, not exhaustive — the point is the two categories above, not this list):
- Subagents dispatched this session — `TaskList`/`TaskGet`/`TaskOutput` for their real status; `BashOutput` for background Bash.
- Repos this session edited — `git status` (and `git worktree list` if multiple worktrees) for actual uncommitted/unpushed/unmerged state.
- Tickets referenced as open/blocked/awaiting-action — read the current record, since another session or a human could have closed, relabeled, or commented on it.
- Ops jobs / launchd jobs / long-running processes referenced — their actual current state (`launchctl list`, job status/log output), since scheduled runs happen independently of this session.
- **Chat surfaces (e.g. Slack)** — when this machine is connected to one, check relevant channels/threads for updates on anything this report touches that the channel also has visibility into (operations status, per-project channels) — other sessions or the user may have posted state changes there that this session wouldn't otherwise see. When no chat surface is connected, skip these checks entirely; don't guess at channel state from an unconnected surface.

Apply the same reasoning to any other surface that fits the two categories, even if it's not listed above (e.g. a new shared dashboard, another machine's charter/handoff, a queue another agent drains) — the categories are the rule, the bullets are just today's known instances.

This is scoped verification, not a fresh audit — check what Section 0 already surfaced, don't go hunting for new items or surfaces unrelated to this session's work. These are cheap, targeted reads, not the "heavy queries" the Constraints section warns off.

If verification contradicts what Section 0 surfaced — something finished, closed, failed, or got picked up/changed elsewhere — report the corrected reality in Sections 2/3 and flag the discrepancy explicitly (e.g. "handoff said still running; TaskList shows it completed 20m ago with no report given"). Silently updating the number without calling out the mismatch hides exactly the kind of drift this step exists to catch.

## 1.5 Catch-up mode (what did I miss)

When invoked as a catch-up rather than a full snapshot, scope Sections 0–1 to the window **since the user's last message**: subagents/tasks that finished, task notifications not yet relayed to them, background bash output produced, tickets that moved (closed, relabeled, commented — by this session's agents or anyone else), monitors or scheduled jobs that fired, and commits/files landed by other sessions on things this session tracks. Lead Section 2 with that delta before any steady-state. Anything already reported before their last message is out of scope unless its state changed since. The full-snapshot sections and their verify-before-report rule still apply — catch-up narrows the window, it does not skip verification.

## 2. Work in flight

Everything currently running or recently finished-but-unacted. For each item give:
- **What** — the task/operation, in a full sentence (not a bare label)
- **Dispatched / started** — when, if known
- **State** — running / blocked / completed-awaiting-action, plus progress if available

Cover: background agents you dispatched that are still running; background bash commands started with `run_in_background: true`; long-running operations (scheduled jobs, multi-step sequences, migrations); and recent dispatches that finished but whose results haven't been reported or acted on.

If nothing is in flight, say so directly.

## 3. Open questions / approvals waiting on the user

For EACH pending item, use this structure:

- **Request/task** — what decision or approval is needed, with the **full context restated**. If the item came up on another surface (a Slack thread, an ops-job report, etc.), **repeat the relevant message content in full** — assume the user cannot see the other surface. Do NOT cite internal message-id numbers; they're invisible to the user.
- **Consequence so far** — what's happening (or not happening) while this waits, with specifics/counts.
- **Options, expanded** — three parts, in order: the full context of the issue, every option with its tradeoffs, and your recommendation with why it beats the alternatives. **Calibrate toward the verbose end** for these pending decisions — err toward the fuller, more-explained version, not a terse summary. Brevity is for Section 2 (status); Section 3 decisions get the verbose treatment.

Cover: unanswered questions you've posed; decisions you flagged as "your call" or A/B/C options awaiting a pick; approvals needed before a non-trivial action (commits to main, agent dispatches with cost, destructive ops); anything you've said you're "holding for direction" on.

If nothing is pending, say so directly.

## Constraints

- Don't dispatch new agents, don't kick off new work, don't run broad/expensive queries (e.g. scanning all open issues across every repo) — this is a snapshot, not work.
- Section 0 (durable state layers) and Section 1 (verify against reality) are both mandatory on every run — not "only if you don't know." The handoff, record, and charter pick the candidates; Section 1's targeted reads confirm what's actually true right now. Skipping straight from context to the report is the failure mode this step exists to prevent.
- **Never reference internal message-id numbers** (e.g. "msg 877"). When citing prior cross-surface content, repeat it in full.
- Structured per the formats above. Don't pad with thinking or recap — just the facts and the decision-ready context.
