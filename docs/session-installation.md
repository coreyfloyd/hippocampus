# Installation and configuration

hippocampus supports Claude Code and Codex on macOS and Linux. Run both tools
inside the same Linux environment when using WSL; native Windows is not a
supported shell environment. Nothing needs configuring to use shared handoffs.
Profiles separately connect the checklist to your record and persistence policy.

## Prerequisites

The runtime requires Python 3.9 or newer (standard library only; rules set-up in `scripts/rules_setup.py` needs 3.11 or newer for `tomllib`), Bash 3.2 or
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
copy in its plugin cache, normally beneath `~/.claude/plugins/cache/hippocampus/`.
For a local marketplace install, the CLI may read directly from the source
folder (`Read from` in `claude plugin list`); keep that folder available.
The active package contains `skills/<skill>/SKILL.md`, `scripts/`, `hooks/`, and
`hooks/hooks.json`. Claude Code discovers every packaged skill from `skills/` and
registers the six handlers declared in `hooks/hooks.json`, resolving their
commands relative to `CLAUDE_PLUGIN_ROOT`. The commands are namespaced
`/hippocampus:<skill>`; no separate copy in `~/.claude/skills` is required.

### Codex

The installer copies the runtime to `~/.local/share/hippocampus/current` rather
than depending on the download. Codex registrations live in:

```text
${CODEX_HOME:-~/.codex}/
├── skills/<skill>            # links into ~/.local/share/hippocampus/current/skills/
├── hooks.json                # six hippocampus handlers plus the actor guard
├── config.toml               # persisted hook trust; other settings retained
└── hippocampus-install.json   # ownership of registrations and trust entries
```

Existing hooks and settings are retained. Existing release-installer links can
be adopted; ownership of each skill link is recorded alongside hooks and trust.
Uninstall preserves any link the user has subsequently replaced, and restores
the old release pointer when Claude still uses that installer layout. A skill owned by another installer
causes refusal before writes. Installation checks all seven handlers through
`codex app-server` (`hooks/list`); failed trust verification restores the previous
installation. Repeating the install command updates the runtime and owned links.
`--codex-home PATH` selects another home; `--codex PATH` selects the binary used
for verification. Restart the Codex session after installing.

## Install from a checkout

Start in a clean checkout's root. To obtain one:

```bash
git clone https://github.com/coreyfloyd/hippocampus.git
cd hippocampus
```

For Claude Code, install from that checkout:

```bash
python3 scripts/install-claude.py
```

For Codex:

```bash
python3 scripts/install-codex.py
```

The Claude helper wraps the native plugin CLI from either tree. It removes only
links owned by the released installer in the same transaction, preserves foreign
links, and restores links, plugin registry, and settings if the CLI fails. Use
this helper for every Claude Code install, including upgrading an existing
`install.sh` installation; invoking the native plugin command directly does not
perform that cutover. `--claude PATH` selects the executable. Concurrent helper
invocations are refused while a cutover holds the lock.

Before installation, both helpers check both selected tool homes for the old
standalone package. If found, installation stops before writes and names the
runtime or registration to uninstall/remove. This check never migrates data or
uninstalls the old package. Hippocampus uninstall remains available.

Both routes register every packaged skill. The package itself requires no account
credentials; your agent CLI retains its own authentication requirements.

## Install a downloaded signed release

Download the matching assets into one directory: `hippocampus-0.1.1.tar.gz`,
`hippocampus-0.1.1.tar.gz.sha256`, `hippocampus-0.1.1.tar.gz.asc`,
`hippocampus-release.asc`, and `verify-release.sh`. The signature is over the
checksum file. Verify before extracting:

```bash
bash verify-release.sh hippocampus-0.1.1.tar.gz hippocampus-release.asc \
  09674AFF392661238F4ACBD9F32B3A412CD5EFC5
tar -xzf hippocampus-0.1.1.tar.gz
cd hippocampus
```

The published fingerprint is `09674AFF392661238F4ACBD9F32B3A412CD5EFC5`, also
in [RELEASE_SIGNING_FINGERPRINT](../RELEASE_SIGNING_FINGERPRINT). The verifier
requires a signature by that primary key and an archive matching the signed
checksum. Replace the version consistently when installing a later release.

