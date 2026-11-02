#!/bin/bash
# Compatibility adapter: the typed handoff module owns all decisions.
_handoff_dir="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
_handoff_py="${HANDOFF_PY:-$_handoff_dir/handoff.py}"
handoff_is_interactive() { python3 "$_handoff_py" is-interactive "$1"; }
handoff_repository_root() { python3 "$_handoff_py" repository-root "$1"; }
resolve_handoff_subject_path() {
    python3 "$_handoff_py" resolve --subject "$1" \
        --session-id "${2:-${CLAUDE_SESSION_ID:-${CLAUDE_CODE_SESSION_ID:-${CODEX_THREAD_ID:-}}}}"
}
handoff_count_for_repository() { python3 "$_handoff_py" count "$1"; }
resolve_handoff_path() {
    python3 "$_handoff_py" resolve "$1" \
        --session-id "${2:-${CLAUDE_SESSION_ID:-${CLAUDE_CODE_SESSION_ID:-${CODEX_THREAD_ID:-}}}}"
}
handoff_atomic_write() { python3 "$_handoff_py" write "$1"; }
# Correct checkpoint entry point: reads continuation JSON on stdin, composes
# subject/git, lints, writes atomically. Prefer this over handoff_atomic_write,
# which is the low-level primitive and now refuses a subject-less payload (#1411).
handoff_checkpoint() { python3 "$_handoff_py" checkpoint "$@"; }
