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

Released as [v0.15.5](https://github.com/coreyfloyd/hippocampus/releases/tag/v0.15.5)
from commit `b1e2fe22baef54ee9c0e497270fa3d075de72f1b` on 2026-11-16.
The annotated remote tag resolves to that commit. Manual exact-head review and
independent evaluation passed with no findings. Both the
[PR-head CI](https://github.com/coreyfloyd/hippocampus/actions/runs/43943322476)
and [release-head CI](https://github.com/coreyfloyd/hippocampus/actions/runs/43943612178)
passed on Ubuntu and macOS on their first attempts. Targeted independent
verification recorded 140 passing tests and one optional skip.

The maintainer approved this exact release before its checksum was signed with
the dedicated signing subkey. The temporary signing home was removed. Exactly
six public assets were downloaded fresh, matched the approved originals
byte-for-byte, and passed the downloaded signature/checksum verifier.
Archive SHA256: `8384ee68a511c11fde53bb1538dd902b6393b8ed9b83f97bbd78ff91175247d4`.
Checksum-file SHA256: `c3cfb019cdcc95686b0b480aedd72f860beb04c2fc1c6721e9b599b0295b33b3`.

The first deployment node installed from those verified public assets. Its
Claude registration was updated through the documented helper after backup,
and native installation verification passed. Its generated decision-policy
source now contains the one-home guidance. Other nodes use the separate
normal release-propagation change. Publication and deployment evidence is
recorded on [hippocampus234](https://github.com/coreyfloyd/hippocampus/issues/234).

Previous publication: [v0.15.4](https://github.com/coreyfloyd/hippocampus/releases/tag/v0.15.4).
The preceding candidate record remains in
[repository history](https://github.com/coreyfloyd/hippocampus/blob/v0.15.4/RELEASE_CANDIDATE.md).

## Release-note draft

Hippocampus v0.15.5 updates improve-harness rule placement: a rule placed in
the system prompt or output style lives only there. Remove copies from lower
rungs so the highest, most effective placement is the rule's only home.

The shared guidance applies to Claude Code and Codex. This release does not
move installed rules or change package paths, hooks or knowledge profiles.
