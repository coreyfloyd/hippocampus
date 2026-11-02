# Artifact example provenance

Captured on 2026-10-14 with the package engines at base `73d7497`.
`handoff.json`, `ledger.jsonl`, and `plan.json` are command outputs from one
temporary sandbox session, not hand-authored examples. Only path redaction was
applied. Timestamps, commit hashes, field names, values, ordering, and formatting
otherwise remain those emitted by the engines.

`profile.md` and `config.json` are **validated inputs**, not captured outputs:
the package reads these files and has no command that generates them. The profile
is an unchanged copy of `tests/fixtures/profiles/user.md`. The configuration is
the existing `{"handoff_dir": "~/state/session-handoffs"}` literal from
`test_configured_handoff_dir_places_handoffs_and_ledger` in `tests/test_handoff.py`,
serialized with two-space indentation and a trailing newline. Its shape and key
are defined by `INTERFACE.md` section 2. No private configuration was copied.

## Sandbox and exact capture commands

The capture driver used Python's `tempfile.mkdtemp` with prefix
`continuity-examples-`, then created `repo` inside it. In the commands below,
`PACKAGE` is the package checkout, `SANDBOX` that temporary directory, `REPO` its
`repo` directory, and `EXAMPLES` the checkout's `docs/examples` directory. These
variables replace machine-local arguments; command argument order is the order
actually used. The driver executed commands with `subprocess.run`, captured
stdout, and required exit status zero.

The driver removed inherited `CODEX_THREAD_ID`, `CLAUDE_SESSION_ID`,
`CLAUDE_CODE_SESSION_ID`, `CLAUDE_CODE_ENTRYPOINT`, `CONTINUITY_HARNESS`, and
`HANDOFF_FILE` from the sandbox environment. It set:

```bash
export HANDOFF_STATE_DIR="$SANDBOX/handoffs"
export HANDOFF_LEDGER_DIR="$SANDBOX/ledger"
export CHECKLIST_STATE_DIR="$SANDBOX/checklist"
export CONTINUITY_CONFIG="$EXAMPLES/config.json"
```

The sandbox repository was initialized with these commands. Before `git add`,
its `README.md` contained `Artifact capture sandbox.` followed by a newline.
After the commit, the driver appended `Capture in progress.` and a newline,
so the captured file entry refers to an actual uncommitted edit.

```bash
git init -q "$REPO"
git -C "$REPO" symbolic-ref HEAD refs/heads/main
git -C "$REPO" add README.md
git -C "$REPO" -c user.name=Example -c user.email=example@example.invalid \
  -c commit.gpgsign=false commit -qm 'Initialize capture sandbox'
```

Ledger file and artifact rows were captured with:

```bash
python3 "$PACKAGE/scripts/lib/handoff.py" ledger-file README.md \
  --cwd "$REPO" --session-id example-session
python3 "$PACKAGE/scripts/lib/handoff.py" ledger-artifact \
  --location https://example.invalid/review --disposition keep \
  --cwd "$REPO" --session-id example-session
```

The handoff command received this continuation input, describing that sandbox's
actual state. Its pending artifact and uncommitted file were supplied by the
ledger, rather than authored into the example:

```bash
python3 "$PACKAGE/scripts/lib/handoff.py" checkpoint \
  --cwd "$REPO" --session-id example-session <<'JSON'
{"resume": {"headline": "Artifact examples captured; validation remains.", "next_action": "Validate the examples against their engines.", "session_summary": "Registered the changed sandbox file and a pending review artifact.", "open_loops": []}, "spawned_processes": [], "suggested_skills": ["checklist"]}
JSON
```

The driver located the written file with `resolve`, then passed that path as
`HANDOFF` to `plan`. Plan stdout became `plan.json`; the plan command also
appended the start marker, completing the ledger example.

```bash
python3 "$PACKAGE/scripts/lib/handoff.py" resolve "$REPO" --session-id example-session
python3 "$PACKAGE/scripts/lib/checklist.py" plan \
  --user-profile "$EXAMPLES/profile.md" --handoff "$HANDOFF" \
  --session-id example-session
```

The driver copied the written handoff JSON, the ledger file
`$HANDOFF_LEDGER_DIR/session-touched-paths.example-session.jsonl`, and plan stdout.
The raw UTF-8 output SHA-256 values, before path replacement, were:

| Output | SHA-256 |
|---|---|
| Handoff | `56bcdddaa797a804558eee461514c3057a3e6dc92b66e90ab4bae91e437bc2bd` |
| Ledger | `c412fd1cef8bd8a9441564649a4e501b8b47efc64d687004a114408954dd41f7` |
| Plan | `e85582274619dec7e3bdb5630a5fc443473cb85ed61b7831a334e1ea60ed13ee` |

## Redaction and validation

Following the pickup fixtures' neutral-stand-in practice, the driver replaced
the canonical sandbox repository path with `/workspace/example-repo` wherever
it appeared, and the absolute profile path with `docs/examples/profile.md`.
It changed no other output text. Session identity was the sandbox's explicit
`example-session`; the artifact URL was `https://example.invalid/review` from
the start. The sandbox contains no personal names, machines, private repositories,
projects, home paths, or channels.

The configuration was checked with the engine command:

```bash
python3 "$PACKAGE/scripts/lib/handoff.py" config-get handoff_dir
```

With `CONTINUITY_CONFIG` set as above it returned `~/state/session-handoffs`.
The profile was validated through the engine's `load_profile` and `compose`
functions, and consumed by the real `plan` command. The documentation tests
repeat these validations, lint the redacted handoff, regenerate the checkpoint
from the capture input, and compare the complete handoff and ledger rows with
fresh command output. They normalize capture-specific paths, timestamps, and
git commit identity while retaining semantic values and field presence. They
also recompose the complete plan from the profile and handoff; only the plan's
machine-local profile path is normalized for that comparison.

No report-input or session-summary example is included: the interactive session
and bound record produce those inputs, rather than the package.

## Contract notes

The outlines follow the engines where wording elsewhere is narrower or broader:

- `INTERFACE.md` section 2 describes `config-get` as printing one value, while
  listing object-valued `cycle_sessions` and `unattended` settings. The command
  handles strings, lists of strings, and positive integer `prune_days`; an object
  goes through `config_string` and is refused. The example uses a string setting.
- The glossary's Profile entry describes configuration as one value naming
  handoff storage. The current section 2 table and engine support more settings;
  the configuration outline follows that table while retaining the glossary's
  distinction between configuration and a profile.
- The checklist skill's plan instructions say an omitted session ID defaults
  to the Claude Code session and should be passed explicitly in Codex. The
  engine actually uses `ambient_session_id`, prioritizing `CODEX_THREAD_ID`
  before either Claude session variable. Capture passes an explicit sandbox ID.

Checkpoint stores unrecorded input `session_items` as `resume.open_loops`, adds
`resume.session_history`, and removes the top-level input array. The outline
distinguishes input from stored output. The tool hook's repository observations
have no `kind` field; they are documented separately from the three explicit
command-generated entry kinds in the example.

## Plan refresh, 2026-10-18

Re-ran the plan command against the committed `profile.md` and `handoff.json`,
using `docs/examples/profile.md` as the profile argument and a temporary ledger
directory, with the inherited session variables listed above removed. Saved
stdout unchanged as `plan.json` (SHA-256 `8eecf3c4a43b6104651a5da25f9b9d6549fe11ff122bdf9aa2deca0e12a6f66b`).
The refreshed plan adds `record_read: null`, reflecting the profile's unbound
read skill. The original handoff and ledger captures above remain unchanged.
