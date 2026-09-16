---
name: research-dev
description: "Quick developer research for implementation or bug diagnosis, with targeted sources, competing explanations, and inline recommendations. Use to research a bug, API behavior, or implementation approach."
---

# Dev Research

Fast, inline research for implementation questions and bug diagnosis. No notebooks, no vault writes, no artifact generation — targeted source scraping, synthesis, and solution proposals delivered in the conversation.

Read `~/.config/hippocampus/profile.md` before checking local knowledge; use only the local-preflight policy it provides. This skill remains an inline response.

For a supplied recording, conference talk, or video demonstration relevant to the diagnosis, invoke `transcribe` to obtain source text before continuing.

Web search uses the runtime's built-in `WebSearch` tool; pass `allowed_domains` to restrict a search to specific sites. Page extraction uses Defuddle's hosted endpoint — `curl https://defuddle.md/<url>` returns Markdown with YAML frontmatter and requires no install or API key. When a source is blocked for either, use native web tools and say so in the report; do not silently reduce source coverage.

## When NOT to Use

- Deep research requiring persistent notebooks and a durable artifact → `research-topic`
- Non-development questions → `research-quick`
- Questions answerable from model knowledge alone (no sources needed)

## Phase 1 — Scope

Ask these questions upfront in a single message. Don't proceed until you have enough to run targeted searches.

1. **Ask for sources first.** "What sites, docs, or repos should I check? Any specific URLs?" User-provided sources are highest signal and are scraped first.

2. **Gather diagnostic context**:
   - The exact error message or stack trace (for bugs)
   - The version of the library/framework/language
   - What has already been tried or ruled out
   - Which library or repo is involved (for GitHub issue searches)

3. **Check local knowledge.** If the local profile defines a knowledge preflight, run it and report useful matches before external research.

4. **Check NotebookLM for existing notebooks when the CLI is installed.** Run `notebooklm list --json` and scan for topic matches. If one exists, query it:
   ```
   notebooklm use <notebook_id>
   notebooklm ask "<research question>"
   ```
   If the notebook already contains a good answer, surface it before running web research. Do not create a notebook for this inline workflow.

## Phase 2 — Web Research

Run searches in parallel where possible.

1. **Extract user-provided sources.** Run `curl https://defuddle.md/<url>` on each URL the user provided. These take priority over anything else you find.

2. **Search GitHub Issues on the relevant repo.** Known bugs and workarounds usually live in the maintainers' issue tracker:
   ```
   WebSearch "<error or symptom> <owner>/<repo>" with allowed_domains: ["github.com"]
   ```
   Or if the repo is known: `gh search issues --repo <owner>/<repo> "<symptom>" --state all --limit 10`

3. **Run targeted dev searches** with 2-3 different angles:
   - Stack Overflow: `"<exact error message>" site:stackoverflow.com`
   - Official docs: `<library> <feature> site:<docs domain>`
   - Blog/implementation posts: `<library> <feature> implementation`

   Use the exact error message text when available; it is far more targeted than a paraphrase.

4. **Check changelog/release notes if version-related.** If the bug may be a regression or fixed in a newer version, scrape the library's CHANGELOG or releases page.

## Phase 3 — Inline Synthesis

Deliver everything inline, structured as:

### Diagnoses & Solutions

Present multiple distinct diagnoses with solution proposals unless the sources clearly establish a single root cause. For each:
- **Diagnosis**: what's causing the problem
- **Solution**: concrete fix or workaround
- **Confidence**: high / medium / low, based on source quality and agreement
- **Source**: which URL(s) support this

If a single fix is obvious and all sources agree, one entry is fine — don't manufacture false uncertainty.

### Source URLs

List every source scraped with a one-line description of what it contributed. Preserve every URL even if it was not quoted directly.

### Source Analysis

- **Correlations**: where multiple sources agree, reinforcing confidence
- **Contradictions**: where sources conflict — state both positions explicitly
- **Gaps**: what the sources don't cover and where to look next

## Key Principles

- **Error text beats description.** Search with the verbatim error message; paraphrasing misses exact matches.
- **GitHub Issues first for library bugs.**
- **Multiple proposals over false certainty.**
- **No notebook, no vault.** This skill produces a conversation response only. If the user wants to persist findings, they can ask for a durable output separately. A local profile may define checklist-time knowledge capture; this skill does not create a persistence path itself.
