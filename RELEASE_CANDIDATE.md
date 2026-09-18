# Release candidate review

## Scope

`0.8.3` closes a gap in `wiki-audit`'s structural-health pass. The audit read the
session cache (`hot_file`) for context at the start of a run but never checked it
against the profile-declared word cap or staleness threshold. A cache many times
over its cap was therefore never surfaced by the audit — the one read-only pass
whose job is to surface structural health — so the breach could accumulate
indefinitely. In one knowledge base the session cache had grown to roughly twelve
times its stated cap with no audit ever reporting it.

The release adds a session-cache health check to `wiki-audit` step 4 (structural
health): it reads the word cap and staleness threshold from the local policy body,
reports the cache's word count against the cap and the count of bullets carried
past the staleness threshold, and treats an undeclared cap as an observation
rather than a failure. The audit remains read-only — it surfaces cache bloat and
does not cull; culling belongs to the authorized writer's session-end step.

Tracking: [hippocampus#22](https://github.com/coreyfloyd/hippocampus/issues/22).

## Compatibility

No installer, profile, package-path, or contract-file change. This release is
skill prose only: `skills/wiki-audit/SKILL.md`. A valid v0.8.2 installation
upgrades in place.

The check reads the cap and staleness threshold from the local policy body a
knowledge base already declares; a base that declares neither sees the cache word
count reported as an observation, unchanged behavior for everything else.

The signing key material and fingerprint are unchanged.

## Verification

- `bash tests/test-contracts.sh`
- `bash tests/test-install.sh`
- `bash tests/test-release.sh`
- `swift test` in `skills/transcribe/tools/apple-speech`
- `git diff --check`

## Release-note draft

`v0.8.3` teaches `wiki-audit` to check the session cache against its own limits.
The audit already read the session cache for context; it now also reports the
cache's word count against the profile-declared cap and counts bullets carried
past the staleness threshold, treating an undeclared cap as an observation. The
audit stays read-only: it surfaces cache bloat and never culls.

Before this, a session cache could grow far past its stated cap with no audit
pass ever flagging it. Updated: `wiki-audit` only. No installer, profile, or
contract-file change.

## Publication checklist

- [x] Complete the verification commands above from the candidate commit.
- [x] Tag the exact pushed commit as `v0.8.3`.
- [x] Maintainer signs the candidate using `HIPPOCAMPUS_GPG_KEY`.
- [x] Verify the signed archive and published release assets before announcing.

## Publication result — 2026-09-17

Published [v0.8.3](https://github.com/coreyfloyd/hippocampus/releases/tag/v0.8.3) from
commit `65e09db767ed96474f46b2e5ab8a2e5f3319eb79`. The annotated tag and remote main both
resolved to that commit before the build (peeled tag verified local and remote). Contract,
install, and release suites passed on the MacBook against that commit; Swift 5/5;
`git diff --check` clean; the documentation sweep found nothing.

Corey signed; the agent verified, published, and installed. All six public assets
downloaded and verified (`hippocampus-0.8.3.tar.gz: OK`; scripts and key byte-identical to
the checkout). Installed and verified on all three machines from the verified assets:
MacBook locally, mini1 and mini2 with the assets copied over SSH. Each resolves `current`
to `releases/0.8.3` and the installed `wiki-audit` carries the session-cache health check.

Closes [hippocampus#22](https://github.com/coreyfloyd/hippocampus/issues/22).
