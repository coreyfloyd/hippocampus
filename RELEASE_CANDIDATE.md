# Release candidate: 0.15.3

## Scope

This patch moves the canonical implementation ladder into improve-harness
([hippocampus224](https://github.com/coreyfloyd/hippocampus/issues/224)). It adds
system prompt and output style at rung 4 and a decision service at rung 6, before
hooks and scripts. The ladder preserves proportionality, lower-rung assessment,
and the full rule at its canonical home. User routing maps rungs to local services
and paths. This is not the public launch of session features.

## Compatibility

Claude Code and Codex receive the same improve-harness skill through their
existing package installers. Knowledge profiles, package paths, hook behavior,
client adapters and signing key remain unchanged. Default routing now chooses a
rung before choosing a hook; a deterministic trigger alone does not skip the
lower-rung assessment.

## Verification and publication state

Source preparation only. This candidate has not been signed, tagged, published
or activated. Candidate checks and isolated both-tool readback are recorded on
[hippocampus224](https://github.com/coreyfloyd/hippocampus/issues/224). Merging this
source does not change an installed signed release. The next maintainer-signed
v0.15.3 release will carry the ladder; publication and installation require their
separate authorized release workflow.

Previous publication: [v0.15.2](https://github.com/coreyfloyd/hippocampus/releases/tag/v0.15.2).
The previous candidate record remains in repository history at
[the preparation record](https://github.com/coreyfloyd/hippocampus/blob/575edf0/RELEASE_CANDIDATE.md).

## Release-note draft

Hippocampus v0.15.3 makes improve-harness the canonical home of the implementation
ladder for choosing where knowledge, rules and solutions belong. System prompt
and output style hold a short form of an important rule still being missed; the
full rule stays canonical. A decision service receives facts and returns a
decision before an unreliable important rule advances to hooks or scripts.
Both Claude Code and Codex use this same guidance. Local names stay in user routing.
