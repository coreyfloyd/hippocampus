# Hippocampus

`Hippocampus` is an opinionated research and knowledge system for Claude Code and Codex. It is a set of Agent Skills that cover quick in-chat research, durable research reports, updates to existing documentation, and an optional curated wiki in the style of Karpathy's LLM wiki. It works from documents, websites, videos, or audio such as podcasts.

Whatever the source, getting an answer out of it is only part of the work. You still have to judge the evidence, decide what applies to your situation, and carry the result into your notes, plans, or projects. That last step is easy to skip, and the answer stays behind in an old chat. Hippocampus keeps the evidence attached to the decision it informed, so you can see why you reached a conclusion, what is still uncertain, and what you meant to do next. When you learn more, you can revisit the decision without redoing the research.

![A broad question or selected sources move through Question, Answer, and Action, then into documents, follow-up work, an optional wiki, or a deliberate discard.](docs/images/question-answer-action.svg)

Every piece of research moves through the same three stages:

1. **Question** names the decision and scope, and identifies any evidence you
   are starting with.
2. **Answer** grounds the result in cited evidence, assesses the sources, and
   makes gaps visible.
3. **Action** gives the result a terminal disposition: use it, integrate it into
   documents, file follow-up work, compile selected sources into an optional
   wiki, or discard it and close the loop.

**Everything the system stores is plain Markdown on your disk.** Research artifacts, wiki articles, indexes, and operation logs are `.md` files in one folder you choose. Markdown is a format AI reads and writes well, and plain files keep your work on your own computer instead of in someone else's service. There is no database and no proprietary format. You can read and edit the files in any editor or on a Git host, version-control them, and keep them after the conversation that produced them is gone. Following the links between wiki articles needs a client that understands `[[wikilinks]]`, such as [Obsidian][7]. The same files are the AI's working set and yours.

I built Hippocampus for my own research, mostly to learn about AI and improve the AI systems I run. One of my favorite ways to use it is after a YouTube video or a podcast. Rather than take notes while I listen, I hand it the URL afterward and ask it to dig into the ideas that caught my attention and help me work out how they might apply to what I'm building.

Substantial research is grounded in **Gemini Notebook** (Google's product
formerly named NotebookLM). This is a deliberate design choice, not just a
convenience. Gemini Notebook answers only from the sources you give it and cites
the exact passage behind every claim, instead of blending in a chat model's
training data or opinions. Analyzing your evidence there keeps the synthesis
tied to what your sources actually say, with far less outside influence and far
less room for confident invention. `research-sources` and `research-topic` build
their artifacts on top of that grounded layer.

After installation, start with `hippocampus-set-up`. It walks you through the
knowledge-store structure, local policy, and follow-up routing, then shows the
complete proposed configuration before creating or changing anything.

