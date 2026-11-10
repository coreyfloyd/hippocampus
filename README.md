# Hippocampus

Hippocampus is a portable, holistic system for keeping your agents' rules and
knowledge. It works with any agent: installers ship for Claude Code and Codex
today, and because the skills are standard Agent Skills and the rules are
composed into `AGENTS.md`, any agent that reads those can use them.
Everything is plain files you own. It remembers five kinds of things:

- **Captured knowledge** from meetings and conversations, kept as
  source-linked records.
- **Research**: reports that answer a question, cite their sources and end in
  decisions.
- **The wiki**, where selected evidence is compiled into short, linked articles.
- **Sessions**: where a piece of work stands, written as a handoff the next
  session can pick up.
- **Rules**: the instruction files, skills and memory settings that govern
  your agents.

Most memory tools keep one of these. Hippocampus keeps all five because they
feed each other: a lesson from a session becomes a rule, a source from a
research question becomes a wiki article, and the next session starts with
both. Every change to a person, document, task, wiki article or rule is
proposed first and runs only once approved.

Hippocampus runs on top of your agent's own compaction and complements it.
Compaction summarizes a long conversation and can drop detail. Hippocampus
keeps a handoff for each session (where the work stands, its open loops, the
files it changed), checks it at the end of every turn, and puts it back into
context after the agent compacts. Because the handoff is kept current at every
stop rather than written at the last moment, it holds even when the agent
compacts a session while you are away, as Claude Code now does with idle
sessions. A wrap at the end of a task sends what the session learned to your
rules, your knowledge and your record before the conversation is gone.

## How the parts fit together

![Hippocampus has five parts. A session writes a handoff through checkpoint or checklist and captures knowledge through knowledge-capture; sources become a meeting record through meeting-capture or a research report through research-topic. You approve or decline each proposed change: lessons reach rules and the agent harness through improve-harness, and absorb carries captures and research to the wiki through wiki-compile and to documents and follow-up work. Through pickup, the next session resumes from its handoff under the improved rules, with the wiki to read.](docs/images/overview.svg)

Every step writes Markdown or JSON to disk, and every step that changes
something you own asks first. You can run any step on its own. The wrap
checklist runs the loop for you at the end of a task: it reconciles your
record, captures knowledge, folds lessons into your rules, persists the work
and writes a handoff, in that order.

## The session loop

![Mid-task, checkpoint writes a handoff; a finished task wraps through checklist and writes one. Pickup in Claude Code or Codex reads the handoff and follows it back to your record.](docs/images/session-lifecycle.svg)

The handoff is how one session passes its work to the next. Hippocampus keeps
your **record** (tickets, project status, documents) as the
source of truth and writes a thin **handoff** that points back to it, with the
session's open loops and uncommitted files.

Hippocampus does not impose its own files for projects and tasks. Most people
already run a project-management tool or task tracker, so Hippocampus writes to
the one you use: the checklist's record and persist steps call your own
commands or skills, and follow-up work from research and meetings goes to the
task route you describe in set-up.

- `checkpoint` writes the handoff now, mid-task. It never commits or pushes.
- `checklist` wraps a finished task through five fixed steps: reconcile the
  record, capture knowledge, fold in lessons, persist, and write and validate
  the handoff. A checklist profile binds the record and persist steps to your
  own commands and can add steps, but cannot remove any.
- `pickup` lists handoffs after a cold start, including ones from other
  worktrees of the same repository, and checks the one you choose against the
  record.
- `wip` reports current work, blockers and pending approvals.
  `handoff-prompt` writes a prompt for deliberately handing work to another
  session or tool. `sweep` reports abandoned sessions and, when configured,
  files their open items.

Handoffs live outside either tool's data folder, so you can checkpoint in
Claude Code and pick up in Codex. Checkpoints never schedule timers.
Use `keep-warm on` only while waiting on a specific result or reply that will
message this session, expected within about two hours. It starts off, allows at
most two wakes around 55 and 110 minutes from activation, and stops at the first
wake without new incoming work. Empty wakes write no handoff. `keep-warm off`
cancels pending work; Claude Code executes native CronDelete.
The pre-compaction hook preserves real work from retained facts.
Hooks also remind you to checkpoint when context
passes 50%, restore the handoff after compaction, and suggest a wrap after a
commit, push or passing test run. The [session guide](docs/session-guide.md)
covers every skill, hook and file the package writes.

