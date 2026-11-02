"""A stand-in session-state provider for the checklist's unattended mode.

It implements the interface INTERFACE.md documents for ``unattended.state_module``:
``state_path(session_id)`` says where a session's mode record lives and
``read_state(path, session_id)`` returns it. Records are JSON files named by
session id under ``$UNATTENDED_STATE_DIR``.
"""
import json
import os
from pathlib import Path


def state_path(session_id):
    directory = os.environ.get("UNATTENDED_STATE_DIR")
    return Path(directory) / session_id if directory else None


def read_state(path, session_id):
    try:
        state = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None
    return state if isinstance(state, dict) and state.get("session_id") == session_id else None
