#!/bin/bash
set -euo pipefail

if ! command -v python3 >/dev/null 2>&1; then
  echo "install.sh: python3 is required but was not found on PATH" >&2
  exit 1
fi

ROOT="$(cd "$(dirname "$0")" && pwd)"
VERSION="$(tr -d '[:space:]' < "$ROOT/VERSION")"
PACKAGE="hippocampus"
LEGACY_PACKAGE="research-tools"
SHARE_ROOT="$HOME/.local/share/$PACKAGE"
RELEASE_ROOT="$SHARE_ROOT/releases"
CURRENT_LINK="$SHARE_ROOT/current"
PROFILE="$HOME/.config/$PACKAGE/profile.md"
LOCK_DIR="$HOME/.config/$PACKAGE/.install-lock"
LEGACY_SHARE_ROOT="$HOME/.local/share/$LEGACY_PACKAGE"
LEGACY_RELEASE_ROOT="$LEGACY_SHARE_ROOT/releases"
LEGACY_CURRENT_LINK="$LEGACY_SHARE_ROOT/current"
LEGACY_PROFILE="$HOME/.config/$LEGACY_PACKAGE/profile.md"
MIGRATION_MARKER="$SHARE_ROOT/migrated-from-research-tools"
RELEASE_DIR="$RELEASE_ROOT/$VERSION"
CLAUDE_DIR="$HOME/.claude/skills"
CODEX_DIR="${CODEX_HOME:-$HOME/.codex}/skills"

manifest_listing() {
  manifest_root="${1:-$ROOT}"
  (
    cd "$manifest_root"
    manifest_paths="skills contracts"
    [ ! -d profiles ] || manifest_paths="$manifest_paths profiles"
    [ ! -f scripts/validate_profile.py ] || manifest_paths="$manifest_paths scripts/validate_profile.py"
    find $manifest_paths -type f -not -path '*/.build/*' -not -path '*/.Ulysses-*/*' -not -name '.DS_Store' -not -name '.Ulysses-*' -exec cksum {} \; | LC_ALL=C sort
  )
}
manifest_hash() { manifest_listing "${1:-$ROOT}" | cksum | awk '{print $1 ":" $2}'; }
manifest_hash_legacy() {
  manifest_root="${1:-$ROOT}"
  (
    cd "$manifest_root"
    manifest_paths="skills contracts"
    [ ! -d profiles ] || manifest_paths="$manifest_paths profiles"
    [ ! -f scripts/validate_profile.py ] || manifest_paths="$manifest_paths scripts/validate_profile.py"
    find $manifest_paths -type f -not -path '*/.build/*' -exec cksum {} \; | LC_ALL=C sort | cksum | awk '{print $1 ":" $2}'
  )
}
SOURCE_HASH="$(manifest_hash)"

copy_release_tree() {
  source="$1" destination="$2"
  mkdir -p "$destination"
  (cd "$source" && tar --exclude='.build' --exclude='.DS_Store' --exclude='.Ulysses-*' -cf - .) | (cd "$destination" && tar -xf -)
}

valid_release_at() {
  release="$1" expected_root="$2"
  [ "$(dirname "$release")" = "$expected_root" ] || return 1
  [ -d "$release" ] && [ -f "$release/manifest" ] || return 1
  stored="$(cat "$release/manifest")"
  [ "$(manifest_hash "$release")" = "$stored" ] || [ "$(manifest_hash_legacy "$release")" = "$stored" ]
}
valid_release() { valid_release_at "$1" "$RELEASE_ROOT"; }
valid_legacy_release() { valid_release_at "$1" "$LEGACY_RELEASE_ROOT"; }

is_package_link() {
  target="$1" skill="$2"
  [ -L "$target" ] || return 1
  case "$(readlink "$target")" in
    "$RELEASE_ROOT"/*/skills/"$skill"|"$CURRENT_LINK"/skills/"$skill") return 0 ;;
    *) return 1 ;;
  esac
}
is_legacy_package_link() {
  target="$1" skill="$2"
  [ -L "$target" ] || return 1
  case "$(readlink "$target")" in
    "$LEGACY_RELEASE_ROOT"/*/skills/"$skill"|"$LEGACY_CURRENT_LINK"/skills/"$skill") return 0 ;;
    *) return 1 ;;
  esac
}

