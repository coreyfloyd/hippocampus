"""#910: pickup.py runs under scripts/pickup.sh's
bare `python3` invocation, where pydantic and python-dotenv are NOT
installed (same class of requirement as factory/run_trace.py, pinned in
factory/tests/test_run_trace.py::test_cli_imports_without_third_party_dependencies).
A future import of either would break every pickup invocation on a box
that never installed them, invisibly, since the dev/test environment (this
one, under uv) has both."""
import importlib.util
import subprocess
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "skills" / "pickup" / "scripts" / "pickup.py"


def test_module_imports_without_third_party_dependencies():
    probe = (
        "import sys, importlib.util;"
        "sys.modules['pydantic'] = None; sys.modules['dotenv'] = None;"
        "spec = importlib.util.spec_from_file_location('pickup', %r);"
        "mod = importlib.util.module_from_spec(spec);"
        "spec.loader.exec_module(mod)"
    ) % str(MODULE_PATH)
    completed = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True,
        env={"PATH": "/usr/bin:/bin"},
    )
    assert completed.returncode == 0, completed.stderr


# Poisoning two names only checks the imports that exist TODAY. #910 round 4
# moved the process execution into this module, adding subprocess use and
# concurrent.futures; the NEXT addition is what this guards against. Assert the
# property directly — every top-level import root is stdlib — rather than
# enumerating the packages we happen to know are absent.


def top_level_import_roots():
    import ast

    tree = ast.parse(MODULE_PATH.read_text())
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return sorted(roots)


def test_every_top_level_import_is_stdlib():
    """Checked by importing each root under `-S -E` (no site-packages, no
    PYTHONPATH), not against sys.stdlib_module_names: that name is 3.10+, and
    the interpreter this module has to survive on is /usr/bin/python3, which is
    3.9.6 on this box. `-S` is also the stronger check — it asks whether the
    import works WITHOUT third-party installs, which is the actual
    requirement, rather than whether a name appears on a list."""
    offenders = []
    for root in top_level_import_roots():
        probe = subprocess.run(
            [sys.executable, "-S", "-E", "-c", "import %s" % root],
            capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"},
        )
        if probe.returncode != 0:
            offenders.append(root)
    assert not offenders, (
        "non-stdlib import(s) %s would break every pickup invocation on a "
        "box that never installed them" % offenders
    )
