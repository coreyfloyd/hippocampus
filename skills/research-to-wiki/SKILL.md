---
name: research-to-wiki
description: Compile a curated raw source subset into a configured Karpathy-wiki knowledge base. Use for "add this to the wiki" or selected raw research/archive material; not for auditing, session capture, or sweeping all uncompiled raw content.
---

# Research to Wiki

Compile a caller-selected, curated source subset from `raw/` into atomic wiki articles. This skill is deliberately not a raw-backlog sweep: select a coherent subset first, then compile it. It writes wiki content and ingestion tracking; it never substitutes a research report for its underlying source material.

Validate `~/.config/hippocampus/profile.md` with `../../scripts/validate_profile.py --require-wiki`, resolved relative to this skill, and read the [Karpathy-wiki contract](../../contracts/karpathy-wiki.md) before the first pass. If the profile is missing or invalid, stop and use `hippocampus-set-up`; do not stage or compile sources. If the validator refuses with `--require-wiki` because the wiki is not configured, stop and relay its message verbatim — hippocampus-set-up enables it; this is not a judgment to make by reading the profile yourself. Use the canonical directories and apply any free-form local policy body only to that knowledge root. `wiki-audit` remains the read-only quality audit companion.

## Inputs and routing

- Accept a selected subset already in `raw/research/`, `raw/archive/`, or another valid raw location. If sources are already raw, skip staging.
- When an approved research artifact identifies external sources for the wiki, `research-absorb` stages their provenance in `raw/research/` and invokes this skill with only that subset. The artifact itself is not compile input.
- A staged raw file must hold the extracted source text under its provenance frontmatter. A file whose body is only an agent summary, or only a NotebookLM source id, is not compile input: stop and obtain the extraction before compiling.
- When invoked from `research-absorb` or `knowledge-capture`, disposition decisions — topic assignment, approved named referents, page conventions — were already made and approved upstream. Honor them; do not re-derive routing. Re-derive routing only on a direct invocation with no upstream plan.
- When a source set is insufficiently grounded, use `research-sources` in **Improve evidence** mode before compiling. Compile from the evaluated source set, not an unsupported transcript alone.
- Exclude corpora marked `compile_exclude` or `compile_mode: exclude`; route `compile_mode: update` sources through their targeted update workflow.

## Stance

- **Draft from sources first.** Read the raw source and draft before reading existing wiki synthesis; compare afterward to find tensions and gaps rather than anchoring on prior articles.
- **Check for an existing article before creating one.** Search alternate concept names in `wiki/`; merge only when the referent is the same.
- **Write claims, not source summaries.** Attribution belongs in `## Sources`.
- **Quality at compile time.** Apply the wiki 5-signal checklist, atomicity, precise article naming, and dense inline links before marking work complete.
- **Do not create entity or concept hubs unilaterally.** Propose candidates, unless an approved upstream row already authorizes the page.

## Procedure

### 0. Restore workflow context

Read the configured session cache and the recent operation log before selecting
sources. Apply the profile body's local entry formats and wiki follow-up routing
rules from `wiki_followup_destination`.

### 1. Confirm the subset

State each source and why it is included. For every file, confirm the upstream topic assignment (or decide it, on a direct invocation) and whether to skip it (too thin, truncated, off-scope, registry, bookmark, already ingested, or excluded). Do not synthesize during triage.

### 2. Compile each source

1. Read the raw source fully before writing.
2. Create or update the appropriate topic article. Follow the public Karpathy-wiki contract: one concept per article, bullet-forward prose, dense wikilinks, meaningful title, `## Key Takeaways`, and `## Sources` with vault-root-relative paths.
3. Keep ordinary articles at or below 120 lines; document `length_justified:` when substance requires more than 200.
4. After drafting, compare the draft's key claims with the 1-3 closest existing wiki articles. Record real contradictions in `## Tensions` and missing prerequisite knowledge in `## Gaps`; do not blend incompatible assertions.
5. Before merging into an existing article, compare claims first. A conflict becomes a tension, not a silent blend.
6. Update the source's `ingestion_status` and `ingested_at` only after its actual compilation result is known.

### 3. Maintain navigation

Update each touched topic `_index.md`; update `wiki/_master-index.md` when a topic is added or its description materially changes. Search for recurring, load-bearing people or concepts after each topic and surface hub candidates for approval.

### 4. Finish

Report articles created or updated, source dispositions, tensions, gaps, and proposed hubs. After a non-exploratory approved run, update the configured session cache and append an operation entry to the configured operation log. Record approved taxonomy or policy decisions in the configured decision log; route actionable wiki-maintenance follow-ups to `wiki_followup_destination`. Commit the knowledge-base work according to its local rules.

## Special source types

- `kind: registry` — compile links and descriptions, not prose.
- `kind: bookmark` — add a concise reference to the relevant article or index.
- Private sources — paraphrase only and use `draws_from_private: true` on resulting articles.
- Cross-topic source — create distinct topic articles and link them; do not force unrelated concepts into one article.

## Does not do

- Audit the wiki (`wiki-audit`)
- Capture or process current conversation knowledge (`knowledge-capture`)
- Stage sources or execute an artifact distribution plan (`research-absorb`)
- Sweep all uncompiled raw material
- Move or delete raw sources, create unapproved hubs, resolve tensions, or perform unrelated follow-up implementation
