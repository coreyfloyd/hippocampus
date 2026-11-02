#!/bin/bash
# Build and sign a release archive. The maintainer runs this; see RELEASING.md.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["version"])' "$ROOT/.claude-plugin/plugin.json")"
OUT="${1:-$ROOT/dist}"
KEY="${CONTINUITY_GPG_KEY:?set CONTINUITY_GPG_KEY to the signing key fingerprint}"

# Only tracked-file changes count as dirty: git archive below never packages
# untracked files, so an in-tree output directory cannot leak into the archive.
if [ -n "$(cd "$ROOT" && git status --porcelain --untracked-files=no)" ]; then
  echo "refusing to build: working tree is dirty" >&2
  exit 1
fi

# If the release tag exists, HEAD must be the commit it points at.
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
# Absolute, so a relative argument means the caller's directory, not $ROOT.
OUT="$(cd "$OUT" && pwd)"
ARCHIVE="$OUT/continuity-$VERSION.tar.gz"
# The archive is the tracked tree at HEAD under a literal continuity/ root,
# whatever the checkout directory is called.
(cd "$ROOT" && git archive --format=tar.gz --prefix=continuity/ -o "$ARCHIVE" HEAD)
(cd "$OUT" && shasum -a 256 "$(basename "$ARCHIVE")") > "$ARCHIVE.sha256"
gpg --batch --yes --local-user "$KEY" --detach-sign --armor --output "$ARCHIVE.asc" "$ARCHIVE.sha256"
