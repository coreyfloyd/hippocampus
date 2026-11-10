"""Manual timer cancellation and bounded keep-warm through shared command seams."""
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/lib'))
import handoff as h


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setenv('HANDOFF_STATE_DIR', str(tmp_path / 'handoffs'))
    monkeypatch.setenv('HANDOFF_TIMER_DIR', str(tmp_path / 'timers'))
    monkeypatch.setenv('HANDOFF_COMPACT_STATE_DIR', str(tmp_path / 'compact'))
    monkeypatch.setenv('CLAUDE_CODE_ENTRYPOINT', 'cli')
    return tmp_path


@pytest.mark.parametrize('orphan', [False, True])
def test_cancel_pending_and_orphan_idempotently(runtime, orphan):
    path = h.timer_file('test', '.pending.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'due_at': 1}) if not orphan else 'corrupt orphan')
    result = h.cancel_timer('test')
    assert result['cancelled'] is True
    assert not path.exists()
    assert h.read_json(str(h.timer_file('test', '.receipt.json')))['cancelled'] is True
    assert h.cancel_timer('test')['cancelled'] is False


def test_claude_cancellation_requires_native_delete(runtime):
    path = h.timer_file('test', '.claude.json')
    h.atomic_write(str(path), {'job_id': 'native-123'})
    result = h.cancel_timer('test')
    assert result['native_cancel_required'] is True
    assert 'CronDelete' in result['instructions'] and 'native-123' in result['instructions']
    assert path.exists()  # a local unlink cannot cancel the native job

@pytest.fixture(params=['claude', 'codex', 'desktop'])
def session(runtime, monkeypatch, request):
    harness = 'codex' if request.param in ('codex', 'desktop') else 'claude'
    monkeypatch.setenv('HIPPOCAMPUS_HARNESS', harness)
    transcript = runtime / 'session.jsonl'
    rows = []
    if harness == 'codex':
        rows.append({'type': 'session_meta', 'payload': {'id': 'test', 'source': 'appServer' if request.param == 'desktop' else 'cli'}})
    transcript.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    h.remember_transcript({'session_id': 'test', 'transcript_path': str(transcript)})
    monkeypatch.setattr(h.time, 'time', lambda: 10000.0)
    monkeypatch.setattr(h.shutil, 'which', lambda _: '/bin/true')
    original_popen = h.subprocess.Popen
    monkeypatch.setattr(h.subprocess, 'Popen', lambda *a, **k: None if k.get('start_new_session') else original_popen(*a, **k))
    def incoming(text):
        row = ({'type': 'event_msg', 'payload': {'type': 'user_message', 'message': text}}
               if harness == 'codex' else {'type': 'user', 'message': {'content': text}})
        with transcript.open('a') as stream:
            stream.write(json.dumps(row) + '\n')
    incoming('Implement parser and await the requested build result')
    return transcript, incoming


def enable(runtime):
    return h.keep_warm('on', str(runtime), 'test')


def state():
    return h.read_json(str(h.timer_file('test', '.keep-warm.json')))


def test_enable_is_explicit_and_cannot_renew(runtime, session):
    result = enable(runtime)
    first = state()
    assert result['enabled'] is True
    assert first['due_at'] == first['activated_at'] + 55 * 60
    assert first['expires_at'] <= first['activated_at'] + 120 * 60
    enable(runtime)
    assert state() == first
    h.keep_warm('off', str(runtime), 'test')
    assert not h.timer_file('test', '.keep-warm.json').exists()


def test_first_empty_wake_off_and_no_handoff(runtime, session, monkeypatch):
    transcript, incoming = session
    enable(runtime)
    first = state()
    incoming(h.keep_warm_prompt('test', first['activation'], 1))
    monkeypatch.setattr(h.time, 'time', lambda: first['due_at'])
    result = h.keep_warm_wake('test', first['activation'], 1)
    assert result['checkpoint'] is False
    assert result['enabled'] is False
    assert not h.timer_file('test', '.pending.json').exists()
    assert not h.timer_file('test', '.keep-warm.json').exists()
    supplied = {'resume': {'headline': 'empty wake', 'open_loops': []}}
    h.checkpoint(supplied, str(runtime), 'test', 'manual')
    assert not list((runtime / 'handoffs').glob('*.json'))
    h.guard_decide(h.resolve_path(str(runtime), 'test'), h.ledger_path('test'), str(runtime), 'test')
    assert not list((runtime / 'handoffs').glob('*.json'))
    payload = {'cwd': str(runtime), 'session_id': 'test', 'transcript_path': str(transcript)}
    h.pre_compact(payload)
    assert not list((runtime / 'handoffs').glob('*.json'))


def test_productive_wakes_have_fixed_budget(runtime, session, monkeypatch):
    _, incoming = session
    enable(runtime)
    first = state()
    incoming('Build finished; resolve the reported parser error')
    incoming(h.keep_warm_prompt('test', first['activation'], 1))
    monkeypatch.setattr(h.time, 'time', lambda: first['due_at'])
    result = h.keep_warm_wake('test', first['activation'], 1)
    assert result['checkpoint'] is True and result['enabled'] is True
    second = state()
    assert second['wakes'] == 1
    assert second['due_at'] == first['activated_at'] + 110 * 60
    assert second['expires_at'] == first['expires_at']
    enable(runtime)
    assert state() == second
    # Duplicate or stale deliveries cannot spend/replenish the budget.
    h.keep_warm_wake('test', first['activation'], 1)
    assert state() == second
    incoming('The requested review has arrived; apply its correction')
    incoming(h.keep_warm_prompt('test', first['activation'], 2))
    monkeypatch.setattr(h.time, 'time', lambda: second['due_at'])
    result = h.keep_warm_wake('test', first['activation'], 2)
    assert result['checkpoint'] is True and result['enabled'] is False
    assert not h.timer_file('test', '.keep-warm.json').exists()
    assert h.keep_warm_wake('test', first['activation'], 3)['checkpoint'] is False


@pytest.mark.parametrize('damage', ['expired', 'missing-transcript', 'invalid-state', 'early', 'stale'])
def test_invalid_wakes_safe(runtime, session, monkeypatch, damage):
    transcript, incoming = session
    enable(runtime)
    first = state()
    incoming('A result arrived')
    if damage == 'expired':
        now = first['expires_at'] + 1
    else:
        now = first['due_at']
    if damage == 'missing-transcript':
        transcript.unlink()
    if damage == 'invalid-state':
        h.timer_file('test', '.keep-warm.json').write_text('{broken')
    if damage == 'early':
        now = first['due_at'] - 1
    monkeypatch.setattr(h.time, 'time', lambda: now)
    activation = 'obsolete' if damage == 'stale' else first['activation']
    assert h.keep_warm_wake('test', activation, 1)['checkpoint'] is False
    if damage in ('early', 'stale'):
        assert state() == first
    else:
        assert not h.timer_file('test', '.keep-warm.json').exists()


def test_headless_cannot_enable(runtime, monkeypatch):
    monkeypatch.setenv('CLAUDE_CODE_ENTRYPOINT', 'headless')
    assert h.keep_warm('on', str(runtime), 'test')['enabled'] is False
    assert not h.timer_file('test', '.pending.json').exists()


def test_preservation_never_subscribes(runtime, session, capsys):
    transcript, _ = session
    payload = {'cwd': str(runtime), 'session_id': 'test', 'transcript_path': str(transcript)}
    h.post_compact(payload | {'source': 'startup'})
    result = h.checkpoint({'resume': {'headline': 'parser work', 'next_action': 'await build', 'history_entry': 'Implemented parser validation.', 'open_loops': []}}, str(runtime), 'test', 'manual')
    assert result.exit_code == 0, result.errors
    h.context_guard(payload)
    h.pre_compact(payload)
    h.post_compact(payload | {'source': 'compact'})
    assert 'CronCreate' not in result.output + capsys.readouterr().out
    assert not h.timer_file('test', '.pending.json').exists()
    assert not h.timer_file('test', '.keep-warm.json').exists()


def test_cancel_serializes_with_replacement(runtime, session):
    import threading
    import time
    enable(runtime)
    old = state()
    started = threading.Event()
    finished = threading.Event()
    def cancel():
        started.set()
        h.cancel_timer('test')
        finished.set()
    with h.timer_lock('test'):
        thread = threading.Thread(target=cancel)
        thread.start()
        assert started.wait(1)
        assert not finished.wait(.02)
    thread.join(2)
    assert finished.is_set()
    enable(runtime)
    replacement = state()
    assert replacement['activation'] != old['activation']
    h.keep_warm_wake('test', old['activation'], 1)
    assert state() == replacement


def test_cancelled_worker_never_queues(runtime, session, monkeypatch):
    enable(runtime)
    h.cancel_timer('test')
    calls = []
    monkeypatch.setattr(h.subprocess, 'run', lambda *a, **k: calls.append(a))
    h.wait_for_keep_warm(str(h.timer_file('test', '.pending.json')))
    assert calls == []


def test_worker_queues_once_and_releases_for_replacement(runtime, session, monkeypatch):
    from types import SimpleNamespace
    enable(runtime)
    first = state()
    if first['harness'] != 'codex':
        return
    monkeypatch.setattr(h.time, 'time', lambda: first['due_at'])
    calls = []
    def queue(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout='queued', stderr='')
    monkeypatch.setattr(h.subprocess, 'run', queue)
    path = str(h.timer_file('test', '.pending.json'))
    h.wait_for_keep_warm(path)
    h.wait_for_keep_warm(path)
    assert len(calls) == 1
    assert calls[0][1:4] == ['queue', '--thread', 'test']
    assert h.read_json(str(h.timer_file('test', '.receipt.json')))['queued'] is True


def test_native_job_registration_cannot_replace_newer_job(runtime, session, monkeypatch):
    enable(runtime)
    first = state()
    assert h.register_keep_warm_job('test', first['activation'], 1, 'old')['registered']
    h.cancel_timer('test')
    assert h.forget_cancelled_job('test', 'old')['forgotten']
    enable(runtime)
    second = state()
    assert h.register_keep_warm_job('test', second['activation'], 1, 'new')['registered']
    assert not h.forget_cancelled_job('test', 'old')['forgotten']
    late = h.register_keep_warm_job('test', first['activation'], 1, 'late')
    assert late['registered'] is False and 'CronDelete job late' in late['instructions']
    assert h.read_json(str(h.timer_file('test', '.claude.json')))['job_id'] == 'new'


def test_empty_wake_suppresses_percentage_guard(runtime, session, capsys):
    transcript, incoming = session
    enable(runtime)
    first = state()
    incoming(h.keep_warm_prompt('test', first['activation'], 1))
    # Enough real context to trigger either harness guard if the timer exclusion fails.
    with transcript.open('a') as stream:
        stream.write(json.dumps({'type': 'assistant', 'message': {'usage': {'input_tokens': 900000}}}) + '\n')
        stream.write(json.dumps({'type': 'event_msg', 'payload': {'type': 'token_count', 'info': {
            'model_context_window': 1000000, 'last_token_usage': {'input_tokens': 900000}}}}) + '\n')
        stream.write(json.dumps({'padding': 'x' * (512 * 1024)}) + '\n')
    h.context_guard({'session_id': 'test', 'cwd': str(runtime), 'transcript_path': str(transcript)})
    assert capsys.readouterr().out == ''


def test_wakes_do_not_renew_through_preservation(runtime, session, monkeypatch):
    transcript, incoming = session
    enable(runtime)
    first = state()
    incoming('The requested build result arrived; fixed parser failure')
    prompt = h.keep_warm_prompt('test', first['activation'], 1)
    incoming(prompt)
    monkeypatch.setattr(h.time, 'time', lambda: first['due_at'])
    assert h.keep_warm_wake('test', first['activation'], 1)['checkpoint']
    before = state()
    result = h.checkpoint({'resume': {'headline': 'Build fixed', 'history_entry': 'Fixed parser failure.', 'open_loops': []}}, str(runtime), 'test', 'manual')
    assert result.exit_code == 0, result.errors
    payload = {'cwd': str(runtime), 'session_id': 'test', 'transcript_path': str(transcript)}
    h.pre_compact(payload)
    h.post_compact(payload | {'source': 'compact'})
    assert state() == before


def test_explicit_off_invalidates_productive_wake_permission(runtime, session, monkeypatch):
    _, incoming = session
    enable(runtime)
    first = state()
    incoming('A requested result arrived')
    incoming(h.keep_warm_prompt('test', first['activation'], 1))
    monkeypatch.setattr(h.time, 'time', lambda: first['due_at'])
    h.keep_warm_wake('test', first['activation'], 1)
    assert not h.maintenance_only('test')
    h.cancel_timer('test')
    assert h.maintenance_only('test')


def test_productive_final_wake_cannot_self_enable(runtime, session, monkeypatch):
    _, incoming = session
    enable(runtime)
    first = state()
    for wake in (1, 2):
        current = state()
        incoming(f'Requested result {wake} arrived; apply the fix')
        incoming(h.keep_warm_prompt('test', first['activation'], wake))
        monkeypatch.setattr(h.time, 'time', lambda: current['due_at'])
        assert h.keep_warm_wake('test', first['activation'], wake)['checkpoint'] is True
    assert enable(runtime)['enabled'] is False
    assert not h.timer_file('test', '.keep-warm.json').exists()


def test_repeated_enable_command_is_not_new_work(runtime, session, monkeypatch):
    _, incoming = session
    enable(runtime)
    first = state()
    incoming('keep-warm on')
    enable(runtime)
    incoming(h.keep_warm_prompt('test', first['activation'], 1))
    monkeypatch.setattr(h.time, 'time', lambda: first['due_at'])
    assert h.keep_warm_wake('test', first['activation'], 1)['checkpoint'] is False


def test_compaction_summary_is_not_incoming_work(runtime, session, monkeypatch):
    transcript, incoming = session
    enable(runtime)
    first = state()
    if first['harness'] == 'claude':
        with transcript.open('a') as stream:
            stream.write(json.dumps({'type': 'user', 'isCompactSummary': True,
                'message': {'content': 'Summary of prior work; no new reply arrived'}}) + '\n')
    incoming(h.keep_warm_prompt('test', first['activation'], 1))
    monkeypatch.setattr(h.time, 'time', lambda: first['due_at'])
    assert h.keep_warm_wake('test', first['activation'], 1)['checkpoint'] is False


def test_unknown_activity_wake_cannot_create_stop_handoff(runtime, session, monkeypatch):
    transcript, incoming = session
    enable(runtime)
    first = state()
    transcript.unlink()
    monkeypatch.setattr(h.time, 'time', lambda: first['due_at'])
    assert not h.keep_warm_wake('test', first['activation'], 1)['checkpoint']
    path = h.resolve_path(str(runtime), 'test')
    h.guard_decide(path, h.ledger_path('test'), str(runtime), 'test')
    assert not Path(path).exists()


def test_invalid_transcript_locator_fails_closed(runtime, session, monkeypatch):
    enable(runtime)
    first = state()
    monkeypatch.setattr(h.time, 'time', lambda: first['due_at'])
    h.timer_file('test', '.context.json').write_text('[]')
    result = h.keep_warm_wake('test', first['activation'], 1)
    assert not result['checkpoint']


def test_delayed_first_wake_never_schedules_past_second_deadline(runtime, session, monkeypatch):
    _, incoming = session
    enable(runtime)
    first = state()
    incoming('A requested reply arrived')
    incoming(h.keep_warm_prompt('test', first['activation'], 1))
    monkeypatch.setattr(h.time, 'time', lambda: first['activated_at'] + 6601)
    result = h.keep_warm_wake('test', first['activation'], 1)
    assert result['checkpoint'] is True and result['enabled'] is False
    assert not h.timer_file('test', '.keep-warm.json').exists()
    assert 'CronCreate' not in result.get('instructions', '')


def test_native_registration_does_not_orphan_previous_job(runtime, session):
    enable(runtime)
    first = state()
    assert h.register_keep_warm_job('test', first['activation'], 1, 'kept')['registered']
    assert h.register_keep_warm_job('test', first['activation'], 1, 'kept')['registered']
    result = h.register_keep_warm_job('test', first['activation'], 1, 'duplicate')
    assert not result['registered']
    assert 'CronDelete job duplicate' in result['instructions']
    assert h.read_json(str(h.timer_file('test', '.claude.json')))['job_id'] == 'kept'


def test_cli_on_off_and_hook_entrypoints(runtime, session):
    import os
    import subprocess
    transcript, _ = session
    engine = ROOT / 'scripts/lib/handoff.py'
    payload = {'session_id': 'test', 'cwd': str(runtime), 'transcript_path': str(transcript)}
    for operation, source in [('post-compact', 'startup'), ('context-guard', ''),
                              ('pre-compact', ''), ('post-compact', 'compact')]:
        if os.environ['HIPPOCAMPUS_HARNESS'] == 'codex':
            argv = [sys.executable, str(ROOT / 'scripts/codex-hook.py'), operation]
        else:
            scripts = {'post-compact': 'post-compact-restore.sh', 'context-guard': 'context-guard.sh', 'pre-compact': 'pre-compact.sh'}
            argv = ['bash', str(ROOT / 'scripts' / scripts[operation])]
        result = subprocess.run(argv, input=json.dumps(payload | {'source': source}),
                                capture_output=True, text=True, cwd=runtime, timeout=10)
        assert result.returncode == 0, result.stderr
        assert 'CronCreate' not in result.stdout
        assert not h.timer_file('test', '.pending.json').exists()
    try:
        enabled = subprocess.run([sys.executable, str(engine), 'keep-warm', 'on', '--session-id', 'test'],
                                 capture_output=True, text=True, cwd=runtime, timeout=10)
        assert enabled.returncode == 0, enabled.stderr
        assert json.loads(enabled.stdout)['enabled']
    finally:
        disabled = subprocess.run([sys.executable, str(engine), 'keep-warm', 'off', '--session-id', 'test'],
                                  capture_output=True, text=True, cwd=runtime, timeout=10)
        assert disabled.returncode == 0, disabled.stderr
    assert not h.timer_file('test', '.pending.json').exists()


def test_duplicate_wake_cannot_reuse_preservation_permission(runtime, session, monkeypatch):
    _, incoming = session
    enable(runtime)
    first = state()
    incoming('A requested result arrived; fix applied')
    incoming(h.keep_warm_prompt('test', first['activation'], 1))
    monkeypatch.setattr(h.time, 'time', lambda: first['due_at'])
    assert h.keep_warm_wake('test', first['activation'], 1)['checkpoint']
    assert not h.keep_warm_wake('test', first['activation'], 1)['checkpoint']
    assert h.maintenance_only('test')


def test_malformed_native_record_can_be_acknowledged_without_losing_replacement(runtime):
    path = h.timer_file('test', '.claude.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('corrupt orphan')
    cancellation = h.cancel_timer('test')
    assert 'CronList' in cancellation['instructions']
    snapshot = cancellation['native_record']
    assert h.forget_cancelled_job('test', record=snapshot)['forgotten']
    assert not path.exists()
    path.write_text('another corrupt orphan')
    cancellation = h.cancel_timer('test')
    h.atomic_write(str(path), {'job_id': 'replacement'})
    assert not h.forget_cancelled_job('test', record=cancellation['native_record'])['forgotten']
    assert path.exists()


def test_productive_wake_retains_native_job_until_native_deletion(runtime, session, monkeypatch):
    _, incoming = session
    enable(runtime)
    first = state()
    h.register_keep_warm_job('test', first['activation'], 1, 'native-job')
    incoming('The requested result arrived')
    incoming(h.keep_warm_prompt('test', first['activation'], 1))
    monkeypatch.setattr(h.time, 'time', lambda: first['due_at'])
    result = h.keep_warm_wake('test', first['activation'], 1)
    assert h.timer_file('test', '.claude.json').exists()
    assert 'CronDelete job native-job' in result['instructions']
    assert h.forget_cancelled_job('test', 'native-job')['forgotten']


@pytest.mark.parametrize('command', [
    '<command-name>/hippocampus:keep-warm</command-name>\n<command-args>on</command-args>',
    'Use keep-warm on',
])
def test_skill_invocation_is_not_new_incoming_work(runtime, session, monkeypatch, command):
    _, incoming = session
    enable(runtime)
    first = state()
    incoming(command)
    enable(runtime)
    incoming(h.keep_warm_prompt('test', first['activation'], 1))
    monkeypatch.setattr(h.time, 'time', lambda: first['due_at'])
    assert not h.keep_warm_wake('test', first['activation'], 1)['checkpoint']


def test_supported_cancellation_cli_handles_legacy_orphan(runtime):
    import subprocess
    path = h.timer_file('old-session', '.pending.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('invalid orphan')
    argv = [sys.executable, str(ROOT / 'scripts/lib/handoff.py'), 'timer-cancel', '--session-id', 'old-session']
    result = subprocess.run(argv, capture_output=True, text=True, cwd=runtime, timeout=10)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['cancelled']
    assert not path.exists()
    receipt = h.read_json(str(h.timer_file('old-session', '.receipt.json')))
    assert receipt['cancelled']
    result = subprocess.run(argv, capture_output=True, text=True, cwd=runtime, timeout=10)
    assert result.returncode == 0 and not json.loads(result.stdout)['cancelled']


@pytest.mark.parametrize('failure', ['missing-codex', 'spawn-failure'])
def test_productive_rearm_failure_disables_but_preserves_checkpoint(runtime, session, monkeypatch, failure):
    _, incoming = session
    enable(runtime)
    first = state()
    if first['harness'] != 'codex':
        pytest.skip('Codex rearm failure seam')
    incoming('Requested build result arrived; fixed its failure')
    incoming(h.keep_warm_prompt('test', first['activation'], 1))
    monkeypatch.setattr(h.time, 'time', lambda: first['due_at'])
    with monkeypatch.context() as failing:
        if failure == 'missing-codex':
            failing.setattr(h.shutil, 'which', lambda _: None)
        else:
            def cannot_spawn(*args, **kwargs):
                raise OSError('controlled spawn failure')
            failing.setattr(h.subprocess, 'Popen', cannot_spawn)
        result = h.keep_warm_wake('test', first['activation'], 1)
    assert result['checkpoint'] is True and result['enabled'] is False
    assert result['error']
    assert not h.timer_file('test', '.keep-warm.json').exists()
    assert not h.timer_file('test', '.pending.json').exists()
    assert h.read_json(str(h.timer_file('test', '.wake-result.json'))) == result
    assert h.read_json(str(h.timer_file('test', '.receipt.json'))) == result
    assert not h.maintenance_only('test')
    assert not enable(runtime)['enabled']  # no self-renewal from the wake
    incoming('keep-warm on')
    assert enable(runtime)['enabled']  # a fresh explicit activation can recover
    assert state()['activation'] != first['activation']
