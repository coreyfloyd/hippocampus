#!/bin/bash
# Verify a release archive: its checksum carries a signature by the expected key,
# and the archive matches the checksum. Usage:
#   verify-release.sh continuity-<version>.tar.gz continuity-release.asc <fingerprint>
set -euo pipefail

ARCHIVE="${1:?archive required}"
KEYRING="${2:?keyring required}"
EXPECTED_FINGERPRINT="${3:?expected signing fingerprint required}"
for tool in gpg shasum; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "verify-release.sh: $tool is required but was not found on PATH" >&2
    exit 1
  fi
done
for file in "$ARCHIVE" "$ARCHIVE.sha256" "$ARCHIVE.asc"; do
  if [ ! -f "$file" ]; then
    echo "verify-release.sh: missing $file" >&2
    exit 1
  fi
done
GNUPGHOME="$(mktemp -d)"
trap 'gpgconf --kill gpg-agent >/dev/null 2>&1 || true; rm -rf "$GNUPGHOME"' EXIT
export GNUPGHOME
gpg --batch --import "$KEYRING" >/dev/null 2>&1
NORMALIZED_EXPECTED="$(printf '%s' "$EXPECTED_FINGERPRINT" | tr -d '[:space:]' | tr '[:lower:]' '[:upper:]')"
VERIFY_STATUS="$(gpg --batch --status-fd 1 --verify "$ARCHIVE.asc" "$ARCHIVE.sha256" 2>/dev/null || true)"
# VALIDSIG's last field is the primary key fingerprint of the signer.
SIGNING_FINGERPRINT="$(printf '%s\n' "$VERIFY_STATUS" | awk '$1 == "[GNUPG:]" && $2 == "VALIDSIG" {print $NF; exit}')"
if [ -z "$SIGNING_FINGERPRINT" ] || [ "$SIGNING_FINGERPRINT" != "$NORMALIZED_EXPECTED" ]; then
  echo "signing fingerprint mismatch" >&2
  exit 1
fi
# The signed checksum must name this archive, not another file beside it.
CHECKSUM_NAME="$(awk '{print $2; exit}' "$ARCHIVE.sha256" | sed 's/^\*//')"
if [ "$CHECKSUM_NAME" != "$(basename "$ARCHIVE")" ]; then
  echo "checksum names $CHECKSUM_NAME, not $(basename "$ARCHIVE")" >&2
  exit 1
fi
(cd "$(dirname "$ARCHIVE")" && shasum -a 256 -c "$(basename "$ARCHIVE").sha256")
