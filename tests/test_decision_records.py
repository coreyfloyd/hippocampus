"""Decisions and change logs file through their own record-write kinds, against fixture writers only."""
import json

import pytest

from test_record_writes import item, payload, requests, row, run, store


def decision(**extra):
    return {**item('Use the agreed retention policy'),
        'type': 'decision', 'entry': 'record', 'author': 'User', 'location': 'session message 3',
        'decision_record': {'title': 'Retention policy', 'scope': {'project': 'fixture-project'},
                            'text': 'Retain dated records.', 'options': ['Retain', 'Expire'],
                            'why': 'Dated records answer later audits.'}, **extra}


def agent_decision(**extra):
    return {**item('Chose the stub writer for the fixture'),
        'type': 'decision', 'entry': 'agent_log', 'author': 'agent',
        'decision_record': {'scope': {'repository': 'example/fixture'},
                            'text': 'Use the stub writer.', 'why': 'No live store in tests.'}, **extra}


def change_log(**extra):
    return {**item('Moved the fixture job'), 'record_kind': 'logs', 'author': 'agent',
            'change_log': {'scope': {'area': 'fixture'}, 'subject': 'fixture-node',
                           'text': 'Moved the fixture job to the scheduler.'}, **extra}


def profile(tmp_path, mode='ok', kinds=('decisions', 'documents', 'tickets', 'logs')):
    return {'name': 'fixture', 'record_writes': {k: store(tmp_path, mode if k == 'decisions' else 'ok', k)
                                                 for k in kinds}}


def approved(**extra):
    return row(rule='R7', answer='approve', approval_source='user message 5', **extra)


def kinds_sent(tmp_path):
    return {k: [r['operation'] for r in requests(tmp_path, k)]
            for k in ('decisions', 'documents', 'tickets', 'logs') if requests(tmp_path, k)}


@pytest.fixture(params=['claude', 'codex'])
def provider(request, tmp_path, monkeypatch):
    if request.param == 'codex':
        monkeypatch.setenv('HIPPOCAMPUS_HARNESS', 'codex')
        monkeypatch.setenv('CODEX_THREAD_ID', 'producer')
        sessions = tmp_path / 'codex/sessions'
        sessions.mkdir(parents=True)
        monkeypatch.setenv('CODEX_HOME', str(sessions.parent))
        (sessions / 'producer.jsonl').write_text(json.dumps({
            'type': 'session_meta', 'payload': {'id': 'producer', 'source': 'cli'}}) + '\n')
    return request.param


def test_approved_decision_sends_one_decisions_request_and_no_documents_request(tmp_path, provider):
    config = profile(tmp_path)
    data = payload([decision()])
    result = run(tmp_path, 'record', config, data, [approved()])
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    saved = out['filing']['items'][0]
    assert saved['binding'] == 'decisions'
    assert saved['receipt']['destination'].startswith('decisions:')
    assert not out['resume']['open_loops']
    assert kinds_sent(tmp_path) == {'decisions': ['lookup', 'write']}
    sent = requests(tmp_path, 'decisions')[1]
    assert sent['item'] == decision()
    assert sent['filing']['approval_source'] == 'user message 5'
    retry = run(tmp_path, 'record', config, data, [approved()])
    assert retry.returncode == 0, retry.stderr
    assert kinds_sent(tmp_path) == {'decisions': ['lookup', 'write', 'lookup']}


def test_documents_record_write_refuses_a_decision_and_names_the_decisions_kind(tmp_path, provider):
    result = run(tmp_path, 'record', profile(tmp_path), payload([decision()]),
                 [approved(record_kind='documents')])
    assert result.returncode == 1
    out = json.loads(result.stdout)
    saved = out['filing']['items'][0]
    assert saved['status'] == 'failed'
    assert "'decisions'" in saved['error']
    assert out['resume']['open_loops'] == [decision()]
    assert kinds_sent(tmp_path) == {}


