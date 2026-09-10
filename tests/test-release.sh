#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TEST_DIR="$(mktemp -d)"
trap 'rm -rf "$TEST_DIR"' EXIT
export GNUPGHOME="$TEST_DIR/gnupg"
mkdir -m 700 "$GNUPGHOME"
gpg --batch --passphrase '' --quick-generate-key 'Hippocampus test <test@example.invalid>' ed25519 sign 0 >/dev/null 2>&1
KEY="$(gpg --batch --with-colons --list-secret-keys | awk -F: '$1 == "fpr" {print $10; exit}')"
gpg --batch --armor --export "$KEY" > "$TEST_DIR/public.asc"
VERSION="$(tr -d '[:space:]' < "$ROOT/VERSION")"

# Build tests run against a throwaway git repository containing a snapshot of
# this worktree's current on-disk state (including any uncommitted edits to
# scripts/build-release.sh under test), rather than against $ROOT's own git
# history. That decouples the tests from $ROOT's actual branch/tag state
# (which may be mid-development, ahead of the last release tag) and lets each
# test control its own dirty/tag/basename conditions precisely.
sandbox_repo() {
  dest="$1"
  mkdir -p "$dest"
  # Snapshot only what a clean clone would hold: Finder and editor droppings,
  # build output, nested worktrees, and release output are never tracked, and
  # committing them here would make the sandbox's tracked state depend on the
  # developer's checkout (a tracked .DS_Store that T3 later truncates reads as
  # a dirty tree).
  (cd "$ROOT" && tar --exclude='.git' --exclude='.worktrees' --exclude='.DS_Store' \
      --exclude='.Ulysses-*' --exclude='.build' --exclude='dist' -cf - .) | (cd "$dest" && tar -xf -)
  (
    cd "$dest"
    git init --quiet
    git config user.email test@example.invalid
    git config user.name 'Hippocampus test'
    git add -A
    git commit --quiet -m 'sandbox snapshot'
  )
}

# --- T1 / T3 / T5: primary sandbox -----------------------------------------
REPO="$TEST_DIR/repo"
sandbox_repo "$REPO"

# T3 setup: untracked files that must structurally be unable to reach the
# archive, since git archive packages only tracked content.
mkdir -p "$REPO/skills"
: > "$REPO/skills/.DS_Store"
printf 'junk\n' > "$REPO/skills/junk.txt"

# T1: an in-tree, differently-named output directory must not leak into the
# archive (no OUT-path refusal is needed because git archive only packages
# tracked files).
HIPPOCAMPUS_GPG_KEY="$KEY" bash "$REPO/scripts/build-release.sh" "$REPO/distcd"
DISTCD_ARCHIVE="$REPO/distcd/hippocampus-$VERSION.tar.gz"
DISTCD_LIST="$TEST_DIR/distcd-list.txt"
tar -tzf "$DISTCD_ARCHIVE" > "$DISTCD_LIST"
if grep -q 'hippocampus/distcd/' "$DISTCD_LIST"; then
  echo 'release archive contains its own in-tree output directory' >&2
  exit 1
fi
if grep -E 'distcd/' "$DISTCD_LIST" | grep -qE '\.(tar\.gz|asc|sha256)$'; then
  echo 'release archive contains release-artifact entries' >&2
  exit 1
fi
rm -rf "$REPO/distcd"

# Primary archive for the Ulysses guard, T3, and the T5 round-trip cases.
HIPPOCAMPUS_GPG_KEY="$KEY" bash "$REPO/scripts/build-release.sh" "$REPO/dist"
ARCHIVE="$REPO/dist/hippocampus-$VERSION.tar.gz"

# Fail closed: `rg` is not POSIX and its absence made this guard pass vacuously.
ARCHIVE_LIST="$TEST_DIR/archive-list.txt"
tar -tzf "$ARCHIVE" > "$ARCHIVE_LIST"
ulysses_status=0
grep -qE '(^|/)[.]Ulysses-' "$ARCHIVE_LIST" || ulysses_status=$?
case "$ulysses_status" in
  1) : ;;
  0) echo 'release archive contains .Ulysses- metadata' >&2; exit 1 ;;
  *) echo "archive metadata scan failed (grep exit $ulysses_status)" >&2; exit 1 ;;
