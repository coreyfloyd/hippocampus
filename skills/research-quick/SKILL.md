---
name: research-quick
description: "Fast inline research on non-development topics—products, places, current events, decisions, health, finance, or travel—with cited findings in conversation. Use for general lookups; no notebook or artifact workflow."
---

# Quick Research

Inline research for non-dev questions: check configured local knowledge first, then Reddit plus domain-appropriate authoritative sources, and synthesize in the conversation. No notebooks, no files written.

Read `~/.config/hippocampus/profile.md` before checking local knowledge; use only the local-preflight policy it provides. This skill remains an inline response.

If a supplied audio or video source is needed as evidence, invoke `transcribe` to acquire its text first. The transcript is input evidence; the response stays inline.

Web search uses the runtime's built-in `WebSearch` tool; pass `allowed_domains` to restrict a search to specific sites. Page extraction uses Defuddle's hosted endpoint, a runtime-detected optional integration — `curl https://defuddle.md/<url>` returns Markdown with YAML frontmatter and requires no install or API key. When a source is blocked for either, use native web tools and say so in the response; do not silently reduce source coverage.

## When NOT to Use

- Code, bugs, library questions → `research-dev`
- Deep research needing persistent notebooks and a durable artifact → `research-topic`
- Community sentiment for an adopt/buy/wait decision → `research-feedback`

## Phase 0 — Check local knowledge

If the local profile defines a knowledge preflight, run it before web search. Surface useful matches and ask whether to use them before searching externally. Without a profile, proceed directly to source planning.

## Phase 1 — Source Planning

### Domain Classification (infer from query, don't ask)

| Domain | Signals in query | Sources to add |
|--------|-----------------|----------------|
| **Product/gear** | "should I buy", "best X", "X vs Y", "worth it", "review" | Wirecutter, RTINGS, Ars Technica, YouTube reviews |
| **Place/travel** | city name, "visit", "trip", "restaurant", "hotel", "neighborhood" | TripAdvisor, Atlas Obscura, local subreddits |
| **Health/wellness** | symptom, medication, diet, supplement, "is X safe" | Mayo Clinic, Examine.com, NIH/PubMed (via search) |
| **Finance/money** | investing, savings, budget, mortgage, tax, crypto | Investopedia, NerdWallet, Bogleheads |
| **Current events** | recent dates, news topics, "what happened with" | Google News, AP, Reuters |
| **Concept/topic** | "what is", "how does", "explain", abstract nouns | Wikipedia, relevant subreddits |
| **Service/company** | brand name, app name, subscription, "is X legit" | Trustpilot, BBB, Reddit |
| **General/unclear** | anything else | Wikipedia + 2 general web searches |

If the domain is genuinely ambiguous and the wrong source set would waste the search, ask one short question up front: "What kind of angle are you looking for — [option A] or [option B]?" Then go.

## Phase 2 — Web Research

Run all searches in parallel.

1. **Reddit** (always): `WebSearch` with `allowed_domains: ["reddit.com"]` — pick the 3 most relevant threads
2. **Domain source 1**: first authoritative source from the table above
3. **Domain source 2** (if warranted): second source or a broader `WebSearch`
4. **Read full Reddit threads** through the user's signed-in browser session:
   Reddit blocks programmatic scrapers but serves the real page to the user's
   own logged-in browser, so the route is: load the thread in that browser,
   extract the rendered text. Use the browser route named in the profile's
   local policy (blocked-channel routes). The bundled helper is the **Safari
   reference implementation** of that route — background tab, no focus steal,
   closes its own tab; it requires an interactive macOS session with Safari
   signed into Reddit:
   ```bash
   ./reddit-read.sh "<thread-url>"
   ```
   Other implementations of the same route (a browser-automation tool the
   runtime provides, another browser's scripting interface, delegating the
   read to another agent runtime with access) are equally valid when local
   policy names them. When no browser route is available, fall back to
   search-result snippets and note the reduced coverage. Scrape non-Reddit
   sources with `curl https://defuddle.md/<url>` as normal.

## Output Format

Deliver inline in the conversation. No files, no notebooks.

```
**[Topic]** — [2-sentence synthesis of the overall picture]

**What people say (Reddit)**
- [Finding] — [r/subreddit thread title](url)
- [Finding] — [r/subreddit thread title](url)

**Key findings**
- [Point] ([Source](url))
- [Conflicting view or caveat if any] ([Source](url))

**Bottom line**: [1-sentence recommendation or verdict, if the question calls for one]
```

If sources agree, consolidate rather than repeating the same finding with multiple URLs. If they conflict, surface the conflict explicitly. Skip sections that don't apply.

If a local profile defines a checklist-time knowledge-capture policy, that policy may review this research later; this skill itself writes nothing.
