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
grep -Fq 'valid research-tools installation' "$ROOT/MIGRATION.md"
grep -Fq 'old release directory in place for recovery' "$ROOT/MIGRATION.md"
grep -Fq 'never a backlog sweep' "$CONTRACT"
grep -Fq 'Reports are not raw compiler input' "$CONTRACT"
grep -Fq 'drafts before reading existing wiki' "$CONTRACT"
grep -Fq 'read-only' "$CONTRACT"
grep -Fxq 'profile_version: 4' "$PROFILE"
scan 'retired profile fields' -nE '^(raw_dir|wiki_dir|output_dir|docs_dir|capabilities):' "$PROFILE"
grep -Fxq 'hot_file: wiki/hot.md' "$PROFILE"
grep -Fxq 'operation_log_file: docs/log.md' "$PROFILE"
grep -Fxq 'decision_log_file: docs/DECISIONS.md' "$PROFILE"
grep -Fq 'wiki_followup_destination:' "$PROFILE"
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
# fields, exactly as hippocampus-set-up and INSTALLATION.md instruct, and
# confirm the result validates against a root with no wiki/.
sed -e "s|/absolute/path/to/knowledge|$PROFILE_ROOT/disabled-root|" \
    -e '/^hot_file:/d' \
    -e '/^wiki_followup_destination:/d' \
    -e 's/^# wiki_enabled: false/wiki_enabled: false/' \
    "$PROFILE" > "$PROFILE_ROOT/documented-disable-recipe.md"
grep -Fxq 'wiki_enabled: false' "$PROFILE_ROOT/documented-disable-recipe.md"
python3 "$ROOT/scripts/validate_profile.py" "$PROFILE_ROOT/documented-disable-recipe.md" >/dev/null

for skill in research-to-wiki wiki-audit; do
  grep -Fq 'Karpathy-wiki contract' "$ROOT/skills/$skill/SKILL.md" || exit 1
  grep -Fq '~/.config/hippocampus/profile.md' "$ROOT/skills/$skill/SKILL.md" || exit 1
done
grep -Fq 'free-form local policy body' "$PROFILE"
grep -Fq 'free-form local policy body' "$ROOT/contracts/karpathy-wiki.md"
grep -Fq 'Obsidian-style wikilinks' "$CONTRACT"
grep -Fq 'session cache' "$CONTRACT"
grep -Fq 'wiki follow-up destination' "$CONTRACT"
grep -Fq 'artifact follow-up destination' "$CONTRACT"
grep -Fq 'must not infer' "$CONTRACT"
grep -Fq 'Andrej Karpathy' "$CONTRACT"
grep -Fq 'canonical directories' "$CONTRACT"
grep -Fq 'runtime-detected optional integrations' "$CONTRACT"
for skill in research-sources research-topic research-feature research-feedback research-absorb; do
  grep -Fq 'artifact_followup_destination' "$ROOT/skills/$skill/SKILL.md" || exit 1
done
grep -Fq 'artifact_followup_destination' "$ROOT/skills/knowledge-capture/SKILL.md"
# research-feature and research-feedback produce deliverables, not absorb handoffs.
for skill in research-feature research-feedback; do
  grep -Fq 'research-absorb` does not apply' "$ROOT/skills/$skill/SKILL.md" || exit 1
  if grep -Fq 'artifact-contract.md' "$ROOT/skills/$skill/SKILL.md"; then exit 1; fi
  if grep -Fq 'Findings format' "$ROOT/skills/$skill/SKILL.md"; then exit 1; fi
done
grep -Fq '## Sources' "$ROOT/skills/research-feature/SKILL.md"
grep -Fq '## Communities to watch' "$ROOT/skills/research-feedback/SKILL.md"
if grep -Fq 'research-feature, or research-feedback' "$ROOT/skills/research-absorb/SKILL.md"; then exit 1; fi
for skill in research-to-wiki wiki-audit; do
  grep -Fq 'wiki_followup_destination' "$ROOT/skills/$skill/SKILL.md" || exit 1
done
for skill in research-sources research-topic research-feature research-feedback research-dev research-quick; do
  grep -Fq 'runtime-detected' "$ROOT/skills/$skill/SKILL.md" || exit 1
