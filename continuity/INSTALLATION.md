# Installation and configuration

continuity supports Claude Code and Codex on macOS and Linux. Run both tools
inside the same Linux environment when using WSL; native Windows is not a
supported shell environment. Nothing needs configuring to use shared handoffs.
Profiles separately connect the checklist to your record and persistence policy.

## Prerequisites

The runtime requires Python 3.9 or newer (standard library only), Bash 3.2 or
newer, and `git`. The Claude Code checklist reminder also requires `jq`.
Install your chosen agent CLI separately: Claude Code with plugin support, or
Codex CLI 0.160.0 or newer with command hooks and `app-server` hook discovery.
The Codex contract uses captured 0.160.0 payloads; installation verifies trusted
hooks against your installed binary.

Cloning a checkout uses `git`. Downloaded signed releases additionally need
`gpg`, `gpgconf`, `shasum`, and `tar`. The commands below install runtime and
route prerequisites; they do not install or authenticate an agent CLI.

macOS includes Bash, `tar`, and `shasum`. With Homebrew:

```bash
brew install git python jq                # checkout route, either tool
brew install git python jq gnupg          # signed-release route, either tool
```

Debian or Ubuntu:

```bash
sudo apt-get update
sudo apt-get install bash git python3 jq                        # checkout route
sudo apt-get install bash git python3 jq tar gnupg libdigest-sha-perl # signed release
```

Fedora:

```bash
sudo dnf install bash git python3 jq                     # checkout route
sudo dnf install bash git python3 jq tar gnupg2 perl-Digest-SHA # signed release
```

For another Linux distribution, install packages providing the same commands.

## Installed layout

### Claude Code

This repository is its own plugin marketplace. Claude Code places a versioned
copy in its plugin cache, normally beneath `~/.claude/plugins/cache/continuity/`.
For a local marketplace install, the CLI may read directly from the source
folder (`Read from` in `claude plugin list`); keep that folder available.
The active package contains `skills/<skill>/SKILL.md`, `scripts/`, `hooks/`, and
`hooks/hooks.json`. Claude Code discovers the seven skills from `skills/` and
registers the six handlers declared in `hooks/hooks.json`, resolving their
commands relative to `CLAUDE_PLUGIN_ROOT`. The commands are namespaced
`/continuity:<skill>`; no separate copy in `~/.claude/skills` is required.

### Codex

The installer copies the runtime rather than depending on the download:

```text
${CODEX_HOME:-~/.codex}/
├── continuity/               # scripts/, skills/, hooks/, INTERFACE.md, LICENSE
├── skills/<skill>            # seven links into continuity/skills/
├── hooks.json                # six continuity handlers plus the actor guard
├── config.toml               # persisted hook trust; other settings retained
└── continuity-install.json   # ownership of registrations and trust entries
```

Existing hooks and settings are retained. A skill owned by another installer
causes refusal before writes. Installation checks all seven handlers through
`codex app-server` (`hooks/list`); failed trust verification restores the previous
installation. Repeating the install command updates the runtime and owned links.
`--codex-home PATH` selects another home; `--codex PATH` selects the binary used
for verification. Restart the Codex session after installing.

## Install from a checkout

Start in a clean checkout's root. To obtain one:

```bash
git clone https://github.com/coreyfloyd/continuity.git
cd continuity
```

For Claude Code, install from that checkout:

```bash
claude plugin install continuity --marketplace "$PWD"
```

For Codex:

```bash
python3 scripts/install-codex.py
```

Both routes register seven skills. The package itself requires no account
credentials; your agent CLI retains its own authentication requirements.

## Install a downloaded signed release

Download the matching assets into one directory: `continuity-0.1.1.tar.gz`,
`continuity-0.1.1.tar.gz.sha256`, `continuity-0.1.1.tar.gz.asc`,
`continuity-release.asc`, and `verify-release.sh`. The signature is over the
checksum file. Verify before extracting:

```bash
bash verify-release.sh continuity-0.1.1.tar.gz continuity-release.asc \
  09674AFF392661238F4ACBD9F32B3A412CD5EFC5
tar -xzf continuity-0.1.1.tar.gz
cd continuity
```

The published fingerprint is `09674AFF392661238F4ACBD9F32B3A412CD5EFC5`, also
in [RELEASE_SIGNING_FINGERPRINT](RELEASE_SIGNING_FINGERPRINT). The verifier
requires a signature by that primary key and an archive matching the signed
checksum. Replace the version consistently when installing a later release.

