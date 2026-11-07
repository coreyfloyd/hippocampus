#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONTRACT="$ROOT/contracts/karpathy-wiki.md"
PROFILE="$ROOT/profiles/karpathy-wiki.example.md"
# Leakage guards must FAIL CLOSED. These were written with `rg`, which is not a
# POSIX tool and is absent from a bare shell: `if rg ...; then exit 1; fi` then
# returned 127, the guard fell through, and the suite still exited 0 — so the
# checks protecting a public release from private paths and names passed
# vacuously. Use grep and treat anything other than a definite "no match" as a
# failure.
scan() {
  local desc="$1"; shift
  local out status
  out="$(grep "$@" 2>&1)" && status=0 || status=$?
  case "$status" in
    1) return 0 ;;
    0) printf '%s: leaked\n%s\n' "$desc" "$out" >&2; exit 1 ;;
    *) printf '%s: scan failed (grep exit %s)\n%s\n' "$desc" "$status" "$out" >&2; exit 1 ;;
  esac
}

test -f "$CONTRACT"
test -f "$PROFILE"
test -f "$ROOT/MIGRATION.md"
test -f "$ROOT/skills/hippocampus-set-up/SKILL.md"
test ! -d "$ROOT/skills/research-tools-set-up"
grep -Fxq 'profile_version: 4' "$PROFILE"
scan 'retired profile fields' -nE '^(raw_dir|wiki_dir|output_dir|docs_dir|capabilities):' "$PROFILE"
grep -Fq 'artifact_followup_destination:' "$PROFILE"
if grep -Fq 'task_destination:' "$PROFILE"; then exit 1; fi
PROFILE_ROOT="$(mktemp -d)"
trap 'rm -rf "$PROFILE_ROOT"' EXIT
mkdir -p "$PROFILE_ROOT/root/raw" "$PROFILE_ROOT/root/wiki" "$PROFILE_ROOT/root/output" "$PROFILE_ROOT/root/docs"
touch "$PROFILE_ROOT/root/wiki/hot.md" "$PROFILE_ROOT/root/docs/log.md" "$PROFILE_ROOT/root/docs/DECISIONS.md"
sed "s|/absolute/path/to/knowledge|$PROFILE_ROOT/root|" "$PROFILE" > "$PROFILE_ROOT/valid.md"
python3 "$ROOT/scripts/validate_profile.py" "$PROFILE_ROOT/valid.md" >/dev/null
sed '5i\
raw_dir: custom-raw' "$PROFILE_ROOT/valid.md" > "$PROFILE_ROOT/noncanonical-topology.md"
if python3 "$ROOT/scripts/validate_profile.py" "$PROFILE_ROOT/noncanonical-topology.md"; then exit 1; fi
sed '5i\
unknown_field: true' "$PROFILE_ROOT/valid.md" > "$PROFILE_ROOT/unknown-field.md"
if python3 "$ROOT/scripts/validate_profile.py" "$PROFILE_ROOT/unknown-field.md"; then exit 1; fi
sed '5i\
capabilities:\
  firecrawl: false' "$PROFILE_ROOT/valid.md" > "$PROFILE_ROOT/inert-capabilities.md"
if python3 "$ROOT/scripts/validate_profile.py" "$PROFILE_ROOT/inert-capabilities.md"; then exit 1; fi
sed '/wiki_followup_destination:/d' "$PROFILE_ROOT/valid.md" > "$PROFILE_ROOT/missing-wiki-followup.md"
if python3 "$ROOT/scripts/validate_profile.py" "$PROFILE_ROOT/missing-wiki-followup.md"; then exit 1; fi

# F4 regression: a comment is recognized only at true line start. An indented
# line beginning with # must still trip the nested-field guard rather than
# being silently skipped as a comment.
sed '5i\
  # sneaky indented comment' "$PROFILE_ROOT/valid.md" > "$PROFILE_ROOT/indented-comment.md"
INDENTED_COMMENT_ERR="$PROFILE_ROOT/indented-comment.err"
if python3 "$ROOT/scripts/validate_profile.py" "$PROFILE_ROOT/indented-comment.md" 2>"$INDENTED_COMMENT_ERR"; then exit 1; fi
grep -Fq 'nested profile fields are not supported' "$INDENTED_COMMENT_ERR"

# Optional wiki: a profile may record the wiki as disabled.
mkdir -p "$PROFILE_ROOT/disabled-root/raw" "$PROFILE_ROOT/disabled-root/output" "$PROFILE_ROOT/disabled-root/docs"
touch "$PROFILE_ROOT/disabled-root/docs/log.md" "$PROFILE_ROOT/disabled-root/docs/DECISIONS.md"
sed -e "s|/absolute/path/to/knowledge|$PROFILE_ROOT/disabled-root|" \
    -e '/^hot_file:/d' \
    -e '/^wiki_followup_destination:/d' \
    "$PROFILE_ROOT/valid.md" > "$PROFILE_ROOT/disabled-base.md"
