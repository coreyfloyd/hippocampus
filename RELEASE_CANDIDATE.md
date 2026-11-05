# Release candidate: 0.14.1

## Scope

This candidate covers the changes since v0.14.0.

- A failed `install-claude.py` no longer removes the Claude plugin directory.
  The backup is kept on disk until the run succeeds, rollback restores only
  what the failed command changed, and removed skill links are restored. A
  `hippocampus` marketplace registered from another source is reported before
  anything changes. `install-codex.py` gets the same guarantees
  ([hippocampus#151](https://github.com/coreyfloyd/hippocampus/issues/151)).
- Upgrades between releases complete unattended in Claude Code. The plugin's
  marketplace is registered at the stable
  `~/.local/share/hippocampus/current` path, and an upgrade runs
  `claude plugin marketplace update` and `claude plugin update`, keeping the
  plugin's options and data. An installation registered at a versioned release
  folder by an earlier release moves to `current` once, on the first upgrade.
- Record the v0.14.0 publication in `docs/releases/0.14.0.md`.

## Compatibility

Knowledge profile version remains 4. Skill names, the Claude `hippocampus:`
namespace and installation paths are unchanged. The public signing key and
fingerprint are unchanged. Run the helpers from
`~/.local/share/hippocampus/current`; a helper run from another release folder
is refused with that instruction. During the one-time move to `current`, the
plugin is briefly unregistered, so a Claude Code session started at that moment
loads without it. An upgrade or rerun currently re-enables a disabled
hippocampus plugin; tracked in
[hippocampus#155](https://github.com/coreyfloyd/hippocampus/issues/155).

## Verification and publication state

Not yet published.

Previous records: [0.14.0](docs/releases/0.14.0.md),
[0.13.2](docs/releases/0.13.2.md),
[0.13.1 (not published)](docs/releases/0.13.1.md).

## Release-note draft

Hippocampus v0.14.1 makes installing and upgrading safe.

A failed Claude Code install in 0.14.0 could delete the whole Claude plugin
directory, removing every plugin. The installer now keeps its backup on disk,
restores only what it changed, and reports a conflicting marketplace before
touching anything.

Upgrades between releases now complete without manual steps: the plugin is
registered at the stable `~/.local/share/hippocampus/current` path and updated
in place, keeping its options and data. To upgrade, run the release installer,
then the helpers from the installed release:

```bash
python3 ~/.local/share/hippocampus/current/scripts/install-claude.py
python3 ~/.local/share/hippocampus/current/scripts/install-codex.py
```

The first upgrade from 0.14.0 moves the plugin's registration to `current`
once. Existing skill names, knowledge profiles and the knowledge root are
compatible with 0.14.0.
