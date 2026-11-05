"""Timed checkpoints through the same command seams used by both harnesses."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / 'scripts/lib/handoff.py'
PROMPT = ROOT / 'scripts/lib/timed-checkpoint-prompt.txt'


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


@pytest.mark.parametrize('harness', ['claude', 'codex'])
@pytest.mark.parametrize('tokens,below', [(199999, True), (200000, False), (200001, False)])
def test_token_boundary(runtime, harness, tokens, below):
    _, env, transcript = runtime
    env['HIPPOCAMPUS_HARNESS'] = harness
    row = {'type': 'assistant', 'message': {'usage': {'input_tokens': tokens - 20,
           'cache_creation_input_tokens': 10, 'cache_read_input_tokens': 10}}}
    if harness == 'codex':
        row = {'type': 'event_msg', 'payload': {'type': 'token_count', 'info': {
            'model_context_window': 1000000, 'last_token_usage': {'input_tokens': tokens, 'cached_input_tokens': tokens}}}}
    transcript.write_text(json.dumps(row) + '\n')
    result = run(runtime, 'timed-checkpoint-check', '--transcript-path', str(transcript))
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {'tokens': tokens, 'limit': 200000, 'below_limit': below}


def test_limit_setting_and_unknown_usage(runtime):
    directory, _, transcript = runtime
    (directory / 'config.json').write_text(json.dumps({'timed_checkpoint_token_limit': 42}))
    result = run(runtime, 'timed-checkpoint-check', '--transcript-path', str(transcript))
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['below_limit'] is False
    transcript.write_text('not json\n')
    result = run(runtime, 'timed-checkpoint-check', '--transcript-path', str(transcript))
    assert result.returncode == 2
    assert 'unknown' in result.stderr.lower()


@pytest.mark.parametrize('key,value', [('timed_checkpoint_minutes', 0), ('timed_checkpoint_minutes', True),
    ('timed_checkpoint_token_limit', -1), ('timed_checkpoint_token_limit', 1.5)])
def test_invalid_settings_rejected(runtime, key, value):
    directory, _, _ = runtime
    (directory / 'config.json').write_text(json.dumps({key: value}))
    result = run(runtime, 'config-get', key)
    assert result.returncode == 2
    assert key in result.stderr


def test_claude_schedule_output_replaces_job_and_uses_single_prompt(runtime):
    directory, _, _ = runtime
    (directory / 'config.json').write_text(json.dumps({'timed_checkpoint_minutes': 17}))
    assert run(runtime, 'claude-timer-set', '--session-id', 'test', '--job-id', 'previous-job').returncode == 0
    result = checkpoint(runtime)
    assert result.returncode == 0, result.stderr
    for text in ['CronDelete', 'previous-job', 'CronCreate', 'recurring: false', 'session-only', '17 minutes', 'pinned']:
        assert text in result.stdout
    prompt = run(runtime, 'timed-checkpoint-prompt', '--session-id', 'test')
    assert prompt.returncode == 0, prompt.stderr
    assert prompt.stdout.strip() in result.stdout
    assert 'below_limit' in prompt.stdout and 'otherwise do nothing' in prompt.stdout
    assert 'timed-checkpoint-check' in PROMPT.read_text()
    skill = (ROOT / 'skills/checkpoint/SKILL.md').read_text()
    assert 'CronCreate' in skill and 'CronDelete' in skill
    assert 'timed-checkpoint-prompt' in skill


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
    json.loads(restored.stdout)  # One valid hook result, including the schedule.
    assert current['written_at'] in restored.stdout
    assert 'Verify the parser' in restored.stdout
    assert 'CronCreate' in restored.stdout


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


def test_codex_timer_fires_once_after_replacement_and_retains_session_context(runtime):
    directory, env, transcript = runtime
    env.update(HIPPOCAMPUS_HARNESS='codex', CODEX_THREAD_ID='test')
    transcript.write_text(json.dumps({'type': 'session_meta', 'payload': {'id': 'test', 'source': 'cli'}}) + '\n' + json.dumps({'type': 'event_msg', 'payload': {'type': 'token_count', 'info': {'model_context_window': 1000000, 'last_token_usage': {'input_tokens': 42}}}}) + '\n')
    commands = directory / 'bin'
    commands.mkdir()
    queue = commands / 'codex'
    calls = directory / 'queue.jsonl'
    queue.write_text('#!' + sys.executable + '\nimport json,sys\nfrom pathlib import Path\nwith Path(' + repr(str(calls)) + ').open("a") as f: f.write(json.dumps(sys.argv[1:])+"\\n")\n')
    queue.chmod(0o755)
    env['PATH'] = str(commands) + os.pathsep + env['PATH']
    config = directory / 'config.json'
    config.write_text(json.dumps({'timed_checkpoint_minutes': 2}))
    assert run(runtime, 'context-guard', payload=event(runtime)).returncode == 0
    first = checkpoint(runtime)
    assert first.returncode == 0, first.stderr
    time.sleep(0.15)
    config.write_text(json.dumps({'timed_checkpoint_minutes': 1}))
    second = checkpoint(runtime)
    assert second.returncode == 0, second.stderr
    # Assert the real configured deadlines before advancing only the clock input
    # in the documented pending state; production intervals remain whole minutes.
    from datetime import datetime
    pending = Path(env['HANDOFF_TIMER_DIR']) / 'test.pending.json'
    state = json.loads(pending.read_text())
    handoff_path = Path(run(runtime, 'resolve', str(directory), '--session-id', 'test').stdout.strip())
    written = datetime.fromisoformat(json.loads(handoff_path.read_text())['written_at'].replace('Z', '+00:00'))
    assert state['due_at'] == written.timestamp() + 60
    import fcntl
    with pending.with_name('test.schedule.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state['due_at'] = time.time() + 0.3
        replacement = pending.with_suffix('.replacement')
        replacement.write_text(json.dumps(state))
        replacement.replace(pending)
    deadline = time.monotonic() + 5
    while not calls.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert calls.exists(), 'detached timer did not queue a message'
    time.sleep(2)
    messages = [json.loads(row) for row in calls.read_text().splitlines()]
    assert len(messages) == 1
    assert messages[0][:3] == ['queue', '--thread', 'test']
    prompt = run(runtime, 'timed-checkpoint-prompt', '--session-id', 'test')
    assert messages[0][4] == prompt.stdout.strip()
    checked = run(runtime, 'timed-checkpoint-check', '--session-id', 'test')
    assert checked.returncode == 0, checked.stderr
    assert json.loads(checked.stdout)['below_limit'] is True


def test_timer_defaults_and_latest_usage(runtime):
    _, _, transcript = runtime
    for key, expected in [('timed_checkpoint_minutes', 55), ('timed_checkpoint_token_limit', 200000)]:
        result = run(runtime, 'config-get', key)
        assert result.returncode == 0, result.stderr
        assert float(result.stdout) == expected
    with transcript.open('a') as handle:
        handle.write(json.dumps({'type': 'assistant', 'message': {'usage': {'input_tokens': 200000}}}) + '\n')
    result = run(runtime, 'timed-checkpoint-check', '--transcript-path', str(transcript))
    assert json.loads(result.stdout)['below_limit'] is False


@pytest.mark.parametrize('value', [-1, True, 'unknown'])
def test_invalid_usage_is_unknown_and_never_below_limit(runtime, value):
    _, _, transcript = runtime
    transcript.write_text(json.dumps({'type': 'assistant', 'message': {'usage': {'input_tokens': value}}}) + '\n')
    result = run(runtime, 'timed-checkpoint-check', '--transcript-path', str(transcript))
    assert result.returncode == 2
    assert 'unknown' in result.stderr.lower()
    assert not result.stdout


def test_claude_pinned_minute_is_calculated_from_write_time(runtime):
    from datetime import datetime, timedelta
    directory, _, _ = runtime
    (directory / 'config.json').write_text(json.dumps({'timed_checkpoint_minutes': 55}))
    result = checkpoint(runtime)
    assert result.returncode == 0, result.stderr
    path = Path(run(runtime, 'resolve', str(directory), '--session-id', 'test').stdout.strip())
    stamp = datetime.fromisoformat(json.loads(path.read_text())['written_at'].replace('Z', '+00:00'))
    due = stamp + timedelta(minutes=55)
    if due.second or due.microsecond:
        due = due.replace(second=0, microsecond=0) + timedelta(minutes=1)
    due = due.astimezone()
    assert f'cron: {due.minute} {due.hour} {due.day} {due.month} *' in result.stdout


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


@pytest.mark.parametrize('harness', ['claude', 'codex'])
@pytest.mark.parametrize('value', [0.5, 1.5, 1.0, 0, -1, True, '1', None])
def test_interval_requires_whole_minutes_in_both_tools(runtime, harness, value):
    directory, env, _ = runtime
    env['HIPPOCAMPUS_HARNESS'] = harness
    (directory / 'config.json').write_text(json.dumps({'timed_checkpoint_minutes': value}))
    result = run(runtime, 'config-get', 'timed_checkpoint_minutes')
    assert result.returncode == 2, result.stdout
    assert 'timed_checkpoint_minutes' in result.stderr
    assert 'whole number of minutes, at least 1' in result.stderr


@pytest.mark.parametrize('harness', ['claude', 'codex'])
def test_one_minute_is_a_valid_interval(runtime, harness):
    directory, env, _ = runtime
    env['HIPPOCAMPUS_HARNESS'] = harness
    (directory / 'config.json').write_text(json.dumps({'timed_checkpoint_minutes': 1}))
    result = run(runtime, 'config-get', 'timed_checkpoint_minutes')
    assert result.returncode == 0, result.stderr
    assert result.stdout == '1\n'


@pytest.mark.parametrize('written,now,expected', [
    ('2026-11-04T12:00:45Z', '2026-11-04T12:00:45Z', '2026-11-04T12:02:00+00:00'),
    ('2026-11-04T12:00:00Z', '2026-11-04T12:00:00Z', '2026-11-04T12:01:00+00:00'),
    ('2026-11-04T12:00:00.000001Z', '2026-11-04T12:00:00.000001Z', '2026-11-04T12:02:00+00:00'),
    ('2026-11-04T12:58:59Z', '2026-11-04T12:58:59Z', '2026-11-04T13:00:00+00:00'),
    ('2026-11-04T23:58:59Z', '2026-11-04T23:58:59Z', '2026-11-05T00:00:00+00:00'),
    ('2026-01-31T23:58:59Z', '2026-01-31T23:58:59Z', '2026-02-01T00:00:00+00:00'),
    ('2026-12-31T23:58:59Z', '2026-12-31T23:58:59Z', '2027-01-01T00:00:00+00:00'),
    ('2028-02-28T23:58:59Z', '2028-02-28T23:58:59Z', '2028-02-29T00:00:00+00:00'),
    ('2026-11-04T11:00:00Z', '2026-11-04T12:00:00Z', '2026-11-04T12:01:00+00:00'),
    ('2026-11-04T11:00:00Z', '2026-11-04T12:00:45Z', '2026-11-04T12:01:00+00:00'),
])
def test_claude_due_minute_rounds_up_and_remains_future(runtime, written, now, expected):
    from datetime import datetime, timedelta
    directory, env, _ = runtime
    env['TZ'] = 'UTC'
    (directory / 'config.json').write_text(json.dumps({'timed_checkpoint_minutes': 1}))
    # Use the real restore command and replace only its wall clock. Fixed dates
    # exercise calendar boundaries without waiting for the host's clock.
    path = Path(run(runtime, 'resolve', str(directory), '--session-id', 'test').stdout.strip())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'schema_version': 2, 'trigger': 'pre-compact',
        'written_at': written, 'resume': {'headline': 'Retained continuation'}}))
    driver = """
import sys
from datetime import datetime, timezone
sys.path.insert(0, sys.argv[1])
import handoff
frozen = datetime.fromisoformat(sys.argv[2].replace('Z', '+00:00'))
class Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return frozen.astimezone(tz) if tz else frozen.replace(tzinfo=None)
handoff.datetime = Clock
raise SystemExit(handoff.main(['post-compact']))
"""
    result = subprocess.run([sys.executable, '-c', driver, str(ENGINE.parent), now],
        cwd=directory, env=env, input=json.dumps(event(runtime, source='compact')),
        text=True, capture_output=True, timeout=9)
    assert result.returncode == 0, result.stderr
    context = json.loads(result.stdout)['hookSpecificOutput']['additionalContext']
    due = datetime.fromisoformat(expected)
    assert f'pinned to {due.isoformat(timespec="minutes")}' in context
    assert f'cron: {due.minute} {due.hour} {due.day} {due.month} *' in context
    assert due >= datetime.fromisoformat(written.replace('Z', '+00:00')) + timedelta(minutes=1)
    assert due > datetime.fromisoformat(now.replace('Z', '+00:00'))
