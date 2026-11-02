#!/bin/bash
# PostToolUse adapter: the stdlib module owns ledger attribution.
_dir="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
python3 "${HANDOFF_PY:-$_dir/../scripts/lib/handoff.py}" ledger-record
exit 0
