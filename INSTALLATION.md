# Installation and configuration

Installation makes the skills available to Claude Code and Codex. Configuration
is a separate, guided step that chooses where the system stores knowledge and
how agents route follow-up work.

Installation is supported on macOS and Linux. Native Windows is not supported;
Windows users can instead run Hippocampus and their agent client inside the
same WSL Linux distribution.

## Prerequisites

`install.sh` requires `bash`, `python3`, and `tar` on `PATH`; it refuses to run
without `python3` rather than leaving a partial install behind. Cloning the
checkout also requires `git`. The signed-release route
(`scripts/install-release.sh`) additionally requires `gpg` and `shasum`.
GnuPG verifies that the checksum file was signed by the expected maintainer
before `shasum` checks the archive and the installer extracts it.

macOS includes `bash`, `tar`, and `shasum`. With Homebrew, install the remaining
prerequisites for the route you choose:

```bash
brew install git python3       # checkout
brew install python3 gnupg     # signed release
```

On Debian or Ubuntu:

```bash
sudo apt-get update
sudo apt-get install bash git python3 tar                       # checkout
sudo apt-get install bash python3 tar gnupg libdigest-sha-perl # signed release
```

On Fedora:

```bash
sudo dnf install bash git python3 tar                    # checkout
sudo dnf install bash python3 tar gnupg2 perl-Digest-SHA # signed release
```

On another Linux distribution, install packages that provide the commands
required by the route you choose.

## Installed package

A successful installation creates immutable per-version package storage, one
stable pointer to the active version, and skill links for both Claude and
Codex:

```text
~/.local/share/hippocampus/
├── releases/
│   └── <version>/
│       ├── skills/
│       ├── contracts/
│       ├── profiles/
│       ├── scripts/
│       └── manifest
└── current -> releases/<version>

$HOME/.claude/skills/<skill> -> $HOME/.local/share/hippocampus/current/skills/<skill>
$HOME/.codex/skills/<skill>  -> $HOME/.local/share/hippocampus/current/skills/<skill>
```

The Codex root defaults to `$HOME/.codex` and can be changed with `CODEX_HOME`.

Upgrades activate all package skills together by moving `current`. Older valid
release directories may remain on disk. The installer refuses to overwrite a
foreign skill link, broken package link, tampered release, or same-version
release with different content.

Installation succeeds before a knowledge profile exists so that the
`hippocampus-set-up` skill is available to guide configuration. The package is
installed at that point, but it is not ready for workflows that read or write
the knowledge store. `bash install.sh --verify` remains the combined package
integrity and configuration-readiness check.

## Install from this checkout

This checkout is a release candidate rather than a published release:

```bash
bash install.sh
```

Then ask your agent to configure it:

```text
Use hippocampus-set-up to walk me through configuring Hippocampus.
```

The skill explains the storage model and workflow, inspects any existing
configuration, discusses the decisions that belong to you, and shows the exact
proposed changes before writing. After configuration, verify the result:

```bash
bash install.sh --verify
```

## Configure a knowledge root manually

The guided skill is recommended because a useful configuration includes local
policy and two meaningful follow-up routes, not just valid paths. To configure
the same contract manually, replace the example path with the root you want the
skills to use:

```bash
RESEARCH_KNOWLEDGE_ROOT=/absolute/path/to/knowledge
mkdir -p "$RESEARCH_KNOWLEDGE_ROOT"/{raw,output,docs}
touch "$RESEARCH_KNOWLEDGE_ROOT/docs/log.md"
touch "$RESEARCH_KNOWLEDGE_ROOT/docs/DECISIONS.md"

# Only when using the wiki, which is enabled by default:
mkdir -p "$RESEARCH_KNOWLEDGE_ROOT/wiki"
touch "$RESEARCH_KNOWLEDGE_ROOT/wiki/hot.md"

mkdir -p ~/.config/hippocampus
cp ~/.local/share/hippocampus/current/profiles/karpathy-wiki.example.md \
  ~/.config/hippocampus/profile.md
```

Edit `~/.config/hippocampus/profile.md` and set:

- `knowledge_root` to the existing absolute root;
- `operation_log_file` and `decision_log_file` to existing files relative to
  that root;
- `artifact_followup_destination` to the route for research findings that
  require work elsewhere.

The wiki is enabled by default. To use it, also set `hot_file` to an existing
file relative to the root and `wiki_followup_destination` to the route for
knowledge-base maintenance. To skip the wiki, add `wiki_enabled: false` to the
profile and omit both wiki fields; the `wiki/` directory is then neither
required nor created, and `research-to-wiki` and `wiki-audit` refuse to run.

The follow-up destinations are intentionally independent. Replace the
instructional placeholders with routes another agent can actually follow. The
profile's free-form Markdown body can define local taxonomy, source-library
routing, output naming, log formats, and other policy for this knowledge root.
The validated frontmatter schema is currently `profile_version: 4`.

## Install a published release

Each published GitHub Release will provide six matching assets: the versioned
archive, its SHA-256 file, a detached signature for that checksum file, the
maintainer public key, and the `install-release.sh` and `verify-release.sh`
scripts themselves. The scripts are published unmodified so that a release can
be installed and verified using only the published assets, without first
cloning the repository or extracting the unverified archive. Releases through
v0.5.0 predate this contract and carry only the first four assets; neither
script is published there. To install one of those releases, clone the
repository and run `bash scripts/install-release.sh` against the downloaded
assets.

Obtain the expected maintainer fingerprint from an independent,
maintainer-controlled channel before downloading the assets. Then verify and
install from local copies, with all six downloaded assets in the same
directory (`install-release.sh` looks for `verify-release.sh` beside it, and
`verify-release.sh` looks for the archive's `.sha256` and `.asc` files beside
the archive):

```bash
bash install-release.sh \
  hippocampus-<version>.tar.gz \
  hippocampus-release.asc \
  <maintainer-fingerprint>
```

The release installer imports the supplied key into a temporary keyring,
requires its fingerprint to match the independently obtained value, verifies
the detached signature and checksum, extracts the signed payload, and invokes
the package installer. Reinstalling identical content is safe; a same-version,
different-content collision fails.

The current release-signing public key is
[`keys/hippocampus-release.asc`](keys/hippocampus-release.asc). Its
fingerprint is `09674AFF392661238F4ACBD9F32B3A412CD5EFC5`.

For published-release upgrades and migration boundaries, see
[MIGRATION.md](MIGRATION.md).

## Verify a checkout

Run the shell contract, installation, and signed-release round-trip suites,
then test the optional Apple Speech package:

```bash
bash tests/test-contracts.sh
bash tests/test-install.sh
bash tests/test-release.sh
(cd skills/transcribe/tools/apple-speech && swift test)
```
