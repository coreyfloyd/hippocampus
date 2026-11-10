"""Compaction preserves real work without subscribing to timers."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / 'scripts/lib/handoff.py'


@pytest.fixture
def runtime(tmp_path):
    env = os.environ | {
        'HANDOFF_STATE_DIR': str(tmp_path / 'handoffs'),
        'HANDOFF_LEDGER_DIR': str(tmp_path / 'ledger'),
        'HANDOFF_COMPACT_STATE_DIR': str(tmp_path / 'compact'),
        'HIPPOCAMPUS_CONFIG': str(tmp_path / 'config.json'),
        'CLAUDE_CODE_ENTRYPOINT': 'cli',
    }
    transcript = tmp_path / 'session.jsonl'
    transcript.write_text(json.dumps({'type': 'assistant', 'message': {'usage': {'input_tokens': 42}}}) + '\n')
    return tmp_path, env, transcript


def run(runtime, *args, payload=None):
    directory, env, _ = runtime
    return subprocess.run([sys.executable, str(ENGINE), *args], cwd=directory,
                          input=json.dumps(payload or {}), env=env, text=True,
                          capture_output=True, timeout=9)


def checkpoint(runtime, session='test'):
    return run(runtime, 'checkpoint', '--session-id', session, payload={
        'resume': {'headline': 'Continue parser work', 'next_action': 'Verify the parser',
                   'session_summary': 'Implemented parser validation.', 'open_loops': []},
        'spawned_processes': [], 'suggested_skills': ['pickup']})


def event(runtime, **extra):
    directory, _, transcript = runtime
    return dict(cwd=str(directory), session_id='test', transcript_path=str(transcript), **extra)


def test_pre_compact_writes_and_restores_current_facts_preserving_continuation(runtime):
    directory, _, _ = runtime
    subprocess.run(['git', 'init', '-q', str(directory)], check=True)
    path = directory / 'parser.py'
    path.write_text('work in progress\n')
    assert checkpoint(runtime).returncode == 0
    assert run(runtime, 'ledger-file', str(path), '--cwd', str(directory), '--session-id', 'test').returncode == 0
    assert run(runtime, 'ledger-ticket', '--ticket', 'https://example.com/issues/1', '--session-id', 'test').returncode == 0
    handoff_path = Path(run(runtime, 'resolve', str(directory), '--session-id', 'test').stdout.strip())
    previous = json.loads(handoff_path.read_text())
    ledger = directory / 'ledger/session-touched-paths.test.jsonl'
    with ledger.open('a') as handle:
        handle.write(json.dumps({'kind': 'touched_project', 'project': 'parser-project'}) + '\n')
    result = run(runtime, 'pre-compact', payload=event(runtime, trigger='auto'))
    assert result.returncode == 0, result.stderr
    current = json.loads(handoff_path.read_text())
    assert current['trigger'] == 'pre-compact'
    assert current['written_at'] > previous['written_at']
    assert current['resume']['next_action'] == previous['resume']['next_action']
    assert current['resume']['session_history'][:1] == previous['resume']['session_history']
    assert 'https://example.com/issues/1' in current['resume']['touched_tickets']
    assert 'parser-project' in current['resume']['touched_projects']
    assert str(path) in current['uncommitted_files']
    assert run(runtime, 'lint', str(handoff_path)).returncode == 0
    restored = run(runtime, 'post-compact', payload=event(runtime, source='compact'))
    json.loads(restored.stdout)  # One valid hook result.
    assert current['written_at'] in restored.stdout
    assert 'Verify the parser' in restored.stdout
    assert 'CronCreate' not in restored.stdout


def test_pre_compact_without_prior_handoff_and_headless_exclusion(runtime):
    directory, env, _ = runtime
    env['CLAUDE_CODE_ENTRYPOINT'] = 'headless'
    assert run(runtime, 'pre-compact', payload=event(runtime, trigger='auto')).returncode == 0
    assert not list((directory / 'handoffs').glob('*.json'))
    env['CLAUDE_CODE_ENTRYPOINT'] = 'cli'
    result = run(runtime, 'pre-compact', payload=event(runtime, trigger='auto'))
    assert result.returncode == 0, result.stderr
    paths = list((directory / 'handoffs').glob('*.json'))
    assert len(paths) == 1
    assert run(runtime, 'lint', str(paths[0])).returncode == 0


def test_pre_compaction_has_bounded_hook_runtime(runtime):
    directory, env, _ = runtime
    commands = directory / 'slow-bin'
    commands.mkdir()
    git = commands / 'git'
    # exec keeps the slow child in the process run() kills on an interrupted wait.
    git.write_text('#!/bin/sh\nexec sleep 20\n')
    git.chmod(0o755)
    env['PATH'] = str(commands) + os.pathsep + env['PATH']
    started = time.monotonic()
    result = run(runtime, 'pre-compact', payload=event(runtime, trigger='auto'))
    assert time.monotonic() - started < 9
    assert result.returncode == 0
    assert '8-second budget' in result.stderr
