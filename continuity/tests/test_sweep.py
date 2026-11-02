"""Sweep command contracts; every store and profile is isolated from the user."""
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / 'scripts/lib/sweep.py'
FIXTURE = ROOT / 'tests/fixtures/sweep-handoff.json'


def readable_rows(text, row):
    """Find text rows carrying every scalar in a structured entry."""
    def values(value):
        if isinstance(value, dict):
            return [leaf for child in value.values() for leaf in values(child)]
        if isinstance(value, list):
            return [leaf for child in value for leaf in values(child)]
        return [] if value is None else [str(value).lower() if isinstance(value, bool) else ' '.join(str(value).splitlines())]

    body = text.split('```json\n', 1)[0]
    assert json.dumps(row, ensure_ascii=False, sort_keys=True) not in body
    return [line for line in body.splitlines() if line.startswith('- ')
            and all(value in line for value in values(row))]


def assert_readable_report(text, data):
    assert text.count('```json\n') == 1
    payload = text.split('```json\n', 1)[1]
    expected = json.dumps(data, indent=2, **({'ensure_ascii': False}
                          if data['mode'] in ('act', 'watch-only') else {}))
    assert payload == expected + '\n```\n'
    assert json.loads(payload.rsplit('\n```', 1)[0]) == data
    if 'directories' in data:
        for section in data['directories'].values():
            for rows in section.values():
                for row in rows:
                    matches = readable_rows(text, row)
                    assert matches, row
                    if row.get('rule'):
                        assert any('Rule: ' + row['rule'] in line for line in matches)
    else:
        body = text.split('```json\n', 1)[0]
        assert '## Items' in body
        for row in data['items']:
            assert readable_rows(text, row), row


@pytest.fixture
def sandbox(tmp_path):
    home = tmp_path / 'home'
    home.mkdir()
    store = tmp_path / 'handoffs'
    store.mkdir()
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({'sweep': {'report_location': str(tmp_path / 'reports')}}))
    env = dict(os.environ, HOME=str(home), CODEX_HOME=str(home / '.codex'),
               CONTINUITY_CONFIG=str(config), HANDOFF_STATE_DIR=str(store),
               PYTHONDONTWRITEBYTECODE='1', GIT_OPTIONAL_LOCKS='0')
    return tmp_path, store, config, env


def source(sandbox, name='source', directory=None, loops=None, version=2):
    base, store, _, _ = sandbox
    data = json.loads(FIXTURE.read_text())
    data['subject'] = {'working_directory': str(directory or base), 'session_id': name}
    data['git'] = {'repository_root': '', 'branch': 'main', 'head': ''}
    data['schema_version'] = version
    data['uncommitted_files'] = []
    data['resume']['open_loops'] = loops if loops is not None else [
        {'context': 'Optional observation', 'disposition': 'consider'}]
    path = store / (name + '.json')
    path.write_text(json.dumps(data))
    old = int(time.time()) - 5 * 86400
    os.utime(path, (old, old))
    return path


def command(sandbox, *args, code=0):
    result = subprocess.run([sys.executable, '-B', str(ENGINE), *args],
                            env=sandbox[3], text=True, capture_output=True)
    assert result.returncode == code, result.stderr
    return result


def report(sandbox, *args):
    # This test driver stands in for the agent; the engine never executes stubs.
    args = list(args)
    if json.loads(sandbox[2].read_text())['sweep'].get('mode') == 'act' and '--decisions' not in args:
        empty = sandbox[0] / 'empty-decisions.json'
        empty.write_text('[]')
        args.extend(['--decisions', str(empty)])
    result = command(sandbox, 'run', '--scope', 'all', *args)
    if result.stdout.startswith('{'):
        payload = json.loads(result.stdout)
        path = Path(payload['report'])
        run = read_run(path)
        behavior_path = sandbox[0] / 'behavior.json'
        behavior = json.loads(behavior_path.read_text()) if behavior_path.exists() else {}
        if behavior.get('dirty_file'):
            Path(behavior['dirty_file']).write_text('changed by agent fixture')
        if behavior.get('rewrite_source'):
            for work in run['work']:
                target = Path(work['source_handoff'])
                raw = target.read_bytes()
                how = behavior['rewrite_source']
                if how == 'replacement':
                    target.unlink()
                if how in ('formatting', 'key-order'):
                    target.write_text(json.dumps(json.loads(raw), indent=2, sort_keys=True))
                elif how == 'new-content':
                    data = json.loads(raw)
                    data['resume']['next_action'] = 'New continuation'
                    target.write_text(json.dumps(data))
                else:
                    target.write_bytes(raw)
        for _ in range(3):
            rows = [dict(write_id=w['write_id'], status='failed' if behavior.get('fail') == w['operation'] else 'written',
                         receipt='fixture-' + w['write_id'], destination=w.get('destination') or 'record:created',
                         error='fixture rejection') for w in run['work'] if w['outcome'] == 'intent']
            results = sandbox[0] / 'agent-results.json'
            results.write_text(json.dumps(rows))
            command(sandbox, 'complete', '--run-id', run['run_id'], '--results', str(results))
            run = read_run(path)
            if run['phase'] == 'completed':
                break
        assert run['phase'] == 'completed'
    else:
        path = Path(result.stdout.strip())
    text, data = path.read_text(), read_run(path)
    assert_readable_report(text, data)
    return text, data


def act_profile(sandbox, behavior=None):
    config = json.loads(sandbox[2].read_text())
    config['sweep']['mode'] = 'act'
    config['sweep']['binding_timeout_seconds'] = 0.5
    sandbox[2].write_text(json.dumps(config))
    (sandbox[0] / 'behavior.json').write_text(json.dumps(behavior or {}))
    return bound_profile(sandbox)


def new_work():
    return dict(rule='R5', destination='new ticket', read_status='ok',
                priority='p2', priority_reason='Stated outcome')


def decisions(sandbox, entries):
    path = sandbox[0] / 'decisions.json'
    inspected = json.loads(command(sandbox, 'inspect', '--scope', 'all').stdout)
    rows = []
    for candidate in inspected['candidates']:
        for index, item in enumerate(candidate['items']):
            rows.append(dict(handoff=candidate['path'], identity=item['identity'],
                             **entries[index % len(entries)]))
    path.write_text(json.dumps(rows))
    return ['--decisions', str(path)]


def bound_profile(sandbox):
    stub = sandbox[0] / 'binding.sh'
    stub.write_text('printf called > "$0.called"\nexit 1\n')
    binding = {'command': 'sh ' + shlex.quote(str(stub))}
    profile = sandbox[0] / 'profile.json'
    profile.write_text(json.dumps({'name': 'test', 'ask': binding, 'record_read': binding,
        'bindings': {slot: dict(binding, consumes=[])
                     for slot in ('record', 'lessons', 'knowledge')}}))
    return profile


def outside_report_snapshot(sandbox):
    root = sandbox[0]
    reports = root / 'reports'
    return {str(path.relative_to(root)): (path.read_bytes(), path.stat().st_mtime_ns)
            if path.is_file() else None
            for path in root.rglob('*') if path != reports and reports not in path.parents}


