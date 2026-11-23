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
WRITTEN = '2026-11-18T12:00:00Z'


def carrier_identity(x):
    """The identity catch-up gives a loop in a ``setup`` handoff: its own fields, else the handoff's."""
    return {'session_id': x.get('session_id') or 'carrier', 'produced_at': x.get('produced_at') or WRITTEN,
            'text': x.get('context', '')}


def setup(tmp_path, items, mode='ok'):
    sources = tmp_path / 'sources'
    sources.mkdir()
    data = {'subject': {'session_id': 'carrier', 'working_directory': '/fixture'},
            'written_at': WRITTEN, 'resume': {'open_loops': items}}
    for provider in ('claude', 'codex'):
        (sources / (provider + '.json')).write_text(json.dumps(data))
    profile = {'name': 'fixture', 'record_writes': {'tickets': store(tmp_path, mode)}}
    (tmp_path / 'profile.json').write_text(json.dumps(profile))
    decisions = [{'identity': carrier_identity(x), 'rule': 'R2', 'read_status': 'ok'} for x in items]
    (tmp_path / 'decisions.json').write_text(json.dumps(decisions))
    return sources


def run(tmp_path, command='run', ledger=True):
    env = {**os.environ, 'HOME': str(tmp_path / 'empty-home'), 'PYTHONDONTWRITEBYTECODE': '1',
           'XDG_CONFIG_HOME': str(tmp_path / 'config'), 'HANDOFF_STATE_DIR': str(tmp_path / 'state'),
           'HANDOFF_LEDGER_DIR': str(tmp_path / 'ledger')}
    if not ledger:
        del env['HANDOFF_LEDGER_DIR']
    return subprocess.run([sys.executable, str(CLI), command, '--node', 'fixture-node',
        '--store', str(tmp_path / 'sources'), '--cutoff', CUTOFF,
        '--user-profile', str(tmp_path / 'profile.json'), '--decisions', str(tmp_path / 'decisions.json'),
        '--report', str(tmp_path / 'report.json')], text=True, capture_output=True, env=env)


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


@pytest.mark.parametrize('problem', ['missing-store', 'invalid-json', 'non-array-loops', 'missing-decision'])
def test_incomplete_inventory_or_judgment_blocks_cutover(tmp_path, problem):
    sources = setup(tmp_path, [item()])
    if problem == 'missing-store':
        for p in sources.iterdir(): p.unlink()
        sources.rmdir()
    elif problem == 'invalid-json':
        (sources / 'broken.json').write_text('{')
    elif problem == 'non-array-loops':
        (sources / 'broken.json').write_text(json.dumps({'resume': {'open_loops': 'unknown'}}))
    else:
        (tmp_path / 'decisions.json').write_text('[]')
    assert run(tmp_path).returncode == 1
    assert not report(tmp_path)['ready_for_durable_filing']


@pytest.mark.parametrize('item_type', ['decision', 'lesson', 'knowledge'])
@pytest.mark.parametrize('judgment', ['omitted', 'filed', 'requested'])
def test_approval_is_owned_ask_with_identity_receipt(tmp_path, item_type, judgment):
    decision = item('Approve the decision document')
    decision['type'] = item_type
    sources = setup(tmp_path, [decision])
    before = {p: p.read_bytes() for p in sources.iterdir()}
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
    rows = json.loads((tmp_path / 'decisions.json').read_text())
    if judgment != 'omitted':
        rows[0]['status'] = 'filed' if judgment == 'filed' else 'pending'
        rows[0]['ask_delivery'] = 'requested'
    (tmp_path / 'decisions.json').write_text(json.dumps(rows))
    native = item_type in ('lesson', 'knowledge')
    import durable_checkpoint
    for _ in range(2):
        assert run(tmp_path).returncode == int(native)
        out = report(tmp_path)
        assert out['unfiled_before_cutoff'] == int(native)
        assert out['ready_for_durable_filing'] is (not native)
        if native:
            assert out['items'][0]['status'] == 'pending'
            assert out['items'][0]['ask_status'] == 'filed'
            with pytest.raises(ValueError):
                durable_checkpoint.schedule_request('fixture', str(tmp_path), ['fixture-node'], [out])
        else:
            assert durable_checkpoint.schedule_request('fixture', str(tmp_path), ['fixture-node'], [out])
    assert all(p.read_bytes() == raw for p, raw in before.items())
    saved = report(tmp_path)['items'][0]
    assert saved['receipt'] == json.loads(script.with_suffix('.json').read_text())
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


