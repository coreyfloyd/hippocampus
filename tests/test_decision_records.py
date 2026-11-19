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


@pytest.mark.parametrize('tool', ['claude', 'codex'])
def test_approved_document_routes_and_retry_reuses_identity(tmp_path, monkeypatch, tool):
    if tool == 'codex':
        monkeypatch.setenv('HIPPOCAMPUS_HARNESS', 'codex')
        monkeypatch.setenv('CODEX_THREAD_ID', 'producer')
        sessions = tmp_path / 'codex/sessions'
        sessions.mkdir(parents=True)
        monkeypatch.setenv('CODEX_HOME', str(sessions.parent))
        (sessions / 'producer.jsonl').write_text(json.dumps({
            'type': 'session_meta', 'payload': {'id': 'producer', 'source': 'cli'}}) + '\n')
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
