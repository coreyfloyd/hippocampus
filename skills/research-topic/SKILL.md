---
name: research-topic
description: "Conduct deep, persistent topic-first research with NotebookLM: gather and index sources, resolve evidence gaps, verify claims, and produce a distribution-ready artifact. Use for substantial research or research verification, not quick lookups or supplied-source analysis."
---

# Research Topic

Conduct topic-first research with NotebookLM as the persistent source and synthesis layer. Use `research-sources` instead when the caller already supplies the evidence or asks to improve a named collection.

Before choosing sources, a durable output location, or local follow-up policy, run `python3` with `../../scripts/validate_profile.py` (resolved relative to this skill) and `~/.config/hippocampus/profile.md`. If the profile is missing or invalid, stop and use `hippocampus-set-up`; do not choose a fallback output path. Any proposed follow-up task in the artifact uses `artifact_followup_destination`, never the wiki-maintenance route.

## Scope and source set

1. Establish the research question, decision it informs, and material constraints. Ask for caller-held sources before discovery; they take priority.
2. Check for a related NotebookLM notebook. Ask before adding to an existing notebook; otherwise create one and preserve its ID.
3. Use the built-in `WebSearch` tool for discovery (`allowed_domains` restricts a search to specific sites) and Defuddle's hosted endpoint — `curl https://defuddle.md/<url>`, a runtime-detected optional integration — for complete-page extraction. Use native web tools for sources the endpoint cannot reach and record that fallback.
4. Add user-provided and discovered sources to NotebookLM, retaining original URLs or paths. Invoke `transcribe` for material audio or video; prefer native YouTube indexing when it suffices.
5. Wait until sources are indexed before synthesis.

## Analyze and improve evidence

Query the notebook for key findings, source agreement, contradictions, evidence gaps, and support for each actionable claim. Classify claims as verified, unverified, contradicted, or overstated.

When evidence is incomplete, identify the specific gap and add the smallest useful set of sources. Use [the evidence-improvement procedure](../research-sources/references/improve-evidence.md) for source discovery and categorization. Re-run synthesis and claim verification after adding sources.

Prefer primary sources. Distinguish source-grounded findings from reasonable inference, disagreements, and open questions.

## Artifact

Write one durable artifact using [the shared research artifact contract](../absorb/references/artifact-contract.md), which defines the artifact's sections. Record the notebook ID and every claim verification in the Evidence Record, and any disagreement between sources in the Source Assessment. Preserve the contract's Insights & Highlights: useful specifics, interpretations and their selection should remain visible in the artifact, not only in a chat summary. Link proposed uses to existing absorption items; a thing to try is not automatically an Action.

Optional NotebookLM outputs such as reports, tables, or mind maps support the artifact; do not substitute them for it. Store generated files only in canonical `output/`, not scratch.

At completion, report the artifact path and its proposed plan. The caller may invoke `absorb`; do not automatically distribute, promote, or archive the artifact.

## Boundaries

- `quick-research` and `dev-research` remain inline research paths.
- `feature-research` covers competitor UX and established patterns.
- `feedback-research` covers lived community experience.
- This skill does not execute a distribution plan or sweep uncompiled knowledge.


## Custom proposal classes

Read local policy in the profile body for declarations in the
[shared distribution contract](../absorb/references/distribution-contract.md).
Propose custom classes only when declared; when none is declared, propose none.
Before proposing, search every declared location and record searched/unavailable
coverage and actual matches. Include all declared required fields, selected source
pointers, source-author attribution, privacy/reuse limits, a concrete change and
explicit authorization. A missing writable workflow or destination leaves the
candidate in the record. An explicit no-candidate result with its basis is valid.
`absorb` executes only approved rows through declared routes, with receipts and
read-back. Capture does not authorize first-person drafting or publication.
