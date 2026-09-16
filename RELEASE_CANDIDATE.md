# Release candidate review

## Scope

`0.8.2` closes an ambiguity in the `research-absorb` raw-staging contract. The Wiki Addition rule said to place "the selected external source material and provenance" in `raw/research/` without defining material. In one knowledge base, eight absorbs on 2026-09-12 staged a 30-line agent summary with a NotebookLM source id and no page text, while four absorbs on 2026-09-15 staged full page extractions, both under the same 0.8.1 wording. A summary-only staged file leaves the knowledge base with no copy of the source and no way to re-verify the articles compiled from it.

The release defines the staged file as the extracted source text (page extraction, transcript, or file conversion) under provenance frontmatter. An agent summary may sit above the text as its own section but never replaces it, and a NotebookLM source id is a pointer, not a copy. `research-to-wiki` now refuses a summary-only raw file as compile input and asks for the extraction first.

Tracking: [hippocampus#21](https://github.com/coreyfloyd/hippocampus/issues/21).

## Compatibility

No installer, profile, package-path, or contract-file change. This release is skill prose only: `skills/research-absorb/SKILL.md`, `skills/research-absorb/references/artifact-contract.md`, `skills/research-to-wiki/SKILL.md`, and the matching README paragraph. A valid v0.8.1 installation upgrades in place.

Existing raw files staged as summaries are not rewritten by the release. A knowledge base that holds them backfills the extracted text itself; `research-to-wiki` will refuse them until it does.

The signing key material and fingerprint are unchanged.

## Verification

- `bash tests/test-contracts.sh`
- `bash tests/test-install.sh`
- `bash tests/test-release.sh`
- `swift test` in `skills/transcribe/tools/apple-speech`
- `git diff --check`

## Release-note draft

`v0.8.2` defines what `research-absorb` stages in `raw/research/` for a Wiki Addition: the extracted source text under provenance frontmatter. A summary alone, or a NotebookLM source id alone, is no longer a valid staged source, and `research-to-wiki` refuses such a file as compile input until the extraction is present.

The previous wording let two sessions read the same rule two ways, one staging summaries and the other staging full extractions. Only the second leaves the knowledge base able to re-verify its compiled articles without the external notebook.

Updated: `research-absorb` and its artifact contract, `research-to-wiki`, and the README's absorb paragraph. No installer, profile, or contract-file change.

## Publication checklist

- [x] Complete the verification commands above from the candidate commit.
- [x] Tag the exact pushed commit as `v0.8.2`.
- [x] Maintainer signs the candidate using `HIPPOCAMPUS_GPG_KEY`.
- [x] Verify the signed archive and published release assets before announcing.

## Publication result — 2026-09-16

Published [v0.8.2](https://github.com/coreyfloyd/hippocampus/releases/tag/v0.8.2) from commit `03aebb8532baa300d8fc491c7bdbc8dc68010545`. The annotated tag and remote main both resolved to that commit before the build. Contract, installer, and release suites passed on the MacBook against that commit; Swift 5/5; `git diff --check` clean. The documentation sweep found one README paragraph still describing staging without the text requirement and it was aligned in the same commit.

Corey signed; the agent verified, published, and installed. All six public assets downloaded and verified (`hippocampus-0.8.2.tar.gz: OK`, scripts and key byte-identical to the checkout). Installed and verified on all three machines: MacBook from the published assets; mini1 and mini2 from the same verified assets copied over SSH, because mini1's GitHub token was rate-limited at install time. Each resolves `current` to `releases/0.8.2` and the installed `research-absorb` carries the extracted-text requirement.

Closes [hippocampus#21](https://github.com/coreyfloyd/hippocampus/issues/21).
