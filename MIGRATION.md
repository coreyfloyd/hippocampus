# Migrating to Hippocampus 0.8.0

Hippocampus stores new installations in `~/.config/hippocampus/` and `~/.local/share/hippocampus/`. The knowledge root and its contents do not move.

Running the 0.8.0 installer upgrades a valid research-tools installation by copying its profile byte-for-byte to `~/.config/hippocampus/profile.md`, adding a new versioned release tree, and replacing each package-owned Claude and Codex link atomically before switching the Hippocampus `current` pointer. It leaves `~/.config/research-tools/` and every old release directory in place for recovery.

The old `research-tools-set-up` command remains a forwarding compatibility skill. Use `hippocampus-set-up` in new instructions.

On the first migration, the installer stops without changing links when it finds a foreign skill link, a broken or tampered legacy release, or different old and new profile files. For a profile conflict, make a backup of both files, reconcile the intended content into `~/.config/hippocampus/profile.md`, then move the legacy profile out of `~/.config/research-tools/profile.md` before rerunning `bash install.sh`. After a completed migration, the Hippocampus profile is authoritative, so later approved setup changes do not conflict with the preserved legacy copy. A stopped or interrupted run is safe to rerun: every pointer and link replacement is atomic, and the old installation is never deleted.

Existing version-4 profiles need no change and continue to validate unchanged. An absent `wiki_enabled` means the wiki remains enabled; setting `wiki_enabled: false` continues to opt out of it.

## Meeting capture and retained outputs

The optional meeting source fields documented in `INSTALLATION.md` require no profile-version change; existing version-4 profiles remain valid. After approved distribution is finished, research outputs now move to `raw/derived/` with `use: artifact` and `compile_mode: exclude`, rather than being deleted. Existing archives are not automatically moved or recovered. `meeting-capture` is a thin entry point to the shared knowledge-capture meeting procedure and is installed in both supported clients.
