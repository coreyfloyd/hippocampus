# Release candidate: 0.13.2

## Scope

This candidate covers the changes since v0.13.0. It replaces 0.13.1, which was
tagged and signed but never published (see
[the 0.13.1 record](docs/releases/0.13.1.md#publication-state-tagged-not-published)).

- One supported route from a signed release to both tools, and a `--verify`
  that passes after it ([hippocampus#80](https://github.com/coreyfloyd/hippocampus/issues/80)).
  The installed release keeps `install.sh` and its marketplace metadata, so
  `install-claude.py` and `install-codex.py` both run from
  `~/.local/share/hippocampus/current` after `install-release.sh`. Codex
  adoption keeps the shared versioned `current` symlink.
- `install.sh --verify` accepts each supported client layout: the Claude
  plugin `hippocampus@hippocampus` when `claude plugin list --json` reports it
  enabled and installed from the current release, plain Claude links from
  `install.sh` alone, Codex links, or both tools. A disabled plugin counts as
  absent. Wrong plugin sources or versions, missing or retargeted links,
  tampered manifests and an install with no client fail.
- New in 0.13.2: verification follows the real Claude CLI. The CLI copies a
  directory-marketplace plugin into its cache and reports the release it read
  from as `readFromFolder`; `--verify` checks that source and the plugin
  version against the current release, and keeps the `installPath` check for
  registrations that do not report a source. The installer tests now model the
  CLI's cache, and a test runs the real Claude CLI through the signed-release
  route when it is installed.
- Session record step: checklist's record step and the new `record` skill
  (`/hippocampus:record` in Claude Code, `record` in Codex) file session items
  through per-kind record writes for tickets, projects, documents and scheduled
  jobs, named by `record_writes` in the user checklist profile
  ([hippocampus#103](https://github.com/coreyfloyd/hippocampus/issues/103)).
- Every checkpoint and wrap adds a history entry to the handoff, kept in the
  session ledger through compaction
  ([hippocampus#104](https://github.com/coreyfloyd/hippocampus/issues/104)).
- Every checklist report ends with each filed or carried ask in full, including
  when the wrap fails
  ([hippocampus#105](https://github.com/coreyfloyd/hippocampus/issues/105)).
- Record the v0.13.0 publication in `docs/releases/0.13.0.md` and the
  unpublished 0.13.1 candidate in `docs/releases/0.13.1.md`.

## Compatibility

Knowledge profile version remains 4; no knowledge profile field is added or
changed. The user checklist profile replaces `bindings.record` with
`record_writes`; a profile that still has `bindings.record` is rejected with
the replacement shape, and nothing converts it automatically. One skill is
added, `record`; existing skill names, the Claude `hippocampus:` namespace, and
installation paths are unchanged.
Verifying a registered Claude plugin needs the Claude CLI on `PATH`.
Installs made with the 0.13.0 helpers directly from a checkout leave `current`
as a directory, which `--verify` rejects; the recovery is in
[INSTALLATION.md](INSTALLATION.md#earlier-helper-only-checkout-installs). The
public signing key and fingerprint are unchanged.

## Verification and publication state

Published 2026-11-04: tag `v0.13.2` (annotated, tag object
`bb28c936fe920e8c6af281c74e27d5ee7210038f`) at commit
`d1110c365018cbc0bcbd72d04d8a4c93d59def57`,
https://github.com/coreyfloyd/hippocampus/releases/tag/v0.13.2 (public, not a
draft or prerelease). Assets: hippocampus-0.13.2.tar.gz, hippocampus-0.13.2.tar.gz.asc, hippocampus-0.13.2.tar.gz.sha256, hippocampus-release.asc, install-release.sh, verify-release.sh.
Archive sha256: `dff6b2ff78ed67527da59020f81d787f5a3c1043118a78bb740701b816732b54`.

Evidence:

- All RELEASING.md candidate checks passed in a clean worktree on the candidate
  (pytest 1466 passed, 3 skipped; swift test passed), and CI passed on macOS
  and Ubuntu. The public commit-range scan was clean before every push.
- The documentation sweep found stale sweep wording left by the record-write
  change; it is unreleased session behavior and is tracked in
  [hippocampus#119](https://github.com/coreyfloyd/hippocampus/issues/119).
- The maintainer signed. `verify-release.sh` passed on the local build and on
  the downloaded assets. The downloaded archive is byte-identical to the local
  build, and the downloaded key and scripts are byte-identical to the
  repository's. The archive has a single `hippocampus/` root (349 entries).
- Installed from the downloaded assets into a clean temporary home with the
  real Claude CLI (2.1.318): `install-release.sh`, then `install-claude.py` and
  `install-codex.py` from `~/.local/share/hippocampus/current`, then a profile.
  `install.sh --verify` passed with both tools: plugin `hippocampus@hippocampus`
  enabled at 0.13.2, read from `releases/0.13.2`, and 26 Codex skill links.
  Retargeting one Codex skill link made `--verify` fail with "codex skill
  target differs".

Previous records: [0.13.1 (not published)](docs/releases/0.13.1.md),
[0.13.0](docs/releases/0.13.0.md), [0.12.0](docs/releases/0.12.0.md).

## Release-note draft

Hippocampus v0.13.2 fixes installation from a signed release.

In 0.13.0, running the helpers after `install-release.sh` failed in both tools,
and `install.sh --verify` failed after the documented Claude plugin install.
Both now work, including with the Claude CLI's plugin cache. Verify and
bootstrap with the published `install-release.sh`, then run the helper for
each tool you use from the installed release:

```bash
python3 ~/.local/share/hippocampus/current/scripts/install-claude.py
python3 ~/.local/share/hippocampus/current/scripts/install-codex.py
```

After guided profile setup, check the install:

```bash
bash ~/.local/share/hippocampus/current/install.sh --verify
```

`--verify` accepts the enabled Claude plugin installed from the current
release, plain Claude links, Codex links, or both tools, and still fails on a
broken install. Keep the Claude CLI on `PATH` when verifying the plugin. If you
installed 0.13.0 by running the helpers from a checkout, see
[INSTALLATION.md](https://github.com/coreyfloyd/hippocampus/blob/v0.13.2/INSTALLATION.md#earlier-helper-only-checkout-installs)
to recover.

Session features in this release:

- A new `record` skill files session items through per-kind record writes for
  tickets, projects, documents and scheduled jobs. Checklist's record step uses
  the same writes.
- Every checkpoint and wrap adds a dated history entry to the handoff.
- Every checklist report ends with each pending ask in full, even when the wrap
  fails.

If your user checklist profile has `bindings.record`, replace it with
`record_writes`; checklist rejects the old binding and shows the new shape.

v0.13.1 was tagged but not published; use v0.13.2.

Existing skill names, knowledge profiles and the knowledge root are compatible
with 0.13.0.
