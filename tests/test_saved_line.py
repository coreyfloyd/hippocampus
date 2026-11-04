"""Saved-state verdicts through filing, reporting, and wrap command lines."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from test_record_writes import ROOT, CLI, item, payload, row, run, store


def check(tmp_path, profile, data):
    profile_path = tmp_path / 'profile.json'
    profile_path.write_text(json.dumps(profile))
    target = tmp_path / 'handoff.json'
    env = dict(os.environ, CLAUDE_CODE_ENTRYPOINT='cli', HANDOFF_PATH=str(target),
               HANDOFF_LEDGER_DIR=str(tmp_path / 'ledger'), HANDOFF_STATE_DIR=str(tmp_path))
    data['resume'].update(headline='Finished recording work', next_action=data['resume'].get('next_action', 'Session finished.'),
                          session_summary='Recorded changes and checked saved state.')
    checkpoint = subprocess.run([sys.executable, str(ROOT / 'scripts/lib/handoff.py'), 'checkpoint',
        '--cwd', str(tmp_path), '--session-id', 'successor', '--trigger', 'wrap'],
        input=json.dumps(data), text=True, capture_output=True, env=env)
    assert checkpoint.returncode == 0, checkpoint.stderr
    results = tmp_path / 'results.json'
    results.write_text(json.dumps([dict(id=s, status='run', writes=[]) for s in
                                  ('record', 'knowledge', 'lessons', 'persist', 'handoff')]))
    summary = tmp_path / 'summary.txt'
    summary.write_text('Recorded changes and checked saved state.')
    common = ['--user-profile', str(profile_path)]
    report = subprocess.run([sys.executable, str(CLI), 'report', *common, '--handoff', str(target),
        '--results', str(results), '--summary', str(summary)], text=True, capture_output=True, env=env)
    wrap = subprocess.run([sys.executable, str(CLI), 'wrap-check', *common, '--written-handoff',
        str(target), '--record-at', '2099-01-01T00:00:00Z'], text=True, capture_output=True, env=env)
    return report, wrap


@pytest.mark.parametrize('state', ['receipt', 'reused', 'dropped', 'ask', 'unbound', 'noask',
                                   'failed', 'uncertain', 'read failed', 'pending'])
def test_saved_state_table(tmp_path, state):
    binding = store(tmp_path, {'failed': 'failed', 'uncertain': 'lost'}.get(state, 'ok'))
    profile = {'name': 'user', 'record_writes': {'documents': binding}}
    source = payload([item('Keep the complete change', record_kind='documents', disposition='File this change')])
    outcome = row()
    if state in ('ask', 'noask', 'pending'):
        source['resume']['open_loops'][0].update(type='decision', choices=['approve', 'defer'], author='user', location='session')
        outcome = dict(index=0, rule='R3', status='filed' if state == 'ask' else 'pending',
                       destination='ask receipt', error='no ask receipt')
        if state != 'noask':
            profile['ask'] = {'command': '/ask'}
    elif state == 'dropped':
        outcome = dict(index=0, rule='R6', status='dropped', reason='Already recorded')
    elif state == 'unbound':
        profile.pop('record_writes')
    elif state == 'read failed':
        outcome.update(status='read failed', error='record unavailable')
    if state == 'reused':
        assert run(tmp_path, 'record', profile, source, [outcome]).returncode == 0
    filed = run(tmp_path, 'record', profile, source, [outcome])
    data = json.loads(filed.stdout)
    report, wrap = check(tmp_path, profile, data)
    output = json.loads(report.stdout)
    failed = state in ('failed', 'uncertain', 'read failed', 'pending')
    assert report.returncode == int(failed), report.stderr
    assert wrap.returncode == int(failed), wrap.stderr
    line = output['saved_line']
    assert list(output)[-2:] == ['saved_line', 'asks']
    if failed:
        assert 'Not saved:' in line and 'Keep the complete change' in line
        assert ('record unavailable' if state == 'read failed' else
                'no ask receipt' if state == 'pending' else 'write') in line
    elif state in ('unbound', 'noask'):
        assert 'Kept:' in line and 'Keep the complete change' in line
        assert ('documents' if state == 'unbound' else 'ask') in line
        assert output['warnings']
    else:
        assert line == 'All saved and pushed'
    if state in ('ask', 'noask', 'pending'):
        assert output['asks'][0]['text'] == 'Keep the complete change'
        assert output['asks'][0]['choices'] == ['approve', 'defer']


def git(path, *args):
    return subprocess.run(['git', '-C', str(path), *args], check=True, text=True, capture_output=True)


@pytest.mark.parametrize('bound', [False, True])
@pytest.mark.parametrize('state', ['dirty', 'unpushed', 'pushed', 'no-upstream'])
def test_repository_saved_state(tmp_path, bound, state):
    repo = tmp_path / 'repository'
    repo.mkdir()
    remote = tmp_path / 'remote.git'
    subprocess.run(['git', 'init', '--bare', '-q', str(remote)], check=True)
    git(repo, 'init', '-q')
    git(repo, 'config', 'user.name', 'Test')
    git(repo, 'config', 'user.email', 'test@example.invalid')
    (repo / 'change.txt').write_text('original')
    git(repo, 'add', 'change.txt')
    git(repo, 'commit', '-qm', 'Initial')
    if state != 'no-upstream':
        git(repo, 'remote', 'add', 'origin', str(remote))
        git(repo, 'push', '-u', 'origin', 'HEAD')
    if state == 'dirty':
        (repo / 'change.txt').write_text('changed')
    elif state == 'unpushed':
        (repo / 'change.txt').write_text('changed')
        git(repo, 'commit', '-qam', 'Changed')
    ledger = tmp_path / 'ledger'
    ledger.mkdir()
    (ledger / 'session-touched-paths.successor.jsonl').write_text(json.dumps(
        dict(kind='file', session_id='successor', path=str(repo / 'change.txt'), checkout=str(repo))) + '\n')
    profile = {'name': 'user'}
    if bound:
        profile['bindings'] = {'persist': {'command': '/persist', 'consumes': []}}
    report, wrap = check(tmp_path, profile, payload([]))
    failed = bound and state != 'pushed'
    assert report.returncode == int(failed), report.stderr
    assert wrap.returncode == int(failed), wrap.stderr
    output = json.loads(report.stdout)
    if state == 'pushed':
        assert output['saved_line'] == 'All saved and pushed'
    else:
        assert str(repo) in output['saved_line']
        assert ('Not saved:' if bound else 'Not pushed:') in output['saved_line']


@pytest.mark.parametrize('status', ['pending', 'failed'])
def test_native_item_without_a_receipt_is_not_saved(tmp_path, status):
    source = payload([item('Capture the finding', disposition='Capture it')])
    source['resume']['open_loops'][0]['type'] = 'knowledge'
    filed = run(tmp_path, 'record', {'name': 'user'}, source,
                [dict(index=0, rule='R4', status=status, reason='capture unavailable')])
    report, wrap = check(tmp_path, {'name': 'user'}, json.loads(filed.stdout))
    assert report.returncode == 1
    assert wrap.returncode == 1
    line = json.loads(report.stdout)['saved_line']
    assert 'Not saved:' in line and 'Capture the finding' in line and 'capture unavailable' in line
