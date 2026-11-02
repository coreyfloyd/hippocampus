# Section usage evidence

Run `python3 <skill-dir>/scripts/harness.py usage <manifest.json>` to emit a JSON
report. This is deterministic lexical evidence, not a judgment that an instruction
was followed. It executes no transcript commands and edits no source files.

The manifest supplies explicit transcripts and skill snapshots; it does not scan
session directories or a skill catalog. Paths resolve from the invocation directory.
For each session, `tool` is `claude` or `codex`, `transcript` names a JSONL file,
and `skills` lists objects with `path` and optional `recorded_path`. The latter is
the literal path in the recorded read when it differs from the snapshot's location:

```json
{
  "sessions": [
    {
      "tool": "claude",
      "transcript": "/captures/session.jsonl",
      "skills": [
        {"path": "/snapshots/workflow/SKILL.md", "recorded_path": "/skills/workflow/SKILL.md"}
      ]
    }
  ]
}
```

Supply the version of the skill that session actually read. Current installed
files are appropriate only if their content has not changed since the session.
The report does not reconstruct historical bodies from transcript outputs.

Claude assistant `tool_use` / user `tool_result` records and Codex `response_item`
function/custom tool calls and corresponding outputs are supported. Returned
full `Read` calls and literal shell `cat` operands establish loading unless
structured result metadata reports failure, truncation, or an unfinished status. Codex
shell calls may be direct JSON arguments or literal JSON-quoted `cmd` fields in
an exec JavaScript wrapper. Partial reads, dynamic shell/JavaScript expressions,
implicit injection, and native Skill invocations are outside this loading detector;
absence from the report is a coverage limitation, not evidence of no load.
Keep `recorded_path` exactly as spelled in the tool input, including a literal tilde.
Malformed JSON fails with the source file and line number rather than silently
omitting records. A read without a returned result does not establish loading.
Failure detection reads only result fields: `is_error` / `isError` signal failure,
`truncated` signals incomplete output, nonzero `exit_code` signals a failed command,
and `status` can signal failed or unfinished execution. These fields are read on
the result envelope and an object-valued Codex `output`, never from file content
or nested command-output text. Text-only wrappers without structured status cannot
establish failure or truncation; returned reads then count as loaded. Instruction
examples of failures or truncation remain ordinary content.

The body is partitioned at ATX headings outside fences. Each row identifies its
skill `path`, `section`, `body_start_line` (relative to the frontmatter-free body),
`size` in lines/words/UTF-8 bytes, `sessions_loaded`, and
`sessions_with_evidence`. Header-only sections and preambles retain their size.
`markers` are literal flags, paths containing a slash, backticked command strings
and commands from shell fences; dotted version prose alone is not a path.
`matched_markers` makes the evidence inspectable. Matching requires
token boundaries and searches only subsequent tool inputs after the read returns.
Read commands for that skill are excluded. Tool outputs, narrative, and thinking
are never evidence. A match proves that text appeared in a tool call, not that a
rule caused the call or that the command succeeded.

`status` is `evidence of use` or `no evidence of use`; prose-only rules retain the
latter label. Never reinterpret it as proof that an instruction is unnecessary.
Repeated reads and repeated exports sharing a recorded session identity count
once per skill. Without a session identity, the resolved transcript path is the
fallback; do not supply duplicate exports under different paths in that case.
`unresolved` lists missing snapshots for recognized loads.

`split_candidates` contains only sections with lexical markers, loaded in at least
3 distinct sessions, with evidence in fewer sessions than loaded. These are
situational extraction candidates for human review, not authorization to split.
Prose-only sections never produce a split suggestion. This heuristic measures
observed coverage, not frequency or importance of safety instructions.
