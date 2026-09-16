# Research artifact contract

Every durable artifact produced by `research-sources` or `research-topic` is a
transient, evidence-grounded handoff to `research-absorb`. (`research-feature`
and `research-feedback` produce deliverables that are read and filed or
deleted, not absorbed; each defines its own document in its SKILL.md.) It is not raw wiki input and it is not a final
archive. Its purpose is to let the user make the decisions the evidence raises,
then be executed and deleted.

This contract is the only place the artifact's sections are defined. A producing
skill adds requirements of its own; it does not restate the section list.

A complete artifact in this shape, sanitized from a real session:
`docs/examples/2026-09-03-fable-5-1-model-routing.md` at the repo root.

## Required sections

1. **Question and Scope** — two required subsections, in this order:
   - `### Question` — the decision, target, or question addressed. Three or
     more questions get short codes (`Q1`, `Q2`). State scope and what is
     deliberately out of scope.
   - `### Answer` — one entry per question, answer first. Follow the entries
     with a **Confidence** line stating how much to trust the answer and what
     that rests on, and a **What would change the answer** line naming the
     evidence that would flip it. When the evidence does not support an
     answer, say so here and point to the Evidence Gaps row that would close
     it. The Answer is the first thing the user judges; it must be readable
     without opening any later section.
2. **Source Summary** — what the sources actually say. The claims, frameworks,
   lists, and arguments themselves, in enough detail that every later section
   can be read and judged without opening a source. This section carries
   content, not commentary about content.
3. **Source Assessment** — whether those sources can be trusted: reliability,
   method, material contradictions between them, confidence, and provenance
   caveats. It says nothing about the user's systems.
4. **How to Absorb** — the proposed distribution plan (shape below).
5. **Evidence Record** — one entry per source: what it is, how it was obtained
   and verified, any retrieval fallback, and notebook IDs. Each source carries
   its own retrieval, so no fact appears twice. Record here what was searched
   for beyond the supplied sources, including searches that returned nothing (a
   verified negative must say how the absence was verified) and channels not
   searched because the runtime is blocked from them or the cost exceeded the
   stakes. Distinguish "searched directly and absent" from "absent from
   indirect search" — they carry different confidence. If local policy names an
   alternate route for a blocked channel, record whether it was used and why or
   why not. A verification that *closed* a question belongs here, not in
   Evidence Gaps.
6. **Evidence Gaps** — what remains unanswered, why it is open, and the
   follow-up that would close it (shape below).
7. **Execution Appendix** — machine-actionable rows (shape below).

### Sizing rule

The Answer subsection sizes to the question set: one entry per question, and
the Confidence and What-would-change lines are single sentences or short
bullets, never a restatement of Source Assessment. Source Summary sizes to the
content: anything a later section relies on must be stated there. Every other section sizes to the decisions the artifact must
enable — not to source volume, and not to analysis effort expended. Write one
assessment per claim that changes how a source is trusted, and one item per
thing to absorb. Verification work that succeeded collapses to a line in the
Evidence Record, not a section.

## How to Absorb

Three classes, split by what the result touches. Every actionable result belongs
to exactly one.

- **Actions** — anything that is not a document: installing or updating a skill,
  installing software, changing an agent harness, a workflow, or the user's own
  code.
- **Wiki Additions** — the compiled knowledge base only.
- **Document Updates** — every other file: context files, project briefs,
  standing documents, repository docs.

Routing knowledge into the knowledge base or into a standing document is never
an Action. When a class has no items, say so in one line — that is the whole
subsection.

The Wiki Additions class exists only for wiki-enabled profiles. Check the
profile before writing How to Absorb: when it records the wiki as disabled, a
wiki-disabled artifact omits the Wiki Additions class entirely — not even an
empty-class line — and any candidate that would have gone there is a Document
Update or discarded instead.

**Absorb or discard; never stage.** Staging a source without absorbing it is a
failure state, not an option. No item may propose an outcome that leaves
knowledge parked.

**Reach the target the user named.** When the document the evidence is meant to
serve does not exist yet, route the knowledge into the standing document that
does — the project brief, the context file, whatever the next session will
actually open. A knowledge-base compile alone leaves the material invisible to
the work that consumes it.

### Item shape

Every item, in all three classes, states in order:

| Field | Contents |
|---|---|
| **What exists now** | The target's current state, specific enough that the change is legible against it: what it says today, and what it does not cover. |
| **Change** | The edit itself — what is added or modified, and what is deliberately left alone. |
| **Why** | The value, including what is lost by skipping it. |
| **Confidence** | How much to trust this, and what that rests on. |
| **Rejected** | Alternatives considered and declined, with the reason. Omit when there are none. |

An Action item also names its execution route inside its **Change**: filed as a
task for another session, or run inline on approval. Wiki Additions and Document
Updates always execute inline and carry no route.

### Options

Present 2–4 options with their tradeoffs, plus a recommendation and the reason
it beats the alternatives, **only when a genuine choice exists**. An item with
one right answer states it and moves on; a fixed option quota manufactures
filler. A trial option is only an option when it is defined: it uses the
source's own installation or adoption mechanism (deviating only for a stated
risk), and it names success criteria, a review date, and a removal path. An
undefined trial is a deferral, not an option.

