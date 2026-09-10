#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="$(tr -d '[:space:]' < "$ROOT/VERSION")"
TEST_HOME="$(mktemp -d)"
SOURCE_ROOT="$TEST_HOME/source"
cp -R "$ROOT" "$SOURCE_ROOT"
BUILD_SENTINEL="$SOURCE_ROOT/skills/transcribe/tools/apple-speech/.build/hippocampus-test-sentinel"
mkdir -p "$(dirname "$BUILD_SENTINEL")"
touch "$BUILD_SENTINEL"
cleanup() {
  status=$?
  rm -rf "$TEST_HOME" "${COLLISION_HOME:-}" "${PROFILE_HOME:-}" "${CONCURRENT_HOME:-}" "${TAMPER_HOME:-}" "${UPGRADE_HOME:-}" "${BROKEN_HOME:-}" "${CURRENT_DIR_HOME:-}" "${RETIRED_HOME:-}" "${NOPY_HOME:-}" "${MISSINGLINK_HOME:-}" "${REMEDY_HOME:-}" "${DSSTORE_HOME:-}" "${MODIFIED_HOME:-}" "${MIGRATE_HOME:-}" "${DIRTY_HOME:-}" "${JUNK_HOME:-}" "$BUILD_SENTINEL"
  exit "$status"
}
trap cleanup EXIT
release_manifest() {
  (
    cd "$1"
    manifest_paths="skills contracts"
    [ ! -d profiles ] || manifest_paths="$manifest_paths profiles"
    [ ! -f scripts/validate_profile.py ] || manifest_paths="$manifest_paths scripts/validate_profile.py"
    find $manifest_paths -type f -not -path '*/.build/*' -not -path '*/.Ulysses-*/*' -not -name '.DS_Store' -not -name '.Ulysses-*' -exec cksum {} \; | LC_ALL=C sort | cksum | awk '{print $1 ":" $2}'
  )
}
release_manifest_legacy() {
  (
    cd "$1"
    manifest_paths="skills contracts"
    [ ! -d profiles ] || manifest_paths="$manifest_paths profiles"
    [ ! -f scripts/validate_profile.py ] || manifest_paths="$manifest_paths scripts/validate_profile.py"
    find $manifest_paths -type f -not -path '*/.build/*' -exec cksum {} \; | LC_ALL=C sort | cksum | awk '{print $1 ":" $2}'
  )
}
HOME="$TEST_HOME" CODEX_HOME="$TEST_HOME/.codex" bash "$SOURCE_ROOT/install.sh"
if HOME="$TEST_HOME" CODEX_HOME="$TEST_HOME/.codex" bash "$SOURCE_ROOT/install.sh" --verify; then
  exit 1
