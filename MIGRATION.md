# Migrating to Hippocampus

Hippocampus stores new installations in `~/.config/hippocampus/` and `~/.local/share/hippocampus/`. The knowledge root and its contents do not move.

The installer upgrades a valid research-tools installation by copying its profile byte-for-byte to `~/.config/hippocampus/profile.md`, adding a new versioned release tree, and replacing each package-owned Claude and Codex link atomically before switching the Hippocampus `current` pointer. It leaves `~/.config/research-tools/` and every old release directory in place for recovery.

The old `research-tools-set-up` compatibility skill has been retired. The installer removes its package-owned Claude and Codex links. Use `hippocampus-set-up`.

On the first migration, the installer stops without changing links when it finds a foreign skill link, a broken or tampered legacy release, or different old and new profile files. For a profile conflict, make a backup of both files, reconcile the intended content into `~/.config/hippocampus/profile.md`, then move the legacy profile out of `~/.config/research-tools/profile.md` before rerunning `bash install.sh`. After a completed migration, the Hippocampus profile is authoritative, so later approved setup changes do not conflict with the preserved legacy copy. A stopped or interrupted run is safe to rerun: every pointer and link replacement is atomic, and the old installation is never deleted.

Existing version-4 profiles need no change and continue to validate unchanged. An absent `wiki_enabled` means the wiki remains enabled; setting `wiki_enabled: false` continues to opt out of it.

## Meeting capture and retained outputs

The unreleased `meeting_daily_note_path` is renamed to `meeting_note_path`; update that field if you used the development candidate. Published profiles do not contain it. The optional meeting source fields documented in `INSTALLATION.md` require no profile-version change; existing version-4 profiles remain valid. After approved distribution is finished, research outputs now move to `raw/derived/` with `use: artifact` and `compile_mode: exclude`, rather than being deleted. Existing archives are not automatically moved or recovered. `meeting-capture` is a thin entry point to the shared knowledge-capture meeting procedure and is installed in both supported clients.


## Capture and shared absorption in 0.10.0

After installing the signed 0.10.0 release, use `absorb`
for both research artifacts and meeting records and `wiki-compile` for selected
primary sources. `research-absorb`, `research-to-wiki`, `vault-compile` and
`vault-audit` remain compatibility entry points; the former research artifact
contract path still resolves. Existing version-4 profiles need no new fields.
New optional record settings default to `meetings/` and the bundled minimal
Markdown template. No existing records, archives or sources are moved by install.

If you own a local compiler/audit skill, first preserve its policy (compile modes,
thresholds, taxonomy, page conventions and coverage) in the profile body or a
root-contained policy file it references. Compare the canonical package behavior
with that policy. Back up or rename the local skill deliberately, then rerun the
signed-release installer and verify both clients. An unowned local `vault-compile`,
`vault-audit`, `wiki-compile` or `absorb` blocks installation explicitly; the
installer will not remove it or adopt its content. Custom templates stay outside
the immutable package and are never overwritten. Package-owned old commands
upgrade normally with both clients.

New meeting records stay at their captured path through partial and completed
absorption. Research artifacts keep their own retention rule. Legacy research
execution tables can be normalized by absorb without rewriting their prose or
renewing unchanged authorization; preserve existing task receipts during that
conversion. Original meeting transcripts keep a separate raw intake/archive
policy; a source's ingested status does not imply all authorized routes completed.
Public-documentation approval, signing/version decisions, release publication,
production activation and live backfill are separate later steps.

## Manual continuity cutover

Continuity was never released. Hippocampus ships no continuity migration code
or aliases. Before changing anything, back up the files you want to keep.

1. Uninstall continuity from every tool where it is present, using its original
   uninstall commands (the Hippocampus installers report those commands when
   they detect it). Then install Hippocampus with `python3 scripts/install-claude.py`
   and/or `python3 scripts/install-codex.py` from the checkout or a verified release.
2. Move or recreate `~/.config/checklist/profile.md` as
   `~/.config/hippocampus/checklist-profile.md`. Manually remove the `knowledge`
   and `lessons` binding blocks; preserve `record`, `persist`, ask and your own
   added steps. The removed slots are now native steps. If both files exist,
   reconcile them yourself rather than overwriting either one.
3. Move custom lesson routing from `~/.config/improve-harness/routing.md` to
   `~/.config/hippocampus/routing.md`. Replace `IMPROVE_HARNESS_ROUTING` overrides
   with `HIPPOCAMPUS_ROUTING`. Move wanted shared configuration from
   `~/.config/continuity/config.json` to `~/.config/hippocampus/config.json`,
   replacing `CONTINUITY_CONFIG` with `HIPPOCAMPUS_CONFIG`. Reconcile existing
   destination files and any old paths inside your configuration manually.
4. Move wanted handoffs from `~/.local/state/continuity/handoffs/` to
   `~/.local/state/hippocampus/handoffs/`, preserving filenames and resolving
   collisions manually. `HANDOFF_STATE_DIR` remains supported if you prefer
   your existing custom location. Use pickup to inspect carried items; the
   native knowledge and lessons steps receive those items at the next wrap.

Claude commands now use `/hippocampus:<skill>`; Codex uses plain names. Setup
stays `hippocampus-set-up`. Existing Hippocampus knowledge profiles remain
version 4 at `~/.config/hippocampus/profile.md`; do not replace that knowledge
profile with your checklist profile. Your knowledge root does not move.
