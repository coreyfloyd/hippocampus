#!/bin/bash
# #909: pickup.sh must resolve EVERY branch/worktree a
# session touched, not just the last-seen one, and classify each into the
# required states. This exercises the alarm paths (dirty, unmerged,
# deleted-with-no-merge) against a disposable, hermetic git repo -- no
# unmerged branch was reliably outstanding in the real sample transcript by
# the time this test was written (the sampled branch landed after the ticket
# was filed), so the alarm states need a constructed fixture.
#
# #910 eval round 1 (F1, F8) reworked this suite:
#   - pickup.sh's directory lens is JSON-only now (no text render at
#     all), so this asserts against the parsed --json object's `branches[]`
#     structure directly, not grepped emoji/text lines. Case E's guard is
#     `merge_evidence is None`, which is strictly stronger than the old
#     `grep -F shared-scope | grep -Fq shared-scope-2` substring heuristic
#     (that heuristic would also fire on an unrelated co-occurrence).
#   - The row-shape template is the COMMITTED fixture
#     tests/fixtures/pickup-session.jsonl, not a scan of the developer's
#     live $HOME/.claude/projects/*/*.jsonl. The live scan made this suite's
#     result depend on whatever happened to be on the box running it, and
#     silently reported PASS-shaped SKIP (exit 0) on a box with no local
#     transcript store.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT="$REPO_DIR/scripts/pickup.sh"
GEN="$REPO_DIR/tests/fixtures/gen_branch_scan_transcript.py"
TEMPLATE="$REPO_DIR/tests/fixtures/pickup-session.jsonl"

[ -f "$TEMPLATE" ] || { echo "test-pickup-branch-scan: FAIL — missing fixture $TEMPLATE"; exit 1; }

# Resolve to the REAL path: mktemp -d on macOS returns /var/folders/... but
# /var is itself a symlink to /private/var, and `git worktree list
# --porcelain` reports the resolved path. A raw mktemp path here would make
# every worktree-path lookup miss even though production paths (under
# /Users/..., no symlink components) never hit this.
TEST_HOME="$(cd "$(mktemp -d)" && pwd -P)"
TEST_REPO="$TEST_HOME/repo"
trap 'rm -rf "$TEST_HOME"' EXIT

# ---------------------------------------------------------------- fixture repo
git init -q -b main "$TEST_REPO"
git -C "$TEST_REPO" config user.email test@example.com
git -C "$TEST_REPO" config user.name "Test"
git -C "$TEST_REPO" commit -q --allow-empty -m "init"

# Case A: worktree exists, dirty -> highest alarm.
git -C "$TEST_REPO" worktree add -q -b dirty-branch "$TEST_REPO/.worktrees/dirty-branch"
echo uncommitted > "$TEST_REPO/.worktrees/dirty-branch/scratch.txt"

# Case B: worktree exists, clean, branch has a commit not on main -> yellow.
git -C "$TEST_REPO" worktree add -q -b clean-unmerged-branch "$TEST_REPO/.worktrees/clean-unmerged-branch"
git -C "$TEST_REPO/.worktrees/clean-unmerged-branch" commit -q --allow-empty -m "feature work"

# Case C: worktree removed, branch still exists with a commit not on main -> yellow.
git -C "$TEST_REPO" worktree add -q -b gone-unmerged-branch "$TEST_REPO/.worktrees/gone-unmerged-branch"
git -C "$TEST_REPO/.worktrees/gone-unmerged-branch" commit -q --allow-empty -m "feature work 2"
git -C "$TEST_REPO" worktree remove -f "$TEST_REPO/.worktrees/gone-unmerged-branch"

# Case D: worktree removed, branch deleted, no merge commit anywhere -> red alarm.
git -C "$TEST_REPO" worktree add -q -b ghost-branch "$TEST_REPO/.worktrees/ghost-branch"
git -C "$TEST_REPO/.worktrees/ghost-branch" commit -q --allow-empty -m "lost work"
git -C "$TEST_REPO" worktree remove -f "$TEST_REPO/.worktrees/ghost-branch"
git -C "$TEST_REPO" branch -D ghost-branch >/dev/null

# Case E: #909 review-finding regression guard. shared-scope is deleted with
# NO merge commit of its own; shared-scope-2 IS merged, and its merge subject
# contains "shared-scope" as a leading substring. An unanchored
# `git log --grep=shared-scope` would match shared-scope-2's merge subject
# and falsely report shared-scope as landed -- exactly the wrong-branch-
# credited bug the anchored regex in find_merge() exists to prevent.
git -C "$TEST_REPO" worktree add -q -b shared-scope "$TEST_REPO/.worktrees/shared-scope"
git -C "$TEST_REPO/.worktrees/shared-scope" commit -q --allow-empty -m "shared-scope work"
git -C "$TEST_REPO" worktree remove -f "$TEST_REPO/.worktrees/shared-scope"
git -C "$TEST_REPO" branch -D shared-scope >/dev/null

