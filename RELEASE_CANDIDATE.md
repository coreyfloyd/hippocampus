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

Candidate preparation only. The real-pipe regression failed before the fix
with `app-server returned no response for request 2` after 15.45 seconds.
Final affected-test and quick-check results are recorded in
[the investigation report](docs/reports/90-codex-reader.md).

Full-suite validation belongs to pull-request CI; it has not run locally.
Independent review, CI, exact-release approval, signing and publication are
pending. No release tag, signed artifact, publication or live activation was
performed during this preparation. (validated: bounded preparation scope)

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
