"""Catch-up uses only supplied handoff stores and fixture record writers."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from test_record_writes import item, store
import test_retained_session_items as carry

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


def isolated_env(tmp_path, ledger=True):
    env = {**os.environ, 'HOME': str(tmp_path / 'empty-home'), 'PYTHONDONTWRITEBYTECODE': '1',
           'XDG_CONFIG_HOME': str(tmp_path / 'config'), 'HANDOFF_STATE_DIR': str(tmp_path / 'state'),
           'HANDOFF_LEDGER_DIR': str(tmp_path / 'ledger')}
    if not ledger:
        del env['HANDOFF_LEDGER_DIR']
    return env


def run(tmp_path, command='run', ledger=True, cutoff=CUTOFF):
    return subprocess.run([sys.executable, str(CLI), command, '--node', 'fixture-node',
        '--store', str(tmp_path / 'sources'), '--cutoff', cutoff,
        '--user-profile', str(tmp_path / 'profile.json'), '--decisions', str(tmp_path / 'decisions.json'),
        '--report', str(tmp_path / 'report.json')], text=True, capture_output=True,
        env=isolated_env(tmp_path, ledger))


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
    ({'type': 'commitment', 'context': 'Unknown producer', 'disposition': 'file'},
     'is a typed item without its own session_id and produced_at; the carry step cannot settle it'),
    ({'type': 'commitment', 'context': 'Unknown time', 'disposition': 'file', 'session_id': 'producer'},
     'is a typed item without its own session_id and produced_at; the carry step cannot settle it'),
], ids=['typed-no-session', 'typed-no-time'])
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


def judge(tmp_path, *rows):
    (tmp_path / 'decisions.json').write_text(json.dumps(list(rows)))


def settled_store(tmp_path):
    return carry.store(tmp_path)


REASON = 'Superseded by the migration ticket.'


@pytest.mark.parametrize('tool', carry.TOOLS)
@pytest.mark.parametrize('kind', ['progress', 'open_loop', 'artifact'])
def test_a_reasoned_drop_writes_one_receipt_and_no_carry_step_restores_it(tmp_path, tool, kind):
    if kind == 'artifact':
        result = carry.command(tmp_path, 'A', 'scripts/lib/handoff.py', 'ledger-artifact', '--cwd', tmp_path,
                               '--session-id', 'A', '--location', 'https://example.com/a',
                               '--disposition', 'remove', tool=tool)
        assert result.returncode == 0, result.stderr
        written = carry.checkpoint(tmp_path, 'A', tool)
    else:
        written = carry.checkpoint(tmp_path, 'A', tool, items=[{'type': kind, 'context': 'Ran the migration.',
            'session_id': 'A', 'produced_at': '2026-11-05T12:00:00Z', 'disposition': 'carry'}])
    [loop] = [x for x in written['resume']['open_loops'] if x.get('type') == kind]
    sources = tmp_path / 'sources'
    sources.mkdir()
    stale = (tmp_path / 'A.json').read_text()
    (sources / 'A.json').write_text(stale)
    (tmp_path / 'stale.json').write_text(stale)
    (tmp_path / 'profile.json').write_text(json.dumps({'name': 'fixture'}))
    identity = {'session_id': 'A', 'produced_at': loop['produced_at'], 'text': loop['context']}
    judge(tmp_path, {'identity': identity, 'rule': 'R6', 'reason': REASON})
    result = run(tmp_path, cutoff='2099-01-01T00:00:00Z')
    assert result.returncode == 0, result.stderr
    out = report(tmp_path)
    assert out['ready_for_durable_filing'] and out['unfiled_before_cutoff'] == 0
    [row] = out['items']
    # The report keeps what was dropped, why, and where it came from.
    assert (row['status'], row['reason'], row['item'], row['sources']) == ('dropped', REASON, loop,
                                                                          [str(sources / 'A.json')])
    [receipt] = settled_store(tmp_path)
    assert receipt == {**row['receipt'], 'destination': None}
    assert receipt['identity'] == {**identity, 'type': kind}
    assert (receipt['disposition'], receipt['reason'], receipt['settled_by']) == (
        'dropped', REASON, 'filing-catchup:fixture-node')
    # Neither a checkpoint re-supplying the stale handoff's loop nor a pickup of it restores the item.
    again = carry.checkpoint(tmp_path, 'A', tool, resume={'open_loops': [loop]})
    assert [x for x in again['resume']['open_loops'] if x.get('type') == kind] == []
    carry.pickup(tmp_path, 'B', 'stale', tool)
    resumed = carry.checkpoint(tmp_path, 'B', tool)
    assert [x for x in resumed['resume']['open_loops'] if x.get('type') == kind] == []
    # A rerun reports the identity as settled and writes nothing more.
    assert run(tmp_path, cutoff='2099-01-01T00:00:00Z').returncode == 0
    assert report(tmp_path)['already_settled'][0]['disposition'] == 'dropped'
    assert len(settled_store(tmp_path)) == 1


@pytest.mark.parametrize('kind', ['knowledge', 'lesson', 'decision', 'commitment', None])
def test_a_drop_of_a_filed_type_is_refused_and_writes_nothing(tmp_path, kind):
    loop = {**item(), 'type': kind} if kind else {k: v for k, v in item().items() if k != 'type'}
    setup(tmp_path, [loop])
    judge(tmp_path, {'identity': carrier_identity(loop), 'rule': 'R1', 'reason': REASON})
    assert run(tmp_path).returncode == 1
    out = report(tmp_path)
    [row] = out['items']
    assert row['status'] == 'failed' and 'filed, never dropped' in row['error']
    assert out['unfiled_before_cutoff'] == 1
    assert settled_store(tmp_path) == [] and not (tmp_path / 'store.json').exists()


@pytest.mark.parametrize('reason', ['', '   ', None])
def test_a_drop_without_a_reason_is_refused(tmp_path, reason):
    setup(tmp_path, [item()])
    judge(tmp_path, {'identity': carrier_identity(item()), 'rule': 'R6',
                     **({} if reason is None else {'reason': reason})})
    assert run(tmp_path).returncode == 1
    [row] = report(tmp_path)['items']
    assert row['status'] == 'failed' and 'reason' in row['error']
    assert settled_store(tmp_path) == []


def recording_store(tmp_path):
    """The fixture ticket store, also keeping the item each write received."""
    script = tmp_path / 'store.py'
    script.write_text(script.read_text().replace("receipt = {'identity': r['identity'], ",
                                                 "receipt = {'item': r['item'], 'identity': r['identity'], "))


def conflicting(tmp_path, newer_written_at, older_written_at=WRITTEN):
    older = item()
    newer = {**item(), 'anchor': {'ticket': 'example/repo#2'}, 'choices': ['approve the newer text', 'defer']}
    sources = setup(tmp_path, [{**older, 'anchor': {'ticket': 'example/repo#1'}}])
    for name, loop, written in (('claude.json', {**older, 'anchor': {'ticket': 'example/repo#1'}}, older_written_at),
                                ('codex.json', newer, newer_written_at)):
        data = json.loads((sources / name).read_text())
        data['resume']['open_loops'] = [loop]
        if written is None:
            del data['written_at']
        else:
            data['written_at'] = written
        (sources / name).write_text(json.dumps(data))
    recording_store(tmp_path)
    return sources, newer


def test_conflicting_copies_inventory_and_file_as_the_newest_handoffs_copy(tmp_path):
    sources, newer = conflicting(tmp_path, '2026-11-18T13:00:00Z')
    assert run(tmp_path, 'inspect').returncode == 1
    inspected = report(tmp_path)
    assert inspected['errors'] == [] and inspected['items'][0]['item'] == newer
    assert run(tmp_path).returncode == 0
    out = report(tmp_path)
    assert out['errors'] == [] and out['ready_for_durable_filing']
    [row] = out['items']
    assert row['status'] == 'filed' and row['item'] == newer
    assert row['superseded_copies'] == [{'source': str(sources / 'claude.json'), 'written_at': WRITTEN,
        'item': {**item(), 'anchor': {'ticket': 'example/repo#1'}}, 'difference': 'differs in anchor, choices'}]
    assert [write['item'] for write in json.loads((tmp_path / 'store.json').read_text())] == [newer]


def test_order_comes_from_written_at_never_from_file_times(tmp_path):
    sources, newer = conflicting(tmp_path, '2026-11-18T13:00:00Z')
    os.utime(sources / 'codex.json', (0, 0))
    assert run(tmp_path, 'inspect').returncode == 1
    assert report(tmp_path)['errors'] == [] and report(tmp_path)['items'][0]['item'] == newer


@pytest.mark.parametrize('newer_written_at,older_written_at,problem', [
    (WRITTEN, WRITTEN, 'written at the same time'),
    (None, WRITTEN, 'no valid written_at'),
])
def test_conflicting_copies_that_cannot_be_ordered_stay_an_inventory_error(tmp_path, newer_written_at,
                                                                          older_written_at, problem):
    conflicting(tmp_path, newer_written_at, older_written_at)
    assert run(tmp_path).returncode == 1
    out = report(tmp_path)
    assert problem in str(out['errors']) and out['items'][0]['status'] == 'pending'
    assert not (tmp_path / 'store.json').exists()


def commitment(**extra):
    return {**item('Send the migration notes'), 'type': 'commitment', **extra}


def test_an_unanchored_commitment_is_never_made_a_new_ticket(tmp_path):
    loop = commitment()
    setup(tmp_path, [loop])
    judge(tmp_path, {'identity': carrier_identity(loop), 'rule': 'R5', 'read_status': 'ok',
                     'priority': 'P2', 'priority_reason': 'Follow-up work.'})
    assert run(tmp_path).returncode == 1
    out = report(tmp_path)
    [row] = out['items']
    assert row['status'] == 'pending' and 'never creates a ticket' in row['reason']
    assert out['unfiled_before_cutoff'] == 1 and not (tmp_path / 'store.json').exists()


def test_an_anchored_commitment_files_as_a_ticket_comment(tmp_path):
    loop = commitment(anchor={'ticket': 'example/repo#1'})
    setup(tmp_path, [loop])
    assert run(tmp_path).returncode == 0
    [row] = report(tmp_path)['items']
    assert row['status'] == 'filed' and row['destination'].startswith('tickets:')


def copies_in(tmp_path, *handoffs):
    """Rewrite the ``setup`` handoffs: each is (name, written_at, loops)."""
    for name, written, loops in handoffs:
        path = tmp_path / 'sources' / name
        data = json.loads(path.read_text())
        data.update(written_at=written)
        data['resume']['open_loops'] = loops
        path.write_text(json.dumps(data))


NEWER = '2026-11-18T13:00:00Z'


@pytest.mark.parametrize('settled', [(), ('progress',), ('progress', 'commitment')])
def test_a_newer_copy_of_another_type_never_supersedes_a_filed_type(tmp_path, settled):
    older, newer = {**item(), 'type': 'commitment'}, item()
    setup(tmp_path, [older])
    copies_in(tmp_path, ('claude.json', WRITTEN, [older]), ('codex.json', NEWER, [newer]))
    judge(tmp_path, {'identity': carrier_identity(newer), 'rule': 'R6', 'reason': REASON})
    store_path(tmp_path).write_text(''.join(json.dumps(receipt({**newer, 'type': kind})) + '\n' for kind in settled))
    assert run(tmp_path).returncode == (0 if len(settled) == 2 else 1)
    out = report(tmp_path)
    if len(settled) == 2:
        # Each copy's own receipt settles it; nothing was superseded or dropped.
        assert out['errors'] == [] and sorted(row['type'] for row in out['already_settled']) == list(sorted(settled))
    else:
        assert 'copies differ in type (commitment, then progress)' in str(out['errors'])
        assert out['items'][0]['status'] == 'pending' and 'superseded_copies' not in out['items'][0]
        assert len(settled_store(tmp_path)) == len(settled)


def test_supersession_is_by_copy_and_every_copy_still_needs_its_receipt(tmp_path):
    old = {**item(), 'choices': ['approve the old text', 'defer']}
    new = {**item(), 'choices': ['approve the new text', 'defer']}
    setup(tmp_path, [old])
    # The older handoff lists the identity twice: once as the newer copy says, once superseded.
    copies_in(tmp_path, ('claude.json', WRITTEN, [new, old]), ('codex.json', NEWER, [new]))
    assert run(tmp_path, 'inspect').returncode == 1
    [row] = report(tmp_path)['items']
    assert report(tmp_path)['errors'] == [] and row['item'] == new
    assert [(copy['source'], copy['item']) for copy in row['superseded_copies']] == [
        (str(tmp_path / 'sources/claude.json'), old)]
    store_path(tmp_path).write_text(json.dumps(receipt(new)) + '\n')
    assert run(tmp_path, 'inspect').returncode == 1
    out = report(tmp_path)
    assert out['items'] == [] and [row['type'] for row in out['already_settled']] == ['progress']


def drop_directly(tmp_path, monkeypatch, decision):
    import checklist
    import filing_catchup
    monkeypatch.setenv('HANDOFF_LEDGER_DIR', str(tmp_path / 'ledger'))
    (tmp_path / 'profile.json').write_text(json.dumps({'name': 'fixture'}))
    profile = checklist.load_profile(tmp_path / 'profile.json')
    source = {'item': item(disposition='carry'), 'subject': {'session_id': 'carrier'}}
    return filing_catchup.drop_item(source, decision, checklist.compose([profile]), checklist.ask_binding(profile),
                                    tmp_path / 'sources', 'fixture-node')


def test_a_drop_counts_only_when_the_store_settles_it_as_that_drop(tmp_path, monkeypatch):
    decision = {'rule': 'R6', 'reason': REASON}
    # Another writer settled the identity first, after catch-up's re-read.
    store_path(tmp_path).write_text(json.dumps(receipt(item(disposition='carry'))) + '\n')
    with pytest.raises(ValueError, match='another receipt .disposition filed. settled this identity first'):
        drop_directly(tmp_path, monkeypatch, decision)
    assert len(settled_store(tmp_path)) == 1
    # A retry of the same drop finds its own receipt.
    store_path(tmp_path).unlink()
    first = drop_directly(tmp_path, monkeypatch, decision)
    assert drop_directly(tmp_path, monkeypatch, decision)['receipt'] == first['receipt']
    assert len(settled_store(tmp_path)) == 1


def test_a_drop_passes_the_wraps_checks_for_its_rule(tmp_path):
    setup(tmp_path, [item()])
    judge(tmp_path, {'identity': carrier_identity(item()), 'rule': 'R1', 'reason': REASON})
    assert run(tmp_path).returncode == 1
    [row] = report(tmp_path)['items']
    assert row['status'] == 'read failed' and settled_store(tmp_path) == []


@pytest.mark.parametrize('anchor,rule,refusal', [
    ({'ticket': '   '}, 'R5', 'stays unfiled'),
    ({'ticket': {}}, 'R5', 'stays unfiled'),
    ({'ticket': '   '}, 'R2', 'stays unfiled'),
    ({'ticket': 'example/repo#1'}, 'R5', 'only as anchored R2 comments on their ticket, never R5'),
])
def test_a_commitment_files_only_as_a_comment_on_its_ticket(tmp_path, anchor, rule, refusal):
    loop = commitment(anchor=anchor)
    setup(tmp_path, [loop])
    judge(tmp_path, {'identity': carrier_identity(loop), 'rule': rule, 'read_status': 'ok',
                     'priority': 'P2', 'priority_reason': 'Follow-up work.'})
    assert run(tmp_path).returncode == 1
    [row] = report(tmp_path)['items']
    assert refusal in (row.get('reason') or '') + (row.get('error') or '')
    assert row['status'] in ('pending', 'failed') and not (tmp_path / 'store.json').exists()


def test_a_dropped_item_changed_before_the_recount_is_reported(tmp_path):
    dropped, filed = item('dropped', disposition='carry'), item('filed')
    sources = setup(tmp_path, [dropped, filed])
    judge(tmp_path, {'identity': carrier_identity(dropped), 'rule': 'R6', 'reason': REASON},
          {'identity': carrier_identity(filed), 'rule': 'R2', 'read_status': 'ok'})
    # The second item's writer stands in for a concurrent checkpoint rewriting the first item.
    script = tmp_path / 'store.py'
    change = ''.join(f"d = json.loads(Path({str(p)!r}).read_text()); d['resume']['open_loops'][0]['detail'] = 'new'; "
                     f"Path({str(p)!r}).write_text(json.dumps(d)); " for p in sorted(sources.iterdir()))
    script.write_text(script.read_text().replace('data.append(receipt);', change + 'data.append(receipt);'))
    assert run(tmp_path).returncode == 1
    out = report(tmp_path)
    rows = {row['identity']['text']: row for row in out['items']}
    assert rows['dropped']['status'] == 'dropped' and 'content changed' in rows['dropped']['recount_error']
    assert rows['filed']['status'] == 'filed' and 'recount_error' not in rows['filed']
    assert out['unfiled_before_cutoff'] == 1 and not out['ready_for_durable_filing']
    # The report agrees: the identity is not also listed as settled.
    assert [row['identity']['text'] for row in out['already_settled']] == []


@pytest.mark.parametrize('same_handoff', [True, False])
def test_artifacts_sharing_an_identity_are_never_dropped(tmp_path, same_handoff):
    first = {**item('Published artifact'), 'type': 'artifact', 'disposition': 'remove', 'location': 'https://example.com/a'}
    second = {**first, 'location': 'https://example.com/b'}
    setup(tmp_path, [first])
    if same_handoff:
        copies_in(tmp_path, ('claude.json', WRITTEN, [first, second]), ('codex.json', WRITTEN, [first]))
    else:
        copies_in(tmp_path, ('claude.json', WRITTEN, [first]), ('codex.json', NEWER, [second]))
    judge(tmp_path, {'identity': carrier_identity(first), 'rule': 'R6', 'reason': REASON})
    assert run(tmp_path).returncode == 1
    out = report(tmp_path)
    assert 'artifacts of one session and produced_at have different locations' in str(out['errors'])
    assert out['items'][0]['status'] == 'pending' and settled_store(tmp_path) == []


@pytest.mark.parametrize('anchor', [None, {'ticket': 'example/repo#1'}])
@pytest.mark.parametrize('rule,extra', [
    ('R3', {'choices': ['approve', 'defer']}),
    ('R7', {}),
    ('R2', {'record_kind': 'projects', 'session_summary': 'Worked.'}),
    ('R5', {}),
    ('R2', {'scheduled': True}),
])
def test_a_commitment_never_files_except_as_an_anchored_ticket_comment(tmp_path, anchor, rule, extra):
    scheduled = extra.pop('scheduled', False)
    loop = commitment(**({'anchor': anchor} if anchor else {}), **({'time': '09:00'} if scheduled else {}))
    setup(tmp_path, [loop])
    profile = json.loads((tmp_path / 'profile.json').read_text())
    for kind in ('projects', 'documents', 'scheduled_jobs'):
        profile['record_writes'][kind] = profile['record_writes']['tickets']
    (tmp_path / 'profile.json').write_text(json.dumps(profile))
    judge(tmp_path, {'identity': carrier_identity(loop), 'rule': rule, 'read_status': 'ok',
                     'priority': 'P2', 'priority_reason': 'Follow-up work.', **extra})
    if anchor and rule == 'R2' and not scheduled:
        # The one allowed filing: an R2 comment through tickets on the anchor.
        assert run(tmp_path).returncode == 0
        assert report(tmp_path)['items'][0]['destination'].startswith('tickets:')
        return
    assert run(tmp_path).returncode == 1
    [row] = report(tmp_path)['items']
    expected = 'only as anchored R2 comments' if anchor else 'without a ticket anchor stays unfiled'
    assert expected in (row.get('reason') or '') + (row.get('error') or '')
    assert not (tmp_path / 'store.json').exists()


@pytest.mark.parametrize('malformed', ['older', 'newest'])
def test_a_malformed_anchor_is_a_conflict_never_superseded_or_filed(tmp_path, malformed):
    bad, good = {**item(), 'anchor': 'T-1'}, {**item(), 'anchor': {'ticket': 'example/repo#2'}}
    setup(tmp_path, [good])
    older, newest = (bad, good) if malformed == 'older' else (good, bad)
    copies_in(tmp_path, ('claude.json', WRITTEN, [older]), ('codex.json', NEWER, [newest]))
    assert run(tmp_path).returncode == 1
    out = report(tmp_path)
    assert 'anchor that is not an object' in str(out['errors'])
    assert 'superseded_copies' not in out['items'][0] and not (tmp_path / 'store.json').exists()


def test_each_older_copy_is_compared_with_the_newest_copy_alone(tmp_path):
    newest = item()
    first, second = ({**item(), 'anchor': {'ticket': 'example/repo#' + n}} for n in ('1', '2'))
    setup(tmp_path, [newest])
    copies_in(tmp_path, ('claude.json', WRITTEN, [first, second]), ('codex.json', NEWER, [newest]))
    recording_store(tmp_path)
    assert run(tmp_path).returncode == 0
    [row] = report(tmp_path)['items']
    # The newest copy's anchor (none) is filed; both older anchors are listed, neither merged in.
    assert row['item'] == newest
    assert [(copy['item'], copy['difference']) for copy in row['superseded_copies']] == [
        (first, 'differs in anchor'), (second, 'differs in anchor')]
    assert [write['item'] for write in json.loads((tmp_path / 'store.json').read_text())] == [newest]


EMPTY = {'what': 'Watch the deploy', 'owner': 'agent', 'disposition': 'check after merge'}


def drop_receipt(identity, disposition='dropped'):
    return {'identity': identity, 'disposition': disposition, 'reason': REASON, 'destination': None,
            'settled_at': '2026-11-20T12:00:00Z', 'settled_by': 'maintainer'}


def settle_identity(tmp_path, *receipts):
    """Record receipts through the carry step's own ``settle-identity`` command."""
    path = tmp_path / 'receipts.jsonl'
    path.write_text(''.join(json.dumps(row) + '\n' for row in receipts))
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/lib/handoff.py'), 'settle-identity',
                             '--receipts', str(path)], text=True, capture_output=True, env=isolated_env(tmp_path))
    return result.returncode, json.loads(result.stdout)


