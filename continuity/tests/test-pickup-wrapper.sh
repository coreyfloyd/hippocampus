#!/bin/bash
# test-pickup-wrapper.sh — #910 round 4.
#
# scripts/pickup.sh's own contract, at the one seam it still owns: it
# finds the engine, runs it, and is answerable for what reaches stdout when the
# engine does not behave. Its header (":72-75") promises that EVERY failure
# path prints the same JSON shape. Three ways that used to be false:
#
#   F3  — a crashing engine gave the caller a Python traceback on stderr and
#         EMPTY stdout. A morning cron parsing stdout got nothing to parse.
#   F3b — the engine's exit code was never read at all (`$?` unchecked), so an
#         engine that printed valid JSON and exited 3 produced rc=0 and a
#         clean-looking report.
#   (new) an engine that exits 0 having printed something that is not JSON.
#
# The engine is stubbed by building a two-file temp tree — a copy of
# pickup.sh next to a fake skills/pickup/scripts/pickup.py — so
# the $0-relative engine lookup the script header calls load-bearing is the
# thing under test, and no production surface gains a test-only env var.
#
# Bash 3.2 target (macOS system bash).
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REAL="$ROOT/scripts/pickup.sh"

FAILURES=0
fail() { echo "FAIL: $*"; FAILURES=$((FAILURES + 1)); }
pass() { echo "ok:   $*"; }

SANDBOX="$(cd "$(mktemp -d)" && pwd -P)"
trap 'rm -rf "$SANDBOX"' EXIT

FAKE_HOME="$SANDBOX/home"
WORKDIR="$SANDBOX/work"
mkdir -p "$FAKE_HOME/.claude" "$WORKDIR" "$SANDBOX/tmp"
printf 'macbook' > "$FAKE_HOME/.claude/.machine"

# A transcript the directory lens can resolve: two rows is enough, since the
# engine is stubbed and never reads them.
SESSION_ID="wrapper-fixture"
PDIR="$FAKE_HOME/.claude/projects/$(printf '%s' "$WORKDIR" | sed 's#[/.]#-#g')"
mkdir -p "$PDIR"
cat > "$PDIR/$SESSION_ID.jsonl" <<'JSONL'
{"type":"user","timestamp":"2026-09-01T10:00:00Z","gitBranch":"main","message":{"role":"user","content":"do the thing"}}
{"type":"assistant","timestamp":"2026-09-01T10:00:05Z","gitBranch":"main","message":{"role":"assistant","content":[{"type":"text","text":"done"}],"stop_reason":"end_turn"}}
JSONL

# build_engine <python-body> — a temp tree whose layout matches the $0-relative
# lookup: <tree>/scripts/pickup.sh and <tree>/skills/pickup/scripts/.
build_engine() {
    TREE="$SANDBOX/tree.$RANDOM"
    mkdir -p "$TREE/scripts/lib" "$TREE/skills/pickup/scripts"
    cp "$REAL" "$TREE/scripts/pickup.sh"
    # The wrapper asks the handoff module where handoffs are stored (#1572).
    cp "$ROOT/scripts/lib/handoff.py" "$TREE/scripts/lib/handoff.py"
    printf '%s\n' "$1" > "$TREE/skills/pickup/scripts/pickup.py"
}

run_wrapper() {  # -> stdout on fd1, rc in $RC
    OUT=$( cd "$WORKDIR" && HOME="$FAKE_HOME" CODEX_HOME="$FAKE_HOME/.codex" \
        TMPDIR="$SANDBOX/tmp" bash "$TREE/scripts/pickup.sh" \
        --session "$SESSION_ID" 2>/dev/null )
    RC=$?
}

run_handoff_wrapper() {  # -> stdout on fd1, rc in $RC
    OUT=$( cd "$WORKDIR" && HOME="$FAKE_HOME" CODEX_HOME="$FAKE_HOME/.codex" \
        TMPDIR="$SANDBOX/tmp" bash "$TREE/scripts/pickup.sh" \
        --handoff "$SANDBOX/selected.json" 2>/dev/null )
    RC=$?
}

is_error_object() {  # is_error_object <json>
    printf '%s' "$1" | python3 -c '
import json, sys
d = json.load(sys.stdin)
assert isinstance(d, dict), d
assert d.get("version") == 2, d
assert d.get("error"), d
' >/dev/null 2>&1
}

