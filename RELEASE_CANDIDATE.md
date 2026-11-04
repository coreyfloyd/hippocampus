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

## Verification

Run the exact candidate checks in `RELEASING.md`, the documentation sweep and
the public commit-range scan. Final commit identifiers and results are recorded
in the release-session evidence; publication evidence is appended after release
to avoid a self-referential commit.

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

## Publication checklist

- [ ] Verify and commit the candidate; resolve the public commit-history scan.
- [ ] Merge the reviewed candidate and tag its exact commit as `v0.13.2`.
- [ ] Maintainer signs using `HIPPOCAMPUS_GPG_KEY` and `scripts/build-release.sh`.
- [ ] Verify signed assets, publish, and independently verify downloaded assets.
- [ ] Install from the signed release in a clean home with the real Claude CLI and confirm `install.sh --verify` passes for both tools.
