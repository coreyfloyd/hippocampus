# Capture, absorption and writing: public documentation review

Status: candidate prepared; maintainer public-communication approval pending.
Implementation approval does not approve communication, publication or release.
Tracking: [hippocampus#31](https://github.com/coreyfloyd/hippocampus/issues/31).

The rendered companion shows the finished README, referenced diagram and existing
presentation alongside actual pre-change versions from candidate base `ae82e49`.
Those original contents remain (the HTML snapshot normalizes trailing whitespace only) in `2026-10-09-public-before/`; the earlier specification
review remains unchanged. The current runtime map is regenerated from committed
implementation evidence. External providers and live user records are outside this
review; no production activation, release, backfill or personal task write occurred.

| Surface | Before | After |
|---|---|---|
| README skill tables and examples | research-absorb/research-to-wiki presented as owners; meetings distributed people/doc/task outcomes | absorb/wiki-compile own the shared flow; compatibility wrappers explained; configurable in-place meeting records and writing candidates included |
| Per-section diagrams | simple research lifecycle with two inputs and user outcomes | up-front research SVG keeps the original simple visual style and retains completed report references; matching green ACTION panels share the same destination set and order, with skills on arrows; event/note/transcript inputs feed the meeting record, and transcript filing is the last meeting-only destination; no legends |
| Meeting lifecycle explanation | completed output review retained in excluded raw archive | Research and Meetings overviews precede the detailed tables; a single meeting overview links to deeper configuration/source handling; records remain references, and transcript filing lives inside the ACTION panel |
| Existing presentation | original palette/fonts/cards; research detail slides | original styling restored; slides 4, 5 and 9 use the corrected diagrams with symmetric outcomes and skills on arrows; shared plumbing panels stay removed; eight slides remain |
| Profile/setup/install/migration | three optional input adapters; no record defaults or writing configuration | two optional record settings, unchanged profile v4, no validation writes, local writing/filing policy, explicit owned/unowned wrapper migration |
| Compiler/audit contracts | research-to-wiki compiler; local entry points separate | canonical wiki-compile/wiki-audit; selected direct compile; opt-in read-only audit; local mode/coverage thresholds preserved |
| Architecture map | research-only artifact flow | meeting capture/record, shared executor, writing workflow and distinct retention; source links refreshed to the current committed implementation; approved setup/profile route included; evidence pointers now reach local destinations through approved rows with contract citations |
| Public examples | research artifact example only | both meeting/research writing routes: new, enrich, published overlap and explicit no-candidate, with attribution/search/reuse boundaries |

The review is a local, portable generator artifact for the orchestrator to publish
through the maintainer's normal review surface. No approval state is inferred from
opening it. Detailed exact-command evidence is in the accompanying generator report.

Public docs correction 1: the maintainer rejected the unified public diagrams and changed deck styling. The current README and deck use simple, per-section research and meeting diagrams in the original visual language. The detailed executor, authority and retention diagram stays in the architecture map, whose evidence-pointer reachability is corrected. Dated before snapshots remain byte-identical. Review approval remains pending.

Public docs correction 2: symmetric ACTION panels now show people/documents, follow-up work, writing opportunities, optional wiki and retained reference records in the same order. Meetings add original transcript filing last, inside the panel. Input order is calendar event, note, transcript; the subtitle states their shared role once. Monospace sublabels name the actual research, meeting-capture, absorb and wiki-compile skills. README leads with Research and Meetings before detailed skill tables, and the later meeting section retains configuration/source depth without duplicating the overview. The deck’s three adjusted slides and architecture viewer reference the same corrected assets.

## Diagram conventions

Boxes are things: blue inputs you bring, one orange record Hippocampus writes, and green destination boxes where approved outcomes land. Every box uses the same two-line style (a title and a one-line description); the record box carries a monospace label above its title. Column headers name the stage in monospace, in the column's color: QUESTION, ANSWER, ACTION for research (Ask and Bring together are the question), MEETING, RECORD, ACTION for meetings. The subtitle states the three-color key in words.

Skills label arrows in monospace, once per operation: research-topic from Ask and research-sources from Bring into the research report; the three meeting inputs merge onto one meeting-capture arrow into the meeting record; absorb from the record into the ACTION column, which fans into each destination. No skills appear in or under boxes, except wiki-compile as the description line of the Wiki destination.

Both diagrams use the same destination boxes in the same order, position and wording: People, Documents, Follow-up work, Wiki, Retained reference record; meetings add Original transcript filed, after approved routes complete, as the last box. "Individual proposals may be declined" sits at the bottom left. Both SVGs are generated from one template so their styles stay identical; keep this grammar in the deck and architecture overview by referencing the same SVGs.
