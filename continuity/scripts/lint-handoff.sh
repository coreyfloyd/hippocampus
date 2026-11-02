#!/bin/bash
# Compatibility adapter: validation belongs to scripts/lib/handoff.py.
_dir="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
exec python3 "${HANDOFF_PY:-$_dir/lib/handoff.py}" lint "$@"
