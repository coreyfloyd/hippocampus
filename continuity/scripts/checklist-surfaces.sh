#!/usr/bin/env bash
# Candidate-surface detector for the `checklist` skill's Step 0.
#
# Prints one `profile<TAB>path` line per surface that looks like this session
# touched it — working-tree changes or unpushed commits. The skill treats the
# output as CANDIDATES, not a verdict: a shared checkout is co-edited by
# other sessions, so a dirty tree there may belong to someone else, and a
# surface committed+pushed mid-session leaves nothing to detect.
#
# Profiles only ever ADD steps to the checklist spine, so a false positive
# costs a skipped report line, never lost persistence. That asymmetry is why
# this errs toward emitting.
#
# Known and accepted: a worktree resolves to its MAIN checkout (see repo_root
# below), so a `.claude/checklist-profile.md` that exists only on a branch is
# invisible here until it merges. Not a bug — the skill tells the reader to add
# a surface the detector missed.
#
# bash 3.2 (macOS system bash): no mapfile, no `declare -A`, no `${x,,}`.
# Advisory tool: fail open, exit 0 even when git is unhappy.

set -uo pipefail

# Standing surfaces and the suite-baseline directory come from the continuity
# configuration (`checklist_surfaces`, `checklist_suite_baselines_dir`); with
# none configured the candidates are the session's own repository only.
HANDOFF_PY="${HANDOFF_PY:-$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)/lib/handoff.py}"
BASELINES_DIR=""
STANDING=()
config_path() { case "$1" in "~"|"~/"*) printf '%s\n' "$HOME${1#\~}" ;; *) printf '%s\n' "$1" ;; esac; }
if [ -f "$HANDOFF_PY" ]; then
    _b=$(python3 "$HANDOFF_PY" config-get checklist_suite_baselines_dir 2>/dev/null) || _b=""
    [ -n "$_b" ] && BASELINES_DIR=$(config_path "$_b")
    while IFS= read -r _s; do
        [ -n "$_s" ] && STANDING+=("$(config_path "$_s")")
    done < <(python3 "$HANDOFF_PY" config-get checklist_surfaces 2>/dev/null)
fi

# Repo root for a path, correct inside a linked worktree: --show-toplevel names
# the BRANCH DIRECTORY there (`.worktrees/feature-x` resolves to itself), so go via
# --git-common-dir and take its parent (a worktree is not its repository).
repo_root() {
    _gcd=$(git -C "$1" rev-parse --git-common-dir 2>/dev/null) || return 1
    [ -z "$_gcd" ] && return 1
    case "$_gcd" in
        /*) : ;;
        *) _gcd="$(cd "$1" 2>/dev/null && cd "$_gcd" 2>/dev/null && pwd)" || return 1 ;;
    esac
    _root=$(cd "$_gcd/.." 2>/dev/null && pwd) || return 1
    printf '%s\n' "$_root"
}

# Has uncommitted changes, or commits not on the tracked upstream.
has_activity() {
    _r="$1"
    [ -n "$(git -C "$_r" status --porcelain 2>/dev/null)" ] && return 0
    _up=$(git -C "$_r" rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null) || return 1
    [ -z "$_up" ] && return 1
    _ahead=$(git -C "$_r" rev-list --count "$_up..HEAD" 2>/dev/null) || return 1
    [ "${_ahead:-0}" -gt 0 ] 2>/dev/null && return 0
    return 1
}

# Project markers that mean "this repo holds code with a test suite". Checked
# one level down too: a repo may keep its package in a subdirectory with no
# root-level marker at all.
has_code_markers() {
    _r="$1"
    for _m in Package.swift package.json pyproject.toml setup.py Cargo.toml go.mod Makefile; do
        [ -e "$_r/$_m" ] && return 0
        ls -d "$_r"/*/"$_m" >/dev/null 2>&1 && return 0
    done
    ls -d "$_r"/*.xcodeproj "$_r"/*.xcworkspace >/dev/null 2>&1 && return 0
    return 1
}

emit_for() {
    _r="$1"
    [ -d "$_r" ] || return 0
    has_activity "$_r" || return 0

    if [ -f "$_r/.claude/checklist-profile.md" ]; then
        printf 'discovered\t%s\n' "$_r/.claude/checklist-profile.md"
    fi
    # A declared suite baseline is the strongest signal that this repo has a
    # suite to run, and it is the source the `code` profile reads first.
    _slug=$(basename "$_r")
    if { [ -n "$BASELINES_DIR" ] && [ -f "$BASELINES_DIR/$_slug.yaml" ]; } || has_code_markers "$_r"; then
        printf 'code\t%s\n' "$_r"
    fi
}

# Candidates: the session's own repo, plus the configured standing surfaces
# every session can touch regardless of cwd.
CWD_ROOT=$(repo_root "$PWD" 2>/dev/null || true)

seen=""
for cand in "$CWD_ROOT" ${STANDING[@]+"${STANDING[@]}"}; do
    [ -z "$cand" ] && continue
    case " $seen " in *" $cand "*) continue ;; esac
    seen="$seen $cand"
    emit_for "$cand"
done

exit 0
