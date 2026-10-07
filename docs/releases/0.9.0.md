# Release candidate review

## Scope

`0.9.0` adds portable meeting capture and retained absorption records. `meeting-capture` is a thin entry point to knowledge-capture's shared meeting mode, rather than a second disposition workflow. It retrieves complete available transcripts, adds optional calendar and meeting-note context, and routes people/coaching records, permitted existing-document updates, actions, and open questions.

The three optional profile inputs are `meeting_transcript_source`, `meeting_event_source`, and `meeting_note_path`. Notes may be a fixed local path, an absolute path outside the knowledge root, a relative path, a local date template, or an HTTPS Google Docs document link. Explicit per-meeting note inputs override the profile default; no common meeting-notes directory is assumed. Sources remain separately attributed and read-only where required; inaccessible sources are reported.

Completed absorbed outputs now move to `raw/derived/` as reference artifacts with `use: artifact`, `compile_mode: exclude`, original path, and absorption date. Unfinished authorized work stays in output. The reference report is never primary compiler evidence. Existing archives are not automatically moved or recovered by installing the package.

Also included since v0.8.3: Python-based profile-validator invocation corrections, the explorable research runtime architecture map, and reconciled skill/install/migration documentation. The architecture map is refreshed for retained absorption records; the README diagrams meeting capture separately.

Tracking: [hippocampus#28](https://github.com/coreyfloyd/hippocampus/issues/28), building on [hippocampus#27](https://github.com/coreyfloyd/hippocampus/issues/27).

## Compatibility

Profile version remains 4. Existing published profiles need no migration. The unreleased development field `meeting_daily_note_path` is renamed to `meeting_note_path`; its validator error names the replacement. Default event lookup is disabled; default note lookup is absent unless a note is supplied. Transcript input uses supplied/available sources when unconfigured. Connectors are runtime capabilities, not installed by the profile.

The live installation route uses downloaded, signature-verified release assets. Candidate validation uses temporary homes; activating a development checkout requires explicit authorization. Both Claude Code and Codex receive the same skill and shared references. The public signing key and fingerprint are unchanged.

## Verification

Run against the exact candidate commit before tagging:

- `python3 tests/test-profile-meetings.py`
- `bash tests/test-contracts.sh`
- `bash tests/test-install.sh`
- `bash tests/test-release.sh`
- `swift test` in `skills/transcribe/tools/apple-speech`
- `git diff --check`
- Required documentation sweep and refreshed architecture-map checks

The meeting-note acceptance test failed on unsupported `meeting_note_path` before implementation. Final commit identifiers and completed evidence are recorded in the release-session issue; publication evidence is appended after release to avoid a self-referential commit.

## Release-note draft

Hippocampus v0.9.0 adds `meeting-capture`: preserve source-linked meeting and coaching records, route authorized document updates and follow-ups, and retain completed reviews. It shares knowledge-capture's disposition logic.

Configure transcript, calendar event, and notes independently. Supply a local note or Google Doc for an individual meeting, or set `meeting_note_path` as an optional profile default. A dated folder structure is optional. Missing or inaccessible inputs are reported, and inferred coaching analysis remains distinct from source evidence.

Absorbed research outputs are preserved in raw as excluded reference records instead of being deleted. Existing archives remain untouched. Profile version 4 remains compatible with published profiles; users of the unreleased `meeting_daily_note_path` field should rename it to `meeting_note_path`. Both supported agent clients receive the same workflow.

## Publication checklist

- [x] Complete verification and documentation sweep against the candidate commit.
- [x] Push and tag the exact candidate as `v0.9.0`.
- [x] Maintainer signs the candidate using `HIPPOCAMPUS_GPG_KEY`.
- [x] Verify signed assets, publish, and independently verify downloaded public assets.
- [x] Install and verify from signed assets.

## Publication status

Published [v0.9.0](https://github.com/coreyfloyd/hippocampus/releases/tag/v0.9.0) on 2026-10-07 at 20:16:02 UTC from candidate `acffd58d2f0e3fa0ae5a1f68f6cfc2a27e2db42e`. Corey signed the assets. All six independently downloaded public assets passed signature/checksum verification; the archive matched all 55 candidate files byte-for-byte. Archive SHA-256: `ff26b1097c64673958712d3a243af990992439a67204a65550f6821b019bc3b3`.

Installed from those verified signed assets on the MacBook; package/profile verification passed for both clients. The private development field was migrated to `meeting_note_path`. Installation on other machines remains user-directed. The immutable v0.9.0 tag is unchanged; this publication record is a later documentation commit.
