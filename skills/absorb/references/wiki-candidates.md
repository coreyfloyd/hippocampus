# Wiki candidates from project deliverables

`feature-research` and `feedback-research` write deliverables filed with the project they serve, and `dev-research` may persist its findings to a file a caller names. These documents do not use the [artifact contract](artifact-contract.md) and are never compile input. Their public sources can still carry knowledge that is reusable outside the project: how a vendor's product behaves, what an upstream codebase does at a pinned commit, what a published guide recommends. Without a route into the wiki, that knowledge is findable only by someone who already knows the project document exists.

## When to add the section

Add `## Wiki candidates` as the last section of a persisted document when both hold:

- the validated profile has a wiki configured (`validate_profile.py --require-wiki` succeeds); and
- at least one cited public source supports a finding that would be true and useful outside this project.

Otherwise omit the section. Do not add it to a conversation-only answer.

## Format

```markdown
## Wiki candidates

| ID | Source | Reusable finding | Proposed wiki target |
|----|--------|------------------|----------------------|
| W1 | S2 (vendor docs, URL) | One-sentence claim the source supports | existing article or new page name |
```

- **Source** names a row of the document's own Sources table, so every candidate is a public, re-fetchable source: documentation pages, repository files at a pinned commit, published articles. Local inspections, private systems and the project's own code are never candidates.
- **Reusable finding** states the claim without project-specific context. Findings that only describe the project, its machines or its decisions stay in the document.
- **Proposed wiki target** is a suggestion; `wiki-compile` still checks for an existing article and applies the wiki's naming rules.

## Handoff

At completion, report the document path and its Wiki candidates as a proposed distribution. Do not stage or compile anything yourself. The caller may approve some or all rows and invoke `absorb` with the document path and the approved IDs.

## How absorb executes it

- Each approved row is a wiki row. `absorb` stages the row's source as complete extracted text under provenance frontmatter in the knowledge root's research raw folder, re-fetching it rather than copying the document's paraphrase, and records the project document as `cited_by`.
- It then invokes `wiki-compile` with only the staged subset. The compiled article may cite the project document as the synthesis it came from, never as evidence.
- The project document stays at its project path and is not edited, moved or retained in `raw/derived/`; the project's own retention policy governs it.
- Receipts for each row (staged path, compiled article, or decline reason) go to the configured operation log.
