"""Compaction preserves real work without subscribing to timers."""
import json
import os
from pathlib import Path
import runpy
import shlex
import subprocess
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / 'scripts/lib/handoff.py'
CLAUDE_RESTORE = ROOT / 'scripts/post-compact-restore.sh'
CODEX_RESTORE = ROOT / 'scripts/codex-hook.py'
POST_COMPACT_CONTEXT_BYTES = runpy.run_path(
    str(ROOT / 'scripts/lib/restore_projection.py'))['POST_COMPACT_CONTEXT_BYTES']


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


def context(result):
    return json.loads(result.stdout)['hookSpecificOutput']['additionalContext']


def restore_through_adapters(runtime, payload):
    directory, env, transcript = runtime
    transcript.write_text(json.dumps({'type': 'session_meta', 'payload': {'id': payload['session_id'], 'source': 'cli'}}) + '\n')
    claude = subprocess.run(['bash', str(CLAUDE_RESTORE)], cwd=directory, input=json.dumps(payload),
                            env=env, text=True, capture_output=True, timeout=9)
    codex = subprocess.run([sys.executable, str(CODEX_RESTORE), 'post-compact'], cwd=directory,
                           input=json.dumps(payload), env=env, text=True, capture_output=True, timeout=9)
    assert claude.returncode == codex.returncode == 0
    return context(claude), context(codex)


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


def test_post_compact_keeps_small_restore_output_unchanged(runtime):
    directory, _, _ = runtime
    assert checkpoint(runtime).returncode == 0
    handoff_path = Path(run(runtime, 'resolve', str(directory), '--session-id', 'test').stdout.strip())
    handoff = json.loads(handoff_path.read_text())
    raw = json.dumps(handoff, separators=(',', ':'))

    restored = run(runtime, 'post-compact', payload=event(runtime, source='compact'))

    assert context(restored) == (
        'Session handoff — your last checkpoint:\n\n' + raw
        + "\n\nRe-validate before acting: this is a point-in-time pass-forward, not ground truth. "
        "Read any referenced ticket before executing it; query briefs scoped to what you're resuming; "
        "reconcile spawned_processes by identity (pid + started_at) before adopting or tearing down.")


def test_post_compact_bounds_large_restore_without_changing_canonical_handoff_or_ledger(runtime):
    directory, env, _ = runtime
    assert checkpoint(runtime).returncode == 0
    handoff_path = Path(run(runtime, 'resolve', str(directory), '--session-id', 'test').stdout.strip())
    handoff = json.loads(handoff_path.read_text())
    handoff['resume']['session_history'] = ['retained history ' + 'x' * 8_000]
    handoff_path.write_text(json.dumps(handoff, separators=(',', ':')))
    ledger_paths = list(Path(env['HANDOFF_LEDGER_DIR']).glob('*'))
    before_handoff = handoff_path.read_bytes()
    before_ledger = {path: path.read_bytes() for path in ledger_paths}

    claude, codex = restore_through_adapters(runtime, event(runtime, source='compact'))

    assert claude == codex
    assert len(claude.encode()) <= POST_COMPACT_CONTEXT_BYTES
    assert 'Verify the parser' in claude
    assert 'retained history ' not in claude
    assert str(handoff_path.resolve()) in claude
    assert 'read the relevant fields' in claude
    assert handoff_path.read_bytes() == before_handoff
    assert {path: path.read_bytes() for path in ledger_paths} == before_ledger


def test_post_compact_requires_targeted_read_when_active_continuation_cannot_fit(runtime):
    directory, _, _ = runtime
    assert checkpoint(runtime).returncode == 0
    handoff_path = Path(run(runtime, 'resolve', str(directory), '--session-id', 'test').stdout.strip())
    handoff = json.loads(handoff_path.read_text())
    oversized_action = 'do not silently settle this decision ' + 'x' * 8_000
    handoff['resume']['next_action'] = oversized_action
    handoff_path.write_text(json.dumps(handoff, separators=(',', ':')))

    restored = run(runtime, 'post-compact', payload=event(runtime, source='compact'))
    output = context(restored)

    assert len(output.encode()) <= POST_COMPACT_CONTEXT_BYTES
    assert oversized_action not in output
    assert 'targeted read required' in output
    assert 'resume.next_action' in output
    assert str(handoff_path.resolve()) in output
    assert 'Do NOT infer that omitted decisions, actions, or gates are absent, settled, or cleared.' in output


