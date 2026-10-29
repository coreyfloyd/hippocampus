# Karpathy-wiki contract

## Topology

A knowledge root always contains the canonical directories `raw/`, `output/`,
and `docs/`. It contains `wiki/` only when the profile records the wiki as
enabled, which is the default. A valid profile resolves whichever canonical
directories apply beneath the canonicalized root. Their names are part of the
supported Karpathy-wiki contract, not per-installation topology settings.

The profile's YAML frontmatter is the portable, validated root and workflow-state
contract.
After the closing frontmatter delimiter, it may contain a free-form local policy body. Skills that consult the profile read the whole file and apply that
body only to the configured knowledge root. The body can declare a personal
taxonomy, local operations conventions, or optional source-library routing; it
is deliberately local configuration, not package content.

## Optional rules profile section

The optional `rules` frontmatter section records the choices approved through
`hippocampus-set-up`; it is the only rules configuration that set-up and the
composer read. Its `preset` is `standard` or `thin`. `cross_tool_document` and
`development_document` name the two rules documents relative to the knowledge
root. An optional absolute `development_root` lets set-up describe the delivery
of development rules. Each `tools` row names one supported tool (`claude-code`, `codex`, or
`openclaw`), its `rules_target` (a file location or `none`), and its `memory`
value (`native` or `off`). A profile without this section remains valid and
uses the standard preset.

## Optional wiki

The wiki is optional. `hippocampus-set-up` explains both the wiki and the
no-wiki alternative in neutral terms, with no default lean, and can enable or
disable the wiki later without disturbing the rest of an existing
configuration. `wiki-compile` and `wiki-audit` gate on the profile
validator's `--require-wiki` option and relay its refusal verbatim; neither
skill judges wiki state by reading the profile itself. A wiki-disabled profile
has no `wiki/` directory, no `hot_file`, and no `wiki_followup_destination`,
and no Wiki Additions class appears in any research artifact or
knowledge-capture proposal it produces.

Disabling the wiki never deletes or modifies an existing `wiki/` directory or anything in it; only `hippocampus-set-up`'s own enable/disable conversation changes the profile fields, and only after the user approves.

## Navigation and links

Topic folders are optional navigation units, not a prescribed taxonomy. A
knowledge base may add a topic folder only when its local policy or a human
approval calls for one; each used topic folder has an `_index.md`, and
`wiki/_master-index.md` describes the topic inventory. Articles are flat within
a topic folder and connect across topics through links.

The contract uses Obsidian-style wikilinks (`[[title]]` and
`[[path/title]]`) as a portable Markdown convention. The files do not require
the Obsidian application, but clients that do not understand wikilinks will not
provide Obsidian's native link resolution or graph view.

## Workflow state and routing

Every profile declares root-relative files for an operation log and decision
log, plus an artifact follow-up destination. When the wiki is enabled, the
profile also declares a session cache file (`hot_file`) and an independent
wiki follow-up destination; a wiki-disabled profile has neither. At the start
of a wiki operation, read the session cache and recent operation history.
After an approved non-exploratory compile, update the session cache and append
an operation entry. Record an approved taxonomy or policy decision in the
decision log. Route an actionable wiki-maintenance follow-up according to the
configured wiki follow-up destination; a roadmap is one possible task system,
not a requirement. Source-derived actions, including meeting tasks and research
follow-ups, use the artifact follow-up destination and its local owner/project rules. The package must not infer that the two destinations are the
same.

The profile body may define the precise entry formats and routing distinctions.
An audit remains read-only: it proposes its operation entry and wiki follow-up
routes, then waits for the authorized writer.

## Optional integrations

Defuddle's hosted extraction endpoint and local Apple Speech are
runtime-detected optional integrations, not profile capabilities. A skill
checks whether its relevant integration is available at the time of use. When
the extraction endpoint is unavailable or a page is blocked, research uses
native web tools and reports that fallback. When local Apple Speech is
unsupported or unavailable, `transcribe` selects or reports an appropriate
alternative input route. A profile never promises that either integration is
installed or permitted.

## Attribution

