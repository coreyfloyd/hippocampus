# Knowledge guide

Reference detail for the knowledge half of Hippocampus: the knowledge root,
research artifacts and their distribution, meetings, the wiki, rule
composition and optional integrations. The [README](../README.md) introduces
the product; the [session guide](session-guide.md) covers sessions, handoffs
and the wrap checklist.

## Knowledge store

The wiki is optional. A configured root contains three canonical directories,
plus a fourth for compiled knowledge when `hippocampus-set-up` configures
the wiki as enabled:

```text
<knowledge-root>/
├── raw/       # source material and provenance
├── output/    # research artifacts and audit reports
├── docs/      # AI-maintained operation history and durable decisions
└── wiki/      # compiled synthesis, topic indexes, and master index (only when the wiki is enabled)
```

`raw/`, `output/`, and `docs/` are always present. `wiki/` and its two
profile fields exist only when the wiki is enabled; declining it at setup
skips the wiki folder, its profile fields, wiki routing in absorption plans
and knowledge captures, and the `wiki-compile` / `wiki-audit` skills,
which refuse to run without it. The wiki can be turned on or off later
through `hippocampus-set-up` alone. The directory names are part of the
public [Karpathy-wiki contract][2]. The organization of the `wiki/`is
customizable, but relies on internal wikilinks for traversal by AI and
wikilink-aware tools.

The `raw/` subfolders express roles: `raw/research/` is the default for extracted
external evidence; `raw/derived/` retains excluded generated reports/synthesis.
Transcript intake and retained-source destinations follow local policy (for
example `raw/inbox/` and `raw/archive/meetings/`). These optional subfolders are
not new required topology; retained transcripts remain primary evidence.

### Index files (wiki enabled)

The wiki maintains three kinds of Markdown index so an agent (or you) can find the
right article without scanning every file. This keeps context small and searches
fast as the wiki grows:

- `wiki/hot.md` — the recent-context entry point. Lists the latest and most
  active content, so a session starts from what changed instead of the whole wiki.
- `wiki/<topic>/_index.md` — one per topic folder, listing that topic's articles.
- `wiki/_master-index.md` — the top-level map of every topic.

The skills update these indexes automatically as articles are created or changed,
so the fast-search entry points stay current without manual upkeep.

### Audit Tracking

In addition, the system writes records to help agents understand how to operate on the knowledge system itself, supporting your own custom workflows, including:
- an operation log,  `docs/log.md`;
- a decision log, `docs/DECISIONS.md`.

The installer validates this structure but does not create it.

## How the skills fit together

### Quick inline research

```text
question
  -> quick-research or dev-research
  -> cited answer in the conversation
```

Inline research does not automatically create a notebook, file, or knowledge
capture task.

### Durable research and distribution

`research-sources` and `research-topic` share the [research artifact contract][3]. Every artifact
is one Markdown file in `output/` with the same documented structure:

```text
output/2026-08-28-example.md
├── Question and Scope   # two required subsections
│   ├── Question         # the decision, target, or question addressed, and scope
│   └── Answer           # answer first, then confidence and what would change it
├── Source Summary       # what the sources actually say, in enough detail to judge
├── Source Assessment    # whether those sources can be trusted
├── How to Absorb        # what the report exists to enable (below)
├── Evidence Record      # one entry per source, plus what was searched and skipped
├── Evidence Gaps        # what remains unanswered, and the follow-up that closes it
└── Execution Appendix   # machine-actionable rows for absorb
```

The Answer is the first thing a reader judges and must stand without the
later sections. A complete artifact in this shape, sanitized from a real
session, is at [docs/examples/2026-09-03-fable-5-1-model-routing.md][10],
and the [public NotebookLM][11] it was grounded in is open for inspection.

Before destinations are proposed, **How to Absorb** inventories the user’s
intended outcomes and marks each satisfied with evidence, proposed, deferred
with an outstanding decision, or declined. Cover personal application/actions,
maintained documents, wiki knowledge when the objective calls for
them. Compilation alone does not satisfy an application request; preserve
remaining outcomes when only part of a broader goal is approved.

