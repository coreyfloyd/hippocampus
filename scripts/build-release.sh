#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="$(tr -d '[:space:]' < "$ROOT/VERSION")"
OUT="${1:-$ROOT/dist}"
UNSIGNED=false
case "${2:-}" in
  --unsigned) UNSIGNED=true ;;
  "") : ;;
  *) echo "usage: $0 [output-directory] [--unsigned]" >&2; exit 2 ;;
esac
if [ "$UNSIGNED" = false ]; then
  KEY="${HIPPOCAMPUS_GPG_KEY:?set HIPPOCAMPUS_GPG_KEY to the signing key fingerprint}"
fi
python3 "$ROOT/scripts/generate-release-metadata.py" --check

# Only tracked-file modifications count as "dirty" here: an in-tree, untracked
# output directory (this script's own OUT, editor droppings, etc.) must not
# block a build, since `git archive` below can never package untracked files
# regardless of where OUT points.
if [ -n "$(cd "$ROOT" && git status --porcelain --untracked-files=no)" ]; then
  echo "refusing to build: working tree is dirty" >&2
  exit 1
fi

# The release runbook requires a clean, exact-tag checkout before building.
# Enforce it here too: if a tag named v<VERSION> exists, HEAD must be it.
TAG="v$VERSION"
if (cd "$ROOT" && git rev-parse --verify --quiet "refs/tags/$TAG") >/dev/null 2>&1; then
  HEAD_COMMIT="$(cd "$ROOT" && git rev-parse HEAD)"
  TAG_COMMIT="$(cd "$ROOT" && git rev-parse "refs/tags/$TAG^{commit}")"
  if [ "$HEAD_COMMIT" != "$TAG_COMMIT" ]; then
    echo "refusing to build: HEAD ($HEAD_COMMIT) is not tag $TAG ($TAG_COMMIT)" >&2
    exit 1
  fi
fi

mkdir -p "$OUT"
ARCHIVE="$OUT/hippocampus-$VERSION.tar.gz"
# Build from the git-tracked tree at HEAD, not the working directory: the
# archive root is a literal prefix (never the checkout's basename) and only
# tracked files (minus any export-ignore paths in .gitattributes) can appear,
# so build output and untracked files are structurally excluded.
(cd "$ROOT" && git archive --format=tar.gz --prefix=hippocampus/ -o "$ARCHIVE" HEAD)
(cd "$OUT" && shasum -a 256 "$(basename "$ARCHIVE")") > "$ARCHIVE.sha256"
if [ "$UNSIGNED" = true ]; then
  # Never leave an older signature beside a freshly rebuilt candidate.
  rm -f "$ARCHIVE.asc"
  echo "Unsigned candidate only; maintainer signature required before publication."
  exit 0
fi
gpg --batch --yes --local-user "$KEY" --detach-sign --armor --output "$ARCHIVE.asc" "$ARCHIVE.sha256"
