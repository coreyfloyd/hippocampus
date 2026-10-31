# Release candidate: 0.11.0

## Scope

This candidate covers the changes since v0.10.0:

- Add a knowledge-root rules composer, `scripts/compose_rules.py` ([hippocampus#41](https://github.com/coreyfloyd/hippocampus/issues/41)). It composes tool instruction files from rule documents in the knowledge root: Claude Code targets import the documents by path, and other targets receive their content. A file carrying the composer's generated header is rewritten in full; any other existing file gains or updates exactly one marked block and is otherwise unchanged. Every target is checked before any is written: missing or unreadable sources, source/target overlaps, unwritable targets and malformed marked blocks fail without changing any target. File modes are preserved.
- Add an optional `rules` section to the profile and its validator ([hippocampus#42](https://github.com/coreyfloyd/hippocampus/issues/42)): a `standard` or `thin` preset, the cross-tool and development rules document locations relative to the knowledge root, an optional absolute development root, and one row per tool (`claude-code`, `codex` or `openclaw`) with its rules target (a file or `none`) and memory value (`native` or `off`).
- Detect each tool's rules and memory state during `hippocampus-set-up` and offer the two presets through `scripts/rules_setup.py` ([hippocampus#43](https://github.com/coreyfloyd/hippocampus/issues/43)). `inspect` reports installation, the default instruction file and its owner, the memory setting and the memory store's location and file count; `plan` lists every proposed mutation with an approval fingerprint; `apply` recomputes the plan and refuses when it no longer matches the approved fingerprint. Installation packages both helpers, and `install.sh --verify` checks for the set-up helper.

The `standard` preset writes no user instruction file and keeps each tool's
detected memory setting. The `thin` preset composes into each tool's default instruction
file and proposes each tool's documented memory-off setting. Each row is
editable before approval. Set-up uses `context/rules.md` and
`context/development-rules.md` in the knowledge root and records those
locations in the profile. When the profile names a development root, set-up
also composes the development rules into `CLAUDE.md` and `AGENTS.md` at that
root, under either preset.

## Compatibility

Profile version remains 4. The `rules` section is optional: existing published
profiles need no new fields and, without the section, use the `standard`
preset. The validator rejects a malformed `rules` section, a document location
outside the knowledge root, a relative development root, and an unknown or
duplicated tool row.

Set-up changes only the files in the approved mutation list: composed rule
targets, the listed memory settings (`autoMemoryEnabled` in Claude Code
settings, `features.memories` in the Codex configuration, and the
pre-compaction memory flush and memory-core dreaming flags in the OpenClaw
configuration), the profile's `rules` section, and any missing parent
directories those need. It never deletes a memory store or any file in one; a
nonempty store is reported for the user to act on. `native` proposes no memory
setting change. A customized memory directory or workspace is described,
flagged when `off` is selected, and left unchanged. A user-written instruction
file keeps everything outside its marked block. A decline writes nothing and
leaves the profile's existing `rules` section unchanged.

Known limitation: set-up composes from `context/rules.md` and
`context/development-rules.md` and records those two paths in the profile, even
when the profile's `cross_tool_document` or `development_document` names another
location. Use the default names until this is fixed
([hippocampus#45](https://github.com/coreyfloyd/hippocampus/issues/45)).

Installation adds `scripts/compose_rules.py` and `scripts/rules_setup.py` to the
release directory and its manifest. It does not run set-up, compose rules or
change any tool's memory setting. Both Claude Code and Codex receive the same
package. The public signing key and fingerprint are unchanged.

## Verification

Run the exact candidate checks in `RELEASING.md`, plus
`python3 tests/test-compose-rules.py` and `python3 tests/test-capture-absorb.py`,
the documentation sweep and the public commit-range scan. Final commit
identifiers and results are recorded in the release-session evidence;
publication evidence is appended after release to avoid a self-referential
commit.

Previous publication evidence: [0.10.0](docs/releases/0.10.0.md),
[0.9.0](docs/releases/0.9.0.md).

## Release-note draft

Hippocampus v0.11.0 lets your agent rules live in your knowledge root.
Keep rules for every tool in `context/rules.md` and rules for development work
in `context/development-rules.md`, and `hippocampus-set-up` composes them into
the instruction files of Claude Code, Codex and OpenClaw.

Set-up first reports each installed tool's instruction file, its native memory
setting and its memory store, then offers two editable presets: `standard`
writes no user instruction file and keeps native memory; `thin` composes into each
tool's default instruction file and turns native memory off. You review the
complete list of changes before anything is written, and set-up refuses to
apply a plan that changed after your approval. In an instruction file you wrote
yourself, only one marked block changes. Set-up never deletes a memory store.

Your choices are recorded in a new optional `rules` section of the profile.
Profile version 4 is unchanged, existing profiles need no migration, and a
profile without the section uses the `standard` preset. Both supported clients
receive the same package.

## Publication checklist

- [x] Verify and commit the candidate; resolve the public commit-history scan.
- [ ] Complete independent review, evaluation and public-communication approval. Not run for 0.11.0: the maintainer authorized an unattended release; the candidate had the runbook checks and documentation sweep only.
- [x] Merge the reviewed candidate and tag its exact commit as `v0.11.0`.
- [x] Maintainer signs using `HIPPOCAMPUS_GPG_KEY` and `scripts/build-release.sh`.
- [x] Verify signed assets, publish, and independently verify downloaded assets.
- [x] Install and verify the signed release in both supported clients.

## Publication

Published 2026-10-28 as a public, non-draft, non-prerelease release.

- Tag: `v0.11.0`, annotated; peeled commit `827acd0ab87a7123e027c385484b49ff601a2829`, equal to `origin/main` at publication.
- Release: https://github.com/coreyfloyd/hippocampus/releases/tag/v0.11.0
- Assets (6): `hippocampus-0.11.0.tar.gz`, `hippocampus-0.11.0.tar.gz.sha256`, `hippocampus-0.11.0.tar.gz.asc`, `hippocampus-release.asc`, `install-release.sh`, `verify-release.sh`.
- Verification: local `scripts/verify-release.sh` passed against `dist/` before publication; the six downloaded public assets were verified in a fresh temporary directory (`cmp` on the key and both scripts, signature and checksum on the archive: OK). The archive lists 132 entries, all under `hippocampus/`.
- Installation: `install-release.sh` from the downloaded assets installed 0.11.0 on the maintainer machine; `current` resolves to the 0.11.0 release directory and includes `scripts/compose_rules.py`.
