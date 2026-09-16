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

## Optional wiki

The wiki is optional. `hippocampus-set-up` explains both the wiki and the
no-wiki alternative in neutral terms, with no default lean, and can enable or
disable the wiki later without disturbing the rest of an existing
configuration. `research-to-wiki` and `wiki-audit` gate on the profile
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
not a requirement. Research-derived follow-ups use the artifact follow-up
destination. The package must not infer that the two destinations are the
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

Humans select a coherent raw-source subset. `research-to-wiki` compiles only
that subset, never a backlog sweep. A selected-subset manifest records each
source's root-relative path, original provenance, and requested disposition.
Reports are not raw compiler input. Sources marked `compile_exclude` are
excluded; `compile_mode: update` requires its targeted update workflow.

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
