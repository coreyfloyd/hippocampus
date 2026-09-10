---
profile_version: 4
knowledge_root: /absolute/path/to/knowledge
hot_file: wiki/hot.md
operation_log_file: docs/log.md
decision_log_file: docs/DECISIONS.md
wiki_followup_destination: "Describe the backlog or task route for knowledge-base maintenance."
artifact_followup_destination: "Describe the task system and routing rule for research findings that affect another project."
# The wiki is optional and enabled by default. To disable it, uncomment the
# line below exactly as written, and remove hot_file and wiki_followup_destination.
# wiki_enabled: false
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
free-form local policy body after the validated YAML frontmatter. The required
frontmatter fields configure the portable session cache, operation log,
decision log, and two independent follow-up destinations; use this body to
define their local shape.
