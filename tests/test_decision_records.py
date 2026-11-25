"""Decisions and change logs file through their own record-write kinds, against fixture writers only."""
import json

import pytest

from test_record_writes import item, payload, requests, row, run, store


def decision(**extra):
    return {**item('Use the agreed retention policy'),
        'type': 'decision', 'entry': 'record', 'author': 'User', 'author_role': 'user',
        'location': 'session message 3',
        'decision_record': {'title': 'Retention policy', 'scope': {'project': 'fixture-project'},
                            'text': 'Retain dated records.', 'options': ['Retain', 'Expire'],
                            'why': 'Dated records answer later audits.'}, **extra}


def agent_decision(**extra):
    return {**item('Chose the stub writer for the fixture'),
        'type': 'decision', 'entry': 'agent_log', 'author': 'agent', 'author_role': 'agent',
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
    return row(**{'rule': 'R7', 'answer': 'approve', 'approval_source': 'user message 5', **extra})


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
    ({'author_role': 'agent'}, approved()),
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
    assert saved['status'] == 'pending'
    assert saved['ask']['text'] == 'Which folder holds this scope?'
    assert saved['ask']['choices'] == ['add a scope row', 'decline']
    assert saved['ask']['owner_agent'] == 'durable-agent'
    assert saved['ask']['decision_record'] == decision()['decision_record']
    assert out['resume']['open_loops'] == [{**decision(), 'writer_ask': saved['ask']}]
    assert out['filing']['asks']
    import checklist
    failures, warnings = checklist.filing_check(checklist.compose([config]), out, config['ask'])
    assert not failures
    assert any('writer' in w for w in warnings)


def test_writer_ask_without_choices_fails_and_names_the_unusable_ask(tmp_path):
    result = run(tmp_path, 'record', profile(tmp_path, 'badask'), payload([decision()]), [approved()])
    assert result.returncode == 1
    out = json.loads(result.stdout)
    saved = out['filing']['items'][0]
    assert saved['status'] == 'failed'
    assert 'writer ask unusable' in saved['error']
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


@pytest.mark.parametrize('change', [{'entry': 'agent_log'}, {'entry': 'agent_log', 'author_role': None}])
def test_a_user_decision_marked_as_an_agent_log_entry_is_refused_without_approval(tmp_path, provider, change):
    source = {k: v for k, v in decision(**change).items() if v is not None}
    result = run(tmp_path, 'record', profile(tmp_path), payload([source]), [row(rule='R7')])
    assert result.returncode == 1
    assert json.loads(result.stdout)['resume']['open_loops'] == [source]
    assert kinds_sent(tmp_path) == {}


@pytest.mark.parametrize('source', [decision(), {k: v for k, v in decision().items()
                                                 if k not in ('entry', 'author_role')}])
def test_a_user_decision_reaches_a_ticket_comment_only_with_approval(tmp_path, provider, source):
    refused = run(tmp_path, 'record', profile(tmp_path), payload([source]), [row(rule='R2')])
    assert refused.returncode == 1
    assert 'approval' in json.loads(refused.stdout)['filing']['items'][0]['error']
    assert kinds_sent(tmp_path) == {}
    filed = run(tmp_path, 'record', profile(tmp_path), payload([source]),
                [row(rule='R2', answer='approve', approval_source='user message 5')])
    assert filed.returncode == 0, filed.stderr
    assert kinds_sent(tmp_path) == {'tickets': ['lookup', 'write']}


def test_wrap_rechecks_approval_of_a_user_decision_filed_as_a_ticket_comment(tmp_path):
    import checklist
    import record_write
    source = decision()
    filing = row(rule='R2')
    filing.update(item=source, status='filed', binding='tickets', destination='tickets:0',
                  receipt={'identity': record_write.identity(source), 'destination': 'tickets:0'})
    data = payload([])
    data['resume']['next_action'] = 'Session finished.'
    data['filing'] = {'items': [filing]}
    failures, _ = checklist.filing_check(checklist.compose([profile(tmp_path)]), data)
    assert any('approval' in f for f in failures)


def test_a_carried_anchored_agent_decision_is_owed_to_the_tickets_record_write(tmp_path):
    import checklist
    source = agent_decision(anchor={'ticket': 'https://example.test/issues/7'})
    data = payload([source])
    data['filing'] = {'items': []}
    failures, warnings = checklist.filing_check(
        checklist.compose([profile(tmp_path, kinds=('decisions',))]), data)
    assert not failures
    assert any('missing tickets binding' in w for w in warnings)


def test_a_malformed_anchor_fails_its_item_and_the_other_items_still_file(tmp_path):
    bad = agent_decision(anchor='https://example.test/issues/7')
    good = agent_decision(context='A second agent decision')
    result = run(tmp_path, 'record', profile(tmp_path), payload([bad, good]),
                 [row(0, rule='R7'), row(1, rule='R7')])
    assert result.returncode == 1
    out = json.loads(result.stdout)
    assert 'anchor' in out['filing']['items'][0]['error']
    assert out['filing']['items'][1]['status'] == 'filed'
    assert out['resume']['open_loops'] == [bad]


def test_a_profile_with_the_retired_decision_routes_still_composes_with_a_warning(tmp_path):
    config = profile(tmp_path)
    config['decision_records'] = {'default_folder': 'operator/decisions'}
    result = run(tmp_path, 'record', config, payload([decision()]), [approved()])
    assert result.returncode == 0, result.stderr
    assert 'decision_records is retired and ignored' in result.stderr
    assert kinds_sent(tmp_path) == {'decisions': ['lookup', 'write']}


def test_a_change_log_entry_defaults_to_the_logs_kind_and_is_refused_elsewhere(tmp_path):
    source = {k: v for k, v in change_log().items() if k != 'record_kind'}
    result = run(tmp_path, 'record', profile(tmp_path), payload([source]), [row(rule='R7')])
    assert result.returncode == 0, result.stderr
    assert kinds_sent(tmp_path) == {'logs': ['lookup', 'write']}
    refused = run(tmp_path, 'record', profile(tmp_path), payload([change_log(context='Another change')]),
                  [row(rule='R7', record_kind='documents')])
    assert refused.returncode == 1
    assert "'logs'" in json.loads(refused.stdout)['filing']['items'][0]['error']
    assert 'documents' not in kinds_sent(tmp_path)


def test_a_deferred_user_decision_row_keeps_its_own_outcome_not_an_approval_failure(tmp_path):
    result = run(tmp_path, 'record', profile(tmp_path), payload([decision()]),
                 [row(rule='R7', status='uncertain', error='writer timed out')])
    assert result.returncode == 1
    saved = json.loads(result.stdout)['filing']['items'][0]
    assert saved['error'] == 'writer timed out'
    assert 'approval' not in saved['error']
    assert kinds_sent(tmp_path) == {}


def test_an_agent_decision_with_a_top_level_ticket_is_refused_by_the_decisions_kind(tmp_path):
    source = agent_decision(ticket='https://example.test/issues/7')
    result = run(tmp_path, 'record', profile(tmp_path), payload([source]), [row(rule='R7')])
    assert result.returncode == 1
    assert 'tickets record write' in json.loads(result.stdout)['filing']['items'][0]['error']
    assert kinds_sent(tmp_path) == {}


def test_a_pending_writer_ask_is_kept_and_raised_once_across_wraps(tmp_path, monkeypatch):
    import checklist
    monkeypatch.setenv('HANDOFF_LEDGER_DIR', str(tmp_path))
    config = profile(tmp_path, 'ask')
    config['ask'] = {'command': '/fixture-ask', 'owner_agent': 'durable-agent'}
    first = json.loads(run(tmp_path, 'record', config, payload([decision()]), [approved()]).stdout)
    assert len([a for group in first['filing']['asks'].values() for a in group]) == 1
    [carried] = first['resume']['open_loops']
    assert carried['writer_ask'] == first['filing']['items'][0]['ask']
    line, not_saved, _ = checklist.saved_state(checklist.compose([config]), first, config['ask'])
    assert "writer's ask" in line and not not_saved
    second = json.loads(run(tmp_path, 'record', config, first, [approved()]).stdout)
    assert second['filing']['asks'] == {}
    assert second['resume']['open_loops'] == [carried]
    assert all('writer_ask' not in r['item'] for r in requests(tmp_path, 'decisions'))


def test_a_carried_change_log_entry_is_owed_to_the_logs_record_write(tmp_path):
    import checklist
    data = payload([change_log()])
    data['filing'] = {'items': []}
    failures, warnings = checklist.filing_check(
        checklist.compose([profile(tmp_path, kinds=('decisions',))]), data)
    assert not failures
    assert any('missing logs binding' in w for w in warnings)


def test_the_retired_record_binding_error_names_every_record_write_kind():
    import checklist
    import record_write
    with pytest.raises(ValueError) as error:
        checklist.reject_record_binding({'bindings': {'record': {'command': '/x'}}})
    assert all(f'"{kind}"' in str(error.value) for kind in record_write.KINDS)


def test_unattended_record_raises_an_ask_and_never_files_a_user_decision(tmp_path, provider):
    config = profile(tmp_path)
    config['ask'] = {'command': '/fixture-ask', 'owner_agent': 'durable-agent'}
    result = run(tmp_path, 'record', config, payload([decision(), agent_decision()]),
                 [approved(), row(1, rule='R7')], '--unattended')
    assert result.returncode == 1
    out = json.loads(result.stdout)
    saved = out['filing']['items'][0]
    assert saved['status'] == 'failed' and 'unattended' in saved['error']
    asks = [a for group in out['filing']['asks'].values() for a in group]
    assert len(asks) == 1
    assert asks[0]['choices'] == ['approve', 'decline']
    assert asks[0]['owner_agent'] == 'durable-agent'
    assert out['resume']['open_loops'] == [decision()]
    # The agent's own log entry needs nobody's approval and still files.
    assert [r['item']['entry'] for r in requests(tmp_path, 'decisions')] == ['agent_log', 'agent_log']


def test_catch_up_delivers_the_writer_ask_for_an_unplaceable_scope(tmp_path, monkeypatch):
    import checklist
    import filing_catchup
    monkeypatch.setenv('HANDOFF_LEDGER_DIR', str(tmp_path))
    asks = store(tmp_path, 'ok', 'asks')
    script = tmp_path / 'asks.py'
    script.write_text(script.read_text().replace(
        "data.append(receipt);", "receipt['owner_agent'] = r['item'].get('owner_agent'); data.append(receipt);"))
    config = profile(tmp_path, 'ask')
    ask = {'command': asks['command'], 'owner_agent': 'durable-agent'}
    plan = checklist.compose([config])
    source = {'item': decision(), 'subject': {'session_id': 'producer', 'working_directory': str(tmp_path)}}
    outcome = filing_catchup.file_item(source, {k: v for k, v in approved().items() if k not in ('index', 'status')}, plan, ask)
    assert outcome['status'] == 'pending' and outcome['ask_status'] == 'filed'
    assert outcome['ask_receipt']['owner_agent'] == 'durable-agent'
    assert [r['operation'] for r in requests(tmp_path, 'asks')] == ['lookup', 'write']
    assert requests(tmp_path, 'asks')[1]['item']['text'] == 'Which folder holds this scope?'
