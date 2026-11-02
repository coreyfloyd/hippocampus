# Codex limits and loading

Checked 2026-10-12. Measure only the Codex session's loaded files. Auto-loaded
instructions and skills/agent definitions read in full are in context; a
listed-only skill gets the description check only. Parent sessions resolve and
measure every required role path themselves; report an unresolved path, not a size.
Codex has no known output-style equivalent as of 2026-10-12.

| File | Limit | Unit |
|---|---:|---|
| Each project AGENTS.md or rules/required role file | 200 | lines |
| Combined project AGENTS.md chain, root to session start folder | 32 KiB (32,768) | UTF-8 bytes |
| User-level ~/.codex/AGENTS.md | 32 KiB (32,768) | UTF-8 bytes |
| SKILL.md body (exclude frontmatter) | 500 | lines |
| SKILL.md body (exclude frontmatter) | 20,000 | UTF-8 bytes |
| Skill description | 1,024 | characters |
| agents/*.toml, whole file, and each required role file | 200 | lines |

The default `project_doc_max_bytes` is 32 KiB; text past the combined project
budget is silently dropped. Check the chain even if every member is under 200
lines. The user-file byte check and 200-line rules/agent thresholds are this
skill's review policy; do not claim the project-chain setting is a per-file cap.
Report lines, words and bytes together; trigger only strictly above each limit.
Use the session's actual discovery chain, including override/fallback selection,
not every file named AGENTS.md found on disk. Measure the configured user file
separately, never include it in the project-chain total.

Situational material moves behind a pointer by default. Offer a nested AGENTS.md
only after the user **confirms** Codex sessions for that area **start** in that
folder: discovery walks from the repository root down to the session's start
folder once at session start, not whenever matching files are touched. Do not
assume nested instructions cover sessions started at the root.

When Codex reports shortened skill descriptions, report its skill-listing budget:
2% of context window, or 8,000 characters if unknown, and the largest descriptions
loaded. This has no per-file automatic trigger. Do not fabricate a truncation
notice or measure descriptions absent from the session's listing.

The skill body triggers a review when either its line or byte limit is exceeded.
The 20,000-byte threshold approximates Anthropic's “Under 5k tokens” guidance for
Level 2 instructions using approximately 4 UTF-8 bytes per token. This is a review
policy shared by both tools, not an exact token count or a vendor truncation cap.

Sources (checked 2026-10-12; skill byte guidance checked 2026-10-17):

- [Agent Skills overview](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview):
  Level 2 instructions (the SKILL.md body) under 5k tokens; the byte conversion
  above is an approximation.

- [Codex AGENTS.md](https://developers.openai.com/codex/guides/agents-md): project
  discovery from repository root to start folder and `project_doc_max_bytes`
  (32 KiB default). Per-project-file 200-line checks are this skill's policy.
- [Codex skills](https://developers.openai.com/codex/skills):
  listing budget and description rendering; this is a shared listing budget,
  not a per-file review trigger.
- [Agent Skills specification](https://agentskills.io/specification): description
  maximum of 1,024 characters in both tools.
- [Skill best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices):
  body under 500 lines, shared skill-authoring guidance, not a Codex truncation cap.

## Removal review (sources checked 2026-10-29)

Apply `references/removable-rules.md` (relative to the skill directory) before
Redundancy: classify defaults, check enforcement, and test dated rules for
supersession. Every finding names system-prompt text, a hook, or a superseding
mechanism as its basis. A user or scheduled review may request an under-limit
file; the user-presence and edit-approval requirements still apply.

- [Claude Code best practices](https://code.claude.com/docs/en/best-practices)
  (checked 2026-10-29): each instruction consumes attention; default to removing
  IMPORTANT/MUST/NEVER rules and propose hooks for zero-exception rules,
  specifying both tools' halves.
- [Fable 5 prompting](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-fable-5)
  (checked 2026-10-29): reconsider older prescriptive instructions when current
  defaults suffice; retain the reason and prefer a brief judgment criterion.
- [Agent Skills best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices)
  (checked 2026-10-29): its “MUST filter” advice predates Claude 5; do not treat
  it as a mandate to retain capitalized emphasis.

Read the available Codex system instructions for the default-behavior test;
report unavailable prompt/style coverage. Inspect Codex enforcement entries.
The Anthropic sources above motivate this shared review policy; they describe
Claude behavior, not evidence of Codex defaults. Use current Codex prompt text
to support a Codex default-behavior finding.
