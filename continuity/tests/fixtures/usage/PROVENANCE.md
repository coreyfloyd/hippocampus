# Transcript fixture provenance

Captured 2026-10-17 from real Claude JSONL and Codex rollout files.

- `claude.jsonl`: source `259934cc-30cb-4087-8c6a-cc13f4788366.jsonl`, SHA-256 `2450c081f0763ffacaab92eaf878bc92e9d0cf9f92941983fc11a70d3b652497`.
- `codex.jsonl`: source `rollout-2026-10-17T21-05-45-01a14cf8-ef21-7a51-bfac-56510cfad79e.jsonl`, SHA-256 `5ed0ab16647baa284761cad265d5a7aa17a3806b02db8e651fdd48184c70af93`.

The fixtures retain a skill read, a later tool input, and their corresponding
results, in their original order. Record envelopes, tool names, and call IDs are
preserved. Free text and outputs are removed; recorded skill paths map to
`/redacted/skills/workflow/SKILL.md`. Session identity is neutralized. Batched
commands are trimmed to a single representative command, retaining the shell
command/flag syntax needed by these tests; repository arguments are neutralized.

The small SKILL.md snapshot combines real command-bearing excerpts of the
installed tracker and git-practices skills, plus the user-supplied authorization
boundary. It tests section accounting without publishing complete private skills.
Headers are organizational test labels. It is not the complete historical skill.

Tests also derive partial/error/reordered variants from these captured records
to exercise detection boundaries. The three-session test changes one captured
session identity to exercise aggregation; it is not a third measured session.

The external record command name in the captured command and skill excerpt is
additionally neutralized to `record-cli`, preserving command structure and the
live-read boundary.
