"""Ownership survives every delivery boundary; all profiles, stores and sessions are fixtures."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from test_over_limit_records import Session

ROOT = Path(__file__).resolve().parents[1]
BINDING = {'command': '/fixture-writer', 'owner_agent': 'fixture-agent'}
ITEM = {'type': 'decision', 'context': 'Approve fixture?', 'session_id': 'original-producer',
        'produced_at': '2026-11-19T12:00:00Z', 'choices': ['approve', 'defer'], 'disposition': 'carry'}


def load(name):
    spec = importlib.util.spec_from_file_location('owned_' + name, ROOT / 'scripts/lib' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def profile(tmp_path, monkeypatch):
    path = tmp_path / 'checklist.json'
    path.write_text(json.dumps({'name': 'fixture', 'ask': BINDING}))
    monkeypatch.setenv('CHECKLIST_USER_PROFILE', str(path))
    return path


def test_report_stamps_stored_and_rebuilt_asks_before_dedup():
    engine = load('checklist')
    subject = {'session_id': 'successor', 'working_directory': '/fixture'}
    plain = engine.ask_payload(ITEM, subject)
    owned = dict(plain, owner_agent=BINDING['owner_agent'])
    stale = dict(plain, owner_agent='old-user')
    handoff = {'subject': subject, 'resume': {'open_loops': [ITEM]},
               'filing': {'items': [{'ask': owned}, {'ask': stale}, {'status': 'failed', 'item': ITEM}],
                          'asks': {'/fixture': [plain]}}}
    before = copy.deepcopy(handoff)
    errors = []
    assert engine.report_asks(handoff, errors, BINDING) == [owned]
    assert not errors
    assert handoff == before


@pytest.mark.parametrize('tool', ['claude', 'codex'])
@pytest.mark.parametrize('receipt_owner', [None, 'wrong-agent', 'fixture-agent'])
@pytest.mark.parametrize('kind', ['decision', 'knowledge', 'lesson'])
def test_writer_readback_required_before_checklist_settlement(tmp_path, tool, receipt_owner, kind):
    session = Session(tmp_path, tool, 'successor')
    session.profile.write_text('```checklist-profile\n' + json.dumps({'name': 'fixture', 'ask': BINDING}) + '\n```\n')
    item = dict(ITEM, type=kind)
    source = tmp_path / 'source.json'
    source.write_text(json.dumps({'subject': {'session_id': 'successor', 'working_directory': str(tmp_path)},
                                  'resume': {'open_loops': [item]}}))
    engine = load('checklist')
    payload = engine.ask_payload(item, {'working_directory': str(tmp_path)}, BINDING)
    # Fixture writer saves first and returns the owner read back from its durable record.
    store = tmp_path / 'writer-store.json'
    saved = dict(payload, owner_agent=receipt_owner) if receipt_owner else {k: v for k, v in payload.items() if k != 'owner_agent'}
    store.write_text(json.dumps(saved))
    readback = json.loads(store.read_text())
    receipt = {'destination': str(store), **({'owner_agent': readback['owner_agent']} if receipt_owner else {})}
    outcomes = tmp_path / 'filing.json'
    outcomes.write_text(json.dumps([{'index': 0, 'rule': 'R3' if kind == 'decision' else 'R4', 'status': 'filed',
                                    'destination': str(store) if kind == 'decision' else 'ask', 'receipt': receipt}]))
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/lib/checklist.py'), 'file',
                             '--user-profile', str(session.profile), '--handoff', str(source),
                             '--filing', str(outcomes)], env=session.env, text=True, capture_output=True)
    assert result.returncode == (0 if receipt_owner == BINDING['owner_agent'] else 1), result.stderr
    output = json.loads(result.stdout)
    assert output['filing']['items'][0]['ask']['owner_agent'] == BINDING['owner_agent']
    assert output['filing']['items'][0]['ask']['session_id'] == ITEM['session_id']
    if receipt_owner != BINDING['owner_agent']:
        assert output['resume']['open_loops'] == [item]
        assert 'owner_agent' in output['filing']['items'][0]['error']
    else:
        assert output['resume']['open_loops'] == ([] if kind == 'decision' else [item])


def test_report_rejects_forged_filed_receipt_without_owner():
    engine = load('checklist')
    plan = engine.compose([{'name': 'fixture', 'ask': BINDING}])
    data = {'resume': {'open_loops': [], 'next_action': 'Session finished.'},
            'filing': {'items': [{'binding': 'ask', 'status': 'filed', 'item': ITEM,
                                  'receipt': 'opaque', 'destination': 'fixture-store'}]}}
    failures, _ = engine.filing_check(plan, data, BINDING)
    assert any('owner_agent' in failure for failure in failures)


def test_sweep_missing_binding_fails_without_mutating_intent():
    engine = load('sweep')
    row = {'identity': {'session_id': 'producer', 'text': ITEM['context']}, 'ask': {'text': ITEM['context']}}
    before = copy.deepcopy(row)
    report = {'run_id': 'fixture', 'mode': 'act', 'work': []}
    with pytest.raises(ValueError, match='ask_binding'):
        engine.add_intent(report, row, '/fixture', 'ask')
    assert report['work'] == []
    assert row == before


@pytest.mark.parametrize('receipt', ['opaque', {'owner_agent': 'wrong-agent'}, {'owner_agent': 'fixture-agent'}])
def test_sweep_requires_saved_owner_before_accepting_result(tmp_path, receipt):
    engine = load('sweep')
    work = [{'write_id': 'fixture-write', 'operation': 'ask', 'binding': 'ask',
             'ask': {'owner_agent': 'fixture-agent'}}]
    path = tmp_path / 'results.json'
    path.write_text(json.dumps([{'write_id': 'fixture-write', 'status': 'written',
                                'destination': 'fixture-store', 'receipt': receipt}]))
    if isinstance(receipt, dict) and receipt.get('owner_agent') == 'fixture-agent':
        assert engine.load_results(path, work, ('written',))['fixture-write']['receipt'] == receipt
    else:
        with pytest.raises(ValueError, match='owner_agent'):
            engine.load_results(path, work, ('written',))


def test_sweep_preview_ask_already_has_owner():
    engine = load('sweep')
    section = {'asks_raised': []}
    candidate = {'session_id': 'producer', 'activity_at': 1000, 'path': '/fixture/handoff', 'directory': '/fixture'}
    engine.add_ask(section, candidate, 'Keep?', ['keep', 'close'], 'fixture', BINDING)
    assert section['asks_raised'][0]['ask']['owner_agent'] == BINDING['owner_agent']


def test_slim_new_retry_and_closed_asks_are_owned_and_receipted(tmp_path, monkeypatch, profile):
    engine = load('slim')
    Path(os.environ['HIPPOCAMPUS_CONFIG']).write_text('{"auto_apply_lessons": true}')
    records = tmp_path / 'records.json'
    records.write_text('{"records": []}')
    run = {'id': 'fixture-run', 'started': ITEM['produced_at'], 'results': [], 'failed': [],
           'queue': [], 'analyzed': 0, 'skipped': [], 'unreachable': [], 'closed': None,
           'deferred': [{'repository': 'acme/rules', 'path': 'rules.md', 'changed_by': 'old-branch'}]}
    with engine._transaction() as state:
        state['run'] = run
        closed = engine._close(state, run)
    ask = closed['asks'][0]
    assert ask['owner_agent'] == BINDING['owner_agent']
    identity = copy.deepcopy(ask['identity'])
    # Every later output is rebound too, including a closed run and old pending asks.
    assert engine.begin('fixture-run')['asks'][0]['owner_agent'] == BINDING['owner_agent']
    for receipt in ['opaque', {'owner_agent': 'wrong-agent'}]:
        with pytest.raises(ValueError, match='owner_agent'):
            engine.ask_delivered(ask['id'], receipt)
        with engine._transaction() as state:
            assert state['asks'][0]['identity'] == identity
    receipt = {'owner_agent': BINDING['owner_agent'], 'destination': 'fixture-store'}
    assert engine.ask_delivered(ask['id'], receipt)['receipt'] == receipt
    with engine._transaction() as state:
        assert state['asks'] == []
    # plan redelivers a preexisting ask with the currently configured owner, preserving identity.
    with engine._transaction() as state:
        state['asks'] = [dict(ask, owner_agent='stale-user')]
    output = engine.plan([records])
    assert output['undelivered_asks'][0]['owner_agent'] == BINDING['owner_agent']
    assert output['undelivered_asks'][0]['identity'] == identity


def test_reserved_sweep_without_binding_keeps_report_and_reservation(tmp_path, monkeypatch):
    engine = load('sweep')
    reservation = tmp_path / 'reservation.json'
    reservation.write_text(json.dumps({'run_id': 'fixture', 'mode': 'act', 'report': str(tmp_path / 'report.md')}))
    report = {'phase': 'planned', 'run_id': 'fixture', 'work': [], 'directories': {}}
    before = copy.deepcopy(report)
    before_bytes = reservation.read_bytes()
    monkeypatch.setattr(engine, 'pending_path', lambda: reservation)
    monkeypatch.setattr(engine, 'read_report', lambda path: report)
    with pytest.raises(ValueError, match='ask_binding'):
        engine.complete_act({}, 'fixture', tmp_path / 'absent-results.json')
    assert report == before
    assert reservation.read_bytes() == before_bytes


def test_missing_explicit_slim_profile_keeps_pending_ask(tmp_path, monkeypatch, profile):
    engine = load('slim')
    ask = {'id': 'fixture', 'owner_agent': 'fixture-agent', 'identity': {'session_id': 'original'}}
    with engine._transaction() as state:
        state['asks'] = [ask]
    before = engine._state_path().read_bytes()
    monkeypatch.setenv('CHECKLIST_USER_PROFILE', str(tmp_path / 'missing-profile.json'))
    with pytest.raises(FileNotFoundError):
        engine.ask_delivered('fixture', {'owner_agent': 'fixture-agent'})
    assert engine._state_path().read_bytes() == before


@pytest.mark.parametrize('kind', ['knowledge', 'lesson'])
def test_native_ask_needs_owner_receipt_and_keeps_unsaved_item(kind):
    engine = load('checklist')
    item = dict(ITEM, type=kind)
    source = {'subject': {'session_id': 'successor', 'working_directory': '/fixture'},
              'resume': {'open_loops': [item]}}
    plan = engine.compose([{'name': 'fixture', 'ask': BINDING}])
    for receipt, success in [('opaque', False), ({'owner_agent': 'fixture-agent'}, True)]:
        # The CLI calls with execute_writes=True; fixture paths are installed by conftest.
        row = {'index': 0, 'rule': 'R4', 'status': 'filed', 'destination': 'ask', 'receipt': receipt}
        output = engine.file_items(plan, source, [row], BINDING)
        filed = output['filing']['items'][0]
        assert filed.get('ask_status') == ('filed' if success else None)
        assert filed['status'] == ('pending' if success else 'failed')
        assert output['resume']['open_loops'] == [item]


def test_unproven_stored_filed_ask_remains_recoverable():
    engine = load('checklist')
    handoff = {'subject': {'working_directory': '/fixture'}, 'resume': {'open_loops': []},
               'filing': {'items': [{'binding': 'ask', 'status': 'filed', 'item': ITEM, 'receipt': 'opaque'}]}}
    errors = []
    asks = engine.report_asks(handoff, errors, BINDING)
    assert len(asks) == 1
    assert asks[0]['owner_agent'] == BINDING['owner_agent']
    assert asks[0]['session_id'] == ITEM['session_id']


def test_resumed_sweep_rechecks_prior_success_owner_proof(tmp_path, monkeypatch):
    engine = load('sweep')
    reservation = tmp_path / 'reservation.json'
    reservation.write_text(json.dumps({'run_id': 'fixture', 'mode': 'act', 'report': str(tmp_path / 'report.md')}))
    report = {'phase': 'planned', 'run_id': 'fixture', 'ask_binding': BINDING,
              'directories': {}, 'discovery': {},
              'work': [{'write_id': 'fixture', 'operation': 'ask', 'outcome': 'written', 'ask': {'text': 'Retained ask'}, 'receipt': 'opaque'}]}
    before = copy.deepcopy(report)
    monkeypatch.setattr(engine, 'pending_path', lambda: reservation)
    monkeypatch.setattr(engine, 'read_report', lambda path: copy.deepcopy(report))
    monkeypatch.setattr(engine, 'read_open_sessions', lambda path: {})
    def reject_unvalidated_success(*args):
        raise AssertionError('An ask with unproven ownership reached post-filing checks')
    monkeypatch.setattr(engine, 'open_session_checks', reject_unvalidated_success)
    with pytest.raises(ValueError, match='owner_agent'):
        engine.complete_act({}, 'fixture', tmp_path / 'absent-results.json')
    assert report == before
    assert reservation.exists()
