# Removable rules

Read before Redundancy in either tool. Apply these tests to every target rule,
even when the file is under its size limit. These are deletion candidates for
the user's decision, not permission to edit or to discard a safety boundary.

## Default behavior

Classify each rule before looking for repeated wording: default behavior for
the current model tier, a convention the model cannot infer, or a mechanism it
cannot guess. Read the running tool's available system prompt, instructions,
and output style alongside the comparison files. If a prompt or style is not
accessible, report the coverage gap; never invent its contents.

Default-behavior rules are deletion candidates, not compression candidates.
Each finding quotes the supporting system-prompt or output-style text and names
its source. Model reputation alone is not evidence that a rule is redundant.
Keep unguessable conventions and mechanisms for the remaining review steps.

## Enforcement

Resolve the shared config using `$CONTINUITY_CONFIG`, otherwise
`${XDG_CONFIG_HOME:-~/.config}/continuity/config.json`; an absent file is `{}`.
Read its optional string key `harness_enforcement_reference`: require an absolute
path or a `~/` path, expanding `~` to the current user’s home directory. Reject
ordinary relative paths as configuration errors; never resolve them against the
working directory. The shared reader is `python3 scripts/lib/handoff.py config-get harness_enforcement_reference` (script path relative to the continuity package).
An empty result means report **“no enforcement reference configured”**, inspect
hooks directly, and continue the review; this gap does not fail it.
Malformed config or an unreadable configured path is a coverage error to report,
not an absent key or evidence of enforcement.

Add the configured document to the comparison set. It lists hooks, gates, and
label families for Claude Code, Codex, and OpenClaw: what each enforces or
injects, which rules it makes redundant, and a superseded list. Check each
claim against the applicable tool and current mechanism; enforcement in one
tool alone does not justify deleting a cross-tool boundary. A finding names
the hook, gate, or label family and the rule it enforces or injects. Recommend
deletion of already-enforced rules rather than compressing them. If direct hook
inspection cannot establish coverage, report uncertainty and keep the boundary.

## Supersession

For every dated rule, compare its date with the reference's superseded list
and current hooks, gates, label families, and skills. Ask whether a mechanism
introduced after that date replaced the rule's purpose. Each deletion finding
names the superseding mechanism, its introduction date or ordering evidence,
and the replaced rule. Age alone does not justify removal. Report gaps in
chronology or coverage rather than assuming replacement.

## Why, examples, and emphasis

A why states the goal or consequence a rule protects. A dated incident account
is provenance: move it to the rule's ticket and retain at most one
repo-qualified link. Preserve the goal when removing the incident narrative.
Keep an example only when it carries a mechanism the rule cannot state, such
as an exact failing command form; reduce it to that clause. Several incidents
under one rule become their judgment criterion plus those mechanisms.

Default to deletion for IMPORTANT/MUST/NEVER rules; emphasis alone does not
justify keeping one. Preserve a distinct safety boundary with a stated reason.
For each emphasized rule record **delete, propose a hook, or keep**, with its
basis. A zero-exception rule gets a hook proposal specifying both Claude Code
and Codex halves; propose only, do not implement hooks or file tickets here.
The [Claude Code best-practices page](https://code.claude.com/docs/en/best-practices)
(checked 2026-10-29) explains why stronger emphasis does not repair an ignored
rule and why exceptionless constraints belong in hooks. Consult the running
tool's reference for source scope and model-specific prompting guidance.