done
grep -Fq 'runtime-detected' "$ROOT/skills/transcribe/SKILL.md"
for skill in research-sources research-topic research-feature research-feedback research-absorb knowledge-capture research-to-wiki wiki-audit; do
  grep -Fq 'scripts/validate_profile.py' "$ROOT/skills/$skill/SKILL.md" || exit 1
  grep -Fq 'hippocampus-set-up' "$ROOT/skills/$skill/SKILL.md" || exit 1
done
grep -Fq 'profiles/karpathy-wiki.example.md' "$ROOT/skills/hippocampus-set-up/SKILL.md"
grep -Fq 'scripts/validate_profile.py' "$ROOT/skills/hippocampus-set-up/SKILL.md"
grep -Fq 'Do not write or change configuration until the user approves' "$ROOT/skills/hippocampus-set-up/SKILL.md"

# Optional wiki: setup asks with no lean, gates wiki-only questions, and can
# flip the wiki state later without redoing the rest of setup.
#
# The phrase greps below (and the similar ones later in this file, matching
# the file's pre-existing convention for skill and contract prose) confirm
# required doctrine is present in the shipped text. They are not behavioral
# tests: they cannot prove an agent follows the instruction, only that the
# instruction exists, and a reword that preserves meaning will need a
# matching reword here. The validator cases above them are the behavioral
# tests for this feature; there is no bash-only way to exercise agent-read
# Markdown instructions behaviorally.
grep -Fq 'Neither option is the default or the recommendation' "$ROOT/skills/hippocampus-set-up/SKILL.md"
grep -Fq 'no `wiki/hot.md`, no `hot_file`, and no `wiki_followup_destination`' "$ROOT/skills/hippocampus-set-up/SKILL.md"
grep -Fq '## Enable or disable the wiki later' "$ROOT/skills/hippocampus-set-up/SKILL.md"
grep -Fq 'Never delete or modify `wiki/`' "$ROOT/skills/hippocampus-set-up/SKILL.md"

# The wiki skills gate on the validator's require-wiki option, not their own
# judgment, and relay its refusal back to setup.
for skill in research-to-wiki wiki-audit; do
  grep -Fq -- '--require-wiki' "$ROOT/skills/$skill/SKILL.md" || exit 1
  grep -Fq 'hippocampus-set-up enables' "$ROOT/skills/$skill/SKILL.md" || exit 1
done

# A wiki-disabled artifact has no Wiki Additions class, and research-absorb
# neither stages provenance nor invokes the compiler.
grep -Fq 'exists only for wiki-enabled profiles' "$ROOT/skills/research-absorb/references/artifact-contract.md"
grep -Fq 'never invokes `research-to-wiki`' "$ROOT/skills/research-absorb/references/artifact-contract.md"

# knowledge-capture offers no wiki classification when the wiki is disabled.
grep -Fq 'offers no wiki classification' "$ROOT/skills/knowledge-capture/SKILL.md"
# F3 regression: a disabled-wiki named referent must route to a classification
# knowledge-capture actually defines, not the research-absorb-only "Document
# Update" class this skill never explains.
if grep -Fq 'Document Update' "$ROOT/skills/knowledge-capture/SKILL.md"; then exit 1; fi
grep -Fq 'raw/derived/' "$ROOT/skills/knowledge-capture/SKILL.md"

# The contract, README, INSTALLATION, and MIGRATION describe the wiki as optional.
grep -Fq 'wiki is optional' "$CONTRACT"
grep -Fq -- '--require-wiki' "$CONTRACT"
grep -Fq 'never deletes or modifies an existing `wiki/`' "$CONTRACT"
grep -Fq 'wiki is optional' "$ROOT/README.md"
grep -Fq 'wiki is enabled by default' "$ROOT/INSTALLATION.md"
grep -Fq 'wiki_enabled: false' "$ROOT/INSTALLATION.md"
grep -Fq 'Existing version-4 profiles need no change' "$ROOT/MIGRATION.md"

scan 'private vault vocabulary' -rnE 'unified Obsidian vault|AI-vault|writing-corpus|R-004|wiki/people/' "$ROOT/skills" "$ROOT/contracts" "$ROOT/profiles" "$ROOT/README.md"
scan 'private paths and names' -rnE --exclude='*.swift' 'claude-dotfiles|research-skills|~/Obsidian|Corey|~/[.]claude/skills|~/Development|wiki/CLAUDE[.]md|wiki/AGENTS[.]md' "$ROOT/skills" "$ROOT/contracts" "$ROOT/profiles" "$ROOT/README.md"
