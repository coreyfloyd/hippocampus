# Release candidate review

## Scope

`0.8.0` renames the public project from research-tools to Hippocampus. New installations use the Hippocampus configuration and package paths, and release archives are rooted and named `hippocampus`.

## Compatibility

The installer upgrades a valid published v0.7.0 installation without changing the profile's bytes or the knowledge root. It preserves the old release tree and forwards the old `research-tools-set-up` command to `hippocampus-set-up`. Foreign links, broken installations, and differing old/new profiles stop with recovery instructions before package links change.

The signing key material and fingerprint are unchanged. The key file is named `keys/hippocampus-release.asc`; published historical tags and assets remain evidence for research-tools releases through v0.7.0.

## Verification

- `bash tests/test-contracts.sh`
- `bash tests/test-install.sh`
- `bash tests/test-release.sh`
- `swift test` in `skills/transcribe/tools/apple-speech`
- `git diff --check`

## Release-note draft

`v0.8.0` introduces Hippocampus, the new name for research-tools. New installs use `~/.config/hippocampus` and `~/.local/share/hippocampus`; descriptive research workflow skill names stay the same. Existing v0.7.0 installs upgrade in place: their profile and knowledge root are preserved, old release trees remain available for recovery, and `research-tools-set-up` continues as a forwarding compatibility command. New setup instructions use `hippocampus-set-up`.

Release archive names and roots now use `hippocampus`. The public signing key has the same bytes and fingerprint as earlier releases.

## Publication checklist

- [x] Complete the verification commands above from the candidate commit.
- [ ] Rename the GitHub repository and verify its redirects.
- [x] Tag the exact pushed commit as `v0.8.0`.
- [x] Maintainer signs the candidate using `HIPPOCAMPUS_GPG_KEY`.
- [x] Verify the signed archive and published release assets before announcing.

## Publication result — 2026-09-13

Published [v0.8.0](https://github.com/coreyfloyd/hippocampus/releases/tag/v0.8.0) at 2026-09-13 19:40:30 UTC, from commit `e7d662f65a3d320c8eebfa20c73cf5d12b1ffae6`. The annotated tag and remote main matched that commit before publication. Corey signed the candidate; the agent verified and published it. Earlier pre-publication tag moves were explicitly approved by Corey to include presentation and README changes.

All contract, installer, release, and Swift checks passed on the MacBook against the release commit (Swift: 5/5). The signed archive contains 82 entries under `hippocampus/` and matches the tracked release tree byte-for-byte. Public-key bytes and fingerprint are unchanged from v0.7.0.

Six public assets were downloaded into a fresh directory and verified:

- `hippocampus-0.8.0.tar.gz`
- `hippocampus-0.8.0.tar.gz.sha256`
- `hippocampus-0.8.0.tar.gz.asc`
- `hippocampus-release.asc`
- `install-release.sh`
- `verify-release.sh`

The downloaded archive matches the signed local archive; downloaded key and installer/verifier scripts match the tagged source. Signature and checksum verification passed. The release is public, not a draft or prerelease. GitHub CLI's release command hit a GraphQL rate limit before creating anything; publication completed through GitHub's REST API.

The MacBook installed the downloaded release and passed `install.sh --verify` for both clients. Migration preserved the legacy profile byte-for-byte (SHA-256 `37988016589af8b475b893d7eaa3858f19b4a54661c73142ef3c531e9d589673`) and retained old releases. A before/after comparison found no changes among 13,905 Markdown files in the knowledge root, excluding `.git` and `.obsidian`. Other machines were not verified at publication; see the subsequent rollout below.

Remaining cutover observation: the canonical repository and issue URLs work, but the plain old issue URL still returned HTTP 404 from the MacBook during release preflight. The rename/redirect checklist item remains unchecked pending full verification. No announcement was sent.

## Mac Mini rollout — 2026-09-14

Both Minis downloaded the six public v0.8.0 assets, verified the signature and checksum against fingerprint `09674AFF392661238F4ACBD9F32B3A412CD5EFC5`, installed the release, and passed `install.sh --verify` for Claude and Codex. Both migrated from research-tools v0.6.0. Profiles were preserved byte-for-byte; legacy profiles and releases remain available. The dotfiles installer on each machine already recognized Hippocampus ownership.

| Machine / account | Markdown files compared | Changed | Preserved profile SHA-256 |
|---|---:|---:|---|
| Mini 1 / `coreyfloyd` | 7,220 | 0 | `a18645a77a604b8cc3ba9ac5e7f8d21e9554841c3cbbf61269d05e99aaeefdfa` |
| Mini 2 / `claude` | 3,711 | 0 | `763872b7c2342ea289d0514eb9124bc1e64f82ecc4d7ed3dd327940b61227946` |

The comparison excludes `.git` and `.obsidian`. Both downloaded archives have SHA-256 `6be606588305347601f427d1fdd0fe1abcafa64546493813744728c31ccd182d`. Connections used the documented LAN routes because Tailscale was stopped on the MacBook. No Tailscale settings were changed.