Inside the verified extracted directory, run the Claude Code checkout install
command above or the Codex checkout install command above. Keep the extracted folder available for Claude Code’s local marketplace
route. The Codex installer copies its runtime, so a Codex-only installation
does not need the extracted folder afterward.

Use `python3 scripts/install-claude.py` for Claude Code from either tree.
The helper is the supported installation path; a bare native plugin command or
in-session marketplace action bypasses the required transaction.

An installed release registers through `~/.local/share/hippocampus/current`, so
upgrades need no marketplace change: install the new release, then run the helper
from `current`. A registration from an earlier release folder moves to `current`
and keeps the plugin's options and data. A marketplace from outside that runtime
root stops at a read-only check that names the source. Run
`claude plugin marketplace remove hippocampus`, which also uninstalls the plugin
and can delete its saved options and data, then run the helper again.

No release assets exist until the release is published; their exact route is
checked in the release's verification procedure in [RELEASING.md](../RELEASING.md).

## Shared configuration

Both tools read one JSON object from `$HIPPOCAMPUS_CONFIG`, otherwise
`${XDG_CONFIG_HOME:-~/.config}/hippocampus/config.json`. An absent file means
empty configuration. An unreadable file, non-object value, or wrongly typed
setting is an error, not an empty configuration.

These are every key in [INTERFACE.md section 2](../INTERFACE.md#2-configuration):

| Key | Type | Meaning |
|---|---|---|
| `handoff_dir` | string | Handoff storage directory; expands `~`. `HANDOFF_STATE_DIR` overrides it. |
| `checklist_state_dir` | string | Checklist marker directory; `CHECKLIST_STATE_DIR` overrides it. |
| `checklist_surfaces` | list of strings | Standing directories the surface detector reports alongside the session's repository. |
| `checklist_suite_baselines_dir` | string | Per-repository suite baseline directory reported by the surface detector. |
| `harness_enforcement_reference` | string | Optional slim-harness enforcement reference; require an absolute path or a `~/` path (expand `~` to the current user’s home). Ordinary relative paths are configuration errors, never relative to the working directory. If absent, report “no enforcement reference configured” and inspect hooks directly. |
| `timed_checkpoint_minutes` | positive integer | Whole-minute timer interval, at least 1; default 55. Both tools refuse fractions and other JSON types. Claude rounds its pinned cron minute up, never earlier than the interval and always in the future. |
| `timed_checkpoint_token_limit` | positive integer | Timed checkpoints run below this count; default 200,000. |
| `prune_days` | positive integer | Transcript age in days for `stale_transcript` prune candidates; default 7, overridden by `PICKUP_PRUNE_DAYS`. |
| `cycle_sessions` | object | Session names mapped to home-relative directories for an external session-cycling consumer. The package does not run that consumer. |
| `unattended` | object | Optional unattended-mode adapter: `state_module`, `completion_command`, and `completed_by`, described in interface section 6. Absent by default. |
| `auto_apply_lessons` | boolean | The auto-apply setting: a wrap applies the lessons it recommends and captures recommended wiki, source and output knowledge under the knowledge root; default false. |
| `slim_checkouts` | object | Maps a repository (`owner/name`) to its checkout on this machine, for the unattended slim. A repository not named is reported and waits. |

Default shared storage sits outside both tools' data areas:

| What | Default | Override |
|---|---|---|
| Handoffs | `~/.local/state/hippocampus/handoffs/` | `HANDOFF_STATE_DIR`, then `handoff_dir` |
| Ledger | the parent of the handoff directory (`~/.local/state/hippocampus/`) | `HANDOFF_LEDGER_DIR` |
| Pre-compaction backups | `~/.local/state/hippocampus/compact-state/` | `HANDOFF_COMPACT_STATE_DIR` |
| Timed checkpoint state | `timed-checkpoints/` beside the handoff directory | `HANDOFF_TIMER_DIR` |
| Checklist state | `~/.local/state/hippocampus/checklist/` | `CHECKLIST_STATE_DIR`, then `checklist_state_dir` |

The ledger holds one `session-touched-paths.<session-id>.jsonl` file per session.
Pre-compaction backups hold raw hook input, not a complete transcript archive.
No cross-host synchronization is provided.

A minimal configuration retaining the default handoff location is:

```json
{
  "handoff_dir": "~/.local/state/hippocampus/handoffs/"
}
```

Create the configuration only if you want overrides; no file is needed for the
defaults. Avoid putting shared storage inside a tool's uninstall area.

### Checklist profiles

A profile is separate from the shared configuration. The user profile is
`$CHECKLIST_USER_PROFILE`, otherwise
`${XDG_CONFIG_HOME:-~/.config}/hippocampus/checklist-profile.md`. Repository profiles live
at `.claude/checklist-profile.md` and add steps. JSON or a Markdown
`checklist-profile` fence names per-kind record writes, binds the persist slot,
and adds steps around the spine. Optional `record_writes` entries name executable
commands for tickets, projects, documents, and scheduled_jobs. Each accepts a
lookup or write request and returns an identity-matched receipt; see the
[record skill](../skills/record/SKILL.md). The retired `bindings.record` is refused.
 See [the profile contract](../INTERFACE.md#6-checklist-engine-scriptslibchecklistpy)
and [glossary](glossary.md) for the full shape and allowed anchors.

Without a profile, no record writes are configured and `persist` is unbound; their
items go through the filing rules before wrap; unbound destinations warn and
retain their items. Knowledge and lessons always run the package’s
knowledge-capture and improve-harness, using the knowledge profile and routing file. A user profile may
bind `"ask": {"command": "/ask-step"}` for user decisions and approvals. This
command is separate from the persist slot and never files asks as tickets. A profile
cannot remove a spine step. Only `own-worktree` may follow the handoff.

## Verify the installation

For Claude Code:

```bash
claude plugin list
```

Confirm `hippocampus@hippocampus` is enabled. Start a new interactive session in
the installed tool and request `Use pickup to list what I can resume here`.
Claude Code should expose `/hippocampus:pickup` and the other six names in the
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
python3 scripts/install-claude.py --uninstall
```

Codex, from a checkout or extracted package:

```bash
python3 scripts/install-codex.py --uninstall
```

If only the installed Codex copy remains, use:

```bash
python3 "$HOME/.local/share/hippocampus/current/scripts/install-codex.py" --uninstall
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

After installation, invoke `/hippocampus:hippocampus-set-up` in Claude Code or `Use hippocampus-set-up` in
Codex. Setup is included among the nine installed skills. It is discovered by the
Claude Code plugin and linked by the Codex installer. Both tools use the same setup
procedure and user profile.

Setup configures the checklist profile and the separate ask binding.
It creates a user profile or extends your existing one, preserving notes,
sections, added steps and unchanged bindings. You can decline either slot or
leave ask unbound. Unbound slots carry unsaved items into the handoff.
Knowledge and lessons are native; their destinations follow the knowledge profile
and lesson routing file. Legacy knowledge/lessons binding blocks are refused with
their line numbers and instructions to delete those blocks manually. Setup does
not convert or remove them automatically.

Setup also asks which tool you track work in. The agent writes your own
read-only record-read skill outside the installed package, using tools you
already have. It runs that skill with a real request and shows the package
validator's verdict before binding it, then checks the written profile with
the profile composer. No particular work-tracking tool is required or supplied.
Missing access or invalid output leaves setup incomplete with an explanation.

Run setup while present to answer its questions. Unattended setup stops without
writes. Setup changes neither shared configuration nor repository profiles.
The user profile and user-owned read skill remain yours when hippocampus is
updated or uninstalled.

To try setup without touching your real profile, set `XDG_CONFIG_HOME` to an
empty folder, unset `CHECKLIST_USER_PROFILE`, and start Claude Code with
`--setting-sources project --plugin-dir <checkout>`. Keep your own `HOME`: a
fresh one on macOS cannot store the Claude Code login.