def receipt_identities(tmp_path):
    """The receipt identity inspect reports for each unfiled row, by its text."""
    assert run(tmp_path, 'inspect').returncode == 1
    return {row['identity']['text']: row.get('receipt_identity') for row in report(tmp_path)['items']}


@pytest.mark.parametrize('tool', carry.TOOLS)
def test_a_dropped_receipt_settles_an_untyped_loop_and_no_carry_step_restores_it(tmp_path, tool):
    loop = {'context': 'Legacy note', 'disposition': 'keep', 'session_id': 'A',
            'produced_at': '2026-11-05T12:00:00Z'}
    written = carry.checkpoint(tmp_path, 'A', tool, resume={'open_loops': [loop]})
    assert loop in written['resume']['open_loops']
    (tmp_path / 'sources').mkdir()
    stale = (tmp_path / 'A.json').read_text()
    (tmp_path / 'sources/A.json').write_text(stale)
    (tmp_path / 'stale.json').write_text(stale)
    (tmp_path / 'profile.json').write_text(json.dumps({'name': 'fixture'}))
    judge(tmp_path)
    identity = receipt_identities(tmp_path)['Legacy note']
    assert identity == {'session_id': 'A', 'produced_at': loop['produced_at'], 'type': 'untyped_loop',
                        'text': 'Legacy note'}
    assert settle_identity(tmp_path, drop_receipt(identity)) == (0, {'written': 1, 'skipped': 0, 'invalid': []})
    assert run(tmp_path, 'inspect').returncode == 1
    out = report(tmp_path)
    assert out['items'] == [] and out['unfiled_before_cutoff'] == 0 and out['errors'] == []
    assert [(row['type'], row['disposition']) for row in out['already_settled']] == [('untyped_loop', 'dropped')]
    # Neither a checkpoint re-supplying the stale handoff's loop nor a pickup of it restores the loop.
    again = carry.checkpoint(tmp_path, 'A', tool, resume={'open_loops': [loop]})
    assert loop not in again['resume']['open_loops']
    carry.pickup(tmp_path, 'B', 'stale', tool)
    resumed = carry.checkpoint(tmp_path, 'B', tool)
    assert loop not in resumed['resume']['open_loops']


