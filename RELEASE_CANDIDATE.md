# Release candidate: 0.15.5

## Scope

This patch updates the improve-harness implementation ladder to keep a rule
only at its highest, most effective placement, tracked by
[hippocampus234](https://github.com/coreyfloyd/hippocampus/issues/234).

## Included

- Rung 4 makes the system prompt or output style the only home of a rule placed
  there and requires removing copies from lower rungs.
- The requirement to keep a full rule at a lower home is removed. The existing
  one-home recording guidance continues to apply.

## Compatibility

The shared skill text applies to Claude Code and Codex. Package paths, knowledge
profiles, hooks and session contracts are unchanged. This is not the public
launch of session features. No installed user rules are moved by this release;
the skill guides future placement and deduplication work.

## Verification and publication state

Candidate preparation is in progress. The release has not been signed, tagged
or published. Exact-head verification and review results will be recorded on
[hippocampus234](https://github.com/coreyfloyd/hippocampus/issues/234).

Previous publication: [v0.15.4](https://github.com/coreyfloyd/hippocampus/releases/tag/v0.15.4).
The preceding candidate record remains in
[repository history](https://github.com/coreyfloyd/hippocampus/blob/v0.15.4/RELEASE_CANDIDATE.md).

## Release-note draft

Hippocampus v0.15.5 updates improve-harness rule placement: a rule placed in
the system prompt or output style lives only there. Remove copies from lower
rungs so the highest, most effective placement is the rule's only home.

The shared guidance applies to Claude Code and Codex. This release does not
move installed rules or change package paths, hooks or knowledge profiles.
