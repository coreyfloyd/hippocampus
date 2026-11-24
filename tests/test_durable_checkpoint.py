"""Durable checkpoints file fixture items without wrapping either provider."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from test_record_writes import store, item

ROOT = Path(__file__).resolve().parents[1]


def invoke(tmp_path, provider, mode='ok', durable=True, items=None, rows=None, profile=None, extra=(), loops=()):
    binding = store(tmp_path, mode)
    script = tmp_path / 'store.py'
    script.write_text(script.read_text().replace("data.append(receipt);", "receipt['owner_agent'] = r['item'].get('owner_agent'); data.append(receipt);"))
    profile = profile(binding) if profile else {'name': 'fixture', 'record_writes': {'tickets': binding}}
    (tmp_path / 'profile.json').write_text(json.dumps(profile))
    (tmp_path / 'rows.json').write_text(json.dumps(rows if rows is not None else [{'index': 0, 'rule': 'R2',
        'status': 'pending', 'read_status': 'ok'}]))
    payload = {'resume': {'headline': 'Continue fixture work', 'next_action': 'Continue fixture work',
        'why': 'Fixture continuation', 'session_summary': 'Investigated fixture work and retained the result.', 'open_loops': list(loops)},
        'session_items': items if items is not None else [{**item(), 'session_id': 'fixture', 'disposition': 'File in fixture record'}], 'spawned_processes': [], 'suggested_skills': []}
    command = [sys.executable, str(ROOT / 'scripts/lib/handoff.py'), 'checkpoint',
        '--cwd', str(tmp_path), '--session-id', 'fixture']
    if durable:
        command += ['--durable', '--user-profile', str(tmp_path / 'profile.json'),
            '--filing', str(tmp_path / 'rows.json'), '--report', str(tmp_path / 'report.json')]
    command += list(extra)
    return subprocess.run(command, input=json.dumps(payload), text=True, capture_output=True,
        env={**os.environ, 'HOME': str(tmp_path / 'home'), 'XDG_CONFIG_HOME': str(tmp_path / 'config'),
            'CLAUDE_CODE_ENTRYPOINT': 'cli', 'HANDOFF_ENTRYPOINT': 'cli',
            'HANDOFF_PATH': str(tmp_path / 'handoff.json'), 'HANDOFF_LEDGER_DIR': str(tmp_path / 'ledger'),
            'HANDOFF_STATE_DIR': str(tmp_path / 'state'), 'HIPPOCAMPUS_HARNESS': provider, 'CODEX_THREAD_ID': 'fixture' if provider == 'codex' else ''})


@pytest.mark.parametrize('provider', ['claude', 'codex'])
def test_durable_files_receipt_and_keeps_continuation(tmp_path, provider):
    result = invoke(tmp_path, provider)
    assert result.returncode == 0, result.stderr
    data = json.loads((tmp_path / 'handoff.json').read_text())
    assert data['resume']['open_loops'] == []
    assert data['resume']['next_action'] == 'Continue fixture work'
    assert data['trigger'] == 'checkpoint'
    report = json.loads((tmp_path / 'report.json').read_text())
    assert report['filed'][0]['receipt']['destination'] == 'tickets:0'
    assert report['unfiled'] == []
    assert invoke(tmp_path, provider).returncode == 0
    assert len(json.loads((tmp_path / 'store.json').read_text())) == 1


def test_failed_filing_stays_carried_and_reported(tmp_path):
    result = invoke(tmp_path, 'codex', 'failed')
    assert result.returncode == 1
    assert json.loads((tmp_path / 'handoff.json').read_text())['resume']['open_loops']
    assert json.loads((tmp_path / 'report.json').read_text())['unfiled']


def test_ordinary_checkpoint_does_not_file(tmp_path):
    assert invoke(tmp_path, 'claude', durable=False).returncode == 0
    assert not (tmp_path / 'store.json').exists()
    assert json.loads((tmp_path / 'handoff.json').read_text())['resume']['open_loops']


def test_schedule_contract_requires_each_nodes_catchup_before_enablement(tmp_path):
    import durable_checkpoint
    reports = [dict(node=n, cutoff='2026-11-19T12:00:00Z', mode='run', errors=[],
        unfiled_before_cutoff=0, ready_for_durable_filing=True) for n in ('one', 'two')]
    with pytest.raises(ValueError):
        durable_checkpoint.schedule_request('fixture', str(tmp_path), ['one', 'two'], reports[:1])
    request = durable_checkpoint.schedule_request('fixture', str(tmp_path), ['one', 'two'], reports)
    assert request['interval_seconds'] == 14400
    assert request['target_session'] == 'fixture'
    assert request['checkpoint_option'] == 'durable'
    reports[1]['unfiled_before_cutoff'] = 1
    with pytest.raises(ValueError):
        durable_checkpoint.schedule_request('fixture', str(tmp_path), ['one', 'two'], reports)


@pytest.mark.parametrize('provider', ['claude', 'codex'])
def test_all_carried_types_use_approval_routes_and_actual_receipts(tmp_path, provider):
    items = [{**item(kind), 'type': kind, 'session_id': 'fixture',
              'disposition': 'File through fixture approval route', 'choices': ['approve', 'defer']}
             for kind in ('decision', 'commitment', 'lesson', 'knowledge')]
    items[0].update(entry='record', author='Fixture user', author_role='user', location='fixture conversation',
                    decision_record={'title': 'Fixture decision', 'scope': {'area': 'fixture'},
                                     'text': 'Full proposal', 'options': [], 'why': 'Fixture reason'})
    def profile(binding):
        import shlex
        return {'name': 'fixture', 'ask': {'command': shlex.join(binding['command']), 'owner_agent': 'fixture-owner'}}
    rows = [{'index': i, 'rule': 'R3', 'status': 'pending', 'ask_delivery': 'requested',
             'choices': ['approve', 'defer']} for i in range(4)]
    result = invoke(tmp_path, provider, items=items, rows=rows, profile=profile)
    # Approval asks are saved, but knowledge and lessons remain until their
    # normal native steps acknowledge actual capture/application.
    assert result.returncode == 1, result.stderr
    report = json.loads((tmp_path / 'report.json').read_text())
    assert len(report['filed']) == 2
    assert [i['type'] for i in report['unfiled']] == ['lesson', 'knowledge']
    assert all(r['receipt']['owner_agent'] == 'fixture-owner' for r in report['items'])
    assert len(json.loads((tmp_path / 'store.json').read_text())) == 4
    assert invoke(tmp_path, provider, items=items, rows=rows, profile=profile).returncode == 1
    assert len(json.loads((tmp_path / 'store.json').read_text())) == 4


def test_scheduled_adapter_records_report_and_failure_is_explicit(tmp_path):
    script = tmp_path / 'scheduled.py'
    script.write_text("import json,sys; from pathlib import Path; r=json.load(sys.stdin); "
                      "Path(__file__).with_suffix('.json').write_text(json.dumps(r)); "
                      "print(json.dumps({'status':'saved','receipt':{'destination':'Scheduled:fixture'}}))")
    result = invoke(tmp_path, 'codex', extra=['--scheduled-report', f'{sys.executable} {script}'])
    assert result.returncode == 0, result.stderr
    saved = json.loads(script.with_suffix('.json').read_text())
    assert len(saved['report']['filed']) == 1
    assert saved['report']['unfiled'] == []
    assert json.loads((tmp_path / 'report.json').read_text())['scheduled_receipt']['destination'] == 'Scheduled:fixture'
    script.write_text("print('{}')")
    assert invoke(tmp_path, 'codex', extra=['--scheduled-report', f'{sys.executable} {script}']).returncode == 1
    assert 'Scheduled report' in str(json.loads((tmp_path / 'report.json').read_text())['errors'])


def test_invalid_checkpoint_still_has_a_failed_pass_report(tmp_path):
    invalid = {**item(), 'type': 'decision', 'disposition': 'Await approval'}
    result = invoke(tmp_path, 'codex', items=[invalid])
    assert result.returncode != 0
    report = json.loads((tmp_path / 'report.json').read_text())
    assert report['errors']
    assert report['unfiled']


def test_approved_user_decision_files_through_the_decisions_kind(tmp_path):
    decision = {**item('Approved fixture proposal'), 'type': 'decision', 'session_id': 'fixture',
        'disposition': 'File approved decision record', 'entry': 'record', 'author': 'Fixture user', 'author_role': 'user',
        'location': 'fixture conversation',
        'decision_record': {'title': 'Fixture decision', 'scope': {'area': 'fixture'}, 'text': 'Full proposal',
                            'options': [], 'why': 'Fixture reason'}}
    def profile(binding):
        return {'name': 'fixture', 'record_writes': {'decisions': binding}}
    rows = [{'index': 0, 'rule': 'R7', 'status': 'pending', 'answer': 'approve',
             'approval_source': 'Fixture user response'}]
    result = invoke(tmp_path, 'codex', items=[decision], rows=rows, profile=profile)
    assert result.returncode == 0, result.stderr
    receipt = json.loads((tmp_path / 'report.json').read_text())['filed'][0]['receipt']
    assert receipt['destination'].startswith('decisions:')
    assert receipt['identity']['text'] == decision['context']
    assert json.loads((tmp_path / 'handoff.json').read_text())['resume']['open_loops'] == []


def test_explicit_schedule_uses_only_configured_fixture_adapter(tmp_path):
    report = tmp_path / 'catchup.json'
    data = dict(node='fixture-node', cutoff='2026-11-19T12:00:00Z', mode='run',
                errors=[], unfiled_before_cutoff=0, ready_for_durable_filing=True)
    report.write_text(json.dumps(data))
    adapter = tmp_path / 'scheduler.py'
    adapter.write_text("import json,sys; from pathlib import Path; r=json.load(sys.stdin); "
        "Path(__file__).with_suffix('.json').write_text(json.dumps(r)); "
        "print(json.dumps({'status':'saved','receipt':{'job_key':r['job_key'],'destination':'Scheduled:fixture'}}))")
    command = [sys.executable, str(ROOT / 'scripts/lib/durable_checkpoint.py'),
        '--session-id', 'fixture', '--cwd', str(tmp_path), '--required-node', 'fixture-node',
        '--catchup-report', str(report), '--adapter', f'{sys.executable} {adapter}']
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    request = json.loads(adapter.with_suffix('.json').read_text())
    assert request['target_session'] == 'fixture'
    assert request['interval_seconds'] == 14400
    assert json.loads(result.stdout)['receipt']['job_key'] == 'FILE-4H:fixture'
    adapter.with_suffix('.json').unlink()
    data['ready_for_durable_filing'] = False
    report.write_text(json.dumps(data))
    assert subprocess.run(command, capture_output=True, text=True).returncode == 1
    assert not adapter.with_suffix('.json').exists()


def owned_ask_profile(binding):
    import shlex
    return {'name': 'fixture', 'ask': {'command': shlex.join(binding['command']),
                                     'owner_agent': 'fixture-owner'}}


@pytest.mark.parametrize('provider', ['claude', 'codex'])
@pytest.mark.parametrize('status', ['pending', 'dropped', 'failed', 'uncertain', 'read failed'])
@pytest.mark.parametrize('requested', [False, True])
def test_deferred_ask_judgment_is_not_delivery_authority(tmp_path, provider, status, requested):
    source = {**item('Deferred promise'), 'type': 'commitment', 'session_id': 'fixture',
              'disposition': 'Await a later decision', 'choices': ['approve', 'defer']}
    row = {'index': 0, 'rule': 'R3', 'status': status, 'reason': 'Deferred', 'error': 'Not ready'}
    if requested:
        row['ask_delivery'] = 'requested'
    result = invoke(tmp_path, provider, items=[source], rows=[row], profile=owned_ask_profile)
    if status == 'pending' and requested:
        assert result.returncode == 0, result.stderr
        assert json.loads((tmp_path / 'report.json').read_text())['filed'][0]['receipt']
        assert json.loads((tmp_path / 'handoff.json').read_text())['resume']['open_loops'] == []
    else:
        assert result.returncode == 1, result.stderr
        assert not (tmp_path / 'store.json').exists()
        report = json.loads((tmp_path / 'report.json').read_text())
        assert report['filed'] == [] and report['unfiled'] == [source]
        assert report['items'][0]['status'] == status
        assert invoke(tmp_path, provider, durable=False, items=[]).returncode == 0
        assert json.loads((tmp_path / 'handoff.json').read_text())['resume']['open_loops'] == [source]


@pytest.mark.parametrize('failure', ['exception', 'no-file', 'keep-warm', 'lint-no-resume', 'lint-no-loops', 'profile-error', 'filing-error'])
@pytest.mark.parametrize('adapter_failure', [False, True])
def test_checkpoint_failures_publish_report_without_using_stale_handoff(tmp_path, monkeypatch, failure, adapter_failure):
    import handoff
    import durable_checkpoint
    from types import SimpleNamespace
    profile = tmp_path / 'profile.json'
    profile.write_text(json.dumps({'name': 'fixture'}))
    rows = tmp_path / 'rows.json'
    rows.write_text('[]')
    if failure == 'profile-error':
        profile.write_text('{')
    if failure == 'filing-error':
        rows.write_text('{')
    path = tmp_path / 'handoff.json'
    source = {**item('Still pending'), 'disposition': 'File later'}
    retained = {**item('Earlier pending'), 'disposition': 'File later'}
    supplied = {'resume': {'next_action': 'Continue fixture work'}, 'session_items': [source]}
    monkeypatch.setattr(handoff, 'retained_session_items', lambda *_: [retained])
    monkeypatch.setattr(handoff, 'resolve_path', lambda *_: str(path))
    original = b'{"resume":{"open_loops":[],"next_action":"stale continuation"}}'
    if failure == 'keep-warm':
        path.write_bytes(original)
    def checkpoint(*_, **__):
        if failure == 'exception':
            raise OSError('fixture checkpoint refused')
        if failure.startswith('lint'):
            path.write_text(json.dumps({} if failure == 'lint-no-resume' else {'resume': {}}))
            return handoff.CheckpointResult(str(path), 1, '', ['fixture lint failure'])
        return handoff.CheckpointResult('' if failure == 'keep-warm' else str(path), 0,
                                        'No handoff written' if failure == 'keep-warm' else '', [])
    monkeypatch.setattr(handoff, 'checkpoint', checkpoint)
    script = tmp_path / 'reporter.py'
    script.write_text("import json,sys; from pathlib import Path; r=json.load(sys.stdin); "
        "Path(__file__).with_suffix('.json').write_text(json.dumps(r)); print(" +
        ("'{}'" if adapter_failure else "json.dumps({'status':'saved','receipt':{'destination':'Scheduled:fixture'}})") + ")")
    args = SimpleNamespace(user_profile=str(profile), repository_profile=[], filing=str(rows),
        report=str(tmp_path / 'report.json'), session_id='fixture', cwd=str(tmp_path),
        trigger='checkpoint', scheduled_report=f'{sys.executable} {script}')
    result = durable_checkpoint.run(handoff, supplied, args)
    assert result.exit_code == 1
    report = json.loads(Path(args.report).read_text())
    assert report['filed'] == [] and report['unfiled'] == [source, retained]
    assert report['next_action'] == 'Continue fixture work'
    assert report['errors'] and report['already_settled'] == []
    published = json.loads(script.with_suffix('.json').read_text())['report']
    assert published['unfiled'] == [source, retained] and published['errors']
    if adapter_failure:
        assert 'Scheduled report' in str(report['errors'])
    if failure == 'keep-warm':
        assert path.read_bytes() == original
    assert handoff.retained_session_items('fixture') == [retained]


@pytest.mark.parametrize('problem', ['no-owner', 'wrong-owner', 'no-choices', 'uncertain'])
def test_requested_ask_guards_retain_source_and_actual_outcome(tmp_path, problem):
    source = {**item('Guarded promise'), 'type': 'commitment', 'session_id': 'fixture',
              'disposition': 'Await receipt', 'choices': ['approve', 'defer']}
    row = {'index': 0, 'rule': 'R3', 'status': 'pending', 'ask_delivery': 'requested'}
    def profile(binding):
        result = owned_ask_profile(binding)
        if problem == 'no-owner':
            result['ask'].pop('owner_agent')
        if problem == 'wrong-owner':
            script = tmp_path / 'store.py'
            script.write_text(script.read_text().replace("r['item'].get('owner_agent')", "'different-owner'"))
        return result
    if problem == 'no-choices':
        source.pop('choices')
    result = invoke(tmp_path, 'codex', mode='lost' if problem == 'uncertain' else 'ok',
                    items=[source], rows=[row], profile=profile)
    assert result.returncode == 1
    report = json.loads((tmp_path / 'report.json').read_text())
    assert report['filed'] == [] and report['unfiled'] == [source]
    assert json.loads((tmp_path / 'handoff.json').read_text())['resume']['open_loops'] == [source]
    if problem in ('no-owner', 'no-choices'):
        assert not (tmp_path / 'store.json').exists()
    if problem == 'uncertain':
        assert report['items'][0]['status'] == 'uncertain'
        assert invoke(tmp_path, 'codex', items=[source], rows=[row], profile=profile).returncode == 0
        assert len(json.loads((tmp_path / 'store.json').read_text())) == 1


def test_claimed_filed_ask_requires_matching_identity_receipt(tmp_path):
    source = {**item('Unacknowledged promise'), 'type': 'commitment', 'session_id': 'fixture',
              'disposition': 'Await receipt', 'choices': ['approve', 'defer']}
    row = {'index': 0, 'rule': 'R3', 'status': 'filed', 'destination': 'asks:wrong',
           'receipt': {'owner_agent': 'fixture-owner', 'destination': 'asks:wrong',
                       'identity': {'session_id': 'another', 'produced_at': source['produced_at'],
                                    'text': source['context']}}}
    result = invoke(tmp_path, 'codex', items=[source], rows=[row], profile=owned_ask_profile)
    assert result.returncode == 1
    assert json.loads((tmp_path / 'report.json').read_text())['unfiled'] == [source]
    assert not (tmp_path / 'store.json').exists()


@pytest.mark.parametrize('provider', ['claude', 'codex'])
@pytest.mark.parametrize('kind', ['tickets', 'projects', 'documents', 'scheduled_jobs'])
@pytest.mark.parametrize('status', ['dropped', 'failed', 'uncertain', 'read failed', 'pending', 'filed'])
@pytest.mark.parametrize('read_status', ['ok', 'failed'])
def test_record_judgment_controls_effects_and_retention(tmp_path, provider, kind, status, read_status):
    source = {**item('Record judgment', record_kind=kind), 'session_id': 'fixture',
              'disposition': 'Retain until filing is authorized'}
    row = dict(index=0, rule='R2', status=status, read_status=read_status,
               reason='Deferred judgment', destination='planned')
    profile = lambda binding: {'name': 'fixture', 'record_writes': {kind: binding}}
    result = invoke(tmp_path, provider, items=[source], rows=[row], profile=profile)
    permitted = status in ('pending', 'filed') and read_status == 'ok'
    assert result.returncode == (0 if permitted else 1), result.stderr
    report = json.loads((tmp_path / 'report.json').read_text())
    assert report['next_action'] == 'Continue fixture work'
    if permitted:
        assert report['filed'][0]['receipt']['identity']['text'] == source['context']
        assert report['unfiled'] == []
        assert invoke(tmp_path, provider, items=[source], rows=[row], profile=profile).returncode == 0
        assert len(json.loads((tmp_path / 'store.json').read_text())) == 1
    else:
        assert not (tmp_path / 'store.json').exists()
        assert report['filed'] == [] and report['unfiled'] == [source]
        assert invoke(tmp_path, provider, durable=False, items=[]).returncode == 0
        assert json.loads((tmp_path / 'handoff.json').read_text())['resume']['open_loops'] == [source]


@pytest.mark.parametrize('provider', ['claude', 'codex'])
@pytest.mark.parametrize('authority', ['configured', 'carried', 'absent'])
@pytest.mark.parametrize('receipt_owner', ['fixture-owner', 'unrelated', None])
def test_existing_ask_receipt_requires_authoritative_owner(tmp_path, provider, authority, receipt_owner):
    import record_write
    source = {**item('Saved promise'), 'type': 'commitment', 'session_id': 'fixture',
              'disposition': 'Await receipt', 'choices': ['approve', 'defer']}
    if authority == 'carried':
        source['owner_agent'] = 'fixture-owner'
    # Obtain the receipt from the actual fixture store, including ownerless saves.
    binding = store(tmp_path)
    script = tmp_path / 'store.py'
    script.write_text(script.read_text().replace('data.append(receipt);',
        f"receipt['owner_agent'] = {receipt_owner!r}; data.append(receipt);"))
    saved = record_write.execute(binding, 'asks', source, {'status': 'pending'})
    receipt = saved['receipt']
    row = dict(index=0, rule='R3', status='filed', receipt=receipt, destination=receipt['destination'])
    def profile(binding):
        result = owned_ask_profile(binding)
        if authority != 'configured':
            result['ask'].pop('owner_agent')
        return result
    result = invoke(tmp_path, provider, items=[source], rows=[row], profile=profile)
    permitted = authority != 'absent' and receipt_owner == 'fixture-owner'
    assert result.returncode == (0 if permitted else 1), result.stderr
    report = json.loads((tmp_path / 'report.json').read_text())
    assert report['unfiled'] == ([] if permitted else [source])
    assert len(json.loads((tmp_path / 'store.json').read_text())) == 1
    assert invoke(tmp_path, provider, durable=False, items=[]).returncode == 0
    assert json.loads((tmp_path / 'handoff.json').read_text())['resume']['open_loops'] == ([] if permitted else [source])


@pytest.mark.parametrize('provider', ['claude', 'codex'])
def test_requested_ask_uses_carried_owner(tmp_path, provider):
    source = {**item('Owned promise'), 'type': 'commitment', 'session_id': 'fixture',
              'owner_agent': 'fixture-owner', 'disposition': 'Deliver promise', 'choices': ['approve', 'defer']}
    def profile(binding):
        result = owned_ask_profile(binding)
        result['ask'].pop('owner_agent')
        return result
    row = dict(index=0, rule='R3', status='pending', ask_delivery='requested')
    result = invoke(tmp_path, provider, items=[source], rows=[row], profile=profile)
    assert result.returncode == 0, result.stderr
    report = json.loads((tmp_path / 'report.json').read_text())
    assert report['filed'][0]['receipt']['owner_agent'] == 'fixture-owner'
    assert report['unfiled'] == []


@pytest.mark.parametrize('provider', ['claude', 'codex'])
def test_omitted_judgment_retains_original_without_effects(tmp_path, provider):
    source = {**item('Omitted judgment'), 'session_id': 'fixture', 'disposition': 'File later'}
    assert invoke(tmp_path, provider, items=[source], rows=[]).returncode == 1
    assert not (tmp_path / 'store.json').exists()
    assert json.loads((tmp_path / 'report.json').read_text())['unfiled'] == [source]
    assert invoke(tmp_path, provider, durable=False, items=[]).returncode == 0
    assert json.loads((tmp_path / 'handoff.json').read_text())['resume']['open_loops'] == [source]


@pytest.mark.parametrize('provider', ['claude', 'codex'])
@pytest.mark.parametrize('rule', ['R5', 'R7'])
@pytest.mark.parametrize('status', ['dropped', 'failed', 'uncertain'])
def test_deferred_new_ticket_and_approved_decision_do_not_write(tmp_path, provider, rule, status):
    source = {**item('Deferred approved work'), 'session_id': 'fixture', 'disposition': 'Wait'}
    row = dict(index=0, rule=rule, status=status, read_status='ok', reason='Deferred',
               priority='p2', priority_reason='Fixture priority', answer='approve', approval_source='User reply')
    if rule == 'R7':
        source.update(type='decision', entry='record', author='Fixture user', author_role='user', location='Fixture chat',
                      decision_record=dict(title='Approved', scope={'area': 'fixture'}, text='Approved text',
                                           options=[], why='Fixture reason'))
    def profile(binding):
        return dict(name='fixture', record_writes={k: binding for k in ('tickets', 'decisions')})
    assert invoke(tmp_path, provider, items=[source], rows=[row], profile=profile).returncode == 1
    assert not (tmp_path / 'store.json').exists()
    report = json.loads((tmp_path / 'report.json').read_text())
    assert report['unfiled'] == [source] and report['items'][0]['status'] == status


@pytest.mark.parametrize('bad', [[], 'ok', None, 12, {},
    {'node': []}, {'node': 'fixture', 'cutoff': []},
    {'node': 'fixture', 'cutoff': None}])
def test_malformed_catchup_report_refuses_before_scheduler(tmp_path, bad):
    path = tmp_path / 'catchup.json'
    path.write_text(json.dumps(bad))
    adapter = tmp_path / 'scheduler.py'
    adapter.write_text("from pathlib import Path; Path(__file__).with_suffix('.called').touch()")
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/lib/durable_checkpoint.py'),
        '--session-id', 'fixture', '--cwd', str(tmp_path), '--required-node', 'fixture',
        '--catchup-report', str(path), '--adapter', f'{sys.executable} {adapter}'],
        capture_output=True, text=True)
    assert result.returncode == 1
    assert result.stderr.strip() and 'Traceback' not in result.stderr
    assert not adapter.with_suffix('.called').exists()


@pytest.mark.parametrize('change', [dict(node='other'), dict(cutoff='bad'), dict(mode='inspect'),
    dict(ready_for_durable_filing=False), dict(unfiled_before_cutoff=1), dict(errors=['failed']),
    dict(unfiled_before_cutoff=False), dict(unfiled_before_cutoff=0.0)])
def test_schedule_requires_valid_matching_proof(change):
    import durable_checkpoint
    proof = dict(node='fixture', cutoff='2026-11-19T12:00:00Z', mode='run',
                 ready_for_durable_filing=True, unfiled_before_cutoff=0, errors=[])
    proof.update(change)
    with pytest.raises(ValueError):
        durable_checkpoint.schedule_request('fixture', '/fixture', ['fixture'], [proof])


@pytest.mark.parametrize('nodes', [None, [], '', [''], [None], [[]], ['fixture', 'fixture']])
def test_schedule_refuses_malformed_required_nodes(nodes):
    import durable_checkpoint
    with pytest.raises(ValueError):
        durable_checkpoint.schedule_request('fixture', '/fixture', nodes, [])


def test_schedule_requires_same_cutoff_for_all_nodes():
    import durable_checkpoint
    reports = [dict(node=node, cutoff=cutoff, mode='run', ready_for_durable_filing=True,
                    unfiled_before_cutoff=0, errors=[])
               for node, cutoff in [('one', '2026-11-19T12:00:00Z'), ('two', '2026-11-19T13:00:00Z')]]
    with pytest.raises(ValueError):
        durable_checkpoint.schedule_request('fixture', '/fixture', ['one', 'two'], reports)


@pytest.mark.parametrize('provider', ['claude', 'codex'])
def test_rows_for_two_equal_loops_each_reach_their_own_loop(tmp_path, provider):
    loop = {'context': 'Untyped legacy loop', 'disposition': 'Drop at the next filing pass'}
    rows = [{'index': index, 'rule': 'R6', 'status': 'dropped', 'reason': 'Already recorded.'} for index in (0, 1)]
    result = invoke(tmp_path, provider, items=[], rows=rows, loops=[loop, dict(loop)])
    assert result.returncode == 0, result.stderr
    report = json.loads((tmp_path / 'report.json').read_text())
    assert report['errors'] == [] and report['unfiled'] == [] and report['already_settled'] == []
    assert [entry['index'] for entry in report['items']] == [0, 1]


def settle(tmp_path, entry):
    receipts = tmp_path / 'receipts.jsonl'
    receipts.write_text(json.dumps({
        'identity': {'session_id': entry['session_id'], 'produced_at': entry['produced_at'],
                     'type': entry['type'], 'text': entry['context']},
        'disposition': 'dropped', 'reason': 'Settled elsewhere.', 'destination': None,
        'settled_at': '2026-11-22T12:00:00+00:00', 'settled_by': 'other'}) + '\n')
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/lib/handoff.py'), 'settle-identity',
                             '--receipts', str(receipts)], text=True, capture_output=True,
                            env={**os.environ, 'HANDOFF_LEDGER_DIR': str(tmp_path / 'ledger')})
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('provider', ['claude', 'codex'])
def test_a_row_for_a_settled_item_is_skipped_and_later_rows_follow_their_item(tmp_path, provider):
    settled = {**item('Settled elsewhere'), 'session_id': 'fixture', 'disposition': 'File in fixture record'}
    other = {**item('Still to file'), 'session_id': 'fixture', 'disposition': 'File in fixture record'}
    settle(tmp_path, settled)
    rows = [{'index': 0, 'rule': 'R2', 'status': 'pending', 'read_status': 'ok'},
            {'index': 1, 'rule': 'R2', 'status': 'pending', 'read_status': 'ok'}]
    result = invoke(tmp_path, provider, items=[settled, other], rows=rows)
    assert result.returncode == 0, result.stderr
    report = json.loads((tmp_path / 'report.json').read_text())
    assert report['already_settled'] == [settled]
    assert [row['receipt']['identity']['text'] for row in report['filed']] == ['Still to file']
    assert [row['identity']['text'] for row in json.loads((tmp_path / 'store.json').read_text())] == ['Still to file']


def test_an_item_settled_by_another_session_mid_pass_is_still_filed_from_the_written_handoff(tmp_path, monkeypatch):
    import handoff
    import durable_checkpoint
    from types import SimpleNamespace
    for key, value in {'HANDOFF_LEDGER_DIR': 'ledger', 'HANDOFF_STATE_DIR': 'state',
                       'HANDOFF_PATH': 'handoff.json'}.items():
        monkeypatch.setenv(key, str(tmp_path / value))
    monkeypatch.setenv('CLAUDE_CODE_ENTRYPOINT', 'cli')
    monkeypatch.setenv('CODEX_THREAD_ID', '')
    binding = store(tmp_path)
    (tmp_path / 'profile.json').write_text(json.dumps({'name': 'fixture', 'record_writes': {'tickets': binding}}))
    first = {**item('First to file'), 'session_id': 'fixture', 'disposition': 'File in fixture record'}
    second = {**item('Settled elsewhere mid-pass'), 'session_id': 'fixture', 'disposition': 'File in fixture record'}
    rows = tmp_path / 'rows.json'
    rows.write_text(json.dumps([{'index': i, 'rule': 'R2', 'status': 'pending', 'read_status': 'ok'} for i in (0, 1)]))
    real = handoff.checkpoint

    def checkpoint(*args, **kwargs):
        result = real(*args, **kwargs)
        # Another session settles the second item after this pass wrote its handoff.
        handoff.write_settlement_receipts([handoff.settlement_receipt(second, 'other', 'dropped', 'Not needed.')])
        return result
    monkeypatch.setattr(handoff, 'checkpoint', checkpoint)
    supplied = {'resume': {'headline': 'Continue fixture work', 'next_action': 'Continue fixture work',
                           'session_summary': 'Investigated fixture work and retained the result.', 'open_loops': []},
                'session_items': [first, second], 'spawned_processes': []}
    args = SimpleNamespace(user_profile=str(tmp_path / 'profile.json'), repository_profile=[], filing=str(rows),
                           report=str(tmp_path / 'report.json'), session_id='fixture', cwd=str(tmp_path),
                           trigger='checkpoint', scheduled_report=None)
    result = durable_checkpoint.run(handoff, supplied, args)
    report = json.loads((tmp_path / 'report.json').read_text())
    assert report['errors'] == [] and report['already_settled'] == [] and 'skipped_rows' not in report
    assert [row['receipt']['identity']['text'] for row in report['filed']] == ['First to file', 'Settled elsewhere mid-pass']
    assert result.exit_code == 0
