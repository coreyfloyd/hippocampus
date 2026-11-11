"""Exercise isolation and its failure guard entirely inside controlled homes."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SURFACES = ('HOME', 'XDG_CONFIG_HOME', 'XDG_STATE_HOME', 'XDG_CACHE_HOME', 'XDG_DATA_HOME',
            'CODEX_HOME', 'CLAUDE_CONFIG_DIR', 'HIPPOCAMPUS_CONFIG', 'HANDOFF_STATE_DIR',
            'HANDOFF_LEDGER_DIR', 'HANDOFF_TIMER_DIR', 'HANDOFF_COMPACT_STATE_DIR', 'CHECKLIST_STATE_DIR')


def test_fixture_subprocesses_inherit_isolated_state(tmp_path):
    result = subprocess.run([sys.executable, '-c', 'import json,os; print(json.dumps(dict(os.environ)))'],
                            capture_output=True, text=True, check=True)
    environment = json.loads(result.stdout)
    for key in SURFACES:
        assert key in environment, f'unisolated state surface: {key}'
        root = tmp_path.parent if key == 'HOME' else tmp_path
        assert Path(environment[key]).is_relative_to(root), f'unisolated state surface: {key}'
    for key in ('HANDOFF_PATH', 'HANDOFF_GUARD_OVERRIDE_PATH', 'HANDOFF_GUARD_OVERRIDE_LEDGER'):
        assert key not in environment


@pytest.mark.parametrize('surface,omit,expression', [
    ('handoffs', ['HANDOFF_STATE_DIR'], 'Path(h.state_dir()) / "probe.json"'),
    ('ledger', ['HANDOFF_LEDGER_DIR', 'HANDOFF_STATE_DIR'], 'Path(h.ledger_path("probe"))'),
    ('timers', ['HANDOFF_TIMER_DIR', 'HANDOFF_STATE_DIR'], 'h.timer_file("probe", ".receipt.json")'),
    ('compaction', ['HANDOFF_COMPACT_STATE_DIR'], 'Path(os.path.expanduser(h.COMPACT_STATE_DIR)) / "probe.json"'),
    ('checklist', ['CHECKLIST_STATE_DIR'], 'Path("~/.local/state/hippocampus/checklist").expanduser() / "probe.json"'),
    ('config', ['HIPPOCAMPUS_CONFIG', 'XDG_CONFIG_HOME'], 'Path(h.config_path())'),
    ('claude', ['CLAUDE_CONFIG_DIR'], 'Path("~/.claude/probe.json").expanduser()'),
    ('codex', ['CODEX_HOME'], 'Path("~/.codex/probe.json").expanduser()'),
])
def test_guard_rejects_omitted_overrides_in_fixture_subprocess(tmp_path, surface, omit, expression):
    probe = tmp_path / 'probe'
    probe.mkdir()
    # Run the actual suite fixtures in a nested pytest process. Even the red
    # version without isolation sees only this controlled, disposable home.
    (probe / 'conftest.py').write_text((ROOT / 'tests/conftest.py').read_text())
    import shutil
    shutil.copytree(ROOT / 'tests/state_guard', probe / 'state_guard', ignore=shutil.ignore_patterns('__pycache__'))
    fake_home = tmp_path / 'controlled-home'
    fake_home.mkdir()
    sentinel = fake_home / 'sentinel'
    sentinel.write_text('controlled original home; never production')
    (probe / 'test_probe.py').write_text('''import os, subprocess, sys
from pathlib import Path

def test_fixture_omitted_override(monkeypatch):
    for key in OMIT:
        monkeypatch.delenv(key, raising=False)
    script = "import os,sys; from pathlib import Path; sys.path.insert(0, ENGINE); import handoff as h; target=EXPRESSION; target.parent.mkdir(parents=True,exist_ok=True); target.write_text('{}')"
    script = script.replace('ENGINE', repr(ENGINE)).replace('EXPRESSION', EXPRESSION)
    subprocess.run([sys.executable, '-c', script], check=True)
'''.replace('OMIT', repr(omit)) +
        '\nENGINE = ' + repr(str(ROOT / 'scripts/lib')) + '\nEXPRESSION = ' + repr(expression) + '\n')
    environment = os.environ | {'HOME': str(fake_home)}
    result = subprocess.run([sys.executable, '-m', 'pytest', '-q', str(probe),
                             '--basetemp', str(tmp_path / 'nested-temp')],
                            env=environment, capture_output=True, text=True, timeout=30)
    assert result.returncode == 1, result.stdout + result.stderr
    assert 'unisolated state write' in result.stdout, result.stdout + result.stderr
    assert sentinel.read_text() == 'controlled original home; never production'


@pytest.mark.parametrize('operation', [
    "target.write_text('changed')",
    "target.unlink()",
    "(target.parent / 'new-dir').mkdir()",
    "source.replace(target)",
])
def test_subprocess_guard_blocks_explicit_state_writes_before_mutation(tmp_path, operation):
    protected = tmp_path / 'controlled-real-state'
    protected.mkdir()
    sentinel = protected / 'sentinel'
    sentinel.write_text('untouched')
    source = tmp_path / 'replacement'
    source.write_text('replacement')
    environment = os.environ | {
        'PYTHONPATH': str(ROOT / 'tests/state_guard'),
        'HIPPOCAMPUS_TEST_PROTECTED_STATE': json.dumps([str(protected)]),
    }
    script = 'from pathlib import Path; target=Path(' + repr(str(sentinel)) + '); source=Path(' + repr(str(source)) + '); ' + operation
    result = subprocess.run([sys.executable, '-c', script], env=environment, capture_output=True, text=True)
    assert result.returncode != 0, result.stdout + result.stderr
    assert 'unisolated state write' in result.stderr
    assert sentinel.read_text() == 'untouched'
    assert list(protected.iterdir()) == [sentinel]
