# Generator report: literal rule targets

Implemented the approved composer extension for [hippocampus#229](https://github.com/coreyfloyd/hippocampus/issues/229). Same attempt resumed; no new run was created.

API: each explicit JSON target accepts `render: "literal"` or `render: "default"`. Omission means `"default"`: Claude retains existing imports; Codex/OpenClaw retain generated bodies. Literal rendering reuses the existing body renderer and ownership header, preserves complete ordered sources then extras, and retains final-newline handling. Invalid selections fail preflight. No generated imports or policy parser were added.

Fixture tests cover per-target selection, provider parity, complete bodies, authored imports/headings, ordering, invalid values, missing sources, overlap, user-content preservation, drift, idempotence and switching modes. Existing atomic writing and preflight remain in use.

## Verification

Logs are retained beside the runtime brief; their tails were read.

| Command | Actual result | Log |
| --- | --- | --- |
| `python3 tests/test-compose-rules.py` before implementation | Exit 1; 28 tests, 24 expected assertion failures including subtests | `red.log` |
| `python3 tests/test-compose-rules.py` after implementation | Exit 0; 28 passed | `green.log` |
| `PYTHONDONTWRITEBYTECODE=1 python3 tests/test-rules-setup.py` | Exit 0; 14 passed | `rules-setup.log` |
| `git diff --check` | Exit 0, initial and resumed | `quick-1.log`, `resumed-01.log` |
| `python3 scripts/generate-release-metadata.py --check` | Exit 0, initial and resumed | `quick-2.log`, `resumed-02.log` |
| `python3 tests/test-staged-release.py` | Exit 0; 1 passed | `resumed-03.log` |
| `python3 tests/test-fold-names.py` | Exit 0; 5 passed, initial and resumed | `quick-3.log`, `resumed-04.log` |
| `python3 tests/test-public-docs.py` | Exit 0; 14 tests, 1 skipped | `quick-4.log` |
| `python3 scripts/check-skill-surface.py skills` | Exit 0, initial and resumed | `quick-5.log`, `resumed-05.log` |
| `python3 -m pytest -q tests` | Exit 1: `No module named pytest` | `resumed-06.log` |
| Earlier requested classifier invocation with base `origin/main`, head `HEAD`, and external `verification.json` destination | Exit 2: script absent | `classifier.log` |

The repository declares no change classes. Positive path probes confirm that the composer and fixture test exist while `scripts/ci/change_classes.py` does not. The execution evidence therefore uses the documented CI suite command and the candidate's head/base, with no classifier fields.

## Candidate verification handoff

The initial serial candidate run stopped at Python's missing pytest module. The authorized continuation created an isolated virtual environment outside the checkout and installed pytest and uv 0.10.2 successfully, following CI's dependency setup. Existing failure logs are preserved. The approved implementation is committed using prior affected-test and quick-check evidence; the full CI suite and remaining documented checks run against that exact commit after commitment. Final outcomes, including any failure, belong to the external execution.json and GEN-REPORT.md so this tracked report does not change after verification.

No full-suite, CI, review or evaluation pass is claimed here. Release metadata, unsigned assets, signing/publication and live installation remain untouched. No acceptance-criteria disagreement was found. No agents, reviewers, evaluators, pushes or tracker mutations were made.
