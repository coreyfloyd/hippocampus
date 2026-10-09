# Meeting capture mode

Preserve what happened in a meeting and carry its actionable outcomes into the configured knowledge and task systems. This capture frontend prepares an in-place meeting record; `absorb` executes its approved rows and `wiki-compile` owns synthesis.

## Preflight and scope

Run `python3` with `../../../scripts/validate_profile.py` (resolved relative to this reference) and `~/.config/hippocampus/profile.md`. If missing or invalid, use `hippocampus-set-up`; do not choose a fallback knowledge root. Read the profile body and applicable destination rules. Use `artifact_followup_destination` for meeting actions; `wiki_followup_destination` is only for wiki-maintenance work.

Resolve the requested people, meetings, and dates through supplied sources or available connected meeting tools. Establish the user's identity for speaker attribution. If a name search fails, inspect a bounded recent meeting inventory before claiming no recording exists. Read complete available primary transcripts with pagination; summaries can help navigate but never replace unread transcript evidence. Distinguish calendar time from modification time, preserve timezone and meeting identifiers, and flag missing or partial recordings.

Infer the purpose of the supplied source material, state that understanding to the user, and ask them to confirm or correct it before planning captures or actions. Distinguish core outcomes from ancillary ones and preserve the confirmed hierarchy in the disposition and resulting records. If the user has already explicitly confirmed the purpose and hierarchy, use that confirmation rather than asking again. This prevents an ancillary use from displacing the user’s purpose (2026-10-07: sprint participation and writing were mistakenly framed around coaching opportunities).

## Configurable source adapters

Read these optional flat profile fields independently. Their values are provider names or retrieval instructions, except the note path. Use unquoted values; `disabled` explicitly skips that input. Configuration selects a source, not permission to mutate it or proof that a connector is available.

| Field | Meaning | When absent |
|---|---|---|
| `meeting_transcript_source` | Provider or supplied-transcript retrieval route | Use the supplied transcript or available meeting source |
| `meeting_event_source` | Calendar provider or event retrieval route | Skip event lookup |
| `meeting_note_path` | Default local path (fixed or with optional `{date}`) or Google Docs document link | Use a supplied meeting note; otherwise skip note lookup |

For enabled event lookup, match a supplied event identifier first; otherwise search the participant and meeting's local date, then read the complete primary event. Flag ambiguous matches rather than silently selecting one. Save and link the actual provider-returned event URL when available; report a missing URL instead of constructing one from an ID. Use the event for scheduled time, agenda, invitations, and source links; an invitation or accepted response does not prove attendance. The transcript establishes what was said and by whom. Do not mirror live calendar data where local policy prohibits it; retain a source pointer and match status instead.

For notes, a path or Google Doc link supplied for a particular meeting overrides `meeting_note_path`; the profile is only an optional default. Accept notes supplied separately for each meeting—never assume a shared directory. Resolve a relative profile path from the knowledge root, an explicit absolute path as given (including outside that root), and a supplied relative path from the request's declared base or working directory. If a local default contains `{date}`, substitute the meeting's local `YYYY-MM-DD`; fixed paths require no template. Check the selected source's actual identity and meeting relevance before applying it to multiple meetings. If the profile disables notes, an explicitly supplied note still authorizes reading that input.

Read a local note without creating or editing it. For a Google Docs link, use an available authorized document/Drive connector or supplied export and read the complete primary document with pagination as needed. A link does not prove access; report unavailable content and continue with the other sources instead of guessing or claiming the note was reviewed. Use no credentials workaround. Treat the user's observations as a separate source, preserve their date, and distinguish plans from actual outcomes. Missing notes are a coverage gap, not an invitation to invent a record. Historical intentions do not become current context without required confirmation.

Keep transcript evidence, event context, note observations, and coaching interpretations separately attributed. Surface conflicting dates, identities, or outcomes. If an enabled source is unavailable, continue with available evidence and report the gap; never silently claim three-input coverage. Do not fetch an explicitly disabled source unless the current request overrides that setting.

The request authorizes only its stated routes. A request to review a meeting does not by itself authorize messages, task writes, context facts, or a new engagement. Conversely, explicit directions to compile records, create todos, or archive reviews do not need a second generic approval. Ask only for a specific missing decision, disputed destination, or required confirmation; continue independent work.

## Persistent record and template

Resolve `meeting_record_folder` (default `meetings/` relative to the knowledge
root) and `meeting_record_template` (default the bundled minimal Markdown
example in `meeting-capture/assets/meeting.md`). An explicit per-capture template
overrides the profile. Relative template paths resolve from the knowledge root;
absolute template paths are accepted. An explicitly missing, empty, non-Markdown
or invalid template fails clearly, with no example substitution. The record
folder must remain in the knowledge root, including through symlinks. Validation
checks settings without creating folders or records.

