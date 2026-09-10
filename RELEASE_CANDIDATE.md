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

- [ ] Complete the verification commands above from the candidate commit.
- [ ] Rename the GitHub repository and verify its redirects.
- [ ] Tag the exact pushed commit as `v0.8.0`.
- [ ] Maintainer signs the candidate using `HIPPOCAMPUS_GPG_KEY`.
- [ ] Verify the signed archive and published release assets before announcing.
