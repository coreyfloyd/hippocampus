---
name: pickup
description: "Resume work after a cold start: lists durable handoff candidates with transcript fallback. Use for 'where was I?' or 'pick up where I left off'; not within-session status."
disable-model-invocation: true
---

# Pickup

Answers *"where was I?"* from a cold start — no surviving context, no memory of what the last session held. It is handoff-first, with transcript fallback.

`<pickup.sh>` is this package's `scripts/pickup.sh` (resolve the path from this skill's real directory: `../../scripts/pickup.sh`).

## Handoff candidates (default)

*"What could I resume on this machine?"*

With no arguments, it reads schema-v2 handoff files from the configured handoff directory (`handoff_dir` in `~/.config/continuity/config.json`; default `~/.local/state/continuity/handoffs/`; `HANDOFF_STATE_DIR` overrides both) and returns candidates in this order: this directory, sibling worktrees whose handoff records the same repository root, then elsewhere on this machine. There is one file per session, named with a readable cwd, cwd hash, and full session id; multiple sessions in one directory are returned individually, newest first. Each candidate carries `session_id`, `headline`, `next_action`, `branch`, and `age`; discovery is file-based, with no index or cross-host sync. A v2 writer records `git.repository_root` as the parent of `git rev-parse --git-common-dir` (the main checkout), never `git rev-parse --show-toplevel`, which is a linked worktree directory.

### Dead-session pruning

The default JSON report includes `prune_candidates` but never changes files. A handoff is a prune candidate when the matching transcript is missing, or when that transcript's mtime is at least 7 days old. Override the threshold with the positive integer `PICKUP_PRUNE_DAYS`. Transcript identity is derived mechanically from the stored handoff subject using Claude Code's cwd slug (`/` and `.` replaced by `-`): `~/.claude/projects/<cwd-slug>/<session_id>.jsonl`.

Each candidate carries `path`, `session_id`, `reason` (`missing_transcript` or `stale_transcript`), and `age`. To act on the suggestion:

```bash
bash <pickup.sh> --prune
```

`--prune` moves candidates into the handoff directory's `archive/` and reports every move in JSON. It never deletes a handoff, and a same-named archive file is preserved by choosing a numbered destination.

Render these groups for the user and let them choose; do not make another candidate the current task. To select a returned candidate, use its `path`:

```bash
bash <pickup.sh> --handoff <path>
```

The selected handoff produces a version-2 briefing from its pointers, open loops, carried commitments, and uncommitted files. Handoff text is inferred; git checks carry their own provenance. Follow the record-read procedure below before rendering. An unbound user profile adds exactly one line: **No record read is bound.**

## Transcript fallback

When no handoff candidate is available, the default path reads the on-disk transcript of the most recent OTHER session for this directory, from either provider: Claude transcripts in `~/.claude/projects/<cwd-slug>/`, and root Codex threads whose `session_meta` records this directory under `$CODEX_HOME/sessions/` or `$CODEX_HOME/archived_sessions/` (`CODEX_HOME` defaults to `~/.codex`). The invoking Claude session and the invoking Codex thread (`CODEX_THREAD_ID`) are excluded. Codex subagent threads are not listed. Its normal report carries `source: "transcript_fallback"` and a notice; the existing no-transcript-directory and no-other-session error shapes remain unchanged. An absent store (a provider never used on this machine) is skipped. A Codex `sessions`, dated, or `archived_sessions` directory, or this directory's Claude project directory, that exists but cannot be listed returns `error: "session_store_unavailable"` naming that directory, with a non-zero exit and no session chosen: a session there may be newer. Other Claude project directories are not read by this path.

