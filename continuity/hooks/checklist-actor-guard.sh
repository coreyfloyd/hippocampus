#!/usr/bin/env bash
# PreToolUse(Bash), Claude Code and Codex: deny a subagent or factory session
# running the checklist or writing a handoff. A subagent shows only in the hook
# payload (`agent_id`), never in the environment its commands inherit, so the
# checklist module cannot refuse it alone. Fails open: a broken guard must not
# block every Bash call.
set -uo pipefail
python3 "$(dirname "$0")/../scripts/lib/checklist.py" actor-guard 2>/dev/null
exit 0