def test_an_empty_loop_is_named_by_its_handoff_and_position_and_a_drop_settles_it(tmp_path):
    sources = setup(tmp_path, [item(), EMPTY, {'owner': 'agent'}])
    judge(tmp_path, {'identity': carrier_identity(item()), 'rule': 'R2', 'read_status': 'ok'})
    seen = []
    for stamp in (0, 4102444800):  # File times never name an empty loop.
        for path in sources.iterdir():
            os.utime(path, (stamp, stamp))
        identities = receipt_identities(tmp_path)
        assert report(tmp_path)['errors'] == []
        seen.append(identities)
    assert seen[0] == seen[1]
    empty = [seen[0]['open_loops[' + str(index) + ']'] for index in (1, 2)]
    assert empty == [{'session_id': 'carrier', 'produced_at': WRITTEN, 'type': 'empty_loop',
                      'text': 'open_loops[' + str(index) + ']'} for index in (1, 2)]
    assert settle_identity(tmp_path, *map(drop_receipt, empty))[0] == 0
    assert run(tmp_path).returncode == 0
    out = report(tmp_path)
    assert out['ready_for_durable_filing'] and out['errors'] == []
    assert [row['identity']['text'] for row in out['items']] == ['change']
    assert sorted(row['identity']['text'] for row in out['already_settled']) == ['open_loops[1]', 'open_loops[2]']
    assert stored(tmp_path) == [record_identity_of(item())]
    # A rerun no longer reports either empty loop.
    assert list(receipt_identities(tmp_path)) == ['change']