@pytest.mark.parametrize('change,filing', [
    ({}, row(rule='R7')),
    ({}, approved(approval_source='')),
    ({'author': ''}, approved()),
    ({'entry': 'note'}, approved()),
    ({'location': ''}, approved()),
    ({'decision_record': {}}, approved()),
    ({'decision_record': {**decision()['decision_record'], 'scope': 'fixture-project'}}, approved()),
    ({'decision_record': {**decision()['decision_record'], 'scope': {'area': 'a', 'project': 'p'}}}, approved()),
])
def test_unapproved_or_incomplete_decision_writes_nothing(tmp_path, change, filing):
    result = run(tmp_path, 'record', profile(tmp_path), payload([decision(**change)]), [filing])
    assert result.returncode == 1
    assert json.loads(result.stdout)['resume']['open_loops'] == [decision(**change)]
    assert kinds_sent(tmp_path) == {}


def test_agent_decision_without_ticket_files_to_the_agent_decision_log_without_approval(tmp_path, provider):
    result = run(tmp_path, 'record', profile(tmp_path), payload([agent_decision()]), [row(rule='R7')])
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['filing']['items'][0]['binding'] == 'decisions'
    assert kinds_sent(tmp_path) == {'decisions': ['lookup', 'write']}
    assert requests(tmp_path, 'decisions')[1]['item']['entry'] == 'agent_log'


def test_agent_decision_with_ticket_stays_a_ticket_comment(tmp_path, provider):
    source = agent_decision(anchor={'ticket': 'https://example.test/issues/7'})
    result = run(tmp_path, 'record', profile(tmp_path), payload([source]), [row(rule='R2')])
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['filing']['items'][0]['binding'] == 'tickets'
    assert kinds_sent(tmp_path) == {'tickets': ['lookup', 'write']}


def test_anchored_agent_decision_is_refused_by_the_decisions_kind(tmp_path):
    source = agent_decision(anchor={'ticket': 'https://example.test/issues/7'})
    result = run(tmp_path, 'record', profile(tmp_path), payload([source]), [row(rule='R7')])
    assert result.returncode == 1
    assert 'tickets record write' in json.loads(result.stdout)['filing']['items'][0]['error']
    assert kinds_sent(tmp_path) == {}


def test_unattended_decision_becomes_one_owned_ask_and_no_record(tmp_path, provider):
    config = profile(tmp_path)
    config['ask'] = {'command': '/fixture-ask', 'owner_agent': 'durable-agent'}
    result = run(tmp_path, 'record', config, payload([decision()]), [{**row(rule='R3'), 'status': 'filed',
        'destination': 'ask:1', 'choices': ['approve', 'decline'], 'receipt': {'owner_agent': 'durable-agent'}}])
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    asks = [a for group in out['filing']['asks'].values() for a in group]
    assert len(asks) == 1
    assert asks[0]['owner_agent'] == 'durable-agent'
    assert asks[0]['decision_record'] == decision()['decision_record']
    assert asks[0]['session_id'] == 'producer'
    assert kinds_sent(tmp_path) == {}


def test_writer_ask_for_an_unmatched_scope_is_reported_and_the_decision_kept(tmp_path, provider):
    config = profile(tmp_path, 'ask')
    config['ask'] = {'command': '/fixture-ask', 'owner_agent': 'durable-agent'}
    result = run(tmp_path, 'record', config, payload([decision()]), [approved()])
    assert result.returncode == 1
    out = json.loads(result.stdout)
    saved = out['filing']['items'][0]
    assert saved['status'] == 'failed'
    assert saved['ask']['text'] == 'Which folder holds this scope?'
    assert saved['ask']['choices'] == ['add a scope row', 'decline']
    assert saved['ask']['owner_agent'] == 'durable-agent'
    assert saved['ask']['decision_record'] == decision()['decision_record']
    assert out['resume']['open_loops'] == [decision()]