@pytest.mark.parametrize('version', [1, 2])
@pytest.mark.parametrize('copies', ['identical', 'different-metadata'])
@pytest.mark.parametrize('judgments', ['none', 'one', 'repeated', 'conflicting'])
def test_duplicate_identities_in_one_handoff_are_retained_as_ambiguous(sandbox, version, copies, judgments):
    captured = json.loads(FIXTURE.read_text())['resume']['open_loops']
    first = dict(captured[0])
    if version == 1:
        first = {key: value for key, value in first.items()
                 if key not in ('type', 'session_id', 'produced_at')}
    second = dict(first)
    if copies == 'different-metadata':
        # These fields affect filing but are outside the approved identity.
        second.update(anchor={'ticket': 'https://example.test/other-ticket'}, disposition='consider')
        if version == 2:
            second['type'] = 'knowledge'
    items = [first, second, captured[3]]
    path = source(sandbox, loops=items, version=version)
    profile = bound_profile(sandbox)
    inspected = json.loads(command(sandbox, 'inspect', '--scope', 'all').stdout)['candidates'][0]['items']
    assert inspected[0]['identity'] == inspected[1]['identity']
    identity = inspected[0]['identity']
    drop = {'rule': 'R6', 'reason': 'No stated outcome'}
    rows = [dict(handoff=str(path), identity=inspected[2]['identity'], **drop)]
    decision = dict(handoff=str(path), identity=identity, rule='R2',
                    destination='https://example.test/ticket', read_status='ok')
    if judgments != 'none':
        rows.append(decision)
    if judgments in ('repeated', 'conflicting'):
        rows.append(dict(decision) if judgments == 'repeated' else
                    dict(handoff=str(path), identity=identity, **drop))
    choices = sandbox[0] / 'decisions.json'
    choices.write_text(json.dumps(rows))
    before = outside_report_snapshot(sandbox)

    text, data = report(sandbox, '--decisions', str(choices), '--user-profile', str(profile))

    section = data['directories'][str(sandbox[0])]
    outcomes = section['filing_outcomes']
    assert len(outcomes) == len(items)
    for item, row in zip(items[:2], outcomes[:2]):
        assert row['outcome'] == 'ambiguous identity'
        assert row['rule'] is None
        assert row['identity'] == identity
        assert row['item'] == item and row['source_handoff'] == str(path)
        assert row['identity_occurrences'] == 2
        assert 'manual judgment' in row['reason']
        assert 'no filing decision applied' in row['reason']
        assert len(readable_rows(text, row)) == outcomes.count(row)
    assert [item['identity_occurrences'] for item in inspected] == [2, 2, 1]
    assert outcomes[2]['outcome'] == 'dry run'
    assert section['items_dropped'] == [outcomes[2]]
    for key in ('asks_raised', 'new_tickets', 'comments_added', 'documents_changed', 'handoffs_archived'):
        assert not section[key]
    assert section['handoffs_kept'][0]['path'] == str(path)
    assert not data['nothing_to_do']
    assert outside_report_snapshot(sandbox) == before
    assert len(list((sandbox[0] / 'reports').iterdir())) == 1


@pytest.mark.parametrize('field', ['session_id', 'produced_at', 'context'])
def test_each_identity_component_distinguishes_items_in_one_handoff(sandbox, field):
    captured = json.loads(FIXTURE.read_text())['resume']['open_loops']
    first = dict(captured[0])
    second = dict(first)
    second[field] = {'session_id': 'another-producer', 'produced_at': '2026-10-02T00:00:00Z',
                     'context': captured[1]['context']}[field]
    path = source(sandbox, loops=[first, second])
    args = decisions(sandbox, [{'rule': 'R6', 'reason': 'No stated outcome'}])

    _, data = report(sandbox, *args)

    section = data['directories'][str(sandbox[0])]
    assert len(section['items_dropped']) == 2
    assert all(row['outcome'] == 'dry run' for row in section['filing_outcomes'])
    assert section['filing_outcomes'][0]['identity'] != section['filing_outcomes'][1]['identity']
    assert section['handoffs_archived'][0]['path'] == str(path)


def test_same_identity_carried_to_a_successor_is_not_a_within_handoff_ambiguity(sandbox):
    item = json.loads(FIXTURE.read_text())['resume']['open_loops'][0]
    original = source(sandbox, name='original', loops=[item])
    successor = source(sandbox, name='successor', directory=sandbox[0] / 'successor', loops=[item])
    args = decisions(sandbox, [{'rule': 'R6', 'reason': 'No stated outcome'}])

    _, data = report(sandbox, *args)

    identities = []
    for directory, path in ((sandbox[0], original), (sandbox[0] / 'successor', successor)):
        section = data['directories'][str(directory)]
        row, = section['filing_outcomes']
        assert row['outcome'] == 'dry run' and row['source_handoff'] == str(path)
        assert section['handoffs_archived'][0]['path'] == str(path)
        identities.append(row['identity'])
    assert identities[0] == identities[1] == {
        'session_id': item['session_id'], 'produced_at': item['produced_at'], 'text': item['context']}


def test_duplicate_identity_added_after_inspection_blocks_the_existing_decision(sandbox):
    item = json.loads(FIXTURE.read_text())['resume']['open_loops'][0]
    path = source(sandbox, loops=[item])
    args = decisions(sandbox, [{'rule': 'R6', 'reason': 'No stated outcome'}])
    source(sandbox, loops=[item, dict(item)])
    before = outside_report_snapshot(sandbox)

    _, data = report(sandbox, *args)

    section = data['directories'][str(sandbox[0])]
    assert len(section['filing_outcomes']) == 2
    assert all(row['outcome'] == 'ambiguous identity' for row in section['filing_outcomes'])
    assert not section['items_dropped'] and not section['handoffs_archived']
    assert section['handoffs_kept'][0]['path'] == str(path)
    assert outside_report_snapshot(sandbox) == before


def test_duplicate_decisions_for_a_unique_source_identity_are_still_rejected(sandbox):
    source(sandbox)
    args = decisions(sandbox, [{'rule': 'R6', 'reason': 'No stated outcome'}])
    path = Path(args[1])
    rows = json.loads(path.read_text())
    path.write_text(json.dumps(rows + rows))
    before = outside_report_snapshot(sandbox)

    result = command(sandbox, 'run', '--scope', 'all', *args, code=1)

    assert 'duplicate' in result.stderr
    assert outside_report_snapshot(sandbox) == before
    assert not (sandbox[0] / 'reports').exists()


@pytest.mark.parametrize('version', [1, 2])
@pytest.mark.parametrize('entry,binding,section_key', [
    pytest.param({'rule': 'R1', 'information_only': True, 'reason': 'Information only'},
                 None, 'items_dropped', id='R1-information'),
    pytest.param({'rule': 'R1', 'read_status': 'ok', 'reason': 'Already recorded'},
                 None, 'items_dropped', id='R1-recorded'),
    pytest.param({'rule': 'R3', 'destination': 'ask', 'choices': ['approve', 'decline']},
                 'ask', 'asks_raised', id='R3'),
    pytest.param({'rule': 'R4', 'destination': 'lessons'},
                 'lessons', 'filing_outcomes', id='R4-lesson'),
    pytest.param({'rule': 'R4', 'destination': 'knowledge'},
                 'knowledge', 'filing_outcomes', id='R4-knowledge'),
    pytest.param({'rule': 'R4', 'destination': 'ask', 'choices': ['save', 'leave it']},
                 'ask', 'asks_raised', id='R4-pending'),
    pytest.param({'rule': 'R7', 'destination': 'README.md'},
                 'record', 'documents_changed', id='R7'),
    pytest.param({'rule': 'R2', 'destination': 'https://example.test/ticket', 'read_status': 'ok'},
                 'record', 'comments_added', id='R2'),
    pytest.param({'rule': 'R5', 'destination': 'record', 'read_status': 'ok',
                  'priority': 'p2', 'priority_reason': 'Needed'},
                 'record', 'new_tickets', id='R5'),
    pytest.param({'rule': 'R6', 'reason': 'No stated outcome'},
                 None, 'items_dropped', id='R6'),
])
def test_untyped_legacy_items_receive_every_filing_outcome(sandbox, version, entry, binding, section_key):
    captured = json.loads(FIXTURE.read_text())['resume']['open_loops'][2]
    item = {key: value for key, value in captured.items()
            if key not in ('type', 'session_id', 'produced_at')}
    path = source(sandbox, loops=[item], version=version)
    profile = bound_profile(sandbox)
    args = decisions(sandbox, [entry])
    identity = json.loads(Path(args[1]).read_text())[0]['identity']
    before = outside_report_snapshot(sandbox)

    text, data = report(sandbox, *args, '--user-profile', str(profile))

    section = data['directories'][str(sandbox[0])]
    row, = section['filing_outcomes']
    assert row['item'] == item
    assert row['identity'] == identity
    assert row['source_handoff'] == str(path)
    assert row['rule'] == entry['rule'] and row['binding'] == binding
    assert row['outcome'] == 'dry run'
    for key, value in entry.items():
        assert row[key] == value
    if binding == 'ask':
        assert row['ask']['identity'] == identity
    assert section[section_key] == [row]
    assert section['handoffs_archived'][0]['path'] == str(path)
    assert not section['handoffs_kept']
    assert readable_rows(text, row)
    assert outside_report_snapshot(sandbox) == before
    assert len(list((sandbox[0] / 'reports').iterdir())) == 1