fi
test ! -e "$TEST_HOME/.config/hippocampus/profile.md"
test -L "$TEST_HOME/.local/share/hippocampus/current"
test -L "$TEST_HOME/.claude/skills/hippocampus-set-up"
test -L "$TEST_HOME/.codex/skills/hippocampus-set-up"
test -f "$TEST_HOME/.local/share/hippocampus/releases/$VERSION/profiles/karpathy-wiki.example.md"
test -f "$TEST_HOME/.local/share/hippocampus/releases/$VERSION/scripts/validate_profile.py"
mkdir -p "$TEST_HOME/.config/hippocampus" "$TEST_HOME/knowledge/raw" "$TEST_HOME/knowledge/wiki" "$TEST_HOME/knowledge/output" "$TEST_HOME/knowledge/docs"
touch "$TEST_HOME/knowledge/wiki/hot.md" "$TEST_HOME/knowledge/docs/log.md" "$TEST_HOME/knowledge/docs/DECISIONS.md"
sed "s|/absolute/path/to/knowledge|$TEST_HOME/knowledge|" "$SOURCE_ROOT/profiles/karpathy-wiki.example.md" > "$TEST_HOME/.config/hippocampus/profile.md"
HOME="$TEST_HOME" CODEX_HOME="$TEST_HOME/.codex" bash "$SOURCE_ROOT/install.sh"
HOME="$TEST_HOME" CODEX_HOME="$TEST_HOME/.codex" bash "$SOURCE_ROOT/install.sh"
HOME="$TEST_HOME" CODEX_HOME="$TEST_HOME/.codex" bash "$SOURCE_ROOT/install.sh" --verify
test -L "$TEST_HOME/.local/share/hippocampus/current"
test "$(readlink "$TEST_HOME/.local/share/hippocampus/current")" = "$TEST_HOME/.local/share/hippocampus/releases/$VERSION"
test -f "$TEST_HOME/.local/share/hippocampus/releases/$VERSION/contracts/karpathy-wiki.md"
test -f "$TEST_HOME/.local/share/hippocampus/releases/$VERSION/profiles/karpathy-wiki.example.md"
test -f "$TEST_HOME/.local/share/hippocampus/releases/$VERSION/scripts/validate_profile.py"
test -x "$TEST_HOME/.local/share/hippocampus/releases/$VERSION/skills/research-quick/reddit-read.sh"
test -x "$TEST_HOME/.local/share/hippocampus/releases/$VERSION/skills/transcribe/tools/apple-speech/run-transcribe.sh"
test ! -e "$TEST_HOME/.local/share/hippocampus/releases/$VERSION/skills/transcribe/tools/apple-speech/.build/hippocampus-test-sentinel"
grep -Fq 'Karpathy-wiki contract' "$TEST_HOME/.local/share/hippocampus/releases/$VERSION/skills/research-to-wiki/SKILL.md"
for skill in "$ROOT"/skills/*; do
  test -f "$skill/SKILL.md" || continue
  name="$(basename "$skill")"
  case "$(readlink "$TEST_HOME/.claude/skills/$name")" in
    "$TEST_HOME/.local/share/hippocampus/current/skills/"*) ;;
    *) exit 1 ;;
  esac
  case "$(readlink "$TEST_HOME/.codex/skills/$name")" in
    "$TEST_HOME/.local/share/hippocampus/current/skills/"*) ;;
    *) exit 1 ;;
  esac
done
COLLISION_HOME="$(mktemp -d)"
mkdir -p "$COLLISION_HOME/.claude/skills"
mkdir -p "$COLLISION_HOME/custom-skill"
ln -s "$COLLISION_HOME/custom-skill" "$COLLISION_HOME/.claude/skills/research-topic"
if HOME="$COLLISION_HOME" CODEX_HOME="$COLLISION_HOME/.codex" bash "$SOURCE_ROOT/install.sh"; then
  exit 1
fi
test "$(readlink "$COLLISION_HOME/.claude/skills/research-topic")" = "$COLLISION_HOME/custom-skill"
test ! -e "$COLLISION_HOME/.config/hippocampus/profile.md"
test ! -e "$COLLISION_HOME/.local/share/hippocampus/releases"

BROKEN_HOME="$(mktemp -d)"
mkdir -p "$BROKEN_HOME/.config/hippocampus" "$BROKEN_HOME/knowledge/raw" "$BROKEN_HOME/knowledge/wiki" "$BROKEN_HOME/knowledge/output" "$BROKEN_HOME/knowledge/docs" "$BROKEN_HOME/.claude/skills"
touch "$BROKEN_HOME/knowledge/wiki/hot.md" "$BROKEN_HOME/knowledge/docs/log.md" "$BROKEN_HOME/knowledge/docs/DECISIONS.md"
sed "s|/absolute/path/to/knowledge|$BROKEN_HOME/knowledge|" "$SOURCE_ROOT/profiles/karpathy-wiki.example.md" > "$BROKEN_HOME/.config/hippocampus/profile.md"
ln -s "$BROKEN_HOME/.local/share/hippocampus/releases/0.2.0/skills/research-topic" "$BROKEN_HOME/.claude/skills/research-topic"
if HOME="$BROKEN_HOME" CODEX_HOME="$BROKEN_HOME/.codex" bash "$SOURCE_ROOT/install.sh"; then
  exit 1
fi
test "$(readlink "$BROKEN_HOME/.claude/skills/research-topic")" = "$BROKEN_HOME/.local/share/hippocampus/releases/0.2.0/skills/research-topic"
test ! -e "$BROKEN_HOME/.local/share/hippocampus/current"
test ! -e "$BROKEN_HOME/.local/share/hippocampus/releases"

CURRENT_DIR_HOME="$(mktemp -d)"
mkdir -p "$CURRENT_DIR_HOME/.config/hippocampus" "$CURRENT_DIR_HOME/knowledge/raw" "$CURRENT_DIR_HOME/knowledge/wiki" "$CURRENT_DIR_HOME/knowledge/output" "$CURRENT_DIR_HOME/knowledge/docs" "$CURRENT_DIR_HOME/.claude/skills" "$CURRENT_DIR_HOME/.local/share/hippocampus/current/skills/research-topic"
touch "$CURRENT_DIR_HOME/knowledge/wiki/hot.md" "$CURRENT_DIR_HOME/knowledge/docs/log.md" "$CURRENT_DIR_HOME/knowledge/docs/DECISIONS.md" "$CURRENT_DIR_HOME/.local/share/hippocampus/current/skills/research-topic/SKILL.md"
sed "s|/absolute/path/to/knowledge|$CURRENT_DIR_HOME/knowledge|" "$SOURCE_ROOT/profiles/karpathy-wiki.example.md" > "$CURRENT_DIR_HOME/.config/hippocampus/profile.md"
ln -s "$CURRENT_DIR_HOME/.local/share/hippocampus/current/skills/research-topic" "$CURRENT_DIR_HOME/.claude/skills/research-topic"
if HOME="$CURRENT_DIR_HOME" CODEX_HOME="$CURRENT_DIR_HOME/.codex" bash "$SOURCE_ROOT/install.sh"; then
  exit 1
fi
test -d "$CURRENT_DIR_HOME/.local/share/hippocampus/current"
test ! -e "$CURRENT_DIR_HOME/.codex/skills/research-topic"
test ! -e "$CURRENT_DIR_HOME/.local/share/hippocampus/releases"

RETIRED_HOME="$(mktemp -d)"
mkdir -p "$RETIRED_HOME/.config/hippocampus" "$RETIRED_HOME/knowledge/raw" "$RETIRED_HOME/knowledge/wiki" "$RETIRED_HOME/knowledge/output" "$RETIRED_HOME/knowledge/docs" "$RETIRED_HOME/.claude/skills" "$RETIRED_HOME/.codex/skills" "$RETIRED_HOME/.local/share/hippocampus/releases/0.0.9/skills/retired-skill" "$RETIRED_HOME/.local/share/hippocampus/releases/0.0.9/contracts"
touch "$RETIRED_HOME/knowledge/wiki/hot.md" "$RETIRED_HOME/knowledge/docs/log.md" "$RETIRED_HOME/knowledge/docs/DECISIONS.md"
sed "s|/absolute/path/to/knowledge|$RETIRED_HOME/knowledge|" "$SOURCE_ROOT/profiles/karpathy-wiki.example.md" > "$RETIRED_HOME/.config/hippocampus/profile.md"
printf '%s\n' '---' 'name: retired-skill' 'description: retired fixture' '---' > "$RETIRED_HOME/.local/share/hippocampus/releases/0.0.9/skills/retired-skill/SKILL.md"
printf '# contract\n' > "$RETIRED_HOME/.local/share/hippocampus/releases/0.0.9/contracts/karpathy-wiki.md"
release_manifest "$RETIRED_HOME/.local/share/hippocampus/releases/0.0.9" > "$RETIRED_HOME/.local/share/hippocampus/releases/0.0.9/manifest"
ln -s "$RETIRED_HOME/.local/share/hippocampus/releases/0.0.9" "$RETIRED_HOME/.local/share/hippocampus/current"
ln -s "$RETIRED_HOME/.local/share/hippocampus/current/skills/retired-skill" "$RETIRED_HOME/.claude/skills/retired-skill"
ln -s "$RETIRED_HOME/.local/share/hippocampus/current/skills/retired-skill" "$RETIRED_HOME/.codex/skills/retired-skill"
if HOME="$RETIRED_HOME" CODEX_HOME="$RETIRED_HOME/.codex" bash "$SOURCE_ROOT/install.sh" --verify; then
  exit 1
fi
if HOME="$RETIRED_HOME" CODEX_HOME="$RETIRED_HOME/.codex" bash "$SOURCE_ROOT/install.sh"; then
  exit 1
fi
test "$(readlink "$RETIRED_HOME/.claude/skills/retired-skill")" = "$RETIRED_HOME/.local/share/hippocampus/current/skills/retired-skill"
test "$(readlink "$RETIRED_HOME/.codex/skills/retired-skill")" = "$RETIRED_HOME/.local/share/hippocampus/current/skills/retired-skill"
test "$(readlink "$RETIRED_HOME/.local/share/hippocampus/current")" = "$RETIRED_HOME/.local/share/hippocampus/releases/0.0.9"

PROFILE_HOME="$(mktemp -d)"
mkdir -p "$PROFILE_HOME/.config/hippocampus" "$PROFILE_HOME/knowledge/raw" "$PROFILE_HOME/knowledge/wiki" "$PROFILE_HOME/knowledge/output" "$PROFILE_HOME/knowledge/docs"
touch "$PROFILE_HOME/knowledge/wiki/hot.md" "$PROFILE_HOME/knowledge/docs/log.md" "$PROFILE_HOME/knowledge/docs/DECISIONS.md"
sed "s|/absolute/path/to/knowledge|$PROFILE_HOME/knowledge|" "$ROOT/profiles/karpathy-wiki.example.md" > "$PROFILE_HOME/.config/hippocampus/profile.md"
HOME="$PROFILE_HOME" CODEX_HOME="$PROFILE_HOME/.codex" bash "$SOURCE_ROOT/install.sh"
HOME="$PROFILE_HOME" CODEX_HOME="$PROFILE_HOME/.codex" bash "$SOURCE_ROOT/install.sh" --verify

CONCURRENT_HOME="$(mktemp -d)"
mkdir -p "$CONCURRENT_HOME/.config/hippocampus" "$CONCURRENT_HOME/knowledge/raw" "$CONCURRENT_HOME/knowledge/wiki" "$CONCURRENT_HOME/knowledge/output" "$CONCURRENT_HOME/knowledge/docs"
touch "$CONCURRENT_HOME/knowledge/wiki/hot.md" "$CONCURRENT_HOME/knowledge/docs/log.md" "$CONCURRENT_HOME/knowledge/docs/DECISIONS.md"
sed "s|/absolute/path/to/knowledge|$CONCURRENT_HOME/knowledge|" "$SOURCE_ROOT/profiles/karpathy-wiki.example.md" > "$CONCURRENT_HOME/.config/hippocampus/profile.md"
HOME="$CONCURRENT_HOME" CODEX_HOME="$CONCURRENT_HOME/.codex" bash "$SOURCE_ROOT/install.sh" >"$CONCURRENT_HOME/one.log" 2>&1 &
ONE_PID=$!
HOME="$CONCURRENT_HOME" CODEX_HOME="$CONCURRENT_HOME/.codex" bash "$SOURCE_ROOT/install.sh" >"$CONCURRENT_HOME/two.log" 2>&1 &
TWO_PID=$!
wait "$ONE_PID"
wait "$TWO_PID"
HOME="$CONCURRENT_HOME" CODEX_HOME="$CONCURRENT_HOME/.codex" bash "$SOURCE_ROOT/install.sh" --verify
rm -rf "$CONCURRENT_HOME"

UPGRADE_HOME="$(mktemp -d)"
mkdir -p "$UPGRADE_HOME/.config/hippocampus" "$UPGRADE_HOME/knowledge/raw" "$UPGRADE_HOME/knowledge/wiki" "$UPGRADE_HOME/knowledge/output" "$UPGRADE_HOME/knowledge/docs"
touch "$UPGRADE_HOME/knowledge/wiki/hot.md" "$UPGRADE_HOME/knowledge/docs/log.md" "$UPGRADE_HOME/knowledge/docs/DECISIONS.md"
sed "s|/absolute/path/to/knowledge|$UPGRADE_HOME/knowledge|" "$SOURCE_ROOT/profiles/karpathy-wiki.example.md" > "$UPGRADE_HOME/.config/hippocampus/profile.md"
for skill in "$ROOT"/skills/*; do
  test -f "$skill/SKILL.md" || continue
  name="$(basename "$skill")"
  mkdir -p "$UPGRADE_HOME/.local/share/hippocampus/releases/0.0.9/skills/$name" "$UPGRADE_HOME/.claude/skills" "$UPGRADE_HOME/.codex/skills"
  cp -R "$SOURCE_ROOT/skills/$name/." "$UPGRADE_HOME/.local/share/hippocampus/releases/0.0.9/skills/$name/"
  ln -s "$UPGRADE_HOME/.local/share/hippocampus/releases/0.0.9/skills/$name" "$UPGRADE_HOME/.claude/skills/$name"
  ln -s "$UPGRADE_HOME/.local/share/hippocampus/releases/0.0.9/skills/$name" "$UPGRADE_HOME/.codex/skills/$name"
done
cp -R "$SOURCE_ROOT/contracts" "$UPGRADE_HOME/.local/share/hippocampus/releases/0.0.9/contracts"
release_manifest "$UPGRADE_HOME/.local/share/hippocampus/releases/0.0.9" > "$UPGRADE_HOME/.local/share/hippocampus/releases/0.0.9/manifest"
HOME="$UPGRADE_HOME" CODEX_HOME="$UPGRADE_HOME/.codex" bash "$SOURCE_ROOT/install.sh"
for skill in "$ROOT"/skills/*; do
  test -f "$skill/SKILL.md" || continue
  name="$(basename "$skill")"
  test "$(readlink "$UPGRADE_HOME/.claude/skills/$name")" = "$UPGRADE_HOME/.local/share/hippocampus/current/skills/$name"
  test "$(readlink "$UPGRADE_HOME/.codex/skills/$name")" = "$UPGRADE_HOME/.local/share/hippocampus/current/skills/$name"
done
test "$(readlink "$UPGRADE_HOME/.local/share/hippocampus/current")" = "$UPGRADE_HOME/.local/share/hippocampus/releases/$VERSION"

TAMPER_HOME="$(mktemp -d)"
mkdir -p "$TAMPER_HOME/.config/hippocampus" "$TAMPER_HOME/knowledge/raw" "$TAMPER_HOME/knowledge/wiki" "$TAMPER_HOME/knowledge/output" "$TAMPER_HOME/knowledge/docs"
touch "$TAMPER_HOME/knowledge/wiki/hot.md" "$TAMPER_HOME/knowledge/docs/log.md" "$TAMPER_HOME/knowledge/docs/DECISIONS.md"
sed "s|/absolute/path/to/knowledge|$TAMPER_HOME/knowledge|" "$SOURCE_ROOT/profiles/karpathy-wiki.example.md" > "$TAMPER_HOME/.config/hippocampus/profile.md"
HOME="$TAMPER_HOME" CODEX_HOME="$TAMPER_HOME/.codex" bash "$SOURCE_ROOT/install.sh"
printf x >> "$TAMPER_HOME/.local/share/hippocampus/releases/$VERSION/skills/research-topic/SKILL.md"
if HOME="$TAMPER_HOME" CODEX_HOME="$TAMPER_HOME/.codex" bash "$SOURCE_ROOT/install.sh" --verify; then
  exit 1
fi
rm -rf "$TAMPER_HOME"

# F2: no python3 on PATH must refuse before any filesystem changes, naming the tool.
NOPY_HOME="$(mktemp -d)"
NOPY_BIN="$NOPY_HOME/bin"
mkdir -p "$NOPY_BIN" "$NOPY_HOME/home"
ln -s "$(command -v bash)" "$NOPY_BIN/bash"
NOPY_STDERR="$NOPY_HOME/stderr.log"
if PATH="$NOPY_BIN" HOME="$NOPY_HOME/home" CODEX_HOME="$NOPY_HOME/home/.codex" bash "$SOURCE_ROOT/install.sh" 2>"$NOPY_STDERR"; then
  exit 1
fi
grep -q python3 "$NOPY_STDERR"
test ! -e "$NOPY_HOME/home/.local/share/hippocampus/releases"

# F3: --verify must name a missing client skill link instead of failing silently.
MISSINGLINK_HOME="$(mktemp -d)"
mkdir -p "$MISSINGLINK_HOME/.config/hippocampus" "$MISSINGLINK_HOME/knowledge/raw" "$MISSINGLINK_HOME/knowledge/wiki" "$MISSINGLINK_HOME/knowledge/output" "$MISSINGLINK_HOME/knowledge/docs"
touch "$MISSINGLINK_HOME/knowledge/wiki/hot.md" "$MISSINGLINK_HOME/knowledge/docs/log.md" "$MISSINGLINK_HOME/knowledge/docs/DECISIONS.md"
sed "s|/absolute/path/to/knowledge|$MISSINGLINK_HOME/knowledge|" "$SOURCE_ROOT/profiles/karpathy-wiki.example.md" > "$MISSINGLINK_HOME/.config/hippocampus/profile.md"
HOME="$MISSINGLINK_HOME" CODEX_HOME="$MISSINGLINK_HOME/.codex" bash "$SOURCE_ROOT/install.sh"
MISSINGLINK_PATH="$MISSINGLINK_HOME/.claude/skills/research-quick"
rm -f "$MISSINGLINK_PATH"
MISSINGLINK_STDERR="$MISSINGLINK_HOME/stderr.log"
if HOME="$MISSINGLINK_HOME" CODEX_HOME="$MISSINGLINK_HOME/.codex" bash "$SOURCE_ROOT/install.sh" --verify 2>"$MISSINGLINK_STDERR"; then
  exit 1
fi
grep -Fq "$MISSINGLINK_PATH" "$MISSINGLINK_STDERR"

# F7: refusal messages must carry a remedy.
REMEDY_HOME="$(mktemp -d)"
mkdir -p "$REMEDY_HOME/.claude/skills/research-quick"
REMEDY_STDERR="$REMEDY_HOME/stderr.log"
if HOME="$REMEDY_HOME" CODEX_HOME="$REMEDY_HOME/.codex" bash "$SOURCE_ROOT/install.sh" 2>"$REMEDY_STDERR"; then
  exit 1
fi
grep -Fq "collision: $REMEDY_HOME/.claude/skills/research-quick" "$REMEDY_STDERR"
grep -Fq "move or remove it and re-run install.sh" "$REMEDY_STDERR"

# F1: Finder droppings in the source tree must not change the manifest.
DSSTORE_HOME="$(mktemp -d)"
DSSTORE_SOURCE="$DSSTORE_HOME/source"
cp -R "$SOURCE_ROOT" "$DSSTORE_SOURCE"
HOME="$DSSTORE_HOME" CODEX_HOME="$DSSTORE_HOME/.codex" bash "$DSSTORE_SOURCE/install.sh"
DSSTORE_MANIFEST_BEFORE="$(cat "$DSSTORE_HOME/.local/share/hippocampus/releases/$VERSION/manifest")"
touch "$DSSTORE_SOURCE/skills/.DS_Store"
touch "$DSSTORE_SOURCE/skills/research-quick/.Ulysses-Group.plist"
HOME="$DSSTORE_HOME" CODEX_HOME="$DSSTORE_HOME/.codex" bash "$DSSTORE_SOURCE/install.sh"
DSSTORE_MANIFEST_AFTER="$(cat "$DSSTORE_HOME/.local/share/hippocampus/releases/$VERSION/manifest")"
test "$DSSTORE_MANIFEST_BEFORE" = "$DSSTORE_MANIFEST_AFTER"
rm -rf "$DSSTORE_HOME"

MODIFIED_HOME="$(mktemp -d)"
MODIFIED_SOURCE="$MODIFIED_HOME/source"
cp -R "$SOURCE_ROOT" "$MODIFIED_SOURCE"
HOME="$MODIFIED_HOME" CODEX_HOME="$MODIFIED_HOME/.codex" bash "$MODIFIED_SOURCE/install.sh"
printf x >> "$MODIFIED_SOURCE/skills/research-topic/SKILL.md"
if HOME="$MODIFIED_HOME" CODEX_HOME="$MODIFIED_HOME/.codex" bash "$MODIFIED_SOURCE/install.sh" 2>"$MODIFIED_HOME/err.log"; then
  exit 1
fi
grep -Fq "skills/research-topic/SKILL.md" "$MODIFIED_HOME/err.log"
rm -rf "$MODIFIED_HOME"

MIGRATE_HOME="$(mktemp -d)"
MIGRATE_SOURCE="$MIGRATE_HOME/source"
cp -R "$SOURCE_ROOT" "$MIGRATE_SOURCE"
mkdir -p "$MIGRATE_HOME/.config/hippocampus" "$MIGRATE_HOME/knowledge/raw" "$MIGRATE_HOME/knowledge/wiki" "$MIGRATE_HOME/knowledge/output" "$MIGRATE_HOME/knowledge/docs"
touch "$MIGRATE_HOME/knowledge/wiki/hot.md" "$MIGRATE_HOME/knowledge/docs/log.md" "$MIGRATE_HOME/knowledge/docs/DECISIONS.md"
sed "s|/absolute/path/to/knowledge|$MIGRATE_HOME/knowledge|" "$MIGRATE_SOURCE/profiles/karpathy-wiki.example.md" > "$MIGRATE_HOME/.config/hippocampus/profile.md"
# Build a release exactly as main's (pre-#6) install.sh would have produced
# from a tree with .DS_Store present: the copied tree kept it (no tar
# exclusion) and the stored manifest was computed over it (no find
# exclusion). MIGRATE_SOURCE itself has since been cleaned (no .DS_Store) --
# the most likely real upgrade path (Finder cleanup, `git clean`, a fresh
# clone), not an edge case, and the harder of the two: it requires content
# equivalence to be judged by what's actually on disk now, not by replaying
# the legacy exclusion rules against a tree that no longer has the junk.
MIGRATE_RELEASE="$MIGRATE_HOME/.local/share/hippocampus/releases/$VERSION"
mkdir -p "$MIGRATE_RELEASE" "$MIGRATE_HOME/.claude/skills" "$MIGRATE_HOME/.codex/skills"
cp -R "$MIGRATE_SOURCE/skills" "$MIGRATE_RELEASE/skills"
touch "$MIGRATE_RELEASE/skills/.DS_Store"
cp -R "$MIGRATE_SOURCE/contracts" "$MIGRATE_RELEASE/contracts"
cp -R "$MIGRATE_SOURCE/profiles" "$MIGRATE_RELEASE/profiles"
mkdir -p "$MIGRATE_RELEASE/scripts"
cp -p "$MIGRATE_SOURCE/scripts/validate_profile.py" "$MIGRATE_RELEASE/scripts/validate_profile.py"
release_manifest_legacy "$MIGRATE_RELEASE" > "$MIGRATE_RELEASE/manifest"
MIGRATE_LEGACY_MANIFEST="$(cat "$MIGRATE_RELEASE/manifest")"
ln -s "$MIGRATE_RELEASE" "$MIGRATE_HOME/.local/share/hippocampus/current"
for skill in "$ROOT"/skills/*; do
  test -f "$skill/SKILL.md" || continue
  name="$(basename "$skill")"
  ln -s "$MIGRATE_HOME/.local/share/hippocampus/current/skills/$name" "$MIGRATE_HOME/.claude/skills/$name"
  ln -s "$MIGRATE_HOME/.local/share/hippocampus/current/skills/$name" "$MIGRATE_HOME/.codex/skills/$name"
done
# --verify is documented as a standalone check, so it must accept a legacy
# install before any install.sh run has had a chance to heal the manifest.
HOME="$MIGRATE_HOME" CODEX_HOME="$MIGRATE_HOME/.codex" bash "$MIGRATE_SOURCE/install.sh" --verify
test "$(cat "$MIGRATE_RELEASE/manifest")" = "$MIGRATE_LEGACY_MANIFEST"
HOME="$MIGRATE_HOME" CODEX_HOME="$MIGRATE_HOME/.codex" bash "$MIGRATE_SOURCE/install.sh" 2>"$MIGRATE_HOME/err.log"
grep -Fq "migrated release manifest: $MIGRATE_RELEASE" "$MIGRATE_HOME/err.log"
test "$(cat "$MIGRATE_RELEASE/manifest")" != "$MIGRATE_LEGACY_MANIFEST"
test -L "$MIGRATE_HOME/.local/share/hippocampus/current"
test -d "$(readlink "$MIGRATE_HOME/.local/share/hippocampus/current")"
HOME="$MIGRATE_HOME" CODEX_HOME="$MIGRATE_HOME/.codex" bash "$MIGRATE_SOURCE/install.sh" --verify
rm -rf "$MIGRATE_HOME"

# The other legacy upgrade path: the source tree still carries the droppings.
# Both must migrate, because the legacy hash is computed over the release
# directory on disk, which kept whatever the old tar copied into it.
DIRTY_HOME="$(mktemp -d)"
DIRTY_SOURCE="$DIRTY_HOME/source"
cp -R "$SOURCE_ROOT" "$DIRTY_SOURCE"
touch "$DIRTY_SOURCE/skills/.DS_Store" "$DIRTY_SOURCE/skills/research-quick/.Ulysses-Group.plist"
mkdir -p "$DIRTY_HOME/.config/hippocampus" "$DIRTY_HOME/knowledge/raw" "$DIRTY_HOME/knowledge/wiki" "$DIRTY_HOME/knowledge/output" "$DIRTY_HOME/knowledge/docs"
touch "$DIRTY_HOME/knowledge/wiki/hot.md" "$DIRTY_HOME/knowledge/docs/log.md" "$DIRTY_HOME/knowledge/docs/DECISIONS.md"
sed "s|/absolute/path/to/knowledge|$DIRTY_HOME/knowledge|" "$DIRTY_SOURCE/profiles/karpathy-wiki.example.md" > "$DIRTY_HOME/.config/hippocampus/profile.md"
DIRTY_RELEASE="$DIRTY_HOME/.local/share/hippocampus/releases/$VERSION"
mkdir -p "$DIRTY_RELEASE/scripts" "$DIRTY_HOME/.claude/skills" "$DIRTY_HOME/.codex/skills"
# The pre-#6 tar excluded only .build, so the release kept both droppings.
cp -R "$DIRTY_SOURCE/skills" "$DIRTY_RELEASE/skills"
cp -R "$DIRTY_SOURCE/contracts" "$DIRTY_RELEASE/contracts"
cp -R "$DIRTY_SOURCE/profiles" "$DIRTY_RELEASE/profiles"
cp -p "$DIRTY_SOURCE/scripts/validate_profile.py" "$DIRTY_RELEASE/scripts/validate_profile.py"
release_manifest_legacy "$DIRTY_RELEASE" > "$DIRTY_RELEASE/manifest"
DIRTY_LEGACY_MANIFEST="$(cat "$DIRTY_RELEASE/manifest")"
ln -s "$DIRTY_RELEASE" "$DIRTY_HOME/.local/share/hippocampus/current"
for skill in "$ROOT"/skills/*; do
  test -f "$skill/SKILL.md" || continue
  name="$(basename "$skill")"
  ln -s "$DIRTY_HOME/.local/share/hippocampus/current/skills/$name" "$DIRTY_HOME/.claude/skills/$name"
  ln -s "$DIRTY_HOME/.local/share/hippocampus/current/skills/$name" "$DIRTY_HOME/.codex/skills/$name"
done
HOME="$DIRTY_HOME" CODEX_HOME="$DIRTY_HOME/.codex" bash "$DIRTY_SOURCE/install.sh" --verify
HOME="$DIRTY_HOME" CODEX_HOME="$DIRTY_HOME/.codex" bash "$DIRTY_SOURCE/install.sh"
test "$(cat "$DIRTY_RELEASE/manifest")" != "$DIRTY_LEGACY_MANIFEST"
HOME="$DIRTY_HOME" CODEX_HOME="$DIRTY_HOME/.codex" bash "$DIRTY_SOURCE/install.sh" --verify
rm -rf "$DIRTY_HOME"

# A stored manifest that is neither the current nor the legacy hash must be
# refused even when the release content matches this checkout. There is no
# current pointer and no client link, so the run reaches the same-version
# branch rather than being stopped by the current-pointer check first.
JUNK_HOME="$(mktemp -d)"
JUNK_SOURCE="$JUNK_HOME/source"
cp -R "$SOURCE_ROOT" "$JUNK_SOURCE"
JUNK_RELEASE="$JUNK_HOME/.local/share/hippocampus/releases/$VERSION"
mkdir -p "$JUNK_RELEASE/scripts"
cp -R "$JUNK_SOURCE/skills" "$JUNK_RELEASE/skills"
cp -R "$JUNK_SOURCE/contracts" "$JUNK_RELEASE/contracts"
cp -R "$JUNK_SOURCE/profiles" "$JUNK_RELEASE/profiles"
cp -p "$JUNK_SOURCE/scripts/validate_profile.py" "$JUNK_RELEASE/scripts/validate_profile.py"
test "$(release_manifest "$JUNK_RELEASE")" = "$(release_manifest "$JUNK_SOURCE")"
printf 'ATTACKER:0\n' > "$JUNK_RELEASE/manifest"
if HOME="$JUNK_HOME" CODEX_HOME="$JUNK_HOME/.codex" bash "$JUNK_SOURCE/install.sh" 2>"$JUNK_HOME/err.log"; then
  exit 1
fi
grep -Fq "release manifest mismatch: $VERSION" "$JUNK_HOME/err.log"
grep -Fq "move or remove $JUNK_RELEASE and re-run install.sh" "$JUNK_HOME/err.log"
test "$(cat "$JUNK_RELEASE/manifest")" = "ATTACKER:0"
rm -rf "$JUNK_HOME"

# Rename migration: use the actual v0.7.0 source tree, not a synthetic legacy
# fixture. It must preserve the profile bytes and legacy release tree while
# atomically moving both clients to the new package root.
RENAME_HOME="$(mktemp -d)"
RENAME_TREE="$RENAME_HOME/v070"
git -C "$ROOT" archive v0.7.0 | tar -x -C "$RENAME_HOME"
mkdir -p "$RENAME_HOME/knowledge/raw" "$RENAME_HOME/knowledge/wiki" "$RENAME_HOME/knowledge/output" "$RENAME_HOME/knowledge/docs" "$RENAME_HOME/.config/research-tools"
touch "$RENAME_HOME/knowledge/wiki/hot.md" "$RENAME_HOME/knowledge/docs/log.md" "$RENAME_HOME/knowledge/docs/DECISIONS.md"
sed "s|/absolute/path/to/knowledge|$RENAME_HOME/knowledge|" "$RENAME_HOME/profiles/karpathy-wiki.example.md" > "$RENAME_HOME/.config/research-tools/profile.md"
PROFILE_SUM="$(shasum -a 256 "$RENAME_HOME/.config/research-tools/profile.md")"
HOME="$RENAME_HOME" CODEX_HOME="$RENAME_HOME/.codex" bash "$RENAME_HOME/install.sh"
HOME="$RENAME_HOME" CODEX_HOME="$RENAME_HOME/.codex" bash "$ROOT/install.sh"
cmp "$RENAME_HOME/.config/research-tools/profile.md" "$RENAME_HOME/.config/hippocampus/profile.md"
test "$(shasum -a 256 "$RENAME_HOME/.config/research-tools/profile.md")" = "$PROFILE_SUM"
test -d "$RENAME_HOME/.local/share/research-tools/releases/0.7.0"
HOME="$RENAME_HOME" CODEX_HOME="$RENAME_HOME/.codex" bash "$ROOT/install.sh" --verify
# A completed migration makes the canonical profile authoritative; later setup
# changes must not be compared to the preserved legacy copy on every install.
printf '\nlocal policy update\n' >> "$RENAME_HOME/.config/hippocampus/profile.md"
HOME="$RENAME_HOME" CODEX_HOME="$RENAME_HOME/.codex" bash "$ROOT/install.sh"
grep -Fq 'local policy update' "$RENAME_HOME/.config/hippocampus/profile.md"
rm -rf "$RENAME_HOME"

# First-migration profile ambiguity and nonregular profile targets stop before
# a Hippocampus release or client-link changes are made.
PROFILE_CONFLICT_HOME="$(mktemp -d)"
mkdir -p "$PROFILE_CONFLICT_HOME/.config/research-tools" "$PROFILE_CONFLICT_HOME/.config/hippocampus"
printf 'legacy profile\n' > "$PROFILE_CONFLICT_HOME/.config/research-tools/profile.md"
printf 'canonical profile\n' > "$PROFILE_CONFLICT_HOME/.config/hippocampus/profile.md"
if HOME="$PROFILE_CONFLICT_HOME" CODEX_HOME="$PROFILE_CONFLICT_HOME/.codex" bash "$ROOT/install.sh"; then
  exit 1
fi
test ! -e "$PROFILE_CONFLICT_HOME/.local/share/hippocampus/releases"
rm -rf "$PROFILE_CONFLICT_HOME"

NONREGULAR_PROFILE_HOME="$(mktemp -d)"
mkdir -p "$NONREGULAR_PROFILE_HOME/.config/hippocampus/profile.md"
if HOME="$NONREGULAR_PROFILE_HOME" CODEX_HOME="$NONREGULAR_PROFILE_HOME/.codex" bash "$ROOT/install.sh"; then
  exit 1
fi
test ! -e "$NONREGULAR_PROFILE_HOME/.local/share/hippocampus/releases"
rm -rf "$NONREGULAR_PROFILE_HOME"

# An interruption after package links point through a missing new `current`
# pointer is safe to rerun; the valid release tree remains and activation
# completes on the retry.
INTERRUPTED_HOME="$(mktemp -d)"
mkdir -p "$INTERRUPTED_HOME/knowledge/raw" "$INTERRUPTED_HOME/knowledge/wiki" "$INTERRUPTED_HOME/knowledge/output" "$INTERRUPTED_HOME/knowledge/docs" "$INTERRUPTED_HOME/.config/hippocampus"
touch "$INTERRUPTED_HOME/knowledge/wiki/hot.md" "$INTERRUPTED_HOME/knowledge/docs/log.md" "$INTERRUPTED_HOME/knowledge/docs/DECISIONS.md"
sed "s|/absolute/path/to/knowledge|$INTERRUPTED_HOME/knowledge|" "$ROOT/profiles/karpathy-wiki.example.md" > "$INTERRUPTED_HOME/.config/hippocampus/profile.md"
HOME="$INTERRUPTED_HOME" CODEX_HOME="$INTERRUPTED_HOME/.codex" bash "$ROOT/install.sh"
rm "$INTERRUPTED_HOME/.local/share/hippocampus/current"
HOME="$INTERRUPTED_HOME" CODEX_HOME="$INTERRUPTED_HOME/.codex" bash "$ROOT/install.sh"
HOME="$INTERRUPTED_HOME" CODEX_HOME="$INTERRUPTED_HOME/.codex" bash "$ROOT/install.sh" --verify
rm -rf "$INTERRUPTED_HOME"
