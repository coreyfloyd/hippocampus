#!/bin/bash
# Stop-hook adapter: the stdlib module owns the staleness decision and JSON.
_dir="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
python3 "${HANDOFF_PY:-$_dir/../scripts/lib/handoff.py}" guard-decide
exit 0
