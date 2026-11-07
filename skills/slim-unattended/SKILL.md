---
name: slim-unattended
description: Slim files recorded over their size limit without the user, at most three per run, leaving each result on a branch with an ask that reports it. Use from a schedule or when asked to run the unattended slim. Needs the auto-apply setting; never merges. For one file with the user present, use slim-harness.
---

# Slim Unattended

Review recorded files without the user and leave each result on a branch. Use the same
procedure in Claude Code and Codex. Resolve the package root from this skill's actual
directory (`../..`); the shared command is `scripts/lib/slim.py`. It chooses what a run may
review, applies your edits in temporary clones of each repository's hosted default branch,
pushes one branch per repository and writes the asks. It never changes a checkout, opens a
pull request, merges or schedules. This step is separate from the sweep: never run a lesson
through it, and never add a lesson to a slim branch.

The user owns the schedule and whatever opens and merges a pull request. With the
auto-apply setting off, or the routing file's `lesson-policy: propose`, `plan` refuses, exit 1:
report that and stop. `slim_checkouts` in the configuration names each repository's checkout.

## Run

1. Take the records you were given. With none given, write this machine's:
   `python3 <package>/scripts/lib/checklist.py over-limit-records > <records-file>`.
2. Start the run, with one `--records` per file; records of one file count as one:
   `python3 <package>/scripts/lib/slim.py plan --records <records-file>`. Keep `run_id`.
   Report `skipped` (a slim awaiting its decision, or `over limit, slim rejected`), `deferred`,
   `unreachable` and `warnings`. Deliver each `undelivered_asks` row as in step 5.
3. Run `python3 <package>/scripts/lib/slim.py begin --run <run-id>`. With `done: false` it hands
   you one file: `file` (its text on the default branch), `workspaces`, `limits`, `duplicates`,
   `frozen` and `surfaces`. Slims go one after another; `begin` repeats the open one until it
   is finished. It stops at three files, largest overage first; the rest wait.
4. Review the whole file (below), write the result, then run
   `python3 <package>/scripts/lib/slim.py finish --run <run-id> --result <result-file>`, and
   go back to step 3. A refused result changes nothing and the slim stays open: correct it and
   send it again. Refused the same way: an `old` that no longer fits the file, a path that is a
   directory or reaches its file through a link, and an edit that leaves its file as it is. A
   push or clone that fails is not refused: the slim ends as `failed`. Every check and commit
   comes before the first push, so a refusal never follows a pushed branch; a push that errors
   after the remote took the branch counts as pushed. Remote commands wait 120 seconds (clones
   600); `HIPPOCAMPUS_SLIM_REMOTE_TIMEOUT` in the environment sets another number of seconds.
5. With `done: true`, hand each row of `asks` to the profile's ask binding, the same way the
   sweep does, whose profile this step shares. After a confirmed delivery run
   `python3 <package>/scripts/lib/slim.py ask-delivered --ask <id> --receipt <receipt>`. With nothing
   bound, an ask stays undelivered and the next `plan` lists it again. Report `results`,
   `waiting`, `skipped`, `deferred`, `unreachable` and `failed`. Write no handoff for this step.

## Review

Read `../slim-harness/SKILL.md` and follow its **Review in this order** sections in the same
order: Redundancy, Unneeded context, Conflicts, Extraction, Compression, with
`../slim-harness/references/removable-rules.md`. Read its limits from the running tool's
reference. Its questions change here, and only these:

- Read every file from `workspaces`, never from a checkout. For a comparison file in another
  repository run `python3 <package>/scripts/lib/slim.py workspace --run <run-id> --repository <owner/name>`.
  Build the comparison set from the record's `duplicates` and the file's direct references;
  there is nobody to ask about others, so report the coverage gap in `left`.
- Make every edit the review recommends without asking. A cross-file duplicate: choose the
  owner by the same recommendation the attended review would make, and remove the other copy.
  A contradiction: choose the winner, and edit the other side when the resolution needs it.
  Keep the attended limits on what may be cut: intent, goals, boundaries, exact commands.
