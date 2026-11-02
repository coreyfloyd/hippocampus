"""Public command contracts for read-only record output and user bindings."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / 'scripts/lib/record_read.py'
COMPOSER = ROOT / 'scripts/lib/checklist.py'


def validate(payload, *args):
    return subprocess.run([sys.executable, str(VALIDATOR), *args],
                          input=payload if isinstance(payload, str) else json.dumps(payload),
                          text=True, capture_output=True)


def row(kind):
    item = dict(reference='work:17', title='Carry the work', state='active', link='https://example.org/work/17')
    if kind == 'ticket_status':
        item['latest_progress'] = 'Contract approved'
    return item


@pytest.mark.parametrize('kind', ['ticket_status', 'commitments'])
@pytest.mark.parametrize('empty', [False, True])
def test_valid_responses(kind, empty):
    result = validate(dict(kind=kind, rows=[] if empty else [row(kind)]), '--expect', kind)
    assert (result.returncode, result.stdout) == (0, 'valid\n'), result.stderr


def test_unresolvable_ticket_has_explicit_not_found_row():
    item = dict(reference='work:missing', title='', state='not_found', link='', latest_progress='')
    result = validate(dict(kind='ticket_status', rows=[item]))
    assert (result.returncode, result.stdout) == (0, 'valid\n')


@pytest.mark.parametrize('payload,reason', [
    ('{', 'malformed JSON'),
    ([], 'object'),
    ({'kind': 'other', 'rows': []}, 'unknown shape'),
    ({'kind': 'ticket_status'}, 'rows'),
    ({'kind': 'commitments', 'rows': {}}, 'array'),
    ({'kind': 'commitments', 'rows': [dict(reference='work:17')]}, 'title'),
    ({'kind': 'ticket_status', 'rows': [row('commitments')]}, 'latest_progress'),
    ({'kind': 'commitments', 'rows': [dict(row('commitments'), state=None)]}, 'state'),
    ({'kind': 'commitments', 'rows': [dict(row('commitments'), extra='anything')]}, 'extra'),
    ({'kind': 'commitments', 'rows': [], 'extra': {}}, 'extra'),
    ({'kind': 'error', 'reason': ''}, 'reason'),
    ({'kind': 'error', 'reason': 'offline', 'rows': []}, 'rows'),
    ('{"kind":"commitments","rows":[],"rows":[]}', 'duplicate'),
    ('{"kind":"commitments","rows":NaN}', 'malformed JSON'),
])
def test_invalid_output_is_deterministic(payload, reason):
    first = validate(payload)
    second = validate(payload)
    assert first.returncode == 1
    assert first.stdout.startswith('invalid: '), first.stderr
    assert reason in first.stdout
    assert (first.returncode, first.stdout, first.stderr) == (second.returncode, second.stdout, second.stderr)


@pytest.mark.parametrize('kind', ['ticket_status', 'commitments'])
def test_explicit_error_is_reported_as_error(kind):
    result = validate(dict(kind='error', reason='record unavailable'), '--expect', kind)
    assert (result.returncode, result.stdout) == (2, 'error: record unavailable\n')


def test_expected_response_kind_is_checked():
    result = validate(dict(kind='commitments', rows=[]), '--expect', 'ticket_status')
    assert result.returncode == 1
    assert 'expected ticket_status' in result.stdout


def compose(tmp_path, user=None, repository=None):
    args = [sys.executable, str(COMPOSER), 'plan']
    for flag, profile in [('--user-profile', user), ('--repository-profile', repository)]:
        if profile is not None:
            path = tmp_path / (flag[2:] + '.json')
            path.write_text(json.dumps(profile))
            args.extend([flag, str(path)])
    return subprocess.run(args, text=True, capture_output=True)


def test_user_record_read_binding_is_available_without_adding_a_spine_step(tmp_path):
    binding = dict(command='/read-work')
    result = compose(tmp_path, user=dict(name='user', record_read=binding))
    assert result.returncode == 0, result.stderr
    plan = json.loads(result.stdout)
    assert plan['record_read'] == binding
    assert [step['id'] for step in plan['steps']] == ['record', 'knowledge', 'lessons', 'persist', 'handoff']


def test_absent_record_read_is_explicitly_unbound(tmp_path):
    result = compose(tmp_path)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['record_read'] is None


@pytest.mark.parametrize('binding', [dict(command='/read-work'), None, {}, dict(command='/read-work', extra='x')])
def test_repository_cannot_declare_record_read_even_without_user_profile(tmp_path, binding):
    result = compose(tmp_path, repository=dict(name='repo', record_read=binding))
    assert result.returncode != 0
    assert 'record_read' in result.stderr
    assert 'repository' in result.stderr


@pytest.mark.parametrize('binding', [None, '', {}, dict(command=''), dict(command=17),
                                     dict(command='/read-work', consumes=[]), dict(command='/read-work', extra='x')])
def test_binding_has_only_a_nonempty_command(tmp_path, binding):
    result = compose(tmp_path, user=dict(name='user', record_read=binding))
    assert result.returncode != 0
    assert 'record_read' in result.stderr


@pytest.mark.parametrize('kind', ['ticket_status', 'commitments'])
@pytest.mark.parametrize('field', ['reference', 'title', 'state', 'link'])
@pytest.mark.parametrize('bad', [None, '', 7])
def test_required_row_fields_have_nonempty_text(kind, field, bad):
    item = row(kind)
    item[field] = bad
    result = validate(dict(kind=kind, rows=[item]))
    assert result.returncode == 1
    assert field in result.stdout


@pytest.mark.parametrize('item', [None, [], 'work:17'])
def test_each_row_must_be_an_object(item):
    result = validate(dict(kind='commitments', rows=[item]))
    assert result.returncode == 1
    assert 'rows[0]' in result.stdout


def test_duplicate_reference_is_not_two_pieces_of_work():
    result = validate(dict(kind='commitments', rows=[row('commitments'), row('commitments')]))
    assert result.returncode == 1
    assert 'duplicate reference' in result.stdout


def test_latest_progress_may_be_empty_but_must_be_text():
    item = dict(row('ticket_status'), latest_progress='')
    assert validate(dict(kind='ticket_status', rows=[item])).returncode == 0
    item['latest_progress'] = []
    assert validate(dict(kind='ticket_status', rows=[item])).returncode == 1


def test_binding_error_stays_one_line():
    result = validate(dict(kind='error', reason='offline\ntry later'))
    assert (result.returncode, result.stdout) == (2, 'error: offline try later\n')


def test_user_binding_survives_repository_additions(tmp_path):
    binding = dict(command='/read-work')
    result = compose(tmp_path, user=dict(name='user', record_read=binding),
                     repository=dict(name='repo', steps=[dict(id='tidy', after='persist', instructions='Tidy up')]))
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['record_read'] == binding


def test_repository_cannot_override_user_read_binding(tmp_path):
    result = compose(tmp_path, user=dict(name='user', record_read=dict(command='/read-work')),
                     repository=dict(name='repo', record_read=dict(command='/other')))
    assert result.returncode != 0
    assert 'record_read' in result.stderr


def test_markdown_user_profile_supports_the_same_binding(tmp_path):
    profile = tmp_path / 'profile.md'
    profile.write_text('# User profile\n\n```checklist-profile\n'
                       '{"name": "user", "record_read": {"command": "/read-work"}}\n```\n')
    result = subprocess.run([sys.executable, str(COMPOSER), 'plan', '--user-profile', str(profile)],
                            text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['record_read'] == dict(command='/read-work')
