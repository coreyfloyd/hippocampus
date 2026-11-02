#!/usr/bin/env bash
# PostToolUse(Bash): after a real task-completion signal — a git commit/push, or
# a passing test run — nudge to run the end-of-task checklist.
#
# There is ONE checklist command (#791). This hook used to route by repo to
# separate per-repo checklist skills that pointed at different steps. /checklist
# now resolves its own profiles from the surfaces the session touched, so the
# hook names it unconditionally and carries no repo map to drift.
# The checklist items most often skipped under pressure are CLAUDE.md /
# MEMORY.md / plans / skills updates (failure mode logged W11+, #141).
#
# Advisory only (exit 0, additionalContext). Throttled to once per session via a
# tmp flag, so a series of commits/pushes/test runs doesn't nag repeatedly.
#
# Success detection for tests: Bash tool_response carries stdout/stderr but NO
# exit code, so a passing run is inferred from definitive per-framework pass
# markers AND the absence of failure markers — never fire on a failing run
# (that's mid-debugging, not completion).

# Advisory hook: fail open. No `set -e` — a jq hiccup on odd input must never
# make this exit non-zero (a non-zero PostToolUse hook can surface as an error).
set -uo pipefail

input=$(cat)

# Optional scope: when the user's checklist configuration has a `nudge-roots`
# file (one directory per line, `~/` allowed, `#` comments), nudge only for a cwd
# under one of them. With no file, every interactive session can be nudged.
config_dir="${CHECKLIST_CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/checklist}"
roots_file="$config_dir/nudge-roots"
cwd=$(printf '%s' "$input" | jq -r '.cwd // empty' 2>/dev/null)
if [ -n "$cwd" ] && [ -f "$roots_file" ]; then
    in_scope=""
    while IFS= read -r root || [ -n "$root" ]; do
        root="${root%%#*}"
        root="$(printf '%s' "$root" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
        [ -z "$root" ] && continue
        case "$root" in "~/"*) root="$HOME/${root#\~/}" ;; esac
        root="${root%/}"
        case "$cwd" in
            "$root"|"$root"/*) in_scope=1; break ;;
        esac
    done < "$roots_file"
    [ -z "$in_scope" ] && exit 0
fi

cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // empty' 2>/dev/null)
[ -z "$cmd" ] && exit 0

signal=""   # set to the human label of the detected completion signal

# --- Signal 1: git commit / push -------------------------------------------
# Allow leading flags (`git -C path commit`). Substring false-positives are
# harmless. Excludes things like `git log --grep=commit`.
if echo "$cmd" | grep -Eq '(^|[^[:alnum:]_])git( +-[^ ]+ +[^ ]+)* +(commit|push)([^[:alnum:]_]|$)'; then
    signal="git $(echo "$cmd" | grep -oE '(commit|push)' | head -1)"

# --- Signal 2: a PASSING test run ------------------------------------------
elif echo "$cmd" | grep -Eq '(pytest|python[0-9.]* +-m +pytest|swift +test|xcodebuild +.*test|-only-testing|npm +(run +)?test|yarn +test|pnpm +test|bun +test|jest|vitest|go +test|cargo +test|rspec|make +test|dotnet +test|(gradle|mvn) +.*test)'; then
    interrupted=$(printf '%s' "$input" | jq -r '.tool_response.interrupted // false' 2>/dev/null)
    [ "$interrupted" = "true" ] && exit 0
    out=$(printf '%s' "$input" | jq -r '((.tool_response.stdout // "") + "\n" + (.tool_response.stderr // ""))' 2>/dev/null)
    # Must show a definitive pass marker AND no failure marker.
    pass='(\*\* TEST SUCCEEDED \*\*|[0-9]+ passed|Test Suite.*passed|(^|[^A-Za-z])ok([^A-Za-z]|$)|All tests passed|tests? passed|OK \()'
    fail='(\*\* TEST FAILED \*\*|[1-9][0-9]* failed|Test Suite.*failed|(^|[^A-Za-z])FAIL([^A-Za-z]|$)|FAILED|✗|❌)'
    if echo "$out" | grep -Eqi "$pass" && ! echo "$out" | grep -Eq "$fail"; then
        signal="passing tests"
    fi
fi

# --- Signal 3: the command that completes an unattended slate --------------
# Only when the user's continuity configuration names one (`unattended`). It
# returns an unattended session to attended mode; wrap-cadence confirms it
# succeeded.
if [ -z "$signal" ] && printf '%s' "$input" | python3 "$(dirname "$0")/../scripts/lib/checklist.py" is-completion-command 2>/dev/null; then
    signal="slate completion"
fi

[ -z "$signal" ] && exit 0

# Factory sessions and subagents never run the checklist, so they get no nudge.
# An unattended session mid-slate checkpoints instead: its one full checklist
# runs after the slate's completion command. Unknown (the module failed) nudges.
cadence=$(printf '%s' "$input" | python3 "$(dirname "$0")/../scripts/lib/checklist.py" wrap-cadence 2>/dev/null) || cadence="checklist"
[ "$cadence" = "none" ] && exit 0

sid=$(printf '%s' "$input" | jq -r '.session_id // "unknown"' 2>/dev/null)
# The command that runs the checklist. An adapter whose tool namespaces the
# package's skills (a Claude Code plugin: /continuity:checklist) sets it.
checklist="${CHECKLIST_COMMAND:-/checklist}"
if [ "$cadence" = "checkpoint" ]; then
    # Not throttled, but only on git: each ticket in the slate lands as a commit.
    case "$signal" in git*) : ;; *) exit 0 ;; esac
    printf '{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":"%s in an unattended session. If this finishes a ticket in the slate, checkpoint now (the checkpoint skill) so carried items survive. Run %s unattended once, after the slate completion command succeeds; not after each ticket."}}\n' "$signal" "$checklist"
    exit 0
fi
if [ "$cadence" = "unattended-checklist" ]; then
    flag="${TMPDIR:-/tmp}/claude-checklist-unattended-${sid}"
    [ -f "$flag" ] && exit 0
    touch "$flag" 2>/dev/null || true
    printf '{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":"%s: the unattended slate is complete. Run %s now, once, unattended: pass --unattended to plan, report, and wrap-check. A step that needs the user'"'"'s answer reports pending, writes nothing, and the checklist continues. Wrap check fails without --unattended until this wrap passes."}}\n' "$signal" "$checklist"
    exit 0
fi
[ "$signal" = "slate completion" ] && exit 0
flag="${TMPDIR:-/tmp}/claude-checklist-nudge-${sid}"
[ -f "$flag" ] && exit 0          # already nudged this session
touch "$flag" 2>/dev/null || true

# One command, no routing: the checklist detects the surfaces this session
# touched and merges each one's steps into the shared spine itself.
items="the record, harness lessons, and pushing every repo touched"

printf '{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":"%s — a real task-completion signal. If this wraps up a unit of work, run %s before moving on. The items most often skipped: %s. (Fires once per session.)"}}\n' "$signal" "$checklist" "$items"
exit 0