This package is an independent implementation inspired by
[Andrej Karpathy's LLM Wiki gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).
It adds its own portable profile, installation, research, and audit contracts.

## Curated compilation

Humans select a coherent raw-source subset. `wiki-compile` compiles only
that subset, never a backlog sweep. A selected-subset manifest records each
source's root-relative path, original provenance, and requested disposition.
Reports are not raw compiler input. Sources marked `compile_exclude: true`,
`compile_mode: exclude` or `use: artifact` are excluded; `compile_mode: update`
requires its targeted update workflow. Absorption status does not imply ingestion.

The compiler reads selected raw sources and drafts before reading existing wiki
synthesis. After drafting, it compares the closest existing articles and records
actual tensions or gaps rather than silently merging incompatible assertions.
When invoked with an approved distribution plan, disposition decisions made
upstream — topic assignment, named referents, page conventions — carry into the
compile; the compiler does not re-derive them. It uses
root-relative `sources:` paths, maintains affected topic indexes and the master
index, and records the final source disposition only after the result is known.

## Audit

`wiki-audit` is read-only. It records its scope and reports missing pages,
atomicity/collision candidates, link and source coverage, tensions, and gaps.
It cannot modify articles, raw sources, frontmatter, indexes, or operation logs.

## What is enforced and what is instructed

Most checks in this contract are agent instructions: the skills tell the agent
what to verify, and nothing outside the agent re-checks it. `wiki-audit` is one
of them; no deterministic structure checker ships yet.

Code enforces less, and only in absorption. `skills/absorb/scripts/distribution.py`
locks the distribution record, replaces it atomically, ties approval to a hash of
each row's scope, verifies retained source files by SHA-256 before use, and
requires read-back before a write with an uncertain result is retried.

Two limits follow. Recording where a source came from is provenance; it is not
evidence that any claim drawn from it is accepted, and this contract keeps no
claim-level records. A distribution receipt confirms one approved row's write; it
does not make a multi-file change atomic, and editors or other writers do not
honor the record lock.


## Capture and shared absorption

Meeting capture creates one template-driven Markdown record directly in the
configured meeting folder (default `meetings/`); completed records stay in place.
Raw transcripts use a separate local-policy intake/archive lifecycle. Pending
routes keep intake; complete/declined routes permit filing with content and link
verification. Ingestion describes compilation, not whole-record completion.
Research artifacts retain their output-to-raw/derived lifecycle and remain excluded
from primary compilation. `absorb` owns shared source-linked authorized rows,
confirmed task/document/custom-class receipts and retry behavior. Custom headings do
not remove provenance or approval requirements. See the package's shared
[distribution contract](../skills/absorb/references/distribution-contract.md).

`research-absorb`, `research-to-wiki`, `vault-compile` and `vault-audit` are
compatibility entry points to absorb, wiki-compile and wiki-audit. Direct authorized
compilation remains supported without a generated artifact. Local modes,
thresholds, taxonomy, page conventions and coverage remain policy inputs.
Custom proposal classes are opt-in local policy declarations with a name,
searches, required fields and workflow or destination. When none is declared,
propose none. Apply the same source attribution, reuse limits, authorization,
receipts and read-back as built-in routes. Missing writable routes keep candidates
in the meeting/research artifact; authored prose and publication remain separate
user-controlled actions.

## Optional meeting profile fields

Profile version 4 accepts independent `meeting_transcript_source` and
`meeting_event_source` provider/retrieval instructions, plus `meeting_note_path`
as an optional local path or HTTPS Google Docs default. Each can be `disabled`.
Absent transcript settings use supplied/available sources; absent event and note
settings skip lookup but still permit explicitly supplied inputs. A per-meeting
note overrides the default; `{date}` in a local default is optional.
`meeting_record_folder` defaults to root-contained `meetings/` and may name a
not-yet-created directory. `meeting_record_template` defaults to the packaged
minimal Markdown template; an explicit template must be an existing nonempty
Markdown file, root-relative or an explicit absolute path. Validation creates
no folders or records. Published version-4 profiles remain valid unchanged.
Records and retained transcripts use meaningful titles/people/subjects; provider
and kind are provenance metadata. Stable identity, collision safety, user edits
and an existing record’s path survive retries and title changes.

## Raw source locations and metadata

`raw/` is canonical; its subfolders describe roles, not required topology.
`raw/research/` is the default for extracted external research evidence;
`raw/derived/` retains completed generated research artifacts and reusable
synthesis, excluded from primary compilation. Transcript intake and retained
primary-source archives are resolved from local policy: `raw/inbox/` and
`raw/archive/meetings/` are examples. An “excluded raw archive” means derived
material with exclusion metadata, not every source under `raw/archive/`.
Retained transcripts remain primary evidence. Setup does not require these
subfolders or relocate existing sources.

| Metadata | Meaning |
|---|---|
| `compile_exclude: true` | Legacy explicit exclusion from compilation |
| `compile_mode` | `exclude` skips compilation; `update` uses the local targeted-update workflow; absent means ordinary selected-source compilation |
| `use: artifact` | Generated reference artifact, never primary evidence |
| `status: absorbed` | Every authorized distribution row completed or was explicitly declined; independent of compilation |
| `absorbed_at`, `archived_from` | Absorption timestamp and original root-relative artifact path; preserved on retention |
| `ingestion_status`, `ingested_at` | Actual compiler disposition (for example ingested, skipped or failed) and timestamp, recorded after its result is known; never overall capture completion |
| `kind` | Raw-source type: transcript, registry (links/descriptions), bookmark (concise reference), or another locally defined type; distinct from distribution record/row kinds |
| `id`, `provider`, `coverage`, `sha256` | Stable source identity, provenance provider, complete/partial/unavailable coverage and local content digest in the distribution block |

Preserve source metadata and original bytes when filing. Generated record blocks
use their own versioned schema in the shared distribution contract. Title changes
never redefine source or record identity, and retaining a source does not turn it
into an excluded synthesis.