def writer_checkpoint(tmp_path, updates):
    """A controlled writer checkpoints supplied handoffs after saving a receipt."""
    script = tmp_path / 'store.py'
    text = script.read_text()
    checkpoint = '\n'.join('    Path(' + repr(str(path)) + ').write_text(' + repr(json.dumps(data)) + ')'
                           for path, data in updates.items())
    script.write_text(text.replace('    data.append(receipt);', checkpoint + '\n    data.append(receipt);'))


@pytest.mark.parametrize('checkpoint', ['newer-only', 'old-and-newer', 'empty'])
def test_supported_checkpoint_does_not_block_eligible_recount(tmp_path, checkpoint):
    sources = setup(tmp_path, [item()])
    data = json.loads((sources / 'claude.json').read_text())
    newer = {**item('new work'), 'produced_at': CUTOFF}
    data['written_at'] = CUTOFF
    data['resume']['open_loops'] = ([] if checkpoint == 'empty' else [newer]
                                  if checkpoint == 'newer-only' else [item(), newer])
    target = sources / ('active.json' if checkpoint != 'old-and-newer' else 'claude.json')
    if checkpoint != 'old-and-newer':
        target.write_text(json.dumps({**data, 'resume': {'open_loops': []}}))
    writer_checkpoint(tmp_path, {target: data})
    untouched = (sources / 'codex.json').read_bytes()
    assert run(tmp_path).returncode == 0
    assert report(tmp_path)['unfiled_before_cutoff'] == 0
    assert report(tmp_path)['ready_for_durable_filing']
    after = target.read_bytes()
    assert json.loads(after) == data
    assert run(tmp_path).returncode == 0
    assert target.read_bytes() == after
    assert (sources / 'codex.json').read_bytes() == untouched
    assert len(json.loads((tmp_path / 'store.json').read_text())) == 1


@pytest.mark.parametrize('changed', ['new-identity', 'proposal', 'choices', 'anchor'])
def test_checkpoint_cannot_hide_old_eligible_change(tmp_path, changed):
    original = item()
    if changed == 'proposal': original['decision_record'] = {'text': 'first proposal'}
    if changed == 'choices': original['choices'] = ['approve', 'defer']
    if changed == 'anchor': original['anchor'] = {'ticket': 'example/repo#1'}
    sources = setup(tmp_path, [original])
    data = json.loads((sources / 'claude.json').read_text())
    replacement = dict(original)
    if changed == 'new-identity': replacement['context'] = 'new old work'
    elif changed == 'proposal': replacement['decision_record'] = {'text': 'different proposal'}
    elif changed == 'choices': replacement['choices'] = ['approve different text', 'defer']
    else: replacement['anchor'] = {'ticket': 'example/repo#2'}
    data['resume']['open_loops'] = [replacement]
    writer_checkpoint(tmp_path, {sources / 'claude.json': data})
    assert run(tmp_path).returncode == 1
    assert report(tmp_path)['unfiled_before_cutoff'] > 0
    assert not report(tmp_path)['ready_for_durable_filing']
    after = {path: path.read_bytes() for path in sources.iterdir()}
    assert run(tmp_path).returncode == 1
    assert all(path.read_bytes() == content for path, content in after.items())


