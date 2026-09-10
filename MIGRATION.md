# Migrating to Hippocampus 0.8.0

Hippocampus stores new installations in `~/.config/hippocampus/` and `~/.local/share/hippocampus/`. The knowledge root and its contents do not move.

Running the 0.8.0 installer upgrades a valid research-tools installation by copying its profile byte-for-byte to `~/.config/hippocampus/profile.md`, adding a new versioned release tree, and atomically repointing package-owned Claude and Codex skill links. It leaves `~/.config/research-tools/` and every old release directory in place for recovery.

The old `research-tools-set-up` command remains a forwarding compatibility skill. Use `hippocampus-set-up` in new instructions.

The installer stops without changing links when it finds a foreign skill link, a broken or tampered legacy release, or different old and new profile files. For a profile conflict, compare the two files, keep the intended content in the Hippocampus path, then rerun `bash install.sh`. A stopped or interrupted run is safe to rerun: release and link updates are atomic and the old installation is never deleted.

Existing profile version 4 files continue to validate unchanged. An absent `wiki_enabled` means the wiki remains enabled; setting `wiki_enabled: false` continues to opt out of it.
