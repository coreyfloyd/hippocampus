---
name: research-feature
description: "Research competitor UX and established patterns before feature design, producing a design input document filed with the project. Use for 'how do other apps handle X?' or standard-pattern research."
---

# Feature Research

Investigate how other products solve the same problem the feature being designed aims to address. Given a set of requirements, research how established products and competitors handle similar features. Identify common patterns, novel approaches, and user expectations.

When a supplied demo, talk, or video is material evidence, invoke `transcribe` to obtain it in the appropriate form before comparing patterns. Do not create a separate media-research workflow.

Firecrawl is a runtime-detected optional integration. Use it first for web search and page extraction when it is available. If it is unavailable or blocked for a source, use native web tools and state that fallback in the report.

Validate `~/.config/hippocampus/profile.md` with `../../scripts/validate_profile.py`, resolved relative to this skill, before writing the document. If it is missing or invalid, stop and use `hippocampus-set-up`; do not choose a fallback output path. This skill is read-only except for its required research artifact. Any proposed follow-up task uses `artifact_followup_destination`, never the wiki-maintenance route.

## Execution Modes

- **Current session** — create the durable artifact after research.
- **Dispatched** — when an orchestrator needs the work off its context, pass the requirements and the destination path. The worker must still create the same artifact rather than leaving search dumps in scratch.

## What to Investigate

- **Established products** that solve the same or similar problem
- **UX patterns** — how do users interact with this feature in other products?
- **Common approaches** — what do most products do? Is there a de facto standard?
- **Novel approaches** — any products doing something unusual that works well?
- **User complaints** — what do users dislike about existing implementations?
- **Accessibility and edge cases** — how do products handle error states, empty states, loading states?

## How to Research

1. Read the requirements to understand what the feature does and who it's for
2. Use Firecrawl first, when available, to find and extract how 3-5 established products handle this — search for "[feature] UX pattern", "[product] [feature] design". Use native web search as supplementary discovery or the fallback when Firecrawl is unavailable or blocked.
3. Check product review sites, Reddit discussions, and design case studies for user feedback
4. Look for Apple Human Interface Guidelines or platform-specific patterns if building for iOS/macOS
5. Identify what works, what frustrates users, and what's table stakes vs. differentiating

## Research artifact

Write a design input document. It feeds the feature's design and spec and stays
with the project: write it into the project repo at the path the caller names,
beside the requirements it answers. When no project path is named, write it to
the local profile's destination and say so. It is not absorbed into a knowledge
base; `research-absorb` does not apply. Report the path at completion.

## Artifact body

```markdown
# Feature research: [Feature name]
Requirements: [link or path]   Platform: [iOS / macOS / web]   Researched: [date]

## Comparison

**[Product A]** (S1)
- How it works: [description]
- What works well: [strengths]
- User complaints: [weaknesses]

**[Product B]** (S2)
- ...

| Requirement | Product A | Product B | Product C |
|---|---|---|---|
| [requirement] | [short value] | [short value] | [short value] |

## Common patterns
- [Pattern]: used by [products]. [Why it works.] (S1, S2)

## Novel approaches
- [Approach]: [Product] does [X]. [Why it's interesting.] (S3)

## Table stakes
- [Feature users expect based on market norms] (S1, S4)

## Platform conventions
- [HIG / Material / platform guideline] ([link](url))

## Implications
[What this suggests for our design; the text the spec draws on]

## Sources
| ID | Product | Type | Link | Date | Version observed |
|----|---------|------|------|------|------------------|
| S1 | [Product A] | official docs / review / user thread / hands-on / HIG | [label](url) | [date] | [version] |
```

Include the requirement × product matrix when three or more products are
compared; keep cell values short. Every claim in Comparison, Common patterns,
Novel approaches, and Table stakes cites a Sources row by ID.

## Constraints

- **Read-only research.** Do not edit or create project files; the only write is the required durable artifact.
- **Evidence-based.** Cite specific products and specific behaviors. Don't generalize without examples.
- **User perspective.** Focus on what works for users, not what's technically clever.
- **Include negative signals.** What users complain about is as valuable as what they like.
- **Placement:** the document lives with the project it serves; nothing is distributed elsewhere.

## When NOT to Use

- General non-dev research → `research-quick`
- Implementation/bug research (libraries, APIs, diagnosis) → `research-dev`
- Deep topic research with persistent notebooks → `research-topic`