@pytest.mark.parametrize('slot', ['lessons', 'knowledge'])
def test_untyped_legacy_slot_without_binding_is_reported_and_kept(sandbox, slot):
    captured = json.loads(FIXTURE.read_text())['resume']['open_loops'][2]
    item = {key: value for key, value in captured.items() if key != 'type'}
    path = source(sandbox, loops=[item], version=1)
    profile = sandbox[0] / 'profile.json'
    profile.write_text(json.dumps({'name': 'test', 'bindings': {slot: None}}))
    args = decisions(sandbox, [{'rule': 'R4', 'destination': slot}])
    before = outside_report_snapshot(sandbox)

    _, data = report(sandbox, *args, '--user-profile', str(profile))

    section = data['directories'][str(sandbox[0])]
    row, = section['filing_outcomes']
    assert row['rule'] == 'R4' and row['binding'] == slot and row['outcome'] == 'unbound'
    assert row['item'] == item
    assert row['identity']['session_id'] == item['session_id']
    assert row['identity']['produced_at'] == item['produced_at']
    assert not section['handoffs_archived']
    assert section['handoffs_kept'][0]['path'] == str(path)
    assert outside_report_snapshot(sandbox) == before


@pytest.mark.parametrize('bad_index', [0, 2])
@pytest.mark.parametrize('bad_entry,item_overrides,error', [
    pytest.param({'rule': 'R1', 'information_only': True}, {}, 'requires dropped with a reason', id='R1'),
    pytest.param({'rule': 'R3', 'destination': 'ask'}, {}, "an ask requires the user's choices", id='R3'),
    pytest.param({'rule': 'R4', 'destination': 'record'}, {}, 'R4 requires', id='R4'),
    pytest.param({'rule': 'R7'}, {}, 'a filed item requires its destination', id='R7'),
    pytest.param({'rule': 'R2', 'read_status': 'ok'}, {}, 'a filed item requires its destination', id='R2'),
    pytest.param({'rule': 'R5', 'destination': 'record', 'read_status': 'ok'}, {},
                 'a new ticket requires priority', id='R5'),
    pytest.param({'rule': 'R6', 'reason': ''}, {}, 'requires dropped with a reason', id='R6'),
    pytest.param({'rule': 'unknown'}, {}, 'unknown rule', id='unknown-rule'),
    pytest.param({'rule': 'R3', 'destination': 'ask', 'choices': ['approve', 'decline']},
                 {'anchor': ['invalid anchor']}, 'has no attribute', id='malformed-legacy-anchor'),
])
def test_item_failure_is_reported_without_aborting_other_items_or_handoffs(sandbox, bad_index, bad_entry,
                                                                         item_overrides, error):
    captured = json.loads(FIXTURE.read_text())['resume']['open_loops']
    items = [{key: value for key, value in item.items() if key != 'type'} for item in captured[:3]]
    items[bad_index].update(item_overrides)
    path = source(sandbox, name='broken', loops=items, version=1)
    other_directory = sandbox[0] / 'other'
    other = source(sandbox, name='healthy', directory=other_directory, loops=[captured[3]])
    profile = bound_profile(sandbox)
    valid = {'rule': 'R6', 'reason': 'No stated outcome'}
    entries = [bad_entry if index == bad_index else valid for index in range(len(items))]
    args = decisions(sandbox, entries)
    rows = json.loads(Path(args[1]).read_text())
    rows = [dict(handoff=row['handoff'], identity=row['identity'], **valid)
            if row['handoff'] == str(other) else row for row in rows]
    Path(args[1]).write_text(json.dumps(rows))
    before = outside_report_snapshot(sandbox)

    text, data = report(sandbox, *args, '--user-profile', str(profile))

    section = data['directories'][str(sandbox[0])]
    outcomes = section['filing_outcomes']
    assert len(outcomes) == len(items)
    for index, row in enumerate(outcomes):
        assert row['item'] == items[index]
        assert row['identity'] == rows[index]['identity']
        assert row['source_handoff'] == str(path)
        assert row['outcome'] == ('failed' if index == bad_index else 'dry run')
    failed = outcomes[bad_index]
    assert failed['rule'] == bad_entry['rule']
    assert failed.get('destination') == bad_entry.get('destination')
    assert error in failed['error']
    assert readable_rows(text, failed)
    assert len(section['items_dropped']) == len(items) - 1
    for key in ('asks_raised', 'comments_added', 'new_tickets', 'documents_changed', 'handoffs_archived'):
        assert not section[key]
    assert section['handoffs_kept'][0]['path'] == str(path)
    healthy = data['directories'][str(other_directory)]
    assert healthy['filing_outcomes'][0]['outcome'] == 'dry run'
    assert healthy['handoffs_archived'][0]['path'] == str(other)
    assert not data['nothing_to_do']
    assert outside_report_snapshot(sandbox) == before
    assert len(list((sandbox[0] / 'reports').iterdir())) == 1


def test_watch_report_covers_legacy_drop_and_changes_only_report(sandbox):
    path = source(sandbox, version=1)
    before = path.read_bytes()
    args = decisions(sandbox, [{'rule': 'R6', 'reason': 'No stated outcome'}])
    text, data = report(sandbox, *args)
    assert data['mode'] == 'watch-only'
    assert data['run_id'] and data['host'] and data['started_at'] and data['ended_at']
    section = data['directories'][str(sandbox[0])]
    assert section['items_dropped'][0]['rule'] == 'R6'
    assert section['items_dropped'][0]['reason'] == 'No stated outcome'
    assert section['handoffs_archived'][0]['outcome'] == 'dry run'
    assert path.read_bytes() == before
    assert list(sandbox[1].iterdir()) == [path]
    assert len(list((sandbox[0] / 'reports').iterdir())) == 1
    headings = ['Asks raised', 'Open sessions with idle time', 'New tickets with priority',
                'Comments added', 'Documents changed', 'Items dropped with reasons',
                'Worktrees removed', 'Handoffs archived']
    assert [text.index('### ' + h) for h in headings] == sorted(text.index('### ' + h) for h in headings)


def test_no_judgment_retains_every_item_and_parse_errors(sandbox):
    path = source(sandbox)
    (sandbox[1] / 'bad.json').write_text('{')
    _, data = report(sandbox)
    section = data['directories'][str(sandbox[0])]
    assert section['filing_outcomes'][0]['outcome'] == 'pending judgment'
    assert section['handoffs_archived'] == []
    assert data['errors'][0]['path'].endswith('bad.json')
    assert data['errors'][0]['reason']
    assert path.exists()


def test_empty_run_and_recent_handoff(sandbox):
    text, data = report(sandbox)
    assert data['nothing_to_do'] and 'Nothing to do.' in text
    path = source(sandbox)
    os.utime(path, None)
    _, data = report(sandbox)
    assert data['nothing_to_do']


def test_newest_claude_and_codex_transcript_controls_idle(sandbox):
    for provider in ('claude', 'codex'):
        path = source(sandbox, name=provider)
        if provider == 'claude':
            slug = str(sandbox[0]).replace('/', '-').replace('.', '-')
            transcript = Path(sandbox[3]['HOME']) / '.claude/projects' / slug / 'claude.jsonl'
            transcript.parent.mkdir(parents=True)
            transcript.write_text('{}\n')
        else:
            transcript = Path(sandbox[3]['CODEX_HOME']) / 'sessions/2026/10/24/rollout-2026-10-24T00-00-00-codex.jsonl'
            transcript.parent.mkdir(parents=True)
            transcript.write_text('{}\n')
        _, data = report(sandbox)
        assert data['nothing_to_do'], (provider, data)
        path.unlink()


def test_exact_non_repository_scope(sandbox):
    source(sandbox, 'one', directory=sandbox[0] / 'one')
    source(sandbox, 'two', directory=sandbox[0] / 'one/child')
    result = command(sandbox, 'inspect', '--scope', str(sandbox[0] / 'one'))
    assert [c['session_id'] for c in json.loads(result.stdout)['candidates']] == ['one']


