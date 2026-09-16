---
name: research-feedback
description: "Research lived community experience before adopting, upgrading, buying, or committing to something, including which forums or user groups to follow. Use for stability and wait-or-adopt decisions; use research-quick for general fact-finding."
---

# Research Feedback

Community-sentiment recon. Answers "what is it actually like to use/run/own this, according to the people doing it right now?" and identifies which communities to watch. It weights lived experience over authority, always checks Reddit, and always surfaces a recommended set of topic-appropriate forums and user groups.

Before checking local knowledge or choosing where the memo is written, validate `~/.config/hippocampus/profile.md` with `../../scripts/validate_profile.py`, resolved relative to this skill. If it is missing or invalid, stop and use `hippocampus-set-up`; do not choose a fallback output path. Any proposed follow-up task uses `artifact_followup_destination`, never the wiki-maintenance route.

When a user supplies an audio or video review, interview, or discussion as evidence, invoke `transcribe` before analysis. It only resolves the input; this skill still owns scope and the durable output.

Web search uses the runtime's built-in `WebSearch` tool; pass `allowed_domains` to restrict a search to specific sites. Page extraction uses Defuddle's hosted endpoint, a runtime-detected optional integration — `curl https://defuddle.md/<url>` returns Markdown with YAML frontmatter and requires no install or API key. When a source is blocked for either, use native web tools and say so in the report; do not silently reduce community coverage.

## When to Use vs. Not

| Use `research-feedback` | Use something else |
|---|---|
| "What's the real-world experience of running X?" | Authoritative facts/specs/how-to → `research-quick` |
| "Is the new beta/release stable enough to adopt?" | Code/library/bug diagnosis → `research-dev` |
| "What are people complaining about with X before I commit?" | Deep, persistent, cited report → `research-topic` |
| Decision gated on peer/community lived experience | Pure fact lookup with one right answer |
| The user wants to know **which communities** to follow on a topic | |

## Phase 0 — Check local knowledge

If the local profile defines a knowledge preflight, run it before external research. Surface useful matches and ask whether to use them; otherwise proceed silently.

## Phase 1 — Scope (infer; ask at most one question)

From the query, pin down:
- **Subject** — the thing being evaluated (product, OS/beta, tool, service, practice, place).
- **Decision context** — what the user is deciding (install / buy / adopt / wait / switch). This sets what "feedback" matters.
- **Recency sensitivity** — for betas, new releases, and fast-moving products, feedback older than the current version is noise. Note the version/date in scope.

Only ask if the wrong read would waste the search. One short question, then go.

## Phase 2 — Map the Community Landscape (required)

Identify the venues where real users of this topic congregate. Always include Reddit, then add venue types that fit the topic — this list is itself an output the user requested:

| Topic type | Community venues to consider |
|---|---|
| **Apple / dev betas** | Reddit (r/iOSBeta, r/MacOSBeta, version subs), [Apple Developer Forums](https://developer.apple.com/forums/), MacRumors Forums, Hacker News |
| **Software / SaaS / tools** | Reddit, official community forum / Discourse, product Discord/Slack, Stack Exchange site, GitHub Discussions, Hacker News |
| **Hardware / gear** | Reddit, dedicated enthusiast forums (e.g. head-fi, mtbr), RTINGS forums, manufacturer forums |
| **Games** | Reddit, Steam discussions, official Discord, GameFAQs |
| **Hobbies / practice** | Reddit, dedicated forums, Facebook/Discord groups, Stack Exchange |
| **Places / travel** | Reddit (city/region subs), TripAdvisor forums, Fodor's, local FB groups |
| **Health / fitness** | Reddit, condition-specific forums, Examine.com community, patient groups |
| **Finance** | Reddit (r/personalfinance, r/Bogleheads), Bogleheads forum, FairMark |

Pick the 2-4 most relevant venues. Name any user groups, Discords, or local meetups worth following if they exist for the topic.

## Phase 3 — Web Research (parallel)

Run searches in parallel.

1. **Reddit — always.** `WebSearch` with `allowed_domains: ["reddit.com"]`. Target the decision: e.g. "<subject> stability daily driver worth it", "<subject> problems after a month". Pull the 4-8 most relevant threads.
2. **Primary community forum** for the topic (from Phase 2).
3. **Official source for hard constraints** when the decision has a factual gate (system requirements, compatibility, pricing). Sentiment can't override a hard requirement.
4. **Read full Reddit threads** through the user's signed-in browser session — comment bodies are the lived-experience signal this skill exists for. Use the browser route named in the profile's local policy; the bundled Safari reference implementation is:
   ```bash
   ../research-quick/reddit-read.sh "<thread-url>"
   ```
   Run it on the 3-5 most relevant threads. See `research-quick` Phase 2 step 4 for the route contract and alternate implementations; when no browser route is available, check local policy for another blocked-channel route (for example, delegating the read to another agent runtime with access) before settling for snippet-level coverage. Extract non-Reddit forums with `curl https://defuddle.md/<url>` as normal.

## Phase 4 — Synthesize (sentiment-weighted)

- **Separate consensus from loud minority.** Many threads saying the same thing = signal. One viral complaint = note it, weight it down.
- **Rank recurring issues** by frequency × severity. Lead with what most affects the user's decision context.
- **Surface the contrarian and the positive signal** explicitly — don't only report problems.
- **Date everything.** For fast-moving topics, tie each finding to the version/build and flag when feedback predates the current release.
- **Respect hard gates.** If an official requirement blocks the option regardless of sentiment, lead with it.

## Output

Write a decision memo. It exists to be read once and acted on, not absorbed
into a knowledge base: `research-absorb` does not apply. Placement: when the
subject is a competitor or the research otherwise serves a project, write the
memo into that project at the path the caller names; otherwise write it to the
local profile's destination, where it is deleted once the decision is made.
Report the path at completion.

```markdown
# [Subject] — [decision: install / buy / adopt / wait / switch]
Scope: [version or date range the feedback covers]   Researched: [date]

🟢/🟡/🔴 **Bottom line**: [verdict tied to the user's decision context]

## Hard constraints
- [Requirement / compatibility / gate] ([official source](url)) — or "none"

## What people are saying
- [Recurring theme — how widespread, dated against the version in scope] — [r/sub or forum](url)
- [Contrarian / positive signal] — [source](url)

## Recurring issues, ranked
1. [Issue] — [frequency × severity note]

## Communities to watch
- [Venue] — [why / what's there] (url)
- [User group / Discord / forum] — (url)

## Sources
- [Thread or page](url) — [date] — [poster's version] — [read via browser / Defuddle / snippet only]
```

Consolidate agreeing sources. Make conflicts explicit. **Communities to watch**
always closes the body, directly before **Sources** — surfacing the right venues
is a primary output of this skill. When the decision should be revisited (a
release ships, a beta exits), file that as a follow-up task through
`artifact_followup_destination` and name it in the memo's last line.