The summary and assessment sections feed the absorption plan, whose items are
split by what the result touches: **Actions** — anything that is not a document,
such as installing a skill or changing a workflow; **Wiki Additions** — the
compiled knowledge base only; and **Document Updates** — context files, project
briefs, standing documents, repository docs. Retention/discard decisions
use their explicit shared row kinds. Every item states what exists now,
the change, why it matters, and how much to trust it, with options and a
recommendation when a genuine choice exists. Nothing may be merely staged:
absorb it or discard it. Adoption decisions about third-party work require
real-world usage and sentiment evidence, not just the source itself.
The artifact is durable enough to support review and execution, but it is
coordination material while pending; completed absorption retains it as an excluded reference record.

If an approved row belongs in the wiki, `absorb` reuses already-retained
primary source text and provenance, or stages new selected external evidence
under `raw/research/`, then invokes
`wiki-compile` on that curated subset. A staged source is the extracted
source text under provenance frontmatter; a summary alone or a NotebookLM
source id is not a staged source. The research report itself is never raw
compiler input.

### Deliverables that are not absorbed

`feature-research` and `feedback-research` sit outside that lifecycle. Neither
uses the artifact contract and neither document goes through `absorb`; each
writes a document with its own structure, defined in its own SKILL.md. Only an
optional Wiki candidates table, described below, reaches `absorb`.

`feature-research` produces a **design input document**. It feeds the feature's
design and spec, and is written into the project repo beside the requirements
it answers:

```text
# Feature research: <feature>
├── Comparison           # per product: how it works, strengths, complaints
│                        # plus a requirement x product matrix for 3+ products
├── Common patterns      # what most products do, and why it works
├── Novel approaches     # unusual approaches worth knowing about
├── Table stakes         # what users expect based on market norms
├── Platform conventions # HIG, Material, or other platform guidance
├── Implications         # what this suggests for your design
├── Sources              # ID, product, type, link, date, version observed
└── Wiki candidates      # optional: reusable public findings for the wiki
```

Every claim cites a source row by ID.

`feedback-research` produces a **decision memo**. It answers one adopt, buy,
upgrade, switch, or wait question, and is read once and then retained as a reference, or filed
with the project it serves:

```text
# <subject> — <decision>
├── Bottom line          # the verdict, tied to your decision context
├── Hard constraints     # requirements and compatibility gates, or "none"
├── What people are saying   # recurring themes, dated against the version in scope
├── Recurring issues, ranked # by frequency and severity
├── Communities to watch # the venues worth following afterward
├── Sources              # thread, date, poster's version, how it was read
└── Wiki candidates      # optional: reusable public findings for the wiki
```

**Communities to watch** always closes the body before the sources, because
surfacing the right venues is a primary output rather than a footnote.

When either deliverable, or a `dev-research` answer persisted to a file, cites
public sources whose findings are reusable outside the project, it ends with a
`## Wiki candidates` table and reports it as a proposed distribution. After
approval, `absorb` stages those sources and compiles them; the project document
stays where it is and is never compile input. See
[`skills/absorb/references/wiki-candidates.md`](../skills/absorb/references/wiki-candidates.md).

### Capture knowledge from a conversation

```text
current conversation
  -> knowledge-capture inventory and disposition proposal
  -> approval
  -> discard | retain output | capture provenance | preserve synthesis | compile
```

Legend: arrows show the proposed handoff sequence; approval is the control boundary before authorized dispositions.

Use this path for knowledge created or discussed in the current conversation. Use `absorb` instead when a durable research artifact already exists.

### Meeting configuration and source handling

The three inputs are independent and configurable: `meeting_transcript_source`
selects a transcript provider or retrieval route, `meeting_event_source` selects
optional calendar context, and `meeting_note_path` is an optional default local path or Google Docs link; a supplied note path/link overrides it for that meeting. `{date}` is optional, and notes need not share a directory. The capture distinguishes source evidence from coaching interpretation and participant intent from later outcomes. Research and meeting reviews share [Insights & Highlights](../skills/absorb/references/insights-highlights.md): selected useful specifics with provenance, dispositions and verified landing. Knowledge, document and action uses remain optional. Calendar events and notes are read-only context; unavailable inputs are reported. See [meeting capture](../skills/meeting-capture/SKILL.md).

Transcript intake and retained-source destinations come from local policy or overrides in the profile body. Pending authorized work stays in intake; completed captures retain originals as primary evidence and repair source links. Installation does not relocate existing material.

`meeting_record_folder` selects a folder within the knowledge root; its default
is `meetings/`. `meeting_record_template` selects a Markdown template; its default
is the bundled [minimal example](../skills/meeting-capture/assets/meeting.md).
Override the template for one capture when needed. Relative template paths resolve
from the knowledge root and absolute template paths are accepted. Explicitly
missing or invalid templates fail clearly. Validation creates no folders or records.
Repeated capture finds the meeting by source identity and preserves its path, user
edits and prior receipts. Coaching sections are optional.