@pytest.mark.parametrize('enrichment', [
    {'status': 'pending', 'recorded': True},
    {'anchor': {'ticket': 'example/repo#1'}},
    {'anchor': {'project': 'example/project'}},
])
def test_carried_metadata_enrichment_merges_without_trusting_recorded_flag(tmp_path, enrichment):
    sources = setup(tmp_path, [item()])
    path = sources / 'codex.json'
    data = json.loads(path.read_text())
    data['resume']['open_loops'][0].update(enrichment)
    path.write_text(json.dumps(data))
    before = {p: p.read_bytes() for p in sources.iterdir()}
    assert run(tmp_path).returncode == 0
    saved = report(tmp_path)['items'][0]
    assert saved['receipt']['identity'] == saved['identity']
    assert len(saved['copies']) == 2
    assert saved['item'].get('anchor') == enrichment.get('anchor')
    assert run(tmp_path).returncode == 0
    assert len(json.loads((tmp_path / 'store.json').read_text())) == 1
    assert all(p.read_bytes() == content for p, content in before.items())


@pytest.mark.parametrize('field,first,second', [
    ('choices', ['approve', 'defer'], ['approve changed proposal', 'defer']),
    ('decision_record', {'text': 'policy one'}, {'text': 'policy two'}),
    ('ask_text', 'Save the first text', 'Save the other text'),
    ('author', 'User', 'Different user'),
    ('anchor', {'ticket': 'example/repo#1'}, {'ticket': 'example/repo#2'}),
])
def test_substantive_copies_never_file_an_arbitrary_first_proposal(tmp_path, field, first, second):
    original = {**item(), field: first}
    sources = setup(tmp_path, [original])
    path = sources / 'codex.json'
    data = json.loads(path.read_text())
    data['resume']['open_loops'][0][field] = second
    path.write_text(json.dumps(data))
    before = {p: p.read_bytes() for p in sources.iterdir()}
    for _ in range(2):
        assert run(tmp_path).returncode == 1
        assert not (tmp_path / 'store.json').exists()
        out = report(tmp_path)
        assert out['unfiled_before_cutoff'] == 1
        assert len(out['items'][0]['copies']) == 2
    assert all(p.read_bytes() == content for p, content in before.items())


def test_checkpoint_between_writes_preserves_remaining_old_work(tmp_path):
    old = [item('first'), item('second')]
    sources = setup(tmp_path, old)
    data = json.loads((sources / 'claude.json').read_text())
    data['written_at'] = CUTOFF
    data['resume']['open_loops'].append({**item('later'), 'produced_at': CUTOFF})
    writer_checkpoint(tmp_path, {sources / 'claude.json': data})
    assert run(tmp_path).returncode == 0
    assert len(json.loads((tmp_path / 'store.json').read_text())) == 2
    assert report(tmp_path)['unfiled_before_cutoff'] == 0
    assert json.loads((sources / 'claude.json').read_text()) == data


@pytest.mark.parametrize('bad_anchor', [None, ['example/repo#1']])
def test_invalid_duplicate_anchor_cannot_leave_first_copy_fileable(tmp_path, bad_anchor):
    sources = setup(tmp_path, [item()])
    path = sources / 'codex.json'
    data = json.loads(path.read_text())
    data['resume']['open_loops'][0]['anchor'] = bad_anchor
    path.write_text(json.dumps(data))
    before = {p: p.read_bytes() for p in sources.iterdir()}
    for _ in range(2):
        assert run(tmp_path).returncode == 1
        assert not (tmp_path / 'store.json').exists()
        assert report(tmp_path)['unfiled_before_cutoff'] == 1
        assert len(report(tmp_path)['items'][0]['copies']) == 2
    assert all(p.read_bytes() == content for p, content in before.items())


@pytest.mark.parametrize('status', ['pending', 'dropped', 'failed', 'uncertain', 'read failed'])
def test_explicit_deferred_judgment_never_writes(tmp_path, status):
    setup(tmp_path, [item()])
    path = tmp_path / 'decisions.json'
    rows = json.loads(path.read_text())
    rows[0].update(status=status, reason='Deferred', error='Not ready')
    path.write_text(json.dumps(rows))
    assert run(tmp_path).returncode == 1
    assert report(tmp_path)['items'][0]['status'] == status
    assert report(tmp_path)['unfiled_before_cutoff'] == 1
    assert not (tmp_path / 'store.json').exists()


