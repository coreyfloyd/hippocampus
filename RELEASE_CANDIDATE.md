# Release candidate: 0.15.8

## Scope

Package the integrated durable-session changes delivered by [PR257](https://github.com/coreyfloyd/hippocampus/pull/257), including the startup-budget and slimming work in [hippocampus#242](https://github.com/coreyfloyd/hippocampus/issues/242). Runtime source is unchanged from main `b897cbf819340038a0d65ced293c587f6a901cb2`; this preparation changes package version metadata and this release record only.

This package release supports the next installed real-input checks. It does not announce the Public launch milestone or claim that pending live acceptance, setup/policy implementation, local lookup or README review is complete.

## Included

- Startup budgets with per-directory overrides, usage-evidence section extraction, retained removal journals, recovery and configured-owner ask receipts.
- Configured durable-agent ownership and stored-owner checks before ask settlement.
- Approved user-decision filing through configured document integrations and unattended proposals retained as asks.
- Identity-bound catch-up filing, destination reports and readiness recounts.
- Durable checkpoints that preserve the running session, retain failures and expose configured scheduler/report integration contracts.
- Retirement of OpenClaw setup/composition support.
- The reviewed example/test delivery correction from PR257, without runtime changes.

## Compatibility and operational boundaries

Claude Code and Codex consume the same package runtime. Released profile readability, installation layout and composer entry points remain supported. Record writes, document destinations, scheduler dispatch and report delivery require the user's configured integrations and their existing approval boundaries. Catch-up readiness remains required before periodic filing is enabled. Installing this release does not configure those integrations, enable a schedule or approve a removal branch.

The startup proof retained so far covers a controlled loaded-file set and one Codex removal/ask loop; it does not establish every live startup overhead source. The remaining real-input acceptance belongs to the delivery tickets. This release makes the main runtime available through signed assets for those checks.

Version 0.15.7 was used only for an unpublished local staging. This candidate uses 0.15.8 because its payload differs from that staging; the earlier staged payload remains untouched. No two different 0.15.7 payloads are published.

## Verification and publication state

The integrated runtime candidate passed independent code/fixture evaluation with its retained conditional follow-ups. PR257's final CI attempt, run `44624650193`, passed on Ubuntu and macOS. The release-preparation head requires its own affected release checks, quick checks, documentation sweep and PR CI before the exact unsigned candidate is frozen. No local full-suite run is authorized; the PR is the full gate.

Not yet signed, tagged or published. Exact commit, immutable unsigned asset digests, checks and the maintainer's SIGN are recorded by the release operation before publication. The post-publication receipt will record the final commit, tag, six public assets and fresh-download verification.

## Release-note draft

Hippocampus 0.15.8 packages the integrated durable-session runtime for Claude Code and Codex. It adds startup-budget and evidence-based slimming commands, stored-owner checks for asks, approved decision-document filing, backlog catch-up and durable checkpoint workflows using configured record, scheduler and reporting integrations. Retired OpenClaw setup/composition support is removed.

These workflows retain approval and receipt requirements and need the user's configured integrations. Installing the package does not enable recurring filing or approve changes to personal rules or knowledge. This is a package delivery for the next live checks, not the announced public launch of session features.