def test_lost_decision_receipt_stays_carried_then_lookup_recovers(tmp_path):
    config = profile(tmp_path, 'lost')
    first = run(tmp_path, 'record', config, payload([decision()]), [approved()])
    assert first.returncode == 1
    out = json.loads(first.stdout)
    assert out['filing']['items'][0]['status'] == 'uncertain'
    assert out['resume']['open_loops'] == [decision()]
    retry = run(tmp_path, 'record', config, out, [approved()])
    assert retry.returncode == 0, retry.stderr
    assert len(json.loads((tmp_path / 'decisions.json').read_text())) == 1


@pytest.mark.parametrize('mode', ['badlookup', 'failed'])
def test_decision_writer_failures_preserve_the_original_decision(tmp_path, mode):
    result = run(tmp_path, 'record', profile(tmp_path, mode), payload([decision()]), [approved()])
    assert result.returncode == 1
    assert json.loads(result.stdout)['resume']['open_loops'] == [decision()]
    assert not (tmp_path / 'decisions.json').exists()


def test_unbound_decisions_kind_keeps_the_decision(tmp_path):
    result = run(tmp_path, 'record', profile(tmp_path, kinds=('documents',)), payload([decision()]), [approved()])
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out['filing']['items'][0]['status'] == 'unbound'
    assert out['resume']['open_loops'] == [decision()]
    assert kinds_sent(tmp_path) == {}


@pytest.mark.parametrize('approved_row', [False, True])
def test_wrap_rechecks_decision_approval(tmp_path, approved_row):
    import checklist
    import record_write
    config = profile(tmp_path)
    source = decision()
    filing = approved() if approved_row else row(rule='R7')
    filing.update(item=source, status='filed', binding='decisions', destination='decisions:0',
                  receipt={'identity': record_write.identity(source), 'destination': 'decisions:0'})
    data = payload([])
    data['resume']['next_action'] = 'Session finished.'
    data['filing'] = {'items': [filing]}
    failures, _ = checklist.filing_check(checklist.compose([config]), data)
    assert bool(failures) is not approved_row


@pytest.mark.parametrize('owner', ['durable-agent', 'wrong-agent'])
def test_decision_r4_ask_keeps_ask_route_and_ownership_guard(tmp_path, owner, provider):
    config = profile(tmp_path)
    config['ask'] = {'command': '/fixture-ask', 'owner_agent': 'durable-agent'}
    source = decision()
    filing = {**row(rule='R4'), 'status': 'filed', 'destination': 'ask',
              'choices': ['approve', 'decline'], 'receipt': {'owner_agent': owner}}
    result = run(tmp_path, 'record', config, payload([source]), [filing])
    out = json.loads(result.stdout)
    saved = out['filing']['items'][0]
    assert saved['binding'] == 'ask'
    assert saved['ask']['decision_record'] == source['decision_record']
    assert kinds_sent(tmp_path) == {}
    if owner == 'durable-agent':
        assert result.returncode == 0, result.stderr
        assert not out['resume']['open_loops']
    else:
        assert result.returncode == 1
        assert saved['status'] == 'failed'


def test_change_log_entry_files_through_the_logs_kind_without_approval(tmp_path, provider):
    result = run(tmp_path, 'record', profile(tmp_path), payload([change_log()]), [row(rule='R7')])
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['filing']['items'][0]['binding'] == 'logs'
    assert kinds_sent(tmp_path) == {'logs': ['lookup', 'write']}
    assert requests(tmp_path, 'logs')[1]['item']['change_log']['subject'] == 'fixture-node'


@pytest.mark.parametrize('change', [{'author': ''}, {'change_log': {'scope': {'area': 'fixture'}, 'text': 'x'}},
                                    {'change_log': {'scope': 'fixture', 'subject': 's', 'text': 'x'}}])
def test_incomplete_change_log_entry_writes_nothing(tmp_path, change):
    result = run(tmp_path, 'record', profile(tmp_path), payload([change_log(**change)]), [row(rule='R7')])
    assert result.returncode == 1
    assert kinds_sent(tmp_path) == {}
