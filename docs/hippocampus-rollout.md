# Hippocampus rename rollout

Approved by Corey on 2026-09-10: complete repository/product rename with installation migration. Tracking: [research-tools issue 17](https://github.com/coreyfloyd/research-tools/issues/17).

## Candidate and verification

The public package candidate is prepared on `rename-hippocampus`. The accompanying private dotfiles compatibility change is prepared on `hippocampus-integration`. These are one migration: the private installer must preserve the package's Claude and Codex links under either name, and must preserve the user's migrated profile.

The public package remains independent of private dotfiles. Its migration supports package-owned published research-tools installations; the private harness retains ownership of its own template and installer integrations.

Before landing, verify fresh installation, upgrade from the actual published v0.7.0 source, repeated installation, conflicting profiles and foreign links, interrupted migration recovery, profile-content preservation, and unchanged knowledge-root contents. Run public contract/install/release suites and Swift tests. Run private installer integration tests in a disposable copy with an isolated home. Record independent runtime evaluation against the exact public and private candidates on the ticket.

## Cutover order

1. Land the evaluated dotfiles compatibility change and deploy it through the normal dotfiles installation path. Its guard recognizes both package names, so it can precede the public cutover. Do not run the dotfiles installer from a linked worktree: it binds live links to the main checkout.
2. Land the evaluated public rename candidate. Preserve old tags, old signed release assets, and signing-key bytes/fingerprint.
3. Rename the existing GitHub repository to `coreyfloyd/hippocampus`, update clone remotes, and check the canonical URL plus old repository/issue redirects. Never create a replacement repository under the old name.
4. Finish all active linked-worktree operations before moving the MacBook checkout from `~/Development/research-tools` to `~/Development/hippocampus`. Repair linked-worktree metadata if any retained worktrees require it. Update the Codex project trust entry and current operator path references with the actual resulting path.
5. Follow `RELEASING.md` for the new version. Corey runs the real build-and-sign command from an interactive terminal; agents must not run the signing operation. Verify and publish the resulting assets, then download and verify the public assets again.
6. Install the verified new release on the MacBook, verify both clients' links and the migrated profile, and record the actual result. Schedule other machines using their documented host routes and deployment procedures; do not infer fleet deployment from a MacBook check.
7. Refresh current vault release/context references and the skill catalog after the name and installed skill actually change. Preserve historical release descriptions and the old signing-key UID as history/identity.
8. Announce only after the new release's documented installation path has passed verification. Announcement messaging needs its own explicit authorization.

## Preflight observed on the MacBook — 2026-09-10

- Local research-tools checkout started clean at `417a994`, with `main` as its sole worktree before candidate creation.
- Installed `research-tools/current` resolves to `research-tools/releases/0.7.0`. Both clients' old setup links point through that current pointer.
- The legacy profile is a regular file; the canonical Hippocampus profile and current pointer are absent.
- GitHub API reports admin permission, no Pages site, and an empty webhook list.
- The dotfiles main checkout has foreign modifications; its compatibility work uses a separate linked worktree.

These are preflight observations, not deployment or release-completion claims. No production profile or installed skill has been migrated by this preflight.

## Recovery constraints

Keep the old package release trees and profile available for recovery. A retry must not overwrite a differing destination profile or a foreign skill link. Use the migration instructions in `MIGRATION.md` for exact supported recovery steps. Do not move a published tag or replace historical signed assets to undo a rename.