@pytest.mark.parametrize('version', [
    99, None, 'x' * 8_000, {'untrusted': 'x' * 8_000},
    ['x' * 8_000], '界' * 8_000,
], ids=['numeric', 'null', 'string', 'object', 'array', 'unicode'])
def test_post_compact_never_dumps_large_unknown_schema(runtime, version):
    directory, env, _ = runtime
    assert checkpoint(runtime).returncode == 0
    handoff_path = Path(run(runtime, 'resolve', str(directory), '--session-id', 'test').stdout.strip())
    handoff_path.write_text(json.dumps({'schema_version': version, 'untrusted': 'x' * 8_000}, separators=(',', ':')))
    before_handoff = handoff_path.read_bytes()
    before_ledger = {path: path.read_bytes() for path in Path(env['HANDOFF_LEDGER_DIR']).glob('*')}

    claude, codex = restore_through_adapters(runtime, event(runtime, source='compact'))

    assert claude == codex
    for output in (claude, codex):
        assert len(output.encode()) <= POST_COMPACT_CONTEXT_BYTES
        assert 'x' * 100 not in output
        assert 'unrecognized schema' in output
        assert 'targeted read required' in output
        assert str(handoff_path.resolve()) in output
        assert 'Read the relevant fields' in output
        assert 'Do NOT infer that omitted decisions, actions, or gates are absent, settled, or cleared.' in output
    assert handoff_path.read_bytes() == before_handoff
    assert {path: path.read_bytes() for path in Path(env['HANDOFF_LEDGER_DIR']).glob('*')} == before_ledger


def test_post_compact_malformed_handoff_does_not_echo_unbounded_input(runtime):
    directory, _, _ = runtime
    handoff_path = Path(run(runtime, 'resolve', str(directory), '--session-id', 'test').stdout.strip())
    handoff_path.parent.mkdir(parents=True, exist_ok=True)
    handoff_path.write_text('{"untrusted":"' + 'x' * 8_000)

    restored = run(runtime, 'post-compact', payload=event(runtime, source='compact'))
    output = context(restored)

    assert 'x' * 100 not in output
    assert 'did not parse as JSON' in output
    assert 'Do NOT trust it.' in output


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


@pytest.mark.parametrize('filename', ['session.json', "'" * 250, '界 space \" name.json'])
@pytest.mark.parametrize('branch', ['continuation', 'oversized', 'missing', 'unknown'])
@pytest.mark.parametrize('override', [False, True], ids=['state-dir', 'override'])
def test_long_canonical_path_fallback_is_bounded_and_recoverable(monkeypatch, branch, override, filename):
    # Valid Linux components and total path length; no host PATH_MAX dependency.
    directory = '/' + '/'.join(['segment' * 25] * 13)
    path = directory + '/' + filename
    monkeypatch.setenv('HANDOFF_STATE_DIR', directory)
    monkeypatch.delenv('HANDOFF_PATH', raising=False)
    if override:
        monkeypatch.setenv('HANDOFF_PATH', path)
    engine = runpy.run_path(str(ENGINE))
    data = {'resume': {'headline': 'Continue', 'next_action': 'Verify', 'open_loops': []}}
    if branch == 'oversized':
        data['resume']['next_action'] = 'unresolved decision ' * POST_COMPACT_CONTEXT_BYTES
    elif branch == 'missing':
        data['resume'] = None
    if branch == 'unknown':
        output = engine['_targeted_restore_context'](path, 'The handoff has an unrecognized schema.')
    else:
        output = engine['_bounded_restore_context'](data, path)
    assert len(output.encode()) <= POST_COMPACT_CONTEXT_BYTES
    assert 'before acting' in output
    assert 'Do NOT infer that omitted decisions, actions, or gates are absent, settled, or cleared.' in output
    assert 'targeted read required' in output
    assert path not in output
    if override:
        assert 'HANDOFF_PATH' in output
        recovered = os.environ['HANDOFF_PATH']
    else:
        assert 'handoff.py state-dir' in output
        assert shlex.quote(Path(path).name) in output
        quoted = output.split('with shell-quoted filename ', 1)[1].split(' in the directory returned', 1)[0]
        recovered = os.path.join(engine['state_dir'](), shlex.split(quoted)[0])
    assert recovered == path


