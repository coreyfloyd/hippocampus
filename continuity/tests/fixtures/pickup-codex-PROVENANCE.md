# Codex rollout fixtures for pickup.py (#1453)

Every file below is a redacted copy of a real Codex rollout captured on the
MacBook on 2026-09-23. `redact_pickup_codex_rollout.py` (same directory)
produced each one. None is hand-written. The sha256 is of the unredacted
source file at capture time.

| Fixture | Source rollout (under `~/.codex/sessions/`) | Source sha256 | Redactor flags |
|---|---|---|---|
| `pickup-codex-rollout.jsonl` | `2026/09/06/rollout-2026-09-06T16-28-41-01a078d6-8cc9-7630-9c55-b658dedb03fa.jsonl` (root thread, `codex_exec`, cli 0.153.4, 162 rows) | `08e8c6928c4695e8616b762f7d056c55fda536cffb4936e0b681cee2bea28fdc` | `--redact-commands --neutral-names` |
| `pickup-codex-paginated-base.jsonl` | `2026/09/21/rollout-2026-09-21T16-02-19-01a0c5fd-cab8-7960-8ba7-8a5c9d3e6759.jsonl` (base file of the only paginated thread on the box, 4,252 rows) | `60c8d6ec1505e1afc09d9ffd9b4b2ed56640a0d3990b48c74a4f1e02754ab603` | `--first-turn --redact-commands --neutral-names` |
| `pickup-codex-paginated-window.jsonl` | `2026/09/23/rollout-2026-09-23T15-00-25-01a0c5fd-cab8-7960-8ba7-8a5c9d3e6759_01a0d011-d843-7552-b2ab-b25f304269ed.jsonl` (window file of the same thread, 379 rows) | `1fcede9cc9f0cf94915a009cdacf60dd9ce022f915e24d1f980298a7105329b3` | `--first-turn --redact-commands --neutral-names` |
| `pickup-codex-subagent.jsonl` | `2026/09/04/rollout-2026-09-04T19-57-10-01a06f48-b1f1-7013-9ffa-40bf188e242d.jsonl` (subagent: `session_id` = `parent_thread_id` ≠ `id`, cli 0.151.0, 13 rows) | `51b632deac92f5f520ab7ddd2d95e5ac3bc9eaddc6a2de891f7753fc3e807188` | `--redact-commands --neutral-names` |

Facts measured on the unredacted sources before redaction:

- Root rollout: one `UserMessage` item, one `final_answer` assistant message,
  `session_meta.payload.id` equals the filename thread id and `session_id`.
- Paginated pair: both files carry `session_meta.payload.id`
  `01a0c5fd-cab8-7960-8ba7-8a5c9d3e6759`. The window file's
  `history_base.thread_id` is the same id. Its filename carries the thread id
  plus a `_<window id>` suffix. `--first-turn` keeps each file's records
  through its first `task_complete`, a real prefix of each file.
- Subagent: `payload.id` `01a06f48-b1f1-7013-9ffa-40bf188e242d`,
  `payload.session_id` and `parent_thread_id`
  `01a06f48-b18c-7551-9ba3-6d17160c21ca`.

Why `--redact-commands`: every source is a private session, and no test reads
command text. The fixtures keep identity, ordering, roles, phases and exit
codes, with command text, command cwd, outputs and changed paths replaced by
placeholders. `--neutral-names` replaces each worktree and branch name (a ticket
number and a work title) with `feature-a`, `feature-b`, ...; trunk names are
kept. The Claude transcript `pickup-session.jsonl` gets both flags from
`redact_pickup_transcript.py`.

Tests copy these files into a sandboxed `CODEX_HOME` under their canonical
rollout filenames (dated `sessions/YYYY/MM/DD/` or flat
`archived_sessions/`). The automatic-listing tests also rewrite the recorded
cwd in the sandbox copy to the sandbox directory, because the wrapper
resolves the invoking directory from `$PWD`.

Neutral stand-ins: after redaction, every file in this directory, and the Claude
transcript `pickup-session.jsonl`, went through one more pass that replaced the
names, repositories, projects, products, channels, paths, host names, and network
addresses of the person who captured them with fixed stand-ins (`alexrivera/example-config`, `/Users/alex`,
`node1`, `100.64.0.1`, and similar). The pass changes text only: row counts, row
order, ids, timestamps, and structure are those of the redacted records. The list of
what was replaced is kept outside this repository, because the list itself would be
the reference the repository must not carry. Tests assert on the stand-ins.

Regenerate the redaction (then apply the stand-in pass to the output):

```bash
R=tests/fixtures/redact_pickup_codex_rollout.py
python3 $R --redact-commands --neutral-names <root source> tests/fixtures/pickup-codex-rollout.jsonl
python3 $R --first-turn --redact-commands --neutral-names <base source> tests/fixtures/pickup-codex-paginated-base.jsonl
python3 $R --first-turn --redact-commands --neutral-names <window source> tests/fixtures/pickup-codex-paginated-window.jsonl
python3 $R --redact-commands --neutral-names <subagent source> tests/fixtures/pickup-codex-subagent.jsonl
python3 tests/fixtures/redact_pickup_transcript.py --redact-commands --neutral-names <transcript source> tests/fixtures/pickup-session.jsonl
```