**Symbolic links.** A configured store root may resolve through a link: `HOME`, `~/.claude`, `~/.claude/projects`, and `CODEX_HOME` are used as given, so a relocated root works. Below that root, a link is rejected wherever the lookup would descend into it or read it as a transcript: Codex `sessions`, `archived_sessions`, any directory in the `sessions` tree, and any rollout file; a Claude project directory the lookup reads (this directory's project on the automatic path, every project under `~/.claude/projects` for `--session`), and any `<id>.jsonl` it reads. That returns `session_store_unavailable` naming the link, with a non-zero exit and no session chosen, on both the automatic path and `--session`. Following the link could read a session outside the store, and skipping it could drop a window of a thread or a second owner of an id. An entry the lookup neither descends into nor reads is not examined, so a linked `memory/` inside a Claude project, a link to a plain file directly under `~/.claude/projects`, or a link to a non-rollout file in the Codex tree, is ignored.

**It always prints a single JSON object — there is no human-rendered mode** (the script emits JSON, the agent renders the briefing, the user never sees raw output). `--json` is accepted for backward compatibility but has no effect — JSON is already the only output.

```bash
bash <pickup.sh> --session <id>
```

| Flag | Effect |
|---|---|
| *(none)* | Handoff candidates; transcript miner only when none are available |
| `--handoff <path>` | Selected handoff briefing with git cross-checks |
| `--session <id>` | A specific session from either provider, found wherever it ran (no skip) — see [Cross-tool reconstruction](#cross-tool-reconstruction) |

When neither provider has a session recorded for this cwd, or the only session here is the current one, the output is still a JSON object — `{"version": 2, "error": "no_transcript_directory" | "no_other_session", "message": "..."}`.

### How it picks the session

Newest first across both providers (by file mtime; equal mtimes break by lowest session id, then provider name, never by file listing order), excluding the current session, **skipping any transcript that is malformed or has no substantive assistant turn** — a lone candidate included. A transcript is malformed when any of its files cannot be read, or any non-empty record in any of its files does not decode as a JSON object, the final record included; it is skipped whole, never reconstructed with that record missing. A Codex thread's files are every rollout whose filename carries its id, so a paginated window file that is unreadable, undecodable, or names another thread in its `session_meta` fails the whole thread rather than being left out. When every candidate is skipped, the result is `error: "no_substantive_transcript"` with a non-zero exit and a message naming each skipped file and why. A session that opened and never ran leaves an empty transcript and is not a resume target. If the default lands on the wrong session, pass `--session <id>`.

**A bare `/pickup <arg>` argument is a session id, not a flag.** Map it to `--session <arg>` before running the script.

Automatic scoping is by directory, so it naturally separates worktrees — each has its own session set. A worktree with no prior session of its own returns the `no_transcript_directory` error above; that is expected, not a bug. If a store directory this path reads exists but cannot be listed, or is a rejected link (see Symbolic links above), it returns `session_store_unavailable` instead, because an absent session cannot be proven.

### Cross-tool reconstruction

`--session <id>` reconstructs context from a session recorded by **either** Claude Code or Codex, whichever tool runs `/pickup`, and from any directory. The engine searches both stores for the id and decides the owner from what it finds there — never from the id's UUID version or from `CLAUDE_*`/`CODEX_*` variables:

- **Claude:** `~/.claude/projects/*/<id>.jsonl`, in any project directory.
- **Codex:** rollout files named `rollout-<timestamp>-<id>[_<window>].jsonl` under `$CODEX_HOME/sessions/YYYY/MM/DD/` and the flat `$CODEX_HOME/archived_sessions/`. The id is the thread id (`session_meta.payload.id`), never `payload.session_id`, which names the parent thread for a subagent. A thread split across several files (a paginated window) is read as one source, oldest file first.

The report is the same version-2 object for both providers, plus `provider` (`"claude"` or `"codex"`) and `transcript_files` (the file or files read, in order). Codex records are mapped to the same fields: user turns from `UserMessage` items, the `final_answer` message as the sign-off, each command as a `Bash` call with its output, and each file change as an edited path. The branch comes from the rollout's `session_meta.git`, since Codex records no per-turn branch.

An explicit id never falls back to a guess. Each failure is a JSON error object with a non-zero exit:

| `error` | Meaning |
|---|---|
| `no_such_session` | Both stores exist, every directory in them could be searched without meeting a rejected link, and neither holds the id. The message lists every root searched. |
| `session_store_unavailable` | Either (a) the id was not found and a provider's store is absent (no `~/.claude/projects`, or no `sessions`/`archived_sessions` under `CODEX_HOME`): point `HOME`/`CODEX_HOME` at the store that holds it. Or (b) a store directory exists but cannot be searched: `~/.claude/projects`, any project directory under it, or any Codex `sessions`, dated, or `archived_sessions` directory. Or (c) the lookup met a rejected link (see [Symbolic links](#transcript-fallback)): a linked project directory or `<id>.jsonl`, or a linked Codex store directory or rollout file. Cases (b) and (c) fail even when a valid match was found elsewhere, since the unsearchable directory or the link may hold another member of the thread or a second owner of the id. The message names the directory or link and never carries transcript content. One unsearchable or linked Claude project directory blocks every explicit lookup on the machine until its permissions are fixed or the link is replaced by a real directory. A project directory counts as searchable when the exact `<id>.jsonl` name can be checked in it. |
| `ambiguous_session` | The id is a valid transcript in more than one place (both providers, or two Claude project directories). The message names each file. |
| `invalid_session_transcript` | A file matched the id but cannot be read as a transcript of its provider, including when it cannot be read or any non-empty record in it, the final one included, does not decode as a JSON object. This fails even when another match is valid. |
| `invalid_session_id` | The id contains path or glob syntax. |

**This is reconstruction, not native continuation.** `/pickup` rebuilds what a dead session did so the current tool can carry on; it works across providers. Continuing the provider's own conversation thread — `claude --resume <id>` or `codex resume <id>` — reads only that provider's store and remains a same-provider capability.

### Rendering the resume briefing (`version: 2`)

The JSON is a deterministic worklog that YOU, the agent, turn into the user's actual briefing. **Rendering it is your job, not the script's.** **Every open ask the dead session left is re-rendered in full** — context, options with tradeoffs, recommendation — never as the prior session's `R3`/`O2` codes: the user has no memory of those labels, and a briefing that says "R6: release, manual, or arm" cannot be answered (2026-09-05).

Top-level transcript fields: `session`, `provider`, `transcript_files`, `messages`, `first_ts`, `last_ts`, `first_user`, `last_user`, `last_assistant` (the last sign-off), `git`, `branches`, `files_by_repo`, `staleness`, `skipped_candidates`, `session_repo_cwd`, and `session_repo_readable`.

**Exit code and error shape.** The engine is one Python process. Every failure emits `{"version": 2, "error": ..., "message": ...}`.

**Branch on the `error` key, not on the exit code**, because the two do not line up and are not meant to:

| Situation | `error` | Exit |
|---|---|---|
| Normal report | absent | 0 |
| `no_transcript_directory`, `no_other_session` (automatic path) | present | **0** |
| An explicit `--session` that did not resolve (see [Cross-tool reconstruction](#cross-tool-reconstruction)) | present | non-zero |
| `session_store_unavailable` on the automatic path (a store directory exists but cannot be listed, or a rejected link) | present | non-zero |
| Engine crashed, printed non-JSON, or exited non-zero | present | non-zero |

"Nothing here to resume" is an answer, not a failure — a worktree with no prior session of its own returns `no_transcript_directory` and exits 0 by design. A non-zero exit means the lens could not produce a trustworthy answer: it broke, a selected transcript was malformed, or a store directory could not be listed or was a rejected link.

**`session_repo_readable: false`** means the session's last recorded cwd no longer exists on disk — every branch in `branches` will read `deleted_no_merge` (the highest alarm) and `files_by_repo` will be empty, not because that is what happened, but because git itself could not be read from there. Check this field before treating an all-red report as a resolved finding.

| Key | What it is |
|---|---|
| `branches[]` | Every branch/worktree the session touched. Each entry: `branch`, `worktree_path`, `worktree_exists`, `dirty`, `ref` (`local`/`remote`/`none`), `on_main`, `merge_evidence` (the `%h %s` line of the merge commit, when one was found by name), `state`, `alarm_rank`, `commits`, `commits_source`. `state` is one of `dirty`, `clean_unmerged`, `gone_unmerged`, `merged`, `landed`, `deleted_no_merge`, or **`unknown`** — `unknown` means git itself could not be read for that worktree (a real error, not "nothing to report"). `alarm_rank` is the machine-readable severity order (**lower = more urgent**: `unknown`/`dirty` = 0, `deleted_no_merge` = 1, `clean_unmerged`/`gone_unmerged` = 2, `merged`/`landed` = 3) — sort `branches[]` by it rather than re-deriving an ordering from this prose. |
| `branches[].commits_source` | Why `commits` is what it is: `"direct"` (the `main..branch` range, authoritative — an empty list here for an unmerged branch is a TRUE empty), `"merge_evidence"` (the branch is merged/gone and its own merge commit was found by name), `"not_applicable"` (ref is gone with no merge found — this already IS the `deleted_no_merge` alarm), or **`"unresolved"`** (the branch is merged, its ref still exists, but no merge commit could be found by name — its `state` is correctly `"merged"`, but what it CONTAINED is genuinely unknown, not confirmed empty). Never render an `"unresolved"` branch's empty `commits` as "no changes." |
| `files_by_repo` | Per repo (keyed by repo root, not per-worktree path): `committed`, `uncommitted`, `transcript_scraped` (three separate lists — a path can appear in more than one), and `unresolved_branches` (branch names in this repo whose `commits_source` is `"unresolved"` — their real files are absent from `committed` above, not confirmed empty; cross-reference before treating the file list as complete). Uncommitted alone misses a merged-but-still-open branch's contribution; committed alone misses live uncommitted edits (a real session had 5 uncommitted changes in a notes repository that `git log` reported as zero); transcript-scraped catches bypass-mode edits routed through `Bash` (heredocs, `sed`, `python3 -c`) that never went through `Write`/`Edit` at all. |
| `staleness` | `last_end_turn_ts` (the last message actually sent to the user) plus `tool_calls_after` — nonzero means the session kept working (or crashed mid-tool-call) past its last sign-off, and `last_assistant` above is stale by exactly that gap. |

**Render the user's briefing from the selected handoff or transcript JSON.** Use the handoff's record pointers, headline, session summary, next action, and every carried open loop, including commitments. Keep the producing session, time, disposition, and decision ownership attached to carried items. A pointer locates the record; it does not validate the record's current state.

Use these sections when applicable:

- **Last session** — what the session set out to do and the work the handoff or transcript describes.
- **Landed** — changes supported by local git evidence.
- **Outstanding** — open loops, carried commitments, uncommitted files, and unresolved branches.
- **Start here** — the handoff's next action, or an action supported by the transcript.

For a selected handoff, follow the record-read procedure below. Without a binding, include exactly one line stating **No record read is bound.** Preserve available pointers so the user can return to the record. Transcript fallback does not detect ticket references or request record reads; render it from transcript and git evidence alone. Define identifiers by their purpose on first mention. Re-render every open decision in full: context, options with tradeoffs, and recommendation; do not reuse unexplained option codes.

Tag each substantive line `(validated: <method>)` or `(inferred: <basis>)`. Git checks are current evidence; handoff and transcript text remain inferred. Re-check a test or file before acting on an old failure report. If `staleness.tool_calls_after` is nonzero, the last sign-off predates subsequent work. If `session_repo_readable` is false, local branch and file checks could not establish the work's state.

A pre-written dispatch is also stale: re-verify its premises before running it. Pickup reconstructs context; it does not grant authority for additional work.

The branch cross-check uses the resumed session's last recorded `gitBranch`, rather than the current checkout's branch. Comparisons resolve the trunk from `PICKUP_TRUNK`, then `git symbolic-ref refs/remotes/origin/HEAD`, then `main`.

Subagent work may be absent from the parent's transcript. Git checks can recover committed changes, but the briefing must not imply completeness when the session mentions dispatched work.

### Read the record through the user binding

This procedure is shared by Claude Code and Codex. Save the selected handoff's
JSON report from `<pickup.sh>` as `<pickup-report>`. Pass `--no-commitments` to
that command when the user requests it; the report omits that request and says
**Commitments from record: skipped (--no-commitments)**. Commitments carried in
the handoff still appear, labeled **from handoff**, with their original identities.
Listing candidates never runs a record read.

If the selected report has `error: "record_helper_failed"`, the package helper
could not run or return a JSON object. Render its `message` (helper path and
actual cause) and every preserved handoff-derived section. Do not call the
binding or describe this installation failure as an unavailable record. The
wrapper finds the helper independently of `PICKUP_ENGINE`, which selects the
engine path; adapters may set `PICKUP_RECORD_HELPER` to select the helper path.
A standalone engine copied outside the package needs that helper override.

The selected report resolves the user profile at `$CHECKLIST_USER_PROFILE`, or
`checklist/profile.md` under `$XDG_CONFIG_HOME` (default `~/.config`). Only an
absent default profile means configured-nothing. A default profile link whose
target is unavailable reports the same path-naming diagnostic as an explicitly
configured path. An unreadable profile is **record read unavailable: <reason>**.
A profile that fails checklist validation, including outside `record_read`,
reports **record read unavailable: user profile: <path>: invalid profile: <reason>**.
A valid profile without `record_read` reports **No record read is bound.** Repository
profiles cannot bind this read. This path reads profiles without starting a
checklist or writing a ledger marker.

When the report has `record_read`, its `command` names the user's skill and
`requests` holds the JSON inputs to run it with. **You, the agent, run that skill**;
the script never executes its name as a shell command. Read the bound skill and
run it once for each prepared request, respecting its read-only contract:

- `ticket_status` asks for the distinct ticket references in handoff open-loop
  `anchor.ticket` pointers. Keep the reference strings intact. Each requested
  reference must return one row, including an explicit `not_found` row for an
  unresolved reference.
- `commitments` passes the **resumed session's** id, its repository, and its
  complete handoff, as prepared. Never substitute the successor's session id or
  current directory. The binding decides which work belongs to that session.
  When this request is absent because of `--no-commitments`, do not run it.

Keep each raw JSON response in a separate file. `<pickup-record>` is this
package's `scripts/lib/pickup_record.py` (resolve from this skill's real
directory: `../../scripts/lib/pickup_record.py`). Finish the report with:

```bash
python3 <pickup-record> --complete \
  --ticket-status <ticket-response> --commitments <commitments-response> \
  < <pickup-report>
```

Omit `--commitments` when skipped. If a skill cannot run, errors, or returns no
output, omit that response argument and keep `--complete`: the missing response
is reported as unavailable. For a known execution error, use the contract's
`{"kind":"error","reason":"<actual error>"}` response. Never replace a failed
response with successful empty rows. Keep malformed or schema-invalid output
intact for validation; do not repair it into plausible results.

The helper passes each raw response through `record_read.py`'s validator with
its expected kind, then checks ticket reference coverage. It appends rows only
for passing responses. See [the contract](../../INTERFACE.md#9-record-read-scriptslibrecord_readpy)
for the exact schema and validator verdicts. Each request is independent: a
successful read may be shown when the other fails.

Render the completed report's handoff sections and appended record lines:
for every ticket, show **reference, title, state, link, and latest progress**;
keep explicit `not_found` rows visible and say when latest progress is empty.
Label carried commitments **from handoff** and returned commitments **from
record**; show each returned reference, title, state, and link. A validated empty
response may say none. For each failed request, show **record read unavailable:
<reason>** in place of its rows, while preserving every handoff-derived section.
Pending requests are unfinished reads, never empty results; complete them or
report why unavailable before delivering the briefing. Validation establishes
response shape and requested-reference coverage, not independent record accuracy;
attribute the state to the binding and do not invent additional current state.

This read makes no record writes and instructs no re-claim. List carried items;
any transfer belongs to the user's own tools.

### The successor rule

The session running pickup is the **successor**; the session whose handoff it selected is the **resumed session**. Keep carried items' original session identity. Session-bound contracts such as pending approvals, pending replies, granted scopes, and any other record keyed by session id may also need transfer. Pickup makes no record writes; any transfer of session-bound contracts is left to the user's own tools. Listing candidates does not select a session.

## Distinct from `/wip`

`/wip` reports within-session work using surviving context. Pickup reconstructs a previous session from durable handoffs or local transcripts, across Claude Code and Codex.