def test_repository_scope_includes_sibling_worktrees(sandbox):
    repo, sibling = sandbox[0] / 'repo', sandbox[0] / 'sibling'
    def git(*args):
        return subprocess.run(['git', *map(str, args)], check=True, capture_output=True, text=True)
    git('init', '-q', repo)
    git('-C', repo, '-c', 'user.name=Test', '-c', 'user.email=test@example.test', 'commit', '--allow-empty', '-qm', 'base')
    git('-C', repo, 'worktree', 'add', '-qb', 'feature-a', sibling)
    source(sandbox, 'main', directory=repo)
    source(sandbox, 'sibling', directory=sibling)
    result = command(sandbox, 'inspect', '--scope', str(repo))
    assert {c['session_id'] for c in json.loads(result.stdout)['candidates']} == {'main', 'sibling'}


def test_all_filing_rules_share_checklist_validation_without_binding_calls(sandbox):
    items = [{'context': f'Item {i}', 'disposition': 'file'} for i in range(7)]
    items[2].update(type='lesson', session_id='original', produced_at='2026-10-01T00:00:00Z')
    source(sandbox, loops=items)
    profile = sandbox[0] / 'profile.json'
    profile.write_text(json.dumps({'name': 'test', 'ask': {'command': 'MUST NEVER RUN'},
        'bindings': {key: {'command': 'MUST NEVER RUN', 'consumes': []}
                     for key in ('record', 'lessons', 'knowledge')}}))
    entries = [
        {'rule': 'R1', 'information_only': True, 'reason': 'Information only'},
        {'rule': 'R3', 'destination': 'ask', 'choices': ['approve', 'decline']},
        {'rule': 'R4', 'destination': 'lessons'},
        {'rule': 'R7', 'destination': 'README.md'},
        {'rule': 'R2', 'destination': 'https://example.test/ticket', 'read_status': 'ok'},
        {'rule': 'R5', 'destination': 'record', 'read_status': 'ok', 'priority': 'p2', 'priority_reason': 'Needed'},
        {'rule': 'R6', 'reason': 'No outcome'}]
    _, data = report(sandbox, *decisions(sandbox, entries), '--user-profile', str(profile))
    section = data['directories'][str(sandbox[0])]
    assert len(section['filing_outcomes']) == 7
    assert all(row['outcome'] == 'dry run' for row in section['filing_outcomes'])
    assert section['new_tickets'][0]['priority'] == 'p2'
    assert section['asks_raised'][0]['ask']['choices'] == ['approve', 'decline']
    assert section['handoffs_archived']
    assert section['filing_outcomes'][2]['identity']['session_id'] == 'original'


def test_failed_reads_and_unbound_asks_keep_handoff(sandbox):
    source(sandbox)
    _, data = report(sandbox, *decisions(sandbox, [{'rule': 'R5', 'destination': 'record'}]))
    section = data['directories'][str(sandbox[0])]
    assert section['filing_outcomes'][0]['outcome'] == 'read failed'
    assert not section['handoffs_archived']
    _, data = report(sandbox, *decisions(sandbox, [{'rule': 'R3', 'choices': ['yes', 'no'], 'destination': 'ask'}]))
    section = data['directories'][str(sandbox[0])]
    assert section['filing_outcomes'][0]['outcome'] == 'unbound'
    assert not section['handoffs_archived']


def test_dirty_files_raise_ask_and_keep_handoff(sandbox):
    path = source(sandbox, loops=[])
    data = json.loads(path.read_text())
    data['uncommitted_files'] = [str(sandbox[0] / 'changed.txt')]
    path.write_text(json.dumps(data))
    old = int(time.time()) - 5 * 86400
    os.utime(path, (old, old))
    _, data = report(sandbox)
    section = data['directories'][str(sandbox[0])]
    ask = section['asks_raised'][0]['ask']
    assert ask['session_id'] == 'source' and ask['directory'] == str(sandbox[0])
    assert 'changed.txt' in ask['text']
    assert not section['handoffs_archived']


def test_open_session_evidence_blocks_filing(sandbox):
    source(sandbox)
    evidence = sandbox[0] / 'open.json'
    evidence.write_text(json.dumps({'session_ids': ['source'], 'method': 'interactive inspection'}))
    _, data = report(sandbox, '--open-sessions', str(evidence), '--interactive')
    section = data['directories'][str(sandbox[0])]
    assert section['open_sessions'][0]['idle_seconds'] > 2 * 86400
    assert not section['filing_outcomes']
    assert data['open_session_checks'][0]['method'] == 'interactive inspection'