replace_link() {
  destination="$1" source="$2" expected="$3"
  python3 - "$destination" "$source" "$expected" "$PACKAGE" <<'PY'
import os, sys
destination, source, expected, package = sys.argv[1:]
if os.path.lexists(destination):
    if not os.path.islink(destination) or os.readlink(destination) != expected:
        raise SystemExit(f"collision changed during install: {destination}")
elif expected != "__absent__":
    raise SystemExit(f"link disappeared during install: {destination}")
temporary = f"{destination}.{package}.{os.getpid()}"
try: os.unlink(temporary)
except FileNotFoundError: pass
os.symlink(source, temporary)
os.replace(temporary, destination)
PY
}
set_current_release() { replace_link "$CURRENT_LINK" "$1" "$2"; }

CURRENT_RELEASE=""
validate_current_pointer() {
  if [ ! -e "$CURRENT_LINK" ] && [ ! -L "$CURRENT_LINK" ]; then return 0; fi
  if [ ! -L "$CURRENT_LINK" ]; then echo "collision: current pointer is not a symlink" >&2; return 1; fi
  CURRENT_RELEASE="$(readlink "$CURRENT_LINK")"
  valid_release "$CURRENT_RELEASE" || { echo "collision: current pointer is not a valid Hippocampus release" >&2; return 1; }
}
validate_legacy_current_pointer() {
  if [ ! -e "$LEGACY_CURRENT_LINK" ] && [ ! -L "$LEGACY_CURRENT_LINK" ]; then return 0; fi
  if [ ! -L "$LEGACY_CURRENT_LINK" ]; then echo "collision: legacy current pointer is not a symlink (move or repair it before migrating)" >&2; return 1; fi
  legacy_current="$(readlink "$LEGACY_CURRENT_LINK")"
  valid_legacy_release "$legacy_current" || { echo "collision: legacy current pointer is not a valid research-tools release (restore it or remove the broken install before migrating)" >&2; return 1; }
}

validate_profile() {
  if [ ! -f "$PROFILE" ]; then echo "profile missing: run the hippocampus-set-up skill after installing" >&2; return 1; fi
  validator="$ROOT/scripts/validate_profile.py"
  [ ! -f "$CURRENT_LINK/scripts/validate_profile.py" ] || validator="$CURRENT_LINK/scripts/validate_profile.py"
  python3 "$validator" "$PROFILE" >/dev/null
}