### Rejected candidates stay inline

A candidate that was considered and rejected is recorded inline in its parent
item, with the reason. It is not escalated as its own item, and no standalone
"confirm the drops" section exists. Approval of the plan covers the discards.
Escalate a rejection only when it forecloses something contentious the user
might weigh differently.

## Evidence sufficiency

Sufficiency is derived from the decision set, not from the source count. Before
writing How to Absorb, check each item: can its options actually be chosen from
the evidence gathered? An Action about adopting third-party work always requires
evidence the primary source cannot contain — real-world usage, community
sentiment, maintenance signals — bounded to what would change the choice,
gathered through the producing skill's evidence-improvement path.

Completion test: if an item's recommended option amounts to "gather more
evidence," the research stopped early — go gather it. The exceptions are
evidence obtainable only first-party (by the user running it themselves) and
evidence whose collection cost exceeds the stakes; name the exception when
relying on one.

### Named referents

Evidence may introduce a **named referent** — a person, organization, product,
or concept — that the material establishes as a substantive subject rather than
an incidental mention. A source's own author or subject counts, even when no
other source in the set names them. When a referent clears that bar, emit an
item for it — a Wiki Addition or Document Update, whichever local policy's
destination implies. It is a distinct actionable result from the sections it
appears in, and the producer is the only stage holding both the evidence and the
authority to propose it. Resolve its destination and page conventions from local
policy; do not invent a taxonomy. Emit no item when nothing clears the bar — a
considered-and-rejected note is not an item.

## Evidence gaps

Each gap states why it is open and names the follow-up that would close it,
including an explicit **none** with its reason: unclosable, already tracked
elsewhere, or not worth the cost. A gap with no stated follow-up cannot be
distinguished from one nobody attended to. A follow-up the user can run in a
minute is worth naming precisely, with the exact step.

## Writing rules

- **Every item is answerable from the artifact.** Whatever the user is asked to
  judge must be present: inline first, a named section of this artifact second,
  a link to the source last. An item referencing a framework states what the
  framework is. An item the user cannot answer without leaving the artifact is
  malformed.
- **Expand every abbreviation on first use.**
- **Three or more items is a list**, never prose inside a paragraph.
- **Absorption items and the gap list are tables.** Each item is a level-4
  heading naming the literal target path, followed by a two-column table with
  the header `| Field | Detail |` and one row per field. The path never sits
  inside the table: a long path in a header cell squeezes the field column and
  wraps badly. The gaps are one two-column gap/follow-up table.
- **No bare URLs or long inline-code spans inside table cells.** Use a linked
  label. An unbreakable token sets a minimum column width that squeezes every
  row of the table, not just the cell containing it.

## Execution appendix

The absorption sections are the surface the user judges. The mechanics of
executing them live in an appendix of machine-actionable rows keyed by item ID,
for `research-absorb` to validate and run:

| ID | Decision | Destination and action | Target | Task route | Preconditions | Terminal disposition |
|----|----------|------------------------|--------|------------|---------------|----------------------|
| E1 | W1 | stage source then compile | named knowledge base area | — | approval; target available | integrated |

`Destination and action` must say whether the result needs source staging,
synthesis, direct document update, or a follow-up task. Only an Action row may
carry a task route, and it must name `artifact_followup_destination`, not the
wiki-maintenance destination. A knowledge-base row names the supporting external
source(s), not the report as raw input. Rows derive from items; a row with no
parent item is invalid.

## Lifecycle invariants

- The producer proposes the plan; `research-absorb` validates and executes an
  approved plan. It does not create a second plan.
- Every row ends as **integrated**, **target document updated**, **task filed**,
  or **explicitly discarded**. A pending row prevents cleanup.
- Staging is never a terminal disposition. A staged source that was not absorbed
  leaves its row pending.
- Approval of the plan is the explicit discard for every inline-rejected
  candidate; no per-item confirmation is required.
- No retain or archive state exists for the artifact. After all rows have a
  terminal disposition, `research-absorb` deletes the artifact.
- **An Action row's task must outlive the artifact.** The artifact is deleted, so
  a ticket it files carries everything its executor needs *inside the ticket* —
  the evidence, the options and their tradeoffs, the source assessment, and what
  would settle the question — citing only durable targets. A ticket that points
  back at the artifact is malformed: it dangles on deletion, or it blocks the
  deletion the contract requires. File the task **after** the Wiki Additions and
  Document Updates rows have executed, so it can cite the compiled destinations
  rather than the transient plan.
- Do not treat a report as a raw knowledge-base source. Preserve selected source
  provenance in canonical `raw/research/` as the extracted source text under
  provenance frontmatter, never as a summary alone, then use `research-to-wiki`
  for the curated subset. Promote a report to derived material only when it is itself a
  required durable transformation and approval covers that promotion.
- When the profile records the wiki as disabled, `research-absorb` does not stage source provenance into `raw/research/` for compilation and never invokes `research-to-wiki`.
