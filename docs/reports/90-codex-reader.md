# Codex trust-response reader — issue 90

The production trust reader can report a missing response even when a complete
response has already arrived. An isolated real-pipe test confirms this defect;
this report does not attribute every historical timeout to it. (validated:
red/green regression; inferred: historical failures lack protocol transcripts)

Issue: [hippocampus90](https://github.com/coreyfloyd/hippocampus/issues/90).
Candidate base: `66bdcbe`. Release preparation: 0.15.6. Publication, signing,
activation, pull-request CI and independent evaluation remain outside this
implementation handoff. (validated: bounded preparation scope)

## Reproduction and cause

`verify_with_hooks_list` in `scripts/lib/codex_trust.py` originally used
`select` on subprocess stdout followed by a text-buffered `readline`. The first
line read can prefetch the following response into Python's text buffer. The
next `select` then waits on an empty OS pipe while the response remains unread
in that buffer. (validated: production source and controlled pipe reproduction)

The test imports the actual helper and supplies a harmless executable stub,
with temporary home, configuration and state paths. The stub replies to request
1 with `b'{"id":1,"result":{}}\n'`. For request 2 it makes one `os.write` with
these exact bytes, then remains alive reading stdin:

```python
b'{"method":"fixture/notification"}\n{"id":2,"result":{"data":[]}}\n'
```

Before implementation, this test failed with
`RuntimeError: app-server returned no response for request 2` after 15.45 seconds.
The existing code had received the response; the text/descriptor read boundary
prevented it from seeing the buffered line. (validated: real subprocess/pipe
fixture using the unchanged helper)

## Fix and scope

The helper now writes encoded request bytes and keeps one explicit byte buffer
for stdout. It drains complete newline-delimited frames before waiting for OS
pipe readiness and retains partial frames between reads. Unrelated notifications
are consumed until the matching response is found. The request deadline stays
15 seconds. Hashing, trust decisions, initialization messages and rollback code
are unchanged. (validated: source diff and affected regression tests)

The new test file covers the coalesced notification/response, split responses,
a split response beside a notification, multiple notifications, EOF before the
matching response and rejection of a matching untrusted hook. The tests use
controlled protocol inputs and do not depend on installed hook names, settings,
rule wording or live CLI state. Existing installer collision/verification-failure
coverage still confirms rollback. (validated: executed affected tests)

Claude Code retains its existing installation and hook contracts. `VERSION`
and generated plugin metadata advance together to 0.15.6; the Codex installation
receipt continues to derive its package version from `VERSION`. No provider
receives a new session or hook contract. (validated: candidate diff and release
metadata checks)

## Verification

- **T1 — Red:** `python -m pytest -q -p no:cacheprovider tests/test_codex_trust_reader.py -k coalesced` failed once with the expected false request-2 timeout; 5 other cases were deselected. (validated: baseline test output)
- **T2 — Green and preservation:** `python -m pytest -q -p no:cacheprovider tests/test_codex_trust_reader.py tests/test_release_metadata.py tests/test_codex_adapter.py -k 'trust_reader or release_metadata or collision_and_verification_failure or two_reinstalls_preserve_adjacent_foreign_agent_block or reinstalls_leave_whole_config_stable or remove_trust'` passed: 25 passed, 117 deselected in 5.04 seconds. (validated: affected test output)
- **T3 — Repository quick checks:** metadata generation check, fold-name check (5 passed), public-document check (14 tests, 1 optional skip), skill-surface check and `git diff --check` passed. (validated: required quick-check outputs)

Full local suites were deliberately unrun under the repository's verification
instructions. Full validation belongs to pull-request CI. No live app-server,
installer, signing operation, tag, release publication or package activation ran.
(validated: implementation command history)

## Review and delivery

The candidate is a source repair and patch-release preparation. The next owner
must run independent review and pull-request CI against the exact delivered
commit, then prepare the exact-release approval through `RELEASING.md`. A changed
release candidate needs its own approval. The maintainer's signing step and normal
signed-release installation remain necessary before claiming deployed recovery.
(validated: release runbook and bounded implementation ownership)