@pytest.mark.parametrize('loop', [{'context': 'Legacy note', 'disposition': 'keep'}, EMPTY], ids=['untyped', 'empty'])
@pytest.mark.parametrize('disposition', ['filed', 'done', 'captured'])
def test_only_a_dropped_receipt_settles_an_untyped_or_empty_loop(tmp_path, loop, disposition):
    setup(tmp_path, [loop])
    [identity] = receipt_identities(tmp_path).values()
    code, summary = settle_identity(tmp_path, drop_receipt(identity, disposition))
    assert code == 1 and summary['written'] == 0
    assert summary['invalid'] == [{'line': 1, 'error': 'an untyped or empty open loop is never filed; '
                                                         'only disposition dropped settles it'}]
    assert settled_store(tmp_path) == []
    # A row written to the store by hand settles nothing either.
    store_path(tmp_path).write_text(json.dumps(drop_receipt(identity, disposition)) + '\n')
    assert run(tmp_path, 'inspect').returncode == 1
    out = report(tmp_path)
    assert [row['receipt_identity'] for row in out['items']] == [identity] and out['already_settled'] == []


def test_each_drop_keeps_its_reason_in_the_receipt_and_the_report(tmp_path):
    loop = {'context': 'Legacy note', 'disposition': 'keep'}
    setup(tmp_path, [loop, EMPTY])
    identities = list(receipt_identities(tmp_path).values())
    assert settle_identity(tmp_path, *map(drop_receipt, identities))[0] == 0
    assert [(row['identity'], row['reason']) for row in settled_store(tmp_path)] == [
        (identity, REASON) for identity in identities]
    assert run(tmp_path).returncode == 0
    rows = report(tmp_path)['already_settled']
    assert sorted(rows, key=lambda row: row['type']) == [
        {'identity': {key: identity[key] for key in ('session_id', 'produced_at', 'text')}, 'type': identity['type'],
         'disposition': 'dropped', 'reason': REASON, 'settled_at': '2026-11-20T12:00:00Z'}
        for identity in sorted(identities, key=lambda identity: identity['type'])]