Use `absorb/scripts/distribution.py capture` (relative to the package) with source
identity, meeting-local date, title, selected sources, coverage and actual event
URL. Create the record directly in its final folder before proposing routes.
Repeat capture searches by source identity and reuses the existing record/path;
compare fresh evidence, fill gaps and update only authorized template-derived
sections, preserving user edits and every prior execution result. If evidence
changed, renew affected row authorization before executing. Never stage this
record in output or replace it with an archived transcript. Coaching content is
optional user template content; the bundled example carries identity/date,
sources/coverage, summary, decisions, actions, writing opportunities, proposed
changes, questions and execution results.

Read [the shared distribution contract](../../absorb/references/distribution-contract.md)
for source-linked stable row mechanics independent of custom headings. Original
transcripts and the generated record have distinct provenance.

## Capture and disposition

Resolve separate transcript intake and retained-source destinations from the knowledge root's local policy, honoring explicit meeting destination overrides in the private profile body. These are output destinations, independent of the three source adapters. Do not assume other users share a folder taxonomy; if either destination is unresolved or conflicts with local policy, ask before filing. Keep both destinations within the configured raw source library. A local policy may use `raw/inbox/` for intake and `raw/archive/meetings/` for retained transcripts.

Stage new source material in the resolved intake with source link, meeting date/timezone, meeting ID, sensitivity, and ingestion tracking. Deduplicate across intake and retained sources by meeting ID or supplied source identity; reuse the existing canonical source on repeat capture. Preserve private material and paraphrase it in derived notes according to local policy. Preserve available partial transcripts with an explicit coverage gap; do not label them complete.

Build one disposition inventory covering all of these routes, even if a route has no items:

- **People and knowledge:** Current source-grounded biography plus dated conversation records. Include purpose/summary, coaching or advice actually delivered, the person's response, decisions, follow-up ownership, unknowns, and source references. Distinguish coaching, teaching, advice, referrals, and peer exchange. Strategies are observed actions; theoretical framework matches and causal explanations are interpretations. In-call intent is not later success. Preserve old records and compare changes before updating a biography. Resolve existing entities before proposing new ones. Match names, nicknames, and spelling against supplied context and known entities; never expand a shortened transcript name into an invented full name. If unresolved, preserve the source spelling and ask or mark the identity unknown.
- **Existing documents:** Identify project, context, content, or other files affected by the meeting. Apply only requested and rule-permitted updates. Record historical facts as dated history; ask for confirmation before treating old preferences or plans as current user context when local rules require it. Do not silently reword authored prose. Route project records through their existing workflow.
- **Actions:** Extract owner, next action, commitment versus suggestion, timing, dependencies, and supporting source. Keep separate contacts and next actions separate unless they share the same joint next step. Another participant's promise is not automatically the user's task; a relevant user task may be to check back. Conditional promises get a readiness check rather than an invented completion deadline. Dates belong to specific actions, not people records. Assign a date only when the user requests dates or a supported commitment or scheduling policy supplies one. When dates are requested but unstated, choose reasonable future planning dates, label them as internal follow-up targets, and explain each rationale while distinguishing source timing from discretionary scheduling; stale deadlines become current status checks. Do not create calendar events or send messages unless explicitly requested.
- **Writing opportunities:** Search configured ideas, drafts and published
  records before proposing new ideas, enrichment or published follow-ups. Report
  unavailable publication coverage instead of claiming novelty. Preserve source
  pointers/timestamps, speaker attribution, proposed angle, specific addition,
  target when known, privacy/public-reuse limits and approval/execution state.
  Another speaker's idea is not the user's idea. Use local templates/scoring and
  writing workflows; without a configured writable destination keep candidates
  in this meeting record. An explicit “no useful opportunity” is valid. Capture
  neither drafts first-person prose nor publishes material.
- **Open questions:** Preserve uncertain identities, one-sided assessments, tentative opportunities, and unverified claims. Do not infer consent, a contract, diagnosis, or completed outcome from a conversation.

Propose any route requiring approval as a concrete change. Existing authorization governs the covered rows; only uncovered decisions stay pending.

## Execute and close

Pass the record and existing row authorization to `absorb`; it owns scoped
execution, `wiki-compile`, current-context confirmation, project/document rules,
task deduplication/read-back, writing workflows and durable receipts. Do not
maintain a second executor here. Only confirmed results complete rows; pending
facts or unavailable targets stay in the record. A repeat capture never creates
already-confirmed tasks, seeds or source records.

Resolve source identity across intake and retained-source storage before staging
or filing. Once all authorized routes complete or are explicitly declined,
absorb files the original transcript into the policy-configured raw archive,
repairs references/manifests and verifies content. Pending routes leave intake
available. Ingestion status records compiler outcomes only. Preserve partial
coverage; a missing optional input does not itself prevent completion. A retained
transcript stays primary evidence and is never excluded just because capture
finished. Source filing and failed link repair remain pending until verified.

Update the meeting record's results in place throughout review, partial execution
and completed absorption. It stays in its meeting folder; research's
output-to-raw/derived retention rule does not apply to it. Verify attribution,
coverage, source links, saved task dates/targets and writing receipts; report
pending confirmations and distinct source/record paths. Use local Git and
delivery rules. This skill does not schedule imports or create an automation.
