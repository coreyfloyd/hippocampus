"""Catch-up uses only supplied handoff stores and fixture record writers."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from test_record_writes import item, store

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'scripts/lib/filing_catchup.py'
CUTOFF = '2026-11-19T12:00:00Z'


def setup(tmp_path, items, mode='ok'):
    sources = tmp_path / 'sources'
    sources.mkdir()
    data = {'subject': {'session_id': 'carrier', 'working_directory': '/fixture'},
            'written_at': '2026-11-18T12:00:00Z', 'resume': {'open_loops': items}}
    for provider in ('claude', 'codex'):
        (sources / (provider + '.json')).write_text(json.dumps(data))
    profile = {'name': 'fixture', 'record_writes': {'tickets': store(tmp_path, mode)}}
    (tmp_path / 'profile.json').write_text(json.dumps(profile))
    decisions = [{'identity': {'session_id': x['session_id'], 'produced_at': x['produced_at'],
                              'text': x['context']}, 'rule': 'R2', 'read_status': 'ok'} for x in items]
    (tmp_path / 'decisions.json').write_text(json.dumps(decisions))
    return sources


def run(tmp_path, command='run'):
    return subprocess.run([sys.executable, str(CLI), command, '--node', 'fixture-node',
        '--store', str(tmp_path / 'sources'), '--cutoff', CUTOFF,
        '--user-profile', str(tmp_path / 'profile.json'), '--decisions', str(tmp_path / 'decisions.json'),
        '--report', str(tmp_path / 'report.json')], text=True, capture_output=True,
        env={**os.environ, 'HOME': str(tmp_path / 'empty-home'), 'PYTHONDONTWRITEBYTECODE': '1'})


def report(tmp_path):
    return json.loads((tmp_path / 'report.json').read_text())


def test_files_both_provider_handoffs_once_and_recounts_without_rewriting(tmp_path):
    sources = setup(tmp_path, [item('first'), item('second')])
    before = {p: p.read_bytes() for p in sources.iterdir()}
    first = run(tmp_path)
    assert first.returncode == 0, first.stderr
    out = report(tmp_path)
    assert out['unfiled_before_cutoff'] == 0 and out['ready_for_durable_filing']
    assert len(out['items']) == 2
    assert all(row['destination'].startswith('tickets:') for row in out['items'])
    assert all(len(row['sources']) == 2 for row in out['items'])
    assert run(tmp_path).returncode == 0
    assert len(json.loads((tmp_path / 'store.json').read_text())) == 2
    assert all(p.read_bytes() == data for p, data in before.items())


def test_lost_receipt_keeps_unfiled_then_retry_looks_up(tmp_path):
    setup(tmp_path, [item()], 'lost')
    assert run(tmp_path).returncode == 1
    assert report(tmp_path)['unfiled_before_cutoff'] == 1
    assert not report(tmp_path)['ready_for_durable_filing']
    assert run(tmp_path).returncode == 0
    assert len(json.loads((tmp_path / 'store.json').read_text())) == 1


@pytest.mark.parametrize('problem', ['missing-store', 'invalid-json', 'missing-identity', 'missing-decision'])
def test_incomplete_inventory_or_judgment_blocks_cutover(tmp_path, problem):
    sources = setup(tmp_path, [item()])
    if problem == 'missing-store':
        for p in sources.iterdir(): p.unlink()
        sources.rmdir()
    elif problem == 'invalid-json':
        (sources / 'broken.json').write_text('{')
    elif problem == 'missing-identity':
        (sources / 'broken.json').write_text(json.dumps({'resume': {'open_loops': [{'context': 'unknown'}]}}))
    else:
        (tmp_path / 'decisions.json').write_text('[]')
    assert run(tmp_path).returncode == 1
    assert not report(tmp_path)['ready_for_durable_filing']


@pytest.mark.parametrize('item_type', ['decision', 'lesson', 'knowledge'])
def test_approval_is_owned_ask_with_identity_receipt(tmp_path, item_type):
    decision = item('Approve the decision document')
    decision['type'] = item_type
    setup(tmp_path, [decision])
    script = tmp_path / 'ask.py'
    script.write_text('''import json, sys
from pathlib import Path
r = json.load(sys.stdin)
p = Path(__file__).with_suffix('.json')
if r['operation'] == 'lookup':
 print(json.dumps({'status': 'found', 'receipt': json.loads(p.read_text())} if p.exists() else {'status': 'not_found'}))
else:
 receipt = {'identity': r['identity'], 'destination': 'asks:1', 'owner_agent': r['item']['owner_agent']}
 p.write_text(json.dumps(receipt)); print(json.dumps({'status': 'saved', 'receipt': receipt}))
''')
    config = {'name': 'fixture', 'ask': {'command': f'{sys.executable} {script}', 'owner_agent': 'filing-agent'}}
    (tmp_path / 'profile.json').write_text(json.dumps(config))
    (tmp_path / 'decisions.json').write_text(json.dumps([{'identity': {'session_id': decision['session_id'],
        'produced_at': decision['produced_at'], 'text': decision['context']}, 'rule': 'R3',
        'choices': ['approve', 'defer']}]))
    assert run(tmp_path).returncode == 0
    saved = report(tmp_path)['items'][0]
    assert saved['destination'] == 'asks:1'
    assert saved['receipt']['owner_agent'] == 'filing-agent'
    assert not (tmp_path / 'store.json').exists()


def test_inspect_never_writes(tmp_path):
    setup(tmp_path, [item()])
    result = run(tmp_path, 'inspect')
    assert result.returncode == 1
    assert not (tmp_path / 'store.json').exists()
    assert report(tmp_path)['unfiled_before_cutoff'] == 1


def test_newer_items_remain_in_source_without_blocking_old_cutoff(tmp_path):
    newer = {**item('later'), 'produced_at': CUTOFF}
    sources = setup(tmp_path, [item(), newer])
    assert run(tmp_path).returncode == 0
    assert len(report(tmp_path)['items']) == 1
    assert newer in json.loads((sources / 'codex.json').read_text())['resume']['open_loops']


def test_conflicting_copies_fail_inventory(tmp_path):
    sources = setup(tmp_path, [item()])
    path = sources / 'codex.json'
    data = json.loads(path.read_text())
    data['resume']['open_loops'][0]['record_kind'] = 'documents'
    path.write_text(json.dumps(data))
    assert run(tmp_path).returncode == 1
    assert 'conflicting' in str(report(tmp_path)['errors'])


@pytest.mark.parametrize('rule', ['R1', 'R6', 'R7'])
def test_no_drop_or_unapproved_document_can_clear_pass(tmp_path, rule):
    decision = {**item(), 'type': 'decision', 'author_role': 'agent'}
    setup(tmp_path, [decision])
    path = tmp_path / 'decisions.json'
    rows = json.loads(path.read_text())
    rows[0].update(rule=rule, reason='discard it')
    path.write_text(json.dumps(rows))
    assert run(tmp_path).returncode == 1
    assert report(tmp_path)['unfiled_before_cutoff'] == 1
    assert not (tmp_path / 'store.json').exists()


def test_source_changed_by_writer_blocks_cutover(tmp_path):
    sources = setup(tmp_path, [item()])
    script = tmp_path / 'store.py'
    text = script.read_text()
    text = text.replace("data.append(receipt);", "Path(" + repr(str(sources / 'new.json')) + ").write_text('{}'); data.append(receipt);")
    script.write_text(text)
    assert run(tmp_path).returncode == 1
    assert report(tmp_path)['errors']
    assert not report(tmp_path)['ready_for_durable_filing']


def test_saved_claim_without_receipt_never_clears_pass(tmp_path):
    setup(tmp_path, [item()])
    script = tmp_path / 'store.py'
    script.write_text("import json\nprint(json.dumps({'status': 'found', 'receipt': {}}))\n")
    assert run(tmp_path).returncode == 1
    assert report(tmp_path)['unfiled_before_cutoff'] == 1
    assert 'receipt' in str(report(tmp_path)['items'][0])