LOCK_HELD=0
release_lock() { if [ "$LOCK_HELD" = "1" ]; then rm -f "$LOCK_DIR/pid"; rmdir "$LOCK_DIR" 2>/dev/null || true; LOCK_HELD=0; fi; }
interrupted() { release_lock; trap - EXIT HUP INT TERM; exit "$1"; }
acquire_lock() {
  attempts=0
  while ! mkdir "$LOCK_DIR" 2>/dev/null; do
    if [ -f "$LOCK_DIR/pid" ]; then
      owner="$(cat "$LOCK_DIR/pid" 2>/dev/null || true)"
      if [ -n "$owner" ] && ! kill -0 "$owner" 2>/dev/null; then rm -rf "$LOCK_DIR"; continue; fi
    fi
    attempts=$((attempts + 1)); [ "$attempts" -lt 30 ] || { echo "install lock busy: $LOCK_DIR" >&2; return 1; }
    sleep 1
  done
  printf '%s\n' "$$" > "$LOCK_DIR/pid"; LOCK_HELD=1
  trap release_lock EXIT; trap 'interrupted 129' HUP; trap 'interrupted 130' INT; trap 'interrupted 143' TERM
}
verify_check() { what="$1" path="$2"; shift 2; "$@" || { echo "verify failed: $what $path" >&2; exit 1; }; }
for_each_skill() { for name in "$ROOT"/skills/*; do [ -f "$name/SKILL.md" ] && printf '%s\n' "$(basename "$name")"; done; }

reject_retired_links() {
  for client_dir in "$CLAUDE_DIR" "$CODEX_DIR"; do
    [ -d "$client_dir" ] || continue
    for target in "$client_dir"/*; do
      [ -L "$target" ] || continue
      skill="$(basename "$target")"
      if { is_package_link "$target" "$skill" || is_legacy_package_link "$target" "$skill"; } && [ ! -f "$ROOT/skills/$skill/SKILL.md" ]; then
        echo "retired package skill: $target (move or remove it and re-run install.sh)" >&2; return 1
      fi
    done
  done
}
prepare_profile_migration() {
  if { [ -e "$PROFILE" ] || [ -L "$PROFILE" ]; } && [ ! -f "$PROFILE" -o -L "$PROFILE" ]; then
    echo "profile collision: $PROFILE is not a regular file (move or repair it before migrating)" >&2; return 1
  fi
  if { [ -e "$LEGACY_PROFILE" ] || [ -L "$LEGACY_PROFILE" ]; } && [ ! -f "$LEGACY_PROFILE" -o -L "$LEGACY_PROFILE" ]; then
    echo "profile collision: $LEGACY_PROFILE is not a regular file (move or repair it before migrating)" >&2; return 1
  fi
  if [ ! -f "$MIGRATION_MARKER" ] && [ -f "$LEGACY_PROFILE" ] && [ -f "$PROFILE" ] && ! cmp -s "$LEGACY_PROFILE" "$PROFILE"; then
    echo "profile collision: $PROFILE differs from $LEGACY_PROFILE (compare them, keep the intended profile, then re-run install.sh)" >&2; return 1
  fi
}
migrate_profile() {
  [ -f "$LEGACY_PROFILE" ] || return 0
  [ -f "$PROFILE" ] && return 0
  mkdir -p "$(dirname "$PROFILE")"
  temporary="$PROFILE.$PACKAGE.$$.tmp"; cp -p "$LEGACY_PROFILE" "$temporary"; mv "$temporary" "$PROFILE"
  echo "migrated profile: $PROFILE" >&2
}
record_profile_migration() {
  [ -f "$LEGACY_PROFILE" ] || return 0
  [ -f "$MIGRATION_MARKER" ] && return 0
  temporary="$MIGRATION_MARKER.$PACKAGE.$$.tmp"
  printf '%s\n' "$(shasum -a 256 "$LEGACY_PROFILE" | awk '{print $1}')" > "$temporary"
  mv "$temporary" "$MIGRATION_MARKER"
}

if [ "${1:-}" = "--verify" ]; then
  reject_retired_links
  verify_check "current pointer" "$CURRENT_LINK" test -L "$CURRENT_LINK"
  verify_check "current manifest" "$CURRENT_LINK/manifest" test -f "$CURRENT_LINK/manifest"
  verify_check "current manifest hash" "$CURRENT_LINK" valid_release "$(readlink "$CURRENT_LINK")"
  verify_check "example profile" "$CURRENT_LINK/profiles/karpathy-wiki.example.md" test -f "$CURRENT_LINK/profiles/karpathy-wiki.example.md"
  verify_check "profile validator" "$CURRENT_LINK/scripts/validate_profile.py" test -f "$CURRENT_LINK/scripts/validate_profile.py"
  for skill in $(for_each_skill); do
    verify_check "claude skill link" "$CLAUDE_DIR/$skill" test -L "$CLAUDE_DIR/$skill"
    verify_check "claude skill target" "$CLAUDE_DIR/$skill" test "$(readlink "$CLAUDE_DIR/$skill")" = "$CURRENT_LINK/skills/$skill"
    verify_check "codex skill link" "$CODEX_DIR/$skill" test -L "$CODEX_DIR/$skill"
    verify_check "codex skill target" "$CODEX_DIR/$skill" test "$(readlink "$CODEX_DIR/$skill")" = "$CURRENT_LINK/skills/$skill"
  done
  verify_check "wiki contract" "$CURRENT_LINK/contracts/karpathy-wiki.md" test -f "$CURRENT_LINK/contracts/karpathy-wiki.md"
  validate_profile; exit 0
fi

mkdir -p "$(dirname "$LOCK_DIR")"; acquire_lock; validate_current_pointer; validate_legacy_current_pointer
prepare_profile_migration; reject_retired_links

# Check every client target before mutating profile, release pointer, or links.
for skill in $(for_each_skill); do
  for target in "$CLAUDE_DIR/$skill" "$CODEX_DIR/$skill"; do
    if [ -e "$target" ] || [ -L "$target" ]; then
      if [ -L "$target" ] && [ "$(readlink "$target")" = "$CURRENT_LINK/skills/$skill" ]; then continue; fi
      if is_package_link "$target" "$skill"; then
        candidate="$(readlink "$target")"
        case "$candidate" in "$CURRENT_LINK"/*) candidate="$CURRENT_RELEASE";; *) candidate="${candidate%/skills/$skill}";; esac
        valid_release "$candidate" || { echo "collision: invalid Hippocampus package link $target" >&2; exit 1; }; continue
      fi
      if is_legacy_package_link "$target" "$skill"; then
        candidate="$(readlink "$target")"
        case "$candidate" in "$LEGACY_CURRENT_LINK"/*) candidate="$(readlink "$LEGACY_CURRENT_LINK")";; *) candidate="${candidate%/skills/$skill}";; esac
        valid_legacy_release "$candidate" || { echo "collision: broken legacy package link $target (restore it or remove it before migrating)" >&2; exit 1; }; continue
      fi
      echo "collision: $target (move or remove it and re-run install.sh)" >&2; exit 1
    fi
  done
done

mkdir -p "$CLAUDE_DIR" "$CODEX_DIR" "$RELEASE_ROOT"
TEMP_RELEASE="$RELEASE_ROOT/.$VERSION.$$"; rm -rf "$TEMP_RELEASE"; mkdir -p "$TEMP_RELEASE"
copy_release_tree "$ROOT/skills" "$TEMP_RELEASE/skills"; copy_release_tree "$ROOT/contracts" "$TEMP_RELEASE/contracts"; copy_release_tree "$ROOT/profiles" "$TEMP_RELEASE/profiles"
mkdir -p "$TEMP_RELEASE/scripts"; cp -p "$ROOT/scripts/validate_profile.py" "$TEMP_RELEASE/scripts/validate_profile.py"
if [ ! -d "$RELEASE_DIR" ]; then
  printf '%s\n' "$SOURCE_HASH" > "$TEMP_RELEASE/manifest"; mv "$TEMP_RELEASE" "$RELEASE_DIR"
else
  existing_manifest=""; [ ! -f "$RELEASE_DIR/manifest" ] || existing_manifest="$(cat "$RELEASE_DIR/manifest")"
  if [ "$(manifest_hash "$RELEASE_DIR")" = "$SOURCE_HASH" ] && [ "$existing_manifest" = "$SOURCE_HASH" ]; then rm -rf "$TEMP_RELEASE"
  elif [ "$(manifest_hash "$RELEASE_DIR")" = "$SOURCE_HASH" ] && [ "$existing_manifest" = "$(manifest_hash_legacy "$RELEASE_DIR")" ]; then
    printf '%s\n' "$SOURCE_HASH" > "$RELEASE_DIR/manifest"
    echo "migrated release manifest: $RELEASE_DIR" >&2
    rm -rf "$TEMP_RELEASE"
  else
    echo "release version collision: $VERSION has different content (move or remove $RELEASE_DIR and re-run install.sh)" >&2
    diff <(manifest_listing "$ROOT") <(manifest_listing "$RELEASE_DIR") >&2 || true
    rm -rf "$TEMP_RELEASE"
    exit 1
  fi
fi

migrate_profile
for skill in $(for_each_skill); do
  for target in "$CLAUDE_DIR/$skill" "$CODEX_DIR/$skill"; do
    actual="__absent__"; [ ! -L "$target" ] || actual="$(readlink "$target")"
    [ "$actual" = "$CURRENT_LINK/skills/$skill" ] || replace_link "$target" "$CURRENT_LINK/skills/$skill" "$actual"
  done
done
current_expected="__absent__"; [ ! -L "$CURRENT_LINK" ] || current_expected="$(readlink "$CURRENT_LINK")"
set_current_release "$RELEASE_DIR" "$current_expected"
record_profile_migration
if validate_profile >/dev/null 2>&1; then echo "Hippocampus $VERSION installed and configured"
else echo "Hippocampus $VERSION installed; run the hippocampus-set-up skill to configure it"; fi
