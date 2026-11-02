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


@pytest.mark.parametrize("contract", [
    "pending approvals", "pending replies", "granted scopes",
    "any other record keyed by session id",
])
def test_pickup_successor_section_names_each_contract(contract):
    pickup = (ROOT / "skills/pickup/SKILL.md").read_text(encoding="utf-8")
    match = re.search(r"^### The successor rule\n(.*?)(?=\n###? |\Z)", pickup, re.M | re.S)
    assert match, "pickup needs a general successor section"
    assert re.search(re.escape(contract), match.group(1)), contract


def test_pickup_leaves_contract_transfer_to_user_tools():
    pickup = (ROOT / "skills/pickup/SKILL.md").read_text(encoding="utf-8")
    section = pickup.split("### The successor rule", 1)[1].split("\n## ", 1)[0]
    assert "Pickup makes no record writes" in section
    assert "left to the user's own tools" in section
