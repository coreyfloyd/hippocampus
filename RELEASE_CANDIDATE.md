# Release candidate: 0.9.1

## Scope

Completed meeting transcripts are filed from local intake into a retained primary-source archive after every authorized capture route is completed or explicitly declined. The shared knowledge-capture meeting procedure handles filing, reference repair, identity deduplication across both locations, collision checks, and pending capture work for both Claude Code and Codex. Compilation status remains separate from capture completion. Generated absorbed reviews remain excluded reference artifacts.

Resolve filing destinations from local policy with optional overrides in the private profile body. The three meeting input fields and profile version 4 are unchanged. Installation does not move existing sources or activate unsigned development skills.

This patch also carries the already-landed meeting-purpose clarification: confirm the user's purpose and preserve core versus ancillary outcomes before planning, reusing an existing explicit confirmation.

Tracking: [hippocampus#29](https://github.com/coreyfloyd/hippocampus/issues/29).
Previous publication evidence: [0.9.0](docs/releases/0.9.0.md).

## Verification

Verification passed on the MacBook; see [filing verification](docs/releases/0.9.1-verification.md). Record the exact candidate in the tracking issue before signing:

- `python3 tests/test-profile-meetings.py`
- `bash tests/test-contracts.sh`
- `bash tests/test-install.sh`
- `bash tests/test-release.sh`
- `git diff --check`
- Check completed, pending, repeated, partial, and collision filing scenarios against the shared procedure.

## Release notes

Hippocampus v0.9.1 completes meeting filing: new transcripts stage in local intake; completed captures retain originals in the configured source archive and repair source links. Pending document or task writes keep a capture staged. Original transcripts remain primary evidence, while generated reviews remain excluded references. Filing destinations use local policy or the private profile body; existing profile version 4 remains compatible. Meeting purpose is confirmed before planning so ancillary outcomes do not displace the user's core goal.

## Publication checklist

- [ ] Verify and commit the candidate.
- [ ] Merge the reviewed candidate and tag its exact commit as `v0.9.1`.
- [ ] Maintainer signs using `HIPPOCAMPUS_GPG_KEY` and `scripts/build-release.sh`.
- [ ] Verify signed assets, publish, and independently verify downloaded assets.
- [ ] Install and verify the signed release in both supported clients.

No v0.9.1 publication or live installation has occurred.
