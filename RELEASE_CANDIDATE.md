# Release candidate: 0.15.0

## Scope

This candidate covers the changes since v0.14.1: epic
[hippocampus#99](https://github.com/coreyfloyd/hippocampus/issues/99), auto-apply
lessons at wrap behind one setting. Everything below happens only with the
auto-apply setting on (`auto_apply_lessons: true` in the shared configuration).
With it off, the default, behavior is unchanged.

- A wrap applies the lessons it recommends, attended or unattended. A lesson in
  a repository is committed on its own and pushed with the wrap's other
  commits, or delivered on one pull-request branch for repositories the routing
  file lists under `lesson-pull-requests:`. A lesson for an always-loaded rules
  file raises an ask afterwards that names the commit and how to undo it.
  A routing file line `lesson-policy: propose` turns this off
  ([hippocampus#99](https://github.com/coreyfloyd/hippocampus/issues/99)).
- A wrap captures wiki captures and retained sources and outputs under the
  knowledge root without an approval, and the report lists what it wrote. A
  fact about the user stays an ask and is saved only on its approving answer.
  Capture outside the knowledge root keeps its approval
  ([hippocampus#131](https://github.com/coreyfloyd/hippocampus/issues/131)).
- A wrap records files over their size limits and duplicate findings in a
  store of over-limit records, instead of asking. Records name the repository
  from its hosted remote and never by a home path
  ([hippocampus#133](https://github.com/coreyfloyd/hippocampus/issues/133)).
- A sweep in act mode applies the carried lessons and knowledge of abandoned
  handoffs under the same rules as a wrap. It never applies anything for a
  session that is open, and archives a handoff only when every item is settled
  ([hippocampus#132](https://github.com/coreyfloyd/hippocampus/issues/132)).
- New skill `slim-unattended` slims the recorded files: at most three per run,
  one branch per repository built in a temporary clone, and one ask per slimmed
  file listing every change. The package never opens or merges a pull request;
  a rejected slim is remembered until the file grows
  ([hippocampus#134](https://github.com/coreyfloyd/hippocampus/issues/134),
  [hippocampus#186](https://github.com/coreyfloyd/hippocampus/issues/186)).
- Record the v0.14.1 publication in `docs/releases/0.14.1.md`.

## Compatibility

Knowledge profile version remains 4. Existing skill names, the Claude
`hippocampus:` namespace, installation paths, the signing key and fingerprint
are unchanged. The installers now register 27 skills (adds `slim-unattended`).
New configuration keys: `auto_apply_lessons` (default false) and
`slim_checkouts`. New routing file lines: `lesson-policy`,
`lesson-pull-requests` and `lesson-pull-request-command`. With the setting on,
a sweep's native steps now apply items instead of only carrying them.

Known open follow-ups, none blocking: hippocampus#174-#177, #180-#183, #187
and #188.

## Verification and publication state

Not yet published. Each ticket was reviewed and evaluated on its own branch
(#131 and #133 conditional pass, #132 conditional pass in round 3, #134
accepted at the round cap with its remaining defect fixed and passed in #186).
CI passed on Ubuntu and macOS for the epic pull requests.

Previous records: [0.14.1](docs/releases/0.14.1.md),
[0.14.0](docs/releases/0.14.0.md), [0.13.2](docs/releases/0.13.2.md).

## Release-note draft

Hippocampus v0.15.0 lets a wrap finish without waiting for you.

One setting, `auto_apply_lessons`, off by default, turns it on. With it on, a
wrap applies the lessons it recommends, captures wiki knowledge under your
knowledge root, and records rule files that have grown past their limits. The
sweep applies the same items from abandoned sessions. The new
`slim-unattended` skill slims those files on a branch per repository, for you
to review. Every lesson in a repository is committed on its own so it can be
reverted, and a lesson for an always-loaded rules file raises an ask telling you what changed
and how to undo it. A fact about you always waits for your answer.

To upgrade, run the release installer, then the helpers from the installed
release:

```bash
python3 ~/.local/share/hippocampus/current/scripts/install-claude.py
python3 ~/.local/share/hippocampus/current/scripts/install-codex.py
```

Knowledge profiles and the knowledge root are compatible with 0.14.1.
