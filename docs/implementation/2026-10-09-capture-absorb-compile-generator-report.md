# Capture / absorb / compile generator evidence

Ticket: [hippocampus#31](https://github.com/coreyfloyd/hippocampus/issues/31).
Candidate branch: `codex/meeting-absorb-compile`. Starting commit: `ae82e49`.
Implementation commit: `b622db6`; subsequent candidate commit carries legacy-receipt
normalization, documentation, examples and this report. No merge or push was made
by this generator. Review, evaluation, ticket lifecycle, communication approval and
release remain orchestrator/maintainer responsibilities.

## Delivered behavior

- S1: profile v4 accepts optional meeting folder/template settings without creating
  files; bundled minimal template, explicit per-capture template override, contained
  record folders and clear invalid-template errors. Record identity reuse preserves
  its path, user prose and saved receipts. Independent note/transcript/calendar
  adapters and actual event URLs remain in the capture contract.
- S2: absorb owns shared row semantics and execution. Its deterministic helper
  validates parent decisions/evidence, executes only approved unblocked rows through
  explicit local workflows, persists inflight keys before writes, confirms matching
  receipts and prevents uncertain-effect retries. Changed scope invalidates approval;
  history survives. Legacy research read-back receipts can be adopted without writes.
  Research filing and original-source filing repair selected references, refuse
  collisions and preserve distinct provenance; meeting records remain in place.
- S3: wiki-compile owns synthesis; research-to-wiki/vault-compile delegate. Direct
  authorized selected-source compilation, local modes, source-first drafting,
  tensions/gaps, privacy, navigation and ingestion remain in the compiler contract.
  wiki-audit remains opt-in/read-only; vault-audit delegates with local policy.
- S4: package-owned wrappers, helpers and the bundled template reach both clients
  through existing manifest/installer mechanics. Unowned new-command collisions and
  custom-template preservation are tested. README, referenced SVG, existing deck,
  profile/setup/install/migration/architecture documents agree on the new lifecycle.
  Actual pre-change README/image/deck content is preserved as dated history (the deck has trailing whitespace normalized only); older
  specification review artifacts are unchanged.
- S5: meeting/research capture proposes source-linked new/enrich/published-follow-up
  opportunities or explicit none, with search coverage, attribution and reuse limits.
  Local writing storage/workflows stay user-configured. Tests exercise writing
  receipts and actual temporary seed writes, preserve authored prose, and skip retry
  duplicates. Public examples show all four routes for meeting and research records.

Source-retention reconciliation read the separate source-filing candidate's primary
meeting procedure via `git show`, then integrated its relevant contract into this
candidate: policy-defined raw intake/archive destinations, source identity reuse,
terminal-route gating, preserved primary content/metadata and verified link repair.
Its worktree remains at `19c9f6c`; no merge, publication or checkout mutation occurred.

## Verification on the MacBook

All of the following completed with exit 0 unless explicitly stated otherwise:

| Command | Result |
|---|---|
| `PYTHONDONTWRITEBYTECODE=1 python3 tests/test-capture-absorb.py` | 19 tests pass, including actual CLI workflow effects, selected-only dispatch, in-place retries, legacy receipts, source exclusion, writing seeds, retention collisions and reference rebasing |
| `python3 tests/test-profile-meetings.py` | 12 tests pass; absent defaults, overrides, symlink containment, template failures, existing note URL/path cases |
| `bash tests/test-contracts.sh` | Pass; expected invalid-profile refusals are negative tests |
| `bash tests/test-install.sh` | Pass; temporary homes only, both-client parity, 8 new-command collision cases, custom-template preservation, upgrade/retry/tamper and actual v0.7.0 migration |
| Final temporary-home `bash install.sh` and `bash install.sh --verify` with a wiki-disabled profile | Pass; the final normalized template is byte-identical in both isolated clients |
| `bash tests/test-release.sh` | Pass; disposable repositories/keys only; expected checksum/signature refusals are negative tests, not published signing |
| `swift test --scratch-path /tmp/hippocampus31-swift-build` in the Apple Speech package | Initial exit 1: nested `sandbox-exec` refused; no source failure established |
| `CLANG_MODULE_CACHE_PATH=/tmp/hippocampus31-clang-cache SWIFTPM_MODULECACHE_OVERRIDE=/tmp/hippocampus31-module-cache swift test --disable-sandbox --scratch-path /tmp/hippocampus31-swift-build --cache-path /tmp/hippocampus31-swift-cache --config-path /tmp/hippocampus31-swift-config --security-path /tmp/hippocampus31-swift-security` | Pass: 5 unchanged Swift tests in 2 suites, using temporary caches/build paths |
| `python3 <installed skill-creator>/scripts/quick_validate.py skills/<name>` for absorb, wiki-compile, vault-compile, vault-audit, research-absorb, research-to-wiki, meeting-capture and wiki-audit | All 8 pass |
| Concrete relative Markdown reference scan under skills; `xml.etree.ElementTree.parse` on the public SVG | No missing concrete skill links; SVG parses. Initial broad scan caught existing literal `(url)` examples; the concrete-link scan excludes those placeholders |
| `uv run --with markdown python scripts/render-public-review.py` | Pass; full before/after README, image and existing presentation embedded/linked in portable HTML |
| `git diff --check ae82e49 HEAD` | Final committed-range check passes; the audit found and removed whitespace in the new template and historical HTML snapshot |

The behavior tests were written and observed failing before their production
mechanics were added. Fixtures use the public package wiki contract and isolated
workflow scripts; no private transcript, personal task or live-provider write.
Install/release checks were repeated after the legacy-receipt implementation.

## Documentation/browser limitation

`node <installed archify>/bin/archify.mjs finalize architecture docs/architecture/runtime.architecture.json docs/architecture/runtime.html --repo-root . --quality showcase --out-dir /tmp/hippocampus31-map/review-2 --json`
passed validate, deliver and strict provenance checks, but exited 1 at browser-check:
Chrome's DevTools pipe ended. The first layout attempt failed desktop text readability;
its repaired candidate passes that validation. A separate headless Playwright
inspection also failed to launch: macOS denied Chrome's Mach-port rendezvous endpoint
within this session sandbox. Neither produced usable screenshot evidence. No visual
quality or full Archify PASS is claimed. Browser verification must run in the
orchestrator's supported inspection environment before documentation sign-off.

Review artifacts: `docs/reviews/2026-10-09-public-documentation.html` and `.md`,
plus dated pre-change files. The orchestrator can publish the portable review using
its authorized persistent delivery route. Public-communication approval is pending;
this generator did not host or publish the review.

## Residual boundaries

The deterministic helper verifies local mechanics and adapter receipts. Skill-driven
semantic source reading, source-identity resolution across provider inventories,
context confirmations, idea/draft/publication searches, authored-prose ownership,
remote task read-back and discovery of all affected references remain the invoking
agent and configured destination workflow's responsibilities. Tests do not establish
live provider access or prove that an agent obeys Markdown instructions. No live
capture/backfill, production install, personal tasks, messages, tag, release, real
maintainer signing, independent review or rubric evaluation was performed here.