@pytest.mark.parametrize('provider', ['claude', 'codex'])
@pytest.mark.parametrize('kind', ['lesson', 'knowledge'])
@pytest.mark.parametrize('rule', ['R3', 'R4'])
@pytest.mark.parametrize('mode', ['ok', 'lost'])
def test_native_approval_retry_cannot_enable_until_capture(tmp_path, provider, kind, rule, mode):
    import record_write
    import durable_checkpoint
    from test_durable_checkpoint import invoke, owned_ask_profile
    original = {**item('Capture this proposal'), 'type': kind, 'session_id': 'fixture',
                'disposition': 'Await native capture', 'choices': ['approve', 'defer']}
    sources = setup(tmp_path, [original], mode)
    binding = {'command': [sys.executable, str(tmp_path / 'store.py')]}
    script = tmp_path / 'store.py'
    script.write_text(script.read_text().replace('data.append(receipt);',
        "receipt['owner_agent'] = r['item']['owner_agent']; data.append(receipt);"))
    (tmp_path / 'profile.json').write_text(json.dumps(owned_ask_profile(binding)))
    judgment = dict(identity=record_write.identity(original), rule=rule, status='pending',
                    ask_delivery='requested', destination='ask')
    (tmp_path / 'decisions.json').write_text(json.dumps([judgment]))
    before = {p: p.read_bytes() for p in sources.iterdir()}
    for attempt in range(2):
        assert run(tmp_path).returncode == 1
        out = report(tmp_path)
        assert out['unfiled_before_cutoff'] == 1 and not out['ready_for_durable_filing']
        if mode == 'ok' or attempt:
            assert out['items'][0]['status'] == 'pending'
            assert out['items'][0]['ask_status'] == 'filed'
            assert out['items'][0]['receipt'] == json.loads((tmp_path / 'store.json').read_text())[0]
        else:
            assert out['items'][0]['status'] == 'uncertain'
            assert 'ask_status' not in out['items'][0]
        with pytest.raises(ValueError):
            durable_checkpoint.schedule_request('fixture', str(tmp_path), ['fixture-node'], [out])
    assert len(json.loads((tmp_path / 'store.json').read_text())) == 1
    assert all(p.read_bytes() == raw for p, raw in before.items())
    live = tmp_path / 'durable'
    live.mkdir()
    row = {k: v for k, v in judgment.items() if k != 'identity'}
    row['index'] = 0
    assert invoke(live, provider, items=[original], rows=[row], profile=owned_ask_profile).returncode == 1
    assert json.loads((live / 'report.json').read_text())['unfiled'] == [original]
    # Execute a fixture native capture, then pass its actual saved readback through
    # the existing native receipt route. Approval delivery alone never did this.
    capture = tmp_path / 'capture'
    capture.mkdir()
    capture_binding = store(capture)
    saved = record_write.execute(capture_binding, 'native_capture', original, {'status': 'pending'})
    assert saved['receipt'] == json.loads((capture / 'store.json').read_text())[0]
    native_row = dict(index=0, rule='R4', status='filed',
                      destination=saved['destination'], receipt=saved['receipt'])
    assert invoke(live, provider, items=[original], rows=[native_row], profile=owned_ask_profile).returncode == 0
    checkpoint = json.loads((live / 'handoff.json').read_text())
    assert checkpoint['resume']['open_loops'] == []
    assert checkpoint['resume']['next_action'] == 'Continue fixture work'
    # Model both source providers receiving the settled checkpoint; catch-up
    # itself never rewrites either source and re-inventories the current store.
    for path in sources.iterdir():
        path.write_text(json.dumps(checkpoint))
    assert run(tmp_path).returncode == 0
    assert report(tmp_path)['unfiled_before_cutoff'] == 0
    assert durable_checkpoint.schedule_request('fixture', str(tmp_path), ['fixture-node'], [report(tmp_path)])