def test_second_run_exits_without_any_write_when_store_locked(sandbox):
    source(sandbox)
    fd = os.open(sandbox[1], os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = command(sandbox, 'run', '--scope', 'all', code=2)
        assert 'already running' in result.stderr
        assert not (sandbox[0] / 'reports').exists()
    finally:
        os.close(fd)


@pytest.mark.parametrize('settings', [{'mode': 'invalid'}, {'idle_days': -1}, {'idle_days': True},
                                      {'open_session_checks': [None]}])
def test_invalid_or_future_settings_never_execute_actions(sandbox, settings):
    sandbox[2].write_text(json.dumps({'sweep': settings}))
    command(sandbox, 'run', '--scope', 'all', code=1)
    assert not (sandbox[0] / 'reports').exists()


def test_stale_decisions_cannot_be_applied_to_changed_item(sandbox):
    path = source(sandbox)
    args = decisions(sandbox, [{'rule': 'R6', 'reason': 'Optional'}])
    data = json.loads(path.read_text())
    data['resume']['open_loops'][0]['context'] = 'Changed outcome'
    path.write_text(json.dumps(data))
    old = int(time.time()) - 5 * 86400
    os.utime(path, (old, old))
    command(sandbox, 'run', '--scope', 'all', *args, code=1)


def test_engine_imports_with_stdlib_only():
    probe = subprocess.run([sys.executable, '-I', '-S', '-B', str(ENGINE), '--help'],
                           text=True, capture_output=True)
    assert probe.returncode == 0, probe.stderr


def test_worktree_proposal_requires_clean_merged_branch_and_preserves_files(sandbox):
    repo, bare, linked = [sandbox[0] / name for name in ('repo', 'origin.git', 'linked')]
    def git(*args):
        return subprocess.run(['git', *map(str, args)], check=True, capture_output=True, text=True)
    git('init', '--bare', '-q', bare)
    git('init', '-qb', 'main', repo)
    git('-C', repo, '-c', 'user.name=Test', '-c', 'user.email=test@example.test', 'commit', '--allow-empty', '-qm', 'base')
    git('-C', repo, 'remote', 'add', 'origin', bare)
    git('-C', repo, 'push', '-q', 'origin', 'main')
    git('-C', repo, 'worktree', 'add', '-qb', 'feature-a', linked)
    source(sandbox, directory=linked, loops=[])
    _, data = report(sandbox)
    section = data['directories'][str(linked)]
    removal = section['worktrees_removed'][0]
    assert removal['branch'] == 'feature-a' and removal['commit']
    assert removal['checks']['clean'] and removal['checks']['contained_in_pushed_trunk']
    assert (linked / '.git').exists()
    (linked / 'untracked.txt').write_text('work')
    _, data = report(sandbox)
    section = data['directories'][str(linked)]
    assert section['worktrees_removed'] == []
    assert not section['handoffs_archived']
    assert section['asks_raised'][0]['outcome'] == 'unbound'
    assert (linked / 'untracked.txt').read_text() == 'work'


def test_missing_legacy_subject_is_decidable_in_all_scope(sandbox):
    path = source(sandbox, version=1)
    data = json.loads(path.read_text())
    data.pop('subject')
    path.write_text(json.dumps(data))
    old = int(time.time()) - 5 * 86400
    os.utime(path, (old, old))
    _, data = report(sandbox, *decisions(sandbox, [{'rule': 'R6', 'reason': 'No outcome'}]))
    assert data['directories']['unknown directory']['items_dropped'][0]['rule'] == 'R6'


def test_unsafe_transcript_discovery_keeps_every_handoff(sandbox):
    source(sandbox)
    linked = Path(sandbox[3]['CODEX_HOME']) / 'sessions'
    linked.parent.mkdir(parents=True)
    target = sandbox[0] / 'relocated'
    target.mkdir()
    linked.symlink_to(target, target_is_directory=True)
    _, data = report(sandbox)
    assert not data['directories']
    assert data['errors'][0]['blocks_sweep']


def test_report_settings_and_strict_idle_boundary(sandbox):
    spec = importlib.util.spec_from_file_location('test_sweep_engine', ENGINE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    path = source(sandbox)
    from datetime import datetime, timezone
    instant = datetime.fromtimestamp(path.stat().st_mtime + 2 * 86400, timezone.utc)
    # Direct deterministic seam; no ambient store or transcript access.
    original = dict(os.environ)
    try:
        os.environ.update(sandbox[3])
        config = module.settings()
        assert config['idle_days'] == 2 and config['archive_retention_days'] is None
        found = module.discover('all', config, instant)
        assert not found['candidates'][0]['abandoned']
    finally:
        os.environ.clear()
        os.environ.update(original)


def test_shared_skill_is_shipped_by_both_installers():
    spec = importlib.util.spec_from_file_location('installer', ROOT / 'scripts/install-codex.py')
    sys.path.insert(0, str(ROOT / 'scripts'))
    try:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    assert 'sweep' in module.SKILLS
    skill = (ROOT / 'skills/sweep/SKILL.md').read_text()
    assert 'name: sweep' in skill
    assert 'scripts/lib/sweep.py' in skill


def test_failed_read_is_retained_instead_of_reported_as_drop_or_new_ticket(sandbox):
    source(sandbox)
    for row in ({'rule': 'R1', 'reason': 'Possibly recorded'},
                {'rule': 'R5', 'destination': 'record'}):
        _, data = report(sandbox, *decisions(sandbox, [row]))
        section = data['directories'][str(sandbox[0])]
        assert section['filing_outcomes'][0]['outcome'] == 'read failed'
        assert not section['items_dropped'] and not section['new_tickets']


def test_generated_ask_includes_stable_source_identity(sandbox):
    path = source(sandbox, loops=[])
    data = json.loads(path.read_text())
    data['uncommitted_files'] = [str(sandbox[0] / 'changed.txt')]
    path.write_text(json.dumps(data))
    old = int(time.time()) - 5 * 86400
    os.utime(path, (old, old))
    _, first = report(sandbox)
    _, second = report(sandbox)
    first_ask = first['directories'][str(sandbox[0])]['asks_raised'][0]
    second_ask = second['directories'][str(sandbox[0])]['asks_raised'][0]
    assert first_ask['identity'] == second_ask['identity']
    assert first_ask['ask']['identity'] == first_ask['identity']


def test_captured_handoff_can_be_swept_without_losing_any_item(sandbox):
    captured = json.loads(FIXTURE.read_text())
    path = source(sandbox, loops=captured['resume']['open_loops'])
    _, data = report(sandbox, *decisions(sandbox, [{'rule': 'R1', 'information_only': True, 'reason': 'Information only'}]))
    outcomes = data['directories'][str(sandbox[0])]['filing_outcomes']
    assert len(outcomes) == len(captured['resume']['open_loops'])
    assert all(row['rule'] == 'R1' for row in outcomes)
    assert path.exists()


@pytest.mark.parametrize('scope_kind', ['all', 'repository-subdirectory'])
@pytest.mark.parametrize('activity', ['open-subdirectory', 'recent-subdirectory', 'open-root', 'open-sibling-prefix'])
def test_active_sessions_protect_containing_worktree_without_merging_directories(sandbox, scope_kind, activity):
    repo, bare, linked = [sandbox[0] / name for name in ('repo', 'origin.git', 'linked')]

    def git(*args):
        return subprocess.run(['git', *map(str, args)], check=True, capture_output=True, text=True)

    git('init', '--bare', '-q', bare)
    git('init', '-qb', 'main', repo)
    git('-C', repo, '-c', 'user.name=Test', '-c', 'user.email=test@example.test',
        'commit', '--allow-empty', '-qm', 'base')
    git('-C', repo, 'remote', 'add', 'origin', bare)
    git('-C', repo, 'push', '-q', 'origin', 'main')
    git('-C', repo, 'worktree', 'add', '-qb', 'feature-a', linked)
    (repo / 'docs').mkdir()
    (linked / 'docs').mkdir()
    old = source(sandbox, 'abandoned', directory=linked, loops=[])
    if activity == 'open-sibling-prefix':
        sibling = sandbox[0] / 'linked-other'
        git('-C', repo, 'worktree', 'add', '-qb', 'feature-b', sibling)
        active_dir = sibling
    else:
        active_dir = linked if activity == 'open-root' else linked / 'docs'
    active = source(sandbox, 'active', directory=active_dir, loops=[])
    if activity == 'recent-subdirectory':
        os.utime(active, None)
    evidence = sandbox[0] / 'open.json'
    evidence.write_text(json.dumps({'session_ids': [] if activity == 'recent-subdirectory' else ['active'],
                                    'method': 'isolated test session evidence'}))
    scope = 'all' if scope_kind == 'all' else str(repo / 'docs')
    inspected = json.loads(command(sandbox, 'inspect', '--scope', scope).stdout)
    assert {c['directory'] for c in inspected['candidates']} == {str(linked), str(active_dir)}
    before = {path: path.read_bytes() for path in (old, active)}
    _, data = report(sandbox, '--scope', scope, '--open-sessions', str(evidence))
    section = data['directories'][str(linked)]
    if activity == 'open-sibling-prefix':
        assert section['worktrees_removed'][0]['path'] == str(linked)
        assert not section['worktrees_kept']
    else:
        assert section['worktrees_removed'] == []
        kept = section['worktrees_kept'][0]
        assert kept['path'] == str(linked)
        assert kept['reason'] == 'another open or active session uses this worktree'
    if activity.startswith('open'):
        assert data['directories'][str(active_dir)]['open_sessions'][0]['session_id'] == 'active'
    assert {path: path.read_bytes() for path in before} == before
    assert (linked / '.git').exists()


def archive_test_repository(sandbox, location):
    repo, bare, linked = [sandbox[0] / name for name in ('repo', 'origin.git', 'linked')]

    def git(*args):
        return subprocess.run(['git', *map(str, args)], check=True, capture_output=True, text=True)

    git('init', '--bare', '-q', bare)
    git('init', '-qb', 'main', repo)
    (repo / 'changed.txt').write_bytes(FIXTURE.read_bytes())
    git('-C', repo, 'add', 'changed.txt')
    git('-C', repo, '-c', 'user.name=Test', '-c', 'user.email=test@example.test',
        'commit', '-qm', 'base')
    git('-C', repo, 'remote', 'add', 'origin', bare)
    git('-C', repo, 'push', '-q', 'origin', 'main')
    if location.startswith('linked'):
        git('-C', repo, 'worktree', 'add', '-qb', 'feature', linked)
        root = linked
    else:
        root = repo
    directory = root / 'docs' if location.endswith('subdirectory') else root
    directory.mkdir(exist_ok=True)
    return root, directory


@pytest.mark.parametrize('mode', ['watch-only', 'act'])
@pytest.mark.parametrize('location', ['main', 'main-subdirectory', 'linked', 'linked-subdirectory'])
@pytest.mark.parametrize('dirty_kind', ['tracked', 'untracked'])
def test_archive_requires_observed_clean_worktree_despite_delivered_ask(sandbox, mode, location, dirty_kind):
    root, directory = archive_test_repository(sandbox, location)
    path = source(sandbox, directory=directory, loops=[])
    original = path.read_bytes()
    changed = root / ('changed.txt' if dirty_kind == 'tracked' else 'untracked.txt')
    changed.write_bytes(FIXTURE.read_bytes() + b'\n')
    profile = act_profile(sandbox)
    config = json.loads(sandbox[2].read_text())
    config['sweep']['mode'] = mode
    sandbox[2].write_text(json.dumps(config))

    _, data = report(sandbox, '--user-profile', str(profile))

    section = data['directories'][str(directory)]
    assert not section['handoffs_archived']
    assert section['handoffs_kept'][0]['path'] == str(path)
    assert path.read_bytes() == original
    assert changed.read_bytes() == FIXTURE.read_bytes() + b'\n'
    assert (root / '.git').exists()
    if mode == 'act' and location == 'linked':
        assert section['asks_raised'][0]['outcome'] == 'written'


def test_archive_rechecks_clean_worktree_after_binding(sandbox):
    root, directory = archive_test_repository(sandbox, 'linked')
    path = source(sandbox, directory=directory)
    profile = act_profile(sandbox, {'dirty_file': str(root / 'untracked.txt')})
    args = decisions(sandbox, [{'rule': 'R3', 'destination': 'ask', 'choices': ['approve', 'decline']}])

    _, data = report(sandbox, *args, '--user-profile', str(profile))

    section = data['directories'][str(directory)]
    assert section['filing_outcomes'][0]['outcome'] == 'written'
    assert (root / 'untracked.txt').exists()
    assert not section['handoffs_archived']
    assert path.exists()


def test_archive_keeps_unreadable_worktree_status(sandbox):
    _, directory = archive_test_repository(sandbox, 'main')
    path = source(sandbox, directory=directory, loops=[])
    profile = act_profile(sandbox)
    real_git = subprocess.run(['which', 'git'], check=True, text=True, capture_output=True).stdout.strip()
    binary = sandbox[0] / 'bin'
    binary.mkdir()
    shim = binary / 'git'
    shim.write_text('#!' + sys.executable + '\nimport os, sys\n'
                    'if "status" in sys.argv[1:]:\n'
                    '    print("worktree status unavailable", file=sys.stderr); sys.exit(1)\n'
                    f'os.execv({real_git!r}, [{real_git!r}, *sys.argv[1:]])\n')
    shim.chmod(0o755)
    sandbox[3]['PATH'] = str(binary) + os.pathsep + sandbox[3]['PATH']

    _, data = report(sandbox, '--user-profile', str(profile))

    section = data['directories'][str(directory)]
    assert not section['handoffs_archived']
    assert path.exists()
    assert 'worktree status unavailable' in section['handoffs_kept'][0]['reason']


@pytest.mark.parametrize('rewrite', ['formatting', 'key-order', 'same-bytes', 'replacement', 'new-content'])
def test_archive_keeps_any_source_rewritten_after_discovery(sandbox, rewrite):
    path = source(sandbox)
    original = path.read_bytes()
    profile = act_profile(sandbox, {'rewrite_source': rewrite})
    args = decisions(sandbox, [new_work()])

    _, data = report(sandbox, *args, '--user-profile', str(profile))

    section = data['directories'][str(sandbox[0])]
    assert section['filing_outcomes'][0]['outcome'] == 'written'
    assert not section['handoffs_archived']
    assert section['handoffs_kept'][0]['error'] == 'handoff changed since discovery'
    assert path.exists()
    if rewrite in ('formatting', 'key-order'):
        assert path.read_bytes() != original
        assert json.loads(path.read_bytes()) == json.loads(original)
    elif rewrite in ('same-bytes', 'replacement'):
        assert path.read_bytes() == original
    else:
        assert json.loads(path.read_bytes()) != json.loads(original)


@pytest.mark.parametrize('guard', ['pending-item', 'unbound-ask', 'recorded-files',
                                   'open-session', 'recent-session', 'unbound-record'])
def test_archive_other_retention_conditions_remain_independent(sandbox, guard):
    path = source(sandbox)
    profile = act_profile(sandbox)
    if guard == 'unbound-ask':
        data = json.loads(profile.read_text())
        data.pop('ask')
        profile.write_text(json.dumps(data))
    elif guard == 'unbound-record':
        data = json.loads(profile.read_text())
        data['bindings']['record'] = None
        profile.write_text(json.dumps(data))
    elif guard == 'recorded-files':
        data = json.loads(path.read_text())
        data['uncommitted_files'] = [str(sandbox[0] / 'changed.txt')]
        path.write_text(json.dumps(data))
        os.utime(path, (time.time() - 5 * 86400,) * 2)
    entry = ({'rule': 'R3', 'destination': 'ask', 'choices': ['approve', 'decline']}
             if guard == 'unbound-ask' else
             {'rule': 'R7', 'destination': 'README.md'} if guard == 'unbound-record' else new_work())
    args = [] if guard == 'pending-item' else decisions(sandbox, [entry])
    if guard == 'open-session':
        evidence = sandbox[0] / 'open.json'
        evidence.write_text(json.dumps({'session_ids': ['source'], 'method': 'isolated evidence'}))
        args.extend(['--open-sessions', str(evidence)])
    if guard == 'recent-session':
        os.utime(path, None)
    before = path.read_bytes()

    _, data = report(sandbox, *args, '--user-profile', str(profile))

    assert path.read_bytes() == before
    assert not any(section['handoffs_archived'] for section in data['directories'].values())
    if guard in ('recent-session', 'pending-item'):
        assert not (sandbox[0] / 'binding.sh.called').exists()


def configure_checks(sandbox, commands):
    config = json.loads(sandbox[2].read_text())
    config['sweep']['open_session_checks'] = commands
    sandbox[2].write_text(json.dumps(config))


def check_command(sandbox, name, content):
    path = sandbox[0] / (name + '.py')
    path.write_text(content)
    return shlex.join([sys.executable, str(path)])


def test_configured_checks_union_and_failure_block_abandonment(sandbox):
    first = source(sandbox, name='first')
    second = source(sandbox, name='second')
    a = check_command(sandbox, 'a', 'print("first")')
    b = check_command(sandbox, 'b', 'print("second")')
    configure_checks(sandbox, [a, b])
    _, data = report(sandbox)
    section = data['directories'][str(sandbox[0])]
    assert {s['session_id'] for s in section['open_sessions']} == {'first', 'second'}
    assert not section['filing_outcomes']
    failing = check_command(sandbox, 'fail', 'import sys; sys.exit(7)')
    configure_checks(sandbox, [a, failing])
    profile = act_profile(sandbox)
    _, data = report(sandbox, '--user-profile', str(profile))
    assert failing in json.dumps(data['errors'])
    assert first.exists() and second.exists()
    assert all(not s['filing_outcomes'] and not s['worktrees_removed']
               for s in data['directories'].values())


@pytest.mark.parametrize('interactive', [False, True])
def test_open_idle_ask_once_until_activity_changes(sandbox, interactive):
    path = source(sandbox, loops=[])
    profile = act_profile(sandbox)
    configure_checks(sandbox, [check_command(sandbox, 'open', 'print("source")')])
    args = ['--user-profile', str(profile)]
    if interactive:
        args += ['--interactive']
    _, data = report(sandbox, *args)
    row, = data['directories'][str(sandbox[0])]['asks_raised']
    assert row['ask']['choices'] == ['wrap it', 'leave it', 'close it']
    assert row['outcome'] == 'written'
    _, data = report(sandbox, *args)
    assert not data['directories'][str(sandbox[0])]['asks_raised']
    activity = path.stat().st_mtime + 60
    os.utime(path, (activity, activity))
    _, data = report(sandbox, *args)
    assert len(data['directories'][str(sandbox[0])]['asks_raised']) == 1
    assert not (sandbox[0] / 'binding.sh.called').exists()
    assert path.exists()


@pytest.mark.parametrize('subdirectory', [False, True])
@pytest.mark.parametrize('kind', ['clean', 'dirty', 'unmerged', 'main', 'open', 'failed-check', 'locked'])
def test_act_worktree_cleanup_safeguards(sandbox, kind, subdirectory):
    location = 'main' if kind == 'main' else 'linked'
    root, directory = archive_test_repository(sandbox, location + ('-subdirectory' if subdirectory else ''))
    repo = sandbox[0] / 'repo'
    profile = act_profile(sandbox)
    path = source(sandbox, directory=directory, loops=[])
    git = lambda *args: subprocess.run(['git', '-C', str(repo), *map(str, args)],
                                      capture_output=True, text=True, check=True)
    head = git('rev-parse', 'HEAD').stdout.strip()
    if kind == 'dirty':
        (root / 'untracked').write_text('work')
    if kind == 'unmerged':
        subprocess.run(['git', '-C', str(root), '-c', 'user.name=Test', '-c',
                        'user.email=test@example.test', 'commit', '--allow-empty', '-qm', 'work'], check=True)
    if kind == 'locked':
        git('worktree', 'lock', root)
    if kind == 'open':
        source(sandbox, name='live', directory=root / 'docs', loops=[])
        configure_checks(sandbox, [check_command(sandbox, 'open', 'print("live")')])
    if kind == 'failed-check':
        configure_checks(sandbox, [check_command(sandbox, 'fail', 'import sys; sys.exit(1)')])
    _, data = report(sandbox, '--user-profile', str(profile))
    section = data['directories'][str(directory)]
    if kind == 'clean':
        assert not root.exists()
        assert git('branch', '--list', 'feature').stdout == ''
        row, = section['worktrees_removed']
        assert row['branch'] == 'feature' and row['commit'] == head
        assert row['checks']['plain_removal'] is True
        assert row['outcome'] == 'removed'
        assert not path.exists()
    else:
        assert root.exists() and not section['worktrees_removed']
        if kind in ('dirty', 'unmerged', 'open', 'locked'):
            assert section['asks_raised']
        if kind == 'failed-check':
            assert path.exists()
    assert git('ls-remote', 'origin', 'refs/heads/main').stdout.split()[0] == head


def test_worktree_becoming_dirty_during_filing_raises_failed_check_ask(sandbox):
    root, directory = archive_test_repository(sandbox, 'linked')
    source(sandbox, directory=directory)
    profile = act_profile(sandbox, {'dirty_file': str(root / 'untracked')})
    args = decisions(sandbox, [{'rule': 'R3', 'destination': 'ask', 'choices': ['save', 'leave it']}])
    _, data = report(sandbox, *args, '--user-profile', str(profile))
    section = data['directories'][str(directory)]
    assert root.exists() and not section['worktrees_removed']
    assert any('Keep worktree' in r['ask']['text'] for r in section['asks_raised'])
    assert section['worktrees_kept'][0]['checks']['clean'] is False


@pytest.mark.parametrize('failure', ['missing', 'timeout'])
def test_unrunnable_check_keeps_handoffs_and_reports_command(sandbox, failure):
    path = source(sandbox, loops=[])
    profile = act_profile(sandbox)
    cmd = str(sandbox[0] / 'missing-command') if failure == 'missing' else check_command(
        sandbox, 'slow', 'import time; time.sleep(2)')
    configure_checks(sandbox, [cmd])
    inspected = json.loads(command(sandbox, 'inspect', '--scope', 'all').stdout)
    assert inspected['candidates'][0]['abandoned'] is False
    _, data = report(sandbox, '--user-profile', str(profile))
    assert path.exists() and cmd in json.dumps(data['errors'])
    assert data['directories'][str(sandbox[0])]['handoffs_kept']
    assert not (sandbox[0] / 'binding.sh.called').exists()


@pytest.mark.parametrize('provider', ['claude', 'codex'])
def test_transcript_activity_rearms_open_session_ask(sandbox, provider):
    source(sandbox, loops=[])
    profile = act_profile(sandbox)
    configure_checks(sandbox, [check_command(sandbox, 'open', 'print("source")')])
    if provider == 'claude':
        transcript = Path(sandbox[3]['HOME']) / '.claude/projects/project/source.jsonl'
    else:
        transcript = Path(sandbox[3]['CODEX_HOME']) / 'sessions/2026/10/24/rollout-2026-10-24T00-00-00-source.jsonl'
    transcript.parent.mkdir(parents=True)
    transcript.write_text('{}\n')
    activity = time.time() - 4 * 86400
    os.utime(transcript, (activity, activity))
    for expected in (1, 0):
        _, data = report(sandbox, '--user-profile', str(profile))
        assert len(data['directories'][str(sandbox[0])]['asks_raised']) == expected
    os.utime(transcript, (activity + 60, activity + 60))
    _, data = report(sandbox, '--user-profile', str(profile))
    assert len(data['directories'][str(sandbox[0])]['asks_raised']) == 1
    assert not (sandbox[0] / 'binding.sh.called').exists()


@pytest.mark.parametrize('order', ['protected-first', 'clean-first'])
@pytest.mark.parametrize('mode,protection',
    [('watch-only', kind) for kind in ('recorded-files', 'pending-item', 'open', 'recent')] +
    [('act', kind) for kind in ('recorded-files', 'pending-item', 'failed-write', 'changed-source', 'open', 'recent')])
@pytest.mark.parametrize('layout', ['same-directory', 'nested', 'siblings'])
def test_shared_worktree_protection_is_independent_of_handoff_order(
        sandbox, order, mode, protection, layout):
    root, directory = archive_test_repository(sandbox, 'linked')
    protected_dir = root if layout == 'same-directory' else root / 'docs'
    protected_dir.mkdir(exist_ok=True)
    if layout == 'siblings':
        directory = root / 'other'
        directory.mkdir()
    protected_name, clean_name = ('a-protected', 'z-clean') if order == 'protected-first' else ('z-protected', 'a-clean')
    source(sandbox, name=clean_name, directory=directory, loops=[])
    protected = source(sandbox, name=protected_name, directory=protected_dir,
                       loops=None if protection in ('pending-item', 'failed-write', 'changed-source') else [])
    behavior = {'fail': 'ask'} if protection == 'failed-write' else (
        {'rewrite_source': 'same-bytes'} if protection == 'changed-source' else {})
    profile = act_profile(sandbox, behavior)
    if protection == 'recorded-files':
        data = json.loads(protected.read_text())
        data['uncommitted_files'] = [str(root / 'changed.txt')]
        protected.write_text(json.dumps(data))
        os.utime(protected, (time.time() - 5 * 86400,) * 2)
    if protection == 'open':
        configure_checks(sandbox, [check_command(sandbox, 'open-shared', f'print({protected_name!r})')])
    if protection == 'recent':
        os.utime(protected, None)
    config = json.loads(sandbox[2].read_text())
    config['sweep']['mode'] = mode
    sandbox[2].write_text(json.dumps(config))
    args = []
    if protection in ('failed-write', 'changed-source'):
        args = decisions(sandbox, [{'rule': 'R3', 'destination': 'ask', 'choices': ['save', 'leave it']}])
    _, data = report(sandbox, *args, '--user-profile', str(profile))
    assert not data['errors'], 'the shared handoffs must be valid discovery inputs'
    assert root.exists(), 'a sibling handoff must protect the shared worktree'
    assert not any(s['worktrees_removed'] for s in data['directories'].values())
    assert any(r['path'] == str(root) for s in data['directories'].values() for r in s['worktrees_kept'])
    assert subprocess.run(['git', '-C', str(root), 'rev-parse', '--verify', 'refs/heads/feature'],
                          capture_output=True).returncode == 0
    if mode == 'act':
        assert protected.exists()


@pytest.mark.parametrize('order', ['root-first', 'child-first'])
def test_shared_eligible_worktree_is_removed_once_and_all_handoffs_archive(sandbox, order):
    root, directory = archive_test_repository(sandbox, 'linked')
    child = root / 'docs'
    child.mkdir()
    root_name, child_name = ('a-root', 'z-child') if order == 'root-first' else ('z-root', 'a-child')
    paths = [source(sandbox, name=root_name, directory=directory, loops=[]),
             source(sandbox, name=child_name, directory=child, loops=[]),
             source(sandbox, name='same-root', directory=directory, loops=[])]
    profile = act_profile(sandbox)
    _, data = report(sandbox, '--user-profile', str(profile))
    removed = [r for s in data['directories'].values() for r in s['worktrees_removed']]
    assert len(removed) == 1 and removed[0]['path'] == str(root)
    assert not root.exists()
    archived = [r for s in data['directories'].values() for r in s['handoffs_archived']]
    assert {r['path'] for r in archived} == {str(p) for p in paths}
    assert all(r['outcome'] == 'archived' for r in archived)
    assert not any(s['handoffs_kept'] or s['worktrees_kept'] for s in data['directories'].values())


def read_run(path):
    return json.loads(Path(path).read_text().split('```json\n', 1)[1].rsplit('\n```', 1)[0])


@pytest.mark.parametrize('days', [None, 2])
def test_retention_deletes_only_strictly_older_regular_archive_handoffs(sandbox, days, monkeypatch):
    spec = importlib.util.spec_from_file_location('retention_sweep', ENGINE)
    engine = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(engine)
    monkeypatch.setenv('HANDOFF_STATE_DIR', str(sandbox[1]))
    live = source(sandbox)
    archive = sandbox[1] / 'archive'
    archive.mkdir()
    for name, age in [('old.json', 3), ('boundary.json', 2), ('recent.json', 1), ('notes.txt', 3)]:
        target = archive / name
        target.write_bytes(live.read_bytes())
        os.utime(target, (2000000000 - age * 86400,) * 2)
    (archive / 'linked.json').symlink_to(live)
    nested = archive / 'nested'
    nested.mkdir()
    (nested / 'kept.json').write_bytes(live.read_bytes())
    before = outside_report_snapshot(sandbox)
    result = engine.execute_retention({'archive_retention_days': days},
        engine.datetime.fromtimestamp(2000000000, engine.timezone.utc))
    after = outside_report_snapshot(sandbox)
    changed = {k for k in before.keys() | after.keys() if before.get(k) != after.get(k)}
    assert changed == ({'handoffs/archive/old.json'} if days is not None else set())
    assert [r['path'] for r in result['items'] if r['outcome'] == 'deleted'] == (
        [str(archive / 'old.json')] if days is not None else [])


def test_retention_cli_reports_changes_and_does_not_run_during_watch(sandbox):
    path = source(sandbox)
    archive = sandbox[1] / 'archive'
    archive.mkdir()
    target = archive / 'old.json'
    target.write_bytes(path.read_bytes())
    os.utime(target, (1, 1))
    cfg = json.loads(sandbox[2].read_text())
    cfg['sweep']['archive_retention_days'] = 2
    sandbox[2].write_text(json.dumps(cfg))
    before = outside_report_snapshot(sandbox)
    report(sandbox)
    assert outside_report_snapshot(sandbox) == before
    done = command(sandbox, 'retention')
    result = read_run(done.stdout.strip())
    assert_readable_report(Path(done.stdout.strip()).read_text(), result)
    assert result['items'][0]['outcome'] == 'deleted'
    assert not target.exists() and path.exists()


@pytest.mark.parametrize('mode', ['watch-only', 'act'])
@pytest.mark.parametrize('subjects', ['sole-subdirectory', 'sibling-subdirectories'])
def test_subdirectory_handoffs_remove_the_containing_worktree_once(sandbox, mode, subjects):
    root, directory = archive_test_repository(sandbox, 'linked-subdirectory')
    paths = [source(sandbox, directory=directory, loops=[])]
    if subjects == 'sibling-subdirectories':
        sibling = root / 'other'
        sibling.mkdir()
        paths.append(source(sandbox, name='sibling', directory=sibling, loops=[]))
    profile = act_profile(sandbox)
    config = json.loads(sandbox[2].read_text())
    config['sweep']['mode'] = mode
    sandbox[2].write_text(json.dumps(config))
    before = outside_report_snapshot(sandbox)
    _, data = report(sandbox, '--user-profile', str(profile))
    removed = [r for section in data['directories'].values() for r in section['worktrees_removed']]
    assert removed and all(r['path'] == str(root) for r in removed)
    if mode == 'watch-only':
        assert outside_report_snapshot(sandbox) == before
        assert all(r['outcome'] == 'dry run' for r in removed)
    else:
        assert len(removed) == 1 and removed[0]['outcome'] == 'removed'
        assert removed[0]['checks']['plain_removal'] is True
        assert not root.exists()
        assert all(not path.exists() for path in paths)
        archived = [r for section in data['directories'].values() for r in section['handoffs_archived']]
        assert {r['path'] for r in archived} == {str(p) for p in paths}
        assert not any(section['worktrees_kept'] or section['handoffs_kept'] for section in data['directories'].values())
        branches = subprocess.run(['git', '-C', str(sandbox[0] / 'repo'), 'branch', '--list', 'feature'],
                                  capture_output=True, text=True, check=True)
        assert not branches.stdout


# Variations of the captured checkpoint structure reproduce the lint families
# recorded in the approved ticket; identities and paths stay sandbox-local.
@pytest.mark.parametrize('defect,reason', [
    ('process-identity', 'missing pid+started_at'),
    ('process-object', 'spawned_processes[0] not an object'),
    ('process-array', 'spawned_processes must be an array'),
    ('context-length', '.context is 601 chars'),
    ('unanchored', 'has no anchor'),
])
@pytest.mark.parametrize('act', [False, True])
def test_approved_lint_findings_warn_and_allow_sweeping(sandbox, defect, reason, act):
    path = source(sandbox)
    data = json.loads(path.read_text())
    if defect == 'process-identity':
        data['spawned_processes'] = [{}]
    elif defect == 'process-object':
        data['spawned_processes'] = ['redacted process']
    elif defect == 'process-array':
        data['spawned_processes'] = {}
    elif defect == 'context-length':
        data['resume']['open_loops'][0]['context'] = 'x' * 601
    else:
        data['resume']['open_loops'][0].pop('disposition')
    path.write_text(json.dumps(data))
    old = int(time.time()) - 5 * 86400
    os.utime(path, (old, old))
    args = decisions(sandbox, [{'rule': 'R6', 'reason': 'No stated outcome'}])
    if act:
        args += ['--user-profile', str(act_profile(sandbox))]

    text, run = report(sandbox, *args)

    assert not run['errors']
    section = run['directories'][str(sandbox[0])]
    warning, = section['handoff_warnings']
    assert warning['path'] == str(path)
    assert any(reason in message for message in warning['warnings'])
    assert reason in text.split('## Structured data')[0]
    assert section['handoffs_archived'][0]['path'] == str(path)
    assert section['handoffs_archived'][0]['outcome'] == ('archived' if act else 'dry run')
    assert path.exists() is not act


@pytest.mark.parametrize('defect,reason', [
    ('flat-v0', 'missing/invalid resume block'),
    ('flat-v2', 'schema_version 2 requires a subject block'),
    ('no-resume', 'missing/invalid resume block'),
    ('other', 'resume.open_loops must be an array'),
    ('mixed', 'resume.open_loops must be an array'),
])
def test_blocking_lint_keeps_source_with_reason(sandbox, defect, reason):
    path = source(sandbox)
    data = json.loads(path.read_text())
    if defect.startswith('flat'):
        data.update(data.pop('resume'))
        data.pop('subject')
        if defect == 'flat-v0':
            data.pop('schema_version')
    elif defect == 'no-resume':
        data.pop('resume')
    else:
        data['resume']['open_loops'] = {}
        if defect == 'mixed':
            data['spawned_processes'] = [{}]
    path.write_text(json.dumps(data))
    before = path.read_bytes()

    inspected = json.loads(command(sandbox, 'inspect', '--scope', 'all').stdout)

    assert not inspected['candidates']
    assert inspected['errors'][0]['path'] == str(path)
    assert reason in inspected['errors'][0]['reason']
    assert path.read_bytes() == before


def test_scope_excludes_other_directories_before_lint(sandbox):
    own = source(sandbox, name='own', directory=sandbox[0] / 'own')
    other = source(sandbox, name='other', directory=sandbox[0] / 'other')
    data = json.loads(other.read_text())
    data.pop('resume')
    other.write_text(json.dumps(data))

    inspected = json.loads(command(sandbox, 'inspect', '--scope', str(sandbox[0] / 'own')).stdout)

    assert [row['path'] for row in inspected['candidates']] == [str(own)]
    assert not inspected['errors']


@pytest.mark.parametrize('message', [
    'a future lint rule',
    'spawned_processes[0] future identity restriction',
    'open_loops[0].context future restriction',
    'open_loops[0] has no anchor future restriction',
])
def test_future_lint_messages_block_even_in_warn_only_fields(sandbox, monkeypatch, message):
    path = source(sandbox)
    spec = importlib.util.spec_from_file_location('future_lint_sweep', ENGINE)
    engine = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(engine)
    for key, value in sandbox[3].items():
        monkeypatch.setenv(key, value)
    lint = engine.handoff.lint_data

    def future_lint(data):
        errors, warnings = lint(data)
        return errors + [message], warnings

    monkeypatch.setattr(engine.handoff, 'lint_data', future_lint)
    discovery = engine.discover('all', engine.settings(), engine.datetime.now(engine.timezone.utc))

    assert not discovery['candidates']
    assert discovery['errors'] == [{'path': str(path), 'reason': message}]
    assert path.exists()


@pytest.mark.parametrize('mode', ['watch-only', 'act'])
def test_reports_have_readable_entries_and_unchanged_json(sandbox, mode):
    source(sandbox)
    profile = act_profile(sandbox) if mode == 'act' else bound_profile(sandbox)
    text, data = report(sandbox, *decisions(sandbox, [new_work()]),
                        '--user-profile', str(profile))
    assert_readable_report(text, data)
    body = text.split('## Structured data')[0]
    assert "'session_ids':" not in body
    assert 'Destination: new ticket' in body
    assert 'Rule: R5' in body
