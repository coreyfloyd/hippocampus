---
name: hippocampus-set-up
description: Guide a user through configuring or repairing a Hippocampus knowledge root and profile. Use after installation, when setup is incomplete, or when the user wants to understand or change how the research workflows store and route work.
---

# Configure Hippocampus

Configure the system through a conversation. The purpose of this skill is not merely to produce a valid file: help the user understand the storage model, make the choices that belong to them, and see how those choices affect later research and knowledge workflows.

The installed, version-matched template is [`profiles/karpathy-wiki.example.md`](../../profiles/karpathy-wiki.example.md). The canonical structural check is [`scripts/validate_profile.py`](../../scripts/validate_profile.py). Resolve both relative to this skill so the configuration matches the active package release.

## Explain the model first

Before asking for values, explain that one knowledge root always contains:

- `raw/`: selected source material and provenance;
- `output/`: durable research artifacts and audit reports awaiting review or distribution;
- `docs/`: AI-maintained operating records, including the operation log and decision log.

Explain the main flow: research creates an inline answer or an artifact; an approved distribution step moves useful findings to named targets or follow-up work, and — when the wiki is enabled — to the wiki.

## Ask whether to use a wiki

Before asking for any wiki-specific value, describe the wiki and its alternative in neutral terms and let the user choose. Neither option is the default or the recommendation:

- **With a wiki**: a `wiki/` folder holds compiled, atomic articles connected
  by Obsidian-style wikilinks, plus `wiki/hot.md` as the recent-context entry
  point. `research-absorb` and `knowledge-capture` can route selected findings
  into it, and `research-to-wiki` and `wiki-audit` compile and audit it.
  Wikilinks are a portable Markdown convention either way; Obsidian is an
  optional client for browsing the result.
- **Without a wiki**: no `wiki/` folder, no wiki-only profile fields, no wiki
  routing in absorption plans or knowledge captures, and `research-to-wiki`
  and `wiki-audit` refuse to run. `raw/`, `output/`, `docs/`, and the rest of
  the research and distribution workflow are unaffected.

If the user declines the wiki, ask none of the wiki-only questions below (the
wiki-maintenance route or whether they use a wikilink-aware client).

## Inspect before asking

Read `~/.config/hippocampus/profile.md` if it exists. Inspect referenced paths without modifying them. Distinguish among:

- no profile;
- a structurally invalid or incomplete profile;
- a valid profile whose local policy may still need clarification;
- a requested change to an existing configuration.

Do not assume that an existing directory is disposable or dedicated to this package. Preserve existing files and the free-form profile body unless the user explicitly approves changing them.

## Discuss the user-owned choices

Ask only for choices that cannot be inferred safely, and explain each before requesting it:

1. The absolute knowledge-root location.
2. When the wiki is enabled, the route for wiki-maintenance follow-ups.
3. The independent route for research findings that require work in another project.
4. Any local policy the agents should follow: taxonomy, source-library routing, output naming, operation/decision log formats, and local boundaries.
5. When the wiki is enabled, whether the user plans to use Obsidian or another wikilink-aware client. This changes the usage guidance, not the profile schema.

When the wiki is enabled, the two follow-up routes may be different and must be concrete enough for another agent to execute. Do not accept the unchanged instructional placeholders from the example profile as configured destinations.

## Present the complete change before writing

Show the proposed values and an exact mutation list: directories to create, files to create, profile fields to add or change, and policy-body edits. Call out everything that already exists and will be preserved.

When the user declines the wiki, the mutation list contains no `wiki/` directory, no `wiki/hot.md`, no `hot_file`, and no `wiki_followup_destination`. It contains `raw/`, `output/`, `docs/`, the operation log, the decision log, and the profile with `wiki_enabled: false` recorded. When the user accepts the wiki, the mutation list adds `wiki/`, `wiki/hot.md`, `hot_file`, and `wiki_followup_destination` to that same base.

Do not write or change configuration until the user approves that complete proposal. Installation and configuration are separate authorization boundaries; the fact that the package is installed is not approval to create a knowledge root.

## Apply an approved configuration safely

After approval:

1. Create only missing canonical directories: `raw/`, `output/`, and `docs/`, plus `wiki/` when the wiki is enabled.
2. Create only missing state files: `docs/log.md` and `docs/DECISIONS.md`, plus `wiki/hot.md` when the wiki is enabled. Never truncate them.
3. Create or update `~/.config/hippocampus/profile.md` from the active example schema. Use root-relative state paths and preserve unapproved frontmatter values and body content. When the wiki is declined, set `wiki_enabled: false` and omit `hot_file` and `wiki_followup_destination`; when it is enabled, omit `wiki_enabled` (or set it to `true`) and include both wiki fields.
4. Run the active `scripts/validate_profile.py` against the resulting profile.
5. If validation fails, report the exact failure and propose the smallest repair; do not replace the profile wholesale.
6. If validation succeeds, summarize the configured root and routes, then teach the user one short first workflow appropriate to their goal. When the wiki is declined, the summary and that first-workflow teaching mention no wiki.

Structural validation proves that the required paths and fields exist. It does not prove that the local taxonomy, route descriptions, or operating policy are useful; confirm those meanings conversationally.

## Enable or disable the wiki later

When an existing profile is valid, offer to change its wiki state as part of a
requested-change conversation. Both directions go through the same
present-then-approve gate as any other change:

- **A wiki-disabled profile**: offer to enable the wiki. If accepted, ask only
  the wiki-only questions from Discuss the user-owned choices (the
  wiki-maintenance route and whether the user uses a wikilink-aware client),
  then propose creating `wiki/` and `wiki/hot.md` and adding `hot_file` and
  `wiki_followup_destination` to the profile. Apply only after approval.
- **A wiki-enabled profile**: offer to disable the wiki. If accepted, propose
  removing `hot_file` and `wiki_followup_destination` from the profile and
  recording `wiki_enabled: false`. Never delete or modify `wiki/` or anything
  in it — disabling only changes the profile.
