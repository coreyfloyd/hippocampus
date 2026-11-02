# Release candidate: 0.13.0

## Scope

This candidate combines session memory, knowledge workflows and agent-rule
maintenance in one Hippocampus package. It implements the release preparation
slice of [hippocampus#64](https://github.com/coreyfloyd/hippocampus/issues/64)
for [the approved fold](https://github.com/coreyfloyd/hippocampus/issues/57).

## Compatibility

The Claude Code command rename is breaking: every skill is now
`/hippocampus:<skill>`, including previously unprefixed knowledge skills.
Codex retains plain skill names. Setup remains `hippocampus-set-up` in both
tools; there is no bare `setup` or `continuity:` alias. The Claude installer
transactionally removes only installer-owned old skill links.

The knowledge profile format (version 4), knowledge root, installation root
and composer entry point remain compatible. Continuity was never released;
there is no automatic migration from its installation or data locations.
Follow the manual steps in [MIGRATION.md](MIGRATION.md#manual-continuity-cutover).
The public signing key and fingerprint are unchanged.

## Verification and publication state

Published 2026-11-02: tag `v0.13.0` (annotated) at commit
`5b364ba7d21497480a1bffdf459e89a638021262`,
https://github.com/coreyfloyd/hippocampus/releases/tag/v0.13.0 (public, not a
draft or prerelease). Assets: hippocampus-0.13.0.tar.gz, hippocampus-0.13.0.tar.gz.asc, hippocampus-0.13.0.tar.gz.sha256, hippocampus-release.asc, install-release.sh, verify-release.sh.

Evidence:

- All RELEASING.md candidate checks passed in a clean worktree at that commit
  (pytest 1211 passed, 3 skipped; swift test passed). The documentation sweep
  passed.
- The maintainer signed. `verify-release.sh` passed on the local build and on
  the downloaded assets. The downloaded key and scripts are byte-identical to
  the repository's. The archive has a single `hippocampus/` root.
- Installed into clean temporary homes from the extracted downloaded archive:
  `install-codex.py` and `install-claude.py` both succeeded (25 skills, six
  hooks; plugin `hippocampus@hippocampus`).

Known issue
([hippocampus#80](https://github.com/coreyfloyd/hippocampus/issues/80), fix in
0.13.1): `install.sh --verify` fails after the plugin installation. Running the
helpers after `install-release.sh` also fails. Install by extracting the
verified archive and running the two helpers from it.

## Release-note draft

Hippocampus v0.13.0 combines session memory, knowledge workflows and agent-rule
maintenance in one package for Claude Code and Codex.

**Breaking Claude Code rename:** invoke every skill as `/hippocampus:<skill>`
(for example `/hippocampus:research-topic` and `/hippocampus:checklist`). Codex
uses plain names, such as `Use checklist`. Setup remains `hippocampus-set-up`:
`/hippocampus:hippocampus-set-up` in Claude Code and `Use hippocampus-set-up` in
Codex. Old Claude names are not retained.

Install from a checkout or a signature-verified extracted release with:

```bash
python3 scripts/install-claude.py
python3 scripts/install-codex.py
```

Run only the helper for each tool you use. The Claude helper installs the native
plugin and replaces installer-owned old links in one transaction. Foreign links
are retained; failures restore the prior state. Codex registers and verifies
trusted hooks and retains foreign settings.

**Continuity users:** continuity was never released, so this release ships no
migration code. Uninstall continuity from both tools before installing
Hippocampus. Back up your data; move or recreate your checklist profile at
`~/.config/hippocampus/checklist-profile.md`, manually removing its `knowledge`
and `lessons` binding blocks. Keep `record`, `persist` and ask bindings. Move
custom lesson routing to `~/.config/hippocampus/routing.md`; move wanted shared
configuration and handoffs to the Hippocampus paths described in
[MIGRATION.md](MIGRATION.md#manual-continuity-cutover). Installation refuses while
continuity is still installed and prints the uninstall commands.

Knowledge capture and lessons are native checklist steps: knowledge runs
`knowledge-capture`, and lessons runs `improve-harness`. Lesson destinations
remain configurable through routing. Without a knowledge root, capture reports
not configured and continues; setup can configure session memory alone.
Failures and declines retain carried items and report an incomplete wrap.

The fold's open questions are resolved: existing Claude knowledge skills take
the `hippocampus:` namespace as a breaking change; lessons are native rather
than a configurable slot; the continuity snapshot was taken after in-flight
work reached a clean break, with no code in flight. continuity's history is not
carried over: it was imported as one squashed snapshot that names its source commit. There is one rule composer and one glossary.

**Known issue:** `install.sh --verify` fails after the documented Claude
plugin installation because it still expects plain skill links. The
installation itself works; the fix ships in 0.13.1
([hippocampus#80](https://github.com/coreyfloyd/hippocampus/issues/80)).

`VERSION` is the package version authority. Claude plugin metadata is generated
from it and checked by the release suite; Codex install receipts read it directly.
The existing knowledge profile and root remain compatible.
