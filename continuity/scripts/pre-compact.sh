#!/bin/bash
# Hook adapter: deterministic pre-compaction handling belongs to handoff.py.
_dir="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
exec python3 "${HANDOFF_PY:-$_dir/lib/handoff.py}" pre-compact
