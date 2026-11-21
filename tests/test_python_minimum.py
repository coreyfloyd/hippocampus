"""The setup and wrap code loads on the oldest Python the README supports (3.9)."""
import ast
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
# Modules that knowledge setup, policy setup and every wrap or sweep auto-apply check import.
WRAP_AND_SETUP = ['scripts/compose_rules.py', 'scripts/knowledge_setup.py', 'scripts/policy_setup.py',
                  'scripts/lib/lessons.py', 'scripts/lib/knowledge.py', 'scripts/lib/checklist.py',
                  'scripts/lib/sweep.py']


def evaluated_union_annotations(tree):
    """Annotations written as `X | Y` that Python 3.9 evaluates and rejects at import time."""
    found = []
    for node in ast.walk(tree):
        annotations = []
        if isinstance(node, ast.AnnAssign):
            annotations.append(node.annotation)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            annotations.append(node.returns)
            arguments = node.args
            for argument in arguments.posonlyargs + arguments.args + arguments.kwonlyargs + [arguments.vararg, arguments.kwarg]:
                if argument is not None:
                    annotations.append(argument.annotation)
        for annotation in annotations:
            if annotation is not None and any(isinstance(part, ast.BinOp) and isinstance(part.op, ast.BitOr)
                                              for part in ast.walk(annotation)):
                found.append(node.lineno)
    return found


def defers_annotations(tree):
    return any(isinstance(node, ast.ImportFrom) and node.module == '__future__'
               and any(alias.name == 'annotations' for alias in node.names) for node in tree.body)


@pytest.mark.parametrize('relative', WRAP_AND_SETUP)
def test_union_annotations_are_deferred_for_python_3_9(relative):
    tree = ast.parse((ROOT / relative).read_text(encoding='utf-8'))
    lines = evaluated_union_annotations(tree)
    assert not lines or defers_annotations(tree), (
        f'{relative} uses `X | Y` annotations at lines {lines} without `from __future__ import annotations`')


def python_3_9():
    found = shutil.which('python3.9')
    if found:
        return found
    if shutil.which('uv'):
        result = subprocess.run(['uv', 'python', 'find', '3.9'], capture_output=True, text=True)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    return None


def test_setup_and_wrap_modules_import_on_python_3_9(tmp_path):
    interpreter = python_3_9()
    if interpreter is None:
        pytest.skip('no Python 3.9 interpreter available')
    script = ('import importlib.util, sys\n'
              f'sys.path[:0] = [{str(ROOT / "scripts")!r}, {str(ROOT / "scripts/lib")!r}]\n'
              f'for path in {[str(ROOT / relative) for relative in WRAP_AND_SETUP]!r}:\n'
              '    spec = importlib.util.spec_from_file_location("m_" + path.replace("/", "_"), path)\n'
              '    module = importlib.util.module_from_spec(spec)\n'
              '    sys.modules[spec.name] = module\n'
              '    spec.loader.exec_module(module)\n'
              'print("ok")\n')
    environment = {'HOME': str(tmp_path), 'XDG_CONFIG_HOME': str(tmp_path / 'config'), 'PATH': '/usr/bin:/bin'}
    result = subprocess.run([interpreter, '-c', script], capture_output=True, text=True, env=environment)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'ok'