@pytest.mark.parametrize('drop', ['written_at', 'subject'])
def test_an_empty_loop_without_its_handoffs_session_or_time_stays_a_loop_error(tmp_path, drop):
    sources = setup(tmp_path, [item()])
    old = sources / 'old.json'
    data = {'subject': {'session_id': 'old'}, 'written_at': WRITTEN, 'resume': {'open_loops': [EMPTY]}}
    del data[drop]
    old.write_text(json.dumps(data))
    assert run(tmp_path).returncode == 1
    out = report(tmp_path)
    assert out['errors'] == [str(old) + ': open_loops[0] has no context, and its handoff has no session_id or '
                             'valid written_at to name it by position; a file name or time is not an identity']
    assert not out['ready_for_durable_filing']


@pytest.mark.parametrize('rule', ['R2', 'R6'])
def test_a_run_judgment_never_files_or_drops_an_empty_loop(tmp_path, rule):
    setup(tmp_path, [EMPTY])
    [identity] = receipt_identities(tmp_path).values()
    judge(tmp_path, {'identity': {key: identity[key] for key in ('session_id', 'produced_at', 'text')},
                     'rule': rule, 'reason': REASON, 'read_status': 'ok'})
    assert run(tmp_path).returncode == 1
    [row] = report(tmp_path)['items']
    assert row['status'] == 'failed' and 'settle-identity' in row['error']
    assert settled_store(tmp_path) == [] and stored(tmp_path) == []
