# Example custom class: writing opportunities

These are illustrative route shapes using the package's public
[wiki contract](../../contracts/karpathy-wiki.md), not measured meeting outcomes
or private transcript excerpts. For a meeting, the source can be a supplied
contract-review note; for research it can be the selected public document.
Candidates live in the in-place meeting record or research artifact and use the
same shared rows. This is an opt-in user-declared custom class, not a built-in
package capability. Without the local declaration, capture proposes none.
A configured workflow supplies actual storage/targets.

## Declare the class in local policy

Add this optional block after the profile's YAML frontmatter (also shown in the
[example profile](../../profiles/karpathy-wiki.example.md)). The search names
refer to locations your policy supplies; they are not package-owned folders.

```hippocampus-classes
[
  {
    "name": "writing",
    "search_before_proposing": ["ideas", "drafts", "published"],
    "required_fields": ["opportunity", "author", "angle", "addition", "privacy"],
    "workflow": "local-writing"
  }
]
```

Local policy defines new/enrich/published-followup as its opportunity taxonomy;
the generic helper checks presence of required fields and search coverage, not
this user-owned taxonomy. It rejects undeclared new classes. For example, a row
in the contract-review record can carry the following fields, with D1 and the
`contract` source already present in that record:

```json
{
  "id": "W0",
  "decision": "D1",
  "kind": "writing",
  "evidence": ["contract"],
  "change": "Retain a source-linked explanation of scoped compilation",
  "opportunity": "new",
  "author": "contract author",
  "angle": "Explain scoped compilation",
  "addition": "Add a source-linked note about the selected subset",
  "privacy": "public contract only",
  "search": {"ideas": "searched", "drafts": "searched", "published": "unavailable"},
  "target": "docs/writing-seeds.json",
  "workflow": "local-writing",
  "authorization": "pending",
  "preconditions": []
}
```

This is illustrative proposal data, not a measured search result or authorization.
Before approval, record the actual search boundaries, matches and evidence passage.
Pass the reviewed plan through `plan` with the same profile. For execution, supply
an authorized argv adapter under the `local-writing` workflow-map key; it must
perform deduplication and read-back before returning a target-matching receipt.
A destination-only declaration may instead constrain `target` and dispatch via
the class-name key. Policy changes require replanning and renewed approval.
Legacy `writing` rows remain readable without rewriting IDs or prose; a pending
legacy row needs a current declaration before it can execute.

## Example proposals

| Route | Meeting-record proposal | Research-artifact proposal | Scope and evidence |
|---|---|---|---|
| New idea | After a contract review, propose an explanation of selecting a coherent source subset | After analyzing the contract, propose the same explanation | Attribute to the document, link its Curated compilation section; call it new only after configured ideas/drafts/published searches |
| Enrichment | Add the contract's source-before-synthesis distinction to an existing idea about evidence | Enrich that same idea with the draft-before-comparison rule | Name the matching idea, proposed addition and exact source; preserve its authored draft |
| Published overlap | Propose a follow-up about tension checks when an earlier published piece already covered source selection | Identify that overlap and propose a narrower follow-up | Link the actual published record when available; never create a duplicate seed or assert user authorship of the source idea |
| No candidate | Record “no useful opportunity: the meeting only confirmed an existing document requirement” | Record “no useful opportunity: the evidence adds no distinct angle to searched material” | No seed, no first-person draft, no publication; state the actual search boundaries or unavailable coverage |

Every candidate includes source identity/passage, speaker or source author,
angle, exact proposed addition, target when known, privacy/public-reuse limits,
search coverage, approval state and stable identity. The public contract allows
public citation; a private recording does not inherit that permission. With
no writable destination, leave the candidate in its record. Only approved rows
are filed, and confirmed receipts make retries skip existing seeds/additions.

## Meeting shape

A custom meeting template may call its disposition section “Next steps” and
omit coaching entirely. It still preserves source/coverage, decisions and shared
row identities. For example, a writing candidate can state:

- Evidence: public wiki contract, Curated compilation.
- Attribution: document author; no claim this is the meeting participant's idea.
- Angle: how selected-source compilation avoids an accidental backlog sweep.
- Addition: one source-linked explanation in the configured idea workflow.
- Search: actual results for configured ideas, drafts and publications; mark any
  unavailable channel explicitly.
- Reuse: public document citation only; no private meeting quotations.
- State: pending until the concrete row is authorized; target unresolved until
  supplied by local policy.

The meeting record remains in its configured folder after absorption; the
original note/transcript uses its own source-retention policy.

## Research shape

Keep the existing research Question/Answer, Source Summary, Source Assessment,
How to Absorb, Evidence Record, Evidence Gaps and Execution Appendix. Add writing
opportunities within How to Absorb; derive execution rows from those decisions.
The same candidate fields apply. After all routes are terminal the report is
retained in raw/derived with compile exclusion, while primary sources remain
available independently. No useful candidate requires no writing-row mutation.
