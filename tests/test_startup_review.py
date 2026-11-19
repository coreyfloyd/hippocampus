"""Candidate review regressions; all startup and usage inputs are fixture-owned."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from test_slim_harness import helper, SKILL, entry


def setup_request(tmp_path, bodies, minimum=10):
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    subprocess.run(['git', '-C', str(tmp_path), 'checkout', '-qb', 'slim/review'], check=True)
    source = tmp_path / 'rules.md'
    source.write_text(''.join(bodies))
    m = helper()
    order = [dict(tool='codex', session_id=f'fixture-{n}') for n in range(minimum)]
    rows = [dict(path=str(source), section=title, body_start_line=start,
                 body_sha256=hashlib.sha256(body.encode()).hexdigest(),
                 sessions_loaded=minimum, sessions_with_evidence=0,
                 markers=m.usage_markers(body), observations=[dict(**s, loaded=True, matched_markers=[]) for s in order])
            for title, start, body in m.skill_sections(source.read_text())]
    policy = tmp_path / 'policy.json'
    policy.write_text(json.dumps({'startup_budget': {'usage_sessions': minimum}}))
    return m, source, dict(tool='codex', directory=str(tmp_path), config=str(policy), usage=dict(
        minimum_sessions=minimum, window_complete=True, session_order=order,
        sections=rows, unresolved=[]))


def test_report_policy_cannot_weaken_and_missing_evidence_refused(tmp_path):
    m, source, req = setup_request(tmp_path, ['## Deploy\nUse --deploy.\n'], minimum=12)
    req.pop('config')  # A missing request config must never weaken the report.
    row = req['usage']['sections'][0]
    row['observations'] = row['observations'][:10]
    row['sessions_loaded'] = 10
    req['usage']['session_order'] = req['usage']['session_order'][:10]
    journal = tmp_path / 'journal.json'
    assert m.extract(req, journal)['extractions'] == []
    del req['usage']['minimum_sessions']
    with pytest.raises(ValueError, match='minimum_sessions'):
        m.extract(req, journal)
    assert source.read_text() == '## Deploy\nUse --deploy.\n'


@pytest.mark.parametrize('gap', ['window', 'observations', 'duplicate', 'counts', 'unloaded'])
def test_incomplete_or_nonconsecutive_window_never_demotes(gap, tmp_path):
    m, source, req = setup_request(tmp_path, ['## Deploy\nUse --deploy.\n'])
    row = req['usage']['sections'][0]
    if gap == 'window':
        req['usage']['window_complete'] = False
    elif gap == 'observations':
        row.pop('observations')
    elif gap == 'duplicate':
        req['usage']['session_order'][-1] = req['usage']['session_order'][0]
        row['observations'][-1] = row['observations'][0]
    elif gap == 'counts':
        row['sessions_loaded'] = 11
    else:
        row['observations'][5]['loaded'] = False
        row['sessions_loaded'] = 9
    if gap == 'unloaded':
        assert m.extract(req, tmp_path / 'journal.json')['extractions'] == []
    else:
        with pytest.raises(ValueError):
            m.extract(req, tmp_path / 'journal.json')
    assert source.read_text() == '## Deploy\nUse --deploy.\n'
    assert not (tmp_path / 'references').exists()


def test_ten_recent_consecutive_unused_sessions_allow_older_evidence(tmp_path):
    m, source, req = setup_request(tmp_path, ['## Deploy\nUse --deploy.\n'], minimum=11)
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({'startup_budget': {'usage_sessions': 10}}))
    req['config'] = str(config)
    req['usage']['minimum_sessions'] = 10
    row = req['usage']['sections'][0]
    row['observations'][0]['matched_markers'] = ['--deploy']
    row['sessions_with_evidence'] = 1
    result = m.extract(req, tmp_path / 'journal.json')
    assert len(result['extractions']) == 1
    assert result['asks'][0]['usage']['consecutive_sessions_without_evidence'] == 10
    assert result['asks'][0]['usage']['sessions_with_evidence'] == 1


def test_prose_and_preamble_are_retained_on_unobservable_evidence(tmp_path):
    text = 'Use --always safely.\n\n## Boundary\nNever push without permission.\n'
    m, source, req = setup_request(tmp_path, [text])
    result = m.extract(req, tmp_path / 'journal.json')
    assert result['extractions'] == []
    assert source.read_text() == text


@pytest.mark.parametrize('fault', ['ambiguous', 'journal', 'write'])
def test_extraction_failure_preserves_entire_request_and_is_retryable(fault, tmp_path, monkeypatch):
    bodies = ['## One\nUse --one.\n\n', '## Two\nUse --two.\n\n']
    m, source, req = setup_request(tmp_path, bodies)
    original = source.read_text()
    journal = tmp_path / 'journal.json'
    if fault == 'ambiguous':
        # Two report rows for one source span must fail before the first write.
        req['usage']['sections'].append(req['usage']['sections'][-1])
    elif fault == 'journal':
        journal.mkdir()
    else:
        # Fail the source publication once, after staging the references/journal.
        real = m._atomic.atomic_write
        fired = False
        def fail_once(path, content):
            nonlocal fired
            if path == source and not fired:
                fired = True
                raise OSError('fixture source publication failure')
            return real(path, content)
        monkeypatch.setattr(m._atomic, 'atomic_write', fail_once)
    with pytest.raises((ValueError, OSError)):
        m.extract(req, journal)
    assert source.read_text() == original
    assert not list((tmp_path / 'references').glob('*.md'))
    if fault == 'ambiguous':
        req['usage']['sections'].pop()
    if fault == 'journal':
        journal.rmdir()
    assert len(m.extract(req, journal)['extractions']) == 2


@pytest.mark.parametrize('modified', [False, True])
def test_rejection_deletes_only_unchanged_reference(modified, tmp_path):
    m, source, req = setup_request(tmp_path, ['## Deploy\nUse --deploy.\n'])
    journal = tmp_path / 'journal.json'
    result = m.extract(req, journal)
    destination = Path(result['extractions'][0]['destination'])
    if modified:
        destination.write_text('Later independent edits.\n')
    m.revert(journal, 1)
    assert source.read_text() == '## Deploy\nUse --deploy.\n'
    assert destination.exists() is modified
    if modified:
        assert destination.read_text() == 'Later independent edits.\n'
    else:
        assert m.extract(req, tmp_path / 'next-journal.json')['extractions']


def test_reused_journal_returns_only_new_asks_and_preserves_heading_spacing(tmp_path):
    m, source, req = setup_request(tmp_path, ['## One\nUse --one.\n\n', '## Two\nUse --two.\n\n'])
    journal = tmp_path / 'journal.json'
    second = req['usage']['sections'].pop()
    first = m.extract(req, journal)
    # Recompute the surviving section's coordinates after the first pointer.
    title, start, body = m.skill_sections(source.read_text())[-1]
    second.update(body_start_line=start, body_sha256=hashlib.sha256(body.encode()).hexdigest())
    req['usage']['sections'] = [second]
    next_result = m.extract(req, journal)
    assert len(next_result['asks']) == 1
    assert next_result['asks'][0]['id'] != first['asks'][0]['id']
    assert len(json.loads(journal.read_text())) == 2
    assert source.read_text().startswith('## One\nRead `')
    assert '\n\n## Two\nRead `' in source.read_text()


@pytest.mark.parametrize('config', [[], {'startup_budget': []}, {'startup_budget': 'wrong'},
    {'startup_budget': {'directories': {'relative/project': 20}}}])
def test_bad_config_is_clean_cli_error(config, tmp_path):
    cfg = tmp_path / 'config.json'
    cfg.write_text(json.dumps(config))
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps(dict(tool='codex', config=str(cfg), files=[])))
    result = subprocess.run([sys.executable, str(SKILL / 'scripts/harness.py'), 'measure', str(manifest)],
                            capture_output=True, text=True)
    assert result.returncode == 2
    assert 'Traceback' not in result.stderr
    assert result.stdout == ''


@pytest.mark.parametrize('tool', ['claude', 'codex'])
def test_listed_skills_include_attested_name_and_path(tool, tmp_path):
    target = tmp_path / 'SKILL.md'
    target.write_text('---\nname: long-discovery-name\ndescription: abcd\n---\nExcluded body.\n')
    listing = entry(target, 'skill', 'listed')
    listing['listing_path'] = '/fixture/catalog/long-discovery-name/SKILL.md'
    result = helper().measure(dict(tool=tool, files=[listing]))
    expected = 'long-discovery-name\n' + listing['listing_path'] + '\nabcd'
    assert result['startup']['tokens'] == (len(expected.encode()) + 3) // 4


@pytest.mark.parametrize('tool', ['claude', 'codex'])
@pytest.mark.parametrize('interrupted', [False, True])
def test_transcripts_produce_consecutive_window_and_drive_branch_extraction(tool, interrupted, tmp_path):
    m, source, req = setup_request(tmp_path, ['## Deploy\nUse --deploy.\n'])
    fix = Path(__file__).parent / 'fixtures/usage'
    source.write_text((fix / 'SKILL.md').read_text())
    sessions = []
    for index in range(11):
        records = [json.loads(line) for line in (fix / (tool + '.jsonl')).read_text().splitlines()]
        if tool == 'claude':
            for record in records:
                record['sessionId'] = f'fixture-session-{index}'
            if index:
                records[2]['message']['content'][0]['input']['command'] = 'true'
            if interrupted and index == 5:
                records[1]['message']['content'][0]['truncated'] = True
        else:
            records.insert(0, dict(type='session_meta', payload={'id': f'fixture-session-{index}'}))
            if index:
                records[3]['payload']['input'] = 'text(await tools.exec_command({cmd:"true"}));'
            if interrupted and index == 5:
                records[2]['payload']['truncated'] = True
        transcript = tmp_path / f'session-{index}.jsonl'
        transcript.write_text(''.join(json.dumps(r) + '\n' for r in records))
        sessions.append(dict(tool=tool, transcript=str(transcript), skills=[dict(
            path=str(source), recorded_path='/redacted/skills/workflow/SKILL.md')]))
    manifest = dict(sessions=sessions, session_window_complete=True, config=req['config'])
    report = m.usage(manifest)
    title = 'Tracker commands' if tool == 'claude' else 'Repository commands'
    row = next(row for row in report['sections'] if row['section'] == title)
    assert len(row['observations']) == 11
    assert row['consecutive_sessions_without_evidence'] == (5 if interrupted else 10)
    assert report['minimum_sessions'] == 10
    assert report['window_complete'] is True
    report['sections'] = [row]
    req.update(tool=tool, usage=report)
    result = m.extract(req, tmp_path / 'journal.json')
    assert len(result['extractions']) == (0 if interrupted else 1)
    if not interrupted:
        assert result['asks'][0]['usage']['observations'] == row['observations']
    manifest.pop('session_window_complete')
    assert m.usage(manifest)['window_complete'] is False


@pytest.mark.parametrize('independent_edit', [False, True])
def test_second_source_io_failure_rolls_back_or_keeps_complete_recovery(independent_edit, tmp_path, monkeypatch):
    m, first, req = setup_request(tmp_path, ['## One\nUse --one.\n'])
    second = tmp_path / 'second.md'
    second.write_text('## Two\nUse --two.\n')
    other = json.loads(json.dumps(req['usage']['sections'][0]))
    other.update(path=str(second), section='Two', markers=['--two'],
                 body_sha256=hashlib.sha256(second.read_bytes()).hexdigest())
    req['usage']['sections'].append(other)
    before_first = first.read_text()
    before_second = second.read_text()
    original = m._atomic.atomic_write
    fired = False
    def fail_once(path, text):
        nonlocal fired
        if path == second and not fired:
            fired = True
            if independent_edit:
                first.write_text(first.read_text() + '\nIndependent change.\n')
            raise OSError('fixture second source failure')
        return original(path, text)
    monkeypatch.setattr(m._atomic, 'atomic_write', fail_once)
    journal = tmp_path / 'journal.json'
    with pytest.raises((OSError, ValueError)):
        m.extract(req, journal)
    assert second.read_text() == before_second
    if independent_edit:
        assert 'Independent change.' in first.read_text()
        records = json.loads(journal.read_text())
        assert len(records) == 2
        # A source preserved after a concurrent edit must retain its reference.
        assert Path(records[0]['destination']).read_text() == before_first
        assert all(row['ask']['approval_required'] for row in records)
    else:
        assert first.read_text() == before_first
        assert not journal.exists()
        assert not list((tmp_path / 'references').glob('*.md'))


def test_conflicting_duplicate_section_evidence_is_refused_before_any_edit(tmp_path):
    m, source, req = setup_request(tmp_path, ['## Deploy\nUse --deploy.\n'])
    duplicate = json.loads(json.dumps(req['usage']['sections'][0]))
    duplicate['observations'][-1]['matched_markers'] = ['--deploy']
    duplicate['sessions_with_evidence'] = 1
    req['usage']['sections'].append(duplicate)
    with pytest.raises(ValueError, match='duplicate'):
        m.extract(req, tmp_path / 'journal.json')
    assert source.read_text() == '## Deploy\nUse --deploy.\n'
    assert not (tmp_path / 'journal.json').exists()
    assert not (tmp_path / 'references').exists()


@pytest.mark.parametrize('tool', ['claude', 'codex'])
def test_extraction_writer_uses_configured_owner_and_requires_saved_owner_receipt(tool, tmp_path, monkeypatch):
    m, source, req = setup_request(tmp_path, ['## Deploy\nUse --deploy.\n'])
    profile = tmp_path / 'checklist.json'
    profile.write_text(json.dumps({'name': 'fixture', 'ask': {'command': '/fixture-writer', 'owner_agent': 'fixture-agent'}}))
    monkeypatch.setenv('CHECKLIST_USER_PROFILE', str(profile))
    req.update(tool=tool, session_id='original-producer')
    journal = tmp_path / 'journal.json'
    output = m.extract(req, journal)
    ask = output['asks'][0]
    assert ask['owner_agent'] == 'fixture-agent'
    assert ask['session_id'] == 'original-producer'
    assert ask['provider'] == tool
    assert ask['owner'] == 'chief' and ask['escalate_to'] == 'user'
    assert json.loads(journal.read_text())[0]['ask'] == ask
    original_id = ask['id']
    before = journal.read_bytes()
    for receipt in ['opaque', {'owner_agent': 'user'}]:
        with pytest.raises(ValueError, match='owner_agent'):
            m.ask_delivered(journal, 1, receipt)
        assert journal.read_bytes() == before
    # The fixture writer saves the payload and returns ownership read back from it.
    store = tmp_path / 'writer.json'
    store.write_text(json.dumps(ask))
    receipt = {'owner_agent': json.loads(store.read_text())['owner_agent'], 'destination': str(store)}
    receipt_path = tmp_path / 'receipt.json'
    receipt_path.write_text(json.dumps(receipt))
    delivered = subprocess.run([sys.executable, str(SKILL / 'scripts/harness.py'), 'ask-delivered',
                                str(journal), '1', str(receipt_path)], capture_output=True, text=True)
    assert delivered.returncode == 0, delivered.stderr
    assert json.loads(delivered.stdout)['receipt'] == receipt
    record = json.loads(journal.read_text())[0]
    assert record['ask']['id'] == original_id
    assert record['ask']['session_id'] == 'original-producer'
    assert record['ask_receipt'] == receipt
    assert output['merge_allowed'] is False


def test_extraction_receipt_retry_rebinds_owner_without_changing_producer(tmp_path, monkeypatch):
    m, source, req = setup_request(tmp_path, ['## Deploy\nUse --deploy.\n'])
    profile = tmp_path / 'checklist.json'
    profile.write_text(json.dumps({'name': 'fixture', 'ask': {'command': '/writer', 'owner_agent': 'first-agent'}}))
    monkeypatch.setenv('CHECKLIST_USER_PROFILE', str(profile))
    req['session_id'] = 'original-producer'
    journal = tmp_path / 'journal.json'
    original = m.extract(req, journal)['asks'][0]
    profile.write_text(json.dumps({'name': 'fixture', 'ask': {'command': '/writer', 'owner_agent': 'next-agent'}}))
    before = journal.read_bytes()
    pending = m.pending_asks(journal)['asks'][0]
    assert pending['number'] == 1
    assert pending['ask']['owner_agent'] == 'next-agent'
    assert pending['ask']['id'] == original['id']
    assert pending['ask']['session_id'] == 'original-producer'
    assert journal.read_bytes() == before
    with pytest.raises(ValueError, match='owner_agent'):
        m.ask_delivered(journal, 1, {'owner_agent': 'first-agent'})
    assert journal.read_bytes() == before
    m.ask_delivered(journal, 1, {'owner_agent': 'next-agent'})
    saved = json.loads(journal.read_text())[0]['ask']
    assert saved['owner_agent'] == 'next-agent'
    assert saved['id'] == original['id']
    assert saved['session_id'] == original['session_id']
    assert m.pending_asks(journal)['asks'] == []