def settle(path, *items, lines=()):
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [json.dumps({'identity': {'session_id': x['session_id'], 'produced_at': x['produced_at'],
                                     'type': x['type'], 'text': x['context']},
                        'disposition': 'filed', 'reason': 'filed by a wrap', 'destination': 'tickets:1',
                        'settled_at': '2026-11-20T12:00:00Z', 'settled_by': 'settler'}) for x in items]
    path.write_text(''.join(row + '\n' for row in [*lines, *rows]))


@pytest.mark.parametrize('ledger', [True, False])
def test_settled_identity_is_reported_and_never_filed(tmp_path, ledger):
    settled, open_item = item('settled'), item('open')
    setup(tmp_path, [settled, open_item])
    # With no ledger override the store sits beside the supplied handoff store, as for the carry step.
    settle((tmp_path / 'ledger' if ledger else tmp_path) / 'settled-identities.jsonl', settled)
    assert run(tmp_path, 'inspect', ledger=ledger).returncode == 1
    out = report(tmp_path)
    assert out['unfiled_before_cutoff'] == 1 and out['unique_items'] == 2 and not out['errors']
    assert out['already_settled'] == [{'identity': {'session_id': 'producer', 'produced_at': settled['produced_at'],
        'text': 'settled'}, 'type': 'progress', 'disposition': 'filed', 'settled_at': '2026-11-20T12:00:00Z'}]
    assert [row['identity']['text'] for row in out['items']] == ['open']
    assert run(tmp_path, ledger=ledger).returncode == 0
    out = report(tmp_path)
    assert out['ready_for_durable_filing'] and out['unfiled_before_cutoff'] == 0
    assert [row['identity']['text'] for row in out['items']] == ['open']
    written = json.loads((tmp_path / 'store.json').read_text())
    assert [row['identity'] for row in written] == [record_identity(open_item)]


def record_identity(x):
    return {'session_id': x['session_id'], 'produced_at': x['produced_at'], 'text': x['context']}


def test_receipt_for_another_type_does_not_settle(tmp_path):
    setup(tmp_path, [item()])
    settle(tmp_path / 'ledger/settled-identities.jsonl', {**item(), 'type': 'decision'})
    assert run(tmp_path, 'inspect').returncode == 1
    out = report(tmp_path)
    assert out['unfiled_before_cutoff'] == 1 and out['already_settled'] == []


def receipt(x, **changes):
    return {'identity': {'session_id': x['session_id'], 'produced_at': x['produced_at'], 'type': x['type'],
                         'text': x['context']}, 'disposition': 'filed', 'reason': 'filed by a wrap',
            'destination': 'tickets:1', 'settled_at': '2026-11-20T12:00:00Z', 'settled_by': 'settler', **changes}


def store_path(tmp_path):
    path = tmp_path / 'ledger/settled-identities.jsonl'
    path.parent.mkdir(exist_ok=True)
    return path


def written_identities(tmp_path):
    path = tmp_path / 'store.json'
    return [row['identity'] for row in json.loads(path.read_text())] if path.exists() else []


@pytest.mark.parametrize('lines', [
    pytest.param(lambda r: [r[:40], r], id='torn-line-then-valid-receipt'),
    pytest.param(lambda r: [b'', r], id='blank-middle-line'),
    pytest.param(lambda r: [b'[]', r], id='non-object-row'),
    pytest.param(lambda r: [json.dumps({'identity': {'session_id': 'producer'}}).encode(), r], id='no-valid-identity'),
    pytest.param(lambda r: [b'{"text": "\xff"}', r], id='undecodable-line'),
])
def test_lines_the_carry_step_skips_are_warnings_and_never_block(tmp_path, lines):
    settled, open_item = item('settled'), item('open')
    setup(tmp_path, [settled, open_item])
    store_path(tmp_path).write_bytes(b'\n'.join(lines(json.dumps(receipt(settled)).encode())) + b'\n')
    assert run(tmp_path).returncode == 0, report(tmp_path)
    out = report(tmp_path)
    assert out['errors'] == [] and out['ready_for_durable_filing']
    (warning,) = out['warnings']
    assert '1 lines skipped' in warning and warning.endswith('first lines: 1')
    assert [row['identity']['text'] for row in out['already_settled']] == ['settled']
    assert written_identities(tmp_path) == [record_identity(open_item)]


