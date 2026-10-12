---
name: vault-audit
description: Compatibility entry point for an opt-in read-only local wiki audit; delegates to wiki-audit.
---

# Vault Audit (compatibility)

Use [wiki-audit](../wiki-audit/SKILL.md) with the same configured scope, local
mode thresholds and coverage expectations. It is read-only and opt-in; retain
its sampling limitations. This wrapper does not repair findings or change logs.
