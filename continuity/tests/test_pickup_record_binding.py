"""The agent receives requests, then supplies skill output for validated rendering."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
READER = ROOT / 'scripts/lib/pickup_record.py'


@pytest.fixture
def selected(tmp_path):
    handoff = json.loads((ROOT / 'docs/examples/handoff.json').read_text())
    handoff['subject']['working_directory'] = str(tmp_path)
    handoff['resume']['open_loops'].append({
        'type': 'commitment', 'context': 'Carry the work',
        'anchor': {'ticket': 'work:17'}, 'session_id': 'example-session',
        'produced_at': handoff['written_at'], 'disposition': 'verify'})
    path = tmp_path / 'handoff.json'
    path.write_text(json.dumps(handoff))
    profile = tmp_path / 'profile.md'
    profile.write_text('```checklist-profile\n' + json.dumps({
        'name': 'user', 'record_read': {'command': '/read-work'}}) + '\n```\n')
    env = dict(os.environ, CHECKLIST_USER_PROFILE=str(profile), HOME=str(tmp_path),
               XDG_CONFIG_HOME=str(tmp_path / 'xdg-config'))
    return path, handoff, env


def pickup(selected, *args):
    path, _, env = selected
    result = subprocess.run(['bash', str(ROOT / 'scripts/pickup.sh'), '--handoff', str(path), *args],
                            env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def finish(selected, report, tmp_path, ticket=None, commitments=None):
    args = []
    for kind, value in [('ticket-status', ticket), ('commitments', commitments)]:
        if value is not None:
            path = tmp_path / kind
            path.write_text(value if isinstance(value, str) else json.dumps(value))
            args += ['--' + kind, str(path)]
    result = subprocess.run([sys.executable, str(READER), *args], input=json.dumps(report),
                            env=selected[2], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def lines(report):
    return '\n'.join(row['line'] for row in report['briefing'])


def test_bound_pickup_prepares_requests_for_resumed_session_without_executing_skill(selected):
    report = pickup(selected)
    read = report['record_read']
    assert read['command'] == '/read-work'
    assert read['requests'] == {
        'ticket_status': {'kind': 'ticket_status', 'references': ['work:17']},
        'commitments': {'kind': 'commitments', 'session_id': 'example-session',
                        'repository': selected[1]['git']['repository_root'], 'handoff': selected[1]}}
    assert 'No record read is bound.' not in lines(report)
    assert 'from handoff' in lines(report)
    assert 'pending' in lines(report)


def test_validated_record_fields_and_both_commitment_sources(selected, tmp_path):
    report = pickup(selected)
    row = dict(reference='work:17', title='Carry the work', state='active',
               link='https://example.org/work/17')
    result = finish(selected, report, tmp_path,
                    dict(kind='ticket_status', rows=[dict(row, latest_progress='Contract approved')]),
                    dict(kind='commitments', rows=[row]))
    for value in [*row.values(), 'Contract approved', 'from handoff', 'from record']:
        assert value in lines(result)
    assert result['handoff'] == selected[1]
    assert all(item in result['briefing'] for item in report['briefing'] if 'record read' not in item['line'])


@pytest.mark.parametrize('response,reason', [
    ('{', 'malformed JSON'),
    ({'kind': 'error', 'reason': 'service offline'}, 'service offline'),
    ({'kind': 'ticket_status', 'rows': [{}]}, 'missing fields'),
    ({'kind': 'ticket_status', 'rows': []}, 'requested references'),
])
def test_failures_preserve_handoff_and_never_look_empty(selected, tmp_path, response, reason):
    report = pickup(selected)
    result = finish(selected, report, tmp_path, response, {'kind': 'commitments', 'rows': []})
    assert 'record read unavailable: ' in lines(result)
    assert reason in lines(result)
    assert result['resume'] == selected[1]['resume']
    assert 'ticket_status' not in result['record_read'].get('results', {})
    assert selected[1]['resume']['headline'] in lines(result)


def test_skip_commitments_survives_wrapper_and_finish(selected, tmp_path):
    report = pickup(selected, '--no-commitments')
    assert 'commitments' not in report['record_read']['requests']
    assert 'from record: skipped (--no-commitments)' in lines(report)
    result = finish(selected, report, tmp_path, {'kind': 'ticket_status', 'rows': [dict(
        reference='work:17', title='', state='not_found', link='', latest_progress='')]},
        {'kind': 'error', 'reason': 'must be ignored'})
    assert 'not_found' in lines(result)
    assert 'must be ignored' not in lines(result)
    assert 'from record: skipped (--no-commitments)' in lines(result)


def test_unreadable_profile_is_failure_not_unbound(selected):
    Path(selected[2]['CHECKLIST_USER_PROFILE']).write_text('```checklist-profile\n{\n```\n')
    assert 'record read unavailable:' in lines(pickup(selected))


@pytest.mark.parametrize('use_xdg', [False, True])
def test_default_profile_path_and_no_record_writes(selected, tmp_path, use_xdg):
    env = selected[2]
    if use_xdg:
        config_home = tmp_path / 'xdg-config'
        env['XDG_CONFIG_HOME'] = str(config_home)
    else:
        env.pop('XDG_CONFIG_HOME', None)
        config_home = tmp_path / '.config'
    configured = config_home / 'checklist/profile.md'
    configured.parent.mkdir(parents=True)
    Path(selected[2].pop('CHECKLIST_USER_PROFILE')).rename(configured)
    before = {str(p): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    assert pickup(selected)['record_read']['command'] == '/read-work'
    assert before == {str(p): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}


@pytest.mark.parametrize('response', [
    '{', {'kind': 'error', 'reason': 'service offline'},
    {'kind': 'commitments', 'rows': [{}]},
])
def test_commitment_failure_does_not_hide_valid_ticket_or_carried_items(selected, tmp_path, response):
    result = finish(selected, pickup(selected), tmp_path,
                    {'kind': 'ticket_status', 'rows': [dict(reference='work:17', title='',
                     state='not_found', link='', latest_progress='')]}, response)
    assert 'not_found' in lines(result)
    assert 'record read unavailable: commitments:' in lines(result)
    assert 'Commitments from handoff:' in lines(result)
    assert 'commitments' not in result['record_read']['results']
    assert 'Commitments from record: none' not in lines(result)


def test_missing_binding_outputs_are_unavailable(selected):
    report = pickup(selected)
    result = subprocess.run([sys.executable, str(READER), '--complete'],
                            input=json.dumps(report), env=selected[2], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    completed = json.loads(result.stdout)
    assert completed['record_read']['results'] == {}
    assert lines(completed).count('record read unavailable:') == 2
    assert 'none (validated empty response)' not in lines(completed)


def test_ticket_reference_coverage_rejects_unrequested_rows(selected, tmp_path):
    result = finish(selected, pickup(selected), tmp_path,
                    {'kind': 'ticket_status', 'rows': [dict(reference='work:missing', title='',
                     state='not_found', link='', latest_progress='')]})
    assert 'record read unavailable: ticket_status:' in lines(result)
    assert 'ticket_status' not in result['record_read']['results']


def test_explicit_missing_profile_is_unavailable(selected):
    Path(selected[2]['CHECKLIST_USER_PROFILE']).unlink()
    report = pickup(selected)
    assert 'record read unavailable: user profile:' in lines(report)
    assert 'No record read is bound.' not in lines(report)


@pytest.mark.parametrize('location', ['explicit', 'xdg', 'home'])
@pytest.mark.parametrize('profile_data', [
    {},
    {'name': 'user', 'bindings': {'record': {'command': '', 'consumes': ['progress']}}},
    {'name': 'user', 'bindings': {'unknown': None}},
    {'name': 'user', 'steps': [{'id': 'extra', 'after': 'unknown', 'instructions': 'Do work'}]},
    {'name': 'user', 'unexpected': True},
    {'name': 'user', 'record_read': {'command': '/read-work'},
     'bindings': {'record': {'command': '', 'consumes': ['progress']}}},
    {'name': 'user'},
], ids=['missing-name', 'empty-command', 'unknown-slot', 'invalid-step',
        'unknown-field', 'invalid-with-read-binding', 'valid-unbound'])
def test_checklist_profile_validation_preserves_handoff(selected, tmp_path, location, profile_data):
    env = selected[2]
    env.pop('CHECKLIST_USER_PROFILE')
    if location == 'home':
        env.pop('XDG_CONFIG_HOME')
    baseline = pickup(selected)
    handoff_rows = [row for row in baseline['briefing'] if row.get('source') != 'record_read']
    if location == 'explicit':
        profile = tmp_path / 'explicit-profile.md'
        env['CHECKLIST_USER_PROFILE'] = str(profile)
    else:
        config_home = Path(env['XDG_CONFIG_HOME']) if location == 'xdg' else tmp_path / '.config'
        profile = config_home / 'checklist/profile.md'
    profile.parent.mkdir(parents=True, exist_ok=True)
    profile.write_text('```checklist-profile\n' + json.dumps(profile_data) + '\n```\n')

    report = pickup(selected)
    assert report['handoff'] == selected[1]
    assert report['resume'] == selected[1]['resume']
    assert [row for row in report['briefing'] if row.get('source') != 'record_read'] == handoff_rows
    assert 'record_read' not in report
    assert 'Tickets from record:' not in lines(report)
    assert 'Commitments from record:' not in lines(report)
    if profile_data == {'name': 'user'}:
        assert lines(report).count('No record read is bound.') == 1
        assert 'record read unavailable:' not in lines(report)
    else:
        assert lines(report).count('record read unavailable: user profile:') == 1
        assert 'invalid' in lines(report)
        assert str(profile) in lines(report)
        assert 'No record read is bound.' not in lines(report)


@pytest.mark.parametrize('use_xdg', [False, True])
@pytest.mark.parametrize('condition', ['absent', 'dangling', 'loop', 'directory', 'invalid'])
def test_profile_diagnostics_preserve_every_handoff_section(selected, tmp_path, use_xdg, condition):
    env = selected[2]
    env['HOME'] = str(tmp_path)
    env.pop('CHECKLIST_USER_PROFILE', None)
    env.pop('XDG_CONFIG_HOME', None)
    config_home = tmp_path / '.config'
    if use_xdg:
        config_home = tmp_path / 'isolated-config'
        env['XDG_CONFIG_HOME'] = str(config_home)
    profile = config_home / 'checklist/profile.md'
    profile.parent.mkdir(parents=True)
    baseline = pickup(selected)
    handoff_rows = [row for row in baseline['briefing'] if row.get('source') != 'record_read']
    assert lines(baseline).count('No record read is bound.') == 1

    if condition == 'dangling':
        profile.symlink_to(tmp_path / 'unavailable-profile.md')
    elif condition == 'loop':
        profile.symlink_to(profile.name)
    elif condition == 'directory':
        profile.mkdir()
    elif condition == 'invalid':
        profile.write_text('```checklist-profile\n{\n```\n')
    default = pickup(selected)
    env['CHECKLIST_USER_PROFILE'] = str(profile)
    explicit = pickup(selected)

    for report in (default, explicit):
        assert report['handoff'] == selected[1]
        assert report['resume'] == selected[1]['resume']
        assert [row for row in report['briefing'] if row.get('source') != 'record_read'] == handoff_rows
        assert 'record_read' not in report
        assert 'Tickets from record:' not in lines(report)
        assert 'Commitments from record:' not in lines(report)
        if condition != 'absent' or report is explicit:
            assert lines(report).count('record read unavailable: user profile:') == 1
            if condition != 'invalid':
                assert str(profile) in lines(report)
            assert 'No record read is bound.' not in lines(report)
    if condition == 'absent':
        assert lines(default).count('No record read is bound.') == 1
    else:
        assert default['briefing'] == explicit['briefing']


@pytest.mark.parametrize('entry', [
    'default', 'external_absolute', 'external_relative', 'engine_symlink',
    'wrapper_symlink', 'direct', 'direct_symlink', 'external_direct_helper_override',
])
def test_engine_locations_reach_record_helper(selected, tmp_path, entry):
    import shutil

    wrapper = ROOT / 'scripts/pickup.sh'
    engine = ROOT / 'skills/pickup/scripts/pickup.py'
    external = tmp_path / 'external engine'
    external.mkdir()
    copied = external / 'pickup.py'
    shutil.copy2(engine, copied)
    env = dict(selected[2])
    if entry in ('external_absolute', 'external_relative', 'engine_symlink'):
        located = copied
        if entry == 'engine_symlink':
            located = tmp_path / 'engine link'
            located.symlink_to(copied)
        env['PICKUP_ENGINE'] = (os.path.relpath(located, tmp_path)
                                if entry == 'external_relative' else str(located))
    if entry == 'wrapper_symlink':
        wrapper = tmp_path / 'wrapper link'
        wrapper.symlink_to(ROOT / 'scripts/pickup.sh')
    if entry == 'direct_symlink':
        engine = tmp_path / 'direct link'
        engine.symlink_to(ROOT / 'skills/pickup/scripts/pickup.py')
    if entry == 'external_direct_helper_override':
        engine = copied
        env['PICKUP_RECORD_HELPER'] = str(READER)
    command = ([sys.executable, str(engine)] if entry in (
        'direct', 'direct_symlink', 'external_direct_helper_override') else ['bash', str(wrapper)])
    result = subprocess.run([*command, '--handoff', str(selected[0]), '--no-commitments'],
                            env=env, cwd=tmp_path, text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report['record_read']['command'] == '/read-work'
    assert report['record_read']['requests'] == {
        'ticket_status': {'kind': 'ticket_status', 'references': ['work:17']}}
    assert 'from record: skipped (--no-commitments)' in lines(report)
    assert report['handoff'] == selected[1]


@pytest.mark.parametrize('failure,reason', [
    ('missing', 'No such file'),
    ('crash', 'helper startup broke'),
    ('malformed', 'invalid JSON'),
    ('array', 'JSON object'),
])
def test_helper_failure_reports_installation_reason_not_record_outage(selected, tmp_path, failure, reason):
    helper = tmp_path / 'record helper.py'
    if failure != 'missing':
        helper.write_text({'crash': "raise RuntimeError('helper startup broke')\n",
                           'malformed': "print('not-json')\n",
                           'array': "print('[]')\n"}[failure])
    env = dict(selected[2], PICKUP_RECORD_HELPER=str(helper))
    result = subprocess.run(['bash', str(ROOT / 'scripts/pickup.sh'),
                             '--handoff', str(selected[0])],
                            env=env, text=True, capture_output=True)
    report = json.loads(result.stdout)
    assert result.returncode != 0
    assert report['error'] == 'record_helper_failed'
    assert str(helper) in report['message']
    assert reason in report['message']
    assert 'record read unavailable:' not in lines(report)
    assert 'No record read is bound.' not in lines(report)
    assert report['handoff'] == selected[1]
    assert selected[1]['resume']['headline'] in lines(report)
    assert 'Commitments from handoff:' in lines(report)
