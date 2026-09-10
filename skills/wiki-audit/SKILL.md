---
name: wiki-audit
description: Read-only structural audit of a configured Karpathy-wiki knowledge base. Use when asked to audit the wiki or knowledge base; it checks atomicity, missing pages, hub coherence, structural health, source coverage, tensions, and gaps without resolving them.
---

# Wiki Audit

Validate `~/.config/hippocampus/profile.md` with `../../scripts/validate_profile.py --require-wiki`, resolved relative to this skill, and read the [public Karpathy-wiki contract](../../contracts/karpathy-wiki.md) before auditing. If the profile is missing or invalid, stop and use `hippocampus-set-up`; do not audit another root or choose a fallback report path. If the validator refuses with `--require-wiki` because the wiki is not configured, stop and relay its message verbatim — hippocampus-set-up enables it; this is not a judgment to make by reading the profile yourself. Run only against the configured `knowledge_root`, applying any free-form local policy body only within that root. Produce a ranked report in canonical `output/`; modify nothing.

## When to use

- "audit the wiki", "audit the knowledge base", or "atomicity check"
- After a substantial compile pass
- Before a proposed taxonomy change

The audit is opt-in; it never runs merely because a wiki changed.

## Invariants

- **Read-only:** do not change articles, sources, frontmatter, indexes, or logs.
- **Surface, do not resolve:** findings become proposals; the audit does not split, merge, rename, or create pages.
- **Configured scope:** never inspect or report on content outside the configured knowledge root.
- **Local taxonomy:** apply an explicit local policy if one exists. Otherwise report navigation concerns without prescribing folder names or placement rules.
- **More links, not fewer:** graph health is the primary structural signal; length is secondary.

## Procedure

### 1. Scope

Read the configured session cache and recent operation history. Count articles under canonical `wiki/`, excluding `_index.md` and `_master-index.md`. State the count and the directories in scope before starting.

### 2. Missing-page lint

Find terms mentioned in at least three distinct articles that lack a page. Normalize existing page names, ignore links and code, and distinguish:

- **Wikilink-only candidate:** a stable referent with congruent mentions; backlinks can implicitly define it.
- **Stub candidate:** a stable referent that needs brief disambiguation.
- **Full-page candidate:** conflicting or synthesis-heavy mentions.
- **Verification needed:** an ambiguous phrase or a likely false positive.

Do not create any candidate page.

### 3. Collision and hub checks

Inspect sections with links from at least three distinct source articles. A coherent section with that level of fan-in is a split candidate. For pages with at least five inbound links, sample inbound contexts and report whether they cohere with the page's stated domain. A long page alone is not a split signal; length matters only when it combines with high, section-targeted fan-in.

### 4. Structural health

Report:

- topic folders with a single ordinary article;
- orphan articles, broken and forward wikilinks, and raw-file wikilinks;
- articles over 200 lines without `length_justified:`;
- compiled articles missing `topic:` or `sources:` frontmatter;
- bare mentions of existing pages that should be inline wikilinks;
- unannotated trailing link-dump sections.

Respect local policy for folder taxonomy, entity placement, naming, and atomicity calibration. If none exists, classify these as observations rather than compliance failures.

### 5. Sources, tensions, and gaps

For `raw/research/` and `raw/archive/`, report sources not referenced from wiki `sources:` metadata, excluding derived material and bookmarks. Sample within-folder clusters and hub neighbors for direct contradictions, scope tensions, and term drift. Aggregate existing `## Tensions` and `## Gaps` sections, then identify dependency, source-implied, and structural gaps.

Document sampling coverage. Do not claim the semantic checks are exhaustive unless every applicable article was evaluated.

### 6. Report

Write `output/YYYY-MM-DD-wiki-audit.md` with:

1. scope and summary counts;
2. missing-page, collision, and hub findings;
3. structural and source-coverage findings;
4. tension and gap findings, including sampling coverage;
5. Must / Should / Can priorities and proposed follow-up actions.

Propose an entry for the configured operation log and route actionable wiki-maintenance findings to `wiki_followup_destination`; do not write either. State every proposed file move, split, or taxonomy change for approval. Record no decision directly because the audit is read-only.

## Does not do

- Modify a knowledge base or its operational records
- Create, move, split, merge, or rename pages
- Resolve tensions or gaps
- Invent taxonomy, folder names, or entity-placement conventions
- Auto-commit audit output
