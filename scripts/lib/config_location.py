"""Where the hippocampus configuration lives: one rule for every reader, standard library only."""
from __future__ import annotations

import os


def config_path() -> str:
    """``$HIPPOCAMPUS_CONFIG``, else ``${XDG_CONFIG_HOME:-~/.config}/hippocampus/config.json``."""
    explicit = os.environ.get("HIPPOCAMPUS_CONFIG")
    if explicit:
        return os.path.expanduser(explicit)
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "hippocampus", "config.json")