esac

# T3: the archive's file entries equal `git ls-files` (minus export-ignored
# paths), each prefixed with hippocampus/, so untracked files structurally
# cannot appear.
EXPECTED_LIST="$TEST_DIR/expected-list.txt"
(cd "$REPO" && git ls-files) \
  | grep -vE '(^|/)\.Ulysses-(Settings|Group)\.plist$' \
  | grep -vE '(^|/)\.DS_Store$' \
  | sed 's#^#hippocampus/#' | sort > "$EXPECTED_LIST"
ACTUAL_LIST="$TEST_DIR/actual-list.txt"
grep -v '/$' "$ARCHIVE_LIST" | sort > "$ACTUAL_LIST"
diff "$EXPECTED_LIST" "$ACTUAL_LIST"
if grep -q 'skills/\.DS_Store$' "$ARCHIVE_LIST"; then
  echo 'release archive contains an untracked .DS_Store' >&2
  exit 1
fi
if grep -q 'skills/junk\.txt$' "$ARCHIVE_LIST"; then
  echo 'release archive contains an untracked file' >&2
  exit 1
fi

# T5: existing round-trip, wrong-key, two-key, and tamper cases, unchanged.
bash "$ROOT/scripts/verify-release.sh" "$ARCHIVE" "$TEST_DIR/public.asc" "$KEY"
gpg --batch --passphrase '' --quick-generate-key 'other test <other@example.invalid>' ed25519 sign 0 >/dev/null 2>&1
OTHER_KEY="$(gpg --batch --with-colons --list-secret-keys | awk -F: '$1 == "fpr" {last=$10} END {print last}')"
gpg --batch --armor --export "$OTHER_KEY" > "$TEST_DIR/other.asc"
HIPPOCAMPUS_GPG_KEY="$OTHER_KEY" bash "$REPO/scripts/build-release.sh" "$REPO/other-dist"
OTHER_ARCHIVE="$REPO/other-dist/hippocampus-$VERSION.tar.gz"
if bash "$ROOT/scripts/verify-release.sh" "$OTHER_ARCHIVE" "$TEST_DIR/other.asc" "$KEY"; then
  exit 1
fi
cat "$TEST_DIR/public.asc" "$TEST_DIR/other.asc" > "$TEST_DIR/two-keys.asc"
if bash "$ROOT/scripts/verify-release.sh" "$OTHER_ARCHIVE" "$TEST_DIR/two-keys.asc" "$KEY"; then
  exit 1
fi
INSTALL_HOME="$TEST_DIR/install-home"
HOME="$INSTALL_HOME" CODEX_HOME="$INSTALL_HOME/.codex" bash "$ROOT/scripts/install-release.sh" "$ARCHIVE" "$TEST_DIR/public.asc" "$KEY"
HOME="$INSTALL_HOME" CODEX_HOME="$INSTALL_HOME/.codex" bash "$ROOT/scripts/install-release.sh" "$ARCHIVE" "$TEST_DIR/public.asc" "$KEY"
test -L "$INSTALL_HOME/.claude/skills/research-topic"
test -L "$INSTALL_HOME/.codex/skills/research-topic"
test -L "$INSTALL_HOME/.claude/skills/hippocampus-set-up"
test -f "$INSTALL_HOME/.local/share/hippocampus/current/profiles/karpathy-wiki.example.md"
test -f "$INSTALL_HOME/.local/share/hippocampus/current/scripts/validate_profile.py"
if HOME="$INSTALL_HOME" CODEX_HOME="$INSTALL_HOME/.codex" bash "$ROOT/install.sh" --verify; then
  exit 1
fi

