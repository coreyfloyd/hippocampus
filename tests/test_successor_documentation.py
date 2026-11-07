"""The glossary and pickup skill share the successor contract."""
from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_glossary_defines_successor_and_links_pickup_rule():
    glossary = (ROOT / "docs/glossary.md").read_text(encoding="utf-8")
    match = re.search(r"^\*\*Successor\*\*:\n(.*?)(?=\n\*\*|\Z)", glossary, re.M | re.S)
    assert match, "glossary needs a successor entry"
    assert "../skills/pickup/SKILL.md#the-successor-rule" in match.group(1)
