"""Inventory attribution recognizes source URLs without a personal owner dependency."""
import ast
from pathlib import Path
import re
import runpy

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE_PACKAGE = runpy.run_path(str(ROOT / "scripts/check-fold-names.py"))["OLD"]


def load_function(script, name):
    # Load only the pure classifier: the generator CLI requires historical clones.
    if script == "check-fold-names.py":
        return runpy.run_path(str(ROOT / "scripts" / script))[name]
    tree = ast.parse((ROOT / "scripts" / script).read_text())
    function = next(node for node in tree.body
                    if isinstance(node, ast.FunctionDef) and node.name == name)
    namespace = {"re": re}
    exec(compile(ast.Module(body=[function], type_ignores=[]), script, "exec"), namespace)
    return namespace[name]


@pytest.mark.parametrize("owner", ["example-owner", "sample-org", "fixture-user"])
@pytest.mark.parametrize("reference", ["blob", "commit"])
def test_inventory_classifies_historical_source_for_any_owner(owner, reference):
    assignment = load_function("generate-fold-inventory.py", "assignment")
    url = f"https://github.com/{owner}/{SOURCE_PACKAGE}/{reference}/{'a' * 40}/source.py"
    assert assignment("docs/source.md", url) == (59, "keep historical source attribution")


@pytest.mark.parametrize("owner", ["example-owner", "sample-org", "fixture-user"])
@pytest.mark.parametrize("reference", ["blob", "tree"])
def test_fold_audit_classifies_historical_source_for_any_owner(owner, reference):
    disposition = load_function("check-fold-names.py", "disposition")
    url = f"https://github.com/{owner}/{SOURCE_PACKAGE}/{reference}/{'a' * 40}/source.py"
    assert disposition("docs/architecture/session/runtime.html", url) == (
        "retained: immutable imported architecture source attribution")