Inside the verified extracted directory, run the Claude Code checkout install
command above or the Codex checkout install command above. Keep the extracted folder available for Claude Code’s local marketplace
route. The Codex installer copies its runtime, so a Codex-only installation
does not need the extracted folder afterward.

Claude Code also supports the repository's marketplace route, which installs
from the marketplace's repository rather than your verified extracted bytes:

```bash
claude plugin install continuity --marketplace coreyfloyd/continuity
```

Inside a Claude Code session the corresponding `/plugin install` action can
also select the marketplace. For a signed release, use the local verified route.
No release assets exist until the release is published; their exact route is
checked in the release's verification procedure in [RELEASING.md](RELEASING.md).

## Shared configuration

Both tools read one JSON object from `$CONTINUITY_CONFIG`, otherwise
`${XDG_CONFIG_HOME:-~/.config}/continuity/config.json`. An absent file means
empty configuration. An unreadable file, non-object value, or wrongly typed
setting is an error, not an empty configuration.

These are every key in [INTERFACE.md section 2](INTERFACE.md#2-configuration):

| Key | Type | Meaning |
|---|---|---|
| `handoff_dir` | string | Handoff storage directory; expands `~`. `HANDOFF_STATE_DIR` overrides it. |
| `checklist_state_dir` | string | Checklist marker directory; `CHECKLIST_STATE_DIR` overrides it. |
| `checklist_surfaces` | list of strings | Standing directories the surface detector reports alongside the session's repository. |
| `checklist_suite_baselines_dir` | string | Per-repository suite baseline directory reported by the surface detector. |
| `harness_enforcement_reference` | string | Optional slim-harness enforcement reference; require an absolute path or a `~/` path (expand `~` to the current user’s home). Ordinary relative paths are configuration errors, never relative to the working directory. If absent, report “no enforcement reference configured” and inspect hooks directly. |
| `prune_days` | positive integer | Transcript age in days for `stale_transcript` prune candidates; default 7, overridden by `PICKUP_PRUNE_DAYS`. |
| `cycle_sessions` | object | Session names mapped to home-relative directories for an external session-cycling consumer. The package does not run that consumer. |
| `unattended` | object | Optional unattended-mode adapter: `state_module`, `completion_command`, and `completed_by`, described in interface section 6. Absent by default. |

Default shared storage sits outside both tools' data areas:

| What | Default | Override |
|---|---|---|
| Handoffs | `~/.local/state/continuity/handoffs/` | `HANDOFF_STATE_DIR`, then `handoff_dir` |
| Ledger | the parent of the handoff directory (`~/.local/state/continuity/`) | `HANDOFF_LEDGER_DIR` |
| Pre-compaction backups | `~/.local/state/continuity/compact-state/` | `HANDOFF_COMPACT_STATE_DIR` |
| Checklist state | `~/.local/state/continuity/checklist/` | `CHECKLIST_STATE_DIR`, then `checklist_state_dir` |

The ledger holds one `session-touched-paths.<session-id>.jsonl` file per session.
Pre-compaction backups hold raw hook input, not a complete transcript archive.
No cross-host synchronization is provided.

A minimal configuration retaining the default handoff location is:

```json
{
  "handoff_dir": "~/.local/state/continuity/handoffs/"
}
```

Create the configuration only if you want overrides; no file is needed for the
defaults. Avoid putting shared storage inside a tool's uninstall area.

### Checklist profiles

A profile is separate from the shared configuration. The user profile is
`$CHECKLIST_USER_PROFILE`, otherwise
`${XDG_CONFIG_HOME:-~/.config}/checklist/profile.md`. Repository profiles live
at `.claude/checklist-profile.md` and add steps. JSON or a Markdown
`checklist-profile` fence binds the four slots and adds steps around the spine.
For example, the glossary's profile binds `record` to `/record-step`, consuming
`progress` and `decision` items; replace that command with your own record
workflow. See [the profile contract](INTERFACE.md#6-checklist-engine-scriptslibchecklistpy)
and [glossary](docs/glossary.md) for the full shape and allowed anchors.

Without a profile, `record`, `knowledge`, and `persist` are unbound; their
items go through the filing rules before wrap; unbound destinations warn and
retain their items. `lessons` defaults to `improve-harness`. A user profile may
bind `"ask": {"command": "/ask-step"}` for user decisions and approvals. This
command is separate from the four slots and never files asks as tickets. A profile
cannot remove a spine step. Only `own-worktree` may follow the handoff.

## Verify the installation

For Claude Code:

```bash
claude plugin list
```

Confirm `continuity@continuity` is enabled. Start a new interactive session in
the installed tool and request `Use pickup to list what I can resume here`.
Claude Code should expose `/continuity:pickup` and the other six names in the
README's table. An empty candidate list is valid when no prior handoff exists.

For Codex, the installer has already verified seven trusted handlers through
`hooks/list`. Start a new interactive Codex session and request `Use pickup to
list what I can resume here`. Confirm it finds the `pickup` skill. Then request
`Use checkpoint to write a handoff for this session now` and confirm it reports
a handoff path and lint result. With both tools installed, pickup in the other
tool should list that same handoff. A lint failure is reported and requires a
corrected handoff; the existence of a file alone does not prove validity.

From the package root, the handoff engine can also confirm storage resolution:

```bash
python3 scripts/lib/handoff.py state-dir
```

## Uninstall

Claude Code:

```bash
claude plugin uninstall continuity@continuity
```

Codex, from a checkout or extracted package:

```bash
python3 scripts/install-codex.py --uninstall
```

If only the installed Codex copy remains, use:

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/continuity/scripts/install-codex.py" --uninstall
```

Codex removes the runtime, owned skill links, handlers, trust entries, and install
manifest. Foreign hooks and settings survive. Claude Code removes the plugin
registration. Neither removal deletes shared handoffs, ledger, compaction backups,
checklist state, shared configuration, user profiles, or repository profiles.

## Test a checkout

With pytest available:

```bash
python3 -m pip install pytest
python3 -m pytest -q tests
bash tests/test-pickup-wrapper.sh
bash tests/test-pickup-branch-scan.sh
```

Alternatively, if `uv` is installed, run the pytest command with an isolated
dependency environment:

```bash
uv run --with pytest python -m pytest -q tests
```

CLI-backed installation checks use isolated homes and skip if the corresponding
CLI is unavailable. The architecture ancestor check skips in extracted archives
without git history. The fixtures are captured sessions with identifying values
replaced by neutral stand-ins; their provenance lives beside them.

The existing personal-reference check walks the shipped tree, including the new
documents. Its term list stays outside the repository. To run that check:

```bash
REFERENCE_CHECK_TERMS=/path/to/terms.txt python3 -m pytest -q tests/test_shipped_surface.py
python3 scripts/lib/reference_check.py --terms /path/to/terms.txt .
```

Terms are case-insensitive, one per line. Between letters or digits, a separator
(`-`, `_`, `.`, or space) matches any run of separators or none. Lines starting
with `#` are comments; use `\#` for a literal leading `#`. Exit zero is clean.


## Guided setup with the user present

After installation, invoke `/continuity:setup` in Claude Code or `Use setup` in
Codex. Setup is included among the nine installed skills. It is discovered by the
Claude Code plugin and linked by the Codex installer. Both tools use the same setup
procedure and user profile.

Setup asks about each checklist slot: record, knowledge, lessons and persist.
It creates a user profile or extends your existing one, preserving notes,
sections, added steps and unchanged bindings. You can decline any slot;
explicitly declining lessons leaves it unbound rather than selecting its
default. Unbound slots carry unsaved items into the handoff.

Setup also asks which tool you track work in. The agent writes your own
read-only record-read skill outside the installed package, using tools you
already have. It runs that skill with a real request and shows the package
validator's verdict before binding it, then checks the written profile with
the profile composer. No particular work-tracking tool is required or supplied.
Missing access or invalid output leaves setup incomplete with an explanation.

Run setup while present to answer its questions. Unattended setup stops without
writes. Setup changes neither shared configuration nor repository profiles.
The user profile and user-owned read skill remain yours when continuity is
updated or uninstalled.

To try setup without touching your real profile, set `XDG_CONFIG_HOME` to an
empty folder, unset `CHECKLIST_USER_PROFILE`, and start Claude Code with
`--setting-sources project --plugin-dir <checkout>`. Keep your own `HOME`: a
fresh one on macOS cannot store the Claude Code login.
