# Release-signing instruction cleanup — 2026-11-17

## Scope and outcome

Text-only cleanup of release-owner instructions. Exact human SIGN approval of a
frozen candidate remains mandatory. The operator signs only its checksum with
a dedicated expiring signing-only subkey from the managed-secret service on
the configured signing node. The maintainer is never asked to run signing
commands. (validated: documentation diff against base `277ddcc`)

The preferred operation is not yet delivered. The runbook specifies its contract
without inventing an installed CLI. The temporary already approved fallback
requires the operation owner's approved procedure and safe receipt reference;
credential retrieval stays inside a deterministic process, passphrase transfer
uses a descriptor, and GnuPG uses a temporary 0700 home with cleanup on every
exit. Verification must establish the unchanged pinned primary and authorized
unexpired subkey. Failures remain operator-owned repair. No primary export,
approval bypass, rebuilding approved bytes, extra uploads, or verifier changes
are permitted. (validated: maintainer direction and runbook diff)

## Whole tracked-tree inventory

Searched every current tracked path, including source, docs and fixtures, using
`git ls-files -z` piped to `xargs -0 rg -L -n -i` with these alternatives:
`pinentry`, `GPG_TTY`, `never.*sign`, `sign.*never`, `manual.*sign`,
`human.*sign`, `maintainer.*sign`, `sign.*maintainer`,
`HIPPOCAMPUS_GPG_KEY`, and `signing.operation`. A separate search covered
secret-key and signing-subkey wording. `rg -L` follows symbolic links.
(validated: successful inventory command output)

- **F1 — Live owner instructions:** corrected contradictory manual-signing and
  interactive-terminal requirements in [RELEASING.md](../../RELEASING.md) and
  [the rollout guide](../hippocampus-rollout.md). Root agent rules contain no
  release-signing directions requiring correction. (validated: inventory and
  root instruction read)
- **F2 — Historical fixture:** retained the old manual-signing text in the
  [fixture runbook](../../tests/fixtures/session-release/RELEASING.md), adding a
  prominent non-authoritative notice pointing agents to the live runbook.
  Fixture scripts and tests remain unchanged. (validated: diff)
- **F3 — Other matches:** historical release records, implementation reports and
  review pages describe past work; installation prose describes verification;
  release scripts and tests exercise build/sign/verify behavior. Other fixture
  hits concern unrelated platform signing or example prose. These are not live
  owner instructions and remain unchanged. The existing builder rebuilds inputs,
  so the live runbook explicitly prohibits its signing mode after approval.
  (validated: inventory, matched documents and builder read)

## Validation and delivery boundary

All repository-required quick checks passed: `git diff --check`, release metadata
check, fold-name checks (5 tests), public-doc checks (14 tests, 1 skipped), and
skill-surface checks. Changed-document relative links and anchors passed using
`uv run --quiet scripts/check-doc-links.py`. (validated: local command exits 0)

The full suite belongs to pull-request CI, with at most two attempts. No
implementation, scripts, tests, signing credentials, provisioned state, release
assets, tags, publication, installation or deployment were changed. No generator,
reviewer, evaluator or subagent was launched for this direct text edit. The
parent operation owner receives the PR, exact head and validation evidence and
owns merge and deployment. (validated: changed-path diff and session actions)
