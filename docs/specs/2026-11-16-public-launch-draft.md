# Public launch: setup, policy, lookup and README

Draft for Corey, 2026-11-16. **Not approved. Implementation and launch remain on hold.** Independent spec review has not been requested or run.

Origin: [coreyfloyd/hippocampus#112 — Make setup opinionated and rewrite the README](https://github.com/coreyfloyd/hippocampus/issues/112), within the [Public launch milestone](https://github.com/coreyfloyd/hippocampus/milestone/1). This combines the three setup slices and the companion lookup scope into one decision pass; it does not authorize a release announcement, deployment or README publication.

## Problem Statement

Setup still offers optional knowledge/wiki paths, creates development rule targets without checking which tools are installed, and distributes policy among several files. The launch tickets retain unresolved choices and explicitly withhold implementation approval. (validated: live ticket bodies and comments, setup and policy readers inspected November 16)

## Solution

Propose one complete new-user knowledge setup, only the required provider entry points, and a single knowledge-profile home for user policy. Add one reusable local-only lookup skill and a short startup/post-compaction reminder. Retain the complete README revision 3 for wording review. The four decisions below determine the final scope; recommendations are proposals, not settled decisions.

## User Stories

### <a id="setup"></a>Complete setup

As a new user, I want one complete knowledge setup; as an existing user, I want to review every proposed upgrade without losing files or custom choices.

### <a id="rules"></a>Portable rules

As a user of one or several providers, I want shared source rules and only the tool entry points my installed tools need.

### <a id="policy"></a>Understandable policy

As a user, I want one place to understand where lessons go and whether recommended lessons and knowledge apply automatically.

### <a id="lookup"></a>Use stored knowledge

As a user, I want an unfamiliar named reference checked against my configured local knowledge before the agent asks me or begins external research.

### <a id="readme"></a>Understand the whole product

As a prospective user, I want to read the complete explanation, including diagrams, and find installation/setup separately.

## Acceptance criteria

### [Complete setup](#setup)

- New setup requires a knowledge root with retained sources, research outputs, operating records and a compiled wiki; it proposes the session cache, operation and decision logs, and two independently configured follow-up destinations.
  - Check: controlled empty roots through setup; verify the complete mutation plan and resulting valid profile in both tool paths.
- New setup cannot finish through a checklist-only or wiki-disabled path. Record integrations, meeting connectors, editor and tool-memory choices remain independent; no particular editor or task service is required.
  - Check: inspect every first-use branch and exercise configured/unconfigured optional integrations against controlled inputs.
- An existing released wiki-disabled profile remains readable. Setup identifies the missing launch configuration and offers an explicit upgrade; declining leaves the profile and retained content unchanged and reports that launch setup is incomplete.
  - Check: controlled version-4 wiki-disabled profile, decline then accept; byte comparison after decline and valid complete setup after acceptance.
- Re-running setup preserves existing files, custom destinations and user text; it previews exact changes and writes only the approved current plan.
  - Check: seed custom files, re-run twice, change the plan after approval, and verify preservation, no duplication and rejection of stale approval.

### [Portable rules](#rules)

- Keep standard and thin presets and per-tool overrides. Recommend thin for multiple providers or portability; do not recommend it universally to single-provider users.
  - Check: reviewer compares the interview against single-provider, multi-provider and explicit portability scenarios; behavioral checks use controlled tool inventories.
- Shared rule sources remain provider-neutral. Claude receives a minimal import entry where required; Codex receives its instruction entry. A development root receives only entries needed by the selected installed tools, with an explanation of how each tool discovers those rules.
  - Check: Claude-only, Codex-only and combined fake homes; inspect planned entries and source references, then verify supported delivery in both adapters.
- An absent repository AGENTS.md does not make CLAUDE.md the default substantive source. Custom source paths and existing entry content remain owned by the user; no existing file is deleted automatically.
  - Check: controlled repositories with neither entry, either entry, both entries and custom source paths. Coordinate with [coreyfloyd/hippocampus#45 — custom rule sources](https://github.com/coreyfloyd/hippocampus/issues/45) before implementation.

### [Understandable policy](#policy)

These criteria apply if decision Q2 selects consolidation.

- The knowledge profile owns destination overrides, memory policy, produced-surface mappings and regeneration commands, lesson proposal policy and destination, pull-request rules and command, and the package auto-apply setting. The checklist profile owns record writes and workflow bindings; runtime configuration owns state/checkpoint settings. No second active policy owner remains.
  - Check: controlled policy inventories and every consumer; compare planned destinations and actions before and after consolidation.
- Preserve the current shared auto-apply behavior: off by default; on allows recommended lessons and eligible knowledge captures; lesson-policy propose still prevents lesson applying; a fact about the user still needs the user's answer. Setup explains and previews the setting explicitly.
  - Check: controlled matrix of on/off, lesson propose/apply and user facts through wrap and sweep; compare outcomes and retained asks.
- Custom routing continues to replace the default routing table. Defaults apply when no custom table is supplied. Preserve user mappings, commands and proposal destinations; do not silently merge defaults into a custom table.
  - Check: custom table deliberately omitting a default route; verify the omitted route stays omitted and generated surfaces resolve to their sources.
- Setup shows the exact policy move, preserves original material until approval and refuses conflicting owners until the user resolves the displayed conflict. Relative references retain their effective destinations when ownership moves. After the approved replacement there is one active owner, with no alias or dual-reader compatibility layer for unreleased session policy.
  - Check: old/new policy with conflicting values and relative paths; decline is byte-preserving, accept leaves equal effective destinations and one active owner. No silent migration at session startup.

### [Use stored knowledge](#lookup)

- Provide one local-only lookup skill. It reads configured locations and searches in order: compiled wiki, operating records, research outputs, retained raw sources, then approved user additions. The procedure uses bounded native searches, finite result excerpts and explicit hit, miss or access-error reporting; it stops when it has a useful answer.
  - Check: controlled locations with early and late answers, a miss, unreadable location and excessive matches; reviewer inspects the bounded procedure and its output evidence.
- A useful result cites source files and dates where available, distinguishing dated or conflicting evidence. A miss or access error lists searched locations; lookup itself never browses, asks for a product decision or writes knowledge.
  - Check: same controlled cases and review of results in both tools. External verification of time-sensitive facts remains the research caller's responsibility.
- Startup and post-compaction context in both tools include a short reminder naming the skill. The reminder and discovery triggers cover unfamiliar named references and the start of external research; no claim of guaranteed model compliance is made.
  - Check: controlled startup and compaction adapter payloads, followed by an unfamiliar-reference scenario in each harness. Record whether actual invocation occurred rather than equating injection with compliance.
- Research skills reuse the procedure and any result already obtained for the same question in the current task. They own subsequent external research. Setup shows custom local additions, order and tool preference for approval; re-running does not duplicate them or silently change existing user rules.
  - Check: review both research callers; controlled setup with additions, no additions and a re-run; observe reuse within a task.

### [Understand the whole product](#readme)

- The review includes every paragraph, list and link from the retained revision-3 proposed README, plus all four diagrams, with attached feedback for each section and diagram. Present feedback in stages of at most five units while keeping the complete text accessible.
  - Check: source-section text comparison, four diagram byte comparisons, every feedback unit retained after reload, phone rendering and no missing assets.
- The wording describes a portable memory and knowledge system with built-in self-improvement, addresses users beyond developers and links a separate installation/setup guide. It does not advertise unbuilt lookup or external fleet automation as shipped.
  - Check: compare the complete candidate against current shipped capabilities; reconcile any selected implementation change before publication.
- Wording approval is separate from implementation approval and release/publication permission. A request for edits, an information request or an unanswered required decision never counts as approval.
  - Check: intercepted form submissions cover approve, reject, missing answer, INFO, section edit and cancel; no actual user verdict is generated during QA.

## What stops working

If Q1 is approved, new users cannot complete setup without the wiki or use checklist-only completion. Existing wiki-disabled profiles remain readable but are marked incomplete until an explicit upgrade. Development rule files for providers the user does not use are no longer created automatically. If Q2 consolidation is approved, the old standalone routing file and runtime auto-apply field cease to be active owners after the reviewed replacement; unreleased session policy gets no compatibility reader.

## Guardrails

Preserve the released install path, version-4 knowledge-profile readability and composer entry point. Preserve custom rule sources, existing content and all effective routing responsibilities. No silent rewrite, deletion or startup migration. Session features are unreleased and replaced outright. Both Claude Code and Codex ship equivalent behavior. Required knowledge does not imply a particular tracker, editor or meeting connector. Facts about the user still require an answer.

## Data Model

One knowledge profile describes a user's root and knowledge policy. One optional custom routing table replaces built-in destinations. One auto-apply choice governs lessons and eligible knowledge, with a lesson-only propose override. A checklist profile contains workflow integrations. Runtime settings describe operational state. Ordered user search additions contain a local location, its position and optional purpose/tool preference. One lookup result contains searched locations, useful citations or an explicit miss/error. The exact representation remains an implementation choice subject to the preservation criteria above.

## Documentation consulted

No new third-party API or service is proposed. This draft relies on the repository's existing setup, composer and adapter entry points, not on an undocumented provider extension. Installed provider discovery requirements must be verified against the applicable provider documentation before implementation; current source behavior is not proof that a development-root entry is discovered by every provider.

## Existing systems

- Reuse setup planning and approved mutation handling in `scripts/rules_setup.py`, the version-4 reader in `scripts/validate_profile.py`, and the composer entry point in `scripts/compose_rules.py`. Current target planning emits both development files; current profile validation reads wiki-disabled profiles. (validated: source inspection)
- Reuse lesson and knowledge outcome handling in `scripts/lib/lessons.py` and `scripts/lib/knowledge.py`, with wrap/sweep callers. Current lesson policy is read from routing and auto-apply from runtime configuration. (validated: source inspection)
- Reuse the existing startup/compact delivery in `hooks/hooks.json`, shared handoff engine and Codex adapter; do not add a timer, persistent daemon or separate search service. Research callers delegate to one skill rather than duplicating its instructions. (validated: hook configuration and research skill inventory; inferred: reuse proposal)
- Retained README revision 3 supplies nine text sections and four diagrams. The retained response file contains an operational probe, not a user decision. (validated: retained source inventory and response read)

## Testing Decisions

Use setup's plan/apply boundary against fake roots, profiles and tool homes; use composer outputs and wrap/sweep outcomes for policy behavior; inspect both startup/compact adapter outputs. Tests control their fixtures and validate behavior or configuration validity, never live wording, names, counts or configuration values. Review skill wording as instructions. Run targeted tests and the repository quick checks; CI remains the full-suite gate. A new head gets its own verification. Independent spec review remains an explicit user choice, not silently requested by this pack.

## Migration strategy and cutover criteria

Before implementation: explicit answers to the four decisions and approval of the resulting spec, plus verified provider discovery documentation. Before any user's setup writes: show the exact plan, conflicting policy owners and affected paths; obtain that user's approval of that plan. Decline preserves current bytes. Existing wiki-disabled profiles remain readable; explicit setup completes them. Do not add a migration daemon or compatibility aliases for unreleased session policy. Validate fresh setup, accepted upgrade, declined upgrade and repeat setup in isolated roots before delivery. After deployment, record the exact release and both tool versions and verify delivered setup/reminder behavior. Deployment and publication require their own authorization; this draft changes no live configuration.

## Out of Scope

Release announcement, tag, deployment, README publication, repository onboarding automation, cross-machine synchronization, a new search index/service, automatic web fallback inside lookup, separate lesson/knowledge auto-apply switches, and changes to the implementation-placement model.

## Evaluator Rubric

Runtime rubric, with explicit attention to both-tool parity, one policy owner, preserved custom destinations, mutation approval, safe repeat setup, bounded lookup and honest miss/error evidence.

## Open questions

### Q1 — Complete setup and required rule entry points

For [coreyfloyd/hippocampus#215 — Require knowledge and wiki setup for launch](https://github.com/coreyfloyd/hippocampus/issues/215) and [coreyfloyd/hippocampus#216 — Limit Claude rule files to required entry points](https://github.com/coreyfloyd/hippocampus/issues/216):

- **Q1A (recommended):** Approve the complete setup/rules criteria above. New users get the required wiki; existing disabled profiles require an explicit upgrade; both presets remain; provider entry files are limited to selected installed tools. Gain: carries forward the already selected launch direction with preservation rules. Cost: some existing users must finish setup and both tool paths need verification.
- **Q1B:** Revise the setup/entry-point plan before implementation. Retain the current behavior meanwhile. Gain: resolves remaining entry ownership concerns first. Cost: these launch blockers remain open. Making optional wiki the launch path would reverse the recorded required-wiki decision and needs an explicit statement.

### Q2 — One policy home, same behavior

For [coreyfloyd/hippocampus#217 — Unify knowledge and lesson policy ownership](https://github.com/coreyfloyd/hippocampus/issues/217):

- **Q2A (recommended):** Consolidate policy into the knowledge profile with the preserved semantics above; keep the shared auto-apply switch and defer splitting lessons from knowledge. Gain: one policy home without changing who may apply what. Cost: all readers and relative paths must move together through reviewed setup.
- **Q2B:** Retain four files for launch and document their boundaries and precedence. Gain: avoids moving policy now. Cost: the split ownership remains; this narrows the consolidation ticket and needs an explicit launch-scope decision.
- **Q2C:** Split lesson and knowledge automation while consolidating. Gain: independent controls. Cost: new behavior, additional setup choices and outcome combinations; revise the spec before implementation. This would replace the shared-switch decision previously recorded on [coreyfloyd/hippocampus#99](https://github.com/coreyfloyd/hippocampus/issues/99).

### Q3 — Local lookup implementation scope

For [coreyfloyd/hippocampus#207 — Search stored knowledge before asking or web lookup](https://github.com/coreyfloyd/hippocampus/issues/207):

- **Q3A (recommended):** Approve one local-only skill using bounded native search, startup/post-compaction reminder and reuse by research skills. Gain: centralizes the procedure without a new executable. Cost: skill selection still relies on model compliance. Prior modeled token comparisons do not establish a measured end-to-end benefit for a helper.
- **Q3B:** Add a deterministic search helper. Gain: enforces order, bounds and errors once called. Cost: another maintained interface; it still cannot ensure invocation. Revise the helper contract and verification before implementation.

### Q4 — Complete README wording

For [coreyfloyd/hippocampus#112 — Make setup opinionated and rewrite the README](https://github.com/coreyfloyd/hippocampus/issues/112):

- **Q4A (recommended):** Approve the complete retained revision-3 wording and four diagrams as the wording baseline, subject to matching the final approved scope before publication. Gain: resolves the existing whole-product copy review. Cost: wording may need a focused reconciliation after the selected features land; it does not authorize publication or launch.
- **Q4B:** Return section/diagram edits or questions. Gain: preserves precise feedback against the complete candidate. Cost: wording remains unapproved until the revision is reviewed.

Every question also permits “Need more information.” Recommendations are not preselected answers. Approval with an unanswered question or an information/edit request is feedback only. Proposed approval authorizes implementation only for the fully specified Q1A/Q2A/Q3A scope and approves Q4A wording; alternatives requiring revision produce a new draft rather than implicit implementation authority.

## Further Notes

This needs several existing tickets, not a new umbrella or duplicate breakdown. No dependency is inferred from build order: query native blockers before execution, wire only real blockers, and parallelize independent approved tickets. The README remains a separate wording review within the single pack. The complete retained README and diagrams accompany the rendered pack; their source lineage is recorded there. Approval: pending.
