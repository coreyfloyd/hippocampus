"""Decision documents use fixture stores and explicit user approvals only."""
import json

import pytest

from test_record_writes import item, payload, row, run, store


def decision(**extra):
    return {**item('Use the agreed retention policy'),
        'type': 'decision', 'author': 'User', 'author_role': 'user',
        'location': 'session message 3',
        'decision_record': {'title': 'Retention policy', 'scope': 'product',
                            'text': 'Retain dated records.'}, **extra}


def profile(tmp_path, mode='ok'):
    return {'name': 'fixture', 'record_writes': {'documents': store(tmp_path, mode)},
            'decision_records': {'default_folder': 'operator/decisions',
                                 'scope_folders': {'product': 'product/decisions'}}}


def approved(**extra):
    return row(rule='R7', answer='approve', approval_source='user message 5', **extra)


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


def test_approved_document_routes_and_retry_reuses_identity(tmp_path, provider):
    config = profile(tmp_path)
    data = payload([decision()])
    result = run(tmp_path, 'record', config, data, [approved()])
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    saved = out['filing']['items'][0]
    assert saved['folder'] == 'product/decisions'
    assert saved['binding'] == 'documents'
    assert not out['resume']['open_loops']
    retry = run(tmp_path, 'record', config, data, [approved()])
    assert retry.returncode == 0, retry.stderr
    assert len(json.loads((tmp_path / 'store.json').read_text())) == 1


def test_default_folder_without_scope_table(tmp_path):
    config = profile(tmp_path)
    config['decision_records'].pop('scope_folders')
    result = run(tmp_path, 'record', config, payload([decision()]), [approved()])
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['filing']['items'][0]['folder'] == 'operator/decisions'


@pytest.mark.parametrize('change,filing', [
    ({}, row(rule='R7')),
    ({'author_role': 'agent'}, approved()),
    ({'author': ''}, approved()),
    ({'decision_record': {}}, approved()),
    ({}, approved(record_kind='tickets')),
])
def test_unapproved_or_operational_decisions_cannot_write(tmp_path, change, filing):
    result = run(tmp_path, 'record', profile(tmp_path), payload([decision(**change)]), [filing])
    assert result.returncode == 1
    assert json.loads(result.stdout)['resume']['open_loops']
    assert not (tmp_path / 'store.json').exists()


def test_missing_route_keeps_decision_without_write(tmp_path):
    config = profile(tmp_path)
    config.pop('decision_records')
    result = run(tmp_path, 'record', config, payload([decision()]), [approved()])
    assert result.returncode == 1
    assert json.loads(result.stdout)['resume']['open_loops']
    assert not (tmp_path / 'store.json').exists()


def test_unattended_proposal_uses_owned_ask_without_document(tmp_path):
    config = profile(tmp_path)
    config['ask'] = {'command': '/fixture-ask', 'owner_agent': 'durable-agent'}
    result = run(tmp_path, 'record', config, payload([decision()]), [{**row(rule='R3'), 'status': 'filed', 'destination': 'ask:1',
        'choices': ['approve', 'decline'], 'receipt': {'owner_agent': 'durable-agent'}}])
    assert result.returncode == 0, result.stderr
    ask = json.loads(result.stdout)['filing']['items'][0]['ask']
    assert ask['owner_agent'] == 'durable-agent'
    assert ask['decision_record'] == decision()['decision_record']
    assert ask['session_id'] == 'producer'
    assert not (tmp_path / 'store.json').exists()


def test_lost_document_receipt_stays_carried_then_lookup_recovers(tmp_path):
    config = profile(tmp_path, 'lost')
    first = run(tmp_path, 'record', config, payload([decision()]), [approved()])
    assert first.returncode == 1
    out = json.loads(first.stdout)
    assert out['filing']['items'][0]['status'] == 'uncertain'
    assert out['resume']['open_loops'] == [decision()]
    retry = run(tmp_path, 'record', config, out, [approved()])
    assert retry.returncode == 0, retry.stderr
    assert len(json.loads((tmp_path / 'store.json').read_text())) == 1


@pytest.mark.parametrize('mode', ['badlookup', 'failed'])
def test_document_failures_preserve_original_decision(tmp_path, mode):
    result = run(tmp_path, 'record', profile(tmp_path, mode), payload([decision()]), [approved()])
    assert result.returncode == 1
    assert json.loads(result.stdout)['resume']['open_loops'] == [decision()]
    assert not (tmp_path / 'store.json').exists()


