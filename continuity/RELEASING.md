# Releasing continuity

The maintainer runbook for a `continuity` GitHub release.

## Release contract

A release uses the `version` in `.claude-plugin/plugin.json` and publishes:

```text
tag and title: v<version>

continuity-<version>.tar.gz
continuity-<version>.tar.gz.sha256
continuity-<version>.tar.gz.asc
continuity-release.asc
verify-release.sh
```

The archive is the tracked tree at the tagged commit under a `continuity/` root.
The checksum is signed, not the archive. `verify-release.sh` is published
unmodified from `scripts/`, so someone holding only the release assets can verify
the archive before extracting it.

The signing key is the one Hippocampus releases use. Its fingerprint is in
`RELEASE_SIGNING_FINGERPRINT` and its public key is `keys/continuity-release.asc`.
`tests/test_release.py` fails if the two disagree. Never replace the key in a
routine release. Rotating it is a separate, reviewed change.

## Signing is a manual maintainer step

The maintainer signs. An agent must never attempt it. Signing binds a human
decision to the published archive, and an agent that could sign unattended would
remove that binding.

An agent running this runbook stops at the build step, hands the maintainer the
exact command, and resumes at verification once the signed files exist. Do not use
`gpg --pinentry-mode loopback`, pipe a passphrase from a file or environment
variable, or install a GUI pinentry so an agent session can answer the prompt.
The key's passphrase is held by a TTY-bound pinentry, so an agent attempt fails
with `gpg: signing failed: Inappropriate ioctl for device`. That message is the
gate working.

## When to cut a release

Cut a tag only after every ticket planned for the release is closed. For the
first release, that is every other ticket on the package's extraction plan.

## Prerequisites

- A trusted machine with the release secret key in GnuPG and an interactive
  pinentry.
- Browser access to the repository with release publishing permission.
- Bash, GnuPG, Git, Python 3, and `shasum`.
- Every intended change committed. `scripts/build-release.sh` refuses a tree with
  modified, staged, or deleted tracked files, and packages only the tree at
  `HEAD`, so an untracked file is never shipped.

Check the environment without changing remote state:

```bash
test "$(git branch --show-current)" = main
test -z "$(git status --short)"
git fetch origin main --tags
test "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)"

VERSION_VALUE="$(python3 -c 'import json; print(json.load(open(".claude-plugin/plugin.json"))["version"])')"
TAG="v$VERSION_VALUE"
FINGERPRINT="$(tr -d '[:space:]' < RELEASE_SIGNING_FINGERPRINT)"

if git rev-parse --verify --quiet "refs/tags/$TAG"; then
  echo "local tag already exists: $TAG" >&2
  exit 1
fi
test -z "$(git ls-remote --tags origin "refs/tags/$TAG" "refs/tags/$TAG^{}")"
gpg --list-secret-keys "$FINGERPRINT"
printf 'VERSION=%s\nTAG=%s\nCOMMIT=%s\n' "$VERSION_VALUE" "$TAG" "$(git rev-parse HEAD)"
```

## Verify the candidate

Run the full suite against the exact commit to be released:

```bash
git diff --check
CONTINUITY_RELEASE_CHECK=1 python3 -m pytest tests
bash tests/test-pickup-wrapper.sh
bash tests/test-pickup-branch-scan.sh
python3 scripts/lib/reference_check.py --terms /path/to/terms.txt .
```

`tests/test_release.py` builds an archive in a sandbox repository, signs it with a
throwaway key, and verifies it. It also checks the committed key against
`RELEASE_SIGNING_FINGERPRINT`. The release check fails if GnuPG prerequisites
are missing; ordinary contributor runs skip these tests instead.

Before tagging, check the documentation against the release: grep `README.md`,
`INTERFACE.md`, and `docs/` for any name the release renamed or removed, and for
counts and absolutes (`six`, `only`, `never`, `always`, `all`) that the release
may have made wrong. A published tag cannot move, so fix drift first.

## Push and tag the exact commit

```bash
git push origin main
COMMIT="$(git rev-parse HEAD)"
test "$(git ls-remote origin refs/heads/main | awk '{print $1}')" = "$COMMIT"

git tag -a "$TAG" "$COMMIT" -m "continuity $VERSION_VALUE"
git push origin "$TAG"
test "$(git ls-remote origin "refs/tags/$TAG^{}" | awk '{print $1}')" = "$COMMIT"
```

Never move or force-push a published tag.

## Build and sign (maintainer only)

From an interactive terminal on the tagged commit:

```bash
export GPG_TTY="$(tty)"
CONTINUITY_GPG_KEY="$FINGERPRINT" bash scripts/build-release.sh dist
```

If the tag exists, the build refuses unless `HEAD` is the tagged commit.

## Verify the build

Everything from here is safe for an agent to run:

```bash
bash scripts/verify-release.sh \
  "dist/continuity-$VERSION_VALUE.tar.gz" keys/continuity-release.asc "$FINGERPRINT"
test -z "$(tar -tzf "dist/continuity-$VERSION_VALUE.tar.gz" | grep -v '^continuity/')"
```

## Publish

Write reviewed release notes to a file outside the repository, then:

```bash
cp keys/continuity-release.asc dist/
cp scripts/verify-release.sh dist/
```

Open the repository's Releases page in a browser, create a release for `$TAG`,
and attach the archive, checksum, signature, public key, and verification script
from `dist/`. Use the reviewed notes and `$TAG` as the title.

## Verify the published release

```bash
VERIFY_DIR="$(mktemp -d)"
printf 'Download all five release assets from the Releases page into %s\n' "$VERIFY_DIR"
# Continue after the browser downloads have finished.
test "$(find "$VERIFY_DIR" -maxdepth 1 -type f | wc -l | tr -d ' ')" = 5
cmp "$VERIFY_DIR/continuity-release.asc" keys/continuity-release.asc
cmp "$VERIFY_DIR/verify-release.sh" scripts/verify-release.sh
bash "$VERIFY_DIR/verify-release.sh" \
  "$VERIFY_DIR/continuity-$VERSION_VALUE.tar.gz" \
  "$VERIFY_DIR/continuity-release.asc" "$FINGERPRINT"
```

## Failure and recovery

Stop on any mismatch and inspect the remote tag, release, asset names, and
checksums before changing anything remote. Never force-push or silently replace
a published tag, and do not assume an upload with the same name overwrites the
old asset. After a recovery, download and verify the release again.
