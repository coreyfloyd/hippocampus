# Release candidate: 0.12.0

## Scope

This candidate covers the changes since v0.11.0:

- Offer wiki candidates from project-filed research ([hippocampus#53](https://github.com/coreyfloyd/hippocampus/issues/53)). `feature-research`, `feedback-research` and a `dev-research` answer persisted to a file end with an optional `## Wiki candidates` table when their public sources carry knowledge reusable outside the project: each row names a Sources entry, the reusable finding and a proposed wiki target. Completion reports the table as a proposed distribution. After approval, `absorb` re-fetches each approved row's source into the research raw folder and invokes `wiki-compile` with that subset. The project document stays at its project path, unedited, and is never compile input; row receipts go to the operation log. The section is defined once in `skills/absorb/references/wiki-candidates.md`.
- State what the Karpathy-wiki contract enforces in code and what it only instructs, with two limits: provenance is not claim evidence, and a distribution receipt is not a multi-file transaction.
- Record the v0.11.0 publication in `docs/releases/0.11.0.md`.

## Compatibility

Profile version remains 4; no profile field is added or changed. The Wiki candidates section is added only when the validated profile has a wiki configured and a cited public source supports a reusable finding, so existing deliverables and profiles without a wiki are unchanged. `research-absorb` still does not apply to the deliverable documents themselves. Installation adds one reference file, `skills/absorb/references/wiki-candidates.md`. Both supported clients receive the same package. The public signing key and fingerprint are unchanged.

## Verification

Run the exact candidate checks in `RELEASING.md`, plus `python3 tests/test-compose-rules.py`, `python3 tests/test-capture-absorb.py` and `python3 tests/test-public-docs.py`, the documentation sweep and the public commit-range scan. Final commit identifiers and results are recorded in the release-session evidence; publication evidence is appended after release to avoid a self-referential commit.

Previous publication evidence: [0.11.0](docs/releases/0.11.0.md), [0.10.0](docs/releases/0.10.0.md).

## Release-note draft

Hippocampus v0.12.0 lets project-filed research feed your wiki. Design inputs from `feature-research`, decision memos from `feedback-research`, and `dev-research` answers saved to a file can now end with a short Wiki candidates table: the public sources they cite, the finding each supports that holds outside the project, and where it might go in the wiki. You approve the rows you want, and `absorb` fetches those sources fresh and compiles them, while the project document stays exactly where it was.

Nothing changes for profiles without a wiki, and no profile migration is needed. Both supported clients receive the same package.

## Publication checklist

- [x] Verify and commit the candidate; resolve the public commit-history scan.
- [ ] Complete independent review, evaluation and public-communication approval. Not run for 0.12.0: the maintainer directed the release in an interactive session; the candidate had the runbook checks and documentation sweep only.
- [x] Merge the reviewed candidate and tag its exact commit as `v0.12.0`.
- [x] Maintainer signs using `HIPPOCAMPUS_GPG_KEY` and `scripts/build-release.sh`.
- [x] Verify signed assets, publish, and independently verify downloaded assets.
- [x] Install and verify the signed release in both supported clients.

## Publication

Published 2026-10-31 as a public, non-draft, non-prerelease release.

- Tag: `v0.12.0`, annotated; peeled commit `a2c6d8771b439b089d86c1649a8524e67b7c0282`, equal to `origin/main` at publication. Its tree equals the tested candidate commit `baad26d`.
- Release: https://github.com/coreyfloyd/hippocampus/releases/tag/v0.12.0
- Assets (6): `hippocampus-0.12.0.tar.gz`, `hippocampus-0.12.0.tar.gz.sha256`, `hippocampus-0.12.0.tar.gz.asc`, `hippocampus-release.asc`, `install-release.sh`, `verify-release.sh`.
- Verification: local `scripts/verify-release.sh` passed against `dist/` before publication; the six downloaded public assets were verified in a fresh temporary directory (`cmp` on the key and both scripts, signature and checksum on the archive: OK). The archive lists 134 entries, all under `hippocampus/`, including `skills/absorb/references/wiki-candidates.md`.
- Installation: `install-release.sh` from the downloaded assets installed 0.12.0 on the maintainer machine; `current` resolves to the 0.12.0 release directory, and both clients' `feature-research` and `absorb` links resolve into it.
