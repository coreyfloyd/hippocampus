"""Project history must wait for successful ticket reads and a current summary."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def cli(script, *args, payload=None, env=None):
    return subprocess.run([sys.executable, str(ROOT / script), *map(str, args)],
                          input=json.dumps(payload) if payload is not None else None,
                          text=True, capture_output=True, env=env)


@pytest.fixture
def project_run(tmp_path):
    response = tmp_path / 'response.json'
    calls = tmp_path / 'calls.jsonl'
    store = tmp_path / 'store.py'
    store.write_text('''import json, sys
from pathlib import Path
r = json.load(sys.stdin)
with Path(sys.argv[1]).open('a') as f:
    f.write(json.dumps(r) + '\\n')
if r['operation'] == 'read':
    print(Path(sys.argv[2]).read_text())
elif r['operation'] == 'lookup':
    print(json.dumps({'status': 'not_found'}))
else:
    print(json.dumps({'status': 'saved', 'receipt': {'identity': r['identity'], 'destination': 'project history'}}))
''')
    profile = tmp_path / 'profile.json'
    profile.write_text(json.dumps({'name': 'test', 'record_writes': {
        kind: {'command': [sys.executable, str(store), str(calls), str(response)]}
        for kind in ('tickets', 'projects')}}))
    item = {'type': 'progress', 'context': 'Record session history', 'record_kind': 'projects',
            'session_id': 'writer', 'produced_at': '2026-11-01T12:00:00Z', 'disposition': 'record'}
    source = {'subject': {'session_id': 'writer', 'working_directory': str(tmp_path)},
              'resume': {'session_summary': 'Implemented the session history feature.',
                         'touched_tickets': ['example/project#7'], 'open_loops': [item]}}
    good = {'status': 'read', 'tickets': [{'ticket': 'example/project#7', 'state': 'open'}]}

    def run(data, ticket_response, *, tickets_bound=True, operation="file"):
        settings = json.loads(profile.read_text())
        if not tickets_bound:
            settings["record_writes"].pop("tickets", None)
        profile.write_text(json.dumps(settings))
        response.write_text(json.dumps(ticket_response))
        handoff, filing = tmp_path / 'source.json', tmp_path / 'filing.json'
        handoff.write_text(json.dumps(data))
        filing.write_text(json.dumps([{'index': 0, 'rule': 'R2', 'status': 'filed', 'read_status': 'ok'}]))
        result = cli('scripts/lib/checklist.py', operation, '--user-profile', profile,
                     '--handoff', handoff, '--filing', filing)
        return result, json.loads(result.stdout)

    return run, source, good, calls


@pytest.mark.parametrize('bad', [
    {'status': 'failed', 'error': 'Ticket store unavailable'},
    {'status': 'read', 'tickets': []},
    {'status': 'read', 'tickets': [None]},
    {'status': 'read', 'tickets': [{'ticket': 'example/project#7', 'state': 'closed', 'close_outcomes': None}]},
])
def test_project_item_waits_for_ticket_read_and_can_retry(project_run, bad):
    run, source, good, calls = project_run
    result, retained = run(source, bad)
    assert result.returncode == 1
    assert retained['resume']['open_loops'] == source['resume']['open_loops']
    assert retained['filing']['items'][0]['status'] == 'pending'
    assert 'ticket reread' in retained['filing']['items'][0]['error']
    assert [r['kind'] for r in map(json.loads, calls.read_text().splitlines())] == ['tickets']
    retried, saved = run(retained, good)
    assert retried.returncode == 0, retried.stderr
    assert saved['resume']['open_loops'] == []
    assert saved['filing']['items'][0]['status'] == 'filed'


def test_new_close_outcome_requires_agent_rewrite_before_project_write(project_run):
    run, source, good, calls = project_run
    closed = {'status': 'read', 'tickets': [{'ticket': 'example/project#7', 'state': 'closed',
        'closed_at': '2026-11-01T13:00:00Z', 'close_outcomes': [
            {'kind': 'epic', 'title': 'Session history', 'state': 'closed', 'done': 1, 'total': 1}]}]}
    first, retained = run(source, closed)
    assert first.returncode == 1
    assert retained['resume']['open_loops'] == source['resume']['open_loops']
    assert retained['filing']['items'][0]['status'] == 'pending'
    assert 'rewrite the session summary' in retained['filing']['items'][0]['error']
    assert retained['resume']['close_outcomes'][0]['title'] == 'Session history'
    # Reusing the returned facts without rewriting the summary must still block.
    unchanged, still_retained = run(retained, closed)
    assert unchanged.returncode == 1
    still_retained['resume']['session_summary'] = ' '
    blank, still_retained = run(still_retained, closed)
    assert blank.returncode == 1
    assert all(r['kind'] == 'tickets' for r in map(json.loads, calls.read_text().splitlines()))
    revised = 'Implemented the feature and closed example/project#7 (session history), completing the Session history epic.'
    still_retained['resume']['session_summary'] = revised
    retried, saved = run(still_retained, closed)
    assert retried.returncode == 0, retried.stderr
    assert saved['resume']['open_loops'] == []
    project_calls = [r for r in map(json.loads, calls.read_text().splitlines()) if r['kind'] == 'projects']
    assert [r['operation'] for r in project_calls] == ['lookup', 'write']
    assert all(r['session_summary'] == revised for r in project_calls)
    assert all(r['close_outcomes'] == saved['resume']['close_outcomes'] for r in project_calls)


@pytest.mark.parametrize('summary', [None, '', ' \t\n', 42, 'missing'])
@pytest.mark.parametrize('operation', ['file', 'record'])
@pytest.mark.parametrize('tickets_bound', [False, True])
def test_project_requires_summary_before_lookup_or_write(project_run, summary, operation, tickets_bound):
    run, source, good, calls = project_run
    if summary == 'missing':
        source['resume'].pop('session_summary')
    else:
        source['resume']['session_summary'] = summary
    result, retained = run(source, good, tickets_bound=tickets_bound, operation=operation)
    assert result.returncode == 1
    assert retained['resume']['open_loops'] == source['resume']['open_loops']
    assert retained['filing']['items'][0]['status'] == 'pending'
    assert 'write a nonempty session summary' in retained['filing']['items'][0]['error']
    observed = list(map(json.loads, calls.read_text().splitlines())) if calls.exists() else []
    assert all(r['kind'] != 'projects' for r in observed)
    retained['resume']['session_summary'] = 'Implemented session history for example/project#7.'
    retried, saved = run(retained, good, tickets_bound=tickets_bound, operation=operation)
    assert retried.returncode == 0, retried.stderr
    assert saved['resume']['open_loops'] == []


@pytest.mark.parametrize('tickets_bound', [False, True])
def test_project_profile_explicitly_uses_reread_or_stored_outcomes(project_run, tickets_bound):
    run, source, good, calls = project_run
    stored = {'kind': 'epic', 'title': 'Session history', 'state': 'closed',
              'done': 1, 'total': 1, 'triggering_ticket': 'example/project#7',
              'produced_at': '2026-11-01T12:00:00Z'}
    source['resume']['close_outcomes'] = [stored]
    response = good if tickets_bound else {'status': 'failed', 'error': 'Must not be called'}
    result, saved = run(source, response, tickets_bound=tickets_bound)
    assert result.returncode == 0, result.stderr
    assert saved['resume']['open_loops'] == []
    assert saved['filing']['ticket_read']['status'] == ('read' if tickets_bound else 'unbound')
    requests = list(map(json.loads, calls.read_text().splitlines()))
    expected = [('tickets', 'read')] if tickets_bound else []
    assert [(r['kind'], r['operation']) for r in requests] == expected + [
        ('projects', 'lookup'), ('projects', 'write')]
    for request in requests[-2:]:
        assert request['close_outcomes'] == [stored]
        assert request['session_summary'] == source['resume']['session_summary']
