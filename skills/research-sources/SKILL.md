---
name: research-sources
description: Investigate supplied sources, improve an insufficient evidence set, or prepare a source-grounded update for an existing artifact. Use when a user provides URLs, documents, audio, video, YouTube, a source collection, or a named target; not for topic-first research without supplied evidence.
---

# Research Sources

Turn supplied evidence into a durable, source-grounded research artifact. This skill may analyze a fixed evidence set, improve an incomplete one, or prepare a proposal for an existing target. It does not directly promote knowledge or mutate a target without explicit authorization.

Before selecting an output location, validate `~/.config/hippocampus/profile.md` with `../../scripts/validate_profile.py`, resolved relative to this skill. If it is missing or invalid, stop and use `hippocampus-set-up`; do not choose a fallback output path. Any proposed follow-up task in the artifact uses `artifact_followup_destination`, never the wiki-maintenance route.

## Modes

### Analyze supplied sources

Use when supplied evidence can answer the question. Add it to NotebookLM, inspect it, and synthesize the requested analysis. Preserve original URL or file provenance and the NotebookLM notebook ID.

### Improve evidence

Use when a supplied source, collection, notebook, or target cannot support the question. Identify the unanswered claim or missing perspective, discover the smallest useful additional evidence set, and add it before analysis. Read the [evidence-improvement procedure](references/improve-evidence.md) for NotebookLM discovery and source categorization.

### Update an existing target

Use when the caller identifies an existing document, wiki article, context file, or other artifact. Analyze the supplied evidence against the target and produce a source-grounded update proposal. Use **Improve evidence** only when the supplied evidence cannot support a safe proposal. Do not edit the target unless the caller explicitly authorizes it.

## Source handling

NotebookLM is the persistent, source-grounded synthesis layer. For supplied web pages, extract with Defuddle's hosted endpoint, a runtime-detected optional integration — `curl https://defuddle.md/<url>` returns Markdown with YAML frontmatter and needs no install or API key — then add the original URL to NotebookLM. Record a native-reader fallback when the endpoint is unavailable or the page is blocked.

For supplied audio or video, invoke `transcribe` to choose the input route. Prefer NotebookLM's native YouTube indexing when sufficient; use a local transcript only when the source or requested output requires one. Keep original media provenance alongside any transcript.

## Research artifact

Write one durable output using [the shared research artifact contract](../research-absorb/references/artifact-contract.md), which defines the artifact's sections. If evidence was improved, record every added source and the precise gap it closed.

Before writing How to Absorb, apply the contract's evidence-sufficiency check: when a decision asks whether to adopt or act on supplied third-party work, the supplied source alone cannot answer it — use **Improve evidence** to gather real-world usage, sentiment, and maintenance signals, bounded to what would change the choice. This is not a topic search; it is the smallest evidence set that makes the decision choosable.

When the current runtime is blocked from a channel the evidence needs (a community forum, a login-walled site), first ask whether the **content** is reachable elsewhere rather than whether the channel is. A post on a blocked platform is often the author syndicating something they published on their own site, newsletter, or blog; search by title and author before treating the channel as the blocker, because a first-party copy beats both an alternate route and a third-party summary. Only when the content exists nowhere else, check the profile's local policy for a blocked-channel route — an alternate retrieval path, such as delegating the read to another agent runtime that has access — before accepting reduced coverage. Record the channel, the route taken or skipped, and why in the artifact's Evidence Record.

At completion, report the artifact path and its proposed plan. The caller may then invoke `research-absorb`; do not invoke it automatically or treat the artifact as raw wiki input.