# The documented published-release flow runs install-release.sh from a
# directory holding only the published assets (the archive, its .sha256 and
# .asc, the maintainer key, and the two scripts) with no access to the rest
# of the checkout. Guard that seam directly instead of only exercising the
# scripts from inside the repository tree.
PUBLISHED_DIR="$TEST_DIR/published"
mkdir "$PUBLISHED_DIR"
cp "$ARCHIVE" "$ARCHIVE.sha256" "$ARCHIVE.asc" "$PUBLISHED_DIR/"
cp "$TEST_DIR/public.asc" "$PUBLISHED_DIR/hippocampus-release.asc"
cp "$ROOT/scripts/install-release.sh" "$ROOT/scripts/verify-release.sh" "$PUBLISHED_DIR/"
PUBLISHED_ARCHIVE_NAME="$(basename "$ARCHIVE")"
PUBLISHED_INSTALL_HOME="$TEST_DIR/published-install-home"
(
  cd "$PUBLISHED_DIR" &&
  HOME="$PUBLISHED_INSTALL_HOME" CODEX_HOME="$PUBLISHED_INSTALL_HOME/.codex" \
    bash ./install-release.sh "$PUBLISHED_ARCHIVE_NAME" hippocampus-release.asc "$KEY"
)
test -L "$PUBLISHED_INSTALL_HOME/.claude/skills/research-topic"
test -f "$PUBLISHED_INSTALL_HOME/.local/share/hippocampus/current/scripts/validate_profile.py"

printf x >> "$ARCHIVE"
if bash "$ROOT/scripts/verify-release.sh" "$ARCHIVE" "$TEST_DIR/public.asc" "$KEY"; then
  exit 1
fi

# --- T2: basename independence ----------------------------------------------
# Build from a checkout whose directory basename is not "hippocampus" and
# assert every archive entry is still rooted at hippocampus/.
V042_REPO="$TEST_DIR/v042"
sandbox_repo "$V042_REPO"
HIPPOCAMPUS_GPG_KEY="$KEY" bash "$V042_REPO/scripts/build-release.sh" "$V042_REPO/dist"
V042_ARCHIVE="$V042_REPO/dist/hippocampus-$VERSION.tar.gz"
V042_LIST="$TEST_DIR/v042-list.txt"
tar -tzf "$V042_ARCHIVE" > "$V042_LIST"
if grep -qv '^hippocampus/' "$V042_LIST"; then
  echo 'release archive root depends on the build directory basename' >&2
  exit 1
fi

# --- T4: dirty tree refusal --------------------------------------------------
DIRTY_REPO="$TEST_DIR/dirty"
sandbox_repo "$DIRTY_REPO"
printf '\nlocal edit\n' >> "$DIRTY_REPO/README.md"
DIRTY_OUTPUT="$TEST_DIR/dirty-output.txt"
if HIPPOCAMPUS_GPG_KEY="$KEY" bash "$DIRTY_REPO/scripts/build-release.sh" "$DIRTY_REPO/dist" >"$DIRTY_OUTPUT" 2>&1; then
  echo 'build-release.sh built from a dirty working tree' >&2
  exit 1
fi
if ! grep -qi 'dirty' "$DIRTY_OUTPUT"; then
  echo 'build-release.sh dirty-tree refusal did not mention "dirty"' >&2
  cat "$DIRTY_OUTPUT" >&2
  exit 1
fi

# --- T7: tag gate, exercised with an annotated tag (releases use `git tag -a`,
# not lightweight tags; see "Push and tag the exact commit" in RELEASING.md) -
TAG_REPO="$TEST_DIR/tagmismatch"
sandbox_repo "$TAG_REPO"
(cd "$TAG_REPO" && git tag -a "v$VERSION" -m "Hippocampus $VERSION")

# Positive case: HEAD at the annotated release tag builds successfully. This
# is what catches an unpeeled tag comparison: `refs/tags/$TAG` alone resolves
# to the annotated tag OBJECT, not the commit it points at, so a build-script
# regression that dropped `^{commit}` peeling would refuse a legitimate build
# right here.
HIPPOCAMPUS_GPG_KEY="$KEY" bash "$TAG_REPO/scripts/build-release.sh" "$TAG_REPO/dist"
test -f "$TAG_REPO/dist/hippocampus-$VERSION.tar.gz"