def test_skipped_lines_are_counted_with_the_first_twenty_line_numbers(tmp_path):
    setup(tmp_path, [item()])
    store_path(tmp_path).write_text('[]\n' * 25)
    assert run(tmp_path, 'inspect').returncode == 1
    (warning,) = report(tmp_path)['warnings']
    assert '25 lines skipped' in warning and warning.endswith(', '.join(map(str, range(1, 21))))


def test_unreadable_store_is_an_error_and_blocks_writes(tmp_path):
    setup(tmp_path, [item()])
    store_path(tmp_path).mkdir()
    assert run(tmp_path).returncode == 1
    out = report(tmp_path)
    assert len(out['errors']) == 1 and 'unreadable' in out['errors'][0]
    assert [(row['status'], row['error']) for row in out['items']] == [
        ('pending', 'settled store unreadable; no write attempted')]
    assert written_identities(tmp_path) == []


def test_strict_invalid_receipt_settles_and_warns_only_for_carried_identities(tmp_path):
    settled = item()
    setup(tmp_path, [settled])
    unrelated = receipt(item('unrelated'), disposition='keep')
    store_path(tmp_path).write_text(json.dumps(unrelated) + '\n'
                                    + json.dumps(receipt(settled, disposition='keep', extra=1)) + '\n')
    assert run(tmp_path).returncode == 0
    out = report(tmp_path)
    assert out['errors'] == [] and len(out['warnings']) == 1 and 'line 2' in out['warnings'][0]
    assert out['already_settled'][0]['disposition'] == 'keep' and out['items'] == []
    assert written_identities(tmp_path) == []


def test_receipt_text_with_unicode_line_separators_matches(tmp_path):
    settled = item('first\u2028second\u0085third')
    setup(tmp_path, [settled])
    store_path(tmp_path).write_text(json.dumps(receipt(settled), ensure_ascii=False) + '\n', encoding='utf-8')
    assert run(tmp_path).returncode == 0
    out = report(tmp_path)
    assert out['errors'] == [] and out['warnings'] == [] and len(out['already_settled']) == 1
    assert written_identities(tmp_path) == []


def test_receipt_wins_over_conflicting_copies_and_ignores_its_judgment(tmp_path):
    settled = item()
    sources = setup(tmp_path, [settled])
    path = sources / 'codex.json'
    data = json.loads(path.read_text())
    data['resume']['open_loops'][0]['record_kind'] = 'documents'
    path.write_text(json.dumps(data))
    store_path(tmp_path).write_text(json.dumps(receipt(settled)) + '\n')
    assert run(tmp_path).returncode == 0
    out = report(tmp_path)
    assert out['errors'] == [] and out['ready_for_durable_filing'] and len(out['already_settled']) == 1
    assert out['ignored_decisions'] == [{'identity': record_identity(settled),
                                         'reason': 'identity already settled; judgment not used'}]
    assert written_identities(tmp_path) == []


@pytest.mark.parametrize('settled_types', [('progress', 'decision'), ('progress',)])
def test_copies_of_different_types_settle_only_when_every_type_has_a_receipt(tmp_path, settled_types):
    progress = item()
    sources = setup(tmp_path, [progress])
    path = sources / 'codex.json'
    data = json.loads(path.read_text())
    data['resume']['open_loops'][0]['type'] = 'decision'
    path.write_text(json.dumps(data))
    store_path(tmp_path).write_text(''.join(json.dumps(receipt({**progress, 'type': kind})) + '\n'
                                            for kind in settled_types))
    assert run(tmp_path, 'inspect').returncode == 1
    out = report(tmp_path)
    if len(settled_types) == 2:
        assert out['errors'] == [] and out['unfiled_before_cutoff'] == 0 and out['unique_items'] == 1
        assert sorted(row['type'] for row in out['already_settled']) == ['decision', 'progress']
    else:
        assert out['already_settled'] == [] and out['unfiled_before_cutoff'] == 1
        assert 'conflicting' in str(out['errors'])


