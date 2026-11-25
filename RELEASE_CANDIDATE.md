# Release candidate: 0.16.4

## Scope

Package the changes merged since 0.16.3: new-skill proposals ([hippocampus#305](https://github.com/coreyfloyd/hippocampus/issues/305) through [PR310](https://github.com/coreyfloyd/hippocampus/pull/310)), their answers ([hippocampus#307](https://github.com/coreyfloyd/hippocampus/issues/307) and [#308](https://github.com/coreyfloyd/hippocampus/issues/308) through [PR314](https://github.com/coreyfloyd/hippocampus/pull/314)), the skill-creator hand-off ([hippocampus#312](https://github.com/coreyfloyd/hippocampus/issues/312) and [#313](https://github.com/coreyfloyd/hippocampus/issues/313) through [PR318](https://github.com/coreyfloyd/hippocampus/pull/318); [hippocampus#316](https://github.com/coreyfloyd/hippocampus/issues/316) and [#317](https://github.com/coreyfloyd/hippocampus/issues/317) through [PR319](https://github.com/coreyfloyd/hippocampus/pull/319)), and decision capture ([hippocampus#294](https://github.com/coreyfloyd/hippocampus/issues/294) and [#295](https://github.com/coreyfloyd/hippocampus/issues/295) through [PR304](https://github.com/coreyfloyd/hippocampus/pull/304)). This preparation changes package version metadata, this release record, and two README sentences found by the documentation sweep (new-skill proposals and decision capture).

This is a patch release. It does not announce the Public launch milestone.

## Included

- `improve-harness` proposes a new skill when a session repeated a process of three or more ordered steps that no installed skill covers. The proposal is asked once, with a stated reason, and carries no draft. No skill is created without the user's "create the skill" answer, even with auto-apply on; work an installed skill already covers becomes a trigger edit instead.
- The user's answer is read at the wrap and by the sweep. An answer counts only for an ask a ledger records as raised, must agree with the row's recommendation, and is checked against the ask's recorded choices from any session's ledger. "decline" drops the lesson with that reason.
- An approved proposal is handed to the running tool's skill creator once, and the hand-off is marked in the ledger. After that it stays carried, and every wrap and sweep reports it waiting for the skill, naming where it is kept, until a skip reports the skill written. A repeated answer never hands it off again. A delivered sweep ask stays written, and an ask delivered or answered in any ledger is never raised again.
- Decision capture: `decisions` and `logs` record-write kinds. The checklist, checkpoint and an on-demand capture run send approved decisions and unanchored agent decisions through them, in Claude Code and Codex. The documents record write refuses a decision and names the decisions record write.

## Migration

None. New-skill proposals and their ledger marks are new; ledger rows written by 0.16.3 read unchanged. Session features have no backward-compatibility paths before the Public launch.

## Compatibility and operational boundaries

Claude Code and Codex use the same code and skill text. Handoff and profile formats are unchanged. A skill is written by the running tool's built-in skill creator after the user's yes, never by hippocampus. A second hand-off of the same proposal needs a new ask: the user declines it and a later session proposes it again. Known follow-ups: [hippocampus#296](https://github.com/coreyfloyd/hippocampus/issues/296), [#297](https://github.com/coreyfloyd/hippocampus/issues/297), [#298](https://github.com/coreyfloyd/hippocampus/issues/298), [#299](https://github.com/coreyfloyd/hippocampus/issues/299) (the real attended and unattended decision-capture proofs, run after this release is installed), and [#309](https://github.com/coreyfloyd/hippocampus/issues/309).

## Verification and publication state

Each change passed native review with every finding repaired, then independent evaluation: #305 CONDITIONAL PASS, #307 and #308 CONDITIONAL PASS (follow-ups #312, #313), #312 and #313 CONDITIONAL PASS (follow-ups #316, #317), #316 and #317 PASS, #294 and #295 CONDITIONAL PASS (follow-ups #296 to #299). Each passed CI on Ubuntu and macOS before merge.

Not yet signed, tagged or published. The release operation records the exact commit, the immutable unsigned asset digests and the maintainer's SIGN before publication.

## Release-note draft

Hippocampus 0.16.4 notices when a session repeated a multi-step process that no skill covers and proposes a new skill once, without a draft. Nothing is created until the user answers "create the skill"; then the proposal goes to the tool's own skill creator once and stays carried until the skill is written. This release also adds decision capture: approved decisions and agent decision logs get their own record-write kinds in Claude Code and Codex.