## What it remembers

| Area | What it keeps | Where it lives | Skills |
|---|---|---|---|
| Wiki | Atomic articles compiled from selected sources, with topic indexes | `wiki/` in your knowledge root | `wiki-compile`, `wiki-audit` |
| Research | Reports that answer a question, assess the sources and end in decisions | `output/`, with sources in `raw/` | `research-topic`, `research-sources`, `quick-research`, `dev-research`, `feature-research`, `feedback-research`, `absorb` |
| Meetings | One source-linked record per meeting, plus the people, documents and follow-ups it changes | `meetings/` in your knowledge root | `meeting-capture`, `transcribe`, `absorb` |
| Conversations | Sources and conclusions from the current session that are worth keeping | Wherever the approved disposition says | `knowledge-capture` |
| Sessions | Handoffs, a ledger of touched files, checklist state | `~/.local/state/hippocampus/` | `checkpoint`, `checklist`, `pickup`, `wip`, `handoff-prompt`, `sweep` |
| Rules | Rule sources composed into each tool's instruction file; lesson routing | A rules document in your knowledge root, composed into `CLAUDE.md` and `AGENTS.md` | `improve-harness`, `slim-harness`, `slim-unattended`, `hippocampus-set-up` |

## The wiki

The wiki is where research ends up when it is worth keeping. It follows
[Andrej Karpathy's LLM Wiki pattern][1]: one concept per article, written as
claims rather than source summaries, with attribution in each article's sources
and `[[wikilinks]]` between related ideas. Agents read it the same way you do.

Three kinds of index keep it fast to search as it grows. `wiki/hot.md` lists
what changed recently, so a session starts there instead of reading everything.
Each topic folder has an `_index.md`, and `wiki/_master-index.md` maps every
topic. The skills update all three as they write.

`wiki-compile` only works from a selected set of primary sources in `raw/`. It
reads those sources before it reads the existing wiki, drafts claims, then
compares them with nearby articles and records tensions and gaps instead of
blending conflicting claims. A research report is never compile input; its
underlying sources are. It never sweeps every uncompiled file. `wiki-audit`
writes a ranked report on structure, source coverage, tensions and gaps
without changing anything.

The wiki is optional. `hippocampus-set-up` asks whether you want one, and you
can turn it on or off later. Without it, research, meetings, sessions and rules
work the same and nothing is routed to a wiki. [Obsidian][7] is the practical
way to browse it, since most Markdown viewers show wikilinks as plain text, but
any wikilink-aware client works.

## Research

![Ask a broad question or bring selected sources; Hippocampus writes a research report; absorb carries approved outcomes to people, documents, follow-up work, the wiki and a retained reference record.](docs/images/question-answer-action.svg)

**Ask** a broad question with `research-topic`, or **bring** sources you
already have with `research-sources`. Both start by settling the **question**:
what you want to understand or decide, the scope, and the evidence needed. Both
produce an **answer** in a research report, with citations, a source
assessment and open gaps.

Substantial research is grounded in [NotebookLM][8], which answers from the
sources you selected and cites them. That keeps the synthesis tied to what your
sources say rather than to a model's training data. Citations still need
checking, and the report says how far to trust each claim.

The report ends in proposed outcomes. Review them, then run `absorb` for the
approved **action**: update people and documents, file follow-up work, and
compile selected evidence into the wiki through `wiki-compile`. You can
decline any single proposal. Once every approved route is done or declined,
the report stays in your knowledge root as a reference record. The report
structure, distribution rules and the deliverables that skip `absorb` are in
the [knowledge guide](docs/knowledge-guide.md#durable-research-and-distribution).

## Meetings

![Bring a calendar event, note or transcript; Hippocampus writes a meeting record in your meeting folder; absorb carries approved outcomes to people, documents (including the original transcript, filed after approved routes complete), follow-up work, the wiki and a retained reference record.](docs/images/capture-meetings.svg)

Bring a **calendar event**, a **note** or a **transcript** to
`meeting-capture`. Each is optional and each adds something different: the
event gives schedule and agenda, notes keep what you observed, and the
transcript records what was said. The record says which inputs it had.
`transcribe` turns local audio or video into a timestamped transcript on macOS
26 or later.

The skill writes a source-linked **meeting record** to its folder (default
`meetings/`) from a bundled or chosen template. The record stays there.
`absorb` carries approved outcomes to the same people, document, follow-up and
wiki destinations as research, and files the original transcript only after
those routes finish. Local policy can add custom classes of proposal with their
own searches, fields and routes; see the
[opt-in worked example](docs/examples/capture-writing.md). Configuration and
source handling are in the
[knowledge guide](docs/knowledge-guide.md#meeting-configuration-and-source-handling).

## Research skills

General research:

| Skill | Use it when | Result |
|---|---|---|
| `quick-research` | You need a cited answer to a general question. | Findings inline in the conversation. |
| `research-sources` | You have URLs, files, media, a source collection or a named target to analyze. | A source-grounded report ending in the decisions it raises; then `absorb`. |
| `research-topic` | You need deep, topic-first research with persistent sources, gap filling and claim verification. | A NotebookLM-backed report ending in the decisions it raises; then `absorb`. |

Specific domains:

| Skill | Use it when | Result |
|---|---|---|
| `feature-research` | You need competitor UX, common patterns or platform conventions before designing a feature. | A design input document filed with the project. Not absorbed. |
| `feedback-research` | An adopt, buy, upgrade or wait decision depends on current community experience. | A decision memo with communities to watch. Not absorbed. |
| `dev-research` | You are diagnosing a bug or checking an API, library or implementation approach. | Competing explanations and sources inline. |

Getting results where they belong:

| Skill | Use it when | Result |
|---|---|---|
| `absorb` | A research report or meeting record has approved changes ready to run. | Runs each approved row and records a receipt for it. |
| `knowledge-capture` | The current conversation produced sources or conclusions worth keeping. | A complete disposition proposal, then the approved captures. |
| `wiki-compile` | A selected set of raw sources is ready to become wiki articles. | New or updated articles, indexes and source status. |
| `wiki-audit` | You want a structural and source-coverage review of the wiki. | A ranked report in `output/`; nothing else changes. |

## Rules and the agent harness

When a session teaches something, such as a mistake you corrected or a "from now
on", `improve-harness` decides where that lesson belongs: a hook, one skill, one
agent definition, a repository's instruction file, your user-level rules, or
memory. It prefers the narrowest place that still loads when the lesson is
needed. Interactive runs propose and wait; unattended runs carry the proposal
forward. A routing file can replace the default placement table.

`slim-harness` reviews one instruction file with you: it finds duplicates and
conflicts with neighboring files, asks before resolving them, and leaves its
edits uncommitted for you to check.

One setting, `auto_apply_lessons` in the shared configuration (off by
default), lets these run without waiting for you. With it on, a wrap applies
the lessons it recommends and captures wiki and retained knowledge under your
knowledge root. It records files over their size limits, and a sweep in act
mode applies the same items from abandoned sessions. `slim-unattended` slims
the recorded files on a branch per repository for your review and never merges
it. A fact about you always waits for your answer, and a routing file line
`lesson-policy: propose` turns lesson applying off. The
[session guide](docs/session-guide.md) explains each step and how to undo it.

Your rules can live in your knowledge root as plain Markdown, one document for
every tool and an optional one for development work. The rule composer writes
them into each tool's own instruction file (`CLAUDE.md` for Claude Code,
`AGENTS.md` for Codex and OpenClaw) and checks for drift. Set-up shows each
tool's current instruction file and memory setting, offers a preset, and lists
every file it will change before it writes. It never deletes a memory store.
Details are in the
[knowledge guide](docs/knowledge-guide.md#rules-and-memory-configuration).

## Your files

Everything is Markdown or JSON on your disk. No database, no hosted service.
You can read and edit it in any editor, version it, and keep it after the
conversation that made it is gone.

```text
<knowledge-root>/          # chosen in set-up
├── raw/                   # source material and provenance
├── output/                # research reports and audit reports
├── docs/                  # operation log and decision log
├── meetings/              # meeting records (folder is configurable)
└── wiki/                  # compiled articles and indexes (when enabled)

~/.local/state/hippocampus/
├── handoffs/              # one handoff per session and subject
└── checklist/             # wrap state

~/.config/hippocampus/
├── profile.md             # knowledge profile
├── checklist-profile.md   # checklist bindings and added steps
├── routing.md             # where lessons go (optional)
└── config.json            # shared session settings (optional)
```

The [knowledge guide](docs/knowledge-guide.md#knowledge-store) and
[session guide](docs/session-guide.md#where-things-live) list every location
and the setting that moves it.

## Install

Hippocampus runs on macOS and Linux (and WSL). It needs Python 3.9 or newer
(3.11 or newer for rules set-up) and `git`; the Claude Code hooks also need
`jq`. From a checkout or a signature-verified release, run the installer for
each tool you use:

```bash
python3 scripts/install-claude.py   # Claude Code plugin, skills and hooks
python3 scripts/install-codex.py    # Codex skills and trusted hooks
```

Then run set-up with your agent:

| Tool | How you invoke a skill | Set-up |
|---|---|---|
| Claude Code | `/hippocampus:<skill>`, for example `/hippocampus:research-topic` | `/hippocampus:hippocampus-set-up` |
| Codex | The skill name, for example `Use checklist` | `Use hippocampus-set-up` |

Set-up explains the storage model, asks whether you want a wiki, configures
your knowledge root, checklist bindings and rule targets, and shows every change
before it writes. You can configure sessions alone and add knowledge later.
Both installers undo themselves with `--uninstall`; your handoffs, profiles and
knowledge root stay.

[INSTALLATION.md][6] covers prerequisites per platform, the signed-release
route and its fingerprint, manual configuration and verification.
[docs/session-installation.md](docs/session-installation.md) covers the
installed layout for each tool, shared configuration and uninstall.

## Coming from continuity

Continuity, the earlier session package, is now part of Hippocampus. It was
never released, so there is no automatic migration:

1. Uninstall continuity from each tool. The Hippocampus installers refuse to
   run while it is present and print the commands to remove it.
2. Install Hippocampus as above.
3. Move your checklist profile to `~/.config/hippocampus/checklist-profile.md`
   and delete its `knowledge` and `lessons` binding blocks. Those steps are now
   built in. Replace `record` with per-kind `record_writes`; keep `persist` and ask.

Moving routing, configuration and saved handoffs is optional; the steps are in
[MIGRATION.md](MIGRATION.md#manual-continuity-cutover).

## Built on

Hippocampus stands on tools others built: [NotebookLM][8] for source-grounded
synthesis, [notebooklm-py][4] for agent access to it, [yt-dlp][5] and
[Defuddle][9] for gathering sources, Apple Speech for transcription, and
[Obsidian][7] for browsing. None of them is bundled except the Apple Speech
transcriber, and each is optional or detected at runtime; see
[external and optional integrations](docs/knowledge-guide.md#external-and-optional-integrations).
What Hippocampus adds is the part that makes them one system: the contracts for
how evidence becomes durable knowledge, reports that end in decisions instead
of summaries, approval before every change, and handoffs and rules that carry
what was learned into the next session.

I built it for my own work, mostly to learn about AI and to improve the agents
I run. A typical use: after a video or podcast, I hand over the URL and ask it
to dig into the ideas that caught my attention and how they apply to what I'm
building. The result lands in the wiki, and the lessons land in my rules.

## Reference

- [Knowledge guide](docs/knowledge-guide.md): knowledge root, research reports
  and distribution, meetings, wiki compile and audit, rule composition,
  integrations, example requests.
- [Session guide](docs/session-guide.md): session skills, hooks, handoff and
  checklist files.
- [Sweep](docs/sweep.md): abandoned-session sweeps and act mode.
- [Glossary](docs/glossary.md): record, handoff, checkpoint, wrap, slot and the
  rest of the vocabulary.
- [INTERFACE.md](INTERFACE.md): contracts for adapter and profile authors.
- [Karpathy-wiki contract][2] and [research artifact contract][3].
- Architecture maps:
  [knowledge](docs/architecture/runtime.html) and
  [sessions](docs/architecture/session/runtime.html).
- [MIGRATION.md](MIGRATION.md): upgrades between releases.

`research-absorb`, `research-to-wiki`, `vault-compile` and `vault-audit` remain
as compatibility names that hand off to `absorb`, `wiki-compile` and
`wiki-audit`.

Apache-2.0. See [LICENSE](LICENSE).

[1]:	https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f
[2]:	contracts/karpathy-wiki.md
[3]:	skills/absorb/references/artifact-contract.md
[4]:	https://github.com/teng-lin/notebooklm-py
[5]:	https://github.com/yt-dlp/yt-dlp
[6]:	INSTALLATION.md
[7]:	https://obsidian.md
[8]:	https://notebooklm.google.com
[9]:	https://defuddle.md
