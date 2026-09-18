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

- [ ] Complete the verification commands above from the candidate commit.
- [ ] Tag the exact pushed commit as `v0.8.3`.
- [ ] Maintainer signs the candidate using `HIPPOCAMPUS_GPG_KEY`.
- [ ] Verify the signed archive and published release assets before announcing.