New meeting records use a date plus a meaningful meeting title, person or
subject (for example, `2026-10-09-public-contract-review.md`). Provider names
and kind suffixes such as `-transcript` belong in source provenance metadata,
not automatic title decoration. Retained transcripts use a meaningful subject;
a transcript and its record may share a filename in different folders.
Identity lookup reuses existing records and preserves user edits and paths,
even when a title changes on retry. Different meetings with the same title get
a stable identity suffix; filing refuses to overwrite different source content.

A capture report distinguishes maintained document/project updates, wiki updates
(when enabled), and actions. Targets and folder names come from the profile.
Local policy can add **custom classes** with declared searches, required fields
and execution routes under the same approval and receipt rules; see the
[opt-in worked example](examples/capture-writing.md).

### Compile and audit an existing source collection

Choose a coherent subset of primary sources and authorize its compilation.
`wiki-compile` creates or updates articles, indexes and source dispositions.
An optional `wiki-audit` then writes a ranked report without changing the wiki.
This direct route needs no generated meeting record or research artifact.

Compilation is never a sweep of every uncompiled file in `raw/`. It reads the
selected raw sources before existing wiki synthesis, drafts claims, then checks
nearby articles for real tensions and gaps instead of silently blending
incompatible assertions.

### Rules and memory configuration

```text
setup
  -> inspect each tool: installed?, instruction file, owner, memory state, memory store
  -> plan: standard | thin preset, editable per tool
  -> review the complete mutation list and its approval fingerprint
  -> approval
  -> apply: compose rule targets | change listed memory settings | record the profile rules section
```

Legend: arrows show the set-up sequence; approval is the control boundary, and
`apply` refuses when the recomputed plan no longer matches the approved fingerprint.

Your agent rules can live in the knowledge root beside the rest of your
knowledge, as plain Markdown, and be composed into each tool's own instruction
file. Set-up uses two documents: `context/rules.md` holds rules for every tool,
and `context/development-rules.md` holds rules for development work under an
optional development root. Claude Code, Codex and OpenClaw are the supported
tools; a tool that is not installed gets no row in the plan.

Set-up first reports each tool's state: its default user instruction file
(`CLAUDE.md` in the Claude Code home, `AGENTS.md` in the Codex home or the
OpenClaw workspace), whether that
file exists and who owns it, the native memory setting, and the memory store's
location and file count. It then offers two editable starting points:

| Preset     | Rules target per tool                       | Memory per tool                          |
| ---------- | ------------------------------------------- | ---------------------------------------- |
| `standard` | `none`: no user instruction file is written | `native`: the detected setting is kept   |
| `thin`     | the tool's default instruction file         | `off`: the tool's documented off setting |

Any row can be changed before approval. The plan lists every file that will
change, including each memory setting with its current and proposed value, and
nothing outside that list is written. A decline writes nothing.

A target that carries the composer's generated header is rewritten in full.
In a file you wrote yourself, composition changes only one marked block and
leaves the rest of the file as it was. Claude Code targets import the documents
by path; Codex and OpenClaw targets receive their content. With a development
root, `CLAUDE.md` and `AGENTS.md` at that root carry the development rules.
Every target is checked before any is written, so a failed check leaves all of
them untouched. After editing either document, run set-up again: the new plan
lists each target whose composed content changed.

The existing composer also supports read-only drift checks:

```sh
python3 scripts/compose_rules.py refresh --config /path/to/targets.json
python3 scripts/compose_rules.py check --config /path/to/targets.json
python3 scripts/compose_rules.py surfaces --source /path/to/rules.md
```

