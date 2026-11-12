"""Shared limits for the bounded post-compaction restore projection."""

# Codex's documented default hook spill threshold is roughly 2,500 tokens.
# Keep the portable projection below that threshold even for byte-level input.
POST_COMPACT_CONTEXT_BYTES = 2_000
