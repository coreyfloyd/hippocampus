"""Durable checkpoints file fixture items without wrapping either provider."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from test_record_writes import store, item

ROOT = Path(__file__).resolve().parents[1]


def invoke(tmp_path, provider, mode='ok', durable=True, items=None, rows=None, profile=None, extra=()):
    binding = store(tmp_path, mode)
    script = tmp_path / 'store.py'
    script.write_text(script.read_text().replace("data.append(receipt);", "receipt['owner_agent'] = r['item'].get('owner_agent'); data.append(receipt);"))
    profile = profile(binding) if profile else {'name': 'fixture', 'record_writes': {'tickets': binding}}
    (tmp_path / 'profile.json').write_text(json.dumps(profile))
    (tmp_path / 'rows.json').write_text(json.dumps(rows if rows is not None else [{'index': 0, 'rule': 'R2',
        'status': 'pending', 'read_status': 'ok'}]))
    payload = {'resume': {'headline': 'Continue fixture work', 'next_action': 'Continue fixture work',
        'why': 'Fixture continuation', 'session_summary': 'Investigated fixture work and retained the result.', 'open_loops': []},
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
    items[0].update(author='Fixture user', author_role='user', location='fixture conversation',
                    decision_record={'title': 'Fixture decision', 'scope': 'fixture', 'text': 'Full proposal'})
    def profile(binding):
        import shlex
        return {'name': 'fixture', 'ask': {'command': shlex.join(binding['command']), 'owner_agent': 'fixture-owner'}}
    rows = [{'index': i, 'rule': 'R3', 'status': 'pending', 'choices': ['approve', 'defer']} for i in range(4)]
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


def test_approved_user_decision_uses_configured_document_folder(tmp_path):
    decision = {**item('Approved fixture proposal'), 'type': 'decision', 'session_id': 'fixture',
        'disposition': 'Write approved decision document', 'author': 'Fixture user',
        'author_role': 'user', 'location': 'fixture conversation',
        'decision_record': {'title': 'Fixture decision', 'scope': 'fixture', 'text': 'Full proposal'}}
    def profile(binding):
        return {'name': 'fixture', 'record_writes': {'documents': binding},
                'decision_records': {'default_folder': 'decisions/default',
                                     'scope_folders': {'fixture': 'decisions/fixture'}}}
    rows = [{'index': 0, 'rule': 'R7', 'status': 'pending', 'answer': 'approve',
             'approval_source': 'Fixture user response'}]
    result = invoke(tmp_path, 'codex', items=[decision], rows=rows, profile=profile)
    assert result.returncode == 0, result.stderr
    receipt = json.loads((tmp_path / 'report.json').read_text())['filed'][0]['receipt']
    assert receipt['folder'] == 'decisions/fixture'
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
