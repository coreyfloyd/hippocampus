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

Preparation only: no tag, maintainer signature, publication or downloaded-release
verification is claimed. Run the full checks and documentation sweep in
[RELEASING.md](RELEASING.md) against the final candidate commit. Build the
unsigned archive and checksum using `bash scripts/build-release.sh dist --unsigned`.
The maintainer must sign before publication. After publication, download and
signature-verify the assets, install into clean temporary homes for both tools,
and run `install.sh --verify` before the continuity repository can be archived.
Record that evidence in a post-publication follow-up; do not infer it from a
local unsigned candidate or the disposable test signing key.

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

`VERSION` is the package version authority. Claude plugin metadata is generated
from it and checked by the release suite; Codex install receipts read it directly.
The existing knowledge profile and root remain compatible.