sed '2a\
wiki_enabled: false' "$PROFILE_ROOT/disabled-base.md" > "$PROFILE_ROOT/disabled.md"
# Validates with no wiki/ directory required or present.
if [ -e "$PROFILE_ROOT/disabled-root/wiki" ]; then exit 1; fi
python3 "$ROOT/scripts/validate_profile.py" "$PROFILE_ROOT/disabled.md" >/dev/null
# A wiki-disabled profile that still names a wiki field fails, naming the contradiction.
sed '2a\
hot_file: wiki/hot.md' "$PROFILE_ROOT/disabled.md" > "$PROFILE_ROOT/disabled-with-hot-file.md"
DISABLED_HOTFILE_ERR="$PROFILE_ROOT/disabled-hot-file.err"
if python3 "$ROOT/scripts/validate_profile.py" "$PROFILE_ROOT/disabled-with-hot-file.md" 2>"$DISABLED_HOTFILE_ERR"; then exit 1; fi
grep -Fq 'hot_file' "$DISABLED_HOTFILE_ERR"
sed '2a\
wiki_followup_destination: "route"' "$PROFILE_ROOT/disabled.md" > "$PROFILE_ROOT/disabled-with-followup.md"
DISABLED_FOLLOWUP_ERR="$PROFILE_ROOT/disabled-followup.err"
if python3 "$ROOT/scripts/validate_profile.py" "$PROFILE_ROOT/disabled-with-followup.md" 2>"$DISABLED_FOLLOWUP_ERR"; then exit 1; fi
grep -Fq 'wiki_followup_destination' "$DISABLED_FOLLOWUP_ERR"
# F2 regression: a wiki-only key whose value was emptied (the line is still
# present, just blank after the colon) is still the key being present, and
# must still fail as a contradiction rather than being treated as absent.
sed '2a\
hot_file:' "$PROFILE_ROOT/disabled.md" > "$PROFILE_ROOT/disabled-empty-hot-file.md"
EMPTY_HOTFILE_ERR="$PROFILE_ROOT/disabled-empty-hot-file.err"
if python3 "$ROOT/scripts/validate_profile.py" "$PROFILE_ROOT/disabled-empty-hot-file.md" 2>"$EMPTY_HOTFILE_ERR"; then exit 1; fi
grep -Fq 'hot_file' "$EMPTY_HOTFILE_ERR"
sed '2a\
wiki_followup_destination:' "$PROFILE_ROOT/disabled.md" > "$PROFILE_ROOT/disabled-empty-followup.md"
EMPTY_FOLLOWUP_ERR="$PROFILE_ROOT/disabled-empty-followup.err"
if python3 "$ROOT/scripts/validate_profile.py" "$PROFILE_ROOT/disabled-empty-followup.md" 2>"$EMPTY_FOLLOWUP_ERR"; then exit 1; fi
grep -Fq 'wiki_followup_destination' "$EMPTY_FOLLOWUP_ERR"
# An invalid wiki_enabled value fails.
sed 's/wiki_enabled: false/wiki_enabled: maybe/' "$PROFILE_ROOT/disabled.md" > "$PROFILE_ROOT/invalid-wiki-value.md"
if python3 "$ROOT/scripts/validate_profile.py" "$PROFILE_ROOT/invalid-wiki-value.md"; then exit 1; fi
# An explicit wiki_enabled: true behaves exactly like the absent field.
sed '2a\
wiki_enabled: true' "$PROFILE_ROOT/valid.md" > "$PROFILE_ROOT/explicit-enabled.md"
python3 "$ROOT/scripts/validate_profile.py" "$PROFILE_ROOT/explicit-enabled.md" >/dev/null
# --require-wiki fails closed on a disabled profile and relays a remedy, but
# passes through unaffected on an enabled one (absent field, and explicit true).
REQUIRE_WIKI_ERR="$PROFILE_ROOT/require-wiki.err"
if python3 "$ROOT/scripts/validate_profile.py" "$PROFILE_ROOT/disabled.md" --require-wiki 2>"$REQUIRE_WIKI_ERR"; then exit 1; fi
grep -Fq 'hippocampus-set-up' "$REQUIRE_WIKI_ERR"
python3 "$ROOT/scripts/validate_profile.py" "$PROFILE_ROOT/valid.md" --require-wiki >/dev/null
python3 "$ROOT/scripts/validate_profile.py" "$PROFILE_ROOT/explicit-enabled.md" --require-wiki >/dev/null

# F1 regression: the shipped example's commented wiki_enabled line, used in
# the documented way (uncomment it exactly as written), must parse to a
# clean boolean value with no trailing comment content attached.
UNCOMMENTED_WIKI_LINE="$(sed -n 's/^# \(wiki_enabled:.*\)$/\1/p' "$PROFILE")"
test -n "$UNCOMMENTED_WIKI_LINE"
case "$UNCOMMENTED_WIKI_LINE" in
  "wiki_enabled: true"|"wiki_enabled: false") ;;
  *) printf 'wiki_enabled example line carries trailing content: %s\n' "$UNCOMMENTED_WIKI_LINE" >&2; exit 1 ;;
esac
# Full documented recipe: uncomment that line and drop the two wiki-only
# fields, exactly as setup and INSTALLATION.md instruct, and
# confirm the result validates against a root with no wiki/.
sed -e "s|/absolute/path/to/knowledge|$PROFILE_ROOT/disabled-root|" \
    -e '/^hot_file:/d' \
    -e '/^wiki_followup_destination:/d' \
    -e 's/^# wiki_enabled: false/wiki_enabled: false/' \
    "$PROFILE" > "$PROFILE_ROOT/documented-disable-recipe.md"
grep -Fxq 'wiki_enabled: false' "$PROFILE_ROOT/documented-disable-recipe.md"
python3 "$ROOT/scripts/validate_profile.py" "$PROFILE_ROOT/documented-disable-recipe.md" >/dev/null


scan 'private vault vocabulary' -rnE 'unified Obsidian vault|AI-vault|writing-corpus|R-004|wiki/people/' "$ROOT/skills" "$ROOT/contracts" "$ROOT/profiles" "$ROOT/README.md"
scan 'private paths and names' -rnE --exclude='*.swift' 'claude-dotfiles|research-skills|~/Obsidian|Corey|~/[.]claude/skills|~/Development|wiki/CLAUDE[.]md|wiki/AGENTS[.]md' "$ROOT/skills" "$ROOT/contracts" "$ROOT/profiles" "$ROOT/README.md"
