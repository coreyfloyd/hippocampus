"""Close outcomes through the shared record, checkpoint, and report commands."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def run(tmp_path, module, *args, payload=None):
    env = os.environ | {'HANDOFF_LEDGER_DIR': str(tmp_path / 'ledger'),
                        'HANDOFF_PATH': str(tmp_path / 'checkpoint.json'),
                        'CLAUDE_CODE_ENTRYPOINT': 'cli', 'HIPPOCAMPUS_HARNESS': 'claude', 'CODEX_THREAD_ID': ''}
    return subprocess.run([sys.executable, str(ROOT / 'scripts/lib' / module), *map(str, args)],
                          input=json.dumps(payload) if payload is not None else None,
                          text=True, capture_output=True, env=env)


def setup(tmp_path):
    stub = tmp_path / 'store.py'
    stub.write_text('''import json, sys
from pathlib import Path
r = json.load(sys.stdin)
p = Path(__file__).with_name('calls.jsonl')
with p.open('a') as f: f.write(json.dumps(r) + '\\n')
ticket = 'https://github.com/example/project/issues/7'
state = {'ticket': ticket, 'state': 'closed', 'close_outcomes': [
    {'kind': 'milestone', 'title': 'Launch', 'state': 'closed', 'done': 4, 'total': 4},
    {'kind': 'epic', 'title': 'Session records', 'state': 'open', 'done': 3, 'total': 5}]}
if r['operation'] == 'read':
    print(json.dumps({'status': 'read', 'tickets': [state for t in r['tickets']]}))
elif r['operation'] == 'lookup': print(json.dumps({'status': 'not_found'}))
else: print(json.dumps({'status': 'saved', 'receipt': {'identity': r['identity'],
    'destination': ticket}, 'tickets': [state]}))
''')
    profile = tmp_path / 'profile.md'
    profile.write_text('```checklist-profile\n' + json.dumps({'name': 'user', 'record_writes': {
        'tickets': {'command': [sys.executable, str(stub)]}}}) + '\n```\n')
    source = {'subject': {'session_id': 'session', 'working_directory': str(tmp_path)},
              'resume': {'headline': 'Records', 'next_action': 'Finish', 'session_summary': 'Recorded ticket progress.',
                         'open_loops': []}}
    return profile, source


def record(tmp_path, profile, source, operation='record', rows=None):
    path = tmp_path / 'source.json'
    path.write_text(json.dumps(source))
    filing = tmp_path / 'filing.json'
    filing.write_text(json.dumps(rows or []))
    return run(tmp_path, 'checklist.py', operation, '--user-profile', profile,
               '--handoff', path, '--filing', filing)


def checkpoint(tmp_path, source):
    result = run(tmp_path, 'handoff.py', 'checkpoint', '--cwd', tmp_path, '--session-id', 'session', payload=source)
    assert result.returncode == 0, result.stderr
    return json.loads((tmp_path / 'checkpoint.json').read_text())


def report(tmp_path, source):
    path = tmp_path / 'report-source.json'
    path.write_text(json.dumps(source))
    results = tmp_path / 'results.json'
    results.write_text('[]')
    result = run(tmp_path, 'checklist.py', 'report', '--handoff', path, '--results', results)
    return json.loads(result.stdout)


def test_close_is_durable_through_compaction_and_report(tmp_path):
    profile, source = setup(tmp_path)
    source['session_items'] = [{'type': 'progress', 'context': 'Close the finished ticket.',
        'session_id': 'session', 'produced_at': '2026-11-01T12:00:00Z', 'disposition': 'record',
        'anchor': {'ticket': 'https://github.com/example/project/issues/7'}}]
    result = record(tmp_path, profile, source, rows=[{'index': 0, 'rule': 'R2', 'status': 'filed', 'read_status': 'ok'}])
    assert result.returncode == 0, result.stderr
    # Compaction supplies no ticket facts: the writer must recover the ledger.
    saved = checkpoint(tmp_path, setup(tmp_path)[1])
    outcomes = saved['resume']['close_outcomes']
    assert len(outcomes) == 2
    assert outcomes[0]['triggering_ticket'].endswith('/7')
    assert outcomes[0]['produced_at']
    assert saved['resume']['touched_tickets'] == ['https://github.com/example/project/issues/7']
    line = report(tmp_path, saved)['outcome_line']
    assert 'Launch' in line and 'closed' in line and '4 of 4' in line
    assert 'Session records' in line and '3 of 5' in line
    assert '\n' not in line


def test_no_close_has_explicit_one_line_outcome(tmp_path):
    _, source = setup(tmp_path)
    assert report(tmp_path, checkpoint(tmp_path, source))['outcome_line'] == 'No milestone or epic closed or moved this session.'


def test_wrap_reads_only_touched_and_recovers_out_of_band_close(tmp_path):
    profile, source = setup(tmp_path)
    source['resume']['touched_tickets'] = ['https://github.com/example/project/issues/7']
    result = record(tmp_path, profile, source, operation='file')
    assert result.returncode == 0, result.stderr
    saved = json.loads(result.stdout)
    assert len(saved['resume']['close_outcomes']) == 2
    calls = [json.loads(line) for line in (tmp_path / 'calls.jsonl').read_text().splitlines()]
    assert calls == [{'operation': 'read', 'kind': 'tickets', 'tickets': source['resume']['touched_tickets']}]
    again = record(tmp_path, profile, saved, operation='file')
    assert again.returncode == 0, again.stderr
    assert len(json.loads(again.stdout)['resume']['close_outcomes']) == 2


def test_ticket_read_is_recorded_without_a_write(tmp_path):
    setup(tmp_path)
    result = run(tmp_path, 'handoff.py', 'ledger-ticket', '--session-id', 'session',
                 '--ticket', 'https://github.com/example/project/issues/7')
    assert result.returncode == 0, result.stderr
    assert checkpoint(tmp_path, setup(tmp_path)[1])['resume']['touched_tickets'] == ['https://github.com/example/project/issues/7']


def test_wrap_without_touched_tickets_never_calls_store(tmp_path):
    profile, source = setup(tmp_path)
    result = record(tmp_path, profile, source, operation='file')
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / 'calls.jsonl').exists()


def test_wrap_read_failure_is_reported_and_fails(tmp_path):
    profile, source = setup(tmp_path)
    (tmp_path / 'store.py').write_text("import json; print(json.dumps({'status': 'failed', 'error': 'offline'}))")
    source['resume']['touched_tickets'] = ['https://github.com/example/project/issues/7']
    result = record(tmp_path, profile, source, operation='file')
    assert result.returncode == 1
    assert 'offline' in json.loads(result.stdout)['filing']['failures'][0]


def test_checkpoint_retains_carried_ticket_facts_in_ledger(tmp_path):
    _, source = setup(tmp_path)
    source['resume']['touched_tickets'] = ['https://github.com/example/project/issues/7']
    source['resume']['close_outcomes'] = [{'kind': 'epic', 'title': 'Carried', 'state': 'closed',
        'done': 1, 'total': 1, 'triggering_ticket': source['resume']['touched_tickets'][0],
        'produced_at': '2026-11-01T12:00:00Z'}]
    first = checkpoint(tmp_path, source)
    second = checkpoint(tmp_path, setup(tmp_path)[1])
    assert second['resume']['close_outcomes'] == first['resume']['close_outcomes']
    assert second['resume']['touched_tickets'] == first['resume']['touched_tickets']


def test_ticket_hook_records_read_in_both_tools(tmp_path):
    transcript = tmp_path / 'interactive.jsonl'
    transcript.write_text(json.dumps({'type': 'session_meta', 'payload': {'id': 'session', 'source': 'vscode'}}) + '\n')
    for module in ('handoff.py', '../codex-hook.py'):
        event = {'session_id': 'session', 'cwd': str(tmp_path), 'hook_event_name': 'PostToolUse',
                 'transcript_path': str(transcript), 'tool_name': 'record_read', 'tool_input': {'ticket': 'https://github.com/example/project/issues/7'},
                 'tool_response': {'exit_code': 0}}
        result = run(tmp_path, module, 'ledger-record', payload=event)
        assert result.returncode == 0, result.stderr
        saved = checkpoint(tmp_path, setup(tmp_path)[1])
        assert saved['resume']['touched_tickets'] == ['https://github.com/example/project/issues/7']
        # Independent ledgers prove each tool took the event.
        for path in (tmp_path / 'ledger').glob('*'):
            path.unlink()


def test_wrap_rejects_extra_ticket_in_read_response(tmp_path):
    profile, source = setup(tmp_path)
    source['resume']['touched_tickets'] = ['https://github.com/example/project/issues/8']
    result = record(tmp_path, profile, source, operation='file')
    assert result.returncode == 1
    saved = json.loads(result.stdout)
    assert 'exactly the touched tickets' in saved['filing']['failures'][0]
    assert saved['resume']['close_outcomes'] == []


def test_reused_receipt_recovers_outcomes_without_writing(tmp_path):
    profile, source = setup(tmp_path)
    stub = tmp_path / 'store.py'
    text = stub.read_text().replace("print(json.dumps({'status': 'not_found'}))", "print(json.dumps({'status': 'found', 'receipt': {'identity': r['identity'], 'destination': ticket}, 'tickets': [state]}))")
    stub.write_text(text)
    source['session_items'] = [{'type': 'progress', 'context': 'Close the finished ticket.',
        'session_id': 'session', 'produced_at': '2026-11-01T12:00:00Z', 'disposition': 'record'}]
    rows = [{'index': 0, 'rule': 'R2', 'status': 'filed', 'read_status': 'ok'}]
    first = record(tmp_path, profile, source, rows=rows)
    second = record(tmp_path, profile, source, rows=rows)
    assert first.returncode == second.returncode == 0
    assert json.loads(first.stdout)['resume']['close_outcomes'] == json.loads(second.stdout)['resume']['close_outcomes']
    calls = [json.loads(line) for line in (tmp_path / 'calls.jsonl').read_text().splitlines()]
    assert [r['operation'] for r in calls] == ['lookup', 'lookup']


def test_invalid_outcome_checkpoint_still_writes_and_reports_validation(tmp_path):
    _, source = setup(tmp_path)
    source['resume']['close_outcomes'] = [{'kind': 'invalid'}]
    result = run(tmp_path, 'handoff.py', 'checkpoint', '--cwd', tmp_path, '--session-id', 'session', payload=source)
    assert result.returncode == 1
    assert (tmp_path / 'checkpoint.json').exists()
    assert 'close outcome' in result.stderr


def test_reported_close_survives_missing_write_receipt(tmp_path):
    profile, source = setup(tmp_path)
    stub = tmp_path / 'store.py'
    stub.write_text(stub.read_text().replace("'identity': r['identity']", "'identity': {}"))
    source['session_items'] = [{'type': 'progress', 'context': 'Close the finished ticket.',
        'session_id': 'session', 'produced_at': '2026-11-01T12:00:00Z', 'disposition': 'record'}]
    result = record(tmp_path, profile, source, rows=[{'index': 0, 'rule': 'R2', 'status': 'filed', 'read_status': 'ok'}])
    assert result.returncode == 1
    assert json.loads(result.stdout)['filing']['items'][0]['status'] == 'uncertain'
    saved = checkpoint(tmp_path, setup(tmp_path)[1])
    assert len(saved['resume']['close_outcomes']) == 2


@pytest.mark.parametrize('operation', ['record', 'file'])
@pytest.mark.parametrize('malformed', ["state.pop('close_outcomes')",
                                       "state['close_outcomes'] = None",
                                       "state['close_outcomes'] = [{'kind': 'invalid'}]"])
def test_existing_close_does_not_bypass_response_validation(tmp_path, operation, malformed):
    profile, source = setup(tmp_path)
    source['resume']['touched_tickets'] = ['https://github.com/example/project/issues/7']
    initial = record(tmp_path, profile, source, operation='file')
    assert initial.returncode == 0, initial.stderr
    previous = json.loads(initial.stdout)['resume']['close_outcomes']
    stub = tmp_path / 'store.py'
    stub.write_text(stub.read_text().replace("if r['operation'] == 'read':", malformed + "\nif r['operation'] == 'read':"))
    source['session_items'] = [{'type': 'progress', 'context': 'Record the ticket close again.',
        'session_id': 'session', 'produced_at': '2026-11-01T13:00:00Z', 'disposition': 'record'}]
    rows = [{'index': 0, 'rule': 'R2', 'status': 'filed', 'read_status': 'ok'}] if operation == 'record' else []
    if operation == 'file':
        source.pop('session_items')
    result = record(tmp_path, profile, source, operation=operation, rows=rows)
    assert result.returncode == 1
    assert 'close' in ' '.join(json.loads(result.stdout)['filing']['failures'])
    saved = checkpoint(tmp_path, setup(tmp_path)[1])
    assert saved['resume']['close_outcomes'] == previous


@pytest.mark.parametrize('operation', ['record', 'file'])
def test_existing_ticket_keeps_new_individual_outcome_without_repeating_old_ones(tmp_path, operation):
    profile, source = setup(tmp_path)
    source['resume']['touched_tickets'] = ['https://github.com/example/project/issues/7']
    initial = record(tmp_path, profile, source, operation='file')
    assert initial.returncode == 0, initial.stderr
    previous = json.loads(initial.stdout)['resume']['close_outcomes']
    stub = tmp_path / 'store.py'
    addition = "state['close_outcomes'].extend([state['close_outcomes'][0], " + repr({
        'kind': 'epic', 'title': 'Follow-up', 'state': 'open', 'done': 1, 'total': 2}) + "])"
    stub.write_text(stub.read_text().replace("if r['operation'] == 'read':", addition + "\nif r['operation'] == 'read':"))
    source['session_items'] = [{'type': 'progress', 'context': 'Record a further outcome for the ticket.',
        'session_id': 'session', 'produced_at': '2026-11-01T13:00:00Z', 'disposition': 'record'}]
    rows = [{'index': 0, 'rule': 'R2', 'status': 'filed', 'read_status': 'ok'}] if operation == 'record' else []
    if operation == 'file':
        source.pop('session_items')
    for _ in range(2):
        result = record(tmp_path, profile, source, operation=operation, rows=rows)
        assert result.returncode == 0, result.stderr
        outcomes = json.loads(result.stdout)['resume']['close_outcomes']
        assert outcomes[:2] == previous
        assert len(outcomes) == 3
        assert outcomes[2]['title'] == 'Follow-up'
    saved = checkpoint(tmp_path, setup(tmp_path)[1])
    assert saved['resume']['close_outcomes'] == outcomes
    assert 'Follow-up' in report(tmp_path, saved)['outcome_line']
