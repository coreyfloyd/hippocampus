# Captured Codex contracts

The five hook payloads are derived from the live five-moment probe on CLI
0.160.0. The manifest pins both original and derived byte hashes. Only identity
and expired paths are replaced. Event-specific fields, tool input and string
output are unchanged. Tests relocate paths and vary scenario values in existing
fields; they never invent a hook shape.

Session metadata rows are projections of the existing captured resume fixtures
(interactive desktop, exec, and subagent). Usage is a projection of a real CLI
0.160.0 token-count row; rate-limit/account fields are removed. Tests vary numeric
usage to exercise the threshold, keeping the captured structure.

The completion row is projected from the existing captured Codex resume rollout.
It pins the real CommandExecution shape (id, command argv, exit_code, status and
aggregated_output). The quiet-commit scenario relocates its id and command to the
replayed hook, preserving the recorded successful exit status.

`pre-compact-output-0.167.0.schema.json` is the unmodified output schema from
[Codex rust-v0.167.0](https://github.com/openai/codex/blob/rust-v0.167.0/codex-rs/hooks/schema/generated/pre-compact.command.output.schema.json),
licensed under [Apache-2.0](https://github.com/openai/codex/blob/rust-v0.167.0/LICENSE).
The adapter regression checks its allowed properties and types, continuation,
and preservation of both the handoff and raw hook input.