def test_wrong_folder_receipt_cannot_settle_decision(tmp_path):
    config = profile(tmp_path)
    # A real store returning a receipt for another folder is not a route proof.
    script = tmp_path / 'store.py'
    script.write_text(script.read_text().replace("receipt['folder'] = r['filing']['folder']",
                                               "receipt['folder'] = 'other-folder'"))
    result = run(tmp_path, 'record', config, payload([decision()]), [approved()])
    assert result.returncode == 1
    out = json.loads(result.stdout)
    assert out['resume']['open_loops'] == [decision()]
    assert out['filing']['items'][0]['status'] == 'uncertain'


def test_unbound_ask_retains_complete_proposal(tmp_path):
    result = run(tmp_path, 'record', profile(tmp_path), payload([decision()]),
                 [row(rule='R3', choices=['approve', 'decline'])])
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out['resume']['open_loops'][0]['decision_record'] == decision()['decision_record']
    assert out['filing']['items'][0]['status'] == 'unbound'
    assert not (tmp_path / 'store.json').exists()


@pytest.mark.parametrize('route', [{}, {'default_folder': ''},
    {'default_folder': 'decisions', 'scope_folders': []},
    {'default_folder': 'decisions', 'scope_folders': {'product': ''}}])
def test_invalid_routes_are_rejected_before_writing(tmp_path, route):
    config = profile(tmp_path)
    config['decision_records'] = route
    result = run(tmp_path, 'record', config, payload([decision()]), [approved()])
    assert result.returncode == 1
    assert 'decision_records' in result.stderr
    assert not (tmp_path / 'store.json').exists()


@pytest.mark.parametrize('approved_row', [False, True])
def test_wrap_rechecks_document_approval_and_folder_receipt(tmp_path, approved_row):
    import checklist
    import record_write
    config = profile(tmp_path)
    source = decision()
    filing = approved() if approved_row else row(rule='R7')
    filing.update(item=source, status='filed', binding='documents', folder='product/decisions',
                  destination='documents:0', receipt={
                      'identity': record_write.identity(source), 'destination': 'documents:0',
                      'folder': 'wrong-folder'})
    data = payload([])
    data['resume']['next_action'] = 'Session finished.'
    data['filing'] = {'items': [filing]}
    failures, _ = checklist.filing_check(checklist.compose([config]), data)
    assert failures


@pytest.mark.parametrize('rule', ['R2', 'R5'])
@pytest.mark.parametrize('proposal', [False, True])
def test_decision_ticket_rows_keep_ticket_route_and_wrap_receipt(tmp_path, rule, proposal, provider):
    import checklist
    config = profile(tmp_path)
    config['record_writes']['tickets'] = config['record_writes']['documents']
    source = decision()
    if not proposal:
        source.pop('decision_record')
    filing = row(rule=rule, priority='normal', priority_reason='agreed work')
    result = run(tmp_path, 'record', config, payload([source]), [filing])
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    saved = out['filing']['items'][0]
    assert saved['binding'] == 'tickets'
    assert saved['receipt']['destination'].startswith('tickets:')
    assert 'folder' not in saved
    assert not out['resume']['open_loops']
    failures, _ = checklist.filing_check(checklist.compose([config]), out)
    assert not failures


@pytest.mark.parametrize('owner', ['durable-agent', 'wrong-agent'])
def test_decision_r4_ask_keeps_ask_route_and_ownership_guard(tmp_path, owner, provider):
    config = profile(tmp_path)
    config['ask'] = {'command': '/fixture-ask', 'owner_agent': 'durable-agent'}
    source = decision()
    # Model the agent's supplied acknowledgement from a controlled ask store.
    ask_store = tmp_path / 'ask-store.json'
    ask_store.write_text(json.dumps({'owner_agent': owner, 'decision_record': source['decision_record']}))
    receipt = json.loads(ask_store.read_text())
    filing = {**row(rule='R4'), 'status': 'filed', 'destination': 'ask',
              'choices': ['approve', 'decline'], 'receipt': receipt}
    result = run(tmp_path, 'record', config, payload([source]), [filing])
    out = json.loads(result.stdout)
    saved = out['filing']['items'][0]
    assert saved['binding'] == 'ask'
    assert saved['ask']['owner_agent'] == 'durable-agent'
    assert saved['ask']['decision_record'] == source['decision_record']
    assert not (tmp_path / 'store.json').exists()
    if owner == 'durable-agent':
        assert result.returncode == 0, result.stderr
        assert not out['resume']['open_loops']
    else:
        assert result.returncode == 1
        assert out['resume']['open_loops'][0]['session_id'] == source['session_id']
        assert saved['status'] == 'failed'


def test_decision_ticket_rule_cannot_write_document_without_document_approval(tmp_path):
    source = decision()
    result = run(tmp_path, 'record', profile(tmp_path), payload([source]),
                 [row(rule='R2', record_kind='documents')])
    assert result.returncode == 1
    assert json.loads(result.stdout)['resume']['open_loops'] == [source]
    assert not (tmp_path / 'store.json').exists()
