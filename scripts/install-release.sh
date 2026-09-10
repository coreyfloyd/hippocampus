#!/bin/bash
set -euo pipefail

ARCHIVE="${1:?usage: install-release.sh ARCHIVE KEYRING EXPECTED_FINGERPRINT}"
KEYRING="${2:?usage: install-release.sh ARCHIVE KEYRING EXPECTED_FINGERPRINT}"
EXPECTED_FINGERPRINT="${3:?usage: install-release.sh ARCHIVE KEYRING EXPECTED_FINGERPRINT}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

bash "$SCRIPT_DIR/verify-release.sh" "$ARCHIVE" "$KEYRING" "$EXPECTED_FINGERPRINT"
tar -xzf "$ARCHIVE" -C "$WORK"
TOP_LEVEL_COUNT="$(find "$WORK" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')"
if [ "$TOP_LEVEL_COUNT" != "1" ]; then
  echo "release archive must contain exactly one top-level directory (found $TOP_LEVEL_COUNT)" >&2
  exit 1
fi
PAYLOAD="$(find "$WORK" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
if [ "$(basename "$PAYLOAD")" != "hippocampus" ]; then
  echo "release archive top-level directory must be named hippocampus (found $(basename "$PAYLOAD"))" >&2
  exit 1
fi
test -f "$PAYLOAD/VERSION"
test -f "$PAYLOAD/install.sh"
bash "$PAYLOAD/install.sh"