@pytest.mark.parametrize('branch', ['continuation', 'oversized', 'missing', 'unknown', 'malformed'])
@pytest.mark.parametrize('override', [False, True], ids=['state-dir', 'override'])
def test_adapters_recover_long_handoff_paths_without_mutation(runtime, branch, override):
    directory, env, _ = runtime
    long_dir = directory
    while len(str(long_dir).encode()) <= POST_COMPACT_CONTEXT_BYTES:
        long_dir /= 'segment' * 25
    # macOS cannot open these Linux-valid absolute paths; renderer cases above
    # still run everywhere. CI on Linux exercises both actual hook transports.
    if len(str(long_dir).encode()) + 255 >= os.pathconf(directory, 'PC_PATH_MAX'):
        pytest.skip('host PATH_MAX cannot represent this Linux long-path fixture')
    env['HANDOFF_STATE_DIR'] = str(long_dir)
    env.pop('HANDOFF_PATH', None)
    if override:
        env['HANDOFF_PATH'] = str(long_dir / 'override.json')
    assert checkpoint(runtime).returncode == 0
    resolved = run(runtime, 'resolve', str(directory), '--session-id', 'test')
    assert resolved.returncode == 0, resolved.stderr
    handoff_path = Path(resolved.stdout.strip())
    handoff = json.loads(handoff_path.read_text())
    handoff['fixture_padding'] = ['retained ' * POST_COMPACT_CONTEXT_BYTES]
    if branch == 'oversized':
        handoff['resume']['next_action'] = 'unresolved decision ' * POST_COMPACT_CONTEXT_BYTES
    elif branch == 'missing':
        handoff['resume'] = None
    elif branch == 'unknown':
        handoff['schema_version'] = 'unknown' * POST_COMPACT_CONTEXT_BYTES
    serialized = json.dumps(handoff)
    assert len(serialized.encode()) > POST_COMPACT_CONTEXT_BYTES
    handoff_path.write_text('{bad json' if branch == 'malformed' else serialized)
    before = handoff_path.read_bytes()
    ledger = {p: p.read_bytes() for p in Path(env['HANDOFF_LEDGER_DIR']).glob('*')}
    claude, codex = restore_through_adapters(runtime, event(runtime, source='compact'))
    assert claude == codex
    assert len(claude.encode()) <= POST_COMPACT_CONTEXT_BYTES
    assert 'before acting' in claude
    assert 'Do NOT infer that omitted decisions, actions, or gates are absent, settled, or cleared.' in claude
    if branch == 'malformed':
        assert 'did not parse as JSON' in claude
        assert 'Do NOT trust it.' in claude
    if override:
        assert 'HANDOFF_PATH' in claude
        recovered = Path(env['HANDOFF_PATH'])
    else:
        assert 'handoff.py state-dir' in claude
        assert shlex.quote(handoff_path.name) in claude
        state = run(runtime, 'state-dir')
        assert state.returncode == 0, state.stderr
        recovered = Path(state.stdout.strip()) / handoff_path.name
    assert recovered == handoff_path
    assert recovered.read_bytes() == before
    assert {p: p.read_bytes() for p in Path(env['HANDOFF_LEDGER_DIR']).glob('*')} == ledger


def test_long_symlink_target_keeps_original_resolvable_filename(monkeypatch):
    engine = runpy.run_path(str(ENGINE))
    monkeypatch.delenv('HANDOFF_PATH', raising=False)
    monkeypatch.setenv('HANDOFF_STATE_DIR', '/configured')
    target = '/' + '/'.join(['segment' * 25] * 13) + '/different-target.json'
    monkeypatch.setattr(os.path, 'realpath', lambda path: target)
    output = engine['_targeted_restore_context']('/configured/original.json', 'Read required.')
    assert len(output.encode()) <= POST_COMPACT_CONTEXT_BYTES
    assert 'original.json' in output
    assert 'different-target.json' not in output
    assert 'handoff.py state-dir' in output
