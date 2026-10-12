---
profile_version: 4
knowledge_root: /absolute/path/to/knowledge
hot_file: wiki/hot.md
operation_log_file: docs/log.md
decision_log_file: docs/DECISIONS.md
wiki_followup_destination: "Describe the backlog or task route for knowledge-base maintenance."
artifact_followup_destination: "Describe the task system and routing rules for source-derived actions, including meeting actions and research follow-ups."
# The wiki is optional and enabled by default. To disable it, uncomment the
# line below exactly as written, and remove hot_file and wiki_followup_destination.
# wiki_enabled: false
# Optional meeting inputs; each can independently be disabled. Use unquoted values.
# meeting_transcript_source: Connected meeting provider or supplied transcript
# meeting_event_source: Connected calendar provider
# meeting_note_path: notes/{date}.md
# A fixed local path, absolute path, or HTTPS Google Docs document link also works.
# A note path/link supplied for a specific meeting overrides this optional default.
# Without these fields, transcripts use supplied/available sources and event/note lookups are disabled.
# Optional meeting record settings. Defaults work with existing version-4 profiles.
# meeting_record_folder: meetings
# meeting_record_template: templates/meeting.md
# Templates are Markdown files: relative to the knowledge root, or explicit absolute paths.
# Record folders stay within the root; validation creates no files.
---

Copy to `~/.config/hippocampus/profile.md` and set `knowledge_root`.

## Optional local policy

This body is intentionally free-form and remains outside the public package.
Use it for personal taxonomy, source-library routing, output conventions,
knowledge-base operation rules, and blocked-channel routes — alternate
retrieval paths for channels the primary runtime cannot reach (for example,
"Reddit: delegate the read to <agent runtime with access>", or "browser
route: <the user's chosen browser and mechanism>" — the bundled Safari
helper is one implementation; a runtime's browser-automation tool or another
browser's scripting interface are equally valid), which the research skills
consult before accepting reduced coverage. Skills that read the profile read this
free-form local policy body after the validated YAML frontmatter. The required frontmatter fields configure the root, operation log, decision
log and source-derived action destination. Wiki-enabled profiles also require
the session cache and independent wiki-maintenance destination; omit those
wiki-only fields when the wiki is disabled. Use this body to define local entry
formats, optional knowledge search locations/rules and routing distinctions.

Meeting filing destinations may be overridden in this free-form local policy body,
without changing the three meeting input fields. For example: "Stage imported
meeting transcripts in raw/inbox/; after all authorized capture routes are
complete or declined, retain original transcripts in raw/archive/meetings/."
Choose paths that agree with your local source-library policy. Partial capture
work remains staged; retained transcripts remain primary evidence.


Local policy may also name transcript intake/archive destinations within `raw/`,
a writing workflow and writable destinations, templates/scoring, and the locations
to search for existing ideas, drafts and published material. No writing destination
is assumed. Local compile/audit modes, thresholds and coverage remain policy, not
new frontmatter fields. Missing optional meeting settings use the bundled minimal
template and `meetings/`; set up record defaults only when requested.

New meeting records use a date plus a meaningful meeting title, person or
subject (for example, `2026-10-09-public-contract-review.md`). Provider names
and kind suffixes such as `-transcript` belong in source provenance metadata,
not automatic title decoration. Retained transcripts use a meaningful subject;
a transcript and its record may share a filename in different folders.
Identity lookup reuses existing records and preserves user edits and paths,
even when a title changes on retry. Different meetings with the same title get
a stable identity suffix; filing refuses to overwrite different source content.
