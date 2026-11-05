# Release candidate: 0.14.0

## Scope

This candidate covers the changes since v0.13.2. Every change is to the session
features.

- Lessons, decisions and knowledge saved at a checkpoint are kept until the wrap
  files or drops them. Each checkpoint, the stop-time skeleton, the
  pre-compaction write and the wrap restore them from the session ledger, and
  pickup carries them to the successor session. Both automatic checkpoint
  prompts now ask for new lessons in `session_items`
  ([hippocampus#141](https://github.com/coreyfloyd/hippocampus/issues/141)).
- An agent can run `pickup`, `checkpoint`, `handoff-prompt` and `wip` when the
  user asks in a sentence; they are no longer user-only
  ([hippocampus#142](https://github.com/coreyfloyd/hippocampus/issues/142)).
- Timed checkpoints: after each checkpoint, a checkpoint is scheduled
  `timed_checkpoint_minutes` later (default 55) and runs only below
  `timed_checkpoint_token_limit` tokens (default 200,000). Before compaction,
  the continuation is captured without an agent turn
  ([hippocampus#125](https://github.com/coreyfloyd/hippocampus/issues/125)).
- The checklist report leads with the session summary, and a wrap needs a
  nonempty one before project persistence
  ([hippocampus#110](https://github.com/coreyfloyd/hippocampus/issues/110)).
- The report ends with the saved line: whether each checkout the session
  touched is committed and pushed
  ([hippocampus#108](https://github.com/coreyfloyd/hippocampus/issues/108)).
- Pickup copies the resumed session's history chain into the successor's
  ledger ([hippocampus#109](https://github.com/coreyfloyd/hippocampus/issues/109)).
- Ticket close outcomes are recorded in the session ledger
  ([hippocampus#107](https://github.com/coreyfloyd/hippocampus/issues/107)).
- Setup and sweep use the per-kind record writes
  ([hippocampus#106](https://github.com/coreyfloyd/hippocampus/issues/106)).
- Record the v0.13.2 publication in `docs/releases/0.13.2.md`.

## Compatibility

Knowledge profile version remains 4. Two optional settings are added to the
shared configuration, `timed_checkpoint_minutes` and
`timed_checkpoint_token_limit`; both have defaults. Skill names, the Claude
`hippocampus:` namespace and installation paths are unchanged. The public
signing key and fingerprint are unchanged.

Session features are unreleased until the public launch and keep no
compatibility paths. Pickup refuses handoffs written by earlier versions,
because they lack a history entry for their write; such a handoff reports
`chain_copy_failed`. Recovering lessons carried in those older handoffs is
tracked in [hippocampus#144](https://github.com/coreyfloyd/hippocampus/issues/144).

## Verification and publication state

Not yet published.

Previous records: [0.13.2](docs/releases/0.13.2.md),
[0.13.1 (not published)](docs/releases/0.13.1.md),
[0.13.0](docs/releases/0.13.0.md).

## Release-note draft

Hippocampus v0.14.0 keeps what a session learns.

Lessons, decisions and knowledge saved at any checkpoint now survive every later
checkpoint, compaction and pickup until the wrap files or drops them. Before
this release, a lesson saved at one checkpoint was lost at the next one that
did not repeat it, and the automatic checkpoint prompts never asked for
lessons.

Also in this release:

- Agents can run `pickup`, `checkpoint`, `handoff-prompt` and `wip` when you
  ask for them in a sentence.
- Timed checkpoints, every 55 minutes by default, and a continuation captured
  before compaction.
- The checklist report leads with the session summary and ends with the saved
  line for each checkout the session touched.
- Pickup carries the resumed session's history to the new session.

Handoffs written by earlier versions cannot be picked up with this release;
start from the transcript (`pickup --session <id>`) for those sessions.

Existing skill names, knowledge profiles and the knowledge root are compatible
with 0.13.2.
