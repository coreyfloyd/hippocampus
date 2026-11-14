# Release candidate: 0.15.4

## Scope

This patch adds opt-in literal rendering to the rule composer, tracked by
[hippocampus229](https://github.com/coreyfloyd/hippocampus/issues/229) and merged
through [PR230](https://github.com/coreyfloyd/hippocampus/pull/230).
An explicit target can select `render: "literal"` to embed the complete ordered
source bodies in its generated instruction file. Omitting `render`, or choosing
`"default"`, retains the existing provider-specific rendering.

## Included

- Per-target `render` selection and validation through the existing composer
  configuration interface.
- Literal source bodies, ownership and provenance using the existing rendering,
  source preflight, managed-block, staging and rollback mechanisms.
- Fixture coverage for provider parity, ordering, authored content, invalid
  selections, source failures, overlap, preservation, drift and idempotence.
- Configuration examples in [the knowledge guide](docs/knowledge-guide.md).

## Compatibility

Default Claude targets still generate source imports. Default Codex and OpenClaw
targets still generate source bodies. Consumers explicitly select literal targets
in their install or refresh declarations; this release changes no installed
user target by itself. Knowledge profiles, package paths, signing keys, skills,
hooks and session contracts are unchanged. This is not the public launch of
session features.

## Verification and publication state

Source candidate `b3397bc` completed independent evaluation with PASS, scores
8–9 and no findings or follow-ups. All 18 documented local checks passed,
including 2,561 passing pytest tests, 15 skips and 71 passing subtests.
[Source PR CI43640008060](https://github.com/coreyfloyd/hippocampus/actions/runs/43640008060)
completed successfully on Ubuntu and macOS on its first run.

Released as [v0.15.4](https://github.com/coreyfloyd/hippocampus/releases/tag/v0.15.4)
from commit `d2d1b069d9466107139737c5bc5d66dc832dff75`.
The annotated remote tag resolves to that commit. The maintainer signed the
checksum; fresh public downloads verified with the pinned signing fingerprint.
All six release assets are present: archive, checksum, checksum signature,
public key, install helper and verify helper. The helper/key assets match source.
Archive SHA256: `23fdd017d52bf2b0124663db816c862fe5e55f206feb66995fbdec6a6ff09ef3`.

Exact release-head local verification passed all documented checks and the
documentation sweep. [Release-head CI attempt 2](https://github.com/coreyfloyd/hippocampus/actions/runs/43643451245/attempts/2)
passed Ubuntu and macOS. Attempt 1 encountered the existing intermittent
`hooks/list` no-response timeout tracked in [issue90](https://github.com/coreyfloyd/hippocampus/issues/90);
its failure evidence is retained. No timeout-policy change is part of this release.
This publication does not activate any live installation.

Previous publication: [v0.15.3](https://github.com/coreyfloyd/hippocampus/releases/tag/v0.15.3).
The preceding candidate record remains in
[repository history](https://github.com/coreyfloyd/hippocampus/blob/8239444/RELEASE_CANDIDATE.md).

## Release-note draft

Hippocampus v0.15.4 adds opt-in literal rule-target rendering. Set
`render: "literal"` on an explicit composer target to generate complete source
text instead of composer-generated imports. Sources and extras retain their
order, and the generated file carries ownership and source attribution.

Existing defaults remain unchanged for Claude Code, Codex and OpenClaw.
Invalid render selections fail during preflight before any target is written.
The feature reuses the existing composition and refresh entry points.
