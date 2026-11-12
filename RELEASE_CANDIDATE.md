# Release candidate: 0.15.2

## Scope

This patch release prepares the bounded post-compaction restore fix from
[hippocampus185](https://github.com/coreyfloyd/hippocampus/issues/185).
Since v0.15.1, the source range contains this fix and its test repairs, plus
the existing documentation record of the v0.15.1 publication. No unrelated
runtime changes are included. This is not the public launch of session features.

Both Claude Code and Codex use the shared renderer. Small restore messages
remain unchanged. Oversized messages contain a bounded continuation or a
recoverable reference requiring a targeted read before acting. Complete filenames,
canonical handoff and ledger bytes, and unresolved decisions are preserved.
Unknown-schema and long-path fallbacks are bounded; direct-file and isolated
Python callers can load the adjacent renderer dependency.

Codex installation records the supported additionalContextLimit handler field
and normalizes that field when checking hook trust. Source output uses a
2,000 UTF-8 byte bound; a harness token threshold is a different measurement.

## Compatibility

Existing knowledge profiles, skill names, package paths and signing key remain
unchanged. This patch does not settle or delete retained items, change record
next_action semantics, or introduce a memory architecture. Actual model-visible
injection and current live harness limits remain unverified until the separately
authorized [required live check221](https://github.com/coreyfloyd/hippocampus/issues/221).
Both that check and parent185 remain open.

## Verification and publication state

Unsigned preparation only. No tag, signature, release publication, installation,
restart or activation has been performed for0.15.2. Version selection is the
maintainer's delegated release-preparation choice.

The immutable round3 CONDITIONAL PASS is bound to source commit
`5075020bcc71f2022ccf6fc2f71f91b912edcf2c`. The merged descendant adds only two
test-fixture corrections; production files are identical to that evaluated
source. It passed the two previously failing Linux cases, all ten Linux
long-path cases without skips, and wrapper and branch-scan shell suites on
Linux and macOS. These focused checks do not imply a complete CI pass.

Both authorized source CI attempts failed with introduced defects subsequently
corrected. An automatically triggered run on the final test-only descendant was
recorded and canceled under the explicit delivery exception. No third CI pass
is claimed. Release checks must run against the exact committed release
candidate and their real results remain in the release-session evidence.

The source PR is [222](https://github.com/coreyfloyd/hippocampus/pull/222).
Previous signed rollback assets remain v0.15.1; retain and verify them before
any separately authorized activation. Manual maintainer signing and coordinated
installation/live verification are separate gates.

Previous publication: [v0.15.1](https://github.com/coreyfloyd/hippocampus/releases/tag/v0.15.1).
Its publication record remains in the repository history at
[the signed-release record](https://github.com/coreyfloyd/hippocampus/blob/c885a66/RELEASE_CANDIDATE.md).

## Release-note draft

Hippocampus v0.15.2 bounds oversized post-compaction handoff messages in Claude
Code and Codex while preserving complete canonical handoffs and ledgers. Small
messages retain their previous output. When a full continuation cannot fit,
the restore requires reading the recoverable canonical file before acting.

The patch also repairs isolated Python module loading and the long-path test
fixtures. It does not change retained-item settlement or record continuation
semantics. Live model-visible restoration remains subject to the required
coordinated verification; this unsigned candidate is not an activated release.
