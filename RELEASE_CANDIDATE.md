# Release candidate: 0.15.0

## Scope

This maintenance release covers the changes since v0.14.1. It includes
opt-in lesson application, explicit bounded keep-warm, and installer, sweep,
and documentation repairs. It is not the public launch of session features.

The lesson and capture behavior below requires the auto-apply setting
(`auto_apply_lessons: true` in the shared configuration), off by default:

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

The release also includes:

- Replace automatic timed checkpoints with explicit `keep-warm on` and
  `keep-warm off` in both tools. Enable only for a specific incoming result
  expected within about two hours. At most two wakes occur, around 55 and
  110 minutes; the first empty wake turns keep-warm off without writing a
  handoff. Checkpoints, compaction and ordinary activity never enable or renew it
  ([hippocampus#214](https://github.com/coreyfloyd/hippocampus/issues/214)).
- Preserve foreign multiline TOML trust text during Codex installation, retain
  sweep record receipts through completion and undo, and scope adapter tools
  and shipped-directory link checks.
- Align engine contracts and affected-test handoff guidance, remove personal
  workflow notes, and improve public-content, documentation-link and shipped
  skill checks.
- Record the v0.14.1 publication in `docs/releases/0.14.1.md`.

## Compatibility

Knowledge profile version remains 4. Existing skill names, the Claude
`hippocampus:` namespace, installation paths, the signing key and fingerprint
are unchanged. The installers now register 28 skills (adds `slim-unattended` and `keep-warm`).
Automatic timed checkpoint activation is removed; sessions start with keep-warm
off. Existing pending timers can be cancelled with the supported `timer-cancel`
command documented in the keep-warm skill.
New configuration keys: `auto_apply_lessons` (default false) and
`slim_checkouts`. New routing file lines: `lesson-policy`,
`lesson-pull-requests` and `lesson-pull-request-command`. With the setting on,
a sweep's native steps now apply items instead of only carrying them.

## Verification and publication state

Not yet published. Each ticket was reviewed and evaluated on its own branch
(#131 and #133 conditional pass, #132 conditional pass in round 3, #134
accepted at the round cap with its remaining defect fixed and passed in #186).
CI passed on Ubuntu and macOS for the epic pull requests.

Previous records: [0.14.1](docs/releases/0.14.1.md),
[0.14.0](docs/releases/0.14.0.md), [0.13.2](docs/releases/0.13.2.md).

## Release-note draft

Hippocampus v0.15.0 is a maintenance release with opt-in wrap automation and
explicit bounded keep-warm in Claude Code and Codex.

One setting, `auto_apply_lessons`, off by default, turns on wrap automation. With it on, a
wrap applies the lessons it recommends, captures wiki knowledge under your
knowledge root, and records rule files that have grown past their limits. The
sweep applies the same items from abandoned sessions. The new
`slim-unattended` skill slims those files on a branch per repository, for you
to review. Every lesson in a repository is committed on its own so it can be
reverted, and a lesson for an always-loaded rules file raises an ask telling you what changed
and how to undo it. A fact about you always waits for your answer.

Automatic timed checkpoints are removed. Keep-warm starts off and is enabled
only by an explicit request while waiting for a specific incoming result expected
within about two hours. It wakes at most twice, around 55 and 110 minutes, and
turns off at the first empty wake without writing a handoff. Ordinary activity,
checkpoints and compaction do not renew it.

This release also repairs Codex TOML preservation, sweep record receipts and
undo, adapter tool scoping, and documentation and installation checks. It is not
the public launch of session features.

To upgrade, run the release installer, then the helpers from the installed
release:

```bash
python3 ~/.local/share/hippocampus/current/scripts/install-claude.py
python3 ~/.local/share/hippocampus/current/scripts/install-codex.py
```

Knowledge profiles and the knowledge root are compatible with 0.14.1.