The system stands on excellent tools others built — [Gemini Notebook][8] for source-grounded synthesis, [notebooklm-py][4] for agent access to it, [yt-dlp][5] and [Defuddle][9] for source gathering, Apple Speech for transcription, and [Obsidian][7] for browsing the result — and the wiki design is inspired by [Andrej Karpathy's LLM Wiki gist][1]. What `Hippocampus` contributes is the system that makes them work as one: the contracts that define how evidence becomes durable knowledge, the decision discipline that makes every report end in choices you can act on rather than a summary you file away, and the lifecycle guarantees that ensure nothing you research is lost, orphaned, or left half-filed. The tools gather and ground the evidence; this system determines what happens to it.

## Research skills

There are three general-purpose skills to get most research questions started:

| Skill              | Use it when                                                                                         | Result and next step                                                                                            |
| ------------------ | --------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| `research-quick`   | You need a cited answer to a general question.                                                      | Returns findings inline. No notebook or artifact workflow.                                                      |
| `research-sources` | You already have URLs, files, media, a source collection, or a named target to analyze.             | Produces a source-grounded artifact ending in the decisions it raises. Review them, then use `research-absorb`.   |
| `research-topic`   | You need substantial topic-first research, persistent sources, gap filling, and claim verification. | Produces a Gemini Notebook-backed artifact ending in the decisions it raises. Review them, then use `research-absorb`. |


In addition, there are three research skills for specific domains:

| Skill               | Use it when                                                                                                     | Result and next step                                                                                     |
| ------------------- | --------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| `research-feature`  | You need competitor UX, established patterns, user expectations, or platform conventions before feature design. | Produces a design input document filed with the project, beside the requirements it answers. Not absorbed. |
| `research-feedback` | An adoption, purchase, upgrade, or wait decision depends on current community experience.                       | Produces a decision memo with communities to watch. Read it, act, delete it (or file it with the project it serves). Not absorbed. |
| `research-dev`      | You are investigating a bug, API behavior, library, or implementation approach.                                 | Returns diagnoses, competing explanations, and sources inline.                                           |


## Knowledge Distribution & Follow Up skills

These skills help you get research filed where it belongs.

| Skill               | Use it when                                                                                             | Result and next step                                                                                                                     |
| ------------------- | ------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `research-absorb`   | You created a research artifact and you are ready to move the knowledge into permanent locations.       | Executes the approved plan, records a terminal disposition for every row, then deletes the completed artifact.                           |
| `knowledge-capture` | Useful sources or synthesis exist in the current conversation and need a complete disposition proposal. | Inventories conversation knowledge, asks for approval, then performs only the approved captures. It does not process research artifacts. |

## Personal Knowledge Curation skills

| Skill              | Use it when                                                              | Result and next step                                                                             |
| ------------------ | ------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------ |
| `research-to-wiki` | A coherent, caller-selected subset of raw sources is ready to compile.   | Creates or updates atomic wiki articles, source status, indexes, and approved workflow records.  |
| `wiki-audit`       | You want a structural and source-coverage review of the configured wiki. | Writes a ranked report in `output/` without changing articles, sources, indexes, logs, or tasks. |

## Knowledge store

The wiki is optional. The system always creates three directories, plus a
fourth for the compiled knowledge base when `hippocampus-set-up` configures
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
and knowledge captures, and the `research-to-wiki` / `wiki-audit` skills,
which refuse to run without it. The wiki can be turned on or off later
through `hippocampus-set-up` alone. The directory names are part of the
public [Karpathy-wiki contract][2]. The organization of the `wiki/`is
customizable, but relies on internal wikilinks for traversal by AI and
wikilink-aware tools.

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
  -> research-quick or research-dev
  -> cited answer in the conversation
```

Inline research does not automatically create a notebook, file, or knowledge
capture task.

### Durable research and distribution

These two skills share the [research artifact contract][3]. Every artifact
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
└── Execution Appendix   # machine-actionable rows for research-absorb
```

The Answer is the first thing a reader judges and must stand without the
later sections. A complete artifact in this shape, sanitized from a real
session, is at [docs/examples/2026-09-03-fable-5-1-model-routing.md][10],
and the [public Gemini Notebook][11] it was grounded in is open for inspection.

The summary and assessment sections feed the absorption plan, whose items are
split by what the result touches: **Actions** — anything that is not a document,
such as installing a skill or changing a workflow; **Wiki Additions** — the
compiled knowledge base only; and **Document Updates** — context files, project
briefs, standing documents, repository docs. Every item states what exists now,
the change, why it matters, and how much to trust it, with options and a
recommendation when a genuine choice exists. Nothing may be merely staged:
absorb it or discard it. Adoption decisions about third-party work require
real-world usage and sentiment evidence, not just the source itself.
The artifact is durable enough to support review and execution, but it is
coordination material rather than a permanent archive.

If an approved row belongs in the wiki, `research-absorb` stages the selected
external sources and their provenance under `raw/research/`, then invokes
`research-to-wiki` on that curated subset. A staged source is the extracted
source text under provenance frontmatter; a summary alone or a NotebookLM
source id is not a staged source. The research report itself is never raw
compiler input.

### Deliverables that are not absorbed

`research-feature` and `research-feedback` sit outside that lifecycle. Neither
uses the artifact contract and neither goes through `research-absorb`; each
writes a document with its own structure, defined in its own SKILL.md.

`research-feature` produces a **design input document**. It feeds the feature's
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
└── Sources              # ID, product, type, link, date, version observed
```

Every claim cites a source row by ID.

`research-feedback` produces a **decision memo**. It answers one adopt, buy,
upgrade, switch, or wait question, and is read once and then deleted, or filed
with the project it serves:

```text
# <subject> — <decision>
├── Bottom line          # the verdict, tied to your decision context
├── Hard constraints     # requirements and compatibility gates, or "none"
├── What people are saying   # recurring themes, dated against the version in scope
├── Recurring issues, ranked # by frequency and severity
├── Communities to watch # the venues worth following afterward
└── Sources              # thread, date, poster's version, how it was read
```

**Communities to watch** always closes the body before the sources, because
surfacing the right venues is a primary output rather than a footnote.

### Capture knowledge from a conversation

```text
current conversation
  -> knowledge-capture inventory and disposition proposal
  -> approval
  -> discard | retain output | capture provenance | preserve synthesis | compile
```

Use this path for knowledge created or discussed in the current conversation.
Use `research-absorb` instead when a durable research artifact already exists.

### Compile and audit an existing source collection

```text
caller-curated raw subset
  -> research-to-wiki
  -> wiki articles + indexes + source dispositions + workflow state
  -> wiki-audit (optional, read-only)
  -> ranked audit report in output/
```

Compilation is never a sweep of every uncompiled file in `raw/`. It reads the
selected raw sources before existing wiki synthesis, drafts claims, then checks
nearby articles for real tensions and gaps instead of silently blending
incompatible assertions.

## Example requests

Natural-language requests work across Agent Skills-compatible clients:

```text
Use research-quick to compare these two services and cite current sources.

Use research-sources to analyze these URLs, identify evidence gaps, and write
the durable artifact proposed by the skill.

Use research-topic to investigate this question deeply, verify the major
claims, and end with the decisions the evidence raises.

Use research-feature to compare how established podcast apps handle this
interaction before we design it.

Use research-feedback to determine whether users consider this release stable
enough to adopt and identify the communities worth following.

Run research-absorb on output/2026-08-27-example.md. Validate and show me its
existing plan before applying anything.

Use research-to-wiki on these three selected files under raw/research/.

Audit the configured wiki with wiki-audit. Do not modify it.
```

## External and optional integrations

- **Gemini Notebook** (formerly **NotebookLM** — Google renamed it in July 2026;
  the CLI and skill below still carry the old name) is the persistent source and
  synthesis layer used by `research-sources` and `research-topic`. Its
  source-grounded answers and inline citations are what keep this system's
  analysis tied to your evidence rather than a model's training data. Agent
  access is provided by the third-party [notebooklm-py][4] CLI and its
  `notebooklm` Agent Skill, not by Google or this package. `research-dev` also
  uses that CLI when it is available. This package does not install it,
  authenticate it, or validate the integration.
- **YouTube library search** is an optional upstream source-discovery step. A
  separate `youtube` Agent Skill can use the third-party [yt-dlp][5] CLI to
  inspect public playlists or retrieve subtitles, then hand selected URLs to
  Gemini Notebook. Neither that skill nor `yt-dlp` is bundled or required by this
  package; Gemini Notebook can index a supplied YouTube URL directly.
- **Defuddle** is optional and detected at runtime. Relevant skills extract
  supplied pages through its hosted endpoint, which needs no install or API key,
  and fall back to native web tools when it is unavailable or a page is blocked.
  Web search uses the runtime's own search tool; no search service is bundled.
- **Apple Speech** source is bundled under the `transcribe` skill and built on demand.
  The local route requires macOS 26 or later; otherwise the calling workflow
  must use another input route.
- Full Reddit-thread reading used by `research-quick` and `research-feedback`
  requires an interactive macOS session with Safari signed into Reddit. Other
  sources continue through the available web tools.
- **Obsidian** is not required to run the system or to read the wiki, but it
  is the practical way for a person to browse it. Wiki articles link to each
  other with `[[wikilinks]]`, which GitHub, VS Code, and most Markdown viewers
  show as plain text rather than links. Any wikilink-aware client works;
  Obsidian is the one this project names and adds backlinks and graph views.

## Installation and configuration

See [Installation and configuration][6] for supported platforms and
prerequisites, the installed layout, checkout and signed-release installation,
the guided configuration workflow, manual configuration, and verification
commands.

[1]:	https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f
[2]:	contracts/karpathy-wiki.md
[3]:	skills/research-absorb/references/artifact-contract.md
[4]:	https://github.com/teng-lin/notebooklm-py
[5]:	https://github.com/yt-dlp/yt-dlp
[6]:	INSTALLATION.md
[7]:	https://obsidian.md
[10]:	docs/examples/2026-09-03-fable-5-1-model-routing.md
[11]:	https://notebook.google.com/notebook/6df011dc-7391-4399-919f-345b6067e29f
[8]:	https://notebooklm.google.com
[9]:	https://defuddle.md
