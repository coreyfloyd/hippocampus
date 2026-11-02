#!/bin/bash
# Compatibility adapter: checkpoint orchestration belongs to handoff.py.
: "${HANDOFF_CHECKPOINT:=${HANDOFF_PY:-$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/../../../scripts/lib" && pwd)/handoff.py}}"
exec python3 "$HANDOFF_CHECKPOINT" checkpoint "$@"