def writer_settles(tmp_path, settled_item):
    """The fixture record writer stands in for a carry step that settles an identity mid-run."""
    store_path(tmp_path)
    (tmp_path / 'store.py').rename(tmp_path / 'store_orig.py')
    (tmp_path / 'store.py').write_text('import runpy\nfrom pathlib import Path\n'
        'here = Path(__file__).parent\n'
        'with (here / "ledger/settled-identities.jsonl").open("a") as handle:\n'
        '    handle.write(' + repr(json.dumps(receipt(settled_item)) + '\n') + ')\n'
        'runpy.run_path(str(here / "store_orig.py"), run_name="__main__")\n')


def test_receipt_written_before_a_later_write_prevents_that_write(tmp_path):
    filed, settled_later = item('filed'), item('later')
    setup(tmp_path, [filed, settled_later])
    writer_settles(tmp_path, settled_later)
    assert run(tmp_path).returncode == 0, report(tmp_path)
    out = report(tmp_path)
    assert out['errors'] == [] and out['unfiled_before_cutoff'] == 0
    assert [row['identity']['text'] for row in out['already_settled']] == ['later']
    statuses = {row['identity']['text']: row for row in out['items']}
    assert statuses['filed']['status'] == 'filed'
    assert statuses['later']['status'] == 'already_settled' and 'error' not in statuses['later']
    # Only the first identity reached the writer (written to the original writer's store).
    stored = json.loads((tmp_path / 'store_orig.json').read_text())
    assert [row['identity'] for row in stored] == [record_identity(filed)]


def test_unjudged_row_settled_during_run_is_relabelled(tmp_path):
    filed, settled_later = item('filed'), item('later')
    setup(tmp_path, [filed, settled_later])
    decisions = json.loads((tmp_path / 'decisions.json').read_text())
    (tmp_path / 'decisions.json').write_text(json.dumps(decisions[:1]))
    writer_settles(tmp_path, settled_later)
    assert run(tmp_path).returncode == 0, report(tmp_path)
    later = next(row for row in report(tmp_path)['items'] if row['identity']['text'] == 'later')
    assert later['status'] == 'already_settled' and 'error' not in later


def test_attempted_write_keeps_its_failure_when_settled_meanwhile(tmp_path):
    failing = item()
    setup(tmp_path, [failing], 'failed')
    writer_settles(tmp_path, failing)
    run(tmp_path)
    out = report(tmp_path)
    (row,) = out['items']
    assert row['status'] == 'failed' and row['error']
    assert row['recount_note'] == 'identity now settled by a receipt; this run attempted a write'
    assert [entry['identity']['text'] for entry in out['already_settled']] == ['change']



def stored(tmp_path):
    path = tmp_path / 'store.json'
    return [row['identity'] for row in json.loads(path.read_text())] if path.exists() else []


def record_identity_of(x):
    return {'session_id': x['session_id'], 'produced_at': x['produced_at'], 'text': x['context']}


@pytest.mark.parametrize('loop', [
    {'context': 'Test module seam', 'disposition': 'file if needed'},
    {'type': '', 'context': 'Empty type', 'disposition': 'file'},
    {'type': None, 'context': 'Null type', 'disposition': 'file'},
], ids=['untyped', 'empty-type', 'null-type'])
def test_untyped_loop_with_context_files_under_its_handoffs_identity_and_reaches_ready(tmp_path, loop):
    setup(tmp_path, [item(), loop])
    assert run(tmp_path).returncode == 0, report(tmp_path)
    out = report(tmp_path)
    assert out['errors'] == [] and out['ready_for_durable_filing']
    assert carrier_identity(loop) in [row['identity'] for row in out['items']]
    assert len(stored(tmp_path)) == 2
    assert run(tmp_path).returncode == 0
    assert len(stored(tmp_path)) == 2


