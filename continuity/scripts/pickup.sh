#!/usr/bin/env bash
# pickup.sh — handoff-first cold-start re-entry (JSON).
# Usage: pickup.sh [--handoff PATH | --session ID | --prune] [--json]
# --no-commitments skips the agent-owned commitments request.
# Without a selection, list handoffs or reconstruct the newest other transcript.
set -uo pipefail

# ---------------------------------------------------------------- args
# Resolve the wrapper itself, including a symlinked entry point. A relocated
# engine still uses this package's helpers unless the caller overrides them.
wrapper_dir="$(python3 -c 'import os,sys; print(os.path.dirname(os.path.realpath(sys.argv[1])))' "${BASH_SOURCE[0]:-$0}")"
# The module that owns where handoffs are stored and reads the configuration.
handoff_py="${HANDOFF_PY:-$wrapper_dir/lib/handoff.py}"
# Read one continuity configuration value into the variable named by $2. A
# malformed configuration makes it return 1 with the reason in $config_error,
# for the caller to report as `handoff_config_error`; an absent key is empty.
config_value() {  # config_value <key> <variable>
  local value
  [ -f "$handoff_py" ] || { printf -v "$2" '%s' ""; return 0; }
  if ! value="$(python3 "$handoff_py" config-get "$1" 2>&1)"; then
    config_error="$value"
    return 1
  fi
  printf -v "$2" '%s' "$value"
}
config_error=""
want_session=""
want_handoff=""
record_args=(--json)
prune=""
directory_option=""

# Every failure path emits the same JSON object, including argument parsing.
json_error() {  # json_error <error-code> <message>
  python3 -c '
import json, sys
print(json.dumps({"version": 2, "error": sys.argv[1], "message": sys.argv[2]}, indent=2))
' "$1" "$2"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --session)
      [ $# -ge 2 ] || { json_error "usage" "--session requires a session id"; exit 2; }
      [ -n "$2" ] || { json_error "usage" "--session requires a non-empty session id"; exit 2; }
      [ -z "$directory_option" ] || { json_error "usage" "--session conflicts with $directory_option"; exit 2; }
      directory_option="--session"
      want_session="$2"; shift 2 ;;
    --handoff)
      [ $# -ge 2 ] || { json_error "usage" "--handoff requires a file path"; exit 2; }
      [ -z "$directory_option" ] || { json_error "usage" "--handoff conflicts with $directory_option"; exit 2; }
      directory_option="--handoff"
      want_handoff="$2"; shift 2 ;;
    --json) shift ;;
    --no-commitments) record_args=(--no-commitments); shift ;;
    --prune)
      [ -z "$directory_option" ] || { json_error "usage" "--prune conflicts with $directory_option"; exit 2; }
      directory_option="--prune"; prune=1; shift ;;
    # print the header comment block, whatever its length: stop at the first
    # non-comment line. A hardcoded range goes stale the moment the header grows
    # and starts spilling code into the help output (#851).
    -h|--help)   sed -n '2,${/^[^#]/q;p;}' "$0"; exit 0 ;;
    *) json_error "usage" "unrecognized option: $1"; exit 2 ;;
  esac
done

engine_path() {
  if [ -n "${PICKUP_ENGINE:-}" ]; then
    [ -f "$PICKUP_ENGINE" ] && printf '%s' "$PICKUP_ENGINE"
    return 0
  fi
  if [ -f "$wrapper_dir/../skills/pickup/scripts/pickup.py" ]; then
    printf '%s' "$wrapper_dir/../skills/pickup/scripts/pickup.py"
  fi
}

run_engine_json() {
  local engine out_file err_file engine_rc
  engine="$(engine_path)"
  if [ -z "$engine" ]; then
    json_error "engine_not_found" "cannot find pickup.py (looked at PICKUP_ENGINE and next to $0 under skills/pickup/scripts)"
    return 1
  fi
  out_file="$(mktemp "${TMPDIR:-/tmp}/resume-report.XXXXXX" 2>/dev/null || mktemp /tmp/resume-report.XXXXXX 2>/dev/null)"
  err_file="$(mktemp "${TMPDIR:-/tmp}/resume-report-err.XXXXXX" 2>/dev/null || mktemp /tmp/resume-report-err.XXXXXX 2>/dev/null)"
  if [ -z "$out_file" ] || [ -z "$err_file" ]; then
    json_error "tmpfile_failed" "cannot create a temporary file (TMPDIR=${TMPDIR:-/tmp})"
    rm -f "$out_file" "$err_file"
    return 1
  fi
  PICKUP_RECORD_HELPER="${PICKUP_RECORD_HELPER:-$wrapper_dir/lib/pickup_record.py}" \
    python3 "$engine" "$@" >"$out_file" 2>"$err_file"
  engine_rc=$?
  if ! python3 -c 'import json,sys; sys.exit(0 if isinstance(json.load(open(sys.argv[1])), dict) else 1)' "$out_file" 2>/dev/null; then
    json_error "engine_bad_output" "pickup.py exited $engine_rc: $(tr '\n' ' ' < "$err_file" | tail -c 400)"
    rm -f "$out_file" "$err_file"
    return 1
  fi
  if [ "$engine_rc" -ne 0 ] && ! python3 -c 'import json,sys; sys.exit(0 if json.load(open(sys.argv[1])).get("error") else 1)' "$out_file" 2>/dev/null; then
    json_error "engine_failed" "pickup.py exited $engine_rc: $(tr '\n' ' ' < "$err_file" | tail -c 400)"
    rm -f "$out_file" "$err_file"
    return "$engine_rc"
  fi
  cat "$out_file"
  rm -f "$out_file" "$err_file"
  return "$engine_rc"
}

# ---------------------------------------------------------------- dispatch
if [ -n "$want_handoff" ]; then
  run_engine_json --handoff "$want_handoff" "${record_args[@]}"
else
  # The handoff module owns where handoffs are stored (HANDOFF_STATE_DIR,
  # else the continuity configuration, else its default).
  if ! state_dir="$(python3 "$handoff_py" state-dir 2>&1)"; then
    json_error "handoff_config_error" "pickup: $state_dir"
    exit 1
  fi
  # Both transcript providers use this one threshold. Leave an explicit
  # environment override intact; the engine supplies 7 when neither is set.
  if [ -z "${PICKUP_PRUNE_DAYS:-}" ]; then
    config_value prune_days prune_days \
      || { json_error "handoff_config_error" "pickup: $config_error"; exit 1; }
    [ -z "$prune_days" ] || export PICKUP_PRUNE_DAYS="$prune_days"
  fi
  current_session="${CLAUDE_CODE_SESSION_ID:-${CLAUDE_SESSION_ID:-}}"
  # The invoking Codex thread is excluded too (#1453): the automatic lens
  # lists both providers' sessions, and under Codex the newest rollout for
  # this directory is the caller itself. Exclusion only; the store that
  # owns a session is decided by the engine from the stores, not this env.
  engine_args=(--directory-resume "$state_dir" "$PWD" "$HOME" --codex-home "${CODEX_HOME:-$HOME/.codex}"
               --current-session "$current_session" --current-session "${CODEX_THREAD_ID:-}")
  [ -n "$want_session" ] && engine_args+=(--transcript-session "$want_session")
  [ -n "$prune" ] && engine_args+=(--prune)
  run_engine_json "${engine_args[@]}"
fi