git -C "$TEST_REPO" worktree add -q -b shared-scope-2 "$TEST_REPO/.worktrees/shared-scope-2"
git -C "$TEST_REPO/.worktrees/shared-scope-2" commit -q --allow-empty -m "shared-scope-2 work"
git -C "$TEST_REPO" merge -q --no-ff shared-scope-2 -m "merge: #999 shared-scope-2 follow-up (shared-scope-2 @ done)"
git -C "$TEST_REPO" worktree remove -f "$TEST_REPO/.worktrees/shared-scope-2"
git -C "$TEST_REPO" branch -D shared-scope-2 >/dev/null

# ---------------------------------------------------------------- fixture transcript
SESSION_ID="branch-scan-fixture"
PDIR_SLUG="$(printf '%s' "$TEST_REPO" | sed 's#[/.]#-#g')"
PDIR="$TEST_HOME/.claude/projects/$PDIR_SLUG"
mkdir -p "$PDIR"
python3 "$GEN" "$TEMPLATE" "$PDIR/$SESSION_ID.jsonl" "$TEST_REPO"

# ---------------------------------------------------------------- run + assert
OUT="$(cd "$TEST_REPO" && HOME="$TEST_HOME" CODEX_HOME="$TEST_HOME/.codex" bash "$SCRIPT" --json --session "$SESSION_ID" 2>&1)"

fail() { echo "test-pickup-branch-scan: FAIL — $1"; echo "----- output -----"; echo "$OUT"; exit 1; }

printf '%s' "$OUT" | python3 -c '
import json, sys

try:
    d = json.load(sys.stdin)
except Exception as e:
    print("NOT_JSON: %s" % e)
    sys.exit(1)

if not isinstance(d, dict) or d.get("version") != 2:
    print("BAD_SHAPE: expected a version-2 object, got %r" % (d,))
    sys.exit(1)

branches = {b["branch"]: b for b in d.get("branches", [])}

def need(name):
    if name not in branches:
        print("MISSING_BRANCH: %s" % name)
        sys.exit(1)
    return branches[name]

b = need("dirty-branch")
if b["state"] != "dirty":
    print("dirty-branch: expected state dirty, got %r" % b["state"]); sys.exit(1)
if not (b["worktree_path"] or "").endswith(".worktrees/dirty-branch"):
    print("dirty-branch: worktree_path missing/wrong: %r" % b["worktree_path"]); sys.exit(1)

b = need("clean-unmerged-branch")
if b["state"] != "clean_unmerged":
    print("clean-unmerged-branch: expected state clean_unmerged, got %r" % b["state"]); sys.exit(1)
if not b["worktree_exists"]:
    print("clean-unmerged-branch: expected worktree_exists true"); sys.exit(1)

b = need("gone-unmerged-branch")
if b["state"] != "gone_unmerged":
    print("gone-unmerged-branch: expected state gone_unmerged, got %r" % b["state"]); sys.exit(1)
if b["ref"] != "local":
    print("gone-unmerged-branch: expected ref local (branch still exists), got %r" % b["ref"]); sys.exit(1)

b = need("ghost-branch")
if b["state"] != "deleted_no_merge":
    print("ghost-branch: expected state deleted_no_merge, got %r" % b["state"]); sys.exit(1)
if b["merge_evidence"] is not None:
    print("ghost-branch: expected no merge evidence, got %r" % b["merge_evidence"]); sys.exit(1)

# Case E, the regression guard: strictly `merge_evidence is None`, not a
# substring heuristic -- shared-scope must not be credited with the
# shared-scope-2 merge just because the merge subject contains its name
# as a leading substring.
b = need("shared-scope")
if b["state"] != "deleted_no_merge":
    print("shared-scope: expected state deleted_no_merge (wrongly credited to shared-scope-2?), got %r" % b["state"]); sys.exit(1)
if b["merge_evidence"] is not None:
    print("shared-scope: merge_evidence must be None, got %r -- unanchored merge-subject match regressed" % b["merge_evidence"]); sys.exit(1)

# shared-scope-2 itself is not a seen_branches/cwd entry in the generated
# fixture transcript (gen_branch_scan_transcript.py never names it in a
# row), so it cannot appear in branches[] here -- this suite only asserts
# shared-scope is not wrongly credited with ITS merge, matching the
# original #909 Case E scope.

print("STRUCTURE_OK")
' || fail "JSON structure assertions failed (see output above)"

echo "test-pickup-branch-scan: PASS"
