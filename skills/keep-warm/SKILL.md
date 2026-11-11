---
name: keep-warm
description: Explicitly turn keep-warm on or off for this interactive session. Enable only while waiting on a specific result or reply that will message this session, expected within about two hours.
---

# Keep-warm

Run only when the user explicitly requests `keep-warm on` or `keep-warm off`.
Claude Code uses `/hippocampus:keep-warm on` or `/hippocampus:keep-warm off`.
Codex uses `$keep-warm on` or `$keep-warm off`.
If no mode was supplied, ask which mode; do not enable by inference.

Enable only when both apply:

- Waiting on a specific result or reply that will message this session.
- That result or reply is expected within about two hours.

Resolve this skill's real installed directory. `<engine>` is
`../../scripts/lib/handoff.py` relative to that directory, inside the package.
Pass the calling session's id explicitly; never an inherited parent id.

```bash
python3 <engine> keep-warm on --session-id <session>
python3 <engine> keep-warm off --session-id <session>
```

Execute the selected command and follow its JSON instructions. Codex starts or
cancels its shared timer directly, including desktop sessions. Claude Code must
execute native CronCreate/CronDelete instructions returned by the command.
Use the exact printed prompt and pinned minute, `recurring: false`, session-only.
After CronCreate succeeds, execute the printed `keep-warm-job` registration.
If registration rejects a stale activation, execute its CronDelete instruction.
Do not report a native job cancelled until CronDelete succeeds. Then acknowledge
that exact id (an older acknowledgement cannot remove a newer job record):

```bash
python3 <engine> keep-warm-job-deleted --session-id <session> --job-id <deleted-job-id>
```

Keep-warm starts off. Repeated `on` while enabled leaves the original activation
unchanged. There are at most two wakes, about 55 and 110 minutes from activation,
then off; with about one hour of cache lifetime after the last activity, cached
life is at most three hours. Checkpoints, ordinary activity, compaction, restore,
and timer turns never renew the deadline or the wake budget.

At a wake, run its exact `keep-warm-wake` command. Only `checkpoint: true`
authorizes checkpointing real work. With no new incoming work, it turns off;
write no handoff and do no maintenance, including percentage or stale-handoff
preservation. Unknown activity or invalid/expired state turns off safely.
Never enable keep-warm from a wake, even a productive one.

For pending timers from an older installation, use the supported cancellation
command with the producing session's id. It handles orphan and malformed Codex
pending records under the scheduling lock and retains a receipt. It also returns
native Claude cancellation instructions; deleting a local job-id file is not
cancellation. If no usable job id remains, use native CronList and CronDelete the
session's keep-warm or timed checkpoint jobs. After successful native deletion,
acknowledge the exact orphan snapshot using `keep-warm-job-deleted --session-id
<session> --record <native_record>` (the hash returned by cancellation). This
cannot remove a replacement record. Report the native outcome.

```bash
python3 <engine> timer-cancel --session-id <session>
```