`check` exits with an error for missing or changed target content and writes
nothing. `surfaces` reads the **Produced surfaces** mapping in the improve-harness
routing file (`--routing`, then `HIPPOCAMPUS_ROUTING`, then
`${XDG_CONFIG_HOME:-~/.config}/hippocampus/routing.md`). Its JSON result names
canonical sources and produced paths with regeneration commands; querying a
produced path traces back to its source. An absent mapping or explicit `[]`
produces no surfaces. Mapping lookup never runs commands. After editing a source,
regenerate its listed surfaces and check for drift; edit the source rather than
the generated file. See the routing block format in
[improve-harness](../skills/improve-harness/SKILL.md#produced-surfaces-routing-contract).

Set-up never deletes a memory store or any file in it; a nonempty store is
reported for you to act on. `native` changes no memory setting. When a tool's
memory directory or workspace is customized, set-up describes it, flags an
`off` choice and proposes no change. The approved choices are recorded in the profile's optional
`rules` section, described in the [Karpathy-wiki contract][2]. A profile
without that section stays valid and uses the `standard` preset.

## Architecture

[`docs/architecture/runtime.html`](architecture/runtime.html) maps research
and meeting capture to shared absorption, local document/task workflows,
selected-source compilation and separate record/source retention. Its source is
[`runtime.architecture.json`](architecture/runtime.architecture.json), pinned
to the implementation commit. Read the relevant map before structural changes,
confirm against the skills and helper, and regenerate the architecture viewer
and public comparison with `uv run --with markdown python scripts/render-public-review.py`.
The architecture SVG preserves the existing viewer; its legend
identifies workflow roles, not deployment status. The runtime
map includes approved setup and its profile; it leaves out inline research, domain-specific deliverables, installation,
release and external provider internals. Earlier review artifacts remain dated
history; this map describes the current candidate.

## Example requests

Natural-language requests work across Agent Skills-compatible clients:

```text
Use quick-research to compare these two services and cite current sources.

Use research-sources to analyze these URLs, identify evidence gaps, and write
the durable artifact proposed by the skill.

Use research-topic to investigate this question deeply, verify the major
claims, and end with the decisions the evidence raises.

Use feature-research to compare how established podcast apps handle this
interaction before we design it.

Use feedback-research to determine whether users consider this release stable
enough to adopt and identify the communities worth following.

Run absorb on output/2026-08-27-example.md. Validate and show me its
existing plan before applying anything.

Use wiki-compile on these three selected files under raw/research/.

Audit the configured wiki with wiki-audit. Do not modify it.
```

## External and optional integrations

- **NotebookLM** is the persistent source and
  synthesis layer used by `research-sources` and `research-topic`. Its
  source-grounded answers and inline citations are what keep this system's
  analysis tied to your evidence rather than a model's training data. Agent
  access is provided by the third-party [notebooklm-py][4] CLI and its
  `notebooklm` Agent Skill, not by Google or this package. `dev-research` also
  uses that CLI when it is available. This package does not install it,
  authenticate it, or validate the integration.
- **YouTube library search** is an optional upstream source-discovery step. A
  separate `youtube` Agent Skill can use the third-party [yt-dlp][5] CLI to
  inspect public playlists or retrieve subtitles, then hand selected URLs to
  NotebookLM. Neither that skill nor `yt-dlp` is bundled or required by this
  package; NotebookLM can index a supplied YouTube URL directly.
- **Defuddle** is optional and detected at runtime. Relevant skills extract
  supplied pages through its hosted endpoint, which needs no install or API key,
  and fall back to native web tools when it is unavailable or a page is blocked.
  Web search uses the runtime's own search tool; no search service is bundled.
- **Apple Speech** source is bundled under the `transcribe` skill and built on demand.
  The local route requires macOS 26 or later; otherwise the calling workflow
  must use another input route.
- Full Reddit-thread reading used by `quick-research` and `feedback-research`
  follows the authorized browser route in local policy. The bundled Safari helper
  requires an interactive macOS session signed into Reddit; other configured
  browser tools are valid. Without a route, report snippet-only coverage. Other
  sources continue through available web tools.
- **Obsidian** is not required to run the system or to read the wiki, but it
  is the practical way for a person to browse it. Wiki articles link to each
  other with `[[wikilinks]]`, which GitHub, VS Code, and most Markdown viewers
  show as plain text rather than links. Any wikilink-aware client works;
  Obsidian is the one this project names and adds backlinks and graph views.


[1]:	https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f
[2]:	../contracts/karpathy-wiki.md
[3]:	../skills/absorb/references/artifact-contract.md
[4]:	https://github.com/teng-lin/notebooklm-py
[5]:	https://github.com/yt-dlp/yt-dlp
[6]:	../INSTALLATION.md
[7]:	https://obsidian.md
[10]:	examples/2026-09-03-fable-5-1-model-routing.md
[11]:	https://notebook.google.com/notebook/6df011dc-7391-4399-919f-345b6067e29f
[8]:	https://notebooklm.google.com
[9]:	https://defuddle.md