# ---------------------------------------------------------------- W1
# Engine crashes: traceback on stderr, nothing on stdout, non-zero exit.
build_engine 'raise RuntimeError("boom")'
run_wrapper
if is_error_object "$OUT"; then pass "W1: a crashing engine still yields the error object on stdout"
else fail "W1: stdout was not a version-2 error object: [$OUT]"; fi
if [ "$RC" -ne 0 ]; then pass "W1: a crashing engine yields a non-zero exit ($RC)"
else fail "W1: exit 0 for a crashed engine"; fi

# ---------------------------------------------------------------- W2  (F3b)
# Engine prints VALID JSON and exits non-zero. The exit code is the only
# signal; discarding it produced a clean-looking report from a failed run.
build_engine 'import json, sys
print(json.dumps({"version": 2, "session": "x"}))
sys.exit(3)'
run_wrapper
if [ "$RC" -ne 0 ]; then pass "W2: a non-zero engine exit propagates ($RC)"
else fail "W2: engine exited 3, wrapper returned 0 — F3b"; fi
if is_error_object "$OUT"; then pass "W2: stdout is still the documented error object"
else fail "W2: stdout was not an error object: [$OUT]"; fi

# ---------------------------------------------------------------- W3
# Engine exits 0 having printed something that is not JSON.
build_engine 'print("not json at all")'
run_wrapper
if is_error_object "$OUT"; then pass "W3: non-JSON on a zero exit yields the error object"
else fail "W3: stdout was not an error object: [$OUT]"; fi
if [ "$RC" -ne 0 ]; then pass "W3: non-JSON output yields a non-zero exit ($RC)"
else fail "W3: exit 0 for unparseable engine output"; fi

# ---------------------------------------------------------------- W3b
# Engine exits 0 having printed VALID JSON that is not an object. `[]` is the
# machine-lens array shape the directory lens must never emit; json.load
# accepts it, so parseability alone is not the guard (#910 eval round 4, F-A).
build_engine 'print("[]")'
run_wrapper
if is_error_object "$OUT"; then pass "W3b: a bare JSON array on a zero exit yields the error object"
else fail "W3b: array passed the object guard: [$OUT]"; fi
if [ "$RC" -ne 0 ]; then pass "W3b: non-object JSON yields a non-zero exit ($RC)"
else fail "W3b: exit 0 for non-object engine output — F-A"; fi

# ---------------------------------------------------------------- W4
# The control: a well-behaved engine passes through byte-for-byte, so W1-W3 are
# not passing because the wrapper errors on everything.
build_engine 'import json
print(json.dumps({"version": 2, "session": "wrapper-fixture"}))'
run_wrapper
if [ "$RC" -eq 0 ]; then pass "W4: a healthy engine exits 0"
else fail "W4: healthy engine gave rc=$RC — [$OUT]"; fi
if printf '%s' "$OUT" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["session"]=="wrapper-fixture" and "error" not in d' 2>/dev/null; then
    pass "W4: the engine's own object reaches the caller unaltered"
else fail "W4: report was rewritten: [$OUT]"; fi

# ---------------------------------------------------------------- W5
# The selected-handoff path must use the same fail-closed engine wrapper as
# the transcript path. A direct `python3 "$engine" --handoff ...` leaks an
# empty stdout/traceback when the engine crashes.
build_engine 'raise RuntimeError("boom")'
run_handoff_wrapper
if is_error_object "$OUT"; then pass "W5: a crashing selected-handoff engine yields the error object";
else fail "W5: selected-handoff stdout was not an error object: [$OUT]"; fi
if [ "$RC" -ne 0 ]; then pass "W5: a crashing selected-handoff engine yields a non-zero exit ($RC)";
else fail "W5: selected-handoff crash returned 0"; fi

# Configuration parsing must still report malformed files.
CFG="$SANDBOX/continuity.json"
printf '{not json' > "$CFG"
build_engine 'print("{}")'
OUT=$(cd "$WORKDIR" && HOME="$FAKE_HOME" CONTINUITY_CONFIG="$CFG" bash "$TREE/scripts/pickup.sh" --session "$SESSION_ID")
RC=$?
if [ "$RC" -ne 0 ] && printf '%s' "$OUT" | python3 -c 'import json,sys; assert json.load(sys.stdin)["error"] == "handoff_config_error"'; then
    pass "W6: malformed configuration reports handoff_config_error"
else fail "W6: malformed configuration was accepted"; fi

echo
if [ "$FAILURES" -eq 0 ]; then echo "test-pickup-wrapper: PASS"; exit 0; fi
echo "test-pickup-wrapper: FAIL — $FAILURES assertion(s)"
exit 1
