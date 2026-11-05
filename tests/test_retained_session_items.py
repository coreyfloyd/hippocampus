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


def wrap_filing(tmp_path, session, tool, outcome):
    filing = tmp_path / 'filing.json'
    filing.write_text(json.dumps([outcome]))
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
