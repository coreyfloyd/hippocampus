"""Pickup owns chain transfer; later commands need only the successor ledger."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def command(tmp_path, session, script, *args, payload=None, tool='codex'):
    sessions = tmp_path / 'codex/sessions'
    sessions.mkdir(parents=True, exist_ok=True)
    (sessions / f'{session}.jsonl').write_text(json.dumps({'type': 'session_meta',
        'payload': {'id': session, 'source': 'cli'}}) + '\n')
    env = os.environ | {'HANDOFF_LEDGER_DIR': str(tmp_path / 'ledger'),
        'HANDOFF_PATH': str(tmp_path / f'{session}.json'),
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


def checkpoint(tmp_path, session, resume=None, trigger='checkpoint'):
    result = command(tmp_path, session, 'scripts/lib/handoff.py', 'checkpoint',
        '--cwd', tmp_path, '--session-id', session, '--trigger', trigger,
        payload={'resume': {'headline': 'Work', 'next_action': 'Continue', 'open_loops': [],
            'session_summary': f'Implemented {session}.', **(resume or {})}})
    assert result.returncode == 0, result.stderr
    return json.loads((tmp_path / f'{session}.json').read_text())


def pickup(tmp_path, session, path, tool='codex'):
    result = command(tmp_path, session, 'skills/pickup/scripts/pickup.py', '--handoff', path, tool=tool)
    assert result.returncode == 0, result.stderr + result.stdout
    report = json.loads(result.stdout)
    assert 'error' not in report, report
    return report


def facts():
    return {'touched_tickets': ['https://github.com/example/project/issues/7'],
        'close_outcomes': [{'kind': 'epic', 'title': 'Records', 'state': 'closed',
            'done': 1, 'total': 1, 'triggering_ticket': 'https://github.com/example/project/issues/7',
            'produced_at': '2026-11-01T12:00:00Z'}]}


@pytest.mark.parametrize('tool', ['claude', 'codex'])
@pytest.mark.parametrize('skeleton', [False, True])
def test_pickup_copies_chain_immediately_and_source_can_disappear(tmp_path, tool, skeleton):
    a = checkpoint(tmp_path, 'A', facts())
    if skeleton:
        a = checkpoint(tmp_path, 'A', trigger='stop')
    pickup(tmp_path, 'B', tmp_path / 'A.json', tool)
    ledger = (tmp_path / 'ledger/session-touched-paths.B.jsonl').read_text()
    assert 'Implemented A.' in ledger
    assert 'Records' in ledger
    assert 'resumed_chain' in ledger
    (tmp_path / 'A.json').unlink()
    planned = command(tmp_path, 'B', 'scripts/lib/checklist.py', 'plan',
                      '--handoff', tmp_path / 'A.json', '--session-id', 'B', tool=tool)
    assert planned.returncode == 0, planned.stderr
    planned_handoff = json.loads(planned.stdout)['handoff']
    assert planned_handoff['subject']['session_id'] == 'B'
    assert planned_handoff['resume']['close_outcomes'] == facts()['close_outcomes']
    automatic = command(tmp_path, 'B', 'scripts/lib/checklist.py', 'plan', tool=tool)
    assert json.loads(automatic.stdout)['handoff'] == planned_handoff
    b = checkpoint(tmp_path, 'B')
    assert a['resume']['session_history'][0] in b['resume']['session_history']
    assert b['resume']['close_outcomes'] == facts()['close_outcomes']
    assert b['resume']['touched_tickets'] == facts()['touched_tickets']
    b_ticket = 'https://github.com/example/project/issues/8'
    b_outcome = dict(facts()['close_outcomes'][0], title='Follow-up', triggering_ticket=b_ticket)
    b = checkpoint(tmp_path, 'B', {'close_outcomes': [b_outcome], 'touched_tickets': [b_ticket]})
    pickup(tmp_path, 'C', tmp_path / 'B.json', tool)
    (tmp_path / 'B.json').unlink()
    c = checkpoint(tmp_path, 'C')
    assert c['resume']['session_history'][:-1] == b['resume']['session_history']
    assert c['resume']['close_outcomes'] == b['resume']['close_outcomes']
    assert len(c['resume']['close_outcomes']) == 2
    assert c['resume']['touched_tickets'] == b['resume']['touched_tickets']
    chain = c['resume']['resumed_chain']
    assert [row['session_id'] for row in chain] == ['A', 'B']
    assert chain[0]['handoff'] == str(tmp_path / 'A.json')
    assert chain[0]['resumed_at']


def test_plan_refuses_disagreeing_handoff_even_with_same_session(tmp_path):
    checkpoint(tmp_path, 'A')
    pickup(tmp_path, 'B', tmp_path / 'A.json')
    other = tmp_path / 'other.json'
    other.write_bytes((tmp_path / 'A.json').read_bytes())
    result = command(tmp_path, 'B', 'scripts/lib/checklist.py', 'plan', '--handoff', other)
    assert result.returncode != 0
    assert 'resumed handoff' in result.stderr
    assert str(other) in result.stderr and 'A.json' in result.stderr


def test_wrap_names_every_missing_carried_fact(tmp_path):
    a = checkpoint(tmp_path, 'A', facts())
    pickup(tmp_path, 'B', tmp_path / 'A.json')
    b = checkpoint(tmp_path, 'B')
    b['resume']['session_history'] = b['resume']['session_history'][-1:]
    b['resume']['close_outcomes'] = []
    (tmp_path / 'B.json').write_text(json.dumps(b))
    result = command(tmp_path, 'B', 'scripts/lib/checklist.py', 'wrap-check',
                     '--written-handoff', tmp_path / 'B.json')
    assert result.returncode == 1
    assert 'missing history entry' in result.stderr
    assert a['resume']['session_history'][0]['summary'] in result.stderr
    assert 'missing close outcome' in result.stderr and 'Records' in result.stderr


def test_brief_or_pasted_payload_without_pickup_does_not_join_chain(tmp_path):
    a = checkpoint(tmp_path, 'A', facts())
    b = checkpoint(tmp_path, 'B', a['resume'])
    assert all(row['session_id'] == 'B' for row in b['resume']['session_history'])
    assert b['resume'].get('resumed_chain', []) == []


def test_repeat_pickup_does_not_duplicate_chain(tmp_path):
    checkpoint(tmp_path, 'A', facts())
    pickup(tmp_path, 'B', tmp_path / 'A.json')
    pickup(tmp_path, 'B', tmp_path / 'A.json')
    b = checkpoint(tmp_path, 'B')
    assert len(b['resume']['resumed_chain']) == 1
    assert len(b['resume']['session_history']) == 2


def test_successor_of_stop_before_any_checkpoint(tmp_path):
    a = checkpoint(tmp_path, 'A', trigger='stop')
    assert a['resume']['session_history'] == []
    pickup(tmp_path, 'B', tmp_path / 'A.json')
    (tmp_path / 'A.json').unlink()
    b = checkpoint(tmp_path, 'B')
    assert [row['session_id'] for row in b['resume']['session_history']] == ['B']
    assert b['resume']['resumed_chain'][0]['skeleton'] is True
    assert b['resume']['resumed_chain'][0]['written_at'] == a['written_at']


@pytest.mark.parametrize('field,value,remove', [
    ('written_at', None, True),
    ('written_at', None, False),
    ('written_at', '', False),
    ('written_at', 42, False),
    ('written_at', 'yesterday', False),
    ('written_at', '2026-11-01T12:00:00', False),
    ('session_id', None, True),
    ('session_id', None, False),
    ('session_id', '', False),
    ('session_id', '   ', False),
])
@pytest.mark.parametrize('tool', ['claude', 'codex'])
def test_pickup_names_invalid_skeleton_metadata_without_copying(tmp_path, field, value, remove, tool):
    skeleton = checkpoint(tmp_path, 'A', trigger='stop')
    target = skeleton['subject'] if field == 'session_id' else skeleton
    if remove:
        target.pop(field)
    else:
        target[field] = value
    path = tmp_path / 'A.json'
    path.write_text(json.dumps(skeleton))
    lint = command(tmp_path, 'B', 'scripts/lib/handoff.py', 'lint', path, tool=tool)
    assert lint.returncode == 1
    assert field in lint.stdout
    result = command(tmp_path, 'B', 'skills/pickup/scripts/pickup.py', '--handoff', path, tool=tool)
    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report['error'] == 'chain_copy_failed'
    assert field in report['message']
    assert 'KeyError' not in result.stderr
    assert not (tmp_path / 'ledger/session-touched-paths.B.jsonl').exists()


@pytest.mark.parametrize('tool', ['claude', 'codex'])
def test_stop_guard_skeleton_has_valid_time_and_can_be_copied(tmp_path, tool):
    path = tmp_path / 'A.json'
    guard = command(tmp_path, 'A', 'scripts/lib/handoff.py', 'guard-decide', '--path', path,
                    payload={'session_id': 'A', 'cwd': str(tmp_path)}, tool=tool)
    assert guard.returncode == 0, guard.stderr
    skeleton = json.loads(path.read_text())
    assert skeleton['skeleton'] is True
    lint = command(tmp_path, 'A', 'scripts/lib/handoff.py', 'lint', path, tool=tool)
    assert lint.returncode == 0, lint.stdout
    pickup(tmp_path, 'B', path, tool)
    successor = checkpoint(tmp_path, 'B')
    assert successor['resume']['resumed_chain'][0]['written_at'] == skeleton['written_at']


def test_pickup_refuses_lint_valid_shape_without_subject_as_unsupported_schema(tmp_path):
    path = tmp_path / 'legacy.json'
    path.write_text(json.dumps({'schema_version': 1, 'written_at': '2026-11-01T12:00:00Z',
                               'resume': {'headline': 'Work', 'open_loops': []}}))
    lint = command(tmp_path, 'B', 'scripts/lib/handoff.py', 'lint', path)
    assert lint.returncode == 0, lint.stdout
    result = command(tmp_path, 'B', 'skills/pickup/scripts/pickup.py', '--handoff', path)
    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report['error'] == 'invalid_handoff'
    assert 'schema-v2' in report['message']
    assert not (tmp_path / 'ledger/session-touched-paths.B.jsonl').exists()
