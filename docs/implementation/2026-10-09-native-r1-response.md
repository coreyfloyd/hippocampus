# Native review round 1 response

Ticket: [hippocampus#31](https://github.com/coreyfloyd/hippocampus/issues/31).
Native review receipt `attempt_id`: `4692da10a47bae2dd8b9f35e`.
This response belongs to the same already-launched generator, round 1.
Reviewed candidate: `db8425b5c48e13d8d08052840358b06f18a667b3`.
Reviewed base: `f4314546fc06825746d0670da4c9988c5cc67ce4`.
Repair commit: `ce6b7c7`. This report is carried by the subsequent ordinary evidence commit; no runtime admission record was authored.

## Finding dispositions

Both findings are accepted; none rejected or deferred. (validated: primary implementation and reproduced regression failures)

| Finding | Primary evidence and repair | Regression evidence |
|---|---|---|
| P2: reject escaping relative meeting templates | `scripts/validate_profile.py`, `meeting_settings`: the reviewed code joined a relative template to the root without checking its resolved location. Resolve that branch and require containment before reading it. Explicit absolute templates and the package default retain their existing behavior. | The new profile test failed for `../outside.md`, a file symlink and a directory symlink; the capture override test failed for traversal and a file symlink. Both suites now pass. Existing internal relative/absolute templates, an internal symlink, normalized `./` paths, external absolute templates and identity-preserving recapture pass. Invalid selections create no meeting folder. |
| P2: root-relative transcript source filing | `skills/absorb/scripts/distribution.py`, `file_source`: the reviewed code resolved a supplied `raw/...` path against `root/raw`, duplicating its prefix. Resolve against the knowledge root, then apply the existing raw containment check to that absolute result. | The new root-relative filing test failed with “source to retain is unavailable” before repair. Relative and absolute forms now preserve bytes, source IDs, digests and partial coverage, repair prose links and JSON source paths, and keep the meeting record in place. Real CLI calls from another working directory verify root-based resolution, pending-route refusal, different-content collision refusal, identical-copy reconciliation and already-retained destination retry. |

Supported refusal variants include sources outside raw, traversal outside the knowledge root, source symlinks outside raw, retained folders outside raw, escaping destination symlinks and missing reference targets. These preserve the intake source and record. Existing tests continue to cover approvals, uncertain-effect reconciliation, confirmed receipt reuse, changed-scope history, wiki-disabled routes, all writing modes, authored prose, legacy receipts and the distinct research archive transition. (validated: 22 behavior tests and 13 profile tests)

## Candidate and package hygiene

Preserved the native capture, immutable receipt, launch guard, orchestration brief and evidence sidecar in place. Added ignore patterns for those runtime files and Python caches; none were staged. Added export-ignore rules so even accidentally tracked native review files and caches cannot enter a release archive. The installer excludes `__pycache__`, `.pyc` and `.pyo` from copied skills and current manifests; the legacy manifest calculation is preserved for existing releases. (validated: install migration suite and release archive tests)

The install regression initially exited 1 because cache fixtures were copied into the installed skill. After exclusions it passes. The release regression deliberately force-tracks a synthetic native capture and cache in its disposable repository; neither file nor the cache directory appears in the archive. Its first run caught an empty cache directory left by file-only export rules; directory exclusion repaired that failure. The archive inventory still equals tracked files minus actual Git export-ignore attributes. Disposable test keys are used only by the existing release suite. No maintainer signing or release publication occurred.

Native evidence hashes, verified before and after repair:

- `review-r1-4692da10a47bae2dd8b9f35e.txt`: `adfab75aeb91cbb5f9ec77b0c668500ff7bd5dee91aeb4d867c3964e46cfca37` (matches the immutable receipt).
- `review-r1-4692da10a47bae2dd8b9f35e-handoff.json`: `da76a950a2276b2b5555fd507949eee7988d934b94146c62c64a5aaba30af992`.

## Mechanical contract sweep

Ran the following against both complete affected implementation files and their caller contracts, profile/setup instructions, public documentation and installer surfaces. It produced 282 matching lines; checked the path/transition claims against implementation and regression results, including source/record distinction, selected-template precedence, default/no-write validation, root containment, terminal gating, collision checks, reference rebasing, exclusion fields and CLI argument routing. (validated: source inspection and tests)

```sh
rg -n -i 'never|always|cannot|only|unique|all [0-9]|relative|absolute|fields|file-source|template|retention|intake|archive|collision' scripts/validate_profile.py skills/absorb/scripts/distribution.py skills/absorb/SKILL.md skills/absorb/references/distribution-contract.md skills/absorb/references/artifact-contract.md skills/meeting-capture/SKILL.md skills/knowledge-capture/references/meetings.md profiles/karpathy-wiki.example.md skills/hippocampus-set-up/SKILL.md README.md INSTALLATION.md MIGRATION.md install.sh .gitattributes .gitignore
```

The placeholder whitelist still matches the six documented tokens. The record/row schema and all six distribution kinds remain unchanged. Relative note-source defaults and explicit absolute note sources retain their independent semantics; the template repair does not restrict absolute inputs. Transcript filing still gates on terminal rows before mutation and uses the existing collision/reference repair implementation. Semantic approval, complete reference discovery and provider read-back remain invoking-skill/workflow responsibilities, rather than claims of deterministic validation.

## Exact verification

Executed on the MacBook (`MacBook-Pro-M5.local`). All final commands below exited 0. Expected refusal output in negative tests does not indicate suite failure. Logs remain scratch artifacts; results are recorded here durably.

| Command | Result |
|---|---|
| `PYTHONDONTWRITEBYTECODE=1 python3 tests/test-profile-meetings.py` | 13 tests pass; before repair exited 1 with three traversal/symlink failures |
| `PYTHONDONTWRITEBYTECODE=1 python3 tests/test-capture-absorb.py` | 22 tests pass; initial 21-test regression run exited 1 with two template failures and a root-relative filing error |
| `bash tests/test-contracts.sh` | Pass, including profile and public-content leakage checks |
| `bash tests/test-install.sh` | Pass in temporary homes, both clients, unowned collisions, profile/template preservation, migration, retries and cache exclusion; initial cache regression exited 1 |
| `bash tests/test-release.sh` | Pass in disposable repositories, including forced tracked-runtime/cache exclusions, exact archive inventory, signatures, tampering and install round trip; first exclusion run exited 1 on an empty cache directory |
| `bash -n install.sh tests/test-install.sh tests/test-release.sh` | Pass |
| `git diff --check` | Pass before repair commit |
| `shasum -a 256 docs/implementation/review-r1-4692da10a47bae2dd8b9f35e.txt docs/implementation/review-r1-4692da10a47bae2dd8b9f35e-handoff.json` | Capture and receipt unchanged |

From `skills/transcribe/tools/apple-speech`:

```sh
CLANG_MODULE_CACHE_PATH=/tmp/hippocampus31-clang-cache SWIFTPM_MODULECACHE_OVERRIDE=/tmp/hippocampus31-module-cache swift test --disable-sandbox --scratch-path /tmp/hippocampus31-swift-build --cache-path /tmp/hippocampus31-swift-cache --config-path /tmp/hippocampus31-swift-config --security-path /tmp/hippocampus31-swift-security
```

Result: five unchanged Swift tests pass in two suites. Temporary build/cache paths and the previously required nested-sandbox workaround were retained.

## Public documentation and remaining gates

No README, installation/migration prose, profile, contract, image, architecture diagram, example, presentation or rendered review content changed from `db8425b`. Verified with `git diff --name-only db8425b -- README.md INSTALLATION.md MIGRATION.md profiles contracts docs/presentation.html docs/images docs/architecture docs/reviews docs/examples`. No public review regeneration was necessary; earlier dated artifacts remain history. Added implementation/test content was scanned for private machine paths, with no matches. (validated: diff and added-line scan)

The orchestrator reports independent MacBook Playwright verification of all 11 presentation slides, forward/Previous navigation counters, slide bounds, visual inspection of slides 5–8, hosted comparison HTTP 200, four images and two presentation iframes loading without HTTP errors, 390px mobile width and the Light theme button. This is attributed browser evidence supplied in the review-response brief; the generator did not rerun it and does not claim a full Archify PASS.

Live provider behavior and agent adherence to semantic contracts remain outside the isolated tests. Independent runtime evaluation and maintainer approval of rendered public documentation/public communication remain later gates. This generator performed no reviewer/evaluator dispatch, lifecycle mutation, merge, production install, live capture/backfill, personal task write, publication or worktree change. The prior generator report remains dated history; this document records only the round-one repairs and their checks.
