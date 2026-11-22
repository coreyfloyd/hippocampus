"""Session items saved at one checkpoint survive later writes until the wrap settles them."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ['claude', 'codex']


def command(tmp_path, session, script, *args, payload=None, tool='codex'):
    sessions = tmp_path / 'codex/sessions'
    sessions.mkdir(parents=True, exist_ok=True)
    (sessions / f'{session}.jsonl').write_text(json.dumps({'type': 'session_meta',
        'payload': {'id': session, 'source': 'cli'}}) + '\n')
    env = os.environ | {'HANDOFF_LEDGER_DIR': str(tmp_path / 'ledger'),
        'HANDOFF_PATH': str(tmp_path / f'{session}.json'),
        'HANDOFF_COMPACT_STATE_DIR': str(tmp_path / 'compact'),
        'CODEX_HOME': str(tmp_path / 'codex'),
        'HIPPOCAMPUS_CONFIG': str(tmp_path / 'config.json'),
        'CHECKLIST_USER_PROFILE': str(tmp_path / 'profile.md'),
        'CLAUDE_CODE_ENTRYPOINT': 'cli', 'HIPPOCAMPUS_HARNESS': tool,
        'CODEX_THREAD_ID': session if tool == 'codex' else '',
        'CLAUDE_SESSION_ID': session, 'CLAUDE_CODE_SESSION_ID': session}
    (tmp_path / 'profile.md').write_text('```checklist-profile\n{"name":"user"}\n```')
    return subprocess.run([sys.executable, str(ROOT / script), *map(str, args)],
        input=json.dumps(payload) if payload is not None else None,
        text=True, capture_output=True, env=env, cwd=tmp_path)


def handoff(tmp_path, session):
    return json.loads((tmp_path / f'{session}.json').read_text())


def checkpoint(tmp_path, session, tool, resume=None, items=None, trigger='checkpoint'):
    payload = {'resume': {'headline': 'Work', 'next_action': 'Continue', 'open_loops': [],
                          'session_summary': f'Worked in {session}.', **(resume or {})},
               'spawned_processes': []}
    if items is not None:
        payload['session_items'] = items
    result = command(tmp_path, session, 'scripts/lib/handoff.py', 'checkpoint',
                     '--cwd', tmp_path, '--session-id', session, '--trigger', trigger,
                     payload=payload, tool=tool)
    assert result.returncode == 0, result.stderr
    return handoff(tmp_path, session)


def lesson(session='A', **changes):
    return {'type': 'lesson', 'session_id': session, 'produced_at': '2026-11-05T12:00:00Z',
            'disposition': 'route through improve-harness',
            'context': ('Target: AGENTS.md, Verify before handing off. Proposed text: run the full '
                        'suite before reporting ready. Evidence: a generator reported ready with '
                        'two failing tests.'), **changes}


def lessons(data):
    return [loop for loop in data['resume']['open_loops'] if loop.get('type') == 'lesson']


@pytest.mark.parametrize('tool', TOOLS)
def test_a_lesson_survives_a_checkpoint_that_does_not_resupply_it(tmp_path, tool):
    checkpoint(tmp_path, 'A', tool, items=[lesson()])
    second = checkpoint(tmp_path, 'A', tool)
    assert lessons(second) == [lesson()]


@pytest.mark.parametrize('tool', TOOLS)
@pytest.mark.parametrize('where', ['open_loops', 'session_items'])
def test_a_resupplied_lesson_is_held_once(tmp_path, tool, where):
    checkpoint(tmp_path, 'A', tool, items=[lesson()])
    if where == 'open_loops':
        second = checkpoint(tmp_path, 'A', tool, resume={'open_loops': [lesson()]})
    else:
        second = checkpoint(tmp_path, 'A', tool, items=[lesson()])
    assert lessons(second) == [lesson()]
    third = checkpoint(tmp_path, 'A', tool, resume={'open_loops': [lesson()]}, items=[lesson()])
    assert lessons(third) == [lesson()]


@pytest.mark.parametrize('tool', TOOLS)
def test_a_pre_compaction_write_keeps_the_lesson(tmp_path, tool):
    checkpoint(tmp_path, 'A', tool, items=[lesson()])
    # The compaction writer re-reads the file; the ledger keeps the lesson even without it.
    (tmp_path / 'A.json').unlink()
    result = command(tmp_path, 'A', 'scripts/lib/handoff.py', 'pre-compact', tool=tool,
                     payload={'session_id': 'A', 'cwd': str(tmp_path), 'trigger': 'auto',
                              'transcript_path': str(tmp_path / 'codex/sessions/A.jsonl')})
    assert result.returncode == 0, result.stderr
    assert 'COMPACTION IMMINENT' in result.stdout
    data = handoff(tmp_path, 'A')
    assert data['trigger'] == 'pre-compact'
    assert lessons(data) == [lesson()]


@pytest.mark.parametrize('tool', TOOLS)
def test_the_stop_skeleton_keeps_the_lesson_and_adds_no_history(tmp_path, tool):
    first = checkpoint(tmp_path, 'A', tool, items=[lesson()])
    (tmp_path / 'A.json').unlink()
    result = command(tmp_path, 'A', 'scripts/lib/handoff.py', 'guard-decide', tool=tool,
                     payload={'session_id': 'A', 'cwd': str(tmp_path),
                              'transcript_path': str(tmp_path / 'codex/sessions/A.jsonl')})
    assert result.returncode == 0 and result.stdout == '', result.stderr
    skeleton = handoff(tmp_path, 'A')
    assert skeleton['skeleton'] is True
    assert lessons(skeleton) == [lesson()]
    assert skeleton['resume']['session_history'] == first['resume']['session_history']


def wrap_filing(tmp_path, session, tool, *outcomes):
    filing = tmp_path / 'filing.json'
    filing.write_text(json.dumps(list(outcomes)))
    result = command(tmp_path, session, 'scripts/lib/checklist.py', 'file',
                     '--handoff', tmp_path / f'{session}.json', '--filing', filing, tool=tool)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize('tool', TOOLS)
@pytest.mark.parametrize('outcome', [
    {'index': 0, 'rule': 'R6', 'status': 'dropped', 'reason': 'Already in AGENTS.md.'},
    {'index': 0, 'rule': 'R4', 'status': 'filed', 'destination': 'AGENTS.md, Verify before handing off'},
])
def test_a_lesson_the_wrap_files_or_drops_is_not_restored(tmp_path, tool, outcome):
    checkpoint(tmp_path, 'A', tool, items=[lesson()])
    filed = wrap_filing(tmp_path, 'A', tool, outcome)
    assert filed['resume']['open_loops'] == []
    later = checkpoint(tmp_path, 'A', tool)
    assert lessons(later) == []


@pytest.mark.parametrize('tool', TOOLS)
def test_a_lesson_the_wrap_keeps_is_still_restored(tmp_path, tool):
    checkpoint(tmp_path, 'A', tool, items=[lesson()])
    kept = wrap_filing(tmp_path, 'A', tool, {'index': 0, 'rule': 'R4', 'status': 'declined',
                                             'reason': 'The user wants to discuss it first.'})
    assert lessons(kept) == [lesson()]
    assert lessons(checkpoint(tmp_path, 'A', tool)) == [lesson()]


@pytest.mark.parametrize('tool', TOOLS)
def test_a_recorded_lesson_is_neither_retained_nor_restored(tmp_path, tool):
    first = checkpoint(tmp_path, 'A', tool, items=[lesson(recorded=True)])
    assert lessons(first) == []
    assert lessons(checkpoint(tmp_path, 'A', tool)) == []
    # Reporting a retained lesson as recorded settles it.
    checkpoint(tmp_path, 'A', tool, items=[lesson(context='Second lesson.')])
    checkpoint(tmp_path, 'A', tool, items=[lesson(context='Second lesson.', recorded=True)])
    assert lessons(checkpoint(tmp_path, 'A', tool)) == []


@pytest.mark.parametrize('tool', TOOLS)
def test_pickup_shows_the_lesson_and_the_successor_carries_its_identity(tmp_path, tool):
    checkpoint(tmp_path, 'A', tool, items=[lesson()])
    checkpoint(tmp_path, 'A', tool)
    result = command(tmp_path, 'B', 'skills/pickup/scripts/pickup.py', '--handoff',
                     tmp_path / 'A.json', tool=tool)
    assert result.returncode == 0, result.stderr + result.stdout
    report = json.loads(result.stdout)
    assert 'error' not in report, report
    assert any(json.dumps(lesson(), ensure_ascii=False) in row['line'] for row in report['briefing'])
    (tmp_path / 'A.json').unlink()
    successor = checkpoint(tmp_path, 'B', tool)
    assert lessons(successor) == [lesson()]
    assert lessons(checkpoint(tmp_path, 'B', tool)) == [lesson()]
    # The successor's wrap settles the carried lesson in its own ledger.
    wrap_filing(tmp_path, 'B', tool, {'index': 0, 'rule': 'R6', 'status': 'dropped',
                                      'reason': 'Already in AGENTS.md.'})
    assert lessons(checkpoint(tmp_path, 'B', tool)) == []


@pytest.mark.parametrize('tool', TOOLS)
def test_another_sessions_items_are_never_restored_without_pickup(tmp_path, tool):
    checkpoint(tmp_path, 'A', tool, items=[lesson()])
    other = checkpoint(tmp_path, 'B', tool, items=[lesson()])
    # B was handed A's lesson without a pickup: it is written once, never retained.
    assert lessons(other) == [lesson()]
    assert lessons(checkpoint(tmp_path, 'B', tool)) == []
    assert lessons(checkpoint(tmp_path, 'A', tool)) == [lesson()]


@pytest.mark.parametrize('tool', TOOLS)
def test_the_successors_wrap_plan_gives_the_lessons_step_every_unsettled_lesson(tmp_path, tool):
    checkpoint(tmp_path, 'A', tool, items=[lesson()])
    result = command(tmp_path, 'B', 'skills/pickup/scripts/pickup.py', '--handoff',
                     tmp_path / 'A.json', tool=tool)
    assert result.returncode == 0, result.stderr + result.stdout
    own = lesson('B', context='Target: README.md, Install. Proposed text: name the state '
                              'directory. Evidence: a user asked where handoffs live.')
    checkpoint(tmp_path, 'B', tool, items=[own])
    planned = command(tmp_path, 'B', 'scripts/lib/checklist.py', 'plan', '--session-id', 'B', tool=tool)
    assert planned.returncode == 0, planned.stderr
    plan = json.loads(planned.stdout)
    assert lessons(plan['handoff']) == [lesson(), own]
    step = next(step for step in plan['steps'] if step['id'] == 'lessons')
    assert [entry['item'] for entry in step.get('carried_items', [])] == [lesson(), own]


# The settled-identity store: a settled item is never carried again by any session on the machine.

TERMINAL = ['captured', 'dropped', 'filed', 'applied', 'recorded', 'done']


def pickup(tmp_path, successor, source, tool):
    result = command(tmp_path, successor, 'skills/pickup/scripts/pickup.py', '--handoff',
                     tmp_path / f'{source}.json', tool=tool)
    assert result.returncode == 0, result.stderr + result.stdout
    assert 'error' not in json.loads(result.stdout)


def receipt(item, disposition='dropped', reason='Already written in its destination.', **changes):
    return {'identity': {'session_id': item['session_id'], 'produced_at': item['produced_at'],
                         'type': item['type'], 'text': item['context']},
            'disposition': disposition, 'reason': reason, 'destination': None,
            'settled_at': '2026-11-22T12:00:00+00:00', 'settled_by': 'catch-up', **changes}


def settle_identity(tmp_path, rows, tool, name='receipts.jsonl'):
    path = tmp_path / name
    path.write_text(''.join(row if isinstance(row, str) else json.dumps(row) + '\n' for row in rows))
    result = command(tmp_path, 'catch-up', 'scripts/lib/handoff.py', 'settle-identity',
                     '--receipts', path, tool=tool)
    return result.returncode, json.loads(result.stdout)


def store(tmp_path):
    path = tmp_path / 'ledger/settled-identities.jsonl'
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def drop_at_wrap(tmp_path, session, item, tool):
    loops = handoff(tmp_path, session)['resume']['open_loops']
    # The wrap drops this item and keeps every other one.
    wrap_filing(tmp_path, session, tool, *(
        {'index': index, 'rule': 'R6', 'status': 'dropped', 'reason': 'Already in AGENTS.md.'} if loop == item
        else {'index': index, 'rule': 'R4', 'status': 'declined', 'reason': 'The user wants to discuss it first.'}
        for index, loop in enumerate(loops)))


@pytest.mark.parametrize('tool', TOOLS)
def test_a_predecessor_never_restores_an_item_its_successor_settled(tmp_path, tool):
    checkpoint(tmp_path, 'A', tool, items=[lesson()])
    pickup(tmp_path, 'B', 'A', tool)
    checkpoint(tmp_path, 'B', tool)
    drop_at_wrap(tmp_path, 'B', lesson(), tool)
    assert lessons(checkpoint(tmp_path, 'A', tool)) == []
    # Neither the predecessor's agent re-supplying it nor its ledger brings it back.
    assert lessons(checkpoint(tmp_path, 'A', tool, items=[lesson()])) == []
    assert lessons(checkpoint(tmp_path, 'A', tool, resume={'open_loops': [lesson()]})) == []
    assert lessons(checkpoint(tmp_path, 'B', tool)) == []
    assert [row['settled_by'] for row in store(tmp_path)] == ['B']


@pytest.mark.parametrize('tool', TOOLS)
@pytest.mark.parametrize('field', ['disposition', 'status'])
@pytest.mark.parametrize('value', TERMINAL)
def test_an_item_with_a_terminal_disposition_is_never_carried_and_says_so(tmp_path, tool, field, value):
    settled = lesson(**{field: value})
    result = command(tmp_path, 'A', 'scripts/lib/handoff.py', 'checkpoint', '--cwd', tmp_path,
                     '--session-id', 'A', tool=tool, payload={
                         'resume': {'headline': 'Work', 'next_action': 'Continue', 'open_loops': [],
                                    'session_summary': 'Worked in A.'},
                         'spawned_processes': [], 'session_items': [settled]})
    assert result.returncode == 0, result.stderr
    assert 'Closed 1 carried item whose disposition or status was terminal' in result.stdout
    assert lessons(handoff(tmp_path, 'A')) == []
    row, = store(tmp_path)
    assert (row['disposition'], row['settled_by']) == (value, 'A')
    assert row['reason'] == f"carried with {field} '{value}'; no filing step in this session settled it"
    assert lessons(checkpoint(tmp_path, 'A', tool, resume={'open_loops': [settled]})) == []


@pytest.mark.parametrize('tool', TOOLS)
def test_pickup_closes_and_reports_a_carried_terminal_item(tmp_path, tool):
    checkpoint(tmp_path, 'A', tool)
    settled = lesson(disposition='done')
    data = handoff(tmp_path, 'A')
    data['resume']['open_loops'].append(settled)
    (tmp_path / 'A.json').write_text(json.dumps(data))
    result = command(tmp_path, 'B', 'skills/pickup/scripts/pickup.py', '--handoff', tmp_path / 'A.json', tool=tool)
    assert result.returncode == 0, result.stderr + result.stdout
    assert json.loads(result.stdout)['terminal_closed'] == 1
    assert lessons(checkpoint(tmp_path, 'B', tool)) == []
    row, = store(tmp_path)
    assert (row['disposition'], row['settled_by']) == ('done', 'B')
    assert row['reason'] == "carried with disposition 'done'; no filing step in this session settled it"


@pytest.mark.parametrize('tool', TOOLS)
def test_a_receipt_closes_only_the_item_of_its_type(tmp_path, tool):
    commitment = lesson(type='commitment')
    checkpoint(tmp_path, 'A', tool, items=[lesson(), commitment])
    assert settle_identity(tmp_path, [receipt(lesson())], tool)[0] == 0
    data = checkpoint(tmp_path, 'A', tool)
    assert lessons(data) == [] and commitment in data['resume']['open_loops']


@pytest.mark.parametrize('tool', TOOLS)
def test_an_unsettled_copy_in_the_same_write_keeps_the_item_open(tmp_path, tool):
    first = checkpoint(tmp_path, 'A', tool, items=[lesson(), lesson(recorded=True)])
    assert lessons(first) == [lesson()] and store(tmp_path) == []
    # A recorded copy alone settles it, and that write's handoff no longer carries it.
    assert lessons(checkpoint(tmp_path, 'A', tool, items=[lesson(recorded=True)])) == []
    assert [row['disposition'] for row in store(tmp_path)] == ['recorded']


@pytest.mark.parametrize('tool', TOOLS)
def test_an_artifact_gets_no_receipt(tmp_path, tool):
    artifact = {'type': 'artifact', 'context': 'Published artifact', 'location': 'https://example.com/a',
                'disposition': 'keep', 'session_id': 'A', 'produced_at': '2026-11-05T12:00:00Z'}
    checkpoint(tmp_path, 'A', tool, resume={'open_loops': [artifact]})
    wrap_filing(tmp_path, 'A', tool, {'index': 0, 'rule': 'R6', 'status': 'dropped', 'reason': 'Removed.'})
    assert store(tmp_path) == []


@pytest.mark.parametrize('tool', TOOLS)
def test_a_receipt_from_settle_identity_closes_the_item_for_every_session(tmp_path, tool):
    checkpoint(tmp_path, 'A', tool, items=[lesson()])
    assert settle_identity(tmp_path, [receipt(lesson())], tool) == (0, {'written': 1, 'skipped': 0, 'invalid': []})
    assert lessons(checkpoint(tmp_path, 'A', tool)) == []
    pickup(tmp_path, 'B', 'A', tool)
    assert lessons(checkpoint(tmp_path, 'B', tool)) == []


@pytest.mark.parametrize('tool', TOOLS)
def test_a_wrap_settlement_closes_the_item_for_a_later_pickup_in_another_session(tmp_path, tool):
    checkpoint(tmp_path, 'A', tool, items=[lesson()])
    stale = handoff(tmp_path, 'A')
    drop_at_wrap(tmp_path, 'A', lesson(), tool)
    (tmp_path / 'A.json').write_text(json.dumps(stale))  # A later reader finds the older handoff.
    pickup(tmp_path, 'C', 'A', tool)
    assert lessons(checkpoint(tmp_path, 'C', tool)) == []
    assert [(row['disposition'], row['settled_by'], row['identity']['type'])
            for row in store(tmp_path)] == [('dropped', 'A', 'lesson')]


@pytest.mark.parametrize('tool', TOOLS)
def test_a_chain_of_seven_handoffs_never_brings_a_settled_item_back(tmp_path, tool):
    sessions = [f'S{n}' for n in range(7)]
    items = [lesson('S0', context=f'Lesson {n}: run the affected tests before reporting.') for n in range(7)]
    checkpoint(tmp_path, 'S0', tool, items=items)
    settled = []
    for link, (previous, session) in enumerate(zip(sessions, sessions[1:]), 1):
        pickup(tmp_path, session, previous, tool)
        checkpoint(tmp_path, session, tool)
        item = items[link - 1]
        # Each link settles one item a different way.
        if link % 3 == 1:
            drop_at_wrap(tmp_path, session, item, tool)
        elif link % 3 == 2:
            assert settle_identity(tmp_path, [receipt(item)], tool)[0] == 0
        else:
            checkpoint(tmp_path, session, tool, items=[dict(item, disposition='filed')])
        settled.append(item)
        for earlier in sessions[:link + 1]:
            carried = lessons(checkpoint(tmp_path, earlier, tool))
            assert not [item for item in settled if item in carried], (link, earlier)
    assert lessons(handoff(tmp_path, 'S6')) == [items[6]]
    assert len(store(tmp_path)) == 6


@pytest.mark.parametrize('tool', TOOLS)
def test_settle_identity_retry_is_idempotent(tmp_path, tool):
    rows = [receipt(lesson(context=f'Lesson {n}.')) for n in range(3)]
    assert settle_identity(tmp_path, rows, tool) == (0, {'written': 3, 'skipped': 0, 'invalid': []})
    assert settle_identity(tmp_path, rows, tool) == (0, {'written': 0, 'skipped': 3, 'invalid': []})
    assert len(store(tmp_path)) == 3


@pytest.mark.parametrize('tool', TOOLS)
@pytest.mark.parametrize('bad', [
    'not json\n',
    receipt(lesson(), reason=' '),
    receipt(lesson(), reason='two\nlines'),
    receipt(lesson(), disposition='carry'),
    receipt(lesson(), settled_at='2026-11-22T12:00:00'),
    receipt(lesson(produced_at='2026-11-05T12:00:00')),
    receipt(lesson(type='artifact')),
    {**receipt(lesson()), 'identity': {k: v for k, v in receipt(lesson())['identity'].items() if k != 'type'}},
    receipt(lesson(), settled_by=''),
    receipt(lesson(), destination=3),
    {k: v for k, v in receipt(lesson()).items() if k != 'reason'},
])
def test_settle_identity_refuses_an_invalid_row_by_line_number(tmp_path, tool, bad):
    good = [receipt(lesson(context='First.')), receipt(lesson(context='Third.'))]
    code, summary = settle_identity(tmp_path, [good[0], bad, good[1]], tool)
    assert code == 1
    assert summary['written'] == 2 and [row['line'] for row in summary['invalid']] == [2]
    assert [row['identity']['text'] for row in store(tmp_path)] == ['First.', 'Third.']


def test_concurrent_settle_identity_appends_do_not_interleave(tmp_path):
    batches = [[receipt(lesson(context=f'Writer {w} lesson {n}. ' + 'x' * 400)) for n in range(40)]
               for w in range(8)]
    shared = receipt(lesson(context='Every writer settles this one.'))
    env = os.environ | {'HANDOFF_LEDGER_DIR': str(tmp_path / 'ledger'),
                        'HIPPOCAMPUS_CONFIG': str(tmp_path / 'config.json')}
    processes = []
    for w, batch in enumerate(batches):
        path = tmp_path / f'batch-{w}.jsonl'
        path.write_text(''.join(json.dumps(row) + '\n' for row in [shared, *batch]))
        processes.append(subprocess.Popen([sys.executable, str(ROOT / 'scripts/lib/handoff.py'),
                                           'settle-identity', '--receipts', str(path)],
                                          env=env, stdout=subprocess.PIPE, text=True))
    summaries = [json.loads(process.communicate()[0]) for process in processes]
    assert all(process.returncode == 0 for process in processes)
    assert sum(summary['written'] for summary in summaries) == 8 * 40 + 1
    texts = [row['identity']['text'] for row in store(tmp_path)]
    assert sorted(texts) == sorted([shared['identity']['text'], *(row['identity']['text']
                                                                   for batch in batches for row in batch)])


def test_a_torn_last_row_never_swallows_the_next_receipt(tmp_path):
    path = tmp_path / 'ledger/settled-identities.jsonl'
    path.parent.mkdir()
    path.write_text(json.dumps(receipt(lesson(context='First.'))) + '\n{"identity": {"sess')
    assert settle_identity(tmp_path, [receipt(lesson(context='Second.'))], 'codex') == (
        0, {'written': 1, 'skipped': 0, 'invalid': []})
    lines = path.read_text().splitlines()
    assert json.loads(lines[-1])['identity']['text'] == 'Second.'
    assert lessons(checkpoint(tmp_path, 'A', 'codex', items=[lesson(context='Second.')])) == []


@pytest.mark.parametrize('tool', TOOLS)
@pytest.mark.parametrize('slot, disposition', [('lessons', 'applied'), ('knowledge', 'captured')])
def test_settle_records_the_slots_disposition_once_the_handoff_is_saved(tmp_path, tool, slot, disposition):
    item = lesson() if slot == 'lessons' else lesson(type='knowledge')
    checkpoint(tmp_path, 'A', tool, items=[item])
    receipts = tmp_path / 'acks.json'
    receipts.write_text(json.dumps({slot: [0]}))
    settled = command(tmp_path, 'A', 'scripts/lib/checklist.py', 'settle', '--handoff', tmp_path / 'A.json',
                      '--receipts', receipts, tool=tool)
    assert settled.returncode == 0, settled.stderr
    assert store(tmp_path) == []  # Nothing is closed machine-wide before the handoff is saved.
    payload = json.loads(settled.stdout)
    saved = command(tmp_path, 'A', 'scripts/lib/handoff.py', 'checkpoint', '--cwd', tmp_path,
                    '--session-id', 'A', tool=tool, payload=dict(payload, spawned_processes=[]))
    assert saved.returncode == 0, saved.stderr
    assert [(row['disposition'], row['identity']['type']) for row in store(tmp_path)] == [(disposition, item['type'])]
    assert item not in handoff(tmp_path, 'A')['resume']['open_loops']
