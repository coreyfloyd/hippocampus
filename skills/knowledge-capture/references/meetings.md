# Meeting capture mode

Preserve what happened in a meeting and carry its actionable outcomes into the configured knowledge and task systems. This is the orchestration step before compilation; `research-to-wiki` remains the compiler.

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

For enabled event lookup, match a supplied event identifier first; otherwise search the participant and meeting's local date, then read the complete primary event. Flag ambiguous matches rather than silently selecting one. Use the event for scheduled time, agenda, invitations, and source links; an invitation or accepted response does not prove attendance. The transcript establishes what was said and by whom. Do not mirror live calendar data where local policy prohibits it; retain a source pointer and match status instead.

For notes, a path or Google Doc link supplied for a particular meeting overrides `meeting_note_path`; the profile is only an optional default. Accept notes supplied separately for each meeting—never assume a shared directory. Resolve a relative profile path from the knowledge root, an explicit absolute path as given (including outside that root), and a supplied relative path from the request's declared base or working directory. If a local default contains `{date}`, substitute the meeting's local `YYYY-MM-DD`; fixed paths require no template. Check the selected source's actual identity and meeting relevance before applying it to multiple meetings. If the profile disables notes, an explicitly supplied note still authorizes reading that input.

Read a local note without creating or editing it. For a Google Docs link, use an available authorized document/Drive connector or supplied export and read the complete primary document with pagination as needed. A link does not prove access; report unavailable content and continue with the other sources instead of guessing or claiming the note was reviewed. Use no credentials workaround. Treat the user's observations as a separate source, preserve their date, and distinguish plans from actual outcomes. Missing notes are a coverage gap, not an invitation to invent a record. Historical intentions do not become current context without required confirmation.

Keep transcript evidence, event context, note observations, and coaching interpretations separately attributed. Surface conflicting dates, identities, or outcomes. If an enabled source is unavailable, continue with available evidence and report the gap; never silently claim three-input coverage. Do not fetch an explicitly disabled source unless the current request overrides that setting.

The request authorizes only its stated routes. A request to review a meeting does not by itself authorize messages, task writes, context facts, or a new engagement. Conversely, explicit directions to compile records, create todos, or archive reviews do not need a second generic approval. Ask only for a specific missing decision, disputed destination, or required confirmation; continue independent work.

## Capture and disposition

Archive complete source material in the configured raw intake with source link, meeting date/timezone, meeting ID, sensitivity, and ingestion tracking. Deduplicate by meeting ID or supplied source identity. Preserve private material and paraphrase it in derived notes according to local policy.

Build one disposition inventory covering all of these routes, even if a route has no items:

- **People and knowledge:** Current source-grounded biography plus dated conversation records. Include purpose/summary, coaching or advice actually delivered, the person's response, decisions, follow-up ownership, unknowns, and source references. Distinguish coaching, teaching, advice, referrals, and peer exchange. Strategies are observed actions; theoretical framework matches and causal explanations are interpretations. In-call intent is not later success. Preserve old records and compare changes before updating a biography. Resolve existing entities before proposing new ones. Match names, nicknames, and spelling against supplied context and known entities; never expand a shortened transcript name into an invented full name. If unresolved, preserve the source spelling and ask or mark the identity unknown.
- **Existing documents:** Identify project, context, content, or other files affected by the meeting. Apply only requested and rule-permitted updates. Record historical facts as dated history; ask for confirmation before treating old preferences or plans as current user context when local rules require it. Do not silently reword authored prose. Route project records through their existing workflow.
- **Actions:** Extract owner, next action, commitment versus suggestion, timing, dependencies, and supporting source. Keep separate contacts and next actions separate unless they share the same joint next step. Another participant's promise is not automatically the user's task; a relevant user task may be to check back. Conditional promises get a readiness check rather than an invented completion deadline. Dates belong to specific actions, not people records. Assign a date only when the user requests dates or a supported commitment or scheduling policy supplies one. When dates are requested but unstated, choose reasonable future planning dates, label them as internal follow-up targets, and explain each rationale while distinguishing source timing from discretionary scheduling; stale deadlines become current status checks. Do not create calendar events or send messages unless explicitly requested.
- **Open questions:** Preserve uncertain identities, one-sided assessments, tentative opportunities, and unverified claims. Do not infer consent, a contract, diagnosis, or completed outcome from a conversation.

Propose any route requiring approval as a concrete change. Existing authorization governs the covered rows; only uncovered decisions stay pending.

## Execute and close

For approved wiki work, invoke `research-to-wiki` on the curated primary sources with the resolved referents and dates. If the profile disables the wiki, use the configured permitted document routes instead; never create a wiki as a side effect. Mark a source ingested only after its actual compilation result is known.

For approved actions, load the available task workflow and discover write targets on the executing host. Search current tasks before creating one; enrich an exact existing match while preserving unrelated notes. Create or update each action with evidence, actionable wording, and an explicit due date when requested. Read back saved dates and targets; an unconfirmed write remains pending. Keep live task state in the task system, not mirrored in wiki or context. Report the saved actions and dates to the user.

A review produced in output stays there while approved work is incomplete. After all approved routes are completed or explicitly declined, move it to `raw/derived/` as an absorbed reference artifact with `use: artifact`, `compile_mode: exclude`, original path, and date. Update durable references without overwriting another archive. Compile from transcripts, never from the archived analysis. A completed review need not be created if dated people records and source tracking already preserve the work.

Verify source completeness, attribution, source links, document changes, and saved task receipts. Report compiled people/documents, observed coaching, dated user actions, pending confirmations, and archive paths. Persist knowledge-store changes using its local Git and delivery rules. This skill does not schedule recurring imports or create an automation.