@pytest.mark.parametrize('loop, problem', [
    ({'what': 'Watch the deploy', 'owner': 'agent', 'disposition': 'check after merge'},
     'has no context; it cannot be filed (see #285 for writers, #271 for existing loops)'),
    ({'type': 'commitment', 'context': 'Unknown producer', 'disposition': 'file'},
     'is a typed item without its own session_id and produced_at; the carry step cannot settle it'),
    ({'type': 'commitment', 'context': 'Unknown time', 'disposition': 'file', 'session_id': 'producer'},
     'is a typed item without its own session_id and produced_at; the carry step cannot settle it'),
], ids=['no-context', 'typed-no-session', 'typed-no-time'])
def test_loop_without_a_fileable_identity_is_an_error_and_never_written(tmp_path, loop, problem):
    sources = setup(tmp_path, [item(), loop])
    assert run(tmp_path).returncode == 1
    out = report(tmp_path)
    assert out['errors'] == [str(sources / name) + ': open_loops[1] ' + problem
                             for name in ('claude.json', 'codex.json')]
    assert not out['ready_for_durable_filing']
    assert [row['item']['context'] for row in out['items']] == ['change']
    assert stored(tmp_path) == [record_identity_of(item())]


@pytest.mark.parametrize('drop, problem', [
    ('written_at', 'has no producing time in the item or its handoff; a file time is not an identity'),
    ('subject', 'has no producing session in the item or its handoff; a file name is not an identity'),
])
def test_untyped_loop_never_takes_its_identity_from_the_file(tmp_path, drop, problem):
    sources = setup(tmp_path, [item()])
    old = sources / 'old.json'
    data = {'subject': {'session_id': 'old'}, 'written_at': WRITTEN,
            'resume': {'open_loops': [{'context': 'Legacy note', 'disposition': 'keep'}]}}
    del data[drop]
    old.write_text(json.dumps(data))
    assert run(tmp_path).returncode == 1
    out = report(tmp_path)
    assert out['errors'] == [str(old) + ': open_loops[0] ' + problem]
    assert not out['ready_for_durable_filing']
    assert stored(tmp_path) == [record_identity_of(item())]


def test_file_times_never_change_an_identity_or_the_cutoff_decision(tmp_path):
    loop = {'context': 'Test module seam', 'disposition': 'file if needed'}
    sources = setup(tmp_path, [item(), loop, {**item('later'), 'produced_at': CUTOFF}])
    seen = []
    for stamp in (0, 4102444800):  # 1970 and 2100: both sides of the cutoff
        for path in sources.iterdir():
            os.utime(path, (stamp, stamp))
        assert run(tmp_path, 'inspect').returncode == 1
        out = report(tmp_path)
        assert out['errors'] == []
        seen.append(sorted(json.dumps(row['identity'], sort_keys=True) for row in out['items']))
    assert seen[0] == seen[1] and len(seen[0]) == 2


@pytest.mark.parametrize('written, warned', [
    ('2026-11-16T12:00:00Z', True), (CUTOFF, False), (None, True), (7, True)])
@pytest.mark.parametrize('subject', [{'session_id': 'old'}, None])
def test_null_open_loops_warn_unless_written_after_the_cutoff(tmp_path, written, warned, subject):
    sources = setup(tmp_path, [item()])
    old = sources / 'old.json'
    data = {'schema_version': 2, 'subject': subject, 'resume': {'open_loops': None}}
    if written is not None:
        data['written_at'] = written
    old.write_text(json.dumps(data))
    assert run(tmp_path).returncode == 0
    out = report(tmp_path)
    assert out['errors'] == [] and out['ready_for_durable_filing']
    assert out['warnings'] == ([str(old) + ': resume.open_loops is null; read as no carried items']
                               if warned else [])
    assert str(old) in out['sources']