- Never edit a file in `frozen`. Leave it as it is, list it in `deferred`, and plan around it.
  Give changes that only work together one `group`; a frozen file defers its whole group. A
  file with another change kept is still changed on the branch, not deferred.
- Never edit a generated surface. For each entry in `surfaces`, and each surface of another
  file you change, preview the content as the attended review does and measure it. Name each
  one you verified in `surfaces_verified`. When a preview is not safe or not possible, name
  it in `unverified` with the reason: no branch is built and an ordinary ask reports it. Run
  no regeneration command.
- Do your best when the file cannot reach its limit, and say what is left and why in `left`.

## Result

```json
{
  "contradictions": [{"rules": "<both rules, with their files>", "winner": "<rule kept>", "reason": "<why>",
                      "path": "<optional: the file its edit changes>"}],
  "duplicates": [{"rule": "<the rule, with both files>", "owner": "<owning file>", "reason": "<why>",
                  "path": "<optional: the file its edit changes>"}],
  "rules": [{"path": "<file>", "action": "removed", "text": "<the rule>", "reason": "<why>"}],
  "changes": [{"repository": "<owner/name>", "path": "<file>", "group": "<optional>",
               "edits": [{"old": "<exact text>", "new": "<replacement, may be empty>"}]}],
  "deferred": [{"repository": "<owner/name>", "path": "<file>", "reason": "<why>"}],
  "surfaces_verified": ["<surface path>"],
  "unverified": [{"surface": "<surface path>", "reason": "<why>"}],
  "left": "<what is left and why, when still over a limit>"
}
```

`rules` lists every rule removed or rewritten, with `action` `removed` or `rewritten`. Each
`old` must appear exactly once in the default branch's file; an edit with no `old` appends
`new`, which also creates a new subfile. `repository` defaults to the recorded file's. A
`path` is relative to its repository; `finish` reduces it to the file's one spelling (no `./`,
`..` or trailing `/`), and that spelling is what the frozen rule and the ask use. Name the file
a contradiction's or duplicate's edit changes in its `path`: when that file is deferred, the ask
lists the choice under "Chosen but not done" instead of as done, as it does a `rules` row.
`finish` measures the sizes itself, and it refuses a result that leaves the file over a limit
with no `left`.

## After the run

A branch awaits its decision until its pull request merges or closes. The user's automation
says which with `python3 <package>/scripts/lib/slim.py decide --repository <owner/name> --branch <branch> --decision merged`
(or `rejected`, for a pull request closed without merging). A branch deleted from its remote
is settled at the next `plan`: merged when its diff reverses cleanly on the default branch,
rejected only when its diff still applies there (the default branch never took the change),
and merged when neither holds, because its lines were edited after it. A remote that cannot
be read or hangs, or a git error, is a warning for that repository: the branch waits, and the
plan goes on for the others. A settled branch refuses a second decision. A rejected file waits until a session measures it larger than at rejection
or records a new duplicate rule naming it.

A plan closes a run that stopped early, so the asks of slims it already pushed are not lost;
a slim left open starts over. A slim whose helper stopped while pushing is settled from its
remotes first: each branch found there is recorded, awaiting its decision, and gets its ask;
one not found is a failure. Until that plan runs, `begin`, `workspace` and `finish` refuse.

A recorded file left alone because a branch from an earlier run already changed it is
`deferred` in `plan`, and gets one ask, once per branch, saying it is left as it is and why.
A recorded file whose duplicate rule lives in a repository `slim_checkouts` does not name is
`unreachable`, with the reason: it waits until that repository is named.

A file that produces no branch in two runs in a row (failed, unverified or nothing to change)
is stalled. Its ask says so, and later runs report it as `over limit, slim stalled` and skip it,
so it stops taking a slot. It returns when a session measures it larger or records a new
duplicate, or when the user fixes the cause and runs
`python3 <package>/scripts/lib/slim.py retry --repository <owner/name> --path <file>`.
