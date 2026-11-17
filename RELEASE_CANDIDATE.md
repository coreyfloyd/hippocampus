# Release candidate: 0.15.6

## Scope

Fix a response-reading defect in the Codex installation trust verifier,
tracked by [hippocampus90](https://github.com/coreyfloyd/hippocampus/issues/90).
A complete `hooks/list` response arriving beside a notification can remain
in a text buffer while the helper waits on an empty OS pipe, incorrectly
reporting no response after 15 seconds. (validated: isolated real-pipe test
against the unchanged production helper)

## Included

- Read newline-delimited protocol frames from one explicit byte buffer and
  drain complete frames before waiting for more pipe input.
- Cover a notification and response in one write, partial frames, multiple
  notifications, EOF, and rejection of an untrusted hook with controlled
  subprocess fixtures.
- Update the package version to 0.15.6 and regenerate Claude plugin metadata.

## Compatibility

The Codex installer's response reader changes. The request deadline remains
15 seconds, and trust hashing, rollback behavior, hook registrations and
session contracts retain their existing behavior. Claude Code uses the same
package version and retains its existing installation and hook contracts.
This is not the public launch of session features. (validated: candidate diff;
affected test evidence recorded below)

The controlled reproduction establishes a reader defect. It does not prove
that this defect caused every historical timeout reported on the issue.
(inferred: historical failures lack the matching protocol transcript)

## Verification and publication state

Published [v0.15.6](https://github.com/coreyfloyd/hippocampus/releases/tag/v0.15.6)
on 2026-11-17 at 07:00:28Z from annotated tag `v0.15.6`, commit
`277ddcc7e711ca2a5b4878b55a76007af4fcdbd4`. The merged tree matches reviewed
candidate `6b2b4e1309b4a0cd512da8225cd5dc10bae3227f`. Independent review and
runtime acceptance passed without findings; first-attempt full CI
`43981105569` passed on that candidate head on Ubuntu and macOS. Full suites were not run locally.
(validated: merge/tree comparison, independent receipts and CI results)

The maintainer approved this exact candidate with SIGN, relayed by the release
coordinator at 06:47Z, and explicitly directed agent signing through the already
provisioned signing-subkey custody path at 06:56Z. The earlier interactive human
command was withdrawn before execution. No secret material was returned in tool
output. The checksum signature uses subkey
`94FF9B623792B24645AB7928F8874E0B2C22A761`; verification matched pinned primary
`09674AFF392661238F4ACBD9F32B3A412CD5EFC5`. The private temporary GnuPG home was
removed after signing. (validated: approval relays and signing receipt)

Exactly six public assets were freshly downloaded, compared byte for byte to
the prepared upload files, and accepted by the unchanged package verifier:

| Asset | SHA256 |
|---|---|
| `hippocampus-0.15.6.tar.gz` | `37eb39725297c1cd754839e3a1aa771baaa7276e8fcefc997813872f0400c6e6` |
| `hippocampus-0.15.6.tar.gz.sha256` | `2994567db0081d053a4409815729623755b0b0f107c3356fe950b02a92ce7fc4` |
| `hippocampus-0.15.6.tar.gz.asc` | `9858d448455d136dcccdea8a206dfabd33fc4c7afd9ef05faafed223ab29883a` |
| `hippocampus-release.asc` | `d8e7989c21df5f182b2033afaa590bb4beaf05544125c601247c71b1b7f7974d` |
| `install-release.sh` | `30ca277e11d46a0e281aeca204d947b96cbdfbfede1a67eddf4959bc34b33ae3` |
| `verify-release.sh` | `d0a4ad1ff98bf37ff22fbd37d7803e13d9f85062f0e3b9c78c5c9878a9f158d6` |

(validated: fresh public download, six-file inventory, byte comparisons,
signature/fingerprint verification and archive checksum check, all exit 0)

The first publication invocation refused before any remote write because its
notes file was absent after an overly strict archive-root check. The check was
corrected to accept the root directory entry and every member beneath it;
the subsequent invocation published the verified assets above. No tag or
published asset was replaced. (validated: command outcomes and release readback)

Live activation and fleet propagation are separate from publication and remain
to be verified. Historical timeout attribution remains unconfirmed.

Previous publication: [v0.15.5](https://github.com/coreyfloyd/hippocampus/releases/tag/v0.15.5).
The preceding publication record remains in
[repository history](https://github.com/coreyfloyd/hippocampus/blob/v0.15.5/RELEASE_CANDIDATE.md).

## Release-note draft

Hippocampus v0.15.6 fixes a Codex installation trust-verification error that
could report a missing response when a notification and the complete response
arrived together. The verifier now reads complete protocol frames from an
explicit byte buffer. The 15-second deadline and hook trust policy are unchanged.

Claude Code's installation and hook contracts are unchanged. This patch does
not introduce the public launch of session features.
