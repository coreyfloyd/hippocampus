---
name: vault-compile
description: Compatibility entry point for a selected-source local wiki compile; delegates to wiki-compile with local policy.
---

# Vault Compile (compatibility)

Use [wiki-compile](../wiki-compile/SKILL.md). Carry the caller's selected primary
sources, approval, compile mode and local policy unchanged. Local thresholds,
page conventions, coverage and targeted update rules are policy inputs to the
canonical compiler, not a second implementation.