# Negative case: a second commit past the annotated tag refuses, naming the tag.
(cd "$TAG_REPO" && git commit --quiet --allow-empty -m 'second commit, past the release tag')
TAG_OUTPUT="$TEST_DIR/tag-output.txt"
if HIPPOCAMPUS_GPG_KEY="$KEY" bash "$TAG_REPO/scripts/build-release.sh" "$TAG_REPO/dist2" >"$TAG_OUTPUT" 2>&1; then
  echo 'build-release.sh built from a commit past the release tag' >&2
  exit 1
fi
if ! grep -q "v$VERSION" "$TAG_OUTPUT"; then
  echo 'build-release.sh tag-mismatch refusal did not name the tag' >&2
  cat "$TAG_OUTPUT" >&2
  exit 1
fi

# --- T6: install-release.sh rejects a multi-root archive --------------------
TWO_DIR_SRC="$TEST_DIR/two-dir-src"
mkdir -p "$TWO_DIR_SRC/Hippocampus" "$TWO_DIR_SRC/extra"
: > "$TWO_DIR_SRC/hippocampus/VERSION"
: > "$TWO_DIR_SRC/hippocampus/install.sh"
: > "$TWO_DIR_SRC/extra/file.txt"
TWO_DIR_ARCHIVE="$TEST_DIR/hippocampus-two-dir.tar.gz"
(cd "$TWO_DIR_SRC" && tar -czf "$TWO_DIR_ARCHIVE" Hippocampus extra)
(cd "$TEST_DIR" && shasum -a 256 "$(basename "$TWO_DIR_ARCHIVE")") > "$TWO_DIR_ARCHIVE.sha256"
gpg --batch --yes --local-user "$KEY" --detach-sign --armor --output "$TWO_DIR_ARCHIVE.asc" "$TWO_DIR_ARCHIVE.sha256"
TWO_DIR_HOME="$TEST_DIR/two-dir-home"
TWO_DIR_OUTPUT="$TEST_DIR/two-dir-output.txt"
if HOME="$TWO_DIR_HOME" CODEX_HOME="$TWO_DIR_HOME/.codex" bash "$ROOT/scripts/install-release.sh" "$TWO_DIR_ARCHIVE" "$TEST_DIR/public.asc" "$KEY" >"$TWO_DIR_OUTPUT" 2>&1; then
  echo 'install-release.sh accepted an archive with two top-level directories' >&2
  exit 1
fi
if ! grep -qi 'top-level' "$TWO_DIR_OUTPUT"; then
  echo 'install-release.sh rejection message did not mention the top-level directory problem' >&2
  cat "$TWO_DIR_OUTPUT" >&2
  exit 1
fi

# gpg preflight (#5): a missing gpg must be named, not surface as exit 127.
NOGPG_BIN="$TEST_DIR/nogpg-bin"
mkdir -p "$NOGPG_BIN"
for tool in bash sh awk tr shasum tar mktemp dirname basename rm test cd printf head find wc; do
  path="$(command -v "$tool" || true)"
  [ -n "$path" ] && [ -f "$path" ] && ln -s "$path" "$NOGPG_BIN/$tool"
done
NOGPG_OUTPUT="$TEST_DIR/nogpg-output.txt"
if env -i HOME="$TEST_DIR" PATH="$NOGPG_BIN" bash "$ROOT/scripts/verify-release.sh" "$ARCHIVE" "$TEST_DIR/public.asc" "$KEY" >"$NOGPG_OUTPUT" 2>&1; then
  echo 'verify-release.sh succeeded without gpg on PATH' >&2
  exit 1
fi
if ! grep -q 'gpg is required' "$NOGPG_OUTPUT"; then
  echo 'verify-release.sh did not name gpg as the missing prerequisite' >&2
  cat "$NOGPG_OUTPUT" >&2
  exit 1
fi
